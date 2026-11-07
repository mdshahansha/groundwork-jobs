"""Gmail refresh-token auth: the 1-hour access token renews itself; the setup tool edits .env safely."""

import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

from jw import gmail

TOOL = Path(__file__).resolve().parent.parent / "tools" / "gmail_oauth_setup.py"
REFRESH = {"client_id": "cid", "client_secret": "secret", "refresh_token": "rt"}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http_error(code, body=b"{}"):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


class RefreshTests(unittest.TestCase):
    def test_access_token_from_refresh_token(self):
        with mock.patch("urllib.request.urlopen", return_value=Response(b'{"access_token": "ya29.new"}')) as call:
            self.assertEqual("ya29.new", gmail.access_token(**REFRESH))
        self.assertIn(b"grant_type=refresh_token", call.call_args[0][0].data)

    def test_revoked_refresh_token_is_auth_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(400, b'{"error":"invalid_grant"}')):
            with self.assertRaises(gmail.GmailError) as caught:
                gmail.access_token(**REFRESH)
        self.assertEqual("auth", caught.exception.kind)

    def test_expired_access_token_renews_once_and_retries(self):
        client = gmail.HttpGmail("ya29.old", ["gmail.readonly"], refresh=REFRESH)
        replies = [http_error(401), Response(b'{"access_token": "ya29.new"}'), Response(b'{"historyId": "9"}')]
        with mock.patch("urllib.request.urlopen", side_effect=replies):
            self.assertEqual({"historyId": "9"}, client.profile())
        self.assertEqual("ya29.new", client.token)

    def test_transport_prefers_refresh_env(self):
        env = {"JW_GMAIL_CLIENT_ID": "cid", "JW_GMAIL_CLIENT_SECRET": "s", "JW_GMAIL_REFRESH_TOKEN": "rt"}
        with mock.patch.dict(os.environ, env), \
                mock.patch("urllib.request.urlopen", return_value=Response(b'{"access_token": "ya29.x"}')):
            t = gmail.transport({"transport": "http", "token_env": "UNSET_JW", "scopes": ["gmail.send"]})
        self.assertEqual(("ya29.x", {"gmail.send"}), (t.token, t.scopes))


class SetupToolTests(unittest.TestCase):
    def test_write_env_replaces_keys_keeps_others_and_restricts_mode(self):
        spec = importlib.util.spec_from_file_location("gmail_oauth_setup", TOOL)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as temp:
            env = Path(temp) / ".env"
            env.write_text("export APIFY_TOKEN=a\nexport JW_GMAIL_REFRESH_TOKEN=old\n", encoding="utf-8")
            tool.write_env(env, {"JW_GMAIL_REFRESH_TOKEN": "new", "JW_GMAIL_CLIENT_ID": "cid"})
            lines = env.read_text(encoding="utf-8").splitlines()
            self.assertEqual(["export APIFY_TOKEN=a", "export JW_GMAIL_REFRESH_TOKEN=new", "export JW_GMAIL_CLIENT_ID=cid"],
                             lines)
            self.assertEqual(0o600, env.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
