"""A 127.0.0.1-only HTTP server for `--dev` and `--screenshot`, never for a normal app start.

It serves the files under `web/` and maps `POST /api/<name>` (body `{"args": [...]}`) to the
bridge method of that name, if the bridge lists it in `EXPOSED`. The page uses it through
`web/js/api.js` whenever it does not run inside pywebview.
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from coppertrail.ui.bridge import Bridge

WEB_DIR = Path(__file__).parent / "web"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ttf": "font/ttf",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".txt": "text/plain; charset=utf-8",
}


def _static_file(url_path: str) -> Path | None:
    """The file under WEB_DIR for a URL path, or None (outside WEB_DIR, missing, unknown type)."""
    root = WEB_DIR.resolve()
    rel = unquote(urlsplit(url_path).path).lstrip("/") or "index.html"
    try:
        target = (root / rel).resolve()
    except (OSError, ValueError):
        return None
    if not target.is_relative_to(root) or not target.is_file():
        return None
    if target.suffix.lower() not in CONTENT_TYPES:
        return None
    return target


def _handler(bridge: Bridge) -> type[BaseHTTPRequestHandler]:
    exposed = frozenset(type(bridge).EXPOSED)
    unlocked = frozenset(getattr(type(bridge), "UNLOCKED", ()))  # they lock for themselves
    lock = bridge.lock  # the bridge is not thread-safe; one call at a time

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, CONTENT_TYPES[".json"])

        def _foreign(self) -> bool:
            """Refuse other Host names (DNS rebinding) with 403."""
            port = self.server.server_address[1]
            if self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                return False
            self._send(HTTPStatus.FORBIDDEN, b"forbidden", CONTENT_TYPES[".txt"])
            return True

        def do_GET(self):  # noqa: N802
            if self._foreign():
                return
            if urlsplit(self.path).path == "/api":
                self._json(HTTPStatus.OK, {"dev": True})  # api.js: "not inside pywebview"
                return
            target = _static_file(self.path)
            if target is None:
                self._send(HTTPStatus.NOT_FOUND, b"not found", CONTENT_TYPES[".txt"])
                return
            self._send(HTTPStatus.OK, target.read_bytes(), CONTENT_TYPES[target.suffix.lower()])

        def do_POST(self):  # noqa: N802
            if self._foreign():
                return
            # JSON only: a cross-site page cannot send it without a CORS preflight, which
            # this server never answers.
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                self._send(HTTPStatus.FORBIDDEN, b"forbidden", CONTENT_TYPES[".txt"])
                return
            path = urlsplit(self.path).path
            name = path.removeprefix("/api/") if path.startswith("/api/") else ""
            if name not in exposed:
                self._json(HTTPStatus.NOT_FOUND, {"error": "unknown method"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = json.loads(self.rfile.read(length) or b"{}")
                args = raw.get("args", [])
                if name in unlocked:
                    result = getattr(bridge, name)(*args)
                else:
                    with lock:
                        result = getattr(bridge, name)(*args)
            except Exception as exc:  # noqa: BLE001 - reported to the page, like pywebview does
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(exc).__name__}: {exc}"}
                )
                return
            self._json(HTTPStatus.OK, {"result": result})

    return Handler


def serve(bridge: Bridge, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Start the server in a daemon thread; returns it and its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(bridge))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, real_port = server.server_address[:2]
    return server, f"http://{host}:{real_port}/"
