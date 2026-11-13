"""The tools Cognix can use, described once and served to any model.

``TOOLS`` is the single source of truth: ``claude_tools()`` and
``openai_tools()`` render it for the two APIs, ``execute()`` validates the
model's arguments and runs the tool, and ``quick_intent()`` recognises the
handful of commands that are obvious enough to run without a model at all.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable

from . import mac
from .mac import ToolResult


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: dict            # JSON-schema "properties"
    required: tuple
    run: Callable
    doing: str              # shown in the UI while it runs
    icon: str = "spark"


def _s(desc: str, **extra) -> dict:
    return {"type": "string", "description": desc, **extra}


def _i(desc: str) -> dict:
    return {"type": "integer", "description": desc}


def _b(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


TOOLS: list[Tool] = [
    Tool(
        "open_app",
        "Open (or bring to the front) an application installed on this Mac. Names are matched loosely, "
        "so pass what the user said, e.g. 'chrome', 'vs code', 'calculator'.",
        {"name": _s("The app's name as the user said it.")}, ("name",),
        lambda name: mac.open_app(name), "Opening app", "app",
    ),
    Tool(
        "quit_app",
        "Quit a running application. The app can still ask the user to save unsaved work.",
        {"name": _s("Name of the running app to quit.")}, ("name",),
        lambda name: mac.quit_app(name), "Quitting app", "app",
    ),
    Tool(
        "find_files",
        "Search the user's files with Spotlight and return the newest matches with full paths. Use this "
        "whenever the user refers to a file or folder without giving an exact path ('my resume', 'the budget "
        "spreadsheet', 'latest PDF in Downloads'), then pass a returned path to open_path or read_file. "
        "Leave query empty to list the most recent files of a kind.",
        {
            "query": _s("Words that appear in the file name. Use the distinctive words only ('resume', "
                        "'q3 budget'), not filler like 'file' or 'my'."),
            "kind": _s("Restrict to a type of file.", enum=mac.FILE_KINDS),
            "folder": _s("Where to look: 'Desktop', 'Documents', 'Downloads', 'Pictures', 'iCloud' or a path. "
                         "Defaults to the whole home folder."),
            "content": _b("Also match words inside documents, not just file names."),
            "limit": _i("How many results to return (default 8, maximum 25)."),
        }, (),
        lambda query="", kind="any", folder="", content=False, limit=8:
            mac.find_files(query, kind, folder, content, limit),
        "Searching files", "search",
    ),
    Tool(
        "open_best",
        "Find a file or folder by name and open it in one step. Use for 'open the folder X', 'open my "
        "resume'. If several match it returns the list instead of opening.",
        {"query": _s("Distinctive words in the name, or a well-known folder like 'Downloads'."),
         "kind": _s("Type of item.", enum=mac.FILE_KINDS),
         "folder": _s("Where to look, e.g. 'Desktop'. Defaults to the home folder.")}, ("query",),
        lambda query, kind="any", folder="": mac.open_best(query, kind, folder), "Opening", "file",
    ),
    Tool(
        "open_path",
        "Open a file or folder with its default app (PDFs open in Preview, folders in Finder), with a "
        "specific app, or reveal it in Finder. Needs a real path — get one from find_files first.",
        {
            "path": _s("Absolute path, ~/path, or a well-known folder name such as 'Downloads'."),
            "app": _s("Optional app to open it with, e.g. 'Preview' or 'Chrome'."),
            "reveal": _b("Show the item selected in Finder instead of opening it."),
        }, ("path",),
        lambda path, app="", reveal=False: mac.open_path(path, app, reveal), "Opening", "file",
    ),
    Tool(
        "read_file",
        "Read the text of a file so you can answer questions about it or summarise it. Works for text and "
        "code files, PDFs, Word and RTF documents. Long files come back in pages; follow the offset in the "
        "result to keep reading.",
        {
            "path": _s("Path of the file to read (from find_files)."),
            "offset": _i("Character offset to start from (default 0)."),
            "max_chars": _i("Maximum characters to return (default 12000)."),
        }, ("path",),
        lambda path, offset=0, max_chars=12000: mac.read_file(path, offset, max_chars), "Reading", "file",
    ),
    Tool(
        "list_folder",
        "List what is inside a folder, most recently changed first.",
        {"path": _s("Folder path or name such as 'Desktop' or 'Downloads'."),
         "limit": _i("How many entries to return (default 30).")}, ("path",),
        lambda path, limit=30: mac.list_folder(path, limit), "Looking in folder", "folder",
    ),
    Tool(
        "search_in_browser",
        "Open the user's web browser on a search results page. Use this when the user asks to search or "
        "look something up 'on the web', 'on Google' or 'in the browser' and wants to see the results.",
        {"query": _s("The search query.")}, ("query",),
        lambda query: mac.search_in_browser(query), "Searching the web", "globe",
    ),
    Tool(
        "open_url",
        "Open a web page in the user's default browser.",
        {"url": _s("The address, e.g. 'youtube.com' or 'https://example.com/page'.")}, ("url",),
        lambda url: mac.open_url(url), "Opening page", "globe",
    ),
    Tool(
        "set_volume",
        "Change the Mac's sound volume: set an exact level, nudge it up or down, or mute/unmute.",
        {"level": _i("Exact volume from 0 to 100."),
         "change": _i("Relative change, e.g. 15 for louder or -15 for quieter."),
         "mute": _b("true to mute, false to unmute.")}, (),
        lambda level=None, change=None, mute=None: mac.set_volume(level, change, mute),
        "Adjusting volume", "volume",
    ),
    Tool(
        "media_control",
        "Control music playback in Spotify or Apple Music.",
        {"action": _s("What to do.", enum=["play_pause", "next", "previous"])}, ("action",),
        lambda action: mac.media_control(action), "Controlling playback", "music",
    ),
    Tool(
        "system_info",
        "Get the current date and time, battery level, volume, free disk space, appearance and which apps "
        "are open. Call this for any question about the time, date or state of the Mac.",
        {}, (), lambda: mac.system_info(), "Checking the system", "chip",
    ),
    Tool(
        "set_dark_mode",
        "Switch macOS between dark and light appearance.",
        {"enabled": _b("true for dark mode, false for light mode.")}, ("enabled",),
        lambda enabled: mac.set_dark_mode(enabled), "Changing appearance", "moon",
    ),
    Tool(
        "take_screenshot",
        "Capture the whole screen to a PNG on the Desktop.",
        {}, (), lambda: mac.take_screenshot(), "Taking a screenshot", "camera",
    ),
    Tool(
        "clipboard",
        "Read the text currently on the clipboard, or copy new text to it.",
        {"action": _s("read or write.", enum=["read", "write"]),
         "text": _s("Text to copy when action is write.")}, ("action",),
        lambda action, text="": mac.clipboard(action, text), "Using the clipboard", "clipboard",
    ),
    Tool(
        "run_shortcut",
        "Run one of the user's own Shortcuts (from the macOS Shortcuts app) by name. Use it when the user "
        "asks for a shortcut by name, or for an action no other tool covers.",
        {"name": _s("Name of the shortcut.")}, ("name",),
        lambda name: mac.run_shortcut(name), "Running shortcut", "bolt",
    ),
    Tool(
        "sleep_display",
        "Turn the display off (the Mac locks if the user requires a password after sleep).",
        {}, (), lambda: mac.sleep_display(), "Sleeping the display", "moon",
    ),
]

_BY_NAME = {tool.name: tool for tool in TOOLS}


def get(name: str) -> Tool | None:
    return _BY_NAME.get(name)


def _schema(tool: Tool) -> dict:
    return {"type": "object", "properties": tool.params, "required": list(tool.required)}


def claude_tools() -> list:
    """Tool definitions in Anthropic Messages API format."""
    return [
        {"name": t.name, "description": t.description, "input_schema": _schema(t),
         "eager_input_streaming": True}
        for t in TOOLS
    ]


def openai_tools() -> list:
    """Tool definitions in OpenAI chat-completions format (LM Studio, Ollama, llama.cpp…)."""
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description,
                                          "parameters": _schema(t)}}
        for t in TOOLS
    ]


# --- argument validation ----------------------------------------------------------

def validate(tool: Tool, args) -> tuple:
    """Check and gently coerce model-supplied arguments. Returns (clean_args, error)."""
    if not isinstance(args, dict):
        return {}, "Arguments must be a JSON object."
    clean = {}
    for key, spec in tool.params.items():
        if key not in args or args[key] is None or args[key] == "":
            continue
        value, kind = args[key], spec["type"]
        if kind == "string":
            if not isinstance(value, str):
                value = str(value)
            if "enum" in spec and value not in spec["enum"]:
                return {}, f"'{key}' must be one of: {', '.join(spec['enum'])}."
        elif kind == "integer":
            if isinstance(value, bool):
                return {}, f"'{key}' must be a whole number."
            try:
                value = int(float(value))
            except (TypeError, ValueError):
                return {}, f"'{key}' must be a whole number."
        elif kind == "boolean":
            if isinstance(value, str) and value.lower() in ("true", "false", "yes", "no"):
                value = value.lower() in ("true", "yes")
            if not isinstance(value, bool):
                return {}, f"'{key}' must be true or false."
        clean[key] = value
    missing = [key for key in tool.required if key not in clean]
    if missing:
        return {}, f"Missing required argument(s): {', '.join(missing)}."
    return clean, ""


# Paths the tools have surfaced this session; the UI may only open these.
_known_paths: set = set()
_known_lock = threading.Lock()


def is_known_path(path: str) -> bool:
    with _known_lock:
        return path in _known_paths


def remember_paths(items: list) -> None:
    with _known_lock:
        for item in items:
            if item.get("path"):
                _known_paths.add(item["path"])


def execute(name: str, args) -> ToolResult:
    """Validate and run a tool. Never raises: failures come back as results the model can read."""
    tool = get(name)
    if tool is None:
        return ToolResult(False, f"Unknown tool '{name}'. Available: {', '.join(_BY_NAME)}.",
                          f"Unknown action {name}")
    clean, error = validate(tool, args)
    if error:
        return ToolResult(False, f"Invalid arguments for {name}: {error}", f"Couldn't run {name}")
    try:
        result = tool.run(**clean)
    except Exception as exc:  # a tool bug must not take the assistant down
        return ToolResult(False, f"{name} failed: {type(exc).__name__}: {exc}", f"{tool.doing} failed")
    remember_paths(result.items)
    return result


# --- instant commands -------------------------------------------------------------

_POLITE = re.compile(r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)+|[\s,]*please$", re.I)
_VOLUME_WORDS = {"up": 15, "louder": 15, "down": -15, "quieter": -15, "lower": -15}
_NUMBER_WORDS = {"zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "half": 50,
                 "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "full": 100,
                 "max": 100, "maximum": 100}


def quick_intent(text: str) -> tuple | None:
    """Recognise unambiguous commands. Returns (tool_name, args, spoken_reply) or None.

    This keeps "open calculator" instant and working even with no model
    connected. Anything remotely open to interpretation is left to the model.
    """
    cmd = _POLITE.sub("", text.strip().strip(".!?").strip()).strip()
    low = cmd.lower()

    match = re.match(r"^(?:open|launch|start)\s+(?:up\s+)?(?:the\s+)?(.+?)(?:\s+app(?:lication)?)?$", low)
    if match and len(match.group(1).split()) <= 4:
        app = mac.find_app(match.group(1), strict=True)
        if app is not None:
            return "open_app", {"name": match.group(1)}, f"Opening {app.name[:-4]}."

    match = re.match(r"^(?:open|show|find|go to)\s+(?:up\s+)?(?:the\s+|my\s+)?(?:(folder|file|pdf|document|image|photo|picture)\s+)?"
                     r"(?:called\s+|named\s+)?(.+?)(?:\s+(folder|file|pdf|document))?"
                     r"(?:\s+(?:on|in|from|inside)\s+(?:the\s+|my\s+)?(desktop|downloads|documents|pictures|home|icloud)(?:\s+folder)?)?$", low)
    if match and not mac.find_app(match.group(2), strict=True) and len(match.group(2).split()) <= 6:
        kind_word = match.group(1) or match.group(3) or ""
        kind = {"folder": "folder", "pdf": "pdf", "image": "image", "photo": "image", "picture": "image"}.get(kind_word, "any")
        args = {"query": match.group(2), "kind": kind}
        if match.group(4):
            args["folder"] = match.group(4)
        if low.startswith("find "):
            return "find_files", args, ""   # "find" lists matches; it never opens anything
        return "open_best", args, ""

    match = re.match(r"^(?:quit|close|exit)\s+(?:the\s+)?(.+?)(?:\s+app(?:lication)?)?$", low)
    if match and len(match.group(1).split()) <= 4:
        app = mac.find_app(match.group(1), strict=True)
        if app is not None:
            return "quit_app", {"name": match.group(1)}, f"Closing {app.name[:-4]}."

    match = re.match(r"^(?:search|google)(?:\s+(?:the\s+)?(?:web|internet|online|google))?\s+(?:for\s+)?(.+)$", low)
    if match and not re.search(r"\b(file|files|folder|document|documents|pdf|desktop|downloads|my)\b", low):
        return "search_in_browser", {"query": cmd[match.start(1):]}, "Here's what I found on the web."

    match = re.match(r"^(?:turn\s+)?(?:the\s+)?volume\s+(up|down)$|^turn\s+(?:it\s+|the\s+volume\s+)?(up|down)$"
                     r"|^(louder|quieter)$", low)
    if match:
        word = next(g for g in match.groups() if g)
        return "set_volume", {"change": _VOLUME_WORDS[word]}, "Done."
    match = re.match(r"^(?:set\s+)?(?:the\s+)?volume\s+(?:to\s+)?(\d{1,3}|[a-z]+)(?:\s*%|\s+percent)?$", low)
    if match:
        raw = match.group(1)
        level = int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)
        if level is not None and 0 <= level <= 100:
            return "set_volume", {"level": level}, f"Volume at {level} percent."
    if low in ("mute", "mute the volume", "mute the sound", "mute my mac"):
        return "set_volume", {"mute": True}, ""
    if low in ("unmute", "unmute the volume", "unmute the sound"):
        return "set_volume", {"mute": False}, "Sound is back on."

    if low in ("pause", "pause the music", "pause music", "play", "play music", "resume", "resume the music"):
        return "media_control", {"action": "play_pause"}, ""
    if low in ("next", "next song", "next track", "skip", "skip this song", "skip song"):
        return "media_control", {"action": "next"}, ""
    if low in ("previous", "previous song", "previous track", "go back a song"):
        return "media_control", {"action": "previous"}, ""

    if re.match(r"^take\s+a\s+screenshot$|^screenshot$|^capture\s+(?:the\s+|my\s+)?screen$", low):
        return "take_screenshot", {}, "Screenshot saved to your Desktop."
    return None
