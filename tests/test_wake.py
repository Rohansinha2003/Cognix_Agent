import unittest

from cognix.wake import find_wake, strip_wake


class WakeTests(unittest.TestCase):
    def test_accepts_the_phrase_and_its_mishearings(self):
        cases = {
            "Hey Cognix, open the calculator.": "open the calculator",
            "Hey Cognix!": "",
            "Cognix, search my documents": "search my documents",
            "Okay Cognix, turn the volume down.": "turn the volume down",
            "Hey kognix what time is it": "what time is it",
            "hey cognics. open safari": "open safari",
            "Haykognix.": "",
            "Hey cog nix, hello": "hello",
            "Hey, Cognix. Open Safari": "Open Safari",
            "so anyway hey cognix open notes": "open notes",
            "Ok Cogniks, turn the volume down.": "turn the volume down",
        }
        for heard, command in cases.items():
            with self.subTest(heard=heard):
                match = find_wake(heard)
                self.assertIsNotNone(match)
                self.assertEqual(match.command, command)

    def test_accepts_common_whisper_mishearings_after_a_greeting(self):
        cases = {"Hey, Cognitive.": "", "Hey Cog Nick.": "", "Hey Konix": "", "Hey Conics, open safari": "open safari",
                 "Hey Connix": "", "Hey Cogs Nix, hello": "hello", "Ok Kognitiv": ""}
        for heard, command in cases.items():
            with self.subTest(heard=heard):
                match = find_wake(heard)
                self.assertIsNotNone(match)
                self.assertEqual(match.command, command)

    def test_rejects_lookalikes(self):
        for heard in [
            "Hey Siri, what time is it", "The cognitive load is high", "Can you pass me the cognac please",
            "The Cognix was off in the last batch.", "New Pass me the cognix, please.", "The cog mix was off",
            "Hey Kevin, what's going on?", "Hey cognac", "Hey cog mix", "The cognitive load", "hey connect the server", "we need to connect the phoenix server", "",
        ]:
            with self.subTest(heard=heard):
                self.assertIsNone(find_wake(heard))

    def test_strip_wake(self):
        self.assertEqual(strip_wake("Hey Cognix"), "")
        self.assertEqual(strip_wake("open notes"), "open notes")
        self.assertEqual(strip_wake("Cognix, open notes"), "open notes")


if __name__ == "__main__":
    unittest.main()
