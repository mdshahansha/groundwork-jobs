"""JW-19: metric dictionary, cohorts, activity time (M1-11) and the labelled dedup release corpus."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from jw.contracts import WorkspaceError, canonical
from jw.metrics import DICTIONARY, active_time, cohorts, record_activity, report
from jw.opportunities import Opportunities
from jw.tasks import Tasks
from jw.workspace import Workspace

CORPUS = Path(__file__).parent / "fixtures" / "jw_dedup_corpus.json"
TEXT = "Built Python services."


def at(minutes):
    return (datetime(2026, 11, 2, 9, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat()


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name) / "workspace", create=True)
        self.addCleanup(lambda: self.ws.close())
        source = self.ws.import_source(TEXT.encode(), sensitivity="public")["source_id"]
        self.claim = self.ws.add_claim(source, 0, len(TEXT))["claim_id"]
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        self.job = self.ws.add_job({"company": "A", "title": "B", "description": "C", "requirements": []})["job_id"]

    def test_unknown_is_never_zero(self):
        cohort = report(self.ws)["cohorts"]["unprepared"]["metrics"]
        for name in DICTIONARY:
            if name != "manual_applications":
                self.assertEqual(("unknown", None, 0), (cohort[name]["status"], cohort[name]["value"],
                                                        cohort[name]["denominator"]), name)
        self.assertEqual(0.0, cohort["manual_applications"]["value"])
        self.assertIn("cost", report(self.ws)["unmeasured"])

    def test_cohort_by_week_of_first_draft_and_rates_with_counts(self):
        tasks = Tasks(self.ws)
        task = tasks.create(self.job, "draft_letter", consent=True)["task_id"]
        tasks.submit(task, canonical({"output": {"assertions": [{"text": TEXT, "claim_id": self.claim}]},
                     "usage": {"model": "m", "input_tokens": None, "output_tokens": None}}).encode())
        tasks.create(self.job, "draft_cv", consent=True)
        other = self.ws.add_job({"company": "X", "title": "Y", "description": "Z", "requirements": []})["job_id"]
        groups = cohorts(self.ws)
        week = next(k for k in groups if k != "unprepared")
        self.assertEqual(([self.job], [other]), (groups[week], groups["unprepared"]))
        metric = report(self.ws)["cohorts"][week]["metrics"]["drafts_completed"]
        self.assertEqual((0.5, 1, 2, "measured"),
                         (metric["value"], metric["numerator"], metric["denominator"], metric["status"]))

    def test_m1_11_active_and_elapsed_time_exclude_idle(self):
        self.assertEqual("unknown", active_time(self.ws, self.job)["status"])
        for minute, event in ((0, "open"), (2, "review"), (4, "edit"), (64, "review"), (65, "approve")):
            record_activity(self.ws, self.job, event, run_id="run-1", at=at(minute))
        measured = active_time(self.ws, self.job)
        self.assertEqual((65 * 60, 5 * 60, 1, 60 * 60),
                         (measured["elapsed_seconds"], measured["active_seconds"], measured["idle_gaps"],
                          measured["idle_seconds_excluded"]))
        with self.assertRaises(WorkspaceError):
            record_activity(self.ws, self.job, "daydream")


class DedupCorpus(unittest.TestCase):
    """FR-DED-01 metrics on the labelled corpus: auto-merge precision >= 98%, overall recall >= 85%."""

    def test_precision_and_recall_on_labelled_corpus(self):
        cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]
        auto_tp = auto_fp = found = positives = 0
        wrong = []
        for case in cases:
            with tempfile.TemporaryDirectory() as temp:
                ws = Workspace(Path(temp) / "ws", create=True)
                try:
                    opps = Opportunities(ws)
                    opps.ingest(case["a"])
                    second = opps.ingest(case["b"])
                    # An identical provider + external ID is the same post, reused: a layer-1 auto-merge.
                    merge = {"state": "merged"} if second["reused"] else second["merge"]
                finally:
                    ws.close()
            positives += case["same"]
            if merge and merge["state"] == "merged":
                auto_tp += case["same"]
                auto_fp += not case["same"]
            if merge and case["same"]:
                found += 1
            if bool(merge and merge["state"] == "merged") and not case["same"]:
                wrong.append(case["id"])
        precision = auto_tp / (auto_tp + auto_fp) if auto_tp + auto_fp else 1.0
        self.assertEqual([], wrong)
        self.assertGreaterEqual(precision, 0.98)
        self.assertGreaterEqual(found / positives, 0.85)


if __name__ == "__main__":
    unittest.main()
