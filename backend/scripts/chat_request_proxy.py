"""Loopback-only response-loss/parallelism rehearsal for release_browser_server.

Usage: uv run python backend/scripts/chat_request_proxy.py /tmp/FIXTURE_ROOT
Listens on 127.0.0.1:8009 and forwards to 127.0.0.1:8008. Set the fixture's
chat-proxy-mode file to pass, drop-once, drop-until-recover, empty-once, or parallel.
Only chat responses are disturbed. Real provider calls remain in the backend.
"""

import hashlib
import http.client
import json
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Expected /tmp/FIXTURE_ROOT")
    root = Path(sys.argv[1]).resolve()
    if not root.is_relative_to(Path("/tmp").resolve()) or not (
        root / "release-fixture.marker"
    ).is_file():
        raise SystemExit("Use a marked release_browser_server fixture under /tmp")
    lock = threading.Lock()
    attempts = {}

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def forward(self, body):
            connection = http.client.HTTPConnection("127.0.0.1", 8008, timeout=150)
            try:
                headers = dict(self.headers)
                headers["Connection"] = "close"
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                return response.status, response.getheaders(), response.read()
            finally:
                connection.close()

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            chat = self.command == "POST" and self.path.endswith("/chat/")
            mode = (root / "chat-proxy-mode").read_text().strip() if (
                root / "chat-proxy-mode"
            ).exists() else "pass"
            identity = json.loads(body).get("request_id") if chat else None
            with lock:
                attempt = attempts.get(identity, 0) + 1
                if chat:
                    attempts[identity] = attempt
            if chat and mode == "parallel" and attempt == 1:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: self.forward(body), range(2)))
            else:
                results = [self.forward(body)]
            dropped = chat and (
                mode == "drop-until-recover" or (mode == "drop-once" and attempt == 1)
            )
            emptied = chat and mode == "empty-once" and attempt == 1 and results[0][0] == 200
            if chat:
                with lock, (root / "chat-proxy-evidence.jsonl").open("a") as file:
                    file.write(json.dumps({
                        "request_id": identity, "body_sha256": hashlib.sha256(body).hexdigest(),
                        "attempt": attempt, "mode": mode, "response_dropped": dropped,
                        "response_emptied": emptied,
                        "upstream_statuses": [item[0] for item in results],
                    }) + "\n")
            if dropped:
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            status, headers, payload = next(
                (item for item in results if item[0] == 200), results[0]
            )
            if emptied:
                payload = b""
            self.send_response(status)
            for name, value in headers:
                if name.lower() not in {"connection", "transfer-encoding", "content-length"}:
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = handle_request
        do_POST = handle_request
        do_PATCH = handle_request
        do_DELETE = handle_request

    print("Chat rehearsal proxy: http://127.0.0.1:8009", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8009), Proxy).serve_forever()


if __name__ == "__main__":
    main()
