"""E2E JW-19, JW-21, JW-23, JW-24: metrics, post dedup and unmerge, schedule refusal, schema and
traceability, through the CLI and the repository script."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

from e2e_support import E2E

ROOT = Path(__file__).resolve().parents[1]
POST = {"provider": "linkedin", "company": "Fixture Co", "title": "Backend Engineer", "location": "Berlin",
        "text": "Build Python services.", "requisition": "R-1"}


class RemainingE2E(E2E):
    def test_jw19_metrics_and_activity(self):
        self.profile()
        job = self.job()
        for event in ("open", "review"):
            self.ok("activity-record", {"job_id": job, "event": event})
        self.assertEqual("measured", self.ok("activity-time", {"job_id": job})["status"])
        report = self.ok("metrics", {})
        self.assertIn("cost", report["unmeasured"])
        self.assertEqual("unknown", report["cohorts"]["unprepared"]["metrics"]["reply_rate"]["status"])

    def test_jw21_dedup_merge_undo_and_paging(self):
        first = self.ok("post-ingest", {"post": POST})
        second = self.ok("post-ingest", {"post": dict(POST, provider="careers")})
        self.assertEqual((first["opportunity_id"], 3), (second["opportunity_id"], second["merge"]["layer"]))
        self.ok("post-ingest", {"post": dict(POST, location="Pune", provider="x")})
        page = self.ok("opportunities", {"limit": 1})
        self.assertIsNotNone(page["next_cursor"])
        self.assertEqual(1, len(self.ok("opportunities", {"cursor": page["next_cursor"], "limit": 5})["items"]))
        self.assertEqual(1, self.ok("merge-undo", {"merge_id": second["merge"]["merge_id"]})["posts_restored"])
        self.assertEqual(3, len(self.ok("opportunities", {"limit": 10})["items"]))

    def test_jw23_schedule_policy(self):
        self.fails("cap_above_hard_limit", "schedule-set", {"policy": {"timezone": "Asia/Kolkata", "channels": {
            "email": {"daily_cap": 99, "hours": [9, 18]}}}})
        self.ok("schedule-set", {"policy": {"timezone": "Asia/Kolkata", "channels": {
            "email": {"daily_cap": 0, "hours": [9, 18]}}}})
        self.fails("channel_capped_off", "schedule-next", {"channel": "email"})

    def test_jw24_schema_and_traceability_script(self):
        schemas = self.ok("schema")
        self.assertEqual(["confirm", "source_id"], schemas["source-delete"]["required"])
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_traceability.py")],
                              capture_output=True, timeout=60, check=False)
        self.assertEqual(0, done.returncode, done.stdout.decode())


if __name__ == "__main__":
    unittest.main()
