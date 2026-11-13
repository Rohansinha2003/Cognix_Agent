import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from cognix import config
from cognix.brain import BrainError, Cancelled, ClaudeBrain, LocalBrain, TagFilter, TurnIO, local_status
from tests.fake_claude import FakeClaude
from tests.fake_llm import FakeLLM


class Recorder(TurnIO):
    def __init__(self):
        super().__init__()
        self.said, self.started, self.ended = [], [], []

    def text(self, delta):
        self.said.append(delta)

    def tool_start(self, call_id, name, args, label, icon):
        self.started.append((name, args))

    def tool_end(self, call_id, result):
        self.ended.append(result)

    @property
    def reply(self):
        return "".join(self.said).strip()


def settings(**values):
    tmp = tempfile.mkdtemp()
    s = config.Settings(Path(tmp) / "config.json")
    s.update(values)
    return s


class TagFilterTests(unittest.TestCase):
    def feed(self, chunks):
        f = TagFilter()
        return "".join(f.feed(c) for c in chunks) + f.flush(), f

    def test_hides_thinking_even_when_split_across_chunks(self):
        out, _ = self.feed(["<thi", "nk>secret plan</th", "ink>Hello", " there"])
        self.assertEqual(out, "Hello there")

    def test_keeps_ordinary_angle_brackets(self):
        out, _ = self.feed(["2 < 3 and <b>bold</b>"])
        self.assertEqual(out, "2 < 3 and <b>bold</b>")

    def test_captures_text_tool_calls(self):
        out, f = self.feed(['Sure. <tool_call>{"name": "system_info", "arguments": {}}</tool_call>'])
        self.assertEqual(out, "Sure. ")
        self.assertEqual(len(f.tool_calls), 1)


class LocalBrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / "resume final.pdf").write_bytes(b"%PDF-1.4\n")

    def tearDown(self):
        self.tmp.cleanup()

    def script(self, messages):
        last = messages[-1]
        if last["role"] == "tool":
            return {"text": "Found your resume." if "resume final.pdf" in last["content"] else "Nothing found."}
        return {"tool": "find_files", "args": {"query": "resume", "folder": self.tmp.name}}

    def test_tool_round_trip(self):
        llm = FakeLLM(self.script).start()
        try:
            brain, io = LocalBrain(settings(local_url=llm.url)), Recorder()
            brain.respond("find my resume", io)
            self.assertEqual(io.reply, "Found your resume.")
            self.assertEqual(io.started[0][0], "find_files")
            self.assertTrue(io.ended[0].ok)
            self.assertEqual([m["role"] for m in brain.messages], ["user", "assistant", "tool", "assistant"])
            self.assertEqual(llm.requests[0]["model"], "fake-model")          # skipped the embedding model
            self.assertEqual(llm.requests[0]["messages"][0]["role"], "system")
            self.assertTrue(llm.requests[0]["tools"])
        finally:
            llm.stop()

    def test_falls_back_to_plain_chat_when_tools_are_rejected(self):
        llm = FakeLLM(lambda m: {"text": "Plain answer."}, reject_tools=True).start()
        try:
            brain, io = LocalBrain(settings(local_url=llm.url)), Recorder()
            brain.respond("hello", io)
            self.assertEqual(io.reply, "Plain answer.")
            self.assertNotIn("tools", llm.requests[-1])
        finally:
            llm.stop()

    def test_cancel_rolls_history_back(self):
        llm = FakeLLM(lambda m: {"text": "one two three four five six seven eight"}, delay=0.05).start()
        try:
            brain, io = LocalBrain(settings(local_url=llm.url)), Recorder()
            threading.Timer(0.15, io.cancelled.set).start()
            with self.assertRaises(Cancelled):
                brain.respond("talk for a while", io)
            self.assertEqual(brain.messages, [])
        finally:
            llm.stop()

    def test_server_down_is_a_friendly_error(self):
        brain = LocalBrain(settings(local_url="http://127.0.0.1:9/v1"))
        with self.assertRaises(BrainError) as ctx:
            brain.respond("hello", Recorder())
        self.assertIn("LM Studio", str(ctx.exception))
        self.assertEqual(local_status("http://127.0.0.1:9/v1"), {"ok": False, "models": []})


class ClaudeBrainTests(unittest.TestCase):
    """Drives the real Anthropic SDK against a local mock of the Messages API."""

    def run_brain(self, script, text="what's in my downloads", **overrides):
        server = FakeClaude(script).start()
        env = {"ANTHROPIC_API_KEY": "test-key", "ANTHROPIC_BASE_URL": server.url}
        try:
            with mock.patch.dict(os.environ, env), mock.patch.object(config, "get_api_key", return_value=""):
                brain, io = ClaudeBrain(settings(**overrides)), Recorder()
                error = None
                try:
                    brain.respond(text, io)
                except BrainError as exc:
                    error = exc
                return brain, io, server, error
        finally:
            server.stop()

    def test_tool_round_trip_and_request_shape(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "invoice.pdf").write_bytes(b"%PDF-1.4\n")

        def script(body):
            last = body["messages"][-1]
            if isinstance(last["content"], list) and last["content"][0]["type"] == "tool_result":
                return {"text": "You have one invoice."}
            return {"text": "Let me look.", "tool": "find_files", "args": {"query": "invoice", "folder": tmp}}

        brain, io, server, error = self.run_brain(script)
        self.assertIsNone(error)
        self.assertEqual(io.reply, "Let me look. You have one invoice.")
        self.assertEqual(io.started, [("find_files", {"query": "invoice", "folder": tmp})])
        self.assertEqual(len(io.ended[0].items), 1)

        first, second = server.requests
        self.assertEqual(first["model"], "claude-opus-5-5")
        self.assertEqual(first["output_config"], {"effort": "low"})
        self.assertEqual(first["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", server.headers[0]["anthropic-beta"])
        self.assertEqual(first["system"][0]["cache_control"], {"type": "ephemeral"})
        names = [t["name"] for t in first["tools"]]
        self.assertIn("find_files", names)
        self.assertEqual(first["tools"][-1], {"type": "web_search_20260209", "name": "web_search", "max_uses": 4})
        self.assertNotIn("thinking", first)
        self.assertNotIn("temperature", first)
        # The follow-up echoes the assistant turn and returns the result in one user message.
        self.assertEqual([m["role"] for m in second["messages"]], ["user", "assistant", "user"])
        self.assertEqual(second["messages"][1]["content"][-1]["type"], "tool_use")
        result = second["messages"][2]["content"][0]
        self.assertEqual((result["type"], result["is_error"]), ("tool_result", False))
        self.assertIn("invoice.pdf", result["content"])
        self.assertEqual(len(brain.messages), 4)

    def test_haiku_gets_no_fallback_and_basic_search(self):
        _, io, server, _ = self.run_brain(lambda b: {"text": "Hi."}, claude_model="claude-haiku-5-5")
        self.assertEqual(io.reply, "Hi.")
        self.assertNotIn("fallbacks", server.requests[0])
        self.assertEqual(server.requests[0]["tools"][-1]["type"], "web_search_20250305")

    def test_web_search_can_be_switched_off(self):
        _, _, server, _ = self.run_brain(lambda b: {"text": "Hi."}, claude_web_search=False)
        self.assertNotIn("web_search", [t["name"] for t in server.requests[0]["tools"]])

    def test_refusal_is_spoken_and_not_remembered(self):
        brain, io, _, error = self.run_brain(lambda b: {"refuse": True})
        self.assertEqual(io.reply, "Sorry, I can't help with that.")
        self.assertEqual(str(error), "")
        self.assertEqual(brain.messages, [])

    def test_bad_key_is_a_friendly_error(self):
        brain, _, _, error = self.run_brain(lambda b: {"status": 401})
        self.assertIn("API key", str(error))
        self.assertEqual(brain.messages, [])

    def test_no_credentials(self):
        with mock.patch.object(config, "claude_credentials_available", return_value=False):
            with self.assertRaises(BrainError) as ctx:
                ClaudeBrain(settings()).respond("hi", Recorder())
        self.assertIn("API key", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
