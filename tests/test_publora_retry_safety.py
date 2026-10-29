"""Offline POST retry contracts; no environment loading or real sessions."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import requests


# Import in an isolated package to bypass lib.__init__'s load_env call.
_package = ModuleType("_publora_retry_tests")
_package.__path__ = []
_env = ModuleType("_publora_retry_tests._env")
_env.load_env = Mock(side_effect=AssertionError("must not load credentials"))
_spec = importlib.util.spec_from_file_location(
    "_publora_retry_tests.publora_client",
    Path(__file__).resolve().parents[1] / "lib" / "publora_client.py",
)
publora = importlib.util.module_from_spec(_spec)
with patch.dict(sys.modules, {_package.__name__: _package, _env.__name__: _env}):
    _spec.loader.exec_module(publora)


class PubloraRetrySafety(unittest.TestCase):
    def setUp(self):
        self.client = publora.PubloraClient.__new__(publora.PubloraClient)
        self.client.timeout = 12.5
        self.client._session = Mock(spec=requests.Session)
        self.post = self.client._session.post
        # Keep regression runs fast even if the retry decorator returns.
        sleeper = patch.object(publora.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def invoke(self, key):
        return self.client._post("/create-post", {"content": "hello"}, idempotency_key=key)

    def test_transport_errors_are_not_retried(self):
        for key in (None, "unverified-key"):
            for error_type in (requests.Timeout, requests.ConnectionError):
                with self.subTest(key=key, error=error_type.__name__):
                    self.post.reset_mock()
                    error = error_type("ambiguous outcome")
                    self.post.side_effect = error
                    with self.assertRaises(error_type) as caught:
                        self.invoke(key)
                    self.assertIs(caught.exception, error)
                    self.post.assert_called_once()

    def test_http_errors_are_not_retried(self):
        for key in (None, "unverified-key"):
            for status in (408, 429, *range(500, 600)):
                for is_json in (True, False):
                    with self.subTest(key=key, status=status, json=is_json):
                        self.post.reset_mock()
                        response = Mock(status_code=status, text="upstream unavailable")
                        if is_json:
                            response.json.return_value = {"error": "unavailable"}
                        else:
                            response.json.side_effect = ValueError("invalid JSON")
                        self.post.return_value = response
                        with self.assertRaises(publora.PubloraError) as caught:
                            self.invoke(key)
                        body = {"error": "unavailable" if is_json else response.text}
                        self.assertEqual(str(caught.exception), f"HTTP {status}: {body}")
                        self.post.assert_called_once()

    def test_non_json_success_is_not_retried(self):
        for key in (None, "unverified-key"):
            with self.subTest(key=key):
                self.post.reset_mock()
                error = ValueError("invalid JSON")
                response = Mock(status_code=200, text="not JSON")
                response.json.side_effect = error
                self.post.return_value = response
                with self.assertRaises(publora.PubloraError) as caught:
                    self.invoke(key)
                self.assertEqual(str(caught.exception), "non-JSON response: not JSON")
                self.assertIs(caught.exception.__cause__, error)
                self.post.assert_called_once()

    def test_success_preserves_response_and_request_options(self):
        for key in (None, "unverified-key"):
            with self.subTest(key=key):
                self.post.reset_mock()
                result = {"postGroupId": "example"}
                self.post.return_value = Mock(status_code=201)
                self.post.return_value.json.return_value = result
                self.assertIs(self.invoke(key), result)
                self.post.assert_called_once_with(
                    self.client.BASE_URL + "/create-post",
                    json={"content": "hello"},
                    headers=None if key is None else {"Idempotency-Key": key},
                    timeout=12.5,
                    allow_redirects=False,
                )

    def test_create_post_preserves_normalization_and_idempotency_header(self):
        result = {"postGroupId": "example"}
        self.post.return_value = Mock(status_code=201)
        self.post.return_value.json.return_value = result
        with patch.object(publora, "uuid4", return_value="example-key"):
            actual = self.client.create_post(
                content="hello", platforms=[{"platformId": "linkedin-example"}],
                scheduled_time="2026-11-01T12:00:00Z",
                media_urls=["https://example.com/image.png"],
            )
        self.assertIs(actual, result)
        self.post.assert_called_once_with(
            self.client.BASE_URL + "/create-post",
            json={"content": "hello", "platforms": ["linkedin-example"],
                  "scheduledTime": "2026-11-01T12:00:00Z",
                  "mediaUrls": ["https://example.com/image.png"]},
            headers={"Idempotency-Key": "example-key"},
            timeout=12.5, allow_redirects=False,
        )


if __name__ == "__main__":
    unittest.main()
