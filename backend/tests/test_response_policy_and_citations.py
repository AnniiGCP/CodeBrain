"""
backend/tests/test_response_policy_and_citations.py
---------------------------------------------------
Automated regression tests for the CodeBrain AI Central Response Policy,
intent classification, retrieval gating, and citation integrity.
Covers Test 1 through Test 10 & Test 12.
"""
import json
import pytest
from pathlib import Path
import sys
import uuid

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from ai.policy import (
    QueryIntent,
    classify_intent,
    should_retrieve_context,
    filter_and_validate_citations,
    build_context_block,
    get_system_prompt_for_intent,
)
from vectorstore.index import search
from database import SessionLocal, init_db
from models import User, Repo, RepoFile, Symbol
from auth import create_session_token


@pytest.fixture
def policy_fixture(tmp_path):
    init_db()
    with SessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            github_id=f"gh_{uuid.uuid4().hex[:8]}",
            github_username="policy_tester",
        )
        db.add(user)
        db.commit()

        repo = Repo(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name="policy_demo_repo",
            source_type="upload",
            pipeline_status="DONE",
        )
        db.add(repo)
        db.commit()

        # Create files on disk inside storage/<repo_id>
        storage_dir = Path(__file__).parent.parent / "storage" / repo.id
        storage_dir.mkdir(parents=True, exist_ok=True)

        auth_file = storage_dir / "auth" / "jwt_service.py"
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        auth_code = (
            "import jwt\n"
            "\n"
            "def generate_token(uid: str):\n"
            "    return jwt.encode({'uid': uid}, 'secret')\n"
            "\n"
            "def verify_token(token: str):\n"
            "    return jwt.decode(token, 'secret')\n"
        )
        auth_file.write_text(auth_code, encoding="utf-8")

        db_file = storage_dir / "db" / "session.py"
        db_file.parent.mkdir(parents=True, exist_ok=True)
        db_code = (
            "from sqlalchemy import create_engine\n"
            "DATABASE_URL = 'sqlite:///./app.db'\n"
            "engine = create_engine(DATABASE_URL)\n"
        )
        db_file.write_text(db_code, encoding="utf-8")

        # Database rows
        rf1 = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo.id,
            path="auth/jwt_service.py",
            language="python",
            size=len(auth_code),
            content_hash="hash_auth",
        )
        rf2 = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo.id,
            path="db/session.py",
            language="python",
            size=len(db_code),
            content_hash="hash_db",
        )
        db.add_all([rf1, rf2])
        db.commit()

        sym1 = Symbol(
            file_id=rf1.id,
            repo_id=repo.id,
            symbol_type="function",
            name="generate_token",
            source_code="def generate_token(uid: str):\n    return jwt.encode({'uid': uid}, 'secret')",
        )
        sym2 = Symbol(
            file_id=rf1.id,
            repo_id=repo.id,
            symbol_type="function",
            name="verify_token",
            source_code="def verify_token(token: str):\n    return jwt.decode(token, 'secret')",
        )
        sym3 = Symbol(
            file_id=rf2.id,
            repo_id=repo.id,
            symbol_type="variable",
            name="engine",
            source_code="engine = create_engine(DATABASE_URL)",
        )
        db.add_all([sym1, sym2, sym3])
        db.commit()

        user_id = user.id
        repo_id = repo.id

    return {"user_id": user_id, "repo_id": repo_id}


# ── Test 1 — Greeting ─────────────────────────────────────────────────────────

def test_greeting_intent():
    """Input 'HI' -> classified as GREETING, no retrieval, zero citations."""
    for greet in ["HI", "hi", "Hello!", "hey there", "good morning :)", "Hey CodeBrain"]:
        intent = classify_intent(greet)
        assert intent == QueryIntent.GREETING, f"Failed for {greet}"
        assert should_retrieve_context(intent) is False
        sys_prompt = get_system_prompt_for_intent(intent)
        assert "Do NOT search or analyze any repository files" in sys_prompt


def test_active_file_header_does_not_pollute_intent():
    """Active file header [Active File: backend/tests/hits.py] must not cause HI or general Qs to trigger repo analysis."""
    # Greeting with active file
    q_greet = "[Active File: backend/tests/hits.py]\nHI"
    intent_greet = classify_intent(q_greet)
    assert intent_greet == QueryIntent.GREETING
    assert should_retrieve_context(intent_greet) is False

    # General question with active file
    q_gen = "[Active File: backend/tests/hits.py]\nWhat is a Python decorator?"
    intent_gen = classify_intent(q_gen)
    assert intent_gen == QueryIntent.GENERAL_PROGRAMMING
    assert should_retrieve_context(intent_gen) is False


# ── Test 2 — Acknowledgement ──────────────────────────────────────────────────

def test_acknowledgement_intent():
    """Input 'Thanks' -> classified as GREETING/pleasantry, no retrieval."""
    for ack in ["Thanks", "thank you so much", "ok", "got it", "cool!", "bye"]:
        intent = classify_intent(ack)
        assert intent == QueryIntent.GREETING, f"Failed for {ack}"
        assert should_retrieve_context(intent) is False


# ── Test 3 — Greeting plus technical request ─────────────────────────────────

def test_greeting_with_substantive_request():
    """Greeting does NOT suppress substantive question."""
    q = "Hi, explain the authentication flow in this repository."
    intent = classify_intent(q)
    assert intent == QueryIntent.REPO_QUERY
    assert should_retrieve_context(intent) is True

    q2 = "Hello, why is my authentication test failing with AssertionError?"
    intent2 = classify_intent(q2)
    assert intent2 == QueryIntent.ERROR_DIAGNOSIS


# ── Test 4 — General programming question ────────────────────────────────────

def test_general_programming_question():
    """General conceptual questions receive GENERAL_PROGRAMMING intent and zero repo citations."""
    queries = [
        "What is a Python decorator?",
        "Explain the difference between a list and a tuple",
        "What is CI/CD?",
        "How does semantic search work?",
        "What are Python generators?",
    ]
    for q in queries:
        intent = classify_intent(q)
        assert intent == QueryIntent.GENERAL_PROGRAMMING, f"Failed for {q}"
        assert should_retrieve_context(intent) is False
        cites = filter_and_validate_citations("fake_repo", [{"file_path": "foo.py"}], q, intent)
        assert cites == []


# ── Test 5 — Repository-specific question ────────────────────────────────────

def test_repository_specific_question(policy_fixture):
    """Where is the database connection configured? -> retrieves db/session.py."""
    repo_id = policy_fixture["repo_id"]
    with SessionLocal() as db:
        results = search(repo_id, "database connection", top_k=5, db=db)
        # Search returns symbols/files related to database / engine
        intent = classify_intent("Where is the database connection configured in this repo?")
        assert intent == QueryIntent.REPO_QUERY
        assert should_retrieve_context(intent) is True

        validated = filter_and_validate_citations(repo_id, results, "database connection", intent)
        assert len(validated) <= 5
        for v in validated:
            assert v["file_path"].startswith("db/") or v["file_path"].startswith("auth/")
            assert v["start_line"] >= 1


# ── Test 6 — Duplicate search results ────────────────────────────────────────

def test_duplicate_search_results_consolidation(policy_fixture):
    """Duplicate chunks from the same file and overlapping lines are consolidated."""
    repo_id = policy_fixture["repo_id"]
    raw_results = [
        {"file_path": "auth/jwt_service.py", "name": "generate_token", "start_line": 3, "source_code": "def generate_token...", "score": 0.95},
        {"file_path": "auth/jwt_service.py", "name": "generate_token", "start_line": 4, "source_code": "def generate_token...", "score": 0.90},
        {"file_path": "auth/jwt_service.py", "name": "generate_token", "start_line": 3, "source_code": "def generate_token...", "score": 0.85},
        {"file_path": "db/session.py", "name": "engine", "start_line": 3, "source_code": "engine = ...", "score": 0.80},
    ]
    intent = QueryIntent.REPO_QUERY
    validated = filter_and_validate_citations(repo_id, raw_results, "query", intent)
    auth_cites = [v for v in validated if v["file_path"] == "auth/jwt_service.py"]
    # All 3 overlapping chunks in jwt_service are consolidated into 1!
    assert len(auth_cites) == 1
    assert len(validated) == 2


# ── Test 7 — Invalid citation rejection ──────────────────────────────────────

def test_invalid_citation_rejected(policy_fixture):
    """Nonexistent files or ghost paths on disk are rejected."""
    repo_id = policy_fixture["repo_id"]
    raw_results = [
        {"file_path": "nonexistent/ghost_module.py", "name": "ghost_func", "start_line": 42, "source_code": "def ghost(): pass", "score": 0.99},
        {"file_path": "auth/jwt_service.py", "name": "generate_token", "start_line": 3, "source_code": "def generate_token(): pass", "score": 0.90},
    ]
    validated = filter_and_validate_citations(repo_id, raw_results, "query", QueryIntent.REPO_QUERY)
    paths = [v["file_path"] for v in validated]
    assert "nonexistent/ghost_module.py" not in paths
    assert "auth/jwt_service.py" in paths


# ── Test 8 — Stale repository isolation ──────────────────────────────────────

def test_stale_repo_isolation(policy_fixture):
    """Citations checked against a different repository ID with different files are rejected."""
    other_repo_id = str(uuid.uuid4())
    raw_results = [
        {"file_path": "auth/jwt_service.py", "name": "generate_token", "start_line": 3, "source_code": "def generate_token...", "score": 0.95},
    ]
    validated = filter_and_validate_citations(other_repo_id, raw_results, "query", QueryIntent.REPO_QUERY)
    # File does not exist under other_repo_id's storage
    assert validated == []


# ── Test 9 — Error diagnosis format ──────────────────────────────────────────

def test_error_diagnosis_policy():
    """Traceback/test failure input receives ERROR_DIAGNOSIS intent and structured prompt."""
    traceback_input = (
        "Traceback (most recent call last):\n"
        '  File "test_auth.py", line 12, in test_login\n'
        "    assert res.status_code == 200\n"
        "AssertionError: assert 401 == 200\n"
        "Diagnose why this login test is failing."
    )
    intent = classify_intent(traceback_input)
    assert intent == QueryIntent.ERROR_DIAGNOSIS
    prompt = get_system_prompt_for_intent(intent)
    assert "**Likely cause**" in prompt
    assert "**Evidence**" in prompt
    assert "**Fix**" in prompt
    assert "**Validation**" in prompt


# ── Test 10 — Comprehensive analysis ─────────────────────────────────────────

def test_comprehensive_analysis_intent():
    """Requests for full architecture receive COMPREHENSIVE_ANALYSIS intent."""
    q = "Analyse the authentication and database architecture across the whole codebase."
    intent = classify_intent(q)
    assert intent == QueryIntent.COMPREHENSIVE_ANALYSIS
    prompt = get_system_prompt_for_intent(intent)
    assert "software architect" in prompt


# ── Test 12 — Streaming metadata envelope ────────────────────────────────────

def test_context_block_formatting():
    """Context block formats start and end lines properly without duplicating headers."""
    citations = [
        {
            "index": 1,
            "file_path": "auth/jwt_service.py",
            "symbol_type": "function",
            "name": "generate_token",
            "start_line": 3,
            "end_line": 5,
            "language": "python",
            "source_code": "def generate_token(uid: str):\n    return jwt.encode({'uid': uid}, 'secret')",
        }
    ]
    block = build_context_block(citations)
    assert "=== RELEVANT CODE CONTEXT ===" in block
    assert "auth/jwt_service.py:3-5" in block
    assert "generate_token" in block
    assert "=== END CODE CONTEXT ===" in block
