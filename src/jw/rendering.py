"""Fixed data-only private PDF template. This is not a LaTeX sandbox."""

from io import BytesIO
from pathlib import Path
import hashlib
import importlib.metadata

from .contracts import fields, require, string

TEMPLATE_VERSION = "private-fixed@1"
REPORTLAB_VERSION = "4.4.9"
PAGE_WIDTH, PAGE_HEIGHT = 595.2756, 841.8898
MARGIN, FONT_SIZE, LEADING = 48, 11, 16


def _text(value, maximum):
    string(value, maximum)
    try:
        value.encode("cp1252", errors="strict")
    except UnicodeError:
        require(False, "unsupported_glyph", "The fixed Latin template cannot render this character; no substitution was made.")
    return value


def render_private_pdf(profile, assertions, kind):
    """Return PDF bytes + deterministic layout report; never evaluate input markup.

    The only ReportLab text primitive is drawString. No Paragraph/XML parser,
    image loaders, URL resolver, arbitrary font or template paths are exposed.
    """
    fields(profile, {"name", "email"})
    require(kind in ("draft_cv", "draft_letter"), "invalid_schema", "Only CV and letter drafts can render.")
    _text(profile["name"], 120)
    _text(profile["email"], 254)
    require(isinstance(assertions, list) and 1 <= len(assertions) <= 100,
            "invalid_schema", "Render requires 1..100 assertions.")
    for assertion in assertions:
        fields(assertion, {"text", "claim_id"})
        _text(assertion["text"], 2000)
        string(assertion["claim_id"], 100)
    require(sum(len(a["text"]) for a in assertions) <= 20000,
            "input_too_large", "Render text exceeds 20000 characters.")
    try:
        version = importlib.metadata.version("reportlab")
    except importlib.metadata.PackageNotFoundError:
        require(False, "toolchain_missing", "Install the pinned render extra: groundwork-jobs[render].")
    require(version == REPORTLAB_VERSION, "toolchain_version", "Renderer version differs from the qualified pin.")
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen.canvas import Canvas

    width = PAGE_WIDTH - 2 * MARGIN
    lines = []

    def append_text(text, size, gap=0):
        # Greedy glyph wrapping has a fixed input bound and preserves all glyphs.
        # Prefer a word boundary, but long tokens must also fit without shrinking.
        for paragraph in text.replace("\t", "    ").split("\n"):
            pending = paragraph
            if not pending:
                lines.append(("", size))
            while pending:
                count = 0
                measured = 0
                for char in pending:
                    addition = stringWidth(char, "Helvetica", size)
                    if measured + addition > width:
                        break
                    measured += addition
                    count += 1
                require(count > 0, "layout_conflict", "A glyph exceeds the available line width.")
                if count < len(pending):
                    boundary = pending.rfind(" ", 0, count + 1)
                    if boundary > 0:
                        count = boundary
                lines.append((pending[:count], size))
                pending = pending[count:]
                if pending.startswith(" "):
                    pending = pending[1:]
        for _ in range(gap):
            lines.append(("", FONT_SIZE))

    append_text("PRIVATE DRAFT - NOT READY", 10, 1)
    append_text(profile["name"], 18)
    append_text(profile["email"], FONT_SIZE, 1)
    append_text("Curriculum vitae" if kind == "draft_cv" else "Cover letter", 13, 1)
    for assertion in assertions:
        append_text(assertion["text"], FONT_SIZE, 1)

    y = PAGE_HEIGHT - MARGIN - 18
    blocks = []
    for text, size in lines:
        require(y - size * .25 >= MARGIN + 24, "page_fit_conflict",
                "Content does not fit one page. Shorten the selected draft; font size will not shrink.")
        if text:
            blocks.append({"text": text, "x": MARGIN, "baseline": y, "size": size,
                           "width": stringWidth(text, "Helvetica", size)})
        y -= max(LEADING, size + 4)

    output = BytesIO()
    canvas = Canvas(output, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), pageCompression=1, invariant=1)
    canvas.setTitle("Private application draft")
    canvas.setAuthor("")
    canvas.setSubject("Unverified draft; not an application or submission")
    for block in blocks:
        canvas.setFont("Helvetica", block["size"])
        canvas.drawString(block["x"], block["baseline"], block["text"])
    canvas.setFont("Helvetica", 9)
    canvas.drawString(MARGIN, MARGIN, "Private review only. Quality gates incomplete. Page 1 of 1.")
    canvas.showPage()
    canvas.save()
    pdf = output.getvalue()
    return pdf, {"template": TEMPLATE_VERSION, "renderer": "reportlab", "renderer_version": version,
                 "sha256": hashlib.sha256(pdf).hexdigest(), "pages": 1, "ready": False,
                 "classification": "private_review_material", "body_font_points": FONT_SIZE,
                 "line_count": len(blocks)}


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
