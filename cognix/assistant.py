"""The conductor: microphone → wake word → transcription → brain → speech.

Phases the UI can show:
  starting   loading the speech model
  idle       listening for "Hey Cognix" (everything else is discarded unheard)
  listening  awake and waiting for a command
  thinking   working on a request
  speaking   reading the reply aloud
  muted      microphone off — typing still works
"""

from __future__ import annotations

import itertools
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from . import __version__, config, discovery, mac, tools
from .brain import BrainError, Cancelled, ClaudeBrain, LocalBrain, TurnIO, local_status
from .events import EventBus
from .listener import MicListener
from .speech import Speaker, list_voices, play_chime
from .stt import Transcriber
from .wake import WAKE_PHRASE, find_wake, strip_wake

MAX_WAKE_SECONDS = 8.0     # while asleep, speech longer than this is ignored without being transcribed
AWAKE_SECONDS = 8.0        # how long Cognix waits for a command after the wake phrase
FOLLOW_UP_SECONDS = 6.0    # ...and after a reply, when follow-up listening is on
IDLE_PATIENCE_MS = 700     # pause that ends an utterance while waiting for the wake phrase
AWAKE_PATIENCE_MS = 1000   # a little more room to think mid-command
NEW_CHAT_AFTER = 20 * 60   # seconds of quiet before context is dropped
MAX_ENTRIES = 300

_DISMISSALS = {"never mind", "nevermind", "cancel", "stop", "nothing", "forget it", "no", "go away"}


class _Turn(TurnIO):
    """Routes one request's streamed text and tool activity to the UI and the speaker."""

    def __init__(self, owner: "Assistant"):
        super().__init__()
        self._owner = owner
        self._entry = None      # the assistant message currently being written
        self.spoken = []        # every text segment, for the transcript

    def text(self, delta: str) -> None:
        owner = self._owner
        if self._entry is None:
            self._entry = owner._add_entry(kind="assistant", text="", streaming=True)
            owner._set_phase("speaking")
        self._entry["text"] += delta
        owner.bus.emit("delta", id=self._entry["id"], text=delta)
        owner.speaker.feed(delta)

    def _close_text(self) -> None:
        if self._entry is None:
            return
        entry, self._entry = self._entry, None
        entry["streaming"] = False
        entry["text"] = entry["text"].strip()
        self.spoken.append(entry["text"])
        self._owner.bus.emit("entry", entry=dict(entry))
        self._owner.speaker.flush()

    def tool_start(self, call_id, name, args, label, icon) -> None:
        self._close_text()
        self._owner._set_phase("thinking")
        detail = next((str(v) for k, v in args.items() if k in ("name", "query", "path", "url") and v), "")
        self._owner._add_entry(kind="tool", id=f"tool-{call_id}", name=name, title=label, icon=icon,
                               detail=detail, status="running", items=[])

    def tool_end(self, call_id, result) -> None:
        self._owner._update_entry(f"tool-{call_id}", status="done" if result.ok else "error",
                                  title=result.title or None, items=result.items,
                                  detail="" if result.items or result.title else None)

    def finish(self) -> str:
        self._close_text()
        return " ".join(s for s in self.spoken if s)


class Assistant:
    def __init__(self, settings: config.Settings, bus: EventBus):
        self.settings = settings
        self.bus = bus
        self._ids = itertools.count(1)
        self._lock = threading.RLock()

        self._phase = "starting"
        self._phase_detail = ""
        self._mic = {"state": "starting", "detail": ""}
        self._stt = {"state": "loading", "detail": ""}
        self._local = {"ok": False, "models": []}
        self._local_started = 0.0       # when we last tried to launch Bionic ourselves
        self._entries: list = []
        self._transcript: list = []     # plain-text turns, used to seed a brain after an engine switch
        self._last_activity = time.monotonic()

        self.speaker = Speaker()
        self._sync_speaker()
        self.transcriber = Transcriber(settings.get("stt_model"))
        self.listener = MicListener(self._on_utterance, self._on_level, self._on_speech, self._on_mic_status)
        self._brains = {"local": LocalBrain(settings), "claude": ClaudeBrain(settings)}
        self._brain_engine = None       # which brain currently holds the conversation

        self._audio_q: queue.Queue = queue.Queue(maxsize=8)
        self._turn_q: queue.Queue = queue.Queue()
        self._turn_active = threading.Event()
        self._current: _Turn | None = None
        self._awake_until = 0.0
        self._speech_active = False
        self._speech_awake = False      # the utterance in progress began while awake
        self._transcribing = False
        self._volume_warned = False
        self._closing = threading.Event()
        self._voices: list = []

    # ------------------------------------------------------------------ lifecycle
    def start(self, microphone: bool = True) -> None:
        """Start the worker threads. ``microphone=False`` skips audio capture (used by tests)."""
        for target, name in ((self._stt_loop, "cognix-stt"), (self._turn_loop, "cognix-turns"),
                             (self._watch_local, "cognix-local-watch")):
            threading.Thread(target=target, name=name, daemon=True).start()
        self._voices = list_voices()
        self.listener.device_name = self.settings.get("mic_device")
        if microphone:
            self.listener.start(enabled=self.settings.get("mic_enabled"))
        else:
            self._mic = {"state": "listening", "detail": ""}

    def shutdown(self) -> None:
        self._closing.set()
        self.stop()
        self.listener.shutdown()
        self._audio_q.put(None)

    # ------------------------------------------------------------------ state for the UI
    def snapshot(self, include_entries: bool = True) -> dict:
        s = self.settings.snapshot()
        local_models = self._local["models"]
        data = {
            "version": __version__,
            "wake_phrase": WAKE_PHRASE,
            "phase": self._phase,
            "detail": self._phase_detail,
            "mic": dict(self._mic),
            "stt": dict(self._stt),
            "settings": s,
            "local": {"ok": self._local["ok"], "models": local_models,
                      "server": discovery.label_for(s["local_url"]),
                      "model": (s["local_model"] if s["local_model"] in local_models
                                else (local_models[0] if local_models else ""))},
            "claude": {"ready": config.claude_credentials_available(), "has_saved_key": bool(config.get_api_key()),
                       "models": config.CLAUDE_MODELS},
            "voices": self._voices,
            "mic_devices": _input_devices(),
            "mic_active": self.listener.active_device,
            "stt_models": config.STT_MODELS,
        }
        if include_entries:
            with self._lock:
                data["entries"] = [dict(e) for e in self._entries]
        return data

    def _emit_status(self) -> None:
        self.bus.emit("status", status=self.snapshot(include_entries=False))

    def _set_phase(self, phase: str, detail: str = "") -> None:
        if (phase, detail) == (self._phase, self._phase_detail):
            return
        self._phase, self._phase_detail = phase, detail
        self.bus.emit("phase", phase=phase, detail=detail)

    def _resting_phase(self) -> None:
        """Pick the right quiet state once nothing is happening."""
        if self._turn_active.is_set():
            return
        if self._stt["state"] != "ready":
            self._set_phase("starting", self._stt["detail"])
        elif not self.settings.get("mic_enabled") or self._mic["state"] in ("error", "silent", "muted"):
            self._set_phase("muted", self._mic["detail"])
        elif self._is_awake():
            self._set_phase("listening")
        else:
            self._set_phase("idle")

    def _add_entry(self, **entry) -> dict:
        entry.setdefault("id", f"e{next(self._ids)}")
        entry["time"] = datetime.now().strftime("%H:%M")
        with self._lock:
            self._entries.append(entry)
            del self._entries[:-MAX_ENTRIES]
        # Emit a copy: the entry keeps changing while the UI thread serialises the event.
        self.bus.emit("entry", entry=dict(entry))
        return entry

    def _update_entry(self, entry_id: str, **changes) -> None:
        with self._lock:
            entry = next((e for e in reversed(self._entries) if e["id"] == entry_id), None)
            if entry is None:
                return
            entry.update({k: v for k, v in changes.items() if v is not None})
            snapshot = dict(entry)
        self.bus.emit("entry", entry=snapshot)

    def _notice(self, text: str, level: str = "error") -> None:
        self._add_entry(kind="notice", level=level, text=text)

    # ------------------------------------------------------------------ microphone callbacks
    def _is_awake(self) -> bool:
        return time.monotonic() < self._awake_until

    def _on_mic_status(self, state: str, detail: str = "") -> None:
        if state == "silent":
            detail = ("The microphone is sending silence. Allow microphone access for the app running Cognix "
                      "in System Settings → Privacy & Security → Microphone, then restart Cognix.")
        changed = (state, detail) != (self._mic["state"], self._mic["detail"])
        self._mic = {"state": state, "detail": detail}
        if changed:
            self._emit_status()
            self._resting_phase()

    def _on_speech(self, active: bool) -> None:
        self._speech_active = active
        if active:
            self._speech_awake = self._is_awake()
        self.bus.emit("hearing", active=active)

    def _on_level(self, level: float) -> None:
        self.bus.emit("level", v=round(level, 3))
        # This fires ~15×/s, which makes it a convenient clock for the awake timeout.
        if (self._awake_until and not self._is_awake() and not self._speech_active
                and not self._transcribing and self._audio_q.empty() and not self._turn_active.is_set()):
            self._sleep()

    def _on_utterance(self, audio) -> None:
        awake = self._speech_awake or self._is_awake()
        self._speech_awake = False
        if not awake and len(audio) > MAX_WAKE_SECONDS * 16000:
            return  # conversation, TV, music: far too long to be "Hey Cognix, …", so it is not even transcribed
        try:
            self._audio_q.put_nowait((audio, awake))
        except queue.Full:
            pass

    def _wake(self, chime: bool = True, seconds: float = AWAKE_SECONDS) -> None:
        self._awake_until = time.monotonic() + seconds
        self.listener.set_patience(AWAKE_PATIENCE_MS)
        if chime and self.settings.get("chime"):
            play_chime("Pop")
        self._set_phase("listening")

    def _sleep(self) -> None:
        self._awake_until = 0.0
        self.listener.set_patience(IDLE_PATIENCE_MS)
        self._resting_phase()

    # ------------------------------------------------------------------ speech → text
    def _load_stt(self) -> None:
        name = self.settings.get("stt_model")
        repo = "models--Systran--faster-whisper-" + name
        cached = (Path.home() / ".cache/huggingface/hub" / repo).exists()
        detail = "Loading the speech model…" if cached else (
            "Downloading the speech model (one time, about 150 MB)…")
        self._stt = {"state": "loading", "detail": detail}
        self._emit_status()
        self._resting_phase()
        try:
            self.transcriber = Transcriber(name)
            self.transcriber.load()
            self._stt = {"state": "ready", "detail": ""}
        except Exception as exc:
            self._stt = {"state": "error", "detail": f"The speech model could not be loaded: {exc}"}
            self._notice(self._stt["detail"] + " Typing still works.")
        self._emit_status()
        self._resting_phase()

    def _stt_loop(self) -> None:
        self._load_stt()
        while not self._closing.is_set():
            item = self._audio_q.get()
            if item is None:
                return
            if item == "reload":
                self._load_stt()
                continue
            audio, awake = item
            if self._turn_active.is_set() or not self.transcriber.ready:
                continue
            self._transcribing = True
            try:
                if awake:
                    self._set_phase("thinking", "Transcribing")
                text = self.transcriber.transcribe(audio)
                self._heard(text, awake)
            except Exception as exc:
                self._notice(f"Speech recognition failed: {exc}")
                self._sleep()
            finally:
                self._transcribing = False

    def _heard(self, text: str, awake: bool) -> None:
        if awake:
            command = strip_wake(text)
            if not command:
                pass                               # just noise, or the wake phrase again: keep waiting, window unchanged
            elif command.lower().strip(" .!?") in _DISMISSALS:
                self._sleep()
            else:
                self._begin_turn(command, "voice")
            return
        match = find_wake(text)
        if match is None:
            return  # not addressed to Cognix: dropped here, never shown, stored or sent anywhere
        if match.command:
            self._begin_turn(match.command, "voice")
        else:
            self._wake()

    # ------------------------------------------------------------------ public controls
    def send_text(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._begin_turn(text[:8000], "text")

    def wake(self) -> None:
        """Same as saying the wake phrase (the orb was clicked)."""
        if self._turn_active.is_set():
            self.stop()
        elif self._is_awake():
            self._sleep()
        elif self._stt["state"] == "ready" and self.settings.get("mic_enabled"):
            self._wake()

    def stop(self) -> None:
        """Stop talking and abandon the current request."""
        while True:
            try:
                self._turn_q.get_nowait()
            except queue.Empty:
                break
        current = self._current
        if current is not None:
            current.cancelled.set()
        self.speaker.stop()
        if not self._turn_active.is_set():
            self._sleep()

    def new_conversation(self) -> None:
        self.stop()
        with self._lock:
            self._entries.clear()
            self._transcript.clear()
        for brain in self._brains.values():
            brain.reset()
        self._brain_engine = None
        self.bus.emit("cleared")

    def apply_settings(self, changes: dict) -> None:
        applied = self.settings.update(changes)
        if not applied:
            return
        if "mic_enabled" in applied:
            self.listener.set_enabled(applied["mic_enabled"])
            if not applied["mic_enabled"]:
                self._awake_until = 0.0
        if {"speak", "voice", "rate"} & applied.keys():
            self._sync_speaker()
            if applied.get("speak") is False:
                self.speaker.stop()
        if "mic_device" in applied:
            self.listener.set_device(applied["mic_device"])
        if "stt_model" in applied:
            self._audio_q.put("reload")
        if "local_url" in applied:
            self._local = local_status(self.settings.get("local_url"))
        self._emit_status()
        self._resting_phase()

    def set_api_key(self, key: str) -> None:
        config.set_api_key(key)
        self._emit_status()

    def preview_voice(self) -> None:
        if not self._turn_active.is_set():
            self.speaker.stop()
            was, self.speaker.enabled = self.speaker.enabled, True
            self.speaker.say("Hi, I'm Cognix. This is how I sound.")
            self.speaker.enabled = was

    def open_item(self, path: str, reveal: bool = False) -> bool:
        """Open something a tool surfaced earlier (the UI cannot open arbitrary paths)."""
        if not tools.is_known_path(path):
            return False
        if path.startswith(("http://", "https://")):
            return mac.open_url(path).ok
        return mac.open_path(path, reveal=reveal).ok

    def _sync_speaker(self) -> None:
        self.speaker.enabled = self.settings.get("speak")
        self.speaker.voice = self.settings.get("voice")
        self.speaker.rate = self.settings.get("rate")

    # ------------------------------------------------------------------ handling a request
    def _begin_turn(self, text: str, source: str) -> None:
        self._awake_until = 0.0
        self.listener.set_patience(IDLE_PATIENCE_MS)
        self._turn_q.put((text, source))

    def _turn_loop(self) -> None:
        while not self._closing.is_set():
            text, source = self._turn_q.get()
            self._turn_active.set()
            self.listener.hold()          # never listen to our own voice
            try:
                self._run_turn(text, source)
            except Exception as exc:      # last line of defence: keep the loop alive
                self._notice(f"Something went wrong: {type(exc).__name__}: {exc}")
            finally:
                self._current = None
                self.speaker.flush()
                self.speaker.wait()
                self.listener.release(tail=0.4)
                self._turn_active.clear()
                self._last_activity = time.monotonic()
                if self._turn_q.empty():
                    if (source == "voice" and self.settings.get("follow_up")
                            and self.settings.get("mic_enabled")):
                        self._wake(chime=False, seconds=FOLLOW_UP_SECONDS)
                    else:
                        self._resting_phase()

    def _brain(self):
        """The brain for the selected engine, carrying the conversation across a switch."""
        engine = self.settings.get("engine")
        stale = time.monotonic() - self._last_activity > NEW_CHAT_AFTER
        if stale:
            self._transcript.clear()
        brain = self._brains[engine]
        if engine != self._brain_engine or stale or len(brain.messages) > 80:
            brain.reset(self._transcript[-12:])
            self._brain_engine = engine
        return brain

    def _run_turn(self, text: str, source: str) -> None:
        self._add_entry(kind="user", text=text, source=source)
        self._log("user", text)
        self._set_phase("thinking")
        self._warn_if_silent_output()
        turn = self._current = _Turn(self)
        brain = self._brain()
        reply = ""
        try:
            quick = tools.quick_intent(text)
            if quick:
                name, args, say = quick
                tool = tools.get(name)
                call_id = f"q{next(self._ids)}"
                turn.tool_start(call_id, name, args, tool.doing, tool.icon)
                result = tools.execute(name, args)
                turn.tool_end(call_id, result)
                spoken = say if result.ok else (result.title or result.text)
                if spoken:
                    turn.text(spoken)
                reply = turn.finish() or result.title
                brain.messages.append({"role": "user", "content": text})
                brain.messages.append({"role": "assistant", "content": reply or "Done."})
            else:
                brain.respond(text, turn)
                reply = turn.finish()
        except Cancelled:
            reply = turn.finish()
            self.speaker.stop()
        except BrainError as exc:
            reply = turn.finish()
            message = str(exc)
            if message:
                self._notice(message)
                self.speaker.say(message)
        if reply:
            self._log("assistant", reply)
            self._transcript.append({"role": "user", "text": text})
            self._transcript.append({"role": "assistant", "text": reply})
            del self._transcript[:-40]

    def _warn_if_silent_output(self) -> None:
        if not self.settings.get("speak"):
            return
        volume = mac.get_volume()
        if volume == 0 and not self._volume_warned:
            self._volume_warned = True
            self._notice("Your Mac's volume is at zero, so you won't hear my replies.", level="info")
        elif volume:
            self._volume_warned = False

    def _log(self, role: str, text: str) -> None:
        if not self.settings.get("save_history"):
            return
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(config.HISTORY_FILE, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"),
                                         "role": role, "text": text}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ LM Studio watcher
    def _watch_local(self) -> None:
        while not self._closing.is_set():
            status = local_status(self.settings.get("local_url"))
            if self.settings.get("local_auto") and not (status["ok"] and status["models"]):
                status = self._find_local(status)
            if status != self._local:
                self._local = status
                self._emit_status()
            self._closing.wait(5.0)

    def _find_local(self, current: dict) -> dict:
        """Look for Bionic, LM Studio or another local server; start Bionic if none is running."""
        url, found = discovery.detect(self.settings.get("local_url"), local_status)
        if not url and self.settings.get("engine") == "local" and discovery.can_start() \
                and time.monotonic() - self._local_started > 600:
            self._local_started = time.monotonic()
            self._notice("Starting Bionic's local server…", "info")
            if discovery.start_server():
                url, found = discovery.detect(self.settings.get("local_url"), local_status)
        if url and url != self.settings.get("local_url"):
            self.settings.update({"local_url": url})
        return found if url else current

def _input_devices() -> list:
    try:
        import sounddevice as sd

        return sorted({d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0})
    except Exception:
        return []
