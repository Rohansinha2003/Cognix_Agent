"""The local HTTP server behind the Cognix window.

It serves the interface, streams live events to it (Server-Sent Events) and
accepts commands from it. Because those commands control the computer, the
server is locked down:

  * it listens on 127.0.0.1 only;
  * every API call must carry a random per-launch token, which a web page on
    another origin cannot read;
  * the Host header must be a loopback name, which defeats DNS rebinding.
"""

from __future__ import annotations

import json
import mimetypes
import queue
import secrets
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 64 * 1024


class CognixServer:
    def __init__(self, assistant, bus, port: int = 0):
        self.assistant = assistant
        self.bus = bus
        self.token = secrets.token_urlsafe(24)
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> None:
        threading.Thread(target=self._httpd.serve_forever, name="cognix-http", daemon=True).start()

    def shutdown(self) -> None:
        threading.Thread(target=self._httpd.shutdown, daemon=True).start()

    # ------------------------------------------------------------------ routes
    def _dispatch(self, action: str, body: dict):
        a = self.assistant
        if action == "send":
            a.send_text(str(body.get("text", "")))
        elif action == "stop":
            a.stop()
        elif action == "wake":
            a.wake()
        elif action == "new":
            a.new_conversation()
        elif action == "settings":
            changes = body.get("changes")
            a.apply_settings(changes if isinstance(changes, dict) else {})
        elif action == "key":
            a.set_api_key(str(body.get("key", "")))
        elif action == "voice-preview":
            a.preview_voice()
        elif action == "open":
            return {"ok": a.open_item(str(body.get("path", "")), bool(body.get("reveal")))}
        else:
            return None
        return {"ok": True}

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "Cognix"

            def log_message(self, *_args):  # keep the terminal quiet
                pass

            # --- helpers ---
            def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, data, status: int = 200):
                self._send(status, json.dumps(data).encode("utf-8"), "application/json")

            def _host_ok(self) -> bool:
                return self.headers.get("Host", "") in server._allowed_hosts

            def _authorised(self, query: dict) -> bool:
                supplied = self.headers.get("X-Cognix-Token") or (query.get("t") or [""])[0]
                return secrets.compare_digest(supplied, server.token)

            # --- GET ---
            def do_GET(self):
                if not self._host_ok():
                    return self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                if parsed.path == "/events":
                    return self._events() if self._authorised(query) else self._json(
                        {"error": "unauthorised"}, HTTPStatus.UNAUTHORIZED)
                if parsed.path == "/api/state":
                    if not self._authorised(query):
                        return self._json({"error": "unauthorised"}, HTTPStatus.UNAUTHORIZED)
                    return self._json(server.assistant.snapshot())
                return self._static(parsed.path)

            def _static(self, path: str):
                name = "index.html" if path in ("/", "") else path.lstrip("/")
                target = (WEB_DIR / name).resolve()
                if WEB_DIR.resolve() not in target.parents or not target.is_file():
                    return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                body = target.read_bytes()
                extra = {}
                if name == "index.html":
                    body = body.replace(b"__COGNIX_TOKEN__", server.token.encode())
                    extra["Content-Security-Policy"] = (
                        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
                    ctype += "; charset=utf-8"
                self._send(200, body, ctype, extra)

            def _events(self):
                q = server.bus.subscribe()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "keep-alive")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    self.close_connection = True
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            event = q.get(timeout=15)
                            payload = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
                        except queue.Empty:
                            payload = b": keep-alive\n\n"
                        self.wfile.write(payload)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
                    pass
                finally:
                    server.bus.unsubscribe(q)

            # --- POST ---
            def do_POST(self):
                if not self._host_ok():
                    return self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                parsed = urlparse(self.path)
                if not self._authorised({}):
                    return self._json({"error": "unauthorised"}, HTTPStatus.UNAUTHORIZED)
                if not parsed.path.startswith("/api/"):
                    return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_BODY:
                    return self._json({"error": "bad request"}, HTTPStatus.BAD_REQUEST)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError
                except ValueError:
                    return self._json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
                try:
                    result = server._dispatch(parsed.path[len("/api/"):], body)
                except Exception as exc:
                    return self._json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                if result is None:
                    return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                self._json(result)

        return Handler
