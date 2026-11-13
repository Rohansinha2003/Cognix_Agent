"""On-device speech-to-text with faster-whisper.

Audio never leaves the machine: the Whisper model is downloaded once
(~150 MB for ``base.en``) and runs locally from then on.
"""

from __future__ import annotations

import re
import threading

import numpy as np

from .listener import SAMPLE_RATE

# Names Whisper should know how to spell. Phrased as a glossary on purpose:
# a prompt that *ends* with the wake phrase makes Whisper drop it from the
# transcript, while a glossary lifts "Cognix" recognition from ~50% to ~99%.
VOCABULARY_PROMPT = "Glossary: Cognix, Safari, Finder, PDF."

_JUNK = re.compile(r"^[\s.\-–—…,!?\[\]()♪*]*$")
# Phrases Whisper invents for breaths, clicks and room noise.
_HALLUCINATIONS = {
    "you", "thank you", "thanks for watching", "thank you for watching", "bye",
    "glossary cognix safari finder pdf",
}


class Transcriber:
    def __init__(self, model_name: str = "base.en"):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load (downloading on first use) the Whisper model. Slow; call off the UI thread."""
        with self._lock:
            if self._model is not None:
                return
            import logging

            import ctranslate2
            from faster_whisper import WhisperModel

            ctranslate2.set_log_level(logging.ERROR)  # keep its hardware tips out of the terminal
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe one utterance; returns "" for silence or noise."""
        self.load()
        if audio.size < SAMPLE_RATE // 5:
            return ""
        language = "en" if self.model_name.endswith(".en") else None
        with self._lock:
            segments, _info = self._model.transcribe(
                audio.astype(np.float32, copy=False),
                language=language,
                beam_size=1,
                condition_on_previous_text=False,
                vad_filter=True,
                initial_prompt=VOCABULARY_PROMPT,
            )
            parts = [
                seg.text.strip()
                for seg in segments
                if seg.no_speech_prob < 0.8 and seg.avg_logprob > -1.3
            ]
        text = " ".join(p for p in parts if p).strip()
        if _JUNK.match(text):
            return ""
        if re.sub(r"[^a-z ]", "", text.lower()).strip() in _HALLUCINATIONS:
            return ""
        return text
