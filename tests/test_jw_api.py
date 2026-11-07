"""JW-17: protected local API. Host, Origin, token, content type and CSRF are each enforced,
and a real loopback server answers only correctly authenticated same-origin requests."""

from io import BytesIO
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from jw.api import App, TOKEN_FILE, csrf, serve
from jw.contracts import canonical
from jw.workspace import Workspace

PORT = 8765


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        Workspace(self.root, create=True).close()
        self.app = App(self.root, PORT)
        self.token = self.app.token

    def call(self, method="GET", path="/status", body=None, **headers):
        raw = canonical(body).encode() if body is not None else b""
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "HTTP_HOST": f"127.0.0.1:{PORT}",
                   "HTTP_AUTHORIZATION": "Bearer " + self.token, "wsgi.input": BytesIO(raw),
                   "CONTENT_LENGTH": str(len(raw)), "CONTENT_TYPE": "application/json",
                   "HTTP_X_JW_CSRF": csrf(self.token)}
        for key, value in headers.items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        captured = {}

        def start(status, response_headers):
            captured["status"], captured["headers"] = status, dict(response_headers)

        payload = json.loads(b"".join(self.app(environ, start)))
        return int(captured["status"][:3]), payload, captured["headers"]

    def code(self, *args, **kwargs):
        status, payload, _ = self.call(*args, **kwargs)
        return status, payload.get("error", {}).get("code")

    def test_status_with_valid_token(self):
        status, payload, headers = self.call()
        self.assertEqual((200, True), (status, payload["ok"]))
        self.assertEqual("nosniff", headers["X-Content-Type-Options"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertNotIn(self.token, json.dumps(payload))

    def test_token_file_is_owner_only_and_outside_database(self):
        mode = stat.S_IMODE(os.stat(self.root / TOKEN_FILE).st_mode)
        self.assertEqual(0o600, mode)
        self.assertNotIn(self.token.encode(), (self.root / "workspace.sqlite3").read_bytes())

    def test_dns_rebinding_host_is_refused(self):
        for host in ("evil.example:8765", "127.0.0.1:9999", "127.0.0.1", "", "localhost.evil.example:8765"):
            with self.subTest(host=host):
                self.assertEqual((421, "bad_host"), self.code(HTTP_HOST=host))
        self.assertEqual(200, self.call(HTTP_HOST=f"localhost:{PORT}")[0])

    def test_cross_origin_is_refused_even_with_token(self):
        self.assertEqual((403, "bad_origin"), self.code(HTTP_ORIGIN="https://evil.example"))
        self.assertEqual((403, "bad_origin"), self.code(HTTP_ORIGIN="null"))
        self.assertEqual((403, "bad_origin"), self.code(HTTP_SEC_FETCH_SITE="cross-site"))
        self.assertEqual(200, self.call(HTTP_ORIGIN=f"http://127.0.0.1:{PORT}")[0])

    def test_missing_or_wrong_token(self):
        self.assertEqual((401, "unauthorized"), self.code(HTTP_AUTHORIZATION=None))
        self.assertEqual((401, "unauthorized"), self.code(HTTP_AUTHORIZATION="Bearer wrong"))
        self.assertEqual((401, "unauthorized"), self.code(HTTP_AUTHORIZATION=self.token))

    def test_csrf_and_content_type_block_form_posts(self):
        body = {"command": "job-add", "input": {"company": "A", "title": "B", "description": "C", "requirements": []}}
        self.assertEqual((403, "csrf"), self.code("POST", "/command", body, HTTP_X_JW_CSRF=None))
        self.assertEqual((415, "bad_content_type"),
                         self.code("POST", "/command", body, CONTENT_TYPE="application/x-www-form-urlencoded"))
        status, payload, _ = self.call("POST", "/command", body)
        self.assertEqual((200, True), (status, payload["ok"]))

    def test_unsupported_and_blocked_commands(self):
        for command, expected in (("send", (501, "unsupported_capability")), ("capture", (501, "unsupported_capability")),
                                  ("restore", (400, "unknown_command")), ("init", (400, "unknown_command")),
                                  ("rm-rf", (400, "unknown_command"))):
            with self.subTest(command=command):
                self.assertEqual(expected, self.code("POST", "/command", {"command": command, "input": {}}))
        self.assertEqual((400, "invalid_schema"), self.code("POST", "/command", {"command": "status", "x": 1}))
        self.assertEqual((413, "input_too_large"), self.code("POST", "/command", {"command": "status"},
                                                              CONTENT_LENGTH=str(2_000_000)))
        self.assertEqual((404, "not_found"), self.code("DELETE", "/command"))

    def test_real_loopback_server(self):
        server = serve(self.root, 0)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        port = server.server_port
        self.assertEqual("127.0.0.1", server.server_address[0])
        request = urllib.request.Request(f"http://127.0.0.1:{port}/status",
                                         headers={"Authorization": "Bearer " + self.token})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertTrue(json.loads(response.read())["ok"])
        bad = urllib.request.Request(f"http://127.0.0.1:{port}/status")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(bad, timeout=5)
        self.assertEqual(401, caught.exception.code)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
