"""JW-06: model pin in every dependency fingerprint, and ranking refresh from recorded inputs."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jw.contracts import WorkspaceError, canonical
from jw.tasks import Tasks
from jw.workspace import Workspace
from test_jw_ranking import assessment, policy


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name) / "workspace", create=True)
        self.addCleanup(lambda: self.ws.close())
        text = "Deployed services with Docker Compose and Python."
        self.source = self.ws.import_source(text.encode(), sensitivity="public")["source_id"]
        self.claim = self.ws.add_claim(self.source, 0, len(text))["claim_id"]
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        self.ws.set_policy(policy())
        self.job = self.ws.add_job({"company": "Fixture Co", "title": "Platform Engineer",
                                    "description": "Synthetic listing.", "requirements": ["Python", "Kubernetes"]})["job_id"]
        self.mapping = [{"index": 0, "state": "supported", "claim_id": self.claim},
                        {"index": 1, "state": "unknown", "claim_id": None}]

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def submit(self, task, model):
        return Tasks(self.ws).submit(task, canonical({"output": {"assertions": [
            {"text": "Deployed services with Docker Compose and Python.", "claim_id": self.claim}]},
            "usage": {"model": model, "input_tokens": None, "output_tokens": None}}).encode())

    def test_pin_changes_versions_and_stales_pending_tasks(self):
        tasks = Tasks(self.ws)
        task = tasks.create(self.job, "draft_letter", consent=True)["task_id"]
        self.assertEqual("host-unspecified", self.ws.versions()["model"])
        self.ws.pin_model("model-a")
        self.assertEqual("model-a", self.ws.versions()["model"])
        self.assertCode("stale_input", tasks.packet, task)

    def test_output_from_another_model_is_refused(self):
        self.ws.pin_model("model-a")
        task = Tasks(self.ws).create(self.job, "draft_letter", consent=True)["task_id"]
        self.assertCode("model_mismatch", self.submit, task, "model-b")
        self.assertEqual("completed", self.submit(task, "model-a")["state"])

    def test_unpin_and_bad_names(self):
        self.ws.pin_model("model-a")
        self.assertIsNone(self.ws.pin_model(None)["model"])
        for bad in ("", " padded ", 7, "x" * 201):
            with self.subTest(bad=bad):
                self.assertCode("invalid_schema", self.ws.pin_model, bad)

    def test_fresh_ranking_is_unchanged(self):
        self.ws.rank(self.job, self.mapping, assessment())
        self.assertEqual({"refreshed": [], "unchanged": [self.job], "failed": []}, self.ws.refresh_rankings())

    def test_dependency_change_reranks_from_recorded_inputs(self):
        first = self.ws.rank(self.job, self.mapping, assessment())
        self.ws.pin_model("model-a")
        report = self.ws.refresh_rankings()
        self.assertEqual(self.job, report["refreshed"][0]["job_id"])
        current = self.ws.rankings()["shortlist"][0]
        self.assertNotEqual(first["ranking_id"], current["ranking_id"])
        self.assertEqual(first["score"], current["score"])

    def test_next_day_refreshes_freshness(self):
        self.ws.rank(self.job, self.mapping, assessment())
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with patch("jw.workspace.utcnow", return_value=tomorrow):
            self.assertEqual(1, len(self.ws.refresh_rankings()["refreshed"]))

    def test_revoked_evidence_leaves_ranking_outdated_with_reason(self):
        other = self.ws.import_source(b"Built Python tools.", sensitivity="public")["source_id"]
        self.ws.add_claim(other, 0, 19)
        self.ws.publish_profile()
        self.ws.rank(self.job, self.mapping, assessment())
        self.ws.delete_source(self.source)
        self.ws.publish_profile()
        report = self.ws.refresh_rankings()
        self.assertEqual([{"job_id": self.job, "code": "unknown_claim"}], report["failed"])
        self.assertEqual([], self.ws.rankings()["shortlist"])


if __name__ == "__main__":
    unittest.main()
