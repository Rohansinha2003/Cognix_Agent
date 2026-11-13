import threading
import time
import unittest
from unittest import mock

from cognix import speech


class FakeSay:
    """Stands in for the `say` process: records what would be spoken, takes a moment, can be killed."""

    spoken: list = []
    commands: list = []

    def __init__(self, cmd, **_):
        FakeSay.commands.append(cmd)
        self._done = threading.Event()
        self.stdin = mock.Mock()
        self.stdin.write.side_effect = lambda data: FakeSay.spoken.append(data.decode())

    def wait(self):
        self._done.wait(0.05)

    def poll(self):
        return 0 if self._done.is_set() else None

    def terminate(self):
        self._done.set()


class SpeakableTests(unittest.TestCase):
    def test_strips_markup(self):
        self.assertEqual(speech.speakable("**Done.** See `notes.md` and [the docs](https://x.y/z)."),
                         "Done. See notes.md and the docs.")
        self.assertEqual(speech.speakable("- one\n- two"), "one two")
        self.assertIn("code shown on screen", speech.speakable("Run:\n```\nls -la\n```"))
        self.assertEqual(speech.speakable("Visit https://example.com/a?b=1 now"), "Visit the link now")


class SpeakerTests(unittest.TestCase):
    def setUp(self):
        FakeSay.spoken, FakeSay.commands = [], []
        patcher = mock.patch("cognix.speech.subprocess.Popen", FakeSay)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.speaker = speech.Speaker()

    def test_speaks_sentence_by_sentence_as_text_streams(self):
        for piece in ["Opened ", "it. Here is", " the rest", " of the reply"]:
            self.speaker.feed(piece)
        time.sleep(0.02)
        self.assertEqual(FakeSay.spoken, ["Opened it."])       # spoken before the reply finished
        self.speaker.flush()
        self.assertTrue(self.speaker.wait(2))
        self.assertEqual(FakeSay.spoken, ["Opened it.", "Here is the rest of the reply"])

    def test_text_is_passed_on_stdin_with_voice_and_rate(self):
        self.speaker.voice, self.speaker.rate = "Samantha", 200
        self.speaker.say("-v Trinoids is not an option")
        self.assertTrue(self.speaker.wait(2))
        self.assertEqual(FakeSay.commands[0], ["say", "-r", "200", "-v", "Samantha", "-f", "-"])
        self.assertEqual(FakeSay.spoken, ["-v Trinoids is not an option"])

    def test_stop_drops_everything_queued(self):
        for n in range(20):
            self.speaker.say(f"Sentence {n}.")
        time.sleep(0.02)
        self.speaker.stop()
        self.assertTrue(self.speaker.wait(2))
        self.assertLess(len(FakeSay.spoken), 4)
        self.speaker.say("Back again.")
        self.assertTrue(self.speaker.wait(2))
        self.assertEqual(FakeSay.spoken[-1], "Back again.")

    def test_disabled_speaker_stays_silent(self):
        self.speaker.enabled = False
        self.speaker.feed("Hello there. ")
        self.speaker.flush()
        self.assertTrue(self.speaker.wait(1))
        self.assertEqual(FakeSay.spoken, [])


if __name__ == "__main__":
    unittest.main()
