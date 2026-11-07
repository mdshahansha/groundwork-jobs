"""JW-17: protected local API on 127.0.0.1 (FR-SEC-01, FR-SEC-03, FR-CAP-01 prerequisite).

Every request passes, in order:
1. Host: exactly `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding cannot reach it).
2. Origin / Sec-Fetch-Site: a browser request must come from this same origin; cross-site
   requests are refused even with a valid token. Requests without Origin (CLI, curl) pass.
3. Authorization: `Bearer <token>`, compared in constant time. The token is random per install,
   kept in `api-token` (mode 0600) beside the database, never in the database, so it never
   reaches backups, logs or responses.
4. POST only with `Content-Type: application/json` and a body of at most 1 MB, plus
   `X-JW-CSRF` equal to the token's CSRF derivative: an HTML form cannot set either.
Responses are JSON with `nosniff`, `no-store`, a deny-all CSP and no CORS headers.
External-action commands stay unsupported here exactly as on the CLI.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
from wsgiref.simple_server import WSGIRequestHandler, make_server

from .contracts import MAX_BYTES, WorkspaceError, canonical, parse_json, require

TOKEN_FILE = "api-token"
HEADERS = [("Content-Type", "application/json; charset=utf-8"), ("X-Content-Type-Options", "nosniff"),
           ("Cache-Control", "no-store"), ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
           ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY")]
BLOCKED = {"restore", "init"}


def token(root):
    """Create the per-install token on first use; owner-only permissions."""
    path = Path(root) / TOKEN_FILE
    if not path.is_file():
        value = secrets.token_urlsafe(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
    return path.read_text(encoding="utf-8").strip()


def csrf(value):
    return hmac.new(value.encode(), b"jw-csrf-v1", hashlib.sha256).hexdigest()


class App:
    def __init__(self, root, port):
        self.root = str(root)
        self.port = port
        self.token = token(root)
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{host}" for host in self.hosts}

    def _reply(self, start, status, body):
        start(status, list(HEADERS))
        return [canonical(body).encode("utf-8")]

    def _error(self, start, status, code, message):
        return self._reply(start, status, {"ok": False, "error": {"code": code, "message": message}})

    def __call__(self, environ, start):
        host = environ.get("HTTP_HOST", "")
        if host not in self.hosts:
            return self._error(start, "421 Misdirected Request", "bad_host", "Host is not this local API.")
        origin = environ.get("HTTP_ORIGIN")
        if origin is not None and origin not in self.origins:
            return self._error(start, "403 Forbidden", "bad_origin", "Cross-origin requests are refused.")
        if environ.get("HTTP_SEC_FETCH_SITE", "same-origin") not in ("same-origin", "none"):
            return self._error(start, "403 Forbidden", "bad_origin", "Cross-site requests are refused.")
        auth = environ.get("HTTP_AUTHORIZATION", "")
        if not (auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].encode(), self.token.encode())):
            return self._error(start, "401 Unauthorized", "unauthorized", "A valid bearer token is required.")
        method, path = environ.get("REQUEST_METHOD"), environ.get("PATH_INFO")
        if method == "GET" and path == "/status":
            return self._run(start, "status", {})
        if method != "POST" or path != "/command":
            return self._error(start, "404 Not Found", "not_found", "Use GET /status or POST /command.")
        if environ.get("CONTENT_TYPE", "").split(";")[0].strip() != "application/json":
            return self._error(start, "415 Unsupported Media Type", "bad_content_type", "Send application/json.")
        if not hmac.compare_digest(environ.get("HTTP_X_JW_CSRF", "").encode(), csrf(self.token).encode()):
            return self._error(start, "403 Forbidden", "csrf", "Missing or wrong X-JW-CSRF header.")
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BYTES:
            return self._error(start, "413 Content Too Large", "input_too_large", "Body must be 1 byte to 1 MB.")
        try:
            request = parse_json(environ["wsgi.input"].read(length))
            require(isinstance(request, dict) and set(request) <= {"command", "input"} and "command" in request,
                    "invalid_schema", "Body is {command, input}.")
        except WorkspaceError as exc:
            return self._error(start, "400 Bad Request", exc.code, str(exc))
        return self._run(start, request["command"], request.get("input", {}))

    def _run(self, start, command, data):
        from .cli import COMMANDS, UNSUPPORTED, dispatch
        from .workspace import Workspace

        if command in UNSUPPORTED:
            return self._error(start, "501 Not Implemented", "unsupported_capability",
                               "Capability is disabled; no external action occurred.")
        if command in BLOCKED or (command not in COMMANDS and command != "status"):
            return self._error(start, "400 Bad Request", "unknown_command", "Command is not available over the API.")
        ws = None
        try:
            ws = Workspace(self.root)
            return self._reply(start, "200 OK", {"ok": True, "result": dispatch(ws, command, data)})
        except WorkspaceError as exc:
            return self._error(start, "400 Bad Request", exc.code, str(exc))
        except (OSError, sqlite3.Error):
            return self._error(start, "500 Internal Server Error", "storage_error", "Storage operation failed.")
        finally:
            if ws:
                ws.close()


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        # Request lines can carry paths a user typed; nothing is logged.
        pass


def serve(root, port=8765):
    """Bind loopback only. Never 0.0.0.0."""
    server = make_server("127.0.0.1", port, lambda environ, start: None, handler_class=_QuietHandler)
    # Port 0 picks a free port; the Host allowlist must name the real one.
    server.set_app(App(root, server.server_port))
    return server
