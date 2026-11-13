"""Entry point: start the assistant and open its window."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import webbrowser

from . import __version__
from .assistant import Assistant
from .config import Settings
from .events import EventBus
from .server import CognixServer

WINDOW_BG = "#0a0a0c"


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cognix", description="Cognix — a voice assistant for your Mac.")
    parser.add_argument("--browser", action="store_true",
                        help="open the interface in your web browser instead of a native window")
    parser.add_argument("--port", type=int, default=0, help="port for the local interface (default: random)")
    parser.add_argument("--no-open", action="store_true", help="start without opening any window")
    parser.add_argument("--version", action="version", version=f"Cognix {__version__}")
    args = parser.parse_args(argv)

    if sys.platform != "darwin":
        print("Cognix controls macOS and currently runs on a Mac only.", file=sys.stderr)
        return 1

    bus = EventBus()
    assistant = Assistant(Settings(), bus)
    server = CognixServer(assistant, bus, port=args.port)
    server.start()
    assistant.start()
    print(f"Cognix {__version__} is running at {server.url}  —  say “Hey Cognix”.  (Ctrl+C to quit)")

    def close(*_):
        assistant.shutdown()
        server.shutdown()

    try:
        if not args.browser and not args.no_open and _open_window(server.url):
            close()
            return 0
        if not args.no_open:
            webbrowser.open(server.url)
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        stop.wait()
    except KeyboardInterrupt:
        pass
    close()
    return 0


def _open_window(url: str) -> bool:
    """Show the interface in a native window. Returns False if pywebview is unavailable."""
    try:
        import webview
    except Exception:
        print("pywebview is not installed, so Cognix is opening in your browser instead.", file=sys.stderr)
        return False
    webview.create_window("Cognix", url, width=1180, height=780, min_size=(820, 600),
                          background_color=WINDOW_BG, text_select=True)
    webview.start()  # blocks until the window is closed
    return True


if __name__ == "__main__":
    sys.exit(main())
