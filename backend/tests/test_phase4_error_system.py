import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys
import uuid
import shutil

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from main import app
from database import SessionLocal, init_db
from models import User, Repo, RepoFile, Symbol, ErrorReport
from auth import create_session_token
from errordetection.scanner import detect_errors
from routers.pipeline import _persist_error_reports

client = TestClient(app)
STORAGE_ROOT = Path(__file__).parent.parent / "storage"


@pytest.fixture
def error_test_repo():
    init_db()
    with SessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            github_id=f"gh_{uuid.uuid4().hex[:8]}",
            github_username="error_test_user",
        )
        db.add(user)
        db.commit()

        repo = Repo(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name="error_test_repo",
            source_type="upload",
            pipeline_status="DONE",
        )
        db.add(repo)
        db.commit()

        user_id = user.id
        repo_id = repo.id

    repo_dir = STORAGE_ROOT / repo_id
    repo_dir.mkdir(parents=True, exist_ok=True)

    yield {"user_id": user_id, "repo_id": repo_id, "repo_dir": repo_dir}

    # Cleanup
    shutil.rmtree(repo_dir, ignore_errors=True)


def test_clean_repo_has_zero_fabricated_errors(error_test_repo):
    """Verify clean code produces exactly zero errors and never fabricates synthetic ones."""
    repo_id = error_test_repo["repo_id"]
    repo_dir = error_test_repo["repo_dir"]
    user_id = error_test_repo["user_id"]
    token = create_session_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Write clean code
    clean_file = repo_dir / "clean_math.py"
    clean_file.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    with SessionLocal() as db:
        rf = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo_id,
            path="clean_math.py",
            language="python",
            size=len(clean_file.read_bytes()),
            content_hash="clean123",
        )
        db.add(rf)
        sym = Symbol(
            file_id=rf.id,
            repo_id=repo_id,
            symbol_type="function",
            name="add",
            source_code="def add(a: int, b: int) -> int:\n    return a + b",
        )
        db.add(sym)
        db.commit()

        scan_result = detect_errors(repo_id, db)
        assert scan_result["total_issues"] == 0
        assert len(scan_result["issues"]) == 0

        _persist_error_reports(repo_id, scan_result["issues"], db)

    resp = client.get(f"/repos/{repo_id}/errors", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert len(data["errors"]) == 0


def test_parser_syntax_error_detection(error_test_repo):
    """Verify genuine Python syntax error is captured with parser source and line/column."""
    repo_id = error_test_repo["repo_id"]
    repo_dir = error_test_repo["repo_dir"]
    user_id = error_test_repo["user_id"]
    token = create_session_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Write broken syntax file
    broken_file = repo_dir / "broken_syntax.py"
    broken_file.write_text("def broken_func(\n    # unclosed parenthesis\n    x = 1\n", encoding="utf-8")

    with SessionLocal() as db:
        rf = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo_id,
            path="broken_syntax.py",
            language="python",
            size=len(broken_file.read_bytes()),
            content_hash="broken123",
        )
        db.add(rf)
        db.commit()

        scan_result = detect_errors(repo_id, db)
        assert scan_result["total_issues"] >= 1
        parser_err = next(i for i in scan_result["issues"] if i["source"] == "parser")
        assert parser_err["rule_id"] == "SYNTAX_ERROR"
        assert parser_err["file_path"] == "broken_syntax.py"
        assert parser_err["line"] is not None
        assert parser_err["stack_trace"] is not None

        _persist_error_reports(repo_id, scan_result["issues"], db)

    resp = client.get(f"/repos/{repo_id}/errors", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    err = data["errors"][0]
    assert err["source"] == "parser"
    assert "Parser Error" in err["message"]
    assert err["file_path"] == "broken_syntax.py"
    assert err["severity"] == "error"


def test_static_analysis_smell_detection(error_test_repo):
    """Verify static analysis detects code smells (eval, bare except) accurately."""
    repo_id = error_test_repo["repo_id"]
    repo_dir = error_test_repo["repo_dir"]
    user_id = error_test_repo["user_id"]
    token = create_session_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    smelly_file = repo_dir / "security_risk.py"
    smelly_code = "def dangerous_eval(expr):\n    return eval(expr)\n"
    smelly_file.write_text(smelly_code, encoding="utf-8")

    with SessionLocal() as db:
        rf = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo_id,
            path="security_risk.py",
            language="python",
            size=len(smelly_code.encode("utf-8")),
            content_hash="smelly123",
        )
        db.add(rf)
        sym = Symbol(
            file_id=rf.id,
            repo_id=repo_id,
            symbol_type="function",
            name="dangerous_eval",
            source_code=smelly_code,
        )
        db.add(sym)
        db.commit()

        scan_result = detect_errors(repo_id, db)
        eval_issue = next(i for i in scan_result["issues"] if i["rule_id"] == "PY003")
        assert eval_issue["source"] == "static_analysis"
        assert eval_issue["severity"] == "warning"
        assert "eval()" in eval_issue["message"]

        _persist_error_reports(repo_id, scan_result["issues"], db)

    resp = client.get(f"/repos/{repo_id}/errors?severity=warning", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert any(e["rule_id"] == "PY003" for e in data["errors"])
