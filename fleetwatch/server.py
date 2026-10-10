"""Thin HTTP shell over ``api.handle`` using only the standard library."""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .api import handle
from .registry import DeviceRegistry

log = logging.getLogger("fleetwatch")
MAX_BODY_BYTES = 64 * 1024


def make_server(registry: DeviceRegistry, host: str = "127.0.0.1", port: int = 8000):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FleetWatch/0.1"

        def _respond(self, status: int, payload) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _dispatch(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._respond(400, {"error": "invalid Content-Length"})
            if length > MAX_BODY_BYTES:
                return self._respond(413, {"error": "request body too large"})
            body = self.rfile.read(length) if length else b""
            try:
                status, payload = handle(registry, self.command, self.path, body)
            except Exception:  # last-resort guard: never leak a traceback
                log.exception("unhandled error on %s %s", self.command, self.path)
                status, payload = 500, {"error": "internal server error"}
            log.info("%s %s -> %s", self.command, self.path, status)
            self._respond(status, payload)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _dispatch

        def log_message(self, *args) -> None:  # we log via `logging` instead
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
