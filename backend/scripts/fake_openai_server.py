"""Minimal OpenAI-compatible stub for Playwright e2e (local providers only)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"data": [{"id": self.server.model_id, "object": "model"}]})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(length) if length else b""
        if self.path.rstrip("/").endswith("/chat/completions"):
            content = self.server.fixed_content
            self._json(
                200,
                {
                    "id": "chatcmpl-stub",
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
                },
            )
            return
        self._json(404, {"error": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8765, model_id: str = "stub-model", content: str | None = None) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    server.model_id = model_id
    server.fixed_content = content or json.dumps(
        {
            "question": "What is policy X?",
            "answer": "Policy X requires VPN.",
            "supporting_quote": "Remote work requires VPN.",
        }
    )
    print(f"fake openai on http://{host}:{port}/v1 model={model_id}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default="stub-model")
    args = parser.parse_args()
    serve(port=args.port, model_id=args.model)
