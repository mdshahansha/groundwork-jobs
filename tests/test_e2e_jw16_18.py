"""E2E JW-16 and JW-18: --dry-run changes nothing on disk; PDF, ZIP and image imports through the CLI."""

from io import BytesIO
import hashlib
import unittest
import zipfile

from e2e_support import CV, E2E
from test_jw_untrusted import pdf


class SimulationAndUntrustedE2E(E2E):
    def digest(self):
        return hashlib.sha256((self.root / "workspace.sqlite3").read_bytes()).hexdigest()

    def test_dry_run_leaves_database_file_identical(self):
        source, _ = self.profile()
        self.ok("checkpoint", {})
        before = self.digest()
        result = self.ok("source-delete", {"source_id": source, "confirm": True}, "--dry-run")
        self.assertEqual((True, 1), (result["simulated"], result["effects"]["rows"]["deletions"]))
        self.ok("job-add", {"company": "A", "title": "B", "description": "C", "requirements": []}, "--dry-run")
        self.assertEqual(before, self.digest())
        self.ok("source-import", None, "--sensitivity", "public", raw=b"Other text.")

    def test_pdf_zip_and_image_imports(self):
        imported = self.ok("source-import", None, "--sensitivity", "public", raw=pdf(CV))
        self.assertFalse(imported["reused"])
        out = BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr("notes.md", "Ran reviews.")
            zf.writestr("../escape.txt", "x")
        self.fails("archive_traversal", "archive-import", None, raw=out.getvalue())
        good = BytesIO()
        with zipfile.ZipFile(good, "w") as zf:
            zf.writestr("notes.md", "Ran reviews.")
            zf.writestr("photo.jpg", b"\xff\xd8\xff")
        result = self.ok("archive-import", None, "--sensitivity", "public", raw=good.getvalue())
        self.assertEqual((["notes.md"], ["photo.jpg"]), ([i["member"] for i in result["imported"]],
                                                         [i["name"] for i in result["ignored"]]))
        self.fails("ocr_unavailable", "source-import", None, raw=b"\x89PNG\r\n\x1a\nxx")


if __name__ == "__main__":
    unittest.main()
