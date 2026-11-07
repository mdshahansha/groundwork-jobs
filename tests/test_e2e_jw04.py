"""E2E JW-04: backup, delete, restore an older backup, and the deleted source stays deleted."""

import unittest

from e2e_support import CV, E2E


class BackupRestoreE2E(E2E):
    def test_restore_cannot_resurrect_a_deleted_source(self):
        source, _ = self.profile()
        backup = self.ok("backup", {"to": str(self.dir / "backups")})["backup"]
        self.fails("confirmation_required", "source-delete", {"source_id": source, "confirm": False})
        self.assertEqual("logically_erased", self.ok("source-delete", {"source_id": source, "confirm": True})["state"])
        self.fails("confirmation_required", "restore", {"backup": backup, "confirm": False})
        restored = self.ok("restore", {"backup": backup, "confirm": True})
        self.assertEqual(([source], True), (restored["purged"], restored["stopped"]))
        self.fails("source_deleted", "source-import", None, "--sensitivity", "public", raw=CV.encode())

    def test_tampered_backup_is_refused(self):
        self.profile()
        backup = self.ok("backup", {"to": str(self.dir / "backups")})["backup"]
        with open(backup, "ab") as stream:
            stream.write(b"tamper")
        self.fails("backup_invalid", "restore", {"backup": backup, "confirm": True})


if __name__ == "__main__":
    unittest.main()
