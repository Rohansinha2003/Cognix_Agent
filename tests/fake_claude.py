"""A mock of the Claude Messages streaming API, so the real Anthropic SDK can be
driven end to end without a network or an API key.

The script is ``(request_body) -> reply`` where reply is
``{"text": str}``, ``{"tool": name, "args": dict}`` (optionally with text), or
``{"refuse": True}`` / ``{"status": 401}``.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeClaude:
    def __init__(self, script, port: int = 0):
        self.script = script
        self.requests: list = []
        self.headers: list = []
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self._httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def start(self) -> "FakeClaude":
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                fake.requests.append(body)
                fake.headers.append({k.lower(): v for k, v in self.headers.items()})
                reply = fake.script(body)
                if reply.get("status"):
                    data = json.dumps({"type": "error", "error": {"type": "authentication_error",
                                                                 "message": "invalid x-api-key"}}).encode()
                    self.send_response(reply["status"])
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()

                def send(event: dict):
                    self.wfile.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
                    self.wfile.flush()

                send({"type": "message_start", "message": {
                    "id": f"msg_{len(fake.requests)}", "type": "message", "role": "assistant",
                    "model": body["model"], "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 12, "output_tokens": 1}}})
                index = 0
                if reply.get("text"):
                    send({"type": "content_block_start", "index": index,
                          "content_block": {"type": "text", "text": ""}})
                    for word in reply["text"].split(" "):
                        send({"type": "content_block_delta", "index": index,
                              "delta": {"type": "text_delta", "text": word + " "}})
                    send({"type": "content_block_stop", "index": index})
                    index += 1
                stop = "refusal" if reply.get("refuse") else "end_turn"
                if reply.get("tool"):
                    stop = "tool_use"
                    send({"type": "content_block_start", "index": index, "content_block": {
                        "type": "tool_use", "id": f"toolu_{len(fake.requests)}", "name": reply["tool"],
                        "input": {}}})
                    args = json.dumps(reply.get("args", {}))
                    half = len(args) // 2
                    for piece in (args[:half], args[half:]):
                        send({"type": "content_block_delta", "index": index,
                              "delta": {"type": "input_json_delta", "partial_json": piece}})
                    send({"type": "content_block_stop", "index": index})
                send({"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                      "usage": {"output_tokens": 30}})
                send({"type": "message_stop"})

        return Handler
