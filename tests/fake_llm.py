"""A tiny OpenAI-compatible server that stands in for LM Studio in tests.

It streams scripted replies, so the real tool-calling loop can be exercised
without a model. The script is a function ``(messages) -> reply`` where reply is
``{"text": str}`` or ``{"tool": name, "args": dict}`` (optionally both).

Run standalone to poke at the app by hand:  python tests/fake_llm.py 1234
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def demo_script(messages: list) -> dict:
    """Find a file when asked, then describe what came back."""
    last = messages[-1]
    if last["role"] == "tool":
        body = last["content"]
        if body.startswith("Found"):
            first = body.split("\n")[1].split(" — ")[0].lstrip("1. ") if "\n" in body else "it"
            return {"text": f"I found a few. The newest is {first}. Want me to open it?"}
        return {"text": "Done."}
    text = str(last["content"]).lower()
    if "pdf" in text or "find" in text:
        return {"text": "", "tool": "find_files", "args": {"query": "", "kind": "pdf", "limit": 6}}
    if "time" in text:
        return {"tool": "system_info", "args": {}}
    return {"text": "I'm a scripted stand-in for a local model, so I can only say this. **Bold** and `code` work."}


class FakeLLM:
    def __init__(self, script=demo_script, port: int = 0, model: str = "fake-model", delay: float = 0.0,
                 reject_tools: bool = False):
        self.script = script
        self.model = model
        self.delay = delay
        self.reject_tools = reject_tools
        self.requests: list = []
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> "FakeLLM":
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

            def _json(self, data, status=200):
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.rstrip("/").endswith("/models"):
                    return self._json({"object": "list", "data": [
                        {"id": fake.model, "object": "model"},
                        {"id": "text-embedding-nomic", "object": "model"},
                    ]})
                self._json({"error": "not found"}, 404)

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                fake.requests.append(payload)
                if fake.reject_tools and payload.get("tools"):
                    return self._json({"error": {"message": "This model does not support tools."}}, 400)
                reply = fake.script(payload["messages"])
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()

                def chunk(delta, finish=None):
                    data = {"id": "c1", "object": "chat.completion.chunk", "model": fake.model,
                            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                    self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(fake.delay)

                try:
                    chunk({"role": "assistant", "content": ""})
                    words = reply.get("text", "").split(" ") if reply.get("text") else []
                    for i, word in enumerate(words):
                        chunk({"content": word + (" " if i < len(words) - 1 else "")})
                    if reply.get("tool"):
                        args = json.dumps(reply.get("args", {}))
                        chunk({"tool_calls": [{"index": 0, "id": f"call_{len(fake.requests)}", "type": "function",
                                               "function": {"name": reply["tool"], "arguments": ""}}]})
                        half = len(args) // 2
                        for piece in (args[:half], args[half:]):
                            chunk({"tool_calls": [{"index": 0, "function": {"arguments": piece}}]})
                    chunk({}, "tool_calls" if reply.get("tool") else "stop")
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        return Handler


if __name__ == "__main__":
    server = FakeLLM(port=int(sys.argv[1]) if len(sys.argv) > 1 else 1234, delay=0.04).start()
    print(f"Fake LM Studio at {server.url} (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
