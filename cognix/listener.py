"""Always-on microphone capture and utterance segmentation.

``Segmenter`` is a pure, testable state machine: feed it 30 ms audio frames and
it hands back complete utterances. ``MicListener`` wires a real microphone to
it on a background thread.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque

import numpy as np

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480


class Segmenter:
    """Energy-based endpointing with an adaptive noise floor.

    Speech starts when the level stays clearly above the background noise and
    ends after ``end_silence_ms`` of quiet. A short pre-roll is kept so the
    first syllable ("Hey…") is never clipped.
    """

    def __init__(
        self,
        end_silence_ms: int = 650,
        min_speech_ms: int = 240,
        max_utterance_ms: int = 15000,
        preroll_ms: int = 360,
    ):
        self.end_silence_frames = max(1, end_silence_ms // FRAME_MS)
        self.min_speech_frames = max(1, min_speech_ms // FRAME_MS)
        self.max_frames = max_utterance_ms // FRAME_MS
        self._preroll = deque(maxlen=max(1, preroll_ms // FRAME_MS))
        self._noise = 0.004          # running estimate of background RMS
        self._frames: list[np.ndarray] = []
        self._in_speech = False
        self._voiced = 0             # voiced frames in the current utterance
        self._silence = 0            # consecutive quiet frames while in speech
        self._onset = 0              # consecutive loud frames before speech starts

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def threshold(self) -> float:
        return max(0.008, self._noise * 3.2)

    def reset(self) -> None:
        self._frames = []
        self._preroll.clear()
        self._in_speech = False
        self._voiced = self._silence = self._onset = 0

    def feed(self, frame: np.ndarray) -> np.ndarray | None:
        """Process one frame; returns a finished utterance or None."""
        rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float32)))) if frame.size else 0.0
        loud = rms > self.threshold()

        if not self._in_speech:
            if loud:
                self._onset += 1
            else:
                self._onset = 0
                # Only learn the noise floor from frames we consider background.
                self._noise += (rms - self._noise) * 0.05
            self._preroll.append(frame)
            if self._onset >= 3:
                self._in_speech = True
                self._frames = list(self._preroll)
                self._preroll.clear()
                self._voiced = self._onset
                self._silence = 0
                self._onset = 0
            return None

        self._frames.append(frame)
        if loud:
            self._voiced += 1
            self._silence = 0
        else:
            self._silence += 1

        ended = self._silence >= self.end_silence_frames
        too_long = len(self._frames) >= self.max_frames
        if not (ended or too_long):
            return None

        frames, voiced = self._frames, self._voiced
        if too_long and not ended:
            # A constant loud sound (music, a fan spinning up) is the new floor.
            self._noise = max(self._noise, rms * 0.6)
        self.reset()
        if voiced < self.min_speech_frames:
            return None
        return np.concatenate(frames)


def _resample(block: np.ndarray, src_rate: float) -> np.ndarray:
    if src_rate == SAMPLE_RATE:
        return block
    n_out = int(round(len(block) * SAMPLE_RATE / src_rate))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, num=len(block), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, block).astype(np.float32)


class MicListener:
    """Streams the default microphone into a ``Segmenter`` forever.

    Callbacks (all invoked from the listener thread):
      on_utterance(audio)      a complete utterance (float32, 16 kHz mono)
      on_level(level)          0..1 loudness, ~15 times a second
      on_speech(active)        speech started / stopped
      on_status(state, detail) "listening" | "muted" | "error" | "silent"
    """

    STALL_SECONDS = 3.0   # no audio for this long means the device went away
    RETRY_SECONDS = 3.0   # pause before reopening the microphone after a failure

    def __init__(self, on_utterance, on_level=None, on_speech=None, on_status=None):
        self._on_utterance = on_utterance
        self._on_level = on_level or (lambda level: None)
        self._on_speech = on_speech or (lambda active: None)
        self._on_status = on_status or (lambda state, detail="": None)
        self._segmenter = Segmenter()
        self._queue: queue.Queue = queue.Queue(maxsize=400)
        self._enabled = threading.Event()
        self._stop = threading.Event()
        self._hold_until = 0.0       # ignore audio until this time (own voice, chimes)
        self._hold_depth = 0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.device_name = ""        # "" = automatic: the system default, skipping dead microphones
        self.active_device = ""      # the microphone currently in use
        self._skip: set = set()      # device names that delivered only silence

    # --- control ---------------------------------------------------------
    def start(self, enabled: bool = True) -> None:
        if enabled:
            self._enabled.set()
        self._thread = threading.Thread(target=self._run, name="cognix-mic", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._enabled.set()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled.set()
        else:
            self._enabled.clear()

    @property
    def enabled(self) -> bool:
        return self._enabled.is_set()

    def set_patience(self, end_silence_ms: int) -> None:
        """How long a pause ends an utterance (longer while taking a command)."""
        self._segmenter.end_silence_frames = max(1, end_silence_ms // FRAME_MS)

    def hold(self) -> None:
        """Stop hearing (Cognix is speaking). Pair with ``release``."""
        with self._lock:
            self._hold_depth += 1

    def release(self, tail: float = 0.35) -> None:
        with self._lock:
            self._hold_depth = max(0, self._hold_depth - 1)
            self._hold_until = max(self._hold_until, time.monotonic() + tail)

    def ignore_for(self, seconds: float) -> None:
        with self._lock:
            self._hold_until = max(self._hold_until, time.monotonic() + seconds)

    def _held(self) -> bool:
        with self._lock:
            return self._hold_depth > 0 or time.monotonic() < self._hold_until

    # --- capture loop ----------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._enabled.is_set():
                self._on_status("muted", "")
                self._on_level(0.0)
                self._enabled.wait()
                continue
            try:
                self._capture()
            except Exception as exc:  # device unplugged, permission denied…
                self._on_status("error", _friendly_audio_error(exc))
                self._on_level(0.0)
                self._stop.wait(self.RETRY_SECONDS)

    def set_device(self, name: str) -> None:
        """Choose a microphone by name ("" = automatic). Takes effect at the next reopen."""
        self.device_name = name
        self._skip.clear()
        self._restart = True

    def _choose_device(self, sd):
        """(index, name) of the microphone to use, or (None, "") for the system default."""
        devices = [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
        if self.device_name:
            for i, name in devices:
                if name == self.device_name:
                    return i, name
        try:
            default = sd.query_devices(kind="input")["name"]
        except Exception:
            default = ""
        ordered = sorted(devices, key=lambda d: d[1] != default)       # system default first
        for i, name in ordered:
            if name not in self._skip:
                return i, name
        return (ordered[0] if ordered else (None, ""))

    def _open_stream(self, sd, device=None):
        # PortAudio caches the device list; refresh it so a newly connected or
        # newly selected microphone is picked up whenever the stream reopens.
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass

        def callback(indata, _frames, _time, _status):
            try:
                self._queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass  # transcription fell behind; drop rather than block audio

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                blocksize=FRAME_SAMPLES, callback=callback, device=device,
            )
            return stream, float(SAMPLE_RATE)
        except Exception:
            rate = float(sd.query_devices(device, kind="input")["default_samplerate"])
            stream = sd.InputStream(
                samplerate=rate, channels=1, dtype="float32",
                blocksize=int(rate * FRAME_MS / 1000), callback=callback, device=device,
            )
            return stream, rate

    def _capture(self) -> None:
        import sounddevice as sd

        while not self._queue.empty():
            self._queue.get_nowait()
        self._segmenter.reset()
        self._restart = False
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        device, name = self._choose_device(sd)
        stream, rate = self._open_stream(sd, device)
        self.active_device = name
        pending = np.zeros(0, dtype=np.float32)
        last_level = 0.0
        smoothed = 0.0
        peak_seen = 0.0
        opened = time.monotonic()
        warned_silent = False
        was_speaking = False
        last_block = time.monotonic()

        with stream:
            self._on_status("listening", "")
            while not self._stop.is_set() and self._enabled.is_set():
                if self._restart:
                    raise RuntimeError("Switching microphone…")
                try:
                    block = self._queue.get(timeout=0.25)
                except queue.Empty:
                    # An unplugged or disconnected microphone stops calling back without an error.
                    if time.monotonic() - last_block > self.STALL_SECONDS:
                        raise RuntimeError("The microphone stopped sending audio. Reconnecting…")
                    continue
                last_block = time.monotonic()
                pending = np.concatenate([pending, _resample(block, rate)])
                while len(pending) >= FRAME_SAMPLES:
                    frame, pending = pending[:FRAME_SAMPLES], pending[FRAME_SAMPLES:]
                    peak_seen = max(peak_seen, float(np.max(np.abs(frame))))

                    if self._held():
                        if self._segmenter.in_speech or was_speaking:
                            self._segmenter.reset()
                            was_speaking = False
                            self._on_speech(False)
                        continue

                    utterance = self._segmenter.feed(frame)
                    speaking = self._segmenter.in_speech
                    if speaking != was_speaking:
                        was_speaking = speaking
                        self._on_speech(speaking)
                    if utterance is not None:
                        self._on_utterance(utterance)

                    rms = float(np.sqrt(np.mean(frame * frame)))
                    level = min(1.0, max(0.0, (rms - 0.004) * 9.0)) ** 0.6
                    smoothed += (level - smoothed) * (0.55 if level > smoothed else 0.18)

                now = time.monotonic()
                if now - last_level >= 0.066:
                    last_level = now
                    self._on_level(0.0 if self._held() else smoothed)
                # A dead microphone (muted earbuds, denied permission) delivers near-silence.
                dead = peak_seen < 0.0006
                if dead and now - opened > 4.0 and not warned_silent:
                    if not self.device_name and name not in self._skip:
                        self._skip.add(name)               # try the next microphone instead
                        raise RuntimeError("Switching microphone…")
                    warned_silent = True
                    self._on_status("silent", "")
                elif warned_silent and not dead:
                    warned_silent = False
                    self._on_status("listening", "")
        self._on_speech(False)


def _friendly_audio_error(exc: Exception) -> str:
    text = str(exc)
    if "No Default Input Device" in text or "Error querying device -1" in text:
        return "No microphone found. Connect one and Cognix will pick it up."
    if "stopped sending audio" in text or "Switching microphone" in text:
        return text
    return f"Microphone problem: {text}"
