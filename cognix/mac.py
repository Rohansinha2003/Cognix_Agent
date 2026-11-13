"""macOS system control: apps, files, Spotlight search, volume, media, etc.

Every function here is a plain, synchronous building block that returns a
``ToolResult``. Nothing in this module deletes, moves or overwrites user data,
and nothing runs arbitrary shell commands — that is a deliberate boundary for
an assistant that acts on what it *thinks* it heard.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()


@dataclass
class ToolResult:
    ok: bool
    text: str                                   # what the language model reads
    title: str = ""                             # one line for the UI ("Opened Safari")
    items: list = field(default_factory=list)   # files/apps shown as clickable rows


def _fail(text: str, title: str = "") -> ToolResult:
    return ToolResult(False, text, title or text)


def _run(cmd: list, timeout: float = 15, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)


def _osascript(script: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return _run(["osascript", "-e", script], timeout=timeout)


def _as_string(value: str) -> str:
    """Quote a Python string as an AppleScript string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


# --- paths ------------------------------------------------------------------------

_WELL_KNOWN = {
    "home": HOME, "desktop": HOME / "Desktop", "documents": HOME / "Documents",
    "downloads": HOME / "Downloads", "pictures": HOME / "Pictures", "movies": HOME / "Movies",
    "music": HOME / "Music", "applications": Path("/Applications"),
    "icloud": HOME / "Library/Mobile Documents/com~apple~CloudDocs",
}

_SENSITIVE_DIRS = [
    HOME / ".ssh", HOME / ".aws", HOME / ".gnupg", HOME / ".cognix", HOME / ".config/anthropic",
    HOME / "Library/Keychains", HOME / ".kube", HOME / ".docker",
]
_SENSITIVE_NAMES = re.compile(r"^(\.env(\..*)?|id_(rsa|dsa|ecdsa|ed25519).*|.*\.(pem|key|p12|pfx|keychain(-db)?))$", re.I)


def resolve_path(raw: str) -> Path:
    """Turn "Downloads", "~/x", "Desktop/report.pdf" or an absolute path into a Path."""
    raw = (raw or "").strip().strip("\"'")
    if not raw:
        return HOME
    key = raw.lower().rstrip("/").removeprefix("my ").removesuffix(" folder")
    if key in _WELL_KNOWN:
        return _WELL_KNOWN[key]
    path = Path(os.path.expanduser(raw))
    if not path.is_absolute():
        first, _, rest = raw.partition("/")
        base = _WELL_KNOWN.get(first.lower())
        path = (base / rest) if base else (HOME / raw)
    return path


def is_sensitive(path: Path) -> bool:
    """Credential stores and key files Cognix refuses to read aloud or send to a model."""
    try:
        resolved = path.resolve()
    except OSError:
        return True
    if _SENSITIVE_NAMES.match(resolved.name):
        return True
    return any(resolved == d or d in resolved.parents for d in _SENSITIVE_DIRS)


def _human_size(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _when(ts: float) -> str:
    then = _dt.datetime.fromtimestamp(ts)
    days = (_dt.date.today() - then.date()).days
    if days == 0:
        return f"today {then:%H:%M}"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return f"{then:%b} {then.day}, {then.year}"


_KIND_BY_EXT = {
    "pdf": "pdf", "png": "image", "jpg": "image", "jpeg": "image", "gif": "image", "heic": "image",
    "webp": "image", "svg": "image", "mp3": "audio", "wav": "audio", "m4a": "audio", "flac": "audio",
    "mp4": "video", "mov": "video", "mkv": "video", "key": "slides", "ppt": "slides", "pptx": "slides",
    "xls": "sheet", "xlsx": "sheet", "csv": "sheet", "numbers": "sheet", "doc": "doc", "docx": "doc",
    "pages": "doc", "rtf": "doc", "txt": "text", "md": "text", "zip": "archive", "dmg": "archive",
    "app": "app", "py": "code", "js": "code", "ts": "code", "json": "code", "html": "code",
    "css": "code", "swift": "code", "go": "code", "rs": "code", "java": "code", "c": "code", "sh": "code",
}


def describe(path: Path) -> dict:
    """A UI/model-friendly record for a file or folder."""
    try:
        st = path.stat()
        is_dir = path.is_dir()
    except OSError:
        return {"name": path.name, "path": str(path), "kind": "file", "detail": ""}
    ext = path.suffix.lower().lstrip(".")
    kind = "app" if ext == "app" else "folder" if is_dir else _KIND_BY_EXT.get(ext, "file")
    parent = str(path.parent).replace(str(HOME), "~", 1)
    if len(parent) > 44:
        parent = "…/" + "/".join(path.parent.parts[-2:])
    bits = [parent, _when(st.st_mtime)]
    if not is_dir:
        bits.append(_human_size(st.st_size))
    return {"name": path.name, "path": str(path), "kind": kind, "detail": " · ".join(bits),
            "modified": st.st_mtime}


def _lines_for_model(items: list) -> str:
    return "\n".join(f"{i}. {it['name']} — {it['path']} ({it['detail']})" for i, it in enumerate(items, 1))


# --- applications -----------------------------------------------------------------

_APP_DIRS = [
    "/Applications", "/System/Applications", "/System/Applications/Utilities",
    "/Applications/Utilities", str(HOME / "Applications"), "/System/Library/CoreServices",
    "/System/Cryptexes/App/System/Applications", "/System/Library/CoreServices/Applications",
]
_APP_ALIASES = {
    "chrome": "google chrome", "vscode": "visual studio code", "vs code": "visual studio code",
    "code": "visual studio code", "word": "microsoft word", "excel": "microsoft excel",
    "powerpoint": "microsoft powerpoint", "outlook": "microsoft outlook", "teams": "microsoft teams",
    "settings": "system settings", "system preferences": "system settings",
    "preferences": "system settings", "app store": "app store", "itunes": "music",
    "apple music": "music", "browser": "safari", "mail app": "mail", "text edit": "textedit",
    "face time": "facetime", "quick time": "quicktime player", "quicktime": "quicktime player",
    "lm studio": "lm studio", "imessage": "messages", "terminal app": "terminal",
    "calc": "calculator", "photo booth": "photo booth", "activity": "activity monitor",
}
_app_cache: dict = {"at": 0.0, "apps": {}}
_app_lock = threading.Lock()


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def installed_apps() -> dict:
    """``{normalised name: Path}`` for every app in the standard locations (cached)."""
    with _app_lock:
        if time.time() - _app_cache["at"] < 120 and _app_cache["apps"]:
            return _app_cache["apps"]
        apps: dict = {}
        for base in _APP_DIRS:
            try:
                entries = sorted(os.scandir(base), key=lambda e: e.name)
            except OSError:
                continue
            for entry in entries:
                if entry.name.endswith(".app"):
                    apps.setdefault(_norm(entry.name[:-4]), Path(entry.path))
                elif entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                    try:  # one level down: "/Applications/Adobe Photoshop 2026/…app"
                        for sub in os.scandir(entry.path):
                            if sub.name.endswith(".app"):
                                apps.setdefault(_norm(sub.name[:-4]), Path(sub.path))
                    except OSError:
                        pass
        _app_cache.update(at=time.time(), apps=apps)
        return apps


def find_app(name: str, strict: bool = False) -> Path | None:
    """Best installed-app match for a spoken name ("chrome", "vs code", "calculater").

    With ``strict`` only exact names and known aliases match — used where a
    wrong guess would be acted on without a model double-checking it.
    """
    apps = installed_apps()
    wanted = _norm(re.sub(r"\b(the|app|application)\b", " ", name.lower()))
    if not wanted:
        return None
    wanted = _APP_ALIASES.get(wanted, wanted)
    if wanted in apps:
        return apps[wanted]
    compact = wanted.replace(" ", "")
    for key, path in apps.items():
        if key.replace(" ", "") == compact:
            return path
    if strict:
        return None
    starts = sorted((k for k in apps if k.startswith(wanted + " ") or k.startswith(wanted)), key=len)
    if starts:
        return apps[starts[0]]
    words = wanted.split()
    contains = sorted((k for k in apps if all(w in k.split() for w in words)), key=len)
    if contains:
        return apps[contains[0]]
    close = difflib.get_close_matches(wanted, list(apps), n=1, cutoff=0.8)
    return apps[close[0]] if close else None


def _app_label(path: Path) -> str:
    return path.name[:-4] if path.name.endswith(".app") else path.name


def open_app(name: str) -> ToolResult:
    path = find_app(name)
    if path is None:
        close = difflib.get_close_matches(_norm(name), list(installed_apps()), n=4, cutoff=0.5)
        hint = f" Similar installed apps: {', '.join(close)}." if close else ""
        return _fail(f"No installed app matches '{name}'.{hint}", f"Couldn't find an app called {name}")
    proc = _run(["open", "-a", str(path)])
    if proc.returncode != 0:
        return _fail(f"macOS could not open {_app_label(path)}: {proc.stderr.strip()}")
    label = _app_label(path)
    return ToolResult(True, f"Opened {label}.", f"Opened {label}",
                      [{"name": label, "path": str(path), "kind": "app", "detail": "Application"}])


def running_apps() -> list:
    """Names of the regular (Dock-visible) apps that are running."""
    try:
        from AppKit import NSWorkspace

        return [
            str(app.localizedName()) for app in NSWorkspace.sharedWorkspace().runningApplications()
            if app.activationPolicy() == 0 and app.localizedName()
        ]
    except Exception:
        proc = _osascript('tell application "System Events" to get name of '
                          "(processes where background only is false)")
        return [n.strip() for n in proc.stdout.split(",") if n.strip()] if proc.returncode == 0 else []


def quit_app(name: str) -> ToolResult:
    names = running_apps()
    wanted = _norm(_APP_ALIASES.get(_norm(name), name))
    by_norm = {_norm(n): n for n in names}
    target = by_norm.get(wanted)
    if target is None:
        close = [n for k, n in by_norm.items() if wanted in k or k in wanted]
        close = close or [by_norm[k] for k in difflib.get_close_matches(wanted, list(by_norm), n=1, cutoff=0.75)]
        target = close[0] if close else None
    if target is None:
        return _fail(f"'{name}' is not running. Running apps: {', '.join(sorted(names)) or 'none'}.",
                     f"{name} isn't running")
    if _norm(target) == "finder":
        return _fail("Finder cannot be quit.", "Finder can't be quit")
    try:
        from AppKit import NSWorkspace

        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.localizedName() == target and app.activationPolicy() == 0:
                app.terminate()  # a normal quit: the app can still ask to save changes
                return ToolResult(True, f"Asked {target} to quit.", f"Quit {target}")
    except Exception:
        pass
    proc = _osascript(f"tell application {_as_string(target)} to quit")
    if proc.returncode != 0:
        return _fail(f"Could not quit {target}: {proc.stderr.strip()}")
    return ToolResult(True, f"Asked {target} to quit.", f"Quit {target}")


# --- finding files ----------------------------------------------------------------

_KIND_QUERIES = {
    "pdf": 'kMDItemContentType == "com.adobe.pdf"',
    "image": 'kMDItemContentTypeTree == "public.image"',
    "audio": 'kMDItemContentTypeTree == "public.audio"',
    "video": 'kMDItemContentTypeTree == "public.movie"',
    "folder": 'kMDItemContentType == "public.folder"',
    "presentation": 'kMDItemContentTypeTree == "public.presentation"',
    "spreadsheet": 'kMDItemContentTypeTree == "public.spreadsheet"',
    "document": '(kMDItemContentTypeTree == "public.composite-content" || '
                'kMDItemContentTypeTree == "public.text")',
}
FILE_KINDS = ["any", *_KIND_QUERIES]
_KIND_EXTS = {
    "pdf": {"pdf"}, "image": {"png", "jpg", "jpeg", "gif", "heic", "webp", "tiff", "bmp", "svg"},
    "audio": {"mp3", "wav", "m4a", "flac", "aac", "aiff"}, "video": {"mp4", "mov", "mkv", "avi", "m4v"},
    "presentation": {"key", "ppt", "pptx"}, "spreadsheet": {"xls", "xlsx", "csv", "numbers"},
    "document": {"pdf", "doc", "docx", "pages", "rtf", "txt", "md", "odt"},
}
_SKIP_PARTS = {"node_modules", "__pycache__", "site-packages", "Library", "DerivedData", "Pods",
               "vendor", "dist", "build", "target"}


def _is_noise(path: Path, scope: Path) -> bool:
    """Hide caches, dependencies and bundle internals from search results."""
    try:
        rel = path.relative_to(scope)
    except ValueError:
        rel = path
    parts = rel.parts[:-1]
    if any(p.startswith(".") or p in _SKIP_PARTS for p in parts):
        return True
    if any(p.endswith((".app", ".framework", ".photoslibrary", ".bundle")) for p in parts):
        return True
    return rel.name.startswith(".")


def _mdfind_escape(word: str) -> str:
    return word.replace("\\", "\\\\").replace('"', '\\"').replace("*", "\\*")


def find_files(query: str = "", kind: str = "any", folder: str = "", content: bool = False,
               limit: int = 8) -> ToolResult:
    """Search by name (and optionally contents) with Spotlight, newest first."""
    scope = resolve_path(folder) if folder else HOME
    if not scope.is_dir():
        return _fail(f"Folder not found: {scope}", "That folder doesn't exist")
    limit = max(1, min(int(limit or 8), 25))
    words = [w for w in re.findall(r"[^\s]+", query or "") if w]

    clauses = []
    if words:
        name = " && ".join(f'kMDItemDisplayName == "*{_mdfind_escape(w)}*"cd' for w in words)
        if content:
            phrase = _mdfind_escape(" ".join(words))
            clauses.append(f'(({name}) || kMDItemTextContent == "*{phrase}*"cd)')
        else:
            clauses.append(f"({name})")
    if kind in _KIND_QUERIES:
        clauses.append(_KIND_QUERIES[kind])
    if not clauses:
        return _fail("Give a search query, a kind, or both.", "Nothing to search for")

    paths: list = []
    try:
        proc = _run(["mdfind", "-onlyin", str(scope), " && ".join(clauses)], timeout=20)
        if proc.returncode == 0:
            paths = [Path(p) for p in proc.stdout.splitlines() if p.startswith("/")]
    except (OSError, subprocess.SubprocessError):
        paths = []
    paths = [p for p in paths if not _is_noise(p, scope)]
    if not paths and not content:
        paths = _walk_search(scope, words, kind)  # Spotlight off or still indexing

    scored = []
    for path in paths[:600]:
        try:
            scored.append((path.stat().st_mtime, path))
        except OSError:
            continue
    scored.sort(key=lambda pair: pair[0], reverse=True)
    items = [describe(p) for _, p in scored[:limit]]

    noun = {"any": "file", "pdf": "PDF"}.get(kind, kind)
    what = f"'{query}'" if query else f"{noun}s"
    where = str(scope).replace(str(HOME), "~", 1)
    if not items:
        return ToolResult(True, f"No files matching {what} in {where}.", f"No matches for {what}")
    count = len(scored)
    more = f" (showing the {len(items)} most recent of {count})" if count > len(items) else ""
    title = f"Found {count} {noun}{'s' if count != 1 else ''}" + (f" matching “{query}”" if query else "")
    return ToolResult(
        True,
        f"Found {count} match(es) for {what} in {where}{more}, newest first:\n{_lines_for_model(items)}",
        title,
        items,
    )


def _walk_search(scope: Path, words: list, kind: str) -> list:
    """Filename search without Spotlight (bounded walk of the usual folders)."""
    roots = [scope] if scope != HOME else [HOME / d for d in ("Desktop", "Documents", "Downloads")]
    wanted = [w.lower() for w in words]
    exts = _KIND_EXTS.get(kind)
    found, deadline = [], time.time() + 6
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            if time.time() > deadline or len(found) >= 300:
                return found
            depth = len(Path(dirpath).relative_to(root).parts)
            dirnames[:] = [] if depth >= 5 else [
                d for d in dirnames if not d.startswith(".") and d not in _SKIP_PARTS and not d.endswith(".app")
            ]
            names = dirnames if kind == "folder" else filenames
            for name in names:
                low = name.lower()
                if name.startswith(".") or not all(w in low for w in wanted):
                    continue
                if exts and low.rsplit(".", 1)[-1] not in exts:
                    continue
                found.append(Path(dirpath) / name)
    return found


def list_folder(path: str = "", limit: int = 30) -> ToolResult:
    folder = resolve_path(path)
    if not folder.is_dir():
        return _fail(f"Folder not found: {folder}", "That folder doesn't exist")
    try:
        entries = [p for p in folder.iterdir() if not p.name.startswith(".")]
    except PermissionError:
        return _fail(f"macOS denied access to {folder}. Grant it in System Settings → Privacy & Security "
                     "→ Files and Folders.", "No permission to read that folder")
    items = sorted((describe(p) for p in entries), key=lambda it: it.get("modified", 0), reverse=True)
    shown = items[: max(1, min(int(limit or 30), 60))]
    where = str(folder).replace(str(HOME), "~", 1)
    if not shown:
        return ToolResult(True, f"{where} is empty.", f"{where} is empty")
    return ToolResult(True, f"{where} has {len(items)} item(s). Most recent first:\n{_lines_for_model(shown)}",
                      f"{len(items)} item{'s' if len(items) != 1 else ''} in {where}", shown)


def open_path(path: str, app: str = "", reveal: bool = False) -> ToolResult:
    """Open a file or folder with its default app (or a named one), or reveal it in Finder."""
    target = resolve_path(path)
    if not target.exists():
        return _fail(f"Nothing exists at {target}. Use find_files to locate it first.",
                     f"Couldn't find {target.name}")
    cmd = ["open"]
    if reveal:
        cmd.append("-R")
    elif app:
        app_path = find_app(app)
        if app_path is None:
            return _fail(f"No installed app matches '{app}'.", f"Couldn't find an app called {app}")
        cmd += ["-a", str(app_path)]
    proc = _run(cmd + [str(target)])
    if proc.returncode != 0:
        return _fail(f"macOS could not open {target.name}: {proc.stderr.strip()}")
    verb = "Revealed" if reveal else "Opened"
    return ToolResult(True, f"{verb} {target}.", f"{verb} {target.name}", [describe(target)])


def open_best(query: str, kind: str = "any", folder: str = "") -> ToolResult:
    """Find something by name and open it if one match clearly stands out; otherwise list the candidates."""
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w]
    direct = resolve_path(query) if query else None
    if direct is not None and not folder and query.strip().lower().rstrip("/") in _WELL_KNOWN:
        return open_path(str(direct))
    found = find_files(query, kind, folder, limit=12)
    if not found.items:
        return found
    def stem(it):
        return re.sub(r"[^a-z0-9]+", " ", Path(it["name"]).stem.lower()).strip()
    exact = [it for it in found.items if stem(it) == " ".join(words)]
    pick = exact[0] if len(exact) == 1 else (found.items[0] if len(found.items) == 1 else None)
    if pick is None:
        found.text += "\nSeveral match; ask the user which one, or pick the clear best."
        return found
    return open_path(pick["path"])


# --- reading files ----------------------------------------------------------------

_TEXTUTIL_EXTS = {".doc", ".docx", ".rtf", ".rtfd", ".odt", ".html", ".htm", ".webarchive", ".wordml"}


def _extract_text(path: Path) -> tuple:
    """Returns (text, note). Raises ValueError with a user-facing reason."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF support needs the 'pypdf' package (pip install pypdf).") from exc
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("That PDF is password-protected.")
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Could not read that PDF: {exc}") from exc
        text = "\n\n".join(f"[Page {i}]\n{t}" for i, t in enumerate(pages, 1) if t)
        if not text.strip():
            raise ValueError("That PDF has no selectable text (it is probably a scan).")
        return text, f"PDF, {len(pages)} page(s)"
    if ext in _TEXTUTIL_EXTS:
        proc = _run(["textutil", "-convert", "txt", "-stdout", str(path)], timeout=30)
        if proc.returncode != 0:
            raise ValueError(f"Could not convert that document: {proc.stderr.strip()}")
        return proc.stdout, f"{ext.lstrip('.').upper()} document"
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ValueError(f"{path.name} is a binary file, not text. It can be opened with open_path instead.")
    return raw.decode("utf-8", errors="replace"), "text file"


def read_file(path: str, offset: int = 0, max_chars: int = 12000) -> ToolResult:
    """Read text out of a text file, PDF or Word/RTF document."""
    target = resolve_path(path)
    if not target.is_file():
        return _fail(f"No file at {target}. Use find_files to locate it first.", f"Couldn't find {target.name}")
    if is_sensitive(target):
        return _fail("That file holds credentials or keys, so Cognix does not read it.",
                     "Blocked: credentials file")
    if target.stat().st_size > 80 * 1024 * 1024:
        return _fail("That file is larger than 80 MB, which is too big to read.", "File too large")
    try:
        text, note = _extract_text(target)
    except ValueError as exc:
        return _fail(str(exc))
    except PermissionError:
        return _fail("macOS denied access to that file. Grant it in System Settings → Privacy & Security "
                     "→ Files and Folders.", "No permission to read that file")
    total = len(text)
    offset = max(0, min(int(offset or 0), total))
    max_chars = max(500, min(int(max_chars or 12000), 60000))
    chunk = text[offset: offset + max_chars]
    end = offset + len(chunk)
    header = f"{target.name} ({note}, {total:,} characters). Showing characters {offset:,}–{end:,}."
    if end < total:
        header += f" There is more: call read_file again with offset={end} to continue."
    return ToolResult(True, f"{header}\n\n{chunk}", f"Read {target.name}", [describe(target)])


# --- web --------------------------------------------------------------------------

def _web_url(url: str) -> str | None:
    """Normalise to a plain http(s) URL, or None if it is anything else."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        if re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", url, re.I):
            return None  # some other scheme: file:, javascript:, mailto:…
        url = "https://" + url
    try:
        parsed = urllib.parse.urlparse(url)
        parsed.port  # raises ValueError on a malformed port
    except ValueError:
        return None
    host = parsed.hostname or ""
    if not re.match(r"^[a-z0-9.-]+$", host, re.I) or ("." not in host and host != "localhost"):
        return None
    return url


def _open_in_browser(url: str) -> bool:
    try:
        return _run(["open", url]).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def open_url(url: str) -> ToolResult:
    clean = _web_url(url)
    if clean is None:
        return _fail("Only http and https web addresses can be opened.", "Not a web link")
    if not _open_in_browser(clean):
        return _fail("macOS could not open that link.")
    return ToolResult(True, f"Opened {clean} in the browser.", f"Opened {urllib.parse.urlparse(clean).hostname}")


def search_in_browser(query: str) -> ToolResult:
    query = (query or "").strip()
    if not query:
        return _fail("Nothing to search for.")
    if not _open_in_browser("https://www.google.com/search?q=" + urllib.parse.quote_plus(query)):
        return _fail("macOS could not open the browser.")
    return ToolResult(True, f"Opened a web search for '{query}' in the browser.", f"Searched the web for “{query}”")


# --- system -----------------------------------------------------------------------

def get_volume() -> int | None:
    proc = _osascript("output volume of (get volume settings)")
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def set_volume(level: int | None = None, change: int | None = None, mute: bool | None = None) -> ToolResult:
    if mute is not None and level is None and change is None:
        proc = _osascript(f"set volume output muted {'true' if mute else 'false'}")
        if proc.returncode != 0:
            return _fail(f"Could not change mute: {proc.stderr.strip()}")
        return ToolResult(True, "Muted." if mute else "Unmuted.", "Muted" if mute else "Unmuted")
    if level is None:
        current = get_volume()
        if change is None or current is None:
            return _fail("Give a level (0-100), a change (e.g. -20) or mute.")
        level = current + int(change)
    level = max(0, min(100, int(level)))
    proc = _osascript(f"set volume output volume {level} without output muted")
    if proc.returncode != 0:
        return _fail(f"Could not set the volume: {proc.stderr.strip()}")
    return ToolResult(True, f"Volume set to {level}%.", f"Volume {level}%")


def media_control(action: str) -> ToolResult:
    verbs = {"play_pause": "playpause", "next": "next track", "previous": "previous track"}
    if action not in verbs:
        return _fail("action must be play_pause, next or previous.")
    player = "Spotify" if "Spotify" in running_apps() else "Music"
    proc = _osascript(f"tell application {_as_string(player)} to {verbs[action]}")
    if proc.returncode != 0:
        return _fail(f"{player} did not respond: {proc.stderr.strip()} (macOS may need you to allow "
                     f"Cognix to control {player} in System Settings → Privacy & Security → Automation.)",
                     f"Couldn't control {player}")
    label = {"play_pause": "Play/pause", "next": "Next track", "previous": "Previous track"}[action]
    return ToolResult(True, f"{label} sent to {player}.", f"{label} · {player}")


def system_info() -> ToolResult:
    now = _dt.datetime.now().astimezone()
    lines = [f"Date and time: {now:%A, %B} {now.day}, {now.year}, {now:%H:%M} ({now.tzname()})"]
    try:
        batt = _run(["pmset", "-g", "batt"], timeout=5).stdout
        match = re.search(r"(\d+)%;\s*([a-zA-Z ]+);", batt)
        if match:
            lines.append(f"Battery: {match.group(1)}% ({match.group(2).strip()})")
    except (OSError, subprocess.SubprocessError):
        pass
    volume = get_volume()
    if volume is not None:
        lines.append(f"Volume: {volume}%")
    try:
        usage = shutil.disk_usage(str(HOME))
        lines.append(f"Disk: {_human_size(usage.free)} free of {_human_size(usage.total)}")
    except OSError:
        pass
    try:
        dark = _run(["defaults", "read", "-g", "AppleInterfaceStyle"], timeout=5).stdout.strip() == "Dark"
        lines.append(f"Appearance: {'dark' if dark else 'light'} mode")
    except (OSError, subprocess.SubprocessError):
        pass
    apps = running_apps()
    if apps:
        lines.append(f"Open apps: {', '.join(sorted(set(apps)))}")
    lines.append(f"macOS {platform.mac_ver()[0]}")
    return ToolResult(True, "\n".join(lines), "Checked the system")


def set_dark_mode(enabled: bool) -> ToolResult:
    proc = _osascript('tell application "System Events" to tell appearance preferences to set dark mode to '
                      + ("true" if enabled else "false"))
    if proc.returncode != 0:
        return _fail("macOS blocked the change. Allow Cognix to control System Events in System Settings → "
                     "Privacy & Security → Automation, then try again.", "Couldn't change appearance")
    mode = "dark" if enabled else "light"
    return ToolResult(True, f"Switched to {mode} mode.", f"Switched to {mode} mode")


def take_screenshot() -> ToolResult:
    target = HOME / "Desktop" / f"Screenshot {_dt.datetime.now():%Y-%m-%d at %H.%M.%S}.png"
    proc = _run(["screencapture", "-x", str(target)], timeout=15)
    if proc.returncode != 0 or not target.exists():
        return _fail("The screenshot failed. Allow screen recording for the app running Cognix in System "
                     "Settings → Privacy & Security → Screen & System Audio Recording.", "Screenshot failed")
    return ToolResult(True, f"Saved a screenshot to {target}.", "Screenshot saved to Desktop", [describe(target)])


def clipboard(action: str, text: str = "") -> ToolResult:
    if action == "read":
        content = _run(["pbpaste"], timeout=5).stdout
        if not content.strip():
            return ToolResult(True, "The clipboard is empty (or holds something that is not text).",
                              "Clipboard is empty")
        shown = content[:8000]
        note = f"\n[Clipboard continues: {len(content):,} characters in total.]" if len(content) > 8000 else ""
        return ToolResult(True, f"Clipboard contents:\n{shown}{note}", "Read the clipboard")
    if action == "write":
        if not text:
            return _fail("No text given to copy.")
        _run(["pbcopy"], timeout=5, input_text=text)
        return ToolResult(True, "Copied to the clipboard.", "Copied to clipboard")
    return _fail("action must be read or write.")


def run_shortcut(name: str) -> ToolResult:
    """Run one of the user's Shortcuts — the extension point for anything Cognix can't do natively."""
    try:
        available = [s for s in _run(["shortcuts", "list"], timeout=10).stdout.splitlines() if s.strip()]
    except (OSError, subprocess.SubprocessError):
        return _fail("The Shortcuts command-line tool is not available on this Mac.")
    by_norm = {_norm(s): s for s in available}
    match = by_norm.get(_norm(name))
    if match is None:
        close = difflib.get_close_matches(_norm(name), list(by_norm), n=1, cutoff=0.7)
        match = by_norm[close[0]] if close else None
    if match is None:
        listing = ", ".join(available[:30]) or "none yet"
        return _fail(f"No shortcut named '{name}'. Available shortcuts: {listing}.", f"No shortcut called {name}")
    try:
        proc = _run(["shortcuts", "run", match], timeout=120)
    except subprocess.TimeoutExpired:
        return _fail(f"The shortcut '{match}' is still running after two minutes.")
    if proc.returncode != 0:
        return _fail(f"The shortcut '{match}' failed: {proc.stderr.strip()}")
    out = proc.stdout.strip()
    return ToolResult(True, f"Ran the shortcut '{match}'." + (f" Output:\n{out[:4000]}" if out else ""),
                      f"Ran shortcut “{match}”")


def sleep_display() -> ToolResult:
    proc = _run(["pmset", "displaysleepnow"], timeout=5)
    if proc.returncode != 0:
        return _fail(f"Could not sleep the display: {proc.stderr.strip()}")
    return ToolResult(True, "The display is going to sleep.", "Display asleep")
