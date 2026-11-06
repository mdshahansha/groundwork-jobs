"""JW-09: mechanical gates 1-2 on rendered PDF bytes and the required-format check.
PDFs are synthetic; defect PDFs are drawn directly to prove each check can fail."""

from contextlib import redirect_stdout
from io import BytesIO
import io
import json
from pathlib import Path
import tempfile
import unittest

from jw.cli import main
from jw.contracts import WorkspaceError, canonical
from jw.rendering import FOOTER, PAGE_HEIGHT, PAGE_WIDTH, WARNING, expected_content, render_private_pdf
from jw.tasks import Tasks
from jw.verification import gate_render, gate_text, verify
from jw.workspace import Workspace

PROFILE = {"name": "Synthetic Candidate", "email": "candidate@example.invalid"}
JOB = {"company": "Fixture Co", "title": "Platform Engineer"}
ASSERTIONS = [{"text": "Built Python services in 2021.", "claim_id": "c1"},
              {"text": "Ran " + "observability " * 30 + "reviews.", "claim_id": "c2"}]


def drawn(*items, pages=1):
    """Draw (text, x, y, font, size) items with no layout logic, to build defect PDFs."""
    from reportlab.pdfgen.canvas import Canvas

    out = BytesIO()
    canvas = Canvas(out, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), invariant=1)
    for page in range(pages):
        for text, x, y, font, size in items:
            canvas.setFont(font, size)
            canvas.drawString(x, y, text)
        canvas.showPage()
    canvas.save()
    return out.getvalue()


GOOD = [(WARNING, 48, 776, "Helvetica", 10), ("Synthetic Candidate", 48, 744, "Helvetica", 18),
        ("candidate@example.invalid", 48, 722, "Helvetica", 11), ("Curriculum vitae", 48, 690, "Helvetica", 13),
        ("Built Python services in 2021.", 48, 657, "Helvetica", 11), (FOOTER, 48, 48, "Helvetica", 9)]


def statuses(results):
    return {name: check["status"] for name, check in results.items()}


class RenderedDocuments(unittest.TestCase):
    def test_real_cv_and_letter_pass_mechanical_gates_but_are_never_ready(self):
        for kind in ("draft_cv", "draft_letter"):
            pdf, report = render_private_pdf(PROFILE, ASSERTIONS, kind, JOB)
            self.assertEqual("private-fixed@2", report["template"])
            result = verify(pdf, expected_content(PROFILE, ASSERTIONS, kind, JOB), JOB)
            self.assertEqual(("mechanical_passed", False, []), (result["status"], result["ready"], result["failed_checks"]))
            self.assertEqual("not_run", result["gates"]["visual_review"]["status"])
            self.assertIn("visual_review", result["remaining_gates"])
        self.assertEqual("passed", result["gates"]["text"]["target"]["status"])

    def test_drawn_baseline_passes_so_defect_cases_are_meaningful(self):
        render, _, text = gate_render(drawn(*GOOD))
        self.assertNotIn("failed", statuses(render).values())
        expected = expected_content(PROFILE, ASSERTIONS[:1], "draft_cv")
        self.assertNotIn("failed", statuses(gate_text(text, expected)).values())

    def test_wrong_target_contact_or_order_fail_gate_two(self):
        pdf, _ = render_private_pdf(dict(PROFILE, name="Someone Else"), ASSERTIONS, "draft_letter",
                                    dict(JOB, company="Other Co"))
        result = verify(pdf, expected_content(PROFILE, ASSERTIONS, "draft_letter", JOB), JOB)
        self.assertEqual("blocked_quality", result["status"])
        self.assertTrue({"text.contact_details", "text.reading_order", "text.target"} <= set(result["failed_checks"]))
        swapped, _ = render_private_pdf(PROFILE, ASSERTIONS[::-1], "draft_cv")
        self.assertIn("text.reading_order", verify(swapped, expected_content(PROFILE, ASSERTIONS, "draft_cv"), JOB)["failed_checks"])

    def test_placeholder_and_required_format(self):
        draft = [{"text": "Improved latency by TODO percent.", "claim_id": "c1"}]
        pdf, _ = render_private_pdf(PROFILE, draft, "draft_cv")
        self.assertIn("text.placeholders", verify(pdf, expected_content(PROFILE, draft, "draft_cv"), JOB)["failed_checks"])
        pdf, _ = render_private_pdf(PROFILE, ASSERTIONS, "draft_cv")
        result = verify(pdf, expected_content(PROFILE, ASSERTIONS, "draft_cv"), dict(JOB, required_formats=["pdf", "docx"]))
        self.assertEqual(("blocked_input", ["docx"]), (result["status"],
                         result["gates"]["format"]["detail"]["unsupported_formats"]))


class DefectDetection(unittest.TestCase):
    def failed(self, pdf):
        return {name for name, check in gate_render(pdf)[0].items() if check["status"] == "failed"}

    def test_clipping_overlap_font_footer_and_orphan(self):
        self.assertIn("text_clipping", self.failed(drawn(*GOOD, ("Off the edge", 10, 400, "Helvetica", 11))))
        self.assertIn("overlap", self.failed(drawn(*GOOD, ("Collides", 52, 657, "Helvetica", 11))))
        self.assertIn("font_consistency", self.failed(drawn(*GOOD, ("Serif line", 48, 600, "Times-Roman", 11))))
        self.assertIn("font_consistency", self.failed(drawn(*GOOD, ("Odd size", 48, 600, "Helvetica", 12))))
        self.assertIn("footer_collision", self.failed(drawn(*GOOD[:-1], (FOOTER, 48, 655, "Helvetica", 9))))
        self.assertIn("orphaned_heading", self.failed(drawn(*GOOD[:4], GOOD[-1])))
        # Two headings in a row: the first is orphaned even though body text follows later.
        self.assertIn("orphaned_heading", self.failed(drawn(*GOOD[:4], ("Experience", 48, 672, "Helvetica", 13),
                                                           *GOOD[4:])))

    def test_wrapped_contact_and_malformed_formats(self):
        from jw.verification import required_format

        expected = expected_content(PROFILE, ASSERTIONS[:1], "draft_cv")
        wrapped = gate_text(gate_render(drawn(*GOOD))[2].replace("Synthetic Candidate", "Synthetic\nCandidate"), expected)
        self.assertEqual("passed", wrapped["contact_details"]["status"])
        for formats in ("pdf", [], [None]):
            self.assertEqual("blocked_input", required_format({"required_formats": formats})["status"])
        self.assertEqual("passed", required_format({})["status"])

    def test_unreadable_and_multi_page_fail_compiles(self):
        self.assertIn("compiles", self.failed(b"%PDF-1.4 truncated"))
        self.assertIn("compiles", self.failed(drawn(*GOOD, pages=2)))
        with self.assertRaises(WorkspaceError):
            verify(b"not a pdf", expected_content(PROFILE, ASSERTIONS, "draft_cv"), JOB)

    def test_mojibake_and_unknown_dates_fail(self):
        expected = expected_content(PROFILE, ASSERTIONS[:1], "draft_cv")
        bad = list(GOOD)
        bad[4] = ("Built Python services in 2019. CafÃ© team.", 48, 657, "Helvetica", 11)
        text = gate_text(gate_render(drawn(*bad))[2], expected)
        self.assertEqual("failed", text["unicode"]["status"])
        self.assertEqual(["2019"], text["dates"]["detail"]["unknown_dates"])


class WorkspaceVerification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.ws = Workspace(self.root, create=True)
        self.addCleanup(lambda: self.ws.close())
        self.tasks = Tasks(self.ws)
        text = "Built Python services in 2021."
        self.source = self.ws.import_source(text.encode(), sensitivity="public")["source_id"]
        self.claim = self.ws.add_claim(self.source, 0, len(text))["claim_id"]
        self.ws.set_profile(PROFILE["name"], PROFILE["email"])
        self.ws.publish_profile()
        self.job = self.ws.add_job({"company": "Fixture Co", "title": "Platform Engineer", "description": "Synthetic.",
                                    "requirements": ["Python"], "required_formats": ["pdf"]})["job_id"]
        self.task = self.tasks.create(self.job, "draft_letter", consent=True)["task_id"]
        self.tasks.submit(self.task, canonical({"output": {"assertions": [{"text": text, "claim_id": self.claim}]},
                          "usage": {"model": "synthetic-fixture", "input_tokens": None, "output_tokens": None}}).encode())

    def test_verify_records_run_and_render_attaches_it(self):
        result = self.tasks.verify_draft(self.task)
        self.assertEqual(("mechanical_passed", False), (result["status"], result["ready"]))
        row = self.ws.db.execute("SELECT * FROM verifications WHERE id=?", (result["verification_id"],)).fetchone()
        self.assertEqual((self.task, result["pdf_sha256"]), (row["task_id"], row["pdf_sha256"]))
        rendered = self.tasks.render_private(self.task, str(Path(self.temp.name) / "letter.pdf"))
        self.assertEqual(result["pdf_sha256"], rendered["verification"]["pdf_sha256"])
        self.assertEqual(rendered["sha256"], rendered["verification"]["pdf_sha256"])

    def test_deletion_scrubs_results_and_format_field_is_validated(self):
        verification = self.tasks.verify_draft(self.task)["verification_id"]
        self.ws.delete_source(self.source)
        row = self.ws.db.execute("SELECT status,result FROM verifications WHERE id=?", (verification,)).fetchone()
        self.assertEqual(("erased", "{}"), (row["status"], row["result"]))
        with self.assertRaises(WorkspaceError):
            self.ws.add_job({"company": "A", "title": "B", "description": "C", "requirements": [],
                             "required_formats": ["exe"]})

    def test_cli_draft_verify(self):
        self.ws.close()
        request = Path(self.temp.name) / "verify.json"
        request.write_text(canonical({"task_id": self.task}), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--workspace", str(self.root), "draft-verify", "--input", str(request)])
        self.assertEqual((0, "mechanical_passed"), (code, json.loads(output.getvalue())["result"]["status"]))
        self.ws = Workspace(self.root)


if __name__ == "__main__":
    unittest.main()
