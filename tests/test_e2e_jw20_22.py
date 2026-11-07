"""E2E JW-20 and JW-22: pause/resume/application-state and history import guarding a new draft,
then history export round trip, all through the CLI."""

import unittest

from e2e_support import E2E
from jw.csv_archive import normalize_csv

CSV = b"Company,Role,Applied,Status\r\nFixture Co,Platform Engineer,2026-09-01,Interview\r\nOther,SRE,bad,\r\n"
MAPPING = {"company": "Company", "title": "Role", "date": "Applied", "outcome": "Status",
           "date_formats": ["%Y-%m-%d"]}


class RunsAndHistoryE2E(E2E):
    def test_pause_resume_and_state(self):
        _, claim = self.profile()
        job = self.job()
        self.assertTrue(self.ok("pause", {})["stopped"])
        self.assertTrue((self.root / "progress.json").is_file())
        self.assertEqual("ready", self.ok("resume", {"holder": "cli"})["state"])
        self.draft(job, claim)
        state = self.ok("application-state", {"job_id": job})
        self.assertEqual(("drafted", None), (state["preparation"], state["outcome"]))

    def test_history_import_blocks_repeat_application_and_exports(self):
        self.profile()
        csv = self.dir / "tracker.csv"
        csv.write_bytes(CSV)
        report = self.ok("history-import", {"path": str(csv), "mapping": MAPPING})
        self.assertEqual((1, [{"line": 3, "reason": "date_not_in_declared_formats"}]),
                         (report["imported"], report["invalid"]))
        self.assertTrue(self.ok("history-import", {"path": str(csv), "mapping": MAPPING})["reused"])
        job = self.job()
        self.fails("prior_application", "task-create", {"job_id": job, "kind": "draft_cv", "consent": True})
        self.ok("task-create", {"job_id": job, "kind": "draft_cv", "consent": True, "prepare_anyway": True})
        out = self.dir / "export.csv"
        self.ok("history-export", {"import_id": report["import_id"], "output_path": str(out)})
        exported = normalize_csv(out.read_bytes())
        self.assertEqual(normalize_csv(CSV)["headings"] + ["jw_status", "jw_line"], exported["headings"])


if __name__ == "__main__":
    unittest.main()
