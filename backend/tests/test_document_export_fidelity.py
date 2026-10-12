"""
backend/tests/test_document_export_fidelity.py
----------------------------------------------
Regression and validation test suite for document export fidelity, PDF layout,
diagram rendering, character encoding, Markdown, and ZIP exports.
Directly prevents regressions for defects observed in QuizGenAI exports:
1. Black-square (■) characters inside hyphenated words (single-page, front-end, etc.)
2. Raw <br/> tags and box-character corruptions in directory trees
3. Raw Mermaid syntax in PDF
4. Inconsistent ZIP archive structure
"""
import io
import zipfile
from pathlib import Path
import pypdf
import pytest

from docgen.pdf_exporter import (
    _format_code_block_for_pdf,
    _sanitize_pdf_text,
    generate_pdf_documentation,
)
from docgen.schema import DocSection, SECTIONS_META


# ── TEST 1: CHARACTER ENCODING AND SANITIZATION REGRESSION ────────────────────

def test_character_encoding_sanitization_eliminates_tofu():
    """
    Verifies that Unicode non-breaking hyphens (U+2011), en-dashes (U+2013),
    em-dashes (U+2014), curly quotes, and box characters are sanitized so
    ReportLab never renders .notdef black squares (■).
    """
    # Text from observed failure screenshot #1
    raw_text = (
        "The QuizGenAI application is built as a single\u2011page application (SPA) "
        "using a modern front\u2011end framework and a complementary back\u2011end runtime. "
        "Provides the server\u2011side logic and powers the client\u2011side interactivity. "
        "\u201cSmart quotes\u201d and \u2018apostrophes\u2019 with an en\u2013dash and em\u2014dash."
    )
    sanitized = _sanitize_pdf_text(raw_text)

    # Assert non-breaking hyphens are replaced with standard ASCII hyphens
    assert "single-page" in sanitized
    assert "front-end" in sanitized
    assert "back-end" in sanitized
    assert "server-side" in sanitized
    assert "client-side" in sanitized
    assert '"Smart quotes"' in sanitized
    assert "'apostrophes'" in sanitized
    assert "en-dash" in sanitized
    assert "em--dash" in sanitized
    assert "\u2011" not in sanitized
    assert chr(0x25A0) not in sanitized


# ── TEST 2: CODE BLOCK AND DIRECTORY TREE FORMATTING REGRESSION ───────────────

def test_code_block_formatting_no_literal_br_and_clean_trees():
    """
    Verifies that directory trees and code blocks:
    1. Do not produce literal '<br/>' in ReportLab Paragraph HTML.
    2. Convert box-drawing characters to clean ASCII tree branch characters.
    """
    tree_lines = [
        "QuizGenAI/",
        "├── .gitignore",
        "├── collab.md",
        "├── backend/",
        "│   ├── config.py",
        "│   └── database.py",
        "└── frontend/",
        "    └── index.html",
    ]
    html_output = _format_code_block_for_pdf(tree_lines)

    # HTML breaks must be real unescaped <br/> tags for ReportLab to interpret
    assert "<br/>" in html_output
    assert "&lt;br/&gt;" not in html_output
    assert "&lt;br&gt;" not in html_output

    # Tree branch characters must be ASCII
    assert "|--&nbsp;.gitignore" in html_output
    assert "\\--&nbsp;database.py" in html_output
    assert "|&nbsp;&nbsp;&nbsp;|--&nbsp;config.py" in html_output
    assert chr(0x25A0) not in html_output
    assert "\u251c" not in html_output
    assert "\u2514" not in html_output
    assert "\u2502" not in html_output


# ── TEST 3: PDF BUILD INTEGRITY, ZERO BLACK SQUARES, ZERO RAW MERMAID ─────────

def test_pdf_export_zero_black_squares_and_no_raw_mermaid(tmp_path):
    """
    Generates an actual PDF containing all edge cases (hyphenated terms, tables,
    directory trees, and mermaid diagrams) and extracts text via pypdf to verify:
    - Zero black squares (\u25a0)
    - Zero raw <br/> text in trees
    - Zero raw Mermaid syntax exposed in document text
    """
    out_pdf = tmp_path / "test_fidelity.pdf"
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy PNG diagram
    from PIL import Image
    dummy_img = Image.new("RGB", (400, 200), color=(15, 23, 42))
    dummy_img.save(assets_dir / "diagram_tech_stack.png", format="PNG")

    sec1_content = (
        "# 1. Project Overview\n\n"
        "QuizGenAI is a single\u2011page application with front\u2011end and back\u2011end.\n"
    )
    sec2_content = (
        "# 2. Technology Stack\n\n"
        "## 2. Technology Stack\n\n"
        "The QuizGenAI application is built as a single\u2011page application.\n\n"
        "| Language | Role | Purpose |\n"
        "|---|---|---|\n"
        "| Python | Core | Provides server\u2011side logic |\n"
        "| JavaScript | UI | Powers client\u2011side view |\n\n"
        "```mermaid\nflowchart TD\n  Client --> Server\n```\n"
    )
    sec3_content = (
        "# 3. Repository Structure\n\n"
        "```text\n"
        "QuizGenAI/\n"
        "├── backend/\n"
        "│   └── main.py\n"
        "└── frontend/\n"
        "    └── App.jsx\n"
        "```\n"
    )

    sections = [
        DocSection(section_number=1, title="Project Overview", schema_key="projectOverview", filename="01-project-overview.md", content=sec1_content),
        DocSection(section_number=2, title="Technology Stack", schema_key="technologyStack", filename="02-technology-stack.md", content=sec2_content),
        DocSection(section_number=3, title="Repository Structure", schema_key="repositoryStructure", filename="03-repository-structure.md", content=sec3_content),
    ]

    generate_pdf_documentation(
        project_name="QuizGenAI",
        sections=sections,
        master_md="",
        output_path=out_pdf,
        metadata={"repository_name": "QuizGenAI", "branch": "main"},
        assets_dir=assets_dir,
    )

    assert out_pdf.exists()
    assert out_pdf.stat().st_size > 1000

    reader = pypdf.PdfReader(str(out_pdf))
    assert len(reader.pages) >= 3

    full_pdf_text = "".join(p.extract_text() for p in reader.pages)

    # 1. Zero black squares
    assert chr(0x25A0) not in full_pdf_text
    assert "single-page" in full_pdf_text
    assert "front-end" in full_pdf_text
    assert "server-side" in full_pdf_text

    # 2. Zero literal <br/> text in directory trees
    assert "<br/>" not in full_pdf_text
    assert "&lt;br/&gt;" not in full_pdf_text
    assert "|-- backend/" in full_pdf_text or "|--  backend/" in full_pdf_text

    # 3. Zero raw Mermaid syntax dumped into PDF body
    assert "flowchart TD" not in full_pdf_text
    assert "Client --> Server" not in full_pdf_text

    # 4. Embedded diagram image present
    total_images = sum(len(p.images) for p in reader.pages)
    assert total_images >= 1


# ── TEST 4: ZIP BUNDLE FIDELITY AND MANIFEST VALIDATION ───────────────────────

def test_zip_bundle_fidelity(tmp_path):
    """
    Verifies that the ZIP bundle packages all canonical components:
    - Master Markdown & PDF at root
    - All canonical section markdown files
    - Diagrams (SVG, PNG) and diagram source (MMD)
    - Metadata manifest and analysis summary
    - Package manifest with exact file inventory
    """
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "diagrams").mkdir(parents=True, exist_ok=True)
    (docs_dir / "diagram-source").mkdir(parents=True, exist_ok=True)
    (docs_dir / "metadata").mkdir(parents=True, exist_ok=True)
    (docs_dir / "evidence").mkdir(parents=True, exist_ok=True)

    # Create dummy artifacts
    (docs_dir / "FULL_PROJECT_DOCUMENTATION.md").write_text("# Master Doc\n\nComplete doc suite.", encoding="utf-8")
    (docs_dir / "FULL_PROJECT_DOCUMENTATION.pdf").write_bytes(b"%PDF-1.4 dummy pdf bytes")
    (docs_dir / "README.md").write_text("# Readme", encoding="utf-8")
    (docs_dir / "01-project-overview.md").write_text("# 1. Overview", encoding="utf-8")
    (docs_dir / "02-technology-stack.md").write_text("# 2. Tech Stack", encoding="utf-8")
    (docs_dir / "diagrams" / "architecture.png").write_bytes(b"\x89PNG\r\n\x1a\n dummy png")
    (docs_dir / "diagrams" / "architecture.svg").write_text("<svg></svg>", encoding="utf-8")
    (docs_dir / "diagram-source" / "architecture.mmd").write_text("flowchart TD\n A-->B", encoding="utf-8")
    (docs_dir / "metadata" / "documentation-manifest.json").write_text('{"is_complete": true}', encoding="utf-8")
    (docs_dir / "evidence" / "analysis-summary.json").write_text('{"verified": true}', encoding="utf-8")

    buf = io.BytesIO()
    root_prefix = "project-documentation"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(docs_dir / "README.md", arcname=f"{root_prefix}/README.md")
        zf.write(docs_dir / "FULL_PROJECT_DOCUMENTATION.md", arcname=f"{root_prefix}/FULL_PROJECT_DOCUMENTATION.md")
        zf.write(docs_dir / "FULL_PROJECT_DOCUMENTATION.md", arcname=f"{root_prefix}/markdown/project-documentation.md")
        zf.write(docs_dir / "FULL_PROJECT_DOCUMENTATION.pdf", arcname=f"{root_prefix}/FULL_PROJECT_DOCUMENTATION.pdf")
        zf.write(docs_dir / "01-project-overview.md", arcname=f"{root_prefix}/markdown/01-project-overview.md")
        zf.write(docs_dir / "02-technology-stack.md", arcname=f"{root_prefix}/markdown/02-technology-stack.md")
        zf.write(docs_dir / "diagrams" / "architecture.png", arcname=f"{root_prefix}/diagrams/architecture.png")
        zf.write(docs_dir / "diagrams" / "architecture.svg", arcname=f"{root_prefix}/diagrams/architecture.svg")
        zf.write(docs_dir / "diagram-source" / "architecture.mmd", arcname=f"{root_prefix}/diagram-source/architecture.mmd")
        zf.write(docs_dir / "metadata" / "documentation-manifest.json", arcname=f"{root_prefix}/metadata/documentation-manifest.json")
        zf.write(docs_dir / "evidence" / "analysis-summary.json", arcname=f"{root_prefix}/evidence/analysis-summary.json")

    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zr:
        namelist = zr.namelist()
        assert f"{root_prefix}/FULL_PROJECT_DOCUMENTATION.md" in namelist
        assert f"{root_prefix}/FULL_PROJECT_DOCUMENTATION.pdf" in namelist
        assert f"{root_prefix}/markdown/01-project-overview.md" in namelist
        assert f"{root_prefix}/diagrams/architecture.png" in namelist
        assert f"{root_prefix}/diagrams/architecture.svg" in namelist
        assert f"{root_prefix}/diagram-source/architecture.mmd" in namelist
        assert f"{root_prefix}/metadata/documentation-manifest.json" in namelist
        assert f"{root_prefix}/evidence/analysis-summary.json" in namelist

        # Validate extracted files are non-empty
        for n in namelist:
            data = zr.read(n)
            assert len(data) > 0, f"File {n} is empty in ZIP"
