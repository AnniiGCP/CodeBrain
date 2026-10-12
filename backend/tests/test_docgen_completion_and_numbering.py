"""
backend/tests/test_docgen_completion_and_numbering.py
-----------------------------------------------------
Targeted test suite verifying:
1. Immutable 16-section contract & canonical numbering (1..16).
2. Elimination of corrupted filenames (10-0, 11-1, 12-1).
3. Server-authoritative completion gate (no partial suite reported as complete).
4. Section validation requirements (preventing empty/truncated/placeholder content).
5. Resumable generation preserving already-validated sections.
6. Honest absence handling without fabrication.
7. Master document assembly order & export consistency.
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

import pytest
from database import SessionLocal
from docgen.master_doc_gen import generate_full_project_documentation
from docgen.schema import (
    CANONICAL_SECTIONS_COUNT,
    CANONICAL_SECTION_BY_ID,
    DOCUMENTATION_SECTIONS,
    DocSection,
    LEGACY_FILENAMES_BY_ID,
    SECTIONS_META,
    get_canonical_section,
    resolve_canonical_filename,
)
from docgen.validator import (
    assert_suite_complete,
    validate_mermaid_syntax,
    validate_section_content,
    validate_suite_integrity,
)
from models import Repo, RepoFile, User


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


def _create_fixture_repo(db_session, user_id: str, repo_name: str, files_dict: dict):
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
            language="python" if rel_path.endswith(".py") else "javascript",
            size=len(content.encode("utf-8")),
            content_hash=uuid.uuid4().hex,
        )
        db_session.add(rf)

    db_session.commit()
    return repo_id, storage_dir


# ── TEST 1: IMMUTABLE 16-SECTION CONTRACT MANIFEST ────────────────────────────

def test_immutable_16_section_contract_manifest():
    """Validates that exactly 16 canonical sections exist, mapped 1..16 sequentially."""
    assert len(SECTIONS_META) == 16
    assert len(DOCUMENTATION_SECTIONS) == 16
    assert CANONICAL_SECTIONS_COUNT == 16

    expected_titles = [
        (1, "Project Overview", "01-project-overview.md"),
        (2, "Technology Stack", "02-technology-stack.md"),
        (3, "Repository Structure", "03-repository-structure.md"),
        (4, "System Architecture", "04-system-architecture.md"),
        (5, "Modules and Components", "05-modules-and-components.md"),
        (6, "Classes and Functions", "06-classes-and-functions.md"),
        (7, "APIs and Interfaces", "07-apis-and-interfaces.md"),
        (8, "Database and Data Model", "08-database-and-data-model.md"),
        (9, "Database Relationships", "09-database-relationships.md"),
        (10, "Dependencies", "10-dependencies.md"),
        (11, "Configuration and Environment", "11-configuration-and-environment.md"),
        (12, "Testing", "12-testing.md"),
        (13, "Security", "13-security.md"),
        (14, "CI/CD Pipeline", "14-ci-cd-pipeline.md"),
        (15, "Deployment Architecture", "15-deployment-architecture.md"),
        (16, "Setup and Developer Guide", "16-setup-and-developer-guide.md"),
    ]

    for expected_num, expected_title, expected_filename in expected_titles:
        meta = get_canonical_section(expected_num)
        assert meta["id"] == expected_num
        assert meta["title"] == expected_title
        assert meta["filename"] == expected_filename

        # Filename resolver check
        assert resolve_canonical_filename(expected_num) == expected_filename
        assert resolve_canonical_filename(expected_filename) == expected_filename


# ── TEST 2: PREVENTION OF 10-0, 11-1, 12-1 NUMBERING CORRUPTION ───────────────

def test_prevention_of_corrupted_numbering():
    """
    Verifies that Section 10, 11, 12 cannot be corrupted to '10-0', '11-1', or '12-1'.
    """
    for corrupted in ("10-0", "11-1", "12-1", "10-0.md", "11-1.md", "12-1.md"):
        # Ensure canonical resolver never maps to corrupted strings
        assert not resolve_canonical_filename(10).startswith("10-0")
        assert not resolve_canonical_filename(11).startswith("11-1")
        assert not resolve_canonical_filename(12).startswith("12-1")

    # Content validator must flag corrupted headings
    corrupted_content = "# 10-0. Dependencies\n\nSome text content..."
    result = validate_section_content(10, "Dependencies", corrupted_content)
    assert not result.is_valid
    assert any("corrupted heading numbering" in err for err in result.errors)


# ── TEST 3: VALIDATOR REJECTS EMPTY, TRUNCATED, AND PLACEHOLDER CONTENT ───────

def test_validator_rejects_empty_and_placeholders():
    """Verifies that empty or stubbed placeholder content fails validation."""
    # 1. Empty content
    res_empty = validate_section_content(1, "Project Overview", "")
    assert not res_empty.is_valid
    assert any("empty" in err for err in res_empty.errors)

    # 2. Truncated content (< 80 chars)
    res_short = validate_section_content(1, "Project Overview", "# 1. Project Overview\n\nBrief text.")
    assert not res_short.is_valid
    assert any("too short" in err for err in res_short.errors)

    # 3. Placeholder tokens
    res_placeholder = validate_section_content(
        1, "Project Overview",
        "# 1. Project Overview\n\nTODO: implement section content. Lorem ipsum dolor sit amet."
    )
    assert not res_placeholder.is_valid
    assert any("placeholder token" in err for err in res_placeholder.errors)


# ── TEST 4: MERMAID SYNTAX VALIDATION ─────────────────────────────────────────

def test_mermaid_syntax_validation():
    """Verifies that diagram validation catches invalid or malformed Mermaid."""
    valid_mermaid = "graph TD\n  A[Client] --> B[Server]"
    is_valid, err = validate_mermaid_syntax(valid_mermaid)
    assert is_valid
    assert not err

    # Unbalanced brackets
    invalid_mermaid = "graph TD\n  A[Client --> B[Server]"
    is_valid, err = validate_mermaid_syntax(invalid_mermaid)
    assert not is_valid
    assert "Unbalanced" in err


# ── TEST 5: STRICT COMPLETION GATE (FAILS CLOSED) ─────────────────────────────

def test_suite_completion_gate_fails_closed():
    """
    Verifies that a suite with fewer than 16 sections or any failed section
    fails the completion gate.
    """
    # 1. Only 15 sections provided
    partial_sections = [
        DocSection(
            section_number=i,
            title=f"Section {i}",
            schema_key=f"sec_{i}",
            filename=f"{i:02d}.md",
            content=f"# {i}. Section {i}\n\nDetailed valid content with sufficient length explaining technical architecture...",
            is_complete=True,
            status="COMPLETE",
        )
        for i in range(1, 16)
    ]
    report = validate_suite_integrity(partial_sections)
    assert not report.is_complete
    assert 16 in report.missing_section_ids
    assert any("Missing required section IDs: [16]" in e for e in report.errors)

    with pytest.raises(ValueError, match="Documentation suite failed completion gate"):
        assert_suite_complete(partial_sections)


# ── TEST 6: RESUMABLE GENERATION PRESERVES VALIDATED SECTIONS ─────────────────

def test_resumable_generation_preserves_validated_sections(db_session, test_user):
    """
    Verifies that generation incrementally checkpoints state and safely resumes
    pre-existing validated sections without overwriting them.
    """
    files = {
        "service.py": "def process(): return True\n",
        "README.md": "# Service\nCore service.",
    }
    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "resume-service", files)

    try:
        # Run 1: generate all sections
        result1 = generate_full_project_documentation(repo_id, db_session, force_all_16=True)
        assert result1.is_complete is True
        assert len(result1.sections) == 16

        sec1_path = storage_dir / "docs" / "01-project-overview.md"
        assert sec1_path.exists()
        original_sec1_content = sec1_path.read_text(encoding="utf-8")

        # Verify generation checkpoint exists
        state_file = storage_dir / "docs" / "metadata" / "generation_state.json"
        assert state_file.exists()
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        assert "1" in state_data
        assert state_data["1"]["is_complete"] is True

        # Run 2: resume should reuse existing validated sections
        result2 = generate_full_project_documentation(repo_id, db_session, resume=True, force_all_16=True)
        assert result2.is_complete is True
        resumed_sec1_content = (storage_dir / "docs" / "01-project-overview.md").read_text(encoding="utf-8")
        assert resumed_sec1_content == original_sec1_content
    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 7: MASTER DOCUMENT ASSEMBLY & CANONICAL ORDER ────────────────────────

def test_master_document_assembly_canonical_order(db_session, test_user):
    """
    Verifies that FULL_PROJECT_DOCUMENTATION.md contains all 16 headings
    in strict 1..16 sequential order without gaps or duplicates when force_all_16 is used.
    """
    files = {
        "main.py": "print('hello')",
        "README.md": "# App",
    }
    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "assembly-app", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session, force_all_16=True)
        assert result.is_complete is True

        master_doc = result.master_readme
        last_pos = -1

        for sec_id, title, _, _ in SECTIONS_META:
            heading = f"# {sec_id}. {title}"
            pos = master_doc.find(heading)
            assert pos != -1, f"Heading '{heading}' missing from master document!"
            assert pos > last_pos, f"Heading '{heading}' is out of canonical order!"
            last_pos = pos

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 8: DYNAMIC EVIDENCE-DRIVEN PLANNING & SEQUENTIAL RENUMBERING ─────────

def test_dynamic_evidence_driven_planning_and_sequential_renumbering(db_session, test_user):
    """
    Verifies that in a repository without a database, database relationships, or CI/CD:
    1. Inapplicable sections are cleanly omitted rather than filled with contradictory claims.
    2. Remaining sections are numbered sequentially 1..N.
    3. Stable topic IDs remain distinct from sequential display numbers.
    4. Table of contents and Master Document match the active manifest.
    """
    files = {
        "app.py": "def run():\n    return 'Hello World'\n",
        "requirements.txt": "requests==2.28.1\npydantic==1.10.2\n",
        "README.md": "# Simple Python App\nA basic request app without database or CI.",
    }
    repo_id, storage_dir = _create_fixture_repo(db_session, test_user.id, "dynamic-app", files)

    try:
        result = generate_full_project_documentation(repo_id, db_session, force_all_16=False)
        assert result.is_complete is True

        # Number of sections should be fewer than 16 (omitted db relationships, ci/cd, docker)
        assert result.total_sections < 16
        assert len(result.sections) == result.total_sections

        # Verify sequential ordering 1..N
        section_numbers = [s.section_number for s in result.sections]
        expected_numbers = list(range(1, result.total_sections + 1))
        assert section_numbers == expected_numbers, f"Expected sequential {expected_numbers}, got {section_numbers}"

        # Verify master document has exact sequential headings 1..N
        for s in result.sections:
            expected_heading = f"# {s.section_number}. {s.title}"
            assert expected_heading in result.master_readme, f"Missing {expected_heading} in master README"

        # Check manifest
        manifest_file = storage_dir / "docs" / "metadata" / "documentation-manifest.json"
        assert manifest_file.exists()
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert manifest_data["total_sections"] == result.total_sections
        assert len(manifest_data["included_sections"]) == result.total_sections
        assert len(manifest_data["omitted_sections"]) > 0

    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)


# ── TEST 9: SECTION 10 & TWO-DIGIT NUMBERING DEFECT REGRESSION TEST ───────────

def test_section_10_and_twodigit_numbering_integrity():
    """
    Directly tests that two-digit sections (such as 10. Dependencies) do NOT contain
    a malformed standalone '1' preceding the title or duplicate headings.
    """
    # 1. Test clean section 10
    valid_sec10 = (
        "# 10. Dependencies\n\n"
        "This project declares its software dependencies in package manifests.\n\n"
        "## 10.1 Runtime Dependencies\n\n"
        "| Package | Version | Ecosystem | Role |\n"
        "|---|---|---|---|\n"
        "| fastapi | 0.95.0 | pip | API Framework |\n\n"
        "Substantive technical explanation of package resolution and runtime dependencies..."
    )
    res_valid = validate_section_content(10, "Dependencies", valid_sec10, display_number=10)
    assert res_valid.is_valid, f"Expected valid section 10, got errors: {res_valid.errors}"

    # 2. Test corrupted section 10 with standalone 1 and repeated heading
    corrupted_sec10 = (
        "1\n\n"
        "1. Dependencies\n\n"
        "# 10. Dependencies\n\n"
        "Detailed package manifest analysis..."
    )
    res_corrupted = validate_section_content(10, "Dependencies", corrupted_sec10, display_number=10)
    assert not res_corrupted.is_valid
    assert any("malformed standalone '1'" in e for e in res_corrupted.errors)
