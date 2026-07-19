"""Tiny localhost UI bridge. Every UI mutation is materialized as a file."""

import json
import mimetypes
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


class ControlServer(ThreadingHTTPServer):
    def __init__(self, address, root: Path):
        self.root = root.resolve()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: ControlServer

    def log_message(self, *_args):
        return

    def _reply(self, code=200, body=b"ok", content_type="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/status.json":
            target = self.server.root / "status.json"
        elif path in ("/", "/index.html"):
            target = self.server.root / "dashboard" / "index.html"
        else:
            target = self.server.root / "dashboard" / path.lstrip("/")
        try:
            target = target.resolve()
            if self.server.root not in target.parents or not target.is_file():
                raise OSError
            self._reply(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        except OSError:
            self._reply(404, b"not found")

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(size) or b"{}")
            action = urlparse(self.path).path.removeprefix("/action/")
            root = self.server.root
            if action == "create":
                pass  # the launcher has already created the deterministic workspace
            elif action == "task":
                (root / "task" / "task.md").write_text(str(data.get("text", "")), encoding="utf-8")
            elif action == "data":
                import base64
                name = Path(str(data.get("name", "data.bin"))).name
                (root / "workspace" / "surface" / name).write_bytes(base64.b64decode(data.get("content", "")))
            elif action == "start":
                (root / "start.flag").write_text("start", encoding="utf-8")
            elif action == "stop":
                (root / "stop.flag").write_text("stop", encoding="utf-8")
            elif action == "verdict":
                verdict = str(data.get("verdict", "")).upper()
                if verdict not in ("INEVITABLE", "PREDICTABLE"):
                    raise ValueError("invalid verdict")
                rounds = sorted((root / "verdicts").glob("verdict_*.json"))
                out = root / "verdicts" / f"verdict_{len(rounds) + 1:03d}.json"
                out.write_text(json.dumps({"verdict": verdict, "reason": data.get("reason", "")},
                                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            else:
                return self._reply(404, b"unknown action")
            self._reply(200, b'{"ok":true}', "application/json")
        except (ValueError, OSError) as exc:
            self._reply(400, json.dumps({"error": str(exc)}).encode(), "application/json")


def serve(root: Path, port: int = 8765) -> None:
    server = ControlServer(("127.0.0.1", port), root)

    def watch():
        start = root / "start.flag"
        while True:
            if start.exists():
                start.unlink(missing_ok=True)
                pid = root / "muto.pid"
                if not pid.exists():
                    subprocess.Popen([sys.executable, "-m", "muto", "run", "--attach"],
                                     cwd=root, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            threading.Event().wait(0.5)

    threading.Thread(target=watch, daemon=True).start()
    server.serve_forever()
