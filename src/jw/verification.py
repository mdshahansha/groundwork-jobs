"""Mechanical document gates 1 and 2 (FR-DOC-03, FR-DOC-04) on the rendered PDF bytes.

The checks read the PDF back with pypdf instead of trusting the renderer's own layout
report: what is checked is what a reader would extract. Passing them is necessary,
never sufficient. The model visual review, page fit, independent review, repair and
manifest gates are separate, so a passing run still reports ready=false.
"""

from io import BytesIO
import re
import unicodedata

from .contracts import require

GATE_VERSION = "mechanical-gates@1"
# Template scale and fonts of private-fixed@2 (rendering.py).
TEMPLATE_FONTS = {"Helvetica"}
TEMPLATE_SIZES = {9.0, 10.0, 11.0, 13.0, 18.0}
HEADING_SIZE = 13.0
FOOTER_SIZE = 9.0
# Helvetica ascender and descender, in 1/1000 em (AFM metrics shipped with ReportLab).
ASCENT, DESCENT = 0.718, 0.207
PRINTABLE_INSET = 36
PLACEHOLDER = re.compile(r"\{\{.*?\}\}|\bTODO\b|\bTBD\b|\[(?:company|role|name|title)\]|lorem ipsum", re.IGNORECASE)
MOJIBAKE = re.compile("Ã[\u0080-¿]|â€|Â[ -¿]")
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|" \
         "august|september|october|november|december"
DATE = re.compile(r"\b(?:(?:" + MONTHS + r")\.?\s+)?(?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?\b", re.IGNORECASE)
SUPPORTED_FORMATS = {"pdf"}


def _squash(text):
    """Whitespace-free comparison form: wrapping may split a token across lines."""
    return "".join(text.split())


def _blocks(page):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    found, problems = [], []

    def visit(text, cm, tm, font, size):
        if not text.strip():
            return
        a, b, c, d = (tm[0] * cm[0] + tm[1] * cm[2], tm[0] * cm[1] + tm[1] * cm[3],
                      tm[2] * cm[0] + tm[3] * cm[2], tm[2] * cm[1] + tm[3] * cm[3])
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        name = str(font.get("/BaseFont", "")).lstrip("/") if font else ""
        if abs(b) > 1e-6 or abs(c) > 1e-6 or abs(a - d) > 1e-6 or a <= 0:
            problems.append("unexpected_transform")
            return
        points = round(float(size) * a, 2)
        line = text.rstrip("\n")
        width = stringWidth(line, name, points) if name in TEMPLATE_FONTS else 0.0
        found.append({"text": line, "font": name, "size": points, "x0": x, "x1": x + width,
                      "y0": y - DESCENT * points, "y1": y + ASCENT * points})

    page.extract_text(visitor_text=visit)
    return found, problems


def _check(results, name, passed, detail=None):
    results[name] = {"status": "passed" if passed else "failed"}
    if detail is not None and not passed:
        results[name]["detail"] = detail


def gate_render(pdf):
    """Gate 1 mechanical checks. Returns (results, blocks, extracted_text)."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    results = {}
    try:
        reader = PdfReader(BytesIO(pdf), strict=True)
        pages = list(reader.pages)
    except (PdfReadError, ValueError, OSError):
        return {"compiles": {"status": "failed", "detail": "unreadable_pdf"}}, [], ""
    _check(results, "compiles", len(pages) == 1, "expected_one_page")
    if len(pages) != 1:
        return results, [], ""
    page = pages[0]
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    blocks, problems = _blocks(page)
    _check(results, "transform", not problems, "rotated_or_skewed_text")
    lo_x, lo_y, hi_x, hi_y = PRINTABLE_INSET, PRINTABLE_INSET, width - PRINTABLE_INSET, height - PRINTABLE_INSET
    clipped = [i for i, b in enumerate(blocks) if b["x0"] < lo_x or b["x1"] > hi_x or b["y0"] < lo_y or b["y1"] > hi_y]
    _check(results, "text_clipping", not clipped, {"blocks": clipped})
    overlaps = [[i, j] for i in range(len(blocks)) for j in range(i + 1, len(blocks))
                if min(blocks[i]["x1"], blocks[j]["x1"]) > max(blocks[i]["x0"], blocks[j]["x0"])
                and min(blocks[i]["y1"], blocks[j]["y1"]) > max(blocks[i]["y0"], blocks[j]["y0"])]
    _check(results, "overlap", not overlaps, {"pairs": overlaps})
    fonts = sorted({b["font"] for b in blocks} - TEMPLATE_FONTS)
    sizes = sorted({b["size"] for b in blocks} - TEMPLATE_SIZES)
    _check(results, "font_consistency", not fonts and not sizes, {"fonts": fonts, "sizes": sizes})
    footers = [b for b in blocks if b["size"] == FOOTER_SIZE]
    body = [b for b in blocks if b["size"] != FOOTER_SIZE]
    collision = bool(footers) and any(f["y1"] > min((b["y0"] for b in body), default=height) for f in footers)
    _check(results, "footer_collision", len(footers) == 1 and not collision, "footer_missing_or_colliding")
    headings = [i for i, b in enumerate(blocks) if b["size"] == HEADING_SIZE]
    orphan = any(not any(b["size"] not in (HEADING_SIZE, FOOTER_SIZE) for b in blocks[i + 1:]) for i in headings)
    _check(results, "orphaned_heading", bool(headings) and not orphan, "heading_without_body")
    # A one-page template has only a final page: whitespace and page-break checks apply to non-final pages.
    results["excessive_whitespace"] = {"status": "not_applicable", "detail": "single_final_page"}
    results["page_break_defects"] = {"status": "not_applicable", "detail": "single_page_template"}
    return results, blocks, page.extract_text()


def gate_text(extracted, expected):
    """Gate 2 on extracted text against the profile, claims and job snapshot it was built from."""
    results = {}
    lines = [line.strip() for line in extracted.splitlines()]
    profile = expected["profile"]
    _check(results, "contact_details", profile["name"] in lines and profile["email"] in lines, "contact_mismatch")
    _check(results, "headings", expected["heading"] in lines, "required_heading_missing")
    results["links"] = {"status": "not_applicable", "detail": "profile_has_no_links"}
    flat, cursor, order_ok = _squash(extracted), 0, True
    for item in expected["sequence"]:
        found = flat.find(_squash(item), cursor)
        if found < 0:
            order_ok = False
            break
        cursor = found + len(_squash(item))
    _check(results, "reading_order", order_ok, "content_missing_or_out_of_order")
    source = "\n".join(expected["sequence"])
    bad = []
    if "�" in extracted:
        bad.append("replacement_character")
    if any("ﬀ" <= ch <= "ﬆ" for ch in extracted) and not any("ﬀ" <= ch <= "ﬆ" for ch in source):
        bad.append("ligature")
    if MOJIBAKE.search(extracted) and not MOJIBAKE.search(source):
        bad.append("mojibake")
    if unicodedata.normalize("NFC", extracted) != extracted and unicodedata.normalize("NFC", source) == source:
        bad.append("unnormalized")
    _check(results, "unicode", not bad, bad)
    _check(results, "placeholders", PLACEHOLDER.search(extracted) is None, "placeholder_present")
    dates = {m.group(0).casefold() for m in DATE.finditer(extracted)}
    known = {m.group(0).casefold() for m in DATE.finditer(source)}
    _check(results, "dates", dates <= known, {"unknown_dates": sorted(dates - known)})
    results["employers_and_titles"] = {"status": "passed", "detail": "covered_by_exact_claim_text"}
    if expected["target"] is None:
        results["target"] = {"status": "not_applicable", "detail": "cv"}
    else:
        _check(results, "target", _squash(expected["target"]) in flat, "target_mismatch")
    return results


def required_format(job):
    """The job's required formats: pdf is supported; anything else blocks input honestly."""
    formats = job.get("required_formats", ["pdf"])
    unsupported = sorted(set(formats) - SUPPORTED_FORMATS)
    if unsupported:
        return {"status": "blocked_input", "detail": {"unsupported_formats": unsupported}}
    return {"status": "passed"}


def verify(pdf, expected, job):
    require(isinstance(pdf, bytes) and pdf.startswith(b"%PDF"), "invalid_schema", "Verification needs PDF bytes.")
    render, _blocks_found, extracted = gate_render(pdf)
    text = gate_text(extracted, expected) if extracted else {"extraction": {"status": "failed"}}
    fmt = required_format(job)
    failed = sorted(f"{gate}.{name}" for gate, checks in (("render", render), ("text", text))
                    for name, check in checks.items() if check["status"] == "failed")
    if fmt["status"] != "passed":
        status = "blocked_input"
    elif failed:
        status = "blocked_quality"
    else:
        status = "mechanical_passed"
    return {"gate_version": GATE_VERSION, "status": status, "ready": False, "failed_checks": failed,
            "gates": {"render": render, "text": text, "format": fmt,
                      "visual_review": {"status": "not_run",
                                        "detail": "model page-image review is not implemented"}},
            "remaining_gates": ["visual_review", "page_fit", "independent_review", "bounded_repair", "manifest"]}
