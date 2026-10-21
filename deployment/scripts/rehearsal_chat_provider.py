"""Fixed chat completion for the isolated Docker rehearsal network only."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *_args):
        pass

    def reply(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(type(self).calls)

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        type(self).calls += 1
        content = {"actions": [{"type": "add", "title": "Container AI", "category": "work",
                                "start_time": "14:00", "end_time": "14:30"}],
                   "explanation": "Added Container AI.", "ask": None}
        self.reply({"id": "rehearsal", "object": "chat.completion", "created": 0,
                    "model": "rehearsal-fixture", "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": json.dumps(content)},
                    "finish_reason": "stop"}]})


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
