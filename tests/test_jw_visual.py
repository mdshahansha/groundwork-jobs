"""JW-25 gate 3: page images reach the reviewer as files with hashes, and `ready` needs every gate."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jw.contracts import canonical
from jw.tasks import Tasks
from jw.visual import FOLDER, rasterise, readiness
from jw.workspace import Workspace

TEXT = "Built Python services in 2021."


def response(output):
    return canonical({"output": output, "usage": {"model": "synthetic-fixture", "input_tokens": None,
                                                  "output_tokens": None}}).encode()


def finding(severity):
    return {"severity": severity, "code": "fabricated_qualification" if severity == "critical" else "word_choice",
            "assertion_index": 0}


class VisualGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.ws = Workspace(self.root, create=True)
        self.addCleanup(lambda: self.ws.close())
        self.tasks = Tasks(self.ws)
        self.source = self.ws.import_source(TEXT.encode(), sensitivity="public")["source_id"]
        self.claim = self.ws.add_claim(self.source, 0, len(TEXT))["claim_id"]
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        self.job = self.ws.add_job({"company": "Fixture Co", "title": "Platform Engineer", "description": "S.",
                                    "requirements": ["Python"]})["job_id"]
        self.draft = self.tasks.create(self.job, "draft_letter", consent=True)["task_id"]
        self.tasks.submit(self.draft, response({"assertions": [{"text": TEXT, "claim_id": self.claim}]}))

    def review(self, findings):
        review = self.tasks.create(self.job, "review", consent=True, draft_id=self.draft)["task_id"]
        packet = self.tasks.packet(review)["packet"]
        self.tasks.submit(review, response({"findings": findings}))
        return packet

    def test_page_images_are_files_with_matching_hashes(self):
        images = self.review([])["rendered"]["page_images"]
        self.assertEqual(1, len(images))
        data = Path(images[0]["path"]).read_bytes()
        self.assertEqual((images[0]["sha256"], b"\x89PNG"), (hashlib.sha256(data).hexdigest(), data[:4]))
        self.assertTrue(Path(images[0]["path"]).is_relative_to(self.ws.store.root / FOLDER))

    def test_ready_only_after_every_gate(self):
        self.assertEqual(["mechanical_gates", "independent_review"], readiness(self.tasks, self.draft)["missing"])
        self.tasks.verify_draft(self.draft)
        self.assertEqual(["independent_review"], readiness(self.tasks, self.draft)["missing"])
        self.review([finding("minor")])
        result = readiness(self.tasks, self.draft)
        self.assertEqual((True, []), (result["ready"], result["missing"]))
        self.ws.set_profile("Synthetic Candidate", "changed@example.invalid")
        self.ws.publish_profile()
        self.assertIn("inputs_changed_or_draft_incomplete", readiness(self.tasks, self.draft)["missing"])

    def test_blocking_finding_or_missing_images_is_not_ready(self):
        self.tasks.verify_draft(self.draft)
        with patch("jw.visual.rasterise", return_value=None):
            self.review([])
        self.assertEqual(["page_images_not_reviewed"], readiness(self.tasks, self.draft)["missing"])

    def test_blocking_review_is_not_ready(self):
        self.tasks.verify_draft(self.draft)
        self.review([finding("critical")])
        self.assertEqual(["blocking_findings"], readiness(self.tasks, self.draft)["missing"])

    def test_deleting_the_source_removes_page_images(self):
        path = Path(self.review([])["rendered"]["page_images"][0]["path"])
        self.ws.delete_source(self.source)
        self.assertFalse(path.exists())

    def test_unreadable_pdf_is_an_explicit_error(self):
        from jw.contracts import WorkspaceError
        with self.assertRaises(WorkspaceError) as caught:
            rasterise(b"%PDF-1.7 broken")
        self.assertEqual("toolchain_missing", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
