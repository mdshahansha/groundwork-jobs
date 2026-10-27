from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "job-application-platform-prd.md"
OUTPUT = ROOT / "output" / "pdf" / "job-application-platform-prd-hld-lld.pdf"


def clean(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#d9e2ec"))
    canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#627d98"))
    canvas.drawString(18 * mm, 9 * mm, "AI Job Application Platform | Architecture proposal")
    canvas.drawRightString(192 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleCustom", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=30, textColor=colors.HexColor("#102a43"), alignment=TA_CENTER, spaceAfter=12))
    styles.add(ParagraphStyle(name="Subtitle", parent=styles["Normal"], fontSize=11, leading=15, textColor=colors.HexColor("#486581"), alignment=TA_CENTER, spaceAfter=22))
    styles.add(ParagraphStyle(name="H1Custom", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=colors.HexColor("#0b7285"), spaceBefore=14, spaceAfter=8, keepWithNext=True))
    styles.add(ParagraphStyle(name="H2Custom", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=colors.HexColor("#243b53"), spaceBefore=9, spaceAfter=4, keepWithNext=True))
    styles.add(ParagraphStyle(name="BodyCustom", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=14, textColor=colors.HexColor("#243b53"), spaceAfter=6))
    styles.add(ParagraphStyle(name="BulletCustom", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.3, leading=13.5, leftIndent=13, firstLineIndent=-8, bulletIndent=5, spaceAfter=3, textColor=colors.HexColor("#243b53")))

    story = []
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    story.append(Spacer(1, 18 * mm))
    first = True
    for line in lines:
        line = line.strip()
        if not line:
            story.append(Spacer(1, 3))
            continue
        if line.startswith("# "):
            if not first:
                story.append(PageBreak())
            story.append(Paragraph(clean(line[2:]), styles["TitleCustom"]))
            first = False
        elif line.startswith("## "):
            story.append(Paragraph(clean(line[3:]), styles["H1Custom"]))
        elif line.startswith("### "):
            story.append(Paragraph(clean(line[4:]), styles["H2Custom"]))
        elif line.startswith("- "):
            story.append(Paragraph(clean(line[2:]), styles["BulletCustom"], bulletText="•"))
        else:
            story.append(Paragraph(clean(line), styles["BodyCustom"]))
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=17 * mm, bottomMargin=19 * mm, title="AI Job Application Platform PRD, HLD and LLD")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUTPUT)


if __name__ == "__main__":
    main()
