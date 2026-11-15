"""Settings, paths and API-key storage.

Settings live in ``~/.cognix/config.json``. The Claude API key is kept in the
macOS Keychain (via ``keyring``) and never written to the settings file; if no
keychain is available it falls back to a file readable only by the user.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

HOME = Path.home()
DATA_DIR = Path(os.environ.get("COGNIX_HOME", HOME / ".cognix"))
CONFIG_FILE = DATA_DIR / "config.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"
KEY_FALLBACK_FILE = DATA_DIR / "api_key"

KEYRING_SERVICE = "Cognix"
KEYRING_USER = "anthropic_api_key"

CLAUDE_MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "hint": "Most capable Opus — the default"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "hint": "Fast and capable"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "hint": "Fastest and cheapest"},
    {"id": "claude-fable-5-2", "label": "Claude Fable 5.2", "hint": "Anthropic's most capable model"},
]

STT_MODELS = ["tiny.en", "base.en", "small.en", "base", "small"]

DEFAULTS = {
    "engine": "local",                       # "local" (Bionic / LM Studio) | "claude"
    "local_url": "http://127.0.0.1:1234/v1",  # any OpenAI-compatible server
    "local_model": "",                       # "" = first model the server reports
    "local_auto": True,                      # find Bionic / LM Studio on its own, and start it if needed
    "claude_model": "claude-opus-5-5",
    "claude_web_search": True,               # let Claude search the web for answers
    "mic_enabled": True,                     # always-on wake-word listening
    "follow_up": False,                      # keep listening briefly after a reply
    "speak": True,                           # read replies aloud
    "voice": "",                             # "" = system default voice
    "rate": 185,                             # words per minute for speech
    "chime": True,                           # play a sound when the wake word is heard
    "stt_model": "base.en",
    "mic_device": "",                        # "" = automatic
    "save_history": True,
}

_VALIDATORS = {
    "engine": lambda v: v in ("local", "claude"),
    "local_url": lambda v: isinstance(v, str) and v.startswith(("http://", "https://")),
    "local_model": lambda v: isinstance(v, str),
    "local_auto": lambda v: isinstance(v, bool),
    "claude_model": lambda v: v in {m["id"] for m in CLAUDE_MODELS},
    "claude_web_search": lambda v: isinstance(v, bool),
    "mic_enabled": lambda v: isinstance(v, bool),
    "follow_up": lambda v: isinstance(v, bool),
    "speak": lambda v: isinstance(v, bool),
    "voice": lambda v: isinstance(v, str),
    "rate": lambda v: isinstance(v, int) and not isinstance(v, bool) and 90 <= v <= 360,
    "chime": lambda v: isinstance(v, bool),
    "stt_model": lambda v: v in STT_MODELS,
    "mic_device": lambda v: isinstance(v, str),
    "save_history": lambda v: isinstance(v, bool),
}


class Settings:
    """Thread-safe settings store backed by a JSON file."""

    def __init__(self, path: Path = CONFIG_FILE):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        self._load()

    def _load(self) -> None:
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS and _VALIDATORS[key](value):
                    self._data[key] = value

    def get(self, key: str):
        with self._lock:
            return self._data[key]

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)

    def update(self, changes: dict) -> dict:
        """Apply valid changes; returns the subset that actually changed."""
        applied = {}
        with self._lock:
            for key, value in (changes or {}).items():
                if key not in DEFAULTS or not _VALIDATORS[key](value):
                    continue
                if self._data[key] != value:
                    self._data[key] = value
                    applied[key] = value
            if applied:
                self._save_locked()
        return applied

    def _save_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            pass  # settings still apply for this session


# --- Claude API key -----------------------------------------------------------

def _keyring():
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring

        if isinstance(keyring.get_keyring(), FailKeyring):
            return None
        return keyring
    except Exception:
        return None


def get_api_key() -> str:
    """The stored Claude API key, or "" if none was saved in Cognix."""
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(KEYRING_SERVICE, KEYRING_USER)
            if value:
                return value
        except Exception:
            pass
    try:
        return KEY_FALLBACK_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def set_api_key(key: str) -> None:
    """Store (or, with an empty string, remove) the Claude API key."""
    key = (key or "").strip()
    kr = _keyring()
    stored = False
    if kr is not None:
        try:
            if key:
                kr.set_password(KEYRING_SERVICE, KEYRING_USER, key)
            else:
                try:
                    kr.delete_password(KEYRING_SERVICE, KEYRING_USER)
                except Exception:
                    pass
            stored = True
        except Exception:
            stored = False
    if stored or not key:
        try:
            KEY_FALLBACK_FILE.unlink()
        except OSError:
            pass
    if key and not stored:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(KEY_FALLBACK_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(key)


def claude_credentials_available() -> bool:
    """True if the Anthropic SDK has something to authenticate with."""
    if get_api_key():
        return True
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (HOME / ".config" / "anthropic").is_dir()  # `ant auth login` profile
