"""End-to-end voice tests: synthesized speech goes through the real pipeline —
endpointing, on-device Whisper, wake matching, the brain and the tools.

They need macOS (`say`, `afconvert`) and the Whisper model, so they are skipped
elsewhere. Nothing is played aloud and the microphone is not used.
"""

import shutil
import subprocess
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from cognix import config
from cognix.assistant import Assistant
from cognix.events import EventBus
from cognix.listener import FRAME_SAMPLES, SAMPLE_RATE, Segmenter
from cognix.mac import ToolResult
from tests.fake_llm import FakeLLM

HAVE_SAY = bool(shutil.which("say") and shutil.which("afconvert"))
RNG = np.random.default_rng(7)


def speak(text: str, voice: str = "Samantha") -> np.ndarray:
    """Synthesize speech to a float32 16 kHz array."""
    with tempfile.TemporaryDirectory() as tmp:
        aiff, wav = Path(tmp) / "s.aiff", Path(tmp) / "s.wav"
        subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1",
                        str(aiff), str(wav)], check=True)
        with wave.open(str(wav)) as handle:
            pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768


def room(seconds: float) -> np.ndarray:
    """Quiet room tone."""
    return (RNG.standard_normal(int(seconds * SAMPLE_RATE)) * 0.0015).astype(np.float32)


def segment(audio: np.ndarray, segmenter: Segmenter | None = None) -> list:
    segmenter = segmenter or Segmenter()
    found = []
    for start in range(0, len(audio) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
        utterance = segmenter.feed(audio[start:start + FRAME_SAMPLES])
        if utterance is not None:
            found.append(utterance)
    return found


class SegmenterTests(unittest.TestCase):
    def test_silence_and_clicks_produce_nothing(self):
        audio = room(3)
        audio[16000:16000 + 400] += 0.5          # a 25 ms click
        self.assertEqual(segment(audio), [])

    def test_tone_bursts_become_utterances_with_preroll(self):
        t = np.arange(int(0.9 * SAMPLE_RATE)) / SAMPLE_RATE
        burst = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        audio = np.concatenate([room(1), burst, room(1.2), burst, room(1.2)]) + room(5.2)[: int(5.2 * SAMPLE_RATE)]
        found = segment(audio)
        self.assertEqual(len(found), 2)
        for utterance in found:
            self.assertGreater(len(utterance), len(burst))                    # pre-roll + trailing pause kept
            self.assertLess(len(utterance), len(burst) + 1.2 * SAMPLE_RATE)

    def test_endless_noise_is_cut_and_becomes_the_floor(self):
        loud = (RNG.standard_normal(SAMPLE_RATE * 20) * 0.1).astype(np.float32)
        segmenter = Segmenter(max_utterance_ms=5000)
        found = segment(np.concatenate([room(1), loud]), segmenter)
        self.assertLessEqual(len(found), 2)       # adapts instead of cutting forever
        self.assertGreater(segmenter.threshold(), 0.1)


@unittest.skipUnless(HAVE_SAY, "needs macOS speech synthesis")
class VoicePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def script(messages):
            last = messages[-1]
            if last["role"] == "tool":
                return {"text": "It is just after midnight."}
            if "time" in str(last["content"]).lower():
                return {"tool": "system_info", "args": {}}
            return {"text": "Okay."}

        cls.llm = FakeLLM(script).start()
        cls.tmp = tempfile.mkdtemp()
        settings = config.Settings(Path(cls.tmp) / "config.json")
        settings.update({"local_auto": False, "local_url": cls.llm.url, "speak": False, "chime": False, "save_history": False})
        cls.bus = EventBus()
        cls.events = cls.bus.subscribe()
        cls.assistant = Assistant(settings, cls.bus)
        cls.assistant.start(microphone=False)
        deadline = time.time() + 180                       # first run downloads the speech model
        while cls.assistant._stt["state"] == "loading" and time.time() < deadline:
            time.sleep(0.1)
        if cls.assistant._stt["state"] != "ready":
            raise unittest.SkipTest("speech model unavailable")

    @classmethod
    def tearDownClass(cls):
        cls.assistant.shutdown()
        cls.llm.stop()

    def setUp(self):
        self.assistant.new_conversation()
        self.wait_idle()

    def hear(self, audio: np.ndarray) -> None:
        """Play audio into the assistant exactly as the microphone thread would."""
        segmenter = self.assistant.listener._segmenter
        was = False
        for start in range(0, len(audio) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
            utterance = segmenter.feed(audio[start:start + FRAME_SAMPLES])
            if segmenter.in_speech != was:
                was = segmenter.in_speech
                self.assistant._on_speech(was)
            if utterance is not None:
                self.assistant._on_utterance(utterance)

    def wait_idle(self, timeout: float = 20) -> None:
        deadline = time.time() + timeout
        time.sleep(0.15)
        a = self.assistant
        while time.time() < deadline:
            if (not a._turn_active.is_set() and a._turn_q.empty() and a._audio_q.empty()
                    and not a._transcribing):
                return
            time.sleep(0.05)
        self.fail("assistant did not settle")

    def entries(self, kind=None):
        return [e for e in self.assistant.snapshot()["entries"] if kind in (None, e["kind"])]

    def test_wake_phrase_and_command_in_one_breath(self):
        self.hear(np.concatenate([room(0.8), speak("Hey Cognix, what time is it?"), room(1.5)]))
        self.wait_idle()
        user = self.entries("user")
        self.assertEqual(len(user), 1)
        self.assertEqual(user[0]["source"], "voice")
        self.assertIn("what time is it", user[0]["text"].lower())
        self.assertNotIn("cognix", user[0]["text"].lower())
        tool = self.entries("tool")[0]
        self.assertEqual((tool["name"], tool["status"]), ("system_info", "done"))
        self.assertEqual(self.entries("assistant")[-1]["text"], "It is just after midnight.")
        self.assertEqual(self.assistant.snapshot()["phase"], "idle")

    def test_speech_not_addressed_to_cognix_is_dropped(self):
        self.hear(np.concatenate([room(0.8), speak("I think we should open the calculator and check the numbers."),
                                  room(1.5), speak("Hey Siri, what time is it?", "Daniel"), room(1.5)]))
        self.wait_idle()
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.assistant.snapshot()["phase"], "idle")

    def test_wake_phrase_then_command_after_a_pause(self):
        self.hear(np.concatenate([room(0.8), speak("Hey Cognix."), room(1.4)]))
        self.wait_idle()
        self.assertEqual(self.assistant.snapshot()["phase"], "listening")
        self.assertEqual(self.entries(), [])
        self.hear(np.concatenate([speak("What time is it right now?"), room(1.6)]))
        self.wait_idle()
        self.assertIn("what time is it", self.entries("user")[0]["text"].lower())
        self.assertEqual(self.entries("assistant")[-1]["text"], "It is just after midnight.")

    def test_awake_state_times_out_back_to_idle(self):
        self.hear(np.concatenate([room(0.5), speak("Hey Cognix."), room(1.4)]))
        self.wait_idle()
        self.assertEqual(self.assistant.snapshot()["phase"], "listening")
        self.assistant._awake_until = time.monotonic() - 0.01     # fast-forward the 8 s window
        self.assistant._on_level(0.0)
        self.assertEqual(self.assistant.snapshot()["phase"], "idle")

    def test_other_accents(self):
        for voice in ("Daniel", "Rishi", "Karen"):
            with self.subTest(voice=voice):
                self.assistant.new_conversation()
                self.hear(np.concatenate([room(0.6), speak("Hey Cognix, what time is it?", voice), room(1.5)]))
                self.wait_idle()
                self.assertEqual(len(self.entries("user")), 1, f"{voice}: wake phrase missed")

    def test_typed_request_and_streamed_events(self):
        while not self.events.empty():
            self.events.get_nowait()
        self.assistant.send_text("what time is it")
        self.wait_idle()
        kinds = []
        while not self.events.empty():
            event = self.events.get_nowait()
            kinds.append(event["type"] if event["type"] != "phase" else f"phase:{event['phase']}")
        self.assertIn("phase:thinking", kinds)
        self.assertIn("delta", kinds)
        self.assertEqual(kinds[-1], "phase:idle")
        self.assertEqual(self.entries("user")[0]["source"], "text")

    def test_model_offline_gives_a_spoken_style_notice(self):
        self.assistant.apply_settings({"local_url": "http://127.0.0.1:9/v1"})
        try:
            self.assistant.send_text("tell me a joke")
            self.wait_idle()
            self.assertIn("Bionic", self.entries("notice")[0]["text"])
        finally:
            self.assistant.apply_settings({"local_url": self.llm.url})

    def test_instant_command_works_with_no_model(self):
        self.assistant.apply_settings({"local_url": "http://127.0.0.1:9/v1"})
        done = ToolResult(True, "Volume set to 30%.", "Volume 30%")
        try:
            with mock.patch("cognix.mac.set_volume", return_value=done) as set_volume:
                self.assistant.send_text("Set the volume to 30.")
                self.wait_idle()
            set_volume.assert_called_once_with(30, None, None)
            self.assertEqual(self.entries("tool")[0]["title"], "Volume 30%")
            self.assertEqual(self.entries("assistant")[0]["text"], "Volume at 30 percent.")
            self.assertEqual(self.entries("notice"), [])
        finally:
            self.assistant.apply_settings({"local_url": self.llm.url})


if __name__ == "__main__":
    unittest.main()
