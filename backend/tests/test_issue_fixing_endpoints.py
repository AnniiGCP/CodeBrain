"""
backend/tests/test_issue_fixing_endpoints.py
--------------------------------------------
Integration tests verifying all issue-fixing entry points route through
the authoritative issue-fixing router (APInex -> NVIDIA -> Groq).
"""
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from main import app
from database import SessionLocal, init_db
from models import User, Repo, RepoFile, Symbol, ErrorReport
from auth import create_session_token

client = TestClient(app)

SAMPLE_VALID_DIFF = """--- a/clean_math.py
+++ b/clean_math.py
@@ -1,2 +1,2 @@
-def add(a, b):
-    return a - b
+def add(a, b):
+    return a + b
"""


@pytest.fixture
def repo_context():
    init_db()
    with SessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            github_id=f"gh_{uuid.uuid4().hex[:8]}",
            github_username="fix_tester",
            preferred_ai_provider="nvidia",  # Chat preference is NVIDIA, but issue fixing MUST use APInex first!
        )
        db.add(user)
        db.commit()

        repo = Repo(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name="test_repo",
            source_type="upload",
            pipeline_status="DONE",
        )
        db.add(repo)
        db.commit()

        rf = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo.id,
            path="clean_math.py",
            language="python",
            size=50,
            content_hash="h1",
        )
        db.add(rf)
        db.commit()

        sym = Symbol(
            file_id=rf.id,
            repo_id=repo.id,
            symbol_type="function",
            name="add",
            source_code="def add(a, b):\n    return a - b\n",
        )
        db.add(sym)
        db.commit()

        err = ErrorReport(
            id=str(uuid.uuid4()),
            repo_id=repo.id,
            symbol_id=sym.id,
            rule_id="MATH01",
            severity="error",
            message="Incorrect subtraction",
            file_path="clean_math.py",
            language="python",
            fix_status="PENDING",
        )
        db.add(err)
        db.commit()

        u_id = user.id
        r_id = repo.id
        s_id = sym.id
        e_id = err.id

    token = create_session_token(u_id)
    headers = {"Authorization": f"Bearer {token}"}

    yield {
        "user_id": u_id,
        "repo_id": r_id,
        "symbol_id": s_id,
        "error_id": e_id,
        "headers": headers,
    }


def test_symbol_fix_endpoint_uses_apinex_first(repo_context):
    """POST /symbols/{id}/fix must use APInex first and return attribution."""
    headers = repo_context["headers"]
    sym_id = repo_context["symbol_id"]

    with patch("ai.issue_fix_router.route_issue_fix") as mock_route:
        mock_route.return_value = MagicMock(
            diff=SAMPLE_VALID_DIFF,
            provider="apinex",
            model="free/gpt-6-luna",
            model_display_name="GPT-6 Luna",
            fallback_used=False,
            fix_attribution="Fixed using APInex GPT-6 Luna",
            attempts=[{"provider": "apinex", "status": "success"}],
        )

        resp = client.post(
            f"/symbols/{sym_id}/fix",
            json={"issue_description": "Fix subtraction to addition"},
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "apinex"
        assert data["model_used"] == "free/gpt-6-luna"
        assert data["fix_attribution"] == "Fixed using APInex GPT-6 Luna"
        assert data["fallback_used"] is False
        mock_route.assert_called_once()


def test_generate_error_fix_endpoint_uses_central_router(repo_context):
    """POST /repos/{repo_id}/errors/{error_id}/generate-fix must return provider diagnostics."""
    headers = repo_context["headers"]
    repo_id = repo_context["repo_id"]
    error_id = repo_context["error_id"]

    with patch("ai.issue_fix_router.route_issue_fix") as mock_route:
        mock_route.return_value = MagicMock(
            diff=SAMPLE_VALID_DIFF,
            provider="apinex",
            model="free/gpt-6-luna",
            model_display_name="GPT-6 Luna",
            fallback_used=False,
            fix_attribution="Fixed using APInex GPT-6 Luna",
            attempts=[{"provider": "apinex", "status": "success"}],
        )

        resp = client.post(
            f"/repos/{repo_id}/errors/{error_id}/generate-fix",
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_used"] == "apinex"
        assert data["model_used"] == "free/gpt-6-luna"
        assert data["fix_attribution"] == "Fixed using APInex GPT-6 Luna"
        assert data["fallback_used"] is False
        assert len(data["attempts"]) >= 1


def test_error_listing_includes_provider_attribution(repo_context):
    """GET /repos/{repo_id}/errors serializes fix_provider and fix_attribution."""
    headers = repo_context["headers"]
    repo_id = repo_context["repo_id"]
    error_id = repo_context["error_id"]

    with SessionLocal() as db:
        err = db.query(ErrorReport).filter(ErrorReport.id == error_id).first()
        err.suggested_fix = SAMPLE_VALID_DIFF
        err.fix_provider = "apinex"
        err.fix_model = "free/gpt-6-luna"
        err.fix_attribution = "Fixed using APInex GPT-6 Luna"
        err.fix_status = "READY"
        db.commit()

    resp = client.get(f"/repos/{repo_id}/errors", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["errors"]) >= 1
    target = next(e for e in data["errors"] if e["id"] == error_id)
    assert target["fix_provider"] == "apinex"
    assert target["fix_attribution"] == "Fixed using APInex GPT-6 Luna"
    assert target["fix_model"] == "free/gpt-6-luna"
