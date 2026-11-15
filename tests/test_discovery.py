import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cognix import discovery


def status_for(up: dict):
    return lambda url: up.get(url, {"ok": False, "models": []})


class DiscoveryTests(unittest.TestCase):
    def test_configured_port_comes_first_after_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.json"
            cfg.write_text(json.dumps({"port": 4321}))
            with mock.patch.object(discovery, "SERVER_CONFIG", cfg):
                urls = discovery.candidate_urls("http://127.0.0.1:9/v1")
        self.assertEqual(urls[:2], ["http://127.0.0.1:9/v1", "http://127.0.0.1:4321/v1"])
        self.assertIn("http://127.0.0.1:11434/v1", urls)
        self.assertEqual(len(urls), len(set(urls)))

    def test_missing_or_bad_config_is_ignored(self):
        with mock.patch.object(discovery, "SERVER_CONFIG", Path("/nonexistent/x.json")):
            self.assertIsNone(discovery.configured_port())

    def test_detect_prefers_a_server_with_models(self):
        up = {"http://127.0.0.1:1234/v1": {"ok": True, "models": []},
              "http://127.0.0.1:11434/v1": {"ok": True, "models": ["llama"]}}
        with mock.patch.object(discovery, "SERVER_CONFIG", Path("/nonexistent/x.json")):
            url, status = discovery.detect("", status_for(up))
        self.assertEqual(url, "http://127.0.0.1:11434/v1")
        self.assertEqual(status["models"], ["llama"])

    def test_detect_falls_back_to_an_empty_server_then_nothing(self):
        with mock.patch.object(discovery, "SERVER_CONFIG", Path("/nonexistent/x.json")):
            up = {"http://127.0.0.1:1234/v1": {"ok": True, "models": []}}
            self.assertEqual(discovery.detect("", status_for(up))[0], "http://127.0.0.1:1234/v1")
            self.assertEqual(discovery.detect("", status_for({})), ("", {"ok": False, "models": []}))


if __name__ == "__main__":
    unittest.main()
