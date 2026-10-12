"""
backend/docgen/pdf_exporter.py
------------------------------
Generates an executive-grade, publication-ready PDF document for the repository documentation suite
using ReportLab with dynamic cover page, responsive auto-wrapping tables, high-resolution rendered
diagrams, clean page breaks, running headers/footers, and page numbers.
Raw Mermaid syntax is NEVER rendered in the PDF.
Character encoding is fully sanitized to prevent .notdef tofu black squares (■).
Code blocks, tree hierarchies, and formatting are strictly parsed with zero raw <br/> artifacts.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from docgen.secret_redactor import redact_secrets

logger = logging.getLogger(__name__)


# ── UNICODE & TEXT SANITIZATION (ZERO BLACK SQUARES / TOFU) ───────────────────

def _sanitize_pdf_text(text: str) -> str:
    """
    Normalizes Unicode punctuation, hyphens, quotes, bullets, spaces, and box-drawing characters
    into standard ASCII or ReportLab-safe representations.
    Prevents ReportLab Type 1 fonts (Helvetica, Courier, Times) from falling back to .notdef tofu (■).
    """
    if not text:
        return ""

    # 1. Hyphens and dashes (Root cause of single■page, front■end, server■side, client■side)
    text = text.replace("\u2010", "-")   # Hyphen
    text = text.replace("\u2011", "-")   # Non-breaking hyphen (U+2011)
    text = text.replace("\u2012", "-")   # Figure dash
    text = text.replace("\u2013", "-")   # En dash (U+2013)
    text = text.replace("\u2014", "--")  # Em dash (U+2014)
    text = text.replace("\u2015", "--")  # Horizontal bar
    text = text.replace("\u2212", "-")   # Minus sign
    text = text.replace("\u00ad", "")    # Soft hyphen

    # 2. Quotation marks and apostrophes
    text = text.replace("\u2018", "'")   # Left single quote
    text = text.replace("\u2019", "'")   # Right single quote / apostrophe
    text = text.replace("\u201a", "'")
    text = text.replace("\u201b", "'")
    text = text.replace("\u201c", '"')   # Left double quote
    text = text.replace("\u201d", '"')   # Right double quote
    text = text.replace("\u201e", '"')
    text = text.replace("\u201f", '"')
    text = text.replace("\u00ab", '"')   # Left-pointing double angle quote
    text = text.replace("\u00bb", '"')   # Right-pointing double angle quote
    text = text.replace("\u2039", "'")
    text = text.replace("\u203a", "'")

    # 3. Spaces, bullets, and ellipses
    text = text.replace("\u00a0", " ")   # Non-breaking space
    text = text.replace("\u202f", " ")   # Narrow no-break space
    text = text.replace("\u2009", " ")   # Thin space
    text = text.replace("\u200a", " ")   # Hair space
    text = text.replace("\u200b", "")    # Zero-width space
    text = text.replace("\ufeff", "")    # BOM
    text = text.replace("\u2022", "&bull;")  # Bullet
    text = text.replace("\u25cf", "&bull;")  # Black circle
    text = text.replace("\u25cb", "&bull;")  # White circle
    text = text.replace("\u25aa", "&bull;")  # Black small square
    text = text.replace("\u25ab", "&bull;")  # White small square
    text = text.replace("\u2026", "...")     # Ellipsis

    # 4. Box-drawing characters (Convert directory tree characters into clean ASCII tree)
    text = text.replace("├── ", "|-- ")
    text = text.replace("└── ", "\\-- ")
    text = text.replace("│   ", "|   ")
    text = text.replace("│  ", "|  ")
    text = text.replace("│", "|")
    text = text.replace("─", "-")
    text = text.replace("├", "+")
    text = text.replace("└", "\\")
    text = text.replace("┌", "+")
    text = text.replace("┐", "+")
    text = text.replace("┘", "+")
    text = text.replace("┤", "+")
    text = text.replace("┬", "+")
    text = text.replace("┴", "+")
    text = text.replace("┼", "+")
    text = text.replace("━", "-")
    text = text.replace("┃", "|")

    # 5. Symbols and arrows
    text = text.replace("\u2192", "->")
    text = text.replace("\u2190", "<-")
    text = text.replace("\u2194", "<->")
    text = text.replace("\u21d2", "=>")
    text = text.replace("\u2713", "[OK]")
    text = text.replace("\u2714", "[OK]")
    text = text.replace("\u2717", "[X]")
    text = text.replace("\u2718", "[X]")
    text = text.replace("\u26a0", "[!]")
    text = text.replace("\u25a0", "-")   # Existing black square replaced by dash

    # 6. Fallback safety: ensure all characters can be encoded in latin-1/cp1252
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        chars = []
        for ch in text:
            try:
                ch.encode("latin-1")
                chars.append(ch)
            except UnicodeEncodeError:
                chars.append("?")
        text = "".join(chars)

    return text


def _format_code_block_for_pdf(lines: List[str], max_lines: int = 60) -> str:
    """
    Formats raw code lines into ReportLab Paragraph HTML.
    Guarantees:
    - Escapes HTML entities (&, <, >) BEFORE joining with <br/>, preventing literal <br/> text
    - Preserves spaces with &nbsp;
    - Sanitizes box-drawing and Unicode characters into clean ASCII
    """
    formatted_lines = []
    for line in lines[:max_lines]:
        # 1. Sanitize Unicode & box-drawing characters first
        sanitized = _sanitize_pdf_text(line)
        # 2. Escape HTML entities
        escaped = (
            sanitized.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        # 3. Replace spaces with non-breaking spaces for Courier indentation
        spaced = escaped.replace(" ", "&nbsp;")
        formatted_lines.append(spaced)

    # 4. Join with <br/> (these <br/> are NOT escaped, so ReportLab parses them as true line breaks)
    return "<br/>".join(formatted_lines)


# ── NUMBERED CANVAS FOR TWO-PASS RUNNING HEADERS & FOOTERS ────────────────────

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas that accumulates total page count and renders
    running headers and 'Page X of Y' footers on every page except the cover.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.doc_title = "Technical Documentation"

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            if self._pageNumber > 1:
                self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Running header
        clean_title = _sanitize_pdf_text(self.doc_title).upper()
        self.drawString(40, 755, clean_title[:65])
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(40, 748, 572, 748)

        # Running footer
        self.line(40, 48, 572, 48)
        self.drawString(40, 36, "Generated by Repository Documentation Engine | Verified Evidence")
        page_str = f"Page {self._pageNumber} of {total_pages}"
        self.drawRightString(572, 36, page_str)
        self.restoreState()


# ── MARKDOWN TABLE PARSER ─────────────────────────────────────────────────────

def _parse_markdown_table_lines(
    lines: List[str],
    cell_style: ParagraphStyle,
    header_style: ParagraphStyle,
    max_width: float = 530,
) -> Optional[Table]:
    """
    Converts consecutive markdown table lines into a styled ReportLab Table
    with auto-wrapping Paragraph cells and repeated headers across page breaks.
    """
    if len(lines) < 2:
        return None

    parsed_rows: List[List[str]] = []
    for line in lines:
        raw_line = line.strip()
        if not raw_line.startswith("|") or not raw_line.endswith("|"):
            continue
        cells = [c.strip() for c in raw_line.split("|")[1:-1]]
        # Skip separator line (e.g. |---|---|)
        if all(re.match(r'^:?-+:?$', c) for c in cells):
            continue
        parsed_rows.append(cells)

    if len(parsed_rows) < 2:
        return None

    num_cols = max(len(r) for r in parsed_rows)
    if num_cols == 0:
        return None

    col_w = max_width / num_cols
    col_widths = [col_w] * num_cols

    table_flowables = []
    for r_idx, row in enumerate(parsed_rows):
        row_flowables = []
        is_header = (r_idx == 0)
        curr_style = header_style if is_header else cell_style

        cells_padded = row + [""] * (num_cols - len(row))
        for cell_text in cells_padded:
            clean_cell = _sanitize_pdf_text(cell_text)
            clean_cell = clean_cell.replace("<", "&lt;").replace(">", "&gt;")
            clean_cell = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', clean_cell)
            clean_cell = re.sub(r'`(.*?)`', r'<font face="Courier">\1</font>', clean_cell)
            row_flowables.append(Paragraph(clean_cell or "-", curr_style))
        table_flowables.append(row_flowables)

    t = Table(table_flowables, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
    ]))
    return t


# ── CANONICAL DIAGRAM DEFINITIONS ACROSS 16 SECTIONS ───────────────────────────

CANONICAL_DIAGRAM_MAP: Dict[str, List[Tuple[str, str]]] = {
    "projectOverview": [
        ("problem_solution", "Problem & Solution Flow Architecture"),
        ("workflow", "End-to-End Execution Workflow"),
    ],
    "technologyStack": [
        ("tech_stack", "Verified Technology Stack Architecture"),
    ],
    "repositoryStructure": [
        ("repo_structure", "Repository Hierarchy & Module Structure"),
    ],
    "systemArchitecture": [
        ("architecture", "Multi-Tier System Topology & Architecture"),
        ("data_flow", "Component Data Flow & Processing"),
    ],
    "modules": [
        ("modules", "Subsystem & Module Relationships"),
    ],
    "classesAndFunctions": [
        ("classes", "Classes & Function Call Graph"),
    ],
    "apis": [
        ("api_tree", "Hierarchical API Route Map"),
        ("api_arch", "API Routing & Request Lifecycle Pipeline"),
    ],
    "database": [
        ("db_tree", "Database Schema & Entity Blueprint"),
        ("er_diagram", "Entity-Relationship Data Model"),
    ],
    "databaseRelationships": [
        ("db_relationships", "Database Entity Cardinality & Relationships"),
    ],
    "dependencies": [
        ("dep_tree", "Package & Dependency Hierarchy"),
        ("dependencies", "Package & Dependency Ecosystem"),
    ],
    "configuration": [
        ("config_flow", "Runtime Configuration Ingestion Flow"),
    ],
    "testing": [
        ("testing_pipeline", "Automated Test Execution Pipeline"),
    ],
    "security": [
        ("security_arch", "Security Architecture & Access Control Flow"),
    ],
    "cicd": [
        ("cicd_pipeline", "Continuous Integration & Deployment Pipeline"),
    ],
    "deployment": [
        ("deployment_arch", "Container & Infrastructure Deployment Topology"),
    ],
    "setupGuide": [
        ("setup_flowchart", "Developer Onboarding & Local Setup Flowchart"),
    ],
}


def _resolve_section_diagrams(schema_key: str, section_num: int) -> List[Tuple[str, str]]:
    """Resolves diagram specifications by schema key (camelCase / snake_case), alias, or section number."""
    if schema_key in CANONICAL_DIAGRAM_MAP:
        return CANONICAL_DIAGRAM_MAP[schema_key]

    # Map aliases & snake_case
    norm_key = re.sub(r'(?<!^)(?=[A-Z])', '_', schema_key).lower().strip()
    alias_map: Dict[str, str] = {
        "project_overview": "projectOverview",
        "overview": "projectOverview",
        "tech_stack": "technologyStack",
        "technology_stack": "technologyStack",
        "repository_structure": "repositoryStructure",
        "system_architecture": "systemArchitecture",
        "modules_components": "modules",
        "classes_functions": "classesAndFunctions",
        "classes_and_functions": "classesAndFunctions",
        "apis_interfaces": "apis",
        "database_data_model": "database",
        "database_relationships": "databaseRelationships",
        "configuration_environment": "configuration",
        "cicd_pipeline": "cicd",
        "deployment_architecture": "deployment",
        "setup_developer_guide": "setupGuide",
        "setup_guide": "setupGuide",
        "setup": "setupGuide",
    }
    canonical_key = alias_map.get(norm_key, alias_map.get(schema_key))
    if canonical_key and canonical_key in CANONICAL_DIAGRAM_MAP:
        return CANONICAL_DIAGRAM_MAP[canonical_key]

    # Fallback to section number index
    section_keys = list(CANONICAL_DIAGRAM_MAP.keys())
    if 1 <= section_num <= len(section_keys):
        return CANONICAL_DIAGRAM_MAP[section_keys[section_num - 1]]

    return []


# ── MAIN PDF BUILDER ──────────────────────────────────────────────────────────

def generate_pdf_documentation(
    project_name: str,
    sections: list,
    master_md: str,
    output_path: Path,
    metadata: Optional[Dict[str, Any]] = None,
    assets_dir: Optional[Path] = None,
) -> Path:
    """
    Builds a styled, publication-ready PDF document from the master documentation and 16 sections.
    Guarantees:
    - Dynamic cover page strictly matching repository evidence
    - Clean Table of Contents box
    - Rendered diagram images from PNG assets (ZERO raw Mermaid in PDF)
    - Auto-wrapping, responsive data tables
    - Running headers and page numbering
    - Comprehensive Unicode character sanitization (ZERO tofu black squares)
    - Clean code blocks and directory trees (ZERO raw <br/> artifacts)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if assets_dir is None:
        assets_dir = output_path.parent / "assets"

    diagrams_dir = output_path.parent / "diagrams"

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=55,
        bottomMargin=55,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    cover_project_style = ParagraphStyle(
        "CoverProjectName",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=30,
        textColor=colors.HexColor("#0f172a"),
        alignment=1,
        spaceAfter=8,
    )

    cover_title_style = ParagraphStyle(
        "CoverDocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#2563eb"),
        alignment=1,
        spaceAfter=25,
    )

    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#475569"),
    )

    meta_val_style = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#0f172a"),
    )

    h1_style = ParagraphStyle(
        "SectionH1",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True,
    )

    h2_style = ParagraphStyle(
        "SectionH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2563eb"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True,
    )

    h3_style = ParagraphStyle(
        "SectionH3",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True,
    )

    body_style = ParagraphStyle(
        "BodyCustom",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceAfter=7,
    )

    bullet_style = ParagraphStyle(
        "BulletCustom",
        parent=body_style,
        leftIndent=15,
        bulletIndent=5,
        spaceAfter=4,
    )

    code_style = ParagraphStyle(
        "CodeBlock",
        parent=styles["Code"],
        fontName="Courier",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#0f172a"),
        backColor=colors.HexColor("#f8fafc"),
        borderColor=colors.HexColor("#cbd5e1"),
        borderWidth=0.5,
        borderPadding=6,
        spaceBefore=6,
        spaceAfter=8,
    )

    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1e293b"),
    )

    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=12,
        textColor=colors.white,
    )

    story = []

    # ── 1. DYNAMIC COVER PAGE ──────────────────────────────────────────────────
    meta = metadata or {}
    disp_name = meta.get("display_name") or project_name
    repo_name = meta.get("repository_name") or project_name
    branch = meta.get("branch") or "Not available"
    commit_sha = meta.get("commit_sha") or "Not available"
    generated_at = meta.get("generated_at") or "Not available"
    doc_ver = meta.get("doc_version") or "v2.0"
    analysis_ver = meta.get("analysis_version") or "v2.0"

    story.append(Spacer(1, 100))
    story.append(Paragraph(_sanitize_pdf_text(disp_name).upper(), cover_project_style))
    story.append(Paragraph("PROJECT DOCUMENTATION", cover_title_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#2563eb"), spaceAfter=30))

    meta_table_data = [
        [Paragraph("Repository:", meta_label_style), Paragraph(_sanitize_pdf_text(repo_name), meta_val_style)],
        [Paragraph("Branch:", meta_label_style), Paragraph(_sanitize_pdf_text(branch), meta_val_style)],
        [Paragraph("Commit:", meta_label_style), Paragraph(_sanitize_pdf_text(commit_sha[:10] if commit_sha != "Not available" else "Not available"), meta_val_style)],
        [Paragraph("Generated:", meta_label_style), Paragraph(_sanitize_pdf_text(generated_at[:19].replace("T", " ") + " UTC" if "T" in generated_at else generated_at), meta_val_style)],
        [Paragraph("Documentation Version:", meta_label_style), Paragraph(_sanitize_pdf_text(doc_ver), meta_val_style)],
        [Paragraph("Analysis Version:", meta_label_style), Paragraph(_sanitize_pdf_text(analysis_ver), meta_val_style)],
    ]

    meta_table = Table(meta_table_data, colWidths=[150, 360])
    meta_table.setStyle(TableStyle([
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
    ]))

    story.append(meta_table)
    story.append(Spacer(1, 40))
    story.append(Paragraph("<i>Verified Technical Architecture & Specification Suite</i>", ParagraphStyle(
        "CoverTag", parent=styles["Normal"], fontSize=9, alignment=1, textColor=colors.HexColor("#64748b")
    )))
    story.append(PageBreak())

    # ── 2. TABLE OF CONTENTS ───────────────────────────────────────────────────
    story.append(Paragraph("Table of Contents", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0"), spaceAfter=15))

    toc_data = [[Paragraph("#", table_header_style), Paragraph("Section Title", table_header_style), Paragraph("Specification File", table_header_style)]]
    for sec in sections:
        num = getattr(sec, "section_number", "") or (sec.get("section_number") if isinstance(sec, dict) else "")
        title = getattr(sec, "title", "") or (sec.get("title") if isinstance(sec, dict) else "")
        fname = getattr(sec, "filename", "") or (sec.get("filename") if isinstance(sec, dict) else "")
        toc_data.append([
            Paragraph(str(num), table_cell_style),
            Paragraph(f"<b>{_sanitize_pdf_text(title)}</b>", table_cell_style),
            Paragraph(f"<font color='#2563eb'>{_sanitize_pdf_text(fname)}</font>", table_cell_style),
        ])

    toc_table = Table(toc_data, colWidths=[35, 320, 175], repeatRows=1)
    toc_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
    ]))
    story.append(toc_table)
    story.append(PageBreak())

    # ── 3. RENDER CANONICAL ACTIVE SECTIONS ────────────────────────────────────

    for sec_idx, sec in enumerate(sections):
        if sec_idx > 0:
            story.append(PageBreak())

        # Resolve strict canonical section number (1..16)
        num = (
            getattr(sec, "section_number", None)
            or getattr(sec, "canonical_id", None)
            or (sec.get("section_number") if isinstance(sec, dict) else None)
            or (sec.get("canonical_id") if isinstance(sec, dict) else None)
            or (sec_idx + 1)
        )
        title = getattr(sec, "title", f"Section {num}") or (sec.get("title") if isinstance(sec, dict) else f"Section {num}")
        schema_key = getattr(sec, "schema_key", "") or (sec.get("schema_key") if isinstance(sec, dict) else "")
        raw_content = getattr(sec, "content", "") or (sec.get("content") if isinstance(sec, dict) else "")
        content = redact_secrets(raw_content)

        # Section Header
        clean_title = _sanitize_pdf_text(title)
        story.append(Paragraph(f"{num}. {clean_title}", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2563eb"), spaceAfter=10))

        # Check for rendered diagram assets for this section
        diags = _resolve_section_diagrams(schema_key, num)
        fig_cursor = 0
        rendered_diag_ids: Set[str] = set()

        def _embed_diagram_img(diag_identifier: str, d_title: str):
            nonlocal fig_cursor
            search_dirs = []
            if assets_dir and assets_dir.exists():
                search_dirs.append(assets_dir)
            if diagrams_dir.exists() and diagrams_dir not in search_dirs:
                search_dirs.append(diagrams_dir)
            if output_path.parent.exists() and output_path.parent not in search_dirs:
                search_dirs.append(output_path.parent)

            clean_id = (
                diag_identifier.replace("diagram_", "")
                .replace(".png", "")
                .replace(".svg", "")
                .strip()
            )
            candidate_filenames = [
                f"diagram_{clean_id}.png",
                f"{clean_id}.png",
                f"diagram_sec_{clean_id}.png",
                diag_identifier if diag_identifier.endswith(".png") else f"{diag_identifier}.png",
            ]

            img_path: Optional[Path] = None
            for s_dir in search_dirs:
                for fname in candidate_filenames:
                    p = s_dir / fname
                    if p.exists() and p.is_file() and p.stat().st_size > 0:
                        img_path = p
                        break
                if img_path:
                    break

            if img_path:
                try:
                    with PILImage.open(str(img_path)) as pil_img:
                        img_w, img_h = pil_img.size
                    target_w = 480
                    target_h = max(80, min(320, int(target_w * (img_h / max(img_w, 1)))))

                    story.append(Spacer(1, 6))
                    story.append(RLImage(str(img_path), width=target_w, height=target_h))
                    story.append(Spacer(1, 4))
                    fig_caption = f"Figure {num}.{fig_cursor + 1}: {d_title}"
                    story.append(Paragraph(
                        f"<i>{_sanitize_pdf_text(fig_caption)}</i>",
                        ParagraphStyle(
                            "FigCap",
                            parent=styles["Normal"],
                            fontSize=8,
                            alignment=1,
                            textColor=colors.HexColor("#64748b"),
                            spaceAfter=10,
                        )
                    ))
                    fig_cursor += 1
                    rendered_diag_ids.add(clean_id)
                except Exception as img_err:
                    logger.warning("Failed to embed diagram image %s: %s", img_path, img_err)

        # Process Markdown Lines
        lines = content.splitlines()
        idx = 0
        in_code = False
        code_lines: List[str] = []
        is_mermaid_block = False

        while idx < len(lines):
            line = lines[idx].rstrip()

            # Skip standalone figure headers if followed by in-place diagram
            if line.strip().startswith("#### Figure"):
                idx += 1
                continue

            # 1. Code blocks
            if line.startswith("```"):
                if in_code:
                    in_code = False
                    if is_mermaid_block:
                        # Enforce Diagram Placement Rule: embed high-resolution rendered diagram in-place
                        if fig_cursor < len(diags):
                            d_id, d_title = diags[fig_cursor]
                            _embed_diagram_img(d_id, d_title)
                    elif code_lines:
                        # Render genuine code block in Courier font with strict HTML escaping
                        code_html = _format_code_block_for_pdf(code_lines)
                        story.append(Paragraph(code_html, code_style))
                    # Reset
                    code_lines = []
                    is_mermaid_block = False
                    idx += 1
                    continue
                else:
                    in_code = True
                    code_header = line.lower()
                    is_mermaid_block = "mermaid" in code_header
                    code_lines = []
                    idx += 1
                    continue

            if in_code:
                # Accumulate code lines (skip if mermaid)
                if not is_mermaid_block:
                    code_lines.append(line)
                idx += 1
                continue

            # 2. Markdown tables
            if line.strip().startswith("|") and line.strip().endswith("|"):
                table_lines = []
                while idx < len(lines) and lines[idx].strip().startswith("|") and lines[idx].strip().endswith("|"):
                    table_lines.append(lines[idx].strip())
                    idx += 1
                t_flowable = _parse_markdown_table_lines(table_lines, table_cell_style, table_header_style)
                if t_flowable:
                    story.append(Spacer(1, 4))
                    story.append(t_flowable)
                    story.append(Spacer(1, 6))
                continue

            # 3. Blank lines
            if not line.strip():
                story.append(Spacer(1, 3))
                idx += 1
                continue

            # 4. Heading processing & deduplication
            clean_strip = line.strip()
            if clean_strip.startswith("#"):
                h_text = clean_strip.lstrip("#").strip()
                h_title = re.sub(r'^\d+(\.\d+)*\.?\s*', '', h_text).strip()
                # Check if this heading duplicates the section title or section number
                if (
                    h_title.lower() == clean_title.lower()
                    or h_text.lower() == clean_title.lower()
                    or h_text.lower() == f"{num}. {clean_title}".lower()
                    or h_text.lower() == f"{num} {clean_title}".lower()
                    or h_text.lower() == f"{num}.".lower()
                ):
                    idx += 1
                    continue

                # Not a duplicate section title: render proper heading style based on level
                if line.startswith("#### "):
                    h4_text = _sanitize_pdf_text(re.sub(r'[\*\#]', '', line[5:]).strip())
                    story.append(Paragraph(f"<b>{h4_text}</b>", h3_style))
                elif line.startswith("### "):
                    h3_text = _sanitize_pdf_text(re.sub(r'[\*\#]', '', line[4:]).strip())
                    story.append(Paragraph(h3_text, h3_style))
                elif line.startswith("## "):
                    h2_text = _sanitize_pdf_text(re.sub(r'[\*\#]', '', line[3:]).strip())
                    story.append(Paragraph(h2_text, h2_style))
                else:
                    h1_sub = _sanitize_pdf_text(re.sub(r'[\*\#]', '', line.lstrip("#")).strip())
                    story.append(Paragraph(h1_sub, h2_style))
                idx += 1
                continue

            # 6. Bullet lists
            if line.strip().startswith(("- ", "* ", "• ")):
                bullet_text = _sanitize_pdf_text(line.strip()[2:].strip())
                clean_b = bullet_text.replace("<", "&lt;").replace(">", "&gt;")
                clean_b = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', clean_b)
                clean_b = re.sub(r'`(.*?)`', r'<font face="Courier">\1</font>', clean_b)
                story.append(Paragraph(f"&bull; {clean_b}", bullet_style))
                idx += 1
                continue

            # 7. Ordered lists (1. , 2. )
            m_num = re.match(r'^(\d+)\.\s+(.*)$', line.strip())
            if m_num:
                ord_num = m_num.group(1)
                ord_text = _sanitize_pdf_text(m_num.group(2)).replace("<", "&lt;").replace(">", "&gt;")
                ord_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', ord_text)
                ord_text = re.sub(r'`(.*?)`', r'<font face="Courier">\1</font>', ord_text)
                story.append(Paragraph(f"<b>{ord_num}.</b> {ord_text}", bullet_style))
                idx += 1
                continue

            # 8. Regular text paragraph
            clean_text = _sanitize_pdf_text(line).replace("<", "&lt;").replace(">", "&gt;")
            clean_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', clean_text)
            clean_text = re.sub(r'`(.*?)`', r'<font face="Courier">\1</font>', clean_text)
            clean_text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<u>\1</u>', clean_text)
            story.append(Paragraph(clean_text, body_style))
            idx += 1

        # Embed any remaining diagram assets that were not matched inline
        for d_id, d_title in diags:
            clean_id = d_id.replace("diagram_", "").replace(".png", "").replace(".svg", "").strip()
            if clean_id not in rendered_diag_ids:
                _embed_diagram_img(d_id, d_title)

        story.append(Spacer(1, 14))

    # Build canvas with running headers and page numbers
    def _canvas_factory(*args, **kwargs):
        c = NumberedCanvas(*args, **kwargs)
        c.doc_title = disp_name
        return c

    doc.build(story, canvasmaker=_canvas_factory)
    logger.info("Universal PDF generated successfully at %s", output_path)
    return output_path
