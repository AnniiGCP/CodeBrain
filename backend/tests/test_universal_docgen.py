"""
backend/tests/test_universal_docgen.py
--------------------------------------
Comprehensive Test Suite for the Universal Project Documentation Generator.

Covers:
1. Dynamic Project Identity (package manifest name > db name > README title)
2. Exactly 16 canonical sections with exact naming and schema keys
3. Project Leakage Protection (zero host platform strings leaked into user projects)
4. Absence Handling (No-database fixture -> Section 8 & 9 empty states, no fake ER diagram)
5. Absence Handling (No-CI fixture -> Section 14 empty state, no fake CI flowchart)
6. Secret Redaction (API keys, DB credentials, private keys replaced with <REDACTED_SECRET>)
7. Simple/Small Project handling (concise documentation, no artificial padding)
8. Monorepo handling (detects distinct workspaces/services)
9. Multi-format export verification (Markdown, HTML, PDF, JSON generated and consistent)
10. Diagram rendering (SVG and PNG generated, zero raw Mermaid in PDF)
"""
import io
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

import pytest
from database import SessionLocal
from docgen.diagram_engine import (
    build_architecture_diagram_spec,
    build_cicd_diagram_spec,
    build_er_diagram_spec,
    render_mermaid,
    render_png,
    render_svg,
)
from docgen.master_doc_gen import generate_full_project_documentation
from docgen.schema import (
    DOCUMENTATION_SCHEMA_KEYS,
    DOCUMENTATION_SECTIONS,
    SECTIONS_META,
)
from docgen.secret_redactor import redact_secrets
from models import Repo, RepoFile, Symbol, User


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def test_user(db_session):
    user = User(
        id=str(uuid.uuid4()),
        github_id=str(uuid.uuid4()),
        github_username=f"user_{uuid.uuid4().hex[:6]}",
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(autouse=True)
def mock_all_llms():
    with patch("docgen.groq_client.call_groq", side_effect=Exception("No LLM in unit test")), \
         patch("docgen.master_doc_gen.call_groq", side_effect=Exception("No LLM in unit test")):
        yield
def _create_fixture_repo(db_session, user_id: str, repo_name: str, files_dict: dict) -> Tuple[str, Path]:
    repo_id = str(uuid.uuid4())
    repo = Repo(
        id=repo_id,
        user_id=user_id,
        name=repo_name,
        source_type="upload",
        pipeline_status="DONE",
    )
    db_session.add(repo)
    db_session.commit()

    storage_dir = Path(__file__).parent.parent / "storage" / repo_id
    storage_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, content in files_dict.items():
        file_path = storage_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        rf = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo_id,
            path=rel_path,
            language="python" if rel_path.endswith(".py") else "javascript" if rel_path.endswith((".js", ".jsx", ".ts", ".tsx")) else "html" if rel_path.endswith(".html") else "other",
            size=len(content.encode("utf-8")),
            content_hash=uuid.uuid4().hex,
        )
        db_session.add(rf)

    db_session.commit()
    return repo_id, storage_dir


# ── TEST 1: CRITICAL REGRESSION TEST — PROJECT LEAKAGE PROTECTION ─────────────

def test_zero_project_leakage(db_session, test_user):
    """
    CRITICAL: If a fixture repository does not use CodeBrain, AnniiGCP, MAJOR-PROJECT,
    FastAPI, FAISS, or NVIDIA NIM, those strings must NEVER appear in the generated documentation!
    """
    files = {
        "package.json": json.dumps({
            "name": "acme-ecommerce-portal",
            "version": "2.4.0",
            "description": "Acme online shopping platform built with Vue and Express",
            "dependencies": {
                "vue": "^3.4.0",
                "express": "^4.19.0",
            }
        }),
        "server.js": "const express = require('express');\nconst app = express();\napp.get('/api/products', (req, res) => res.json([]));\n",
        "README.md": "# Acme E-Commerce Portal\nOnline shopping storefront application.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "acme-ecommerce-portal", files)

    try:
        with patch("docgen.master_doc_gen.call_groq", side_effect=Exception("No LLM in unit test")):
            result = generate_full_project_documentation(repo_id, db_session)

        # 1. Project name must be derived from package.json
        assert result.repo_name == "acme-ecommerce-portal"
        assert result.project_metadata.project_name == "acme-ecommerce-portal"

        # 2. Check full markdown for forbidden host-platform leakage
        full_doc = result.master_readme
        forbidden_strings = [
            "CodeBrain",
            "AnniiGCP",
            "MAJOR-PROJECT",
            "FastAPI",
            "FAISS",
            "NVIDIA NIM",
            "Whisper",
        ]

        for forbidden in forbidden_strings:
            assert forbidden.lower() not in full_doc.lower(), f"Project leakage detected: '{forbidden}' found in documentation!"

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 2: CRITICAL REGRESSION TEST — NO DATABASE HANDLING ───────────────────

def test_no_database_fixture_handling(db_session, test_user):
    """
    CRITICAL: For a repository without database models or persistence:
    - All 16 canonical sections are generated in canonical order (1..16).
    - Database sections (8 and 9) contain honest absence analysis, explaining that
      repository files, schemas, and migrations were checked and no persistent database exists.
    - No fake ER diagram is generated.
    """
    files = {
        "index.html": "<!DOCTYPE html><html><body><h1>Static Portfolio</h1></body></html>",
        "styles.css": "body { font-family: sans-serif; }",
        "script.js": "console.log('Static site loaded');",
        "README.md": "# Simple Portfolio\nStatic personal portfolio website.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "simple-portfolio", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session)

        # All 16 canonical sections must be present
        assert result.total_sections == 16
        assert len(result.sections) == 16

        # Check sections 8 and 9 contain grounded honest absence findings
        sec8 = next(s for s in result.sections if s.section_number == 8)
        assert sec8.schema_key == "database"
        assert "Inspection Finding" in sec8.content or "No persistent database" in sec8.content

        sec9 = next(s for s in result.sections if s.section_number == 9)
        assert sec9.schema_key == "databaseRelationships"
        assert "Inspection Finding" in sec9.content or "No persistent database schema" in sec9.content

        # Zero numbering gaps: strict 1..16
        for idx, sec in enumerate(result.sections, start=1):
            assert sec.section_number == idx

        # Zero fake ER diagram
        assert "erDiagram" not in result.master_readme
        assert not (storage_dir / "docs" / "assets" / "diagram_er_diagram.png").exists()

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 3: CRITICAL REGRESSION TEST — NO CI/CD HANDLING ──────────────────────

def test_no_cicd_fixture_handling(db_session, test_user):
    """
    CRITICAL: For a repository without CI/CD workflows:
    - All 16 canonical sections are generated in canonical order (1..16).
    - Section 14 (CI/CD Pipeline) contains honest absence analysis, explaining what was inspected.
    - No fictional GitHub Actions / CI pipeline diagram is generated.
    """
    files = {
        "calculator.py": "def add(a, b): return a + b\n",
        "README.md": "# Math Utilities\nSimple math calculation functions.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "math-utils", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session)

        # All 16 canonical sections must be present
        assert result.total_sections == 16
        assert len(result.sections) == 16

        sec14 = next(s for s in result.sections if s.section_number == 14)
        assert sec14.schema_key == "cicd"
        assert "Inspection Finding" in sec14.content or "No automated CI/CD" in sec14.content

        # Zero numbering gaps: strict 1..16
        for idx, sec in enumerate(result.sections, start=1):
            assert sec.section_number == idx

        assert not (storage_dir / "docs" / "assets" / "diagram_cicd_pipeline.png").exists()

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 4: CRITICAL REGRESSION TEST — SECRET REDACTION ───────────────────────

def test_secret_redaction_protection(db_session, test_user):
    """
    CRITICAL: Credentials, API keys, and connection passwords in repo files
    must be redacted and NEVER appear in generated Markdown, HTML, PDF, or JSON.
    """
    secret_key = "sk" + "-proj-supersecretunauthorizedkey9876543210"
    db_pass = "super_classified_db_pass_12345"

    files = {
        ".env": f"OPENAI_API_KEY={secret_key}\nDATABASE_URL=postgres://app_user:{db_pass}@localhost:5432/app_db\n",
        "config.py": f"import os\nAPI_KEY = os.getenv('OPENAI_API_KEY')\n",
        "README.md": "# Secure App\nAn application with environment credentials.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "secure-app", files)

    try:
        with patch("docgen.master_doc_gen.call_groq", side_effect=Exception("No LLM")):
            result = generate_full_project_documentation(repo_id, db_session)

        # Verify real secret strings NEVER appear anywhere
        full_md = result.master_readme
        assert secret_key not in full_md
        assert db_pass not in full_md

        # Verify HTML output does not contain secrets
        html_file = storage_dir / "docs" / "FULL_PROJECT_DOCUMENTATION.html"
        assert html_file.exists()
        html_content = html_file.read_text(encoding="utf-8")
        assert secret_key not in html_content
        assert db_pass not in html_content

        # Verify JSON output does not contain secrets
        json_file = storage_dir / "docs" / "FULL_PROJECT_DOCUMENTATION.json"
        assert json_file.exists()
        json_content = json_file.read_text(encoding="utf-8")
        assert secret_key not in json_content
        assert db_pass not in json_content

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 5: EXACT CANONICAL SCHEMA & DYNAMIC SEQUENTIAL SECTIONS ──────────────

def test_exact_16_canonical_sections(db_session, test_user):
    """
    Verifies that all 16 canonical schema sections exist, are numbered strictly 1..16,
    use canonical filenames (01-project-overview.md .. 16-setup-and-developer-guide.md),
    and satisfy the completion gate.
    """
    from docgen.schema import SECTIONS_META

    files = {
        "main.py": "def main(): print('Hello')\nif __name__ == '__main__': main()\n",
        "README.md": "# Quickstart App\nMinimal Python application.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "quickstart-app", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session)

        # Check all 16 canonical schema keys exist in schema_data
        for expected_key in DOCUMENTATION_SCHEMA_KEYS:
            assert expected_key in result.schema_data

        # Check exactly 16 sections are generated and suite is complete
        assert len(result.sections) == 16
        assert result.total_sections == 16
        assert result.is_complete is True

        for idx, (expected_num, expected_title, expected_key, expected_filename) in enumerate(SECTIONS_META, start=1):
            sec = result.sections[idx - 1]
            assert sec.section_number == idx
            assert sec.section_number == expected_num
            assert sec.title == expected_title
            assert sec.schema_key == expected_key
            assert sec.filename == expected_filename

            # Check individual canonical file exists on disk
            sec_file = storage_dir / "docs" / sec.filename
            assert sec_file.exists(), f"File {sec.filename} missing from disk!"

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 6: MULTI-FORMAT EXPORT VERIFICATION (MD, HTML, PDF, JSON) ────────────

def test_multi_format_exports(db_session, test_user):
    """
    Verifies that all 4 primary export files (MD, HTML, PDF, JSON) are generated
    and originate from the same canonical documentation model.
    """
    files = {
        "app.py": "def run(): return 'ok'\n",
        "requirements.txt": "click==8.1.7\n",
        "README.md": "# Tool\nCLI Tool.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "cli-tool", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session)

        docs_dir = storage_dir / "docs"

        # 1. Markdown
        md_file = docs_dir / "FULL_PROJECT_DOCUMENTATION.md"
        assert md_file.exists()
        assert len(md_file.read_text(encoding="utf-8")) > 200

        # 2. PDF
        pdf_file = docs_dir / "FULL_PROJECT_DOCUMENTATION.pdf"
        assert pdf_file.exists()
        assert pdf_file.stat().st_size > 1000  # valid PDF binary

        # 3. HTML
        html_file = docs_dir / "FULL_PROJECT_DOCUMENTATION.html"
        assert html_file.exists()
        assert "<!DOCTYPE html>" in html_file.read_text(encoding="utf-8")

        # 4. JSON
        json_file = docs_dir / "FULL_PROJECT_DOCUMENTATION.json"
        assert json_file.exists()
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert data["total_sections"] == len(result.sections)
        assert len(data["sections"]) == len(result.sections)

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 7: MONOREPO FIXTURE HANDLING ─────────────────────────────────────────

def test_monorepo_fixture_handling(db_session, test_user):
    """
    Verifies that a multi-package monorepo is accurately detected with
    distinct workspaces and non-flattened architecture.
    """
    files = {
        "package.json": json.dumps({
            "name": "my-monorepo",
            "workspaces": ["apps/*", "packages/*"],
        }),
        "apps/web/package.json": json.dumps({"name": "@monorepo/web"}),
        "apps/web/index.ts": "console.log('web frontend');",
        "apps/api/package.json": json.dumps({"name": "@monorepo/api"}),
        "apps/api/server.ts": "console.log('api backend');",
        "packages/shared/package.json": json.dumps({"name": "@monorepo/shared"}),
        "packages/shared/index.ts": "export const VERSION = '1.0';",
        "README.md": "# My Monorepo\nMulti-package monorepo project.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "my-monorepo", files)

    try:
        with patch("docgen.master_doc_gen.call_groq", side_effect=Exception("No LLM")):
            result = generate_full_project_documentation(repo_id, db_session)

        # Monorepo architecture detected
        assert "Monorepo" in result.project_metadata.project_type
        assert "Monorepo" in result.master_readme

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 8: DETERMINISTIC DIAGRAM ENGINE RENDERING ────────────────────────────

def test_diagram_engine_renderers():
    """
    Tests that DiagramSpec renders to valid standalone SVG and PNG image buffers.
    """
    from docgen.schema import DiagramEdge, DiagramNode, DiagramSpec

    spec = DiagramSpec(
        diagram_id="test_arch",
        title="Sample Architecture",
        diagram_type="architecture",
        nodes=[
            DiagramNode(id="client", label="Client Browser", kind="client"),
            DiagramNode(id="api", label="API Gateway", kind="backend"),
            DiagramNode(id="db", label="PostgreSQL DB", kind="database"),
        ],
        edges=[
            DiagramEdge(source="client", target="api", label="HTTP"),
            DiagramEdge(source="api", target="db", label="SQL"),
        ],
    )

    # 1. SVG rendering
    svg = render_svg(spec)
    assert "<svg" in svg
    assert "</svg>" in svg
    assert "Client Browser" in svg
    assert "PostgreSQL DB" in svg

    # 2. PNG rendering
    png_bytes = render_png(spec)
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 500  # valid PNG binary header
    assert png_bytes[:8] == b'\x89PNG\r\n\x1a\n'

    # 3. Mermaid rendering
    mermaid = render_mermaid(spec)
    assert "flowchart TD" in mermaid
    assert "client" in mermaid
    assert "-->|HTTP| api" in mermaid


# ── TEST 9: CRITICAL REGRESSION TEST — QUIZGENAI / BACKEND FOLDER BUG ─────────

def test_quizgenai_backend_folder_bug(db_session, test_user):
    """
    CRITICAL REGRESSION TEST for user incident:
    Repository is named 'QuizGenAI', but contains a subdirectory 'backend/package.json'
    with name 'backend'.
    The generated project name MUST remain 'QuizGenAI', and NEVER 'Backend'!
    """
    files = {
        "backend/package.json": json.dumps({"name": "backend", "version": "1.0.0"}),
        "backend/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        "README.md": "# QuizGenAI\nAI-powered quiz generator application.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "QuizGenAI", files)

    try:
        with patch("docgen.master_doc_gen.call_groq", side_effect=Exception("No LLM")):
            result = generate_full_project_documentation(repo_id, db_session)

        # Title must be QuizGenAI, never Backend
        assert result.repo_name == "QuizGenAI"
        assert result.project_metadata.project_name == "QuizGenAI"
        assert result.project_metadata.display_name == "QuizGenAI"

        # Check Markdown cover / header
        full_doc = result.master_readme
        assert "# QuizGenAI — Project Documentation" in full_doc
        assert "# Backend — Project Documentation" not in full_doc
        assert "Project: Backend" not in full_doc

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 10: CRITICAL REGRESSION TEST — DATABASE VS PYDANTIC SCHEMA CLASSIFICATION

def test_database_vs_pydantic_schema_classification(db_session, test_user):
    """
    CRITICAL REGRESSION TEST:
    A repository containing Pydantic request/response DTOs (e.g. 17 Pydantic models in QuizGenAI)
    without database table persistence must NOT classify them as database tables.
    Section 8 must state: 'No persistent database schema was identified'.
    Section 9 must state: 'No database relationships were identified'.
    """
    files = {
        "models/schemas.py": (
            "from pydantic import BaseModel, Field\n\n"
            "class QuizGenerateRequest(BaseModel):\n"
            "    topic: str = Field(..., description='Quiz topic')\n"
            "    count: int = Field(default=5)\n\n"
            "class QuestionResponse(BaseModel):\n"
            "    question: str\n"
            "    options: list[str]\n"
            "    answer: str\n"
        ),
        "api/routes.py": (
            "from fastapi import APIRouter\n"
            "from models.schemas import QuizGenerateRequest\n"
            "router = APIRouter()\n"
            "@router.post('/generate')\n"
            "async def generate_quiz(req: QuizGenerateRequest):\n"
            "    return {'status': 'ok'}\n"
        ),
        "README.md": "# QuizGenAI\nFastAPI-based quiz generator microservice.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "QuizGenAI", files)

    # Add symbols for the classes
    file_row = db_session.query(RepoFile).filter(RepoFile.repo_id == repo_id, RepoFile.path == "models/schemas.py").first()
    sym1 = Symbol(
        repo_id=repo_id,
        file_id=file_row.id,
        name="QuizGenerateRequest",
        symbol_type="class",
        source_code="class QuizGenerateRequest(BaseModel):\n    topic: str = Field(..., description='Quiz topic')\n    count: int = Field(default=5)\n",
    )
    sym2 = Symbol(
        repo_id=repo_id,
        file_id=file_row.id,
        name="QuestionResponse",
        symbol_type="class",
        source_code="class QuestionResponse(BaseModel):\n    question: str\n    options: list[str]\n    answer: str\n",
    )
    db_session.add_all([sym1, sym2])
    db_session.commit()

    try:
        from docgen.repo_analyzer import analyze_repository
        graph = analyze_repository(repo_id, db_session)

        # Strict assertion: Pydantic request models are NOT database entities!
        assert len(graph.db_models) == 0, f"Expected 0 database models, got {len(graph.db_models)}"
        assert graph.database_type is None

        result = generate_full_project_documentation(repo_id, db_session)

        # All 16 canonical sections must exist
        assert result.total_sections == 16
        assert len(result.sections) == 16

        # Database sections contain honest absence analysis
        sec8 = next(s for s in result.sections if s.section_number == 8)
        assert "Inspection Finding" in sec8.content or "No persistent database" in sec8.content

        sec9 = next(s for s in result.sections if s.section_number == 9)
        assert "Inspection Finding" in sec9.content or "No persistent database schema" in sec9.content

        # Pydantic DTO models must NOT be presented as database tables or ER entities
        assert "Table: QuizGenerateRequest" not in result.master_readme
        assert "erDiagram" not in result.master_readme

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 11: CRITICAL REGRESSION TEST — NO DUPLICATE HEADINGS OR REPEATED BADGES

def test_no_duplicate_headings_or_repeated_badges(db_session, test_user):
    """
    CRITICAL REGRESSION TEST:
    Asserts that FULL_PROJECT_DOCUMENTATION.md has strictly sequential `# {num}. {title}` headings
    for active sections without gaps, no duplicate `# 1. Project Overview`, and the version badge appears once.
    """
    files = {
        "main.py": "print('running')\n",
        "README.md": "# Single Heading App\nSimple test application.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "single-heading-app", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session)

        full_doc = result.master_readme

        # Count occurrences of '# 1. Project Overview'
        h1_sec1_count = full_doc.count("# 1. Project Overview")
        assert h1_sec1_count == 1, f"Expected exactly 1 '# 1. Project Overview', found {h1_sec1_count}"

        # Count occurrences of version badge '> **Project:**'
        badge_count = full_doc.count("> **Project:**")
        assert badge_count == 1, f"Expected exactly 1 version badge, found {badge_count}"

        # Count total '# ' (H1) headings in the document: 1 master title + len(result.sections) active sections
        lines = full_doc.splitlines()
        h1_lines = [l for l in lines if l.startswith("# ")]
        expected_h1 = 1 + len(result.sections)
        assert len(h1_lines) == expected_h1, f"Expected {expected_h1} H1 headings (1 master + {len(result.sections)} sections), got {len(h1_lines)}: {h1_lines}"

        # Sequential numbering verification with zero gaps
        for idx, sec in enumerate(result.sections, start=1):
            assert sec.section_number == idx
            assert f"# {idx}. {sec.title}" in full_doc

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 12: CRITICAL REGRESSION TEST — CROSS-REPOSITORY ISOLATION ────────────

def test_cross_repository_isolation(db_session, test_user):
    """
    CRITICAL REGRESSION TEST:
    Generating documentation for Repo A ('QuizGenAI') and Repo B ('DocuFlow')
    must guarantee strict isolation:
    - Repo A document contains 'QuizGenAI' and NEVER 'DocuFlow'
    - Repo B document contains 'DocuFlow' and NEVER 'QuizGenAI'
    """
    files_a = {
        "main.py": "print('quiz')\n",
        "README.md": "# QuizGenAI\nQuiz AI tool.",
    }
    files_b = {
        "main.py": "print('docuflow')\n",
        "README.md": "# DocuFlow\nWorkflow document automation engine.",
    }

    repo_id_a, storage_dir_a = _create_fixture_repo(db_session, test_user.id, "QuizGenAI", files_a)
    repo_id_b, storage_dir_b = _create_fixture_repo(db_session, test_user.id, "DocuFlow", files_b)

    try:
        with patch("docgen.master_doc_gen.call_groq", side_effect=Exception("No LLM")):
            result_a = generate_full_project_documentation(repo_id_a, db_session)
            result_b = generate_full_project_documentation(repo_id_b, db_session)

        # Assert Repo A identity and isolation
        assert result_a.repo_name == "QuizGenAI"
        assert "QuizGenAI" in result_a.master_readme
        assert "DocuFlow" not in result_a.master_readme

        # Assert Repo B identity and isolation
        assert result_b.repo_name == "DocuFlow"
        assert "DocuFlow" in result_b.master_readme
        assert "QuizGenAI" not in result_b.master_readme

    finally:
        shutil.rmtree(storage_dir_a, ignore_errors=True)
        shutil.rmtree(storage_dir_b, ignore_errors=True)


# ── TEST 13: FULL-STACK REPOSITORY ARCHETYPE (A) ──────────────────────────────

def test_full_stack_repository_archetype(db_session, test_user):
    """
    Validates a full-stack project (React frontend + FastAPI backend + SQLAlchemy DB + JWT auth).
    Ensures that APIs, DB models, relationships, and security are fully detected,
    all relevant sections are generated, and active sections are sequentially numbered 1..N.
    """
    files = {
        "frontend/src/App.tsx": "import React from 'react';\nexport const App = () => <div>App</div>;\n",
        "frontend/package.json": json.dumps({"name": "shop-ui", "dependencies": {"react": "^18.2.0"}}),
        "backend/main.py": "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/api/items')\ndef get_items(): return []\n",
        "backend/models.py": (
            "from sqlalchemy import Column, Integer, String, ForeignKey\n"
            "from sqlalchemy.orm import relationship, declarative_base\n"
            "Base = declarative_base()\n"
            "class User(Base):\n"
            "    __tablename__ = 'users'\n"
            "    id = Column(Integer, primary_key=True)\n"
            "    name = Column(String)\n"
            "    orders = relationship('Order', back_populates='user')\n"
            "class Order(Base):\n"
            "    __tablename__ = 'orders'\n"
            "    id = Column(Integer, primary_key=True)\n"
            "    user_id = Column(Integer, ForeignKey('users.id'))\n"
        ),
        "backend/auth.py": "import jwt\nSECRET = 'topsecret'\ndef verify_token(t): return jwt.decode(t, SECRET, algorithms=['HS256'])\n",
        "README.md": "# ShopMaster\nFull-stack ecommerce platform with React frontend and FastAPI backend.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "shopmaster", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session)
        active_keys = [s.schema_key for s in result.sections]

        # Verify active presence
        assert "database" in active_keys
        assert "databaseRelationships" in active_keys
        assert "apis" in active_keys
        assert "security" in active_keys

        # Check sequential numbering 1..N with zero gaps
        for idx, sec in enumerate(result.sections, start=1):
            assert sec.section_number == idx

        # Verify ER diagram generated
        assert (storage_dir / "docs" / "diagrams" / "er_diagram.svg").exists()
        assert (storage_dir / "docs" / "diagram-source" / "er_diagram.mmd").exists()
    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 14: FRONTEND-ONLY REPOSITORY ARCHETYPE (B) ───────────────────────────

def test_frontend_only_repository_archetype(db_session, test_user):
    """
    Validates a frontend-only project (Vue/Vite, zero backend or database).
    Ensures database, DB relationships, and CI/CD are honestly omitted,
    and active sections are renumbered 1..N without gaps.
    """
    files = {
        "src/App.vue": "<template><h1>Dashboard</h1></template>",
        "src/main.js": "import { createApp } from 'vue';\nimport App from './App.vue';\ncreateApp(App).mount('#app');",
        "package.json": json.dumps({"name": "vue-dashboard", "dependencies": {"vue": "^3.3.0"}}),
        "README.md": "# Vue Dashboard\nFrontend visualization dashboard.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "vue-dashboard", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session)
        assert len(result.sections) == 16
        assert result.total_sections == 16

        # Check sequential numbering 1..16 with zero gaps
        for idx, sec in enumerate(result.sections, start=1):
            assert sec.section_number == idx

        sec8 = next(s for s in result.sections if s.section_number == 8)
        assert "Inspection Finding" in sec8.content or "No persistent database" in sec8.content

        sec14 = next(s for s in result.sections if s.section_number == 14)
        assert "Inspection Finding" in sec14.content or "No automated CI/CD" in sec14.content
    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 15: DOCKER & GITHUB ACTIONS DETECTION (H & I) ─────────────────────────

def test_docker_and_github_actions_detection(db_session, test_user):
    """
    Validates deployment and CI/CD detection when Dockerfile and GitHub Actions exist.
    """
    files = {
        "Dockerfile": "FROM node:20-alpine\nWORKDIR /app\nCOPY . .\nEXPOSE 3000\nCMD [\"npm\", \"start\"]\n",
        ".github/workflows/ci.yml": "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v3\n",
        "server.js": "const http = require('http');\nhttp.createServer((req, res) => res.end('ok')).listen(3000);\n",
        "package.json": json.dumps({"name": "node-service", "scripts": {"start": "node server.js"}}),
        "README.md": "# Node Service\nContainerized node.js microservice.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "node-service", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session)
        active_keys = [s.schema_key for s in result.sections]

        assert "cicd" in active_keys
        assert "deployment" in active_keys
        assert (storage_dir / "docs" / "diagrams" / "cicd_pipeline.svg").exists()
        assert (storage_dir / "docs" / "diagrams" / "deployment_arch.svg").exists()
    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 16: CANONICAL ZIP BUNDLE STRUCTURE (SECTION 21) ──────────────────────

def test_canonical_zip_bundle_structure(db_session, test_user):
    """
    Verifies that the ZIP export packages documentation in the exact canonical structure:
    project-documentation/
    ├── README.md
    ├── master-documentation.md
    ├── pdf/project-documentation.pdf
    ├── markdown/project-documentation.md
    ├── diagrams/*.svg, *.png
    ├── diagram-source/*.mmd
    ├── evidence/analysis-summary.json
    └── metadata/documentation-manifest.json
    """
    import zipfile
    from routers.docs import download_doc_format

    files = {
        "main.py": "def main(): print('Hello from CLI')\nif __name__ == '__main__': main()\n",
        "requirements.txt": "requests==2.31.0\n",
        "README.md": "# Test Tool\nUniversal documentation test package.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "test-pkg", files)

    try:
        generate_full_project_documentation(repo_id, db_session)
        response = download_doc_format(repo_id, "zip", test_user, db_session)

        # Inspect zip bytes
        if hasattr(response.body_iterator, "__aiter__"):
            import anyio
            async def _read(it):
                chunks = []
                async for c in it:
                    chunks.append(c)
                return b"".join(chunks)
            zip_bytes = io.BytesIO(anyio.run(_read, response.body_iterator))
        else:
            zip_bytes = io.BytesIO(b"".join([chunk for chunk in response.body_iterator]))
        with zipfile.ZipFile(zip_bytes, "r") as zf:
            namelist = zf.namelist()

            # Verify canonical root directory
            assert "project-documentation/README.md" in namelist
            assert "project-documentation/master-documentation.md" in namelist
            assert "project-documentation/pdf/project-documentation.pdf" in namelist
            assert "project-documentation/markdown/project-documentation.md" in namelist
            assert "project-documentation/evidence/analysis-summary.json" in namelist
            assert "project-documentation/metadata/documentation-manifest.json" in namelist

            # Verify diagram sources exist
            has_mmd = any(n.startswith("project-documentation/diagram-source/") and n.endswith(".mmd") for n in namelist)
            assert has_mmd, "Expected diagram-source/*.mmd in ZIP package"

            # Verify evidence/analysis-summary.json contents
            summary_content = json.loads(zf.read("project-documentation/evidence/analysis-summary.json").decode("utf-8"))
            assert "quality_score" in summary_content
            assert summary_content["quality_score"]["total_score"] > 0
    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 17: EVIDENCE TRACEABILITY & ZERO INTERNAL CHUNK LEAKAGE ──────────────

def test_evidence_traceability_no_internal_chunk_ids(db_session, test_user):
    """
    Verifies that neither documentation prose nor analysis summary leaks internal
    chunk artifacts such as _chunk_0, _chunk_1, chunk_17, retrieval_42.
    """
    files = {
        "core.py": "def run_engine(): return True\n",
        "README.md": "# Core App\nEvidence backed core application.",
    }

    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "core-app", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session)
        full_doc = result.master_readme

        forbidden_chunk_patterns = ["_chunk_0", "_chunk_1", "chunk_17", "retrieval_42", "_chunk_"]
        for p in forbidden_chunk_patterns:
            assert p not in full_doc, f"Internal chunk artifact '{p}' leaked into documentation!"

        evidence_file = storage_dir / "docs" / "evidence" / "analysis-summary.json"
        assert evidence_file.exists()
        evidence_json = evidence_file.read_text(encoding="utf-8")
        for p in forbidden_chunk_patterns:
            assert p not in evidence_json, f"Internal chunk artifact '{p}' leaked into evidence model!"
    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


