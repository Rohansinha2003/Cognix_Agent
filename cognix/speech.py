"""Text-to-speech using the voices built into macOS (``say``).

Replies are spoken sentence by sentence as they stream in, so Cognix starts
talking while the model is still writing.
"""

from __future__ import annotations

import queue
import re
import subprocess
import threading

_SENTENCE_END = re.compile(r"(?<=[.!?。])[\"')\]]?\s+|\n+")
_URL = re.compile(r"https?://\S+")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_SYMBOLS = re.compile(r"[*_#`>|~]+")


def speakable(text: str) -> str:
    """Strip markup that a speech synthesiser would read out literally."""
    text = _CODE_BLOCK.sub(" (code shown on screen) ", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("the link", text)
    text = _SYMBOLS.sub(" ", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def list_voices() -> list[dict]:
    """Installed system voices as ``{"name", "lang"}``."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    voices = []
    for line in out.splitlines():
        match = re.match(r"^(.+?)\s{2,}([a-z]{2}_[A-Z0-9]{2,3})\s", line)
        if match:
            voices.append({"name": match.group(1).strip(), "lang": match.group(2)})
    return voices


class Speaker:
    """A queue of sentences spoken one after another on a worker thread."""

    def __init__(self, on_start=None, on_stop=None):
        self._on_start = on_start or (lambda: None)
        self._on_stop = on_stop or (lambda: None)
        self._queue: queue.Queue = queue.Queue()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._generation = 0       # bumped by stop(): drops everything queued
        self._buffer = ""
        self._active = False
        self._pending = 0          # sentences queued or being spoken
        self._idle = threading.Event()
        self._idle.set()
        self.voice = ""
        self.rate = 185
        self.enabled = True
        threading.Thread(target=self._run, name="cognix-tts", daemon=True).start()

    # --- feeding text ------------------------------------------------------
    def feed(self, text: str) -> None:
        """Add streamed text; complete sentences are spoken immediately."""
        if not self.enabled:
            return
        self._buffer += text
        while True:
            match = _SENTENCE_END.search(self._buffer)
            if not match:
                break
            sentence, self._buffer = self._buffer[: match.end()], self._buffer[match.end():]
            self._enqueue(sentence)

    def flush(self) -> None:
        """Speak whatever is left in the buffer (end of a reply)."""
        rest, self._buffer = self._buffer, ""
        self._enqueue(rest)

    def say(self, text: str) -> None:
        if self.enabled:
            self._enqueue(text)

    def _enqueue(self, text: str) -> None:
        text = speakable(text)
        if text and self.enabled:
            with self._lock:
                self._pending += 1
                self._idle.clear()
                self._queue.put((self._generation, text))

    # --- control -----------------------------------------------------------
    def stop(self) -> None:
        """Stop talking right now and forget anything queued."""
        with self._lock:
            self._generation += 1
            proc = self._proc
        self._buffer = ""
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def wait(self, timeout: float | None = None) -> bool:
        """Block until everything queued has been spoken."""
        return self._idle.wait(timeout)

    @property
    def speaking(self) -> bool:
        return not self._idle.is_set()

    # --- worker ------------------------------------------------------------
    def _run(self) -> None:
        while True:
            generation, text = self._queue.get()
            if generation == self._generation:
                if not self._active:
                    self._active = True
                    self._on_start()
                self._speak(generation, text)
            with self._lock:
                self._pending -= 1
                finished = self._pending == 0
                if finished:
                    self._idle.set()   # under the lock, so a sentence queued right now is not missed
            if finished and self._active:
                self._active = False
                self._on_stop()

    def _speak(self, generation: int, text: str) -> None:
        cmd = ["say", "-r", str(int(self.rate))]
        if self.voice:
            cmd += ["-v", self.voice]
        # Text goes through stdin so a reply starting with "-" is never read as an option.
        cmd += ["-f", "-"]
        try:
            with self._lock:
                if generation != self._generation:
                    return
                self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                proc = self._proc
            proc.stdin.write(text.encode("utf-8"))
            proc.stdin.close()
            proc.wait()
        except OSError:
            pass
        finally:
            with self._lock:
                self._proc = None


def play_chime(name: str = "Pop") -> None:
    """Play a short system sound without blocking."""
    try:
        subprocess.Popen(
            ["afplay", "-v", "0.6", f"/System/Library/Sounds/{name}.aiff"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
