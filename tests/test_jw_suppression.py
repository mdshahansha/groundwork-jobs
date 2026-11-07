"""JW-13: permanent suppression (FR-EML-04) and the recovery boundary: restore cannot unblock."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from jw import backup as bk
from jw.actions import Actions
from jw.contracts import WorkspaceError
from jw.execution import Executor
from jw.suppression import JOURNAL, suppress, suppressed
from jw.workspace import Workspace

EMAIL = {"subject": "Role", "body": "Hello."}
TO = "Recruiter@Example.invalid"


class SuppressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.open(create=True)
        text = "Built Python services."
        source = self.ws.import_source(text.encode(), sensitivity="public")["source_id"]
        self.ws.add_claim(source, 0, len(text))
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        self.job = self.ws.add_job({"company": "Fixture Co", "title": "T", "description": "D",
                                    "requirements": []})["job_id"]
        self.actions.set_mode("email", "approve_each_action")

    def open(self, create=False):
        self.ws = Workspace(self.root, create=create)
        self.addCleanup(self.ws.close)
        self.actions = Actions(self.ws)
        self.ex = Executor(self.actions)

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def envelope(self, to=TO, job=None):
        return self.actions.create_envelope("email", to, EMAIL, job_id=job or self.job)["envelope_id"]

    def test_opt_out_blocks_approval_and_reservation_case_insensitively(self):
        auth = self.actions.approve(self.envelope())["authorisation_id"]
        suppress(self.ws, "recruiter@example.INVALID ", "opt_out")
        self.assertCode("suppressed", self.actions.approve, self.envelope())
        token = self.ex.acquire("w")["token"]
        self.assertCode("suppressed", self.ex.reserve, token, auth, "email", TO, EMAIL)
        self.assertEqual("active", self.ws.store.one("authorisations", auth)["state"])

    def test_wrong_recipient_blocks_only_that_company(self):
        suppress(self.ws, TO, "wrong_recipient", company="  fixture   co ")
        self.assertTrue(suppressed(self.ws, TO, "Fixture Co"))
        other = self.ws.add_job({"company": "Other Ltd", "title": "T", "description": "D", "requirements": []})["job_id"]
        self.assertFalse(suppressed(self.ws, TO, "Other Ltd"))
        self.actions.approve(self.envelope(job=other))
        self.assertCode("suppressed", self.actions.approve, self.envelope())
        self.assertCode("invalid_schema", suppress, self.ws, TO, "wrong_recipient")
        self.assertCode("invalid_schema", suppress, self.ws, TO, "opt_out", company="X")

    def test_only_hashes_are_stored_and_rows_are_permanent(self):
        suppress(self.ws, TO, "hard_bounce")
        self.assertNotIn("example", (self.root / JOURNAL).read_text(encoding="utf-8").lower())
        self.assertNotIn("example", str(list(self.ws.db.execute("SELECT * FROM suppressions").fetchone())).lower())
        with self.assertRaises(sqlite3.IntegrityError):
            self.ws.db.execute("DELETE FROM suppressions")
        self.ws.db.rollback()

    def test_restore_of_older_backup_keeps_suppression(self):
        made = bk.backup(self.ws, Path(self.temp.name) / "backups")["backup"]
        suppress(self.ws, TO, "opt_out")
        self.ws.close()
        bk.restore(self.root, made)
        self.open()
        self.assertTrue(suppressed(self.ws, TO))

    def test_rotation_writes_suppression_into_kept_backups(self):
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        dest = Path(self.temp.name) / "backups"
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with patch("jw.backup.utcnow", return_value=yesterday):
            old = bk.backup(self.ws, dest)["backup"]
        suppress(self.ws, TO, "opt_out")
        bk.backup(self.ws, dest)
        db = sqlite3.connect(old)
        try:
            self.assertEqual(1, db.execute("SELECT count(*) FROM suppressions").fetchone()[0])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
