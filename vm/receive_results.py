"""Receive test reports and Windows binaries from the QEMU guest on localhost."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


RESULTS = Path(__file__).resolve().parent / "results"
ALLOWED = {
    "unit-tests.txt",
    "probe-log.txt",
    "device-report.json",
    "Nadajnik.exe",
    "Odbiornik.exe",
}
MAX_BYTES = 100 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        name = self.path.removeprefix("/")
        length = int(self.headers.get("Content-Length", "0"))
        if name not in ALLOWED or not 0 < length <= MAX_BYTES:
            self.send_error(400, "Invalid upload")
            return
        RESULTS.mkdir(exist_ok=True)
        target = RESULTS / name
        temporary = RESULTS / f"{name}.part"
        with temporary.open("wb") as output:
            remaining = length
            while remaining:
                data = self.rfile.read(min(1024 * 1024, remaining))
                if not data:
                    temporary.unlink(missing_ok=True)
                    self.send_error(400, "Incomplete upload")
                    return
                output.write(data)
                remaining -= len(data)
        temporary.replace(target)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK\n")
        print(f"Received {name}: {length} bytes", flush=True)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
