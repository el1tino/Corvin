"""Exports a draft's Markdown-ish content to DOCX or PDF for manual
submission by a human (build spec: "Drafts are exported as DOCX or PDF for
manual submission"; actual submission to an authority portal is explicitly
out of scope).

The renderer understands a small, deliberate subset of Markdown -- `#`/`##`
headings, `**bold**`, `*italic*`, and `- ` bullet lists -- enough for the
templates in templates/*.md.j2, without pulling in a full Markdown engine.
"""

from __future__ import annotations

import io
import re

from docx import Document
from docx.shared import Pt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")


def _line_kind(line: str) -> tuple[str, str]:
    stripped = line.rstrip()
    if stripped.startswith("# "):
        return "h1", stripped[2:]
    if stripped.startswith("## "):
        return "h2", stripped[3:]
    if stripped.startswith("- "):
        return "bullet", stripped[2:]
    if stripped.startswith("---"):
        return "rule", ""
    if not stripped.strip():
        return "blank", ""
    return "para", stripped


def export_to_docx(content: str, *, title: str) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.size = Pt(10.5)

    for line in content.splitlines():
        kind, text = _line_kind(line)
        if kind == "h1":
            doc.add_heading(text, level=1)
        elif kind == "h2":
            doc.add_heading(text, level=2)
        elif kind == "bullet":
            p = doc.add_paragraph(style="List Bullet")
            _add_runs(p, text)
        elif kind == "rule":
            doc.add_paragraph("_" * 40)
        elif kind == "blank":
            doc.add_paragraph("")
        else:
            p = doc.add_paragraph()
            _add_runs(p, text)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _add_runs(paragraph, text: str) -> None:
    pos = 0
    for match in _BOLD_PATTERN.finditer(text):
        if match.start() > pos:
            paragraph.add_run(text[pos : match.start()])
        run = paragraph.add_run(match.group(1))
        run.bold = True
        pos = match.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def export_to_pdf(content: str, *, title: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("CorvinH1", parent=styles["Heading1"], spaceAfter=10)
    h2 = ParagraphStyle("CorvinH2", parent=styles["Heading2"], spaceAfter=8)
    body = ParagraphStyle("CorvinBody", parent=styles["Normal"], spaceAfter=6, leading=14)
    bullet = ParagraphStyle("CorvinBullet", parent=body, leftIndent=14, bulletIndent=4)

    story = []
    for line in content.splitlines():
        kind, text = _line_kind(line)
        text = _BOLD_PATTERN.sub(r"<b>\1</b>", text)
        if kind == "h1":
            story.append(Paragraph(text, h1))
        elif kind == "h2":
            story.append(Paragraph(text, h2))
        elif kind == "bullet":
            story.append(Paragraph(f"&bull; {text}", bullet))
        elif kind == "rule":
            story.append(Spacer(1, 4 * mm))
        elif kind == "blank":
            story.append(Spacer(1, 2 * mm))
        else:
            story.append(Paragraph(text, body))

    doc.build(story)
    return buffer.getvalue()
