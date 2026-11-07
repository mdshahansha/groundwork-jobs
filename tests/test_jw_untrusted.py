"""JW-18: PDF parser isolation, archive limits, OCR refusal, SSRF and XSS fixtures (FR-SEC-04, FR-SEC-06)."""

from io import BytesIO
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from jw.contracts import WorkspaceError
from jw.untrusted import check_redirects, check_url, extract_pdf_text, html_text
from jw.workspace import Workspace


def pdf(text):
    from reportlab.pdfgen.canvas import Canvas

    out = BytesIO()
    canvas = Canvas(out, invariant=1)
    canvas.drawString(72, 720, text)
    canvas.showPage()
    canvas.save()
    return out.getvalue()


def archive(*members, symlink=None):
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return out.getvalue()


def resolver(table):
    return lambda host, port: table[host]


class UntrustedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name) / "workspace", create=True)
        self.addCleanup(lambda: self.ws.close())

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def test_pdf_text_is_extracted_in_isolated_worker_and_imported(self):
        raw = pdf("Built Python services in 2021.")
        self.assertIn("Built Python services", extract_pdf_text(raw))
        source = self.ws.import_source(raw, sensitivity="public")["source_id"]
        self.assertIn("Built Python services", self.ws.store.one("sources", source)["text"])

    def test_broken_or_textless_pdf_is_refused(self):
        self.assertCode("unsupported_format", self.ws.import_source, b"%PDF-1.7 garbage")
        from reportlab.pdfgen.canvas import Canvas
        out = BytesIO()
        canvas = Canvas(out)
        canvas.showPage()
        canvas.save()
        self.assertCode("unsupported_format", extract_pdf_text, out.getvalue())

    def test_parser_time_limit_is_enforced(self):
        self.assertCode("parser_limit", extract_pdf_text, pdf("x"), timeout=0.001)

    def test_images_need_ocr(self):
        for magic in (b"\x89PNG\r\n", b"\xff\xd8\xff\xe0", b"GIF89a"):
            self.assertCode("ocr_unavailable", self.ws.import_source, magic + b"data")

    def test_archive_imports_text_and_pdf_members_and_ignores_others(self):
        raw = archive(("cv.txt", b"Ran observability reviews."), ("notes/cv.pdf", pdf("Led releases.")),
                      ("photo.png", b"\x89PNG"), symlink="link.txt")
        result = self.ws.import_archive(raw, sensitivity="public")
        self.assertEqual(["cv.txt", "notes/cv.pdf"], [item["member"] for item in result["imported"]])
        self.assertEqual({"photo.png": "unsupported_type", "link.txt": "symlink"},
                         {item["name"]: item["reason"] for item in result["ignored"]})

    def test_archive_attacks_are_refused_before_any_import(self):
        cases = {
            "archive_traversal": archive(("../escape.txt", b"x")),
            "archive_nested": archive(("inner.zip", archive(("a.txt", b"x")))),
            "archive_limit": archive(*[(f"{i}.txt", b"x") for i in range(21)]),
        }
        cases["archive_traversal_abs"] = archive(("/etc/cron.txt", b"x"))
        bomb = archive(("bomb.txt", b"0" * 4_000_000))
        for code, raw in cases.items():
            with self.subTest(code=code):
                self.assertCode(code.replace("_abs", ""), self.ws.import_archive, raw)
        self.assertCode("archive_limit", self.ws.import_archive, bomb)
        self.assertEqual(0, self.ws.db.execute("SELECT count(*) FROM sources").fetchone()[0])
        self.assertCode("unsupported_format", self.ws.import_source, archive(("a.txt", b"x")))

    def test_ssrf_fixtures(self):
        table = {"jobs.example.com": ["93.184.216.34"], "evil.example.com": ["127.0.0.1"],
                 "meta.example.com": ["169.254.169.254"], "lan.example.com": ["10.0.0.5"],
                 "v6.example.com": ["::1"], "mapped.example.com": ["::ffff:192.168.1.1"],
                 "mixed.example.com": ["93.184.216.34", "172.16.0.1"], "cgnat.example.com": ["100.64.0.1"],
                 "2130706433": ["127.0.0.1"], "[::1]": ["::1"], "::1": ["::1"]}
        resolve = resolver(table)
        self.assertEqual(["93.184.216.34"], check_url("https://jobs.example.com/a", resolve=resolve)["addresses"])
        for url in ("https://evil.example.com/", "https://meta.example.com/latest", "https://lan.example.com",
                    "https://v6.example.com", "https://mapped.example.com", "https://mixed.example.com",
                    "https://cgnat.example.com", "https://2130706433/", "https://[::1]/",
                    "http://jobs.example.com", "file:///etc/passwd", "https://user:pw@jobs.example.com",
                    "https://jobs.example.com:8080", "gopher://jobs.example.com", "https://"):
            with self.subTest(url=url):
                self.assertCode("unsafe_url", check_url, url, resolve=resolve)
        self.assertEqual(1, len(check_url("http://jobs.example.com", user_supplied=True, resolve=resolve)["addresses"]))

    def test_every_redirect_hop_is_revalidated(self):
        resolve = resolver({"a.example.com": ["93.184.216.34"], "b.example.com": ["10.0.0.1"]})
        self.assertCode("unsafe_url", check_redirects, ["https://a.example.com", "https://b.example.com"],
                        resolve=resolve)
        self.assertCode("unsafe_url", check_redirects, ["https://a.example.com", "http://a.example.com"],
                        user_supplied=True, resolve=resolve)
        self.assertCode("unsafe_url", check_redirects, ["https://a.example.com"] * 7, resolve=resolve)
        self.assertEqual(6, len(check_redirects(["https://a.example.com"] * 6, resolve=resolve)))

    def test_xss_fixtures_are_inert(self):
        for payload in ('<script>alert(1)</script>', '"><img src=x onerror=alert(1)>', "' onmouseover='x",
                        "<svg/onload=alert(1)>", "javascript:alert(1)</a>"):
            with self.subTest(payload=payload):
                escaped = html_text(payload)
                self.assertFalse(any(ch in escaped for ch in "<>\"'"))


if __name__ == "__main__":
    unittest.main()
