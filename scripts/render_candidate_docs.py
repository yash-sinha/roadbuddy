from __future__ import annotations

from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[2]


def build_styles(doc_kind: str):
    styles = getSampleStyleSheet()
    body_size = 8.9 if doc_kind == "prd" else 9.5
    leading = 10.6 if doc_kind == "prd" else 11.8
    heading_space_before = 5 if doc_kind == "prd" else 8
    heading_space_after = 3 if doc_kind == "prd" else 5
    body_space_after = 3 if doc_kind == "prd" else 5

    styles.add(ParagraphStyle(
        name="DocTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=21,
        textColor=colors.HexColor("#111827"),
        alignment=TA_CENTER,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="DocMeta",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=10,
        textColor=colors.HexColor("#4b5563"),
        alignment=TA_CENTER,
        spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        name="DocH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11.2,
        leading=13,
        textColor=colors.HexColor("#111827"),
        spaceBefore=heading_space_before,
        spaceAfter=heading_space_after,
    ))
    styles.add(ParagraphStyle(
        name="DocBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=body_size,
        leading=leading,
        textColor=colors.HexColor("#1f2937"),
        spaceAfter=body_space_after,
    ))
    styles.add(ParagraphStyle(
        name="DocBullet",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=body_size,
        leading=leading,
        leftIndent=10,
        textColor=colors.HexColor("#1f2937"),
    ))
    styles.add(ParagraphStyle(
        name="DocTableHeader",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=7.7 if doc_kind == "prd" else 8.4,
        leading=9.1 if doc_kind == "prd" else 10,
        textColor=colors.HexColor("#111827"),
    ))
    styles.add(ParagraphStyle(
        name="DocTableCell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7.55 if doc_kind == "prd" else 8.2,
        leading=8.9 if doc_kind == "prd" else 9.8,
        textColor=colors.HexColor("#1f2937"),
    ))
    return styles


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawCentredString(LETTER[0] / 2, 0.45 * inch, f"{doc.title} | Page {canvas.getPageNumber()}")
    canvas.restoreState()


def parse_markdown(markdown_text: str, styles) -> list:
    story = []
    bullet_items: list[ListItem] = []
    paragraph_lines: list[str] = []
    table_lines: list[str] = []
    title_seen = False
    meta_seen = False

    def flush_paragraph():
        nonlocal paragraph_lines
        if paragraph_lines:
            story.append(Paragraph(" ".join(paragraph_lines), styles["DocBody"]))
            paragraph_lines = []

    def flush_bullets():
        nonlocal bullet_items
        if bullet_items:
            story.append(ListFlowable(bullet_items, bulletType="bullet", leftIndent=12, bulletFontName="Helvetica"))
            story.append(Spacer(1, 4))
            bullet_items = []

    def parse_table_row(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    def is_table_separator(line: str) -> bool:
        cells = parse_table_row(line)
        return bool(cells) and all(set(cell.replace(":", "").strip()) <= {"-"} for cell in cells)

    def flush_table():
        nonlocal table_lines
        if not table_lines:
            return
        rows = [parse_table_row(row) for row in table_lines if not is_table_separator(row)]
        if rows:
            col_count = len(rows[0])
            col_widths = None
            if col_count == 4:
                col_widths = [0.95 * inch, 2.6 * inch, 0.9 * inch, 2.8 * inch]
            data = []
            for row_index, row in enumerate(rows):
                style = styles["DocTableHeader"] if row_index == 0 else styles["DocTableCell"]
                data.append([Paragraph(cell, style) for cell in row])
            table = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(table)
            story.append(Spacer(1, 5))
        table_lines = []

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_bullets()
            flush_table()
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            flush_bullets()
            table_lines.append(line)
            continue
        flush_table()
        if line == "<!-- pagebreak -->":
            flush_paragraph()
            flush_bullets()
            story.append(PageBreak())
            continue
        if line.startswith("# "):
            flush_paragraph()
            flush_bullets()
            style_name = "DocTitle" if not title_seen else "DocH2"
            story.append(Paragraph(line[2:].strip(), styles[style_name]))
            title_seen = True
            continue
        if line.startswith("## "):
            flush_paragraph()
            flush_bullets()
            meta_seen = True
            story.append(Paragraph(line[3:].strip(), styles["DocH2"]))
            continue
        if line.startswith("- "):
            flush_paragraph()
            bullet_items.append(ListItem(Paragraph(line[2:].strip(), styles["DocBullet"])))
            continue
        if title_seen and not meta_seen:
            story.append(Paragraph(line, styles["DocMeta"]))
            meta_seen = True
            continue
        paragraph_lines.append(line)

    flush_paragraph()
    flush_bullets()
    flush_table()
    return story


def render(md_path: Path, pdf_path: Path, doc_kind: str):
    styles = build_styles(doc_kind)
    story = parse_markdown(md_path.read_text(), styles)
    margin = 0.5 * inch if doc_kind == "prd" else 0.62 * inch
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=LETTER,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=0.48 * inch if doc_kind == "prd" else 0.58 * inch,
        bottomMargin=0.55 * inch if doc_kind == "prd" else 0.62 * inch,
        title=md_path.stem.replace("_", " "),
        author="Yash",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def main():
    docs = [
        (ROOT / "PRD_Insurance_CoPilot.md", ROOT / "PRD_Insurance_CoPilot.pdf", "prd"),
        (ROOT / "SystemDesign_Insurance_CoPilot.md", ROOT / "SystemDesign_Insurance_CoPilot.pdf", "system"),
    ]
    for md_path, pdf_path, doc_kind in docs:
        render(md_path, pdf_path, doc_kind)
        print(f"Rendered {pdf_path}")


if __name__ == "__main__":
    main()
