import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from cognix import config
from cognix.assistant import Assistant
from cognix.events import EventBus
from cognix.server import CognixServer


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = config.Settings(Path(tempfile.mkdtemp()) / "config.json")
        settings.update({"speak": False, "save_history": False})
        cls.assistant = Assistant(settings, EventBus())    # not started: no mic, no model
        cls.server = CognixServer(cls.assistant, cls.assistant.bus)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def call(self, path, body=None, token=None, host=None):
        request = urllib.request.Request(self.server.url.rstrip("/") + path,
                                         data=None if body is None else json.dumps(body).encode())
        if token:
            request.add_header("X-Cognix-Token", token)
        if host:
            request.add_header("Host", host)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_page_carries_the_token_and_a_csp(self):
        status, body = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn(self.server.token.encode(), body)
        self.assertNotIn(b"__COGNIX_TOKEN__", body)

    def test_api_requires_the_token(self):
        self.assertEqual(self.call("/api/state")[0], 401)
        self.assertEqual(self.call("/api/stop", {})[0], 401)
        self.assertEqual(self.call("/api/stop", {}, token="wrong")[0], 401)
        self.assertEqual(self.call("/events")[0], 401)
        self.assertEqual(self.call("/api/state", token=self.server.token)[0], 200)

    def test_foreign_host_header_is_refused(self):
        self.assertEqual(self.call("/", host="evil.example")[0], 403)
        self.assertEqual(self.call("/api/state", token=self.server.token, host="evil.example:80")[0], 403)

    def test_static_files_cannot_escape_the_web_folder(self):
        self.assertEqual(self.call("/../config.py")[0], 404)
        self.assertEqual(self.call("/%2e%2e/config.py")[0], 404)

    def test_settings_round_trip_and_validation(self):
        token = self.server.token
        self.call("/api/settings", {"changes": {"rate": 220, "engine": "nonsense", "bogus": 1}}, token=token)
        state = json.loads(self.call("/api/state", token=token)[1])
        self.assertEqual(state["settings"]["rate"], 220)
        self.assertEqual(state["settings"]["engine"], "local")
        self.assertNotIn("bogus", state["settings"])

    def test_open_refuses_paths_no_tool_surfaced(self):
        status, body = self.call("/api/open", {"path": "/etc/passwd"}, token=self.server.token)
        self.assertEqual((status, json.loads(body)), (200, {"ok": False}))

    def test_unknown_action_and_bad_json(self):
        self.assertEqual(self.call("/api/nope", {}, token=self.server.token)[0], 404)
        request = urllib.request.Request(self.server.url + "api/stop", data=b"{not json",
                                         headers={"X-Cognix-Token": self.server.token})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
