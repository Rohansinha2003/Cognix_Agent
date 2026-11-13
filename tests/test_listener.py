import sys
import threading
import time
import types
import unittest
from unittest import mock

import numpy as np

from cognix.listener import FRAME_SAMPLES, MicListener


class FakeStream:
    """A microphone that delivers `blocks` frames of tone, then goes quiet as if unplugged."""

    opened = 0

    def __init__(self, callback, blocks, **_):
        FakeStream.opened += 1
        self._callback, self._blocks = callback, blocks
        self._alive = threading.Event()

    def __enter__(self):
        self._alive.set()
        threading.Thread(target=self._pump, daemon=True).start()
        return self

    def __exit__(self, *_):
        self._alive.clear()

    def _pump(self):
        t = np.arange(FRAME_SAMPLES) / 16000
        frame = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32).reshape(-1, 1)
        for _ in range(self._blocks):
            if not self._alive.is_set():
                return
            self._callback(frame, FRAME_SAMPLES, None, None)
            time.sleep(0.002)


def fake_sounddevice(blocks, fail_open=0):
    module = types.ModuleType("sounddevice")
    state = {"failures": fail_open}

    def input_stream(callback=None, **kwargs):
        if state["failures"] > 0:
            state["failures"] -= 1
            raise RuntimeError("Error querying device -1")
        return FakeStream(callback, blocks)

    module.InputStream = input_stream
    module._terminate = module._initialize = lambda: None
    mic = {"default_samplerate": 16000.0, "name": "Fake Mic", "max_input_channels": 1}
    module.query_devices = lambda device=None, kind=None: mic if (kind or device is not None) else [mic]
    return module


class MicListenerTests(unittest.TestCase):
    def run_listener(self, module, seconds):
        FakeStream.opened = 0
        statuses, levels, utterances = [], [], []
        listener = MicListener(utterances.append, levels.append, None, lambda s, d="": statuses.append((s, d)))
        listener.STALL_SECONDS, listener.RETRY_SECONDS = 0.3, 0.1
        with mock.patch.dict(sys.modules, {"sounddevice": module}):
            listener.start()
            time.sleep(seconds)
            listener.shutdown()
            time.sleep(0.4)
        return statuses, levels, utterances

    def test_reopens_a_microphone_that_stops_sending_audio(self):
        statuses, levels, _ = self.run_listener(fake_sounddevice(blocks=40), seconds=1.6)
        states = [s for s, _ in statuses]
        self.assertEqual(states[:3], ["listening", "error", "listening"])
        self.assertIn("stopped sending audio", statuses[1][1])
        self.assertGreaterEqual(FakeStream.opened, 2)
        self.assertGreater(max(levels), 0.5)              # the tone registered on the meter

    def test_missing_microphone_is_reported_then_recovered(self):
        statuses, _, _ = self.run_listener(fake_sounddevice(blocks=400, fail_open=2), seconds=1.0)
        self.assertEqual(statuses[0][0], "error")
        self.assertIn("No microphone found", statuses[0][1])
        self.assertEqual(statuses[-1][0], "listening")

    def test_muting_stops_capture_and_unmuting_resumes(self):
        FakeStream.opened = 0
        statuses = []
        listener = MicListener(lambda a: None, None, None, lambda s, d="": statuses.append(s))
        with mock.patch.dict(sys.modules, {"sounddevice": fake_sounddevice(blocks=100000)}):
            listener.start()
            time.sleep(0.3)
            listener.set_enabled(False)
            time.sleep(0.5)
            listener.set_enabled(True)
            time.sleep(0.4)
            listener.shutdown()
            time.sleep(0.4)
        self.assertEqual(statuses[:3], ["listening", "muted", "listening"])
        self.assertEqual(FakeStream.opened, 2)

    def test_held_audio_is_ignored(self):
        utterances = []
        listener = MicListener(utterances.append)
        listener.hold()
        with mock.patch.dict(sys.modules, {"sounddevice": fake_sounddevice(blocks=100000)}):
            listener.start()
            time.sleep(0.6)
            listener.shutdown()
            time.sleep(0.4)
        self.assertEqual(utterances, [])
        self.assertFalse(listener._segmenter.in_speech)


if __name__ == "__main__":
    unittest.main()
