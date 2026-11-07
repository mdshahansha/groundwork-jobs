"""E2E JW-25: the M1 scenarios not covered in-process (M1-02, M1-07, M1-08, M1-11), through the CLI."""

import os
import unittest

from e2e_support import CV, E2E


class M1RemainingE2E(E2E):
    def test_m1_02_conflict_blocks_publication_until_corrected_and_unsupported_text_is_refused(self):
        text = "Worked at Fixture Co from 2019 to 2021."
        source = self.ok("source-import", None, "--sensitivity", "public", raw=text.encode())["source_id"]
        claim = self.ok("claim-add", {"source_id": source, "start": 0, "end": len(text), "state": "conflict"})["claim_id"]
        self.ok("profile-set", {"name": "Synthetic Candidate", "email": "candidate@example.invalid"})
        self.fails("profile_conflict", "profile-publish")
        corrected = self.ok("claim-correct", {"claim_id": claim, "text": "Worked at Fixture Co from 2019 to 2022."})
        self.ok("profile-publish")
        job = self.job()
        task = self.ok("task-create", {"job_id": job, "kind": "draft_cv", "consent": True})["task_id"]
        code, out = self.cli("task-submit", {"task_id": task, "response": {
            "output": {"assertions": [{"text": "Holds a PhD in distributed systems.", "claim_id": corrected["claim_id"]}]},
            "usage": {"model": "synthetic-fixture", "input_tokens": None, "output_tokens": None}}})
        self.assertNotEqual(0, code)
        self.assertNotEqual("completed", self.ok("application-state", {"job_id": job})["preparation"])

    def test_m1_07_quota_pauses_with_next_step_and_missing_renderer_is_explicit(self):
        _, claim = self.profile()
        job = self.job()
        letter = self.draft(job, claim)
        review = self.ok("task-create", {"job_id": job, "kind": "review", "consent": True, "draft_id": letter})["task_id"]
        self.assertEqual("blocked_quota", self.ok("task-failure", {"task_id": review, "reason": "quota"})["state"])
        self.assertEqual("resume", self.ok("pause", {})["next_safe_step"])
        fake = self.dir / "no-renderer" / "reportlab"
        fake.mkdir(parents=True)
        (fake / "__init__.py").write_text("raise ImportError('renderer removed for test')\n", encoding="utf-8")
        self.env["PYTHONPATH"] = str(fake.parent) + os.pathsep + self.env["PYTHONPATH"]
        self.fails("toolchain_missing", "draft-verify", {"task_id": letter})
        self.assertNotEqual("ready", self.ok("application-state", {"job_id": job})["preparation"])

    def test_m1_08_prior_application_needs_prepare_anyway(self):
        _, claim = self.profile()
        earlier = self.job()
        self.ok("outcome-record", {"job_id": earlier, "kind": "manual_applied", "effective_at": "2026-10-01T09:00:00+00:00"})
        again = self.job(description="Reposted listing.")
        self.fails("prior_application", "task-create", {"job_id": again, "kind": "draft_letter", "consent": True})
        self.ok("task-create", {"job_id": again, "kind": "draft_letter", "consent": True, "prepare_anyway": True})

    def test_m1_11_activity_and_unknown_cost(self):
        _, claim = self.profile()
        job = self.job()
        self.draft(job, claim)
        for event in ("open", "review", "approve"):
            self.ok("activity-record", {"job_id": job, "event": event, "run_id": "run-1"})
        measured = self.ok("activity-time", {"job_id": job})
        self.assertEqual("measured", measured["status"])
        self.assertLessEqual(measured["active_seconds"], measured["elapsed_seconds"])
        usage = self.ok("usage-report", {"job_id": job})
        self.assertEqual((None, "unknown"), (usage["cost"], usage["cost_status"]))


if __name__ == "__main__":
    unittest.main()
