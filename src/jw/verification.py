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

GATE_VERSION = "mechanical-gates@2"
# Template scale of private-fixed@3 (rendering.py). The font comes from the expected content.
TEMPLATE_SIZES = {9.0, 10.0, 11.0, 13.0, 18.0}
HEADING_SIZE = 13.0
FOOTER_SIZE = 9.0
# Helvetica, the default when the expected content names no font.
BASE = {"name": "Helvetica", "ascent": 0.718, "descent": 0.207}
# Blank share of a non-final page's content area above which the page counts as underfilled (FR-DOC-03).
WHITESPACE_LIMIT = 0.35
CONTENT_TOP, CONTENT_BOTTOM = 841.8898 - 48 - 18, 48 + 24
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


def _font_name(raw, expected):
    """TrueType subsets are embedded as `XXXXXX+<name>`; report the registered name when it matches."""
    name = raw.split("+", 1)[1] if len(raw) > 7 and raw[6] == "+" else raw
    return expected["name"] if name in (expected["name"], expected.get("face")) else name


def _blocks(page, font=BASE):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    found, problems = [], []

    def visit(text, cm, tm, pdf_font, size):
        if not text.strip():
            return
        a, b, c, d = (tm[0] * cm[0] + tm[1] * cm[2], tm[0] * cm[1] + tm[1] * cm[3],
                      tm[2] * cm[0] + tm[3] * cm[2], tm[2] * cm[1] + tm[3] * cm[3])
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        name = _font_name(str(pdf_font.get("/BaseFont", "")).lstrip("/"), font) if pdf_font else ""
        if abs(b) > 1e-6 or abs(c) > 1e-6 or abs(a - d) > 1e-6 or a <= 0:
            problems.append("unexpected_transform")
            return
        points = round(float(size) * a, 2)
        line = text.rstrip("\n")
        width = stringWidth(line, name, points) if name == font["name"] else 0.0
        found.append({"text": line, "font": name, "size": points, "x0": x, "x1": x + width,
                      "y0": y - font["descent"] * points, "y1": y + font["ascent"] * points})

    page.extract_text(visitor_text=visit)
    return found, problems


def _check(results, name, passed, detail=None):
    results[name] = {"status": "passed" if passed else "failed"}
    if detail is not None and not passed:
        results[name]["detail"] = detail


def _starts(expected):
    """Squashed first-line prefixes: a line that begins one of these begins a block."""
    return [_squash(item) for item in expected["sequence"]] if expected else []


def _block_start(line, items):
    squashed = _squash(line)
    return any(item.startswith(squashed) for item in items)


def _block_whole(line, items):
    return _squash(line) in items


def gate_render(pdf, expected=None):
    """Gate 1 mechanical checks over every page. Returns (results, blocks, extracted_text).

    Without expected content (drawn fixtures), the limit is one page in Helvetica and page-break
    checks have no block boundaries to use.
    """
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    from .rendering import footer

    font = (expected or {}).get("font", BASE)
    limit = (expected or {}).get("page_limit", 1)
    results = {}
    try:
        reader = PdfReader(BytesIO(pdf), strict=True)
        pages = list(reader.pages)
    except (PdfReadError, ValueError, OSError):
        return {"compiles": {"status": "failed", "detail": "unreadable_pdf"}}, [], ""
    _check(results, "compiles", 1 <= len(pages) <= limit, {"pages": len(pages), "page_limit": limit})
    if not 1 <= len(pages) <= limit:
        return results, [], ""
    count, every, problems = len(pages), [], []
    clipped, overlaps, fonts, sizes = [], [], set(), set()
    footer_bad, orphan, headings_seen, underfilled, breaks = [], [], False, [], []
    per_page = []
    for number, page in enumerate(pages, 1):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        blocks, issues = _blocks(page, font)
        problems += issues
        lo_x, lo_y, hi_x, hi_y = PRINTABLE_INSET, PRINTABLE_INSET, width - PRINTABLE_INSET, height - PRINTABLE_INSET
        clipped += [[number, i] for i, b in enumerate(blocks)
                    if b["x0"] < lo_x or b["x1"] > hi_x or b["y0"] < lo_y or b["y1"] > hi_y]
        overlaps += [[number, i, j] for i in range(len(blocks)) for j in range(i + 1, len(blocks))
                     if min(blocks[i]["x1"], blocks[j]["x1"]) > max(blocks[i]["x0"], blocks[j]["x0"])
                     and min(blocks[i]["y1"], blocks[j]["y1"]) > max(blocks[i]["y0"], blocks[j]["y0"])]
        fonts |= {b["font"] for b in blocks} - {font["name"]}
        sizes |= {b["size"] for b in blocks} - TEMPLATE_SIZES
        footers = [b for b in blocks if b["size"] == FOOTER_SIZE]
        body = [b for b in blocks if b["size"] != FOOTER_SIZE]
        collision = bool(footers) and any(f["y1"] > min((b["y0"] for b in body), default=height) for f in footers)
        if len(footers) != 1 or collision or footers[0]["text"].strip() != footer(number, count):
            footer_bad.append(number)
        headings = [i for i, b in enumerate(blocks) if b["size"] == HEADING_SIZE]
        headings_seen = headings_seen or bool(headings)
        # The block right after a heading must be body on the same page: a heading followed by another
        # heading, the footer or the page end is orphaned.
        if any(i + 1 >= len(blocks) or blocks[i + 1]["size"] in (HEADING_SIZE, FOOTER_SIZE) for i in headings):
            orphan.append(number)
        if number < count and body:
            blank = (min(b["y0"] for b in body) - CONTENT_BOTTOM) / (CONTENT_TOP - CONTENT_BOTTOM)
            if blank > WHITESPACE_LIMIT:
                underfilled.append({"page": number, "blank": round(blank, 3)})
        per_page.append(body)
        every += blocks
    _check(results, "transform", not problems, "rotated_or_skewed_text")
    _check(results, "text_clipping", not clipped, {"blocks": clipped})
    _check(results, "overlap", not overlaps, {"pairs": overlaps})
    _check(results, "font_consistency", not fonts and not sizes, {"fonts": sorted(fonts), "sizes": sorted(sizes)})
    _check(results, "footer_collision", not footer_bad, {"pages": footer_bad})
    _check(results, "orphaned_heading", headings_seen and not orphan, {"pages": orphan})
    if count == 1:
        results["excessive_whitespace"] = {"status": "not_applicable", "detail": "single_final_page"}
        results["page_break_defects"] = {"status": "not_applicable", "detail": "single_page"}
    else:
        _check(results, "excessive_whitespace", not underfilled, {"pages": underfilled})
        items = _starts(expected)
        for number in range(1, count):
            before, after = per_page[number - 1], per_page[number]
            # A block's first line alone at the foot of a page, or its last line alone at the head of the next.
            if before and _block_start(before[-1]["text"], items) and not _block_whole(before[-1]["text"], items):
                breaks.append({"page": number, "defect": "lone_first_line"})
            if after and not _block_start(after[0]["text"], items) and \
                    (len(after) == 1 or _block_start(after[1]["text"], items)):
                breaks.append({"page": number + 1, "defect": "lone_last_line"})
        if items:
            _check(results, "page_break_defects", not breaks, breaks)
        else:
            results["page_break_defects"] = {"status": "failed", "detail": "no_expected_content_to_check_breaks"}
    # Footers are left out, so an item wrapped across a page break still reads as one run.
    text = "\n".join(b["text"] for page in per_page for b in page)
    return results, every, text


def gate_text(extracted, expected):
    """Gate 2 on extracted text against the profile, claims and job snapshot it was built from."""
    results = {}
    lines = [line.strip() for line in extracted.splitlines()]
    profile, flat = expected["profile"], _squash(extracted)
    # Squashed, so a long name or email the renderer wrapped across lines still matches.
    _check(results, "contact_details", _squash(profile["name"]) in flat and _squash(profile["email"]) in flat,
           "contact_mismatch")
    _check(results, "headings", expected["heading"] in lines, "required_heading_missing")
    results["links"] = {"status": "not_applicable", "detail": "profile_has_no_links"}
    cursor, order_ok = 0, True
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
    if not isinstance(formats, list) or not formats or not all(isinstance(f, str) for f in formats):
        return {"status": "blocked_input", "detail": {"invalid_required_formats": True}}
    unsupported = sorted(set(formats) - SUPPORTED_FORMATS)
    if unsupported:
        return {"status": "blocked_input", "detail": {"unsupported_formats": unsupported}}
    return {"status": "passed"}


def verify(pdf, expected, job):
    require(isinstance(pdf, bytes) and pdf.startswith(b"%PDF"), "invalid_schema", "Verification needs PDF bytes.")
    render, _blocks_found, extracted = gate_render(pdf, expected)
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
                      "visual_review": {"status": "pending_review_task",
                                        "detail": "page images go to the independent review task (visual.py)"}},
            "remaining_gates": ["visual_review", "page_fit", "independent_review", "bounded_repair", "manifest"]}
