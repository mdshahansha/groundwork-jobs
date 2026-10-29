"""Synthetic fixed-template probes; no LaTeX, network, images or provider calls."""

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from jw.contracts import WorkspaceError
from jw.rendering import render_private_pdf, write_new_pdf


class RenderingTests(unittest.TestCase):
    profile = {"name": "Synthetic Candidate", "email": "candidate@example.invalid"}

    def render(self, text="Built Python services.", kind="draft_cv"):
        return render_private_pdf(self.profile, [{"text": text, "claim_id": "clm_fixture"}], kind)

    def test_cv_and_letter_extract_with_no_active_actions(self):
        for kind in ("draft_cv", "draft_letter"):
            pdf, report = self.render("Built Python services. Worked with José.", kind)
            reader = PdfReader(BytesIO(pdf))
            self.assertEqual(1, len(reader.pages))
            self.assertIn("José", reader.pages[0].extract_text())
            self.assertIn("PRIVATE DRAFT - NOT READY", reader.pages[0].extract_text())
            root = reader.trailer["/Root"]
            for key in ("/OpenAction", "/AA", "/AcroForm", "/Names"):
                self.assertNotIn(key, root)
            self.assertNotIn("/Annots", reader.pages[0])
            self.assertFalse(report["ready"])

    def test_markup_paths_and_commands_stay_literal(self):
        text = r'<img src="file:///secret"> <script>alert(1)</script> \input{secret} \write18{whoami}'
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.Popen", side_effect=AssertionError("process forbidden")):
            pdf, _ = self.render(text)
        extracted = PdfReader(BytesIO(pdf)).pages[0].extract_text()
        self.assertIn(r"\input{secret}", extracted)
        self.assertIn("<script>alert(1)</script>", extracted)
        self.assertNotIn("/XObject", PdfReader(BytesIO(pdf)).pages[0]["/Resources"])

    def test_one_page_overflow_blocks_without_font_shrink(self):
        with self.assertRaises(WorkspaceError) as caught:
            self.render("line\n" * 300)
        self.assertEqual("page_fit_conflict", caught.exception.code)

    def test_long_token_wraps_and_repeated_build_is_identical(self):
        first, _ = self.render("X" * 300)
        second, _ = self.render("X" * 300)
        self.assertEqual(first, second)
        text = PdfReader(BytesIO(first)).pages[0].extract_text()
        self.assertEqual(300, text.count("X"))

    def test_unknown_glyph_and_template_fields_fail_closed(self):
        with self.assertRaises(WorkspaceError) as caught:
            self.render("Unsupported emoji \U0001f600")
        self.assertEqual("unsupported_glyph", caught.exception.code)
        with self.assertRaises(WorkspaceError):
            render_private_pdf(dict(self.profile, template="run-command"), [], "draft_cv")

    def test_missing_or_wrong_renderer_is_explicit(self):
        from importlib.metadata import PackageNotFoundError
        for value, code in ((PackageNotFoundError(), "toolchain_missing"), ("0.0", "toolchain_version")):
            options = {"side_effect": value} if isinstance(value, Exception) else {"return_value": value}
            with patch("jw.rendering.importlib.metadata.version", **options):
                with self.assertRaises(WorkspaceError) as caught:
                    self.render()
                self.assertEqual(code, caught.exception.code)

    def test_exclusive_export_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "draft.pdf"
            pdf, _ = self.render()
            write_new_pdf(target, pdf)
            with self.assertRaises(WorkspaceError) as caught:
                write_new_pdf(target, b"replacement")
            self.assertEqual("output_exists", caught.exception.code)
            self.assertEqual(pdf, target.read_bytes())
