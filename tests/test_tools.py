import os
import tempfile
import time
import unittest
from pathlib import Path

from cognix import mac, tools


class ValidationTests(unittest.TestCase):
    def test_coerces_and_checks_arguments(self):
        tool = tools.get("set_volume")
        self.assertEqual(tools.validate(tool, {"level": "40", "mute": "true"}), ({"level": 40, "mute": True}, ""))
        self.assertTrue(tools.validate(tool, {"level": "loud"})[1])
        self.assertTrue(tools.validate(tools.get("open_app"), {})[1])
        self.assertTrue(tools.validate(tools.get("media_control"), {"action": "explode"})[1])
        self.assertTrue(tools.validate(tool, "not a dict")[1])

    def test_execute_never_raises(self):
        self.assertFalse(tools.execute("no_such_tool", {}).ok)
        self.assertFalse(tools.execute("open_app", {}).ok)
        self.assertFalse(tools.execute("open_path", {"path": "/nonexistent/file.pdf"}).ok)

    def test_schemas_render_for_both_apis(self):
        claude, openai = tools.claude_tools(), tools.openai_tools()
        self.assertEqual(len(claude), len(openai))
        self.assertTrue(all("input_schema" in t and t["input_schema"]["type"] == "object" for t in claude))
        self.assertTrue(all(t["type"] == "function" for t in openai))


class QuickIntentTests(unittest.TestCase):
    def test_obvious_commands_run_without_a_model(self):
        self.assertEqual(tools.quick_intent("Open the Calculator app.")[:2], ("open_app", {"name": "calculator"}))
        self.assertEqual(tools.quick_intent("please open safari")[0], "open_app")
        self.assertEqual(tools.quick_intent("search for flights to Tokyo")[:2],
                         ("search_in_browser", {"query": "flights to Tokyo"}))
        self.assertEqual(tools.quick_intent("set the volume to fifty percent")[1], {"level": 50})
        self.assertEqual(tools.quick_intent("volume down")[1], {"change": -15})
        self.assertEqual(tools.quick_intent("take a screenshot")[0], "take_screenshot")

    def test_file_and_folder_opening_needs_no_model(self):
        self.assertEqual(tools.quick_intent("open the folder Research on desktop")[:2],
                         ("open_best", {"query": "research", "kind": "folder", "folder": "desktop"}))
        self.assertEqual(tools.quick_intent("open downloads")[0], "open_best")
        self.assertEqual(tools.quick_intent("find my passport scan")[0], "find_files")

    def test_open_ended_requests_go_to_the_model(self):
        for text in ["search my documents for budget", "what's the weather", "summarise the lease pdf"]:
            with self.subTest(text=text):
                self.assertIsNone(tools.quick_intent(text))


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "Q3 Budget Review.pdf").write_bytes(b"%PDF-1.4\n")
        (root / "notes.md").write_text("# Meeting notes\nReview budget\n" + "x" * 3000)
        (root / "holiday.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
        (root / ".env").write_text("SECRET=1")
        (root / "sub").mkdir()
        (root / "sub" / "old budget.pdf").write_bytes(b"%PDF-1.4\n")
        os.utime(root / "sub" / "old budget.pdf", (time.time() - 86400 * 30,) * 2)
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_by_name_newest_first(self):
        result = mac.find_files("budget", folder=str(self.root))
        self.assertTrue(result.ok)
        self.assertEqual([i["name"] for i in result.items], ["Q3 Budget Review.pdf", "old budget.pdf"])
        self.assertIn("Found 2 files", result.title)

    def test_find_by_kind(self):
        result = mac.find_files("", kind="pdf", folder=str(self.root))
        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.title, "Found 2 PDFs")
        self.assertEqual(mac.find_files("", kind="image", folder=str(self.root)).items[0]["name"], "holiday.png")

    def test_find_nothing(self):
        result = mac.find_files("zzzqqq", folder=str(self.root))
        self.assertTrue(result.ok)
        self.assertEqual(result.items, [])

    def test_read_text_in_pages(self):
        first = mac.read_file(str(self.root / "notes.md"), max_chars=500)
        self.assertTrue(first.ok)
        self.assertIn("Meeting notes", first.text)
        self.assertIn("offset=500", first.text)
        second = mac.read_file(str(self.root / "notes.md"), offset=500, max_chars=60000)
        self.assertNotIn("There is more", second.text)

    def test_refuses_secrets_and_binaries(self):
        self.assertFalse(mac.read_file(str(self.root / ".env")).ok)
        self.assertFalse(mac.read_file(str(self.root / "holiday.png")).ok)
        self.assertTrue(mac.is_sensitive(Path.home() / ".ssh" / "config"))

    def test_list_folder_hides_dotfiles(self):
        names = [i["name"] for i in mac.list_folder(str(self.root)).items]
        self.assertIn("notes.md", names)
        self.assertNotIn(".env", names)

    def test_resolve_path(self):
        self.assertEqual(mac.resolve_path("Downloads"), Path.home() / "Downloads")
        self.assertEqual(mac.resolve_path("my downloads folder"), Path.home() / "Downloads")
        self.assertEqual(mac.resolve_path("Desktop/report.pdf"), Path.home() / "Desktop" / "report.pdf")
        self.assertEqual(mac.resolve_path("~/x"), Path.home() / "x")

    def test_only_surfaced_paths_are_openable(self):
        result = tools.execute("find_files", {"query": "budget", "folder": str(self.root)})
        self.assertTrue(tools.is_known_path(result.items[0]["path"]))
        self.assertFalse(tools.is_known_path("/etc/passwd"))


class AppTests(unittest.TestCase):
    def test_finds_apps_loosely_but_not_wildly(self):
        self.assertEqual(mac.find_app("calculator").name, "Calculator.app")
        self.assertEqual(mac.find_app("the Calculator app").name, "Calculator.app")
        self.assertEqual(mac.find_app("calculater").name, "Calculator.app")
        self.assertIsNone(mac.find_app("calculater", strict=True))
        self.assertIsNone(mac.find_app("definitely not an app xyz"))

    def test_only_web_addresses_count_as_urls(self):
        self.assertEqual(mac._web_url("youtube.com"), "https://youtube.com")
        self.assertEqual(mac._web_url("http://localhost:3000/x"), "http://localhost:3000/x")
        self.assertEqual(mac._web_url("example.com:8080"), "https://example.com:8080")
        for bad in ["file:///etc/passwd", "javascript:alert(1)", "mailto:a@b.com", "not a url", "",
                    "https://exa mple.com", "--help"]:
            with self.subTest(url=bad):
                self.assertIsNone(mac._web_url(bad))
                self.assertFalse(mac.open_url(bad).ok)


if __name__ == "__main__":
    unittest.main()
