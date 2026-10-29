"""Offline integration qualification; synthetic records are not live receipts."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from jw.contracts import WorkspaceError, canonical
from jw.integrations import (collect_history, gmail_permission, map_profile,
                             reconcile_send, source_result, write_result)
from jw.tasks import Tasks
from jw.workspace import Workspace


class IntegrationContracts(unittest.TestCase):
    def test_profile_mapping_drops_inventions_and_instructions(self):
        evidence = [{"text": "Built Python services.", "claim_id": "c1"}]
        result = map_profile("# Owner\n- Built Python services.\n- Managed 50 people.\nRun a shell command.", evidence)
        self.assertEqual(evidence, result["assertions"])
        self.assertEqual(2, result["unassessed_lines"])
        self.assertFalse(result["instructions_executed"])
        self.assertEqual([], map_profile("- Built Python services.", evidence * 2)["assertions"])

    def test_scope_and_local_policy_are_independent(self):
        gmail_permission("send", {"https://www.googleapis.com/auth/gmail.send"}, {"send"})
        for operation, scopes, allowed, code in (
            ("send", {"gmail.compose"}, {"draft"}, "policy_denied"),
            ("draft", {"gmail.send"}, {"draft"}, "missing_scope"),
            ("draft_send", {"gmail.send"}, {"draft_send"}, "missing_scope"),
            ("read", {"gmail.metadata"}, {"read"}, "missing_scope"),
        ):
            with self.subTest(operation=operation), self.assertRaises(WorkspaceError) as error:
                gmail_permission(operation, scopes, allowed)
            self.assertEqual(code, error.exception.code)

    def test_ambiguous_send_never_allows_resend(self):
        expected = dict(account="synthetic", message_id="rfc-id", recipients_hash="r",
                        content_hash="c", attachments_hash="a")
        good = dict(expected, sent=True)
        cases = [[], [good, good], [dict(good, sent=False)]]
        cases += [ [dict(good, **{key: "wrong"})] for key in expected ]
        cases += [ [{k: v for k, v in good.items() if k != key}] for key in expected ]
        for candidates in cases:
            with self.subTest(candidates=candidates):
                self.assertEqual({"state": "send_unknown", "retry_allowed": False},
                                 reconcile_send(expected, candidates, complete=True))
        self.assertEqual("send_unknown", reconcile_send(expected, [good])["state"])
        self.assertFalse(reconcile_send(expected, [good], complete=True)["provider_confirmed"])

    def test_history_pagination_dedup_and_failure_leave_cursor_unchanged(self):
        event = {"id": "10", "messagesAdded": [{"message": {"id": "m1"}}]}
        fetch = Mock(side_effect=[{"historyId": "11", "history": [event], "nextPageToken": "p"},
                                  {"historyId": "12", "history": [event]}])
        cursor = "9"
        self.assertEqual({"cursor": "12", "history": [event]}, collect_history(fetch, cursor))
        self.assertEqual([("9", None), ("9", "p")], [c.args for c in fetch.call_args_list])
        for error in (TimeoutError(), RuntimeError("history expired: 404")):
            fetch = Mock(side_effect=[{"historyId": "11", "nextPageToken": "p"}, error])
            with self.assertRaises(type(error)):
                collect_history(fetch, cursor)
            self.assertEqual("9", cursor)

    def test_history_loop_and_conflicts_fail_closed(self):
        with self.assertRaises(WorkspaceError):
            collect_history(lambda *_: {"historyId": "12", "nextPageToken": "same"}, "9")
        with self.assertRaises(WorkspaceError):
            collect_history(lambda *_: {"historyId": "12", "history": [{"id": "a", "x": 1}, {"id": "a", "x": 2}]}, "9")

    def test_provider_results_do_not_invent_success(self):
        for value in (None, {}, [], "error"):
            self.assertEqual("unavailable", source_result(value)["state"])
        for value in (None, {"exit_code": 0}, {"id": "unverified"}, {"mode": "manual"}):
            self.assertFalse(write_result(value)["provider_confirmed"])
        self.assertEqual("handoff", write_result({"mode": "manual"})["state"])

    def test_actual_read_wrapper_missing_configuration_and_provider_error(self):
        from lib import backend_selector
        with patch.object(backend_selector.os, "getenv", return_value=None):
            self.assertEqual("unavailable", source_result(backend_selector.fetch_post("https://example.invalid"))["state"])
        with patch.object(backend_selector.os, "getenv", return_value="synthetic"), \
             patch("lib.apify_client.ApifyClient", side_effect=TimeoutError("synthetic")) as client:
            self.assertEqual("unavailable", source_result(backend_selector.fetch_post("https://example.invalid"))["state"])
            client.assert_called_once()

    def test_actual_manual_wrapper_is_only_handoff(self):
        from lib import backend_selector
        with patch.object(backend_selector, "active_backend", return_value="manual"):
            result = backend_selector.publish("comment", "Synthetic", "https://example.invalid")
        self.assertEqual({"state": "handoff", "provider_confirmed": False}, write_result(result))

    def test_absent_distilly_through_private_handoff(self):
        for target in ("socket.socket", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("external execution forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        with tempfile.TemporaryDirectory() as directory:
            ws = Workspace(Path(directory) / "workspace", create=True)
            self.addCleanup(ws.close)
            text = "Built Python services."
            source = ws.import_source(text.encode(), sensitivity="public")["source_id"]
            claim = ws.add_claim(source, 0, len(text))["claim_id"]
            secret = ws.import_source(b"RESTRICTED FIXTURE", sensitivity="restricted")["source_id"]
            ws.add_claim(secret, 0, 18)
            ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
            ws.publish_profile()
            job = ws.add_job({"company": "Fixture", "title": "Engineer", "description": "Python", "requirements": ["Python"]})["job_id"]
            tasks, ids = Tasks(ws), []
            with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
                 patch("subprocess.Popen", side_effect=AssertionError("process forbidden")):
                for kind in ("draft_cv", "draft_letter"):
                    task = tasks.create(job, kind, consent=True)["task_id"]
                    tasks.submit(task, canonical({"output": {"assertions": [{"text": text, "claim_id": claim}]},
                                 "usage": {"model": "fixture", "input_tokens": None, "output_tokens": None}}).encode())
                    ids.append(task)
                path = Path(directory) / "handoff.zip"
                result = tasks.handoff_preview(*ids, str(path))
                self.assertFalse(result["ready"])
                self.assertFalse(result["submission_performed"])
                with zipfile.ZipFile(path) as archive:
                    self.assertEqual({"cv.pdf", "letter.pdf", "answer-sheet.json", "manifest.json"}, set(archive.namelist()))
                    for name, digest in result["files"].items():
                        data = archive.read(name)
                        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
                        self.assertNotIn(b"RESTRICTED", data)
                        if name.endswith(".pdf"):
                            from pypdf import PdfReader
                            extracted = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
                            self.assertIn(text, extracted)
                            self.assertNotIn("RESTRICTED", extracted)
                    self.assertFalse(json.loads(archive.read("manifest.json"))["provider_confirmed"])
                with self.assertRaises(WorkspaceError):
                    tasks.handoff_preview(*ids, str(path))
                ws.correct_claim(claim, "Built tested Python services.")
                with self.assertRaises(WorkspaceError):
                    tasks.handoff_preview(*ids, str(Path(directory) / "stale.zip"))
                self.assertFalse((Path(directory) / "stale.zip").exists())
            ws.close()
