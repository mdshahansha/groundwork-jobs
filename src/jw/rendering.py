"""Fixed data-only private PDF template. This is not a LaTeX sandbox."""

from io import BytesIO
from pathlib import Path
import hashlib
import importlib.metadata
import unicodedata

from .contracts import fields, require, string

TEMPLATE_VERSION = "private-fixed@3"
REPORTLAB_VERSION = "4.4.9"
PAGE_WIDTH, PAGE_HEIGHT = 595.2756, 841.8898
MARGIN, FONT_SIZE, LEADING = 48, 11, 16
HEADING_SIZE = 13
# A block of this many lines or fewer is never split across pages; a longer one keeps two lines on each side.
KEEP_TOGETHER, MIN_SPLIT = 6, 2
DEFAULT_PAGE_LIMIT = {"draft_cv": 2, "draft_letter": 1}
BASE_FONT = "Helvetica"
# Helvetica ascender and descender, in 1/1000 em (AFM metrics shipped with ReportLab).
BASE_METRICS = (0.718, 0.207)
# Scripts that need shaping or right-to-left layout. drawString does neither, so they are refused
# instead of rendered as wrong, disconnected glyphs.
SHAPED = ((0x0590, 0x08FF), (0x0900, 0x0DFF), (0x0E00, 0x0FFF), (0x1000, 0x109F), (0x1780, 0x17FF),
          (0xFB1D, 0xFDFF), (0xFE70, 0xFEFF))


def footer(page, pages):
    return f"Private review only. Quality gates incomplete. Page {page} of {pages}."


WARNING = "PRIVATE DRAFT - NOT READY"
FOOTER = footer(1, 1)
HEADINGS = {"draft_cv": "Curriculum vitae", "draft_letter": "Cover letter"}


def target_line(job):
    """Letters name the job snapshot's role and employer; gate 2 checks they match it."""
    return None if job is None else f"Application for {job['title']} at {job['company']}"


def page_limit(kind, job=None):
    limit = (job or {}).get("page_limit", DEFAULT_PAGE_LIMIT[kind])
    require(type(limit) is int and 1 <= limit <= 3, "invalid_schema", "page_limit must be 1, 2 or 3.")
    return limit


def load_font(font):
    """Helvetica (Windows-1252) by default; an owner-supplied TrueType font pinned by SHA-256 otherwise.

    Returns {name, ascent, descent, sha256, covers}. The file is read once and hashed before ReportLab
    parses it, so a swapped file never renders.
    """
    if font is None:
        return {"name": BASE_FONT, "ascent": BASE_METRICS[0], "descent": BASE_METRICS[1], "sha256": None,
                "covers": None}
    fields(font, {"path", "sha256"})
    string(font["path"], 4096)
    string(font["sha256"], 64)
    try:
        data = Path(font["path"]).read_bytes()
    except OSError:
        require(False, "toolchain_missing", "The configured render font cannot be read.")
    require(hashlib.sha256(data).hexdigest() == font["sha256"], "toolchain_version",
            "The render font differs from its pinned SHA-256; set it again after review.")
    from io import BytesIO as _Bytes
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFError, TTFont

    name = "JW-" + font["sha256"][:12]
    try:
        registered = pdfmetrics.getFont(name)
    except KeyError:
        try:
            registered = TTFont(name, _Bytes(data))
        except (TTFError, ValueError, OSError):
            require(False, "toolchain_missing", "The render font is not a usable TrueType font.")
        pdfmetrics.registerFont(registered)
    face = registered.face
    widths = face.charWidths
    # A cmap entry may point at glyph 0 (.notdef) or carry no advance: that prints nothing, so it is not coverage.
    covers = {code for code, glyph in face.charToGlyph.items() if glyph and widths.get(code, 0) > 0}
    covers.add(32)
    return {"name": name, "ascent": face.ascent / 1000, "descent": -face.descent / 1000,
            "sha256": font["sha256"], "covers": covers, "face": face.name.decode("latin-1")}


def _text(value, maximum, font=None):
    string(value, maximum)
    if font is None or font["covers"] is None:
        try:
            value.encode("cp1252", errors="strict")
        except UnicodeError:
            require(False, "unsupported_glyph", "The fixed Latin template cannot render this character; no substitution was made.")
        return value
    for char in value:
        code = ord(char)
        if char in "\n\t":
            continue
        shaped = any(lo <= code <= hi for lo, hi in SHAPED) or unicodedata.category(char) in ("Mn", "Me")
        require(not shaped, "unsupported_glyph",
                "This script needs shaping or right-to-left layout, which the fixed template does not do.")
        require(code in font["covers"], "unsupported_glyph",
                "The configured font has no glyph for a character; no substitution was made.")
    return value


def expected_content(profile, assertions, kind, job=None, font=None):
    """What a reader must extract, in order. Built from inputs, not from renderer output."""
    target = target_line(job) if kind == "draft_letter" else None
    sequence = [WARNING, profile["name"], profile["email"], HEADINGS[kind]]
    sequence += ([target] if target else []) + [a["text"] for a in assertions]
    face = load_font(font)
    return {"profile": profile, "heading": HEADINGS[kind], "target": target, "sequence": sequence,
            "page_limit": page_limit(kind, job),
            "font": {"name": face["name"], "face": face.get("face", BASE_FONT), "ascent": face["ascent"],
                     "descent": face["descent"]}}


def render_private_pdf(profile, assertions, kind, job=None, font=None):
    """Return PDF bytes + deterministic layout report; never evaluate input markup.

    The only ReportLab text primitive is drawString. No Paragraph/XML parser,
    image loaders, URL resolver, arbitrary font or template paths are exposed.
    `font` is an owner-pinned {path, sha256} TrueType file, or None for Helvetica.
    """
    fields(profile, {"name", "email"})
    require(kind in ("draft_cv", "draft_letter"), "invalid_schema", "Only CV and letter drafts can render.")
    limit = page_limit(kind, job)
    try:
        version = importlib.metadata.version("reportlab")
    except importlib.metadata.PackageNotFoundError:
        require(False, "toolchain_missing", "Install the pinned render extra: groundwork-jobs[render].")
    require(version == REPORTLAB_VERSION, "toolchain_version", "Renderer version differs from the qualified pin.")
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
    except ImportError:
        # Installed metadata but an unimportable package is still a missing toolchain, not a crash.
        require(False, "toolchain_missing", "The renderer is installed but cannot be imported.")
    from reportlab.pdfgen.canvas import Canvas

    face = load_font(font)
    typeface = face["name"]
    _text(profile["name"], 120, face)
    _text(profile["email"], 254, face)
    require(isinstance(assertions, list) and 1 <= len(assertions) <= 100,
            "invalid_schema", "Render requires 1..100 assertions.")
    for assertion in assertions:
        fields(assertion, {"text", "claim_id"})
        _text(assertion["text"], 2000, face)
        string(assertion["claim_id"], 100)
    target = target_line(job) if kind == "draft_letter" else None
    if target is not None:
        _text(job["title"], 200, face)
        _text(job["company"], 200, face)
    require(sum(len(a["text"]) for a in assertions) <= 20000,
            "input_too_large", "Render text exceeds 20000 characters.")

    width = PAGE_WIDTH - 2 * MARGIN
    blocks = []

    def wrap(text, size):
        # Greedy glyph wrapping has a fixed input bound and preserves all glyphs.
        # Prefer a word boundary, but long tokens must also fit without shrinking.
        lines = []
        for paragraph in text.replace("\t", "    ").split("\n"):
            pending = paragraph
            if not pending:
                lines.append("")
            while pending:
                count = 0
                measured = 0
                for char in pending:
                    addition = stringWidth(char, typeface, size)
                    if measured + addition > width:
                        break
                    measured += addition
                    count += 1
                require(count > 0, "layout_conflict", "A glyph exceeds the available line width.")
                if count < len(pending):
                    boundary = pending.rfind(" ", 0, count + 1)
                    if boundary > 0:
                        count = boundary
                lines.append(pending[:count])
                pending = pending[count:]
                if pending.startswith(" "):
                    pending = pending[1:]
        return lines

    def add(text, size, gap=0, heading=False):
        blocks.append({"lines": wrap(text, size), "size": size, "gap": gap, "heading": heading})

    add(WARNING, 10, 1)
    add(profile["name"], 18)
    add(profile["email"], FONT_SIZE, 1)
    add(HEADINGS[kind], HEADING_SIZE, 1, heading=True)
    if target is not None:
        add(target, FONT_SIZE, 1)
    for assertion in assertions:
        add(assertion["text"], FONT_SIZE, 1)

    top, floor = PAGE_HEIGHT - MARGIN - 18, MARGIN + 24

    def step(size):
        return max(LEADING, size + 4)

    def room(y, size):
        """Lines of `size` that still fit below baseline y on this page."""
        count = 0
        while y - size * .25 >= floor:
            count += 1
            y -= step(size)
        return count

    pages, y = [[]], top

    def new_page():
        nonlocal y
        pages.append([])
        y = top
        require(len(pages) <= limit, "page_fit_conflict",
                f"Content does not fit {limit} page(s). Shorten the selected draft; font size will not shrink.")

    def place(lines, size):
        nonlocal y
        for text in lines:
            if text:
                pages[-1].append({"text": text, "baseline": y, "size": size,
                                  "width": stringWidth(text, typeface, size)})
            y -= step(size)

    for index, block in enumerate(blocks):
        lines, size = block["lines"], block["size"]
        if block["heading"] and index + 1 < len(blocks):
            # Keep with next: the heading moves unless the start of the next block can follow it.
            following = blocks[index + 1]["lines"]
            needed = len(lines) + block["gap"] + (len(following) if len(following) <= KEEP_TOGETHER else MIN_SPLIT)
            if room(y, size) < needed and pages[-1]:
                new_page()
        rest, started = lines, False
        while rest:
            free, total = room(y, size), len(rest)
            if total <= free:
                take = total
            elif pages[-1] and (free < MIN_SPLIT or (not started and total <= KEEP_TOGETHER)):
                new_page()
                continue
            else:
                # Split, leaving at least two lines on each side of the break.
                take = min(free, total - MIN_SPLIT)
                if take < MIN_SPLIT and pages[-1]:
                    new_page()
                    continue
            place(rest[:take], size)
            rest, started = rest[take:], True
            if rest:
                new_page()
        for _ in range(block["gap"]):
            if room(y, FONT_SIZE):
                y -= step(FONT_SIZE)

    count = len(pages)
    output = BytesIO()
    canvas = Canvas(output, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), pageCompression=1, invariant=1)
    canvas.setTitle("Private application draft")
    canvas.setAuthor("")
    canvas.setSubject("Unverified draft; not an application or submission")
    for number, page in enumerate(pages, 1):
        for line in page:
            canvas.setFont(typeface, line["size"])
            canvas.drawString(MARGIN, line["baseline"], line["text"])
        canvas.setFont(typeface, 9)
        canvas.drawString(MARGIN, MARGIN, footer(number, count))
        canvas.showPage()
    canvas.save()
    pdf = output.getvalue()
    return pdf, {"template": TEMPLATE_VERSION, "renderer": "reportlab", "renderer_version": version,
                 "sha256": hashlib.sha256(pdf).hexdigest(), "pages": count, "page_limit": limit,
                 "font": face.get("face", BASE_FONT), "font_sha256": face["sha256"], "ready": False,
                 "classification": "private_review_material", "body_font_points": FONT_SIZE,
                 "line_count": sum(len(page) for page in pages)}


def write_new_pdf(destination, pdf):
    """Explicit export copy, exclusive create; existing files are never overwritten."""
    path = Path(destination).resolve()
    require(path.suffix.lower() == ".pdf", "invalid_path", "Private PDF output must have .pdf extension.")
    require(path.parent.is_dir(), "invalid_path", "Choose an existing private output directory.")
    try:
        with path.open("xb") as stream:
            stream.write(pdf)
    except FileExistsError:
        require(False, "output_exists", "Output exists; select a new filename.")
    return str(path)
