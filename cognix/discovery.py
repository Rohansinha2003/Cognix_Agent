"""Finding the local model server on this Mac.

Bionic and LM Studio share one engine: both serve an OpenAI-compatible API,
and both keep their server settings in ``~/.lmstudio``. Ollama, llama.cpp and
Jan speak the same protocol on other ports, so any of them is picked up too.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

HOME = Path.home()
SERVER_CONFIG = HOME / ".lmstudio" / ".internal" / "http-server-config.json"
LMS_CLI = HOME / ".lmstudio" / "bin" / "lms"
BIONIC_APP = Path("/Applications/Bionic.app")
LM_STUDIO_APP = Path("/Applications/LM Studio.app")

# (port, label): tried in this order after the port Bionic/LM Studio is configured for.
KNOWN_PORTS = [(1234, "Bionic / LM Studio"), (11434, "Ollama"), (8080, "llama.cpp"),
               (1337, "Jan"), (8000, "local server")]


def configured_port() -> int | None:
    """The port Bionic / LM Studio is set to serve on, if it has been configured."""
    try:
        port = json.loads(SERVER_CONFIG.read_text(encoding="utf-8")).get("port")
    except (OSError, ValueError, AttributeError):
        return None
    return port if isinstance(port, int) and 0 < port < 65536 else None


def candidate_urls(preferred: str = "") -> list:
    urls, seen = [], set()

    def add(url: str):
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    add(preferred)
    port = configured_port()
    if port:
        add(f"http://127.0.0.1:{port}/v1")
    for known, _ in KNOWN_PORTS:
        add(f"http://127.0.0.1:{known}/v1")
    return urls


def label_for(url: str) -> str:
    """A friendly name for the server behind ``url``."""
    try:
        port = int(url.rsplit(":", 1)[1].split("/")[0])
    except (IndexError, ValueError):
        return "local server"
    if port == configured_port() and (BIONIC_APP.exists() or LM_STUDIO_APP.exists()):
        return "Bionic" if BIONIC_APP.exists() else "LM Studio"
    return dict(KNOWN_PORTS).get(port, "local server")


def detect(preferred: str, status_fn) -> tuple:
    """Probe the likely servers. Returns ``(url, status)`` for the first with a chat model.

    A server that is up but has no model still counts if nothing better turns
    up, so the app can say "load a model" instead of "not running". Returns
    ``("", {"ok": False, "models": []})`` when nothing answers.
    """
    fallback = ("", {"ok": False, "models": []})
    for url in candidate_urls(preferred):
        status = status_fn(url)
        if status["ok"] and status["models"]:
            return url, status
        if status["ok"] and not fallback[0]:
            fallback = (url, status)
    return fallback


def can_start() -> bool:
    return (BIONIC_APP.exists() or LM_STUDIO_APP.exists()) and (LMS_CLI.exists() or bool(shutil.which("lms")))


def start_server(timeout: float = 45.0) -> bool:
    """Launch Bionic (or LM Studio) in the background and start its API server.

    Returns True once the server's command-line tool reports it is running.
    """
    if not can_start():
        return False
    lms = str(LMS_CLI) if LMS_CLI.exists() else shutil.which("lms")
    app = BIONIC_APP if BIONIC_APP.exists() else LM_STUDIO_APP
    try:
        subprocess.run(["open", "-g", "-j", "-a", str(app)], capture_output=True, timeout=10)  # background, no focus steal
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            proc = subprocess.run([lms, "server", "start", "--port", str(configured_port() or 1234)],
                                  capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                return True
            time.sleep(2.0)
    except (OSError, subprocess.SubprocessError):
        pass
    return False
