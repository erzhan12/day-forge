"""Fixed chat completion for the isolated Docker rehearsal network only."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def pending_reply(text):
    """Deterministic metadata for the pending-intent container protocol checks."""
    if text.startswith("Add Container "):
        name = text.removeprefix("Add ").split(";")[0]
        partial = name == "Container partial"
        omitted = name == "Container partial-omitted"
        if partial:
            return {
                "actions": [
                    {"type": "add", "title": "Container accepted", "category": "work",
                     "start_time": "13:00", "end_time": "13:30"},
                    {"type": "add", "title": "Container unresolved", "category": "work",
                     "start_time": "23:00", "end_time": "23:30"},
                ],
                "explanation": "Apply available changes.", "ask": None,
                "intent_decision": "new", "pending_actions": [],
            }
        title = "Container unresolved omitted" if omitted else name
        return {
            "actions": [{"type": "add", "title": "Container accepted omitted",
                         "category": "work", "start_time": "12:00", "end_time": "12:30"}]
            if omitted else [],
            "explanation": "Need a time.", "ask": None if omitted else "What start time?",
            "intent_decision": "new",
            "pending_actions": [{"type": "add", "task_id": None, "target_ids": [],
                                 "known_fields": {"title": title, "category": "work",
                                                  "duration_minutes": 30},
                                 "missing_fields": ["start_time"] if name == "Container narrow"
                                 else ["start_time", "end_time"]}],
        }
    titles = {"14:00": "Container pending", "15:00": "Container unresolved",
              "19:00": "Container unresolved omitted",
              "21:00": "Container procedural", "08:00": "Container anchored",
              "10:00": "Container anchored",
              "20:00": "Container narrow"}
    if text not in titles:
        raise ValueError("Unexpected pending fixture turn")
    return {"actions": [{"type": "add", "title": titles[text], "category": "work",
                         "start_time": text, "end_time": text[:3] + "30"}],
            "explanation": "Added.", "ask": None, "intent_decision": "continue",
            "pending_actions": []}


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
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls += 1
        content = {"actions": [{"type": "add", "title": "Container AI", "category": "work",
                                "start_time": "14:00", "end_time": "14:30"}],
                   "explanation": "Added Container AI.", "ask": None}
        if request.get("model") == "rehearsal-pending-fixture":
            content = pending_reply(request["messages"][-1]["content"])
        self.reply({"id": "rehearsal", "object": "chat.completion", "created": 0,
                    "model": "rehearsal-fixture", "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": json.dumps(content)},
                    "finish_reason": "stop"}]})


if __name__ == "__main__":
    # Container-only fixture: Compose exposes no port and uses an internal network.
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
