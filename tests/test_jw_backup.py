"""JW-04: deletion journal, backups, retention, purge on rotation and restore (FR-ADM-03, NFR-PRV-03)."""

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from jw import backup as bk
from jw.actions import Actions
from jw.cli import main
from jw.contracts import WorkspaceError, canonical
from jw.execution import Executor
from jw.workspace import Workspace

SECRET = "Led the confidential Orion migration."


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.ws = Workspace(self.root, create=True)
        self.addCleanup(lambda: self.ws and self.ws.close())
        self.source = self.ws.import_source(SECRET.encode(), sensitivity="private")["source_id"]
        self.ws.add_claim(self.source, 0, len(SECRET))
        self.dest = Path(self.temp.name) / "backups"

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def contains_secret(self, path):
        db = sqlite3.connect(path)
        try:
            rows = db.execute("SELECT text FROM sources UNION ALL SELECT text FROM claims").fetchall()
            return any(SECRET in (r[0] or "") for r in rows)
        finally:
            db.close()

    def test_deletion_writes_journal_outside_database_with_hash_only(self):
        self.ws.delete_source(self.source)
        text = (self.root / bk.JOURNAL).read_text(encoding="utf-8")
        entry = json.loads(text)
        self.assertEqual(self.source, entry["source_id"])
        self.assertNotIn("Orion", text)
        self.assertEqual(0, bk.sync_journal(self.ws))

    def test_backup_has_manifest_and_restores_round_trip(self):
        made = bk.backup(self.ws, self.dest)
        manifest = json.loads(Path(made["backup"] + ".json").read_text(encoding="utf-8"))
        self.assertEqual((9, "none"), (manifest["schema_version"], manifest["secrets"]))
        self.ws.close()
        self.ws = None
        result = bk.restore(self.root, made["backup"])
        self.assertEqual(([], True), (result["purged"], result["stopped"]))
        self.ws = Workspace(self.root)
        self.assertEqual("active", self.ws.store.one("sources", self.source)["state"])

    def test_restore_of_older_backup_cannot_resurrect_a_deleted_source(self):
        made = bk.backup(self.ws, self.dest)["backup"]
        self.ws.delete_source(self.source)
        self.ws.close()
        self.ws = None
        result = bk.restore(self.root, made)
        self.assertEqual([self.source], result["purged"])
        self.ws = Workspace(self.root)
        self.assertEqual("deleted", self.ws.store.one("sources", self.source)["state"])
        self.assertFalse(self.contains_secret(self.root / "workspace.sqlite3"))
        self.assertCode("source_deleted", self.ws.import_source, SECRET.encode(), sensitivity="private")

    def test_next_rotation_purges_deleted_source_from_kept_backups(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with patch("jw.backup.utcnow", return_value=yesterday):
            made = bk.backup(self.ws, self.dest)["backup"]
        self.assertTrue(self.contains_secret(made))
        self.ws.delete_source(self.source)
        result = bk.backup(self.ws, self.dest)
        self.assertEqual({Path(made).name: [self.source]}, result["purged"])
        for path in self.dest.glob("backup-*.sqlite3"):
            self.assertFalse(self.contains_secret(path), path.name)
            bk._manifest(path)

    def test_retention_keeps_seven_daily_and_four_weekly(self):
        start = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        for day in range(40):
            stamp = (start + timedelta(days=day)).isoformat()
            with patch("jw.backup.utcnow", return_value=stamp):
                result = bk.backup(self.ws, self.dest)
        kept = [bk._stamp(self.dest / name) for name in result["kept"]]
        self.assertEqual(len(kept), len(list(self.dest.glob("backup-*.sqlite3"))))
        self.assertTrue(7 <= len(kept) <= 11)
        newest = max(kept)
        self.assertEqual(7, sum(1 for k in kept if newest - k < timedelta(days=7)))

    def test_restore_marks_in_flight_unknown_and_sets_stop(self):
        public = self.ws.import_source(b"Built Python services.", sensitivity="public")["source_id"]
        self.ws.add_claim(public, 0, 22)
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        actions = Actions(self.ws)
        actions.set_mode("email", "approve_each_action")
        email = {"subject": "Role", "body": "Hello."}
        auth = actions.approve(actions.create_envelope("email", "r@example.invalid", email)["envelope_id"])
        ex = Executor(actions)
        token = ex.acquire("worker-a")["token"]
        action = ex.reserve(token, auth["authorisation_id"], "email", "r@example.invalid", email)["action_id"]
        made = bk.backup(self.ws, self.dest)["backup"]
        self.ws.close()
        self.ws = None
        result = bk.restore(self.root, made)
        self.assertEqual([action], result["unknown"])
        self.ws = Workspace(self.root)
        self.assertTrue(Actions(self.ws).stopped())
        self.assertEqual("unknown", self.ws.store.one("attempts", action)["state"])

    def test_tampered_or_newer_backup_is_refused(self):
        made = bk.backup(self.ws, self.dest)["backup"]
        self.ws.close()
        self.ws = None
        manifest = Path(made + ".json")
        good = manifest.read_text(encoding="utf-8")
        manifest.write_text(good.replace('"schema_version": 9', '"schema_version": 99'), encoding="utf-8")
        self.assertCode("unsupported_schema", bk.restore, self.root, made)
        manifest.write_text(good, encoding="utf-8")
        with open(made, "ab") as stream:
            stream.write(b"x")
        self.assertCode("backup_invalid", bk.restore, self.root, made)

    def test_older_schema_backup_migrates_forward(self):
        made = bk.backup(self.ws, self.dest)["backup"]
        db = sqlite3.connect(made)
        for table in ("attempts", "leases"):
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version=8")
        db.commit()
        db.close()
        bk._write_manifest(made, 8, "2026-11-01T00:00:00+00:00", 0)
        self.ws.close()
        self.ws = None
        self.assertEqual((8, 9), tuple(bk.restore(self.root, made)[k] for k in ("from_schema", "schema_version")))

    def test_cli_backup_and_restore_require_confirm(self):
        self.ws.close()
        self.ws = None

        def run(command, payload):
            request = Path(self.temp.name) / (command + ".json")
            request.write_text(canonical(payload), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--workspace", str(self.root), command, "--input", str(request)])
            return code, json.loads(output.getvalue())

        code, out = run("backup", {"to": str(self.dest)})
        self.assertEqual(0, code)
        made = out["result"]["backup"]
        self.assertEqual("confirmation_required", run("restore", {"backup": made, "confirm": False})[1]["error"]["code"])
        self.assertEqual((0, True), (lambda r: (r[0], r[1]["result"]["stopped"]))(run("restore", {"backup": made,
                                                                                                    "confirm": True})))


if __name__ == "__main__":
    unittest.main()
