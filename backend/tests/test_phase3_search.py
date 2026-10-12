import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys
import uuid

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from main import app
from database import SessionLocal, init_db
from models import User, Repo, RepoFile, Symbol
from auth import create_session_token

client = TestClient(app)


@pytest.fixture
def search_fixture():
    init_db()
    with SessionLocal() as db:
        # Create user
        user = User(
            id=str(uuid.uuid4()),
            github_id=f"gh_{uuid.uuid4().hex[:8]}",
            github_username="search_user",
        )
        db.add(user)
        db.commit()

        # Create repo
        repo = Repo(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name="search_demo",
            source_type="upload",
            pipeline_status="DONE",
        )
        db.add(repo)
        db.commit()

        # Create RepoFile
        rf = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo.id,
            path="auth/jwt_service.py",
            language="python",
            size=256,
            content_hash="hash123",
        )
        db.add(rf)
        db.commit()

        # Create Symbols
        sym1 = Symbol(
            file_id=rf.id,
            repo_id=repo.id,
            symbol_type="function",
            name="generate_access_token",
            source_code="def generate_access_token(user_id: str):\n    return jwt.encode({'uid': user_id})\n",
        )
        sym2 = Symbol(
            file_id=rf.id,
            repo_id=repo.id,
            symbol_type="function",
            name="verify_access_token",
            source_code="def verify_access_token(token: str):\n    return jwt.decode(token)\n",
        )
        db.add_all([sym1, sym2])
        db.commit()

        user_id = user.id
        repo_id = repo.id

    return {"user_id": user_id, "repo_id": repo_id}


def test_search_exact_and_partial_symbol(search_fixture):
    """Verify search returns matching symbols with rich metadata and high relevance score."""
    user_id = search_fixture["user_id"]
    repo_id = search_fixture["repo_id"]
    token = create_session_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Exact symbol match
    resp = client.post(
        f"/repos/{repo_id}/search",
        json={"query": "generate_access_token", "top_k": 5},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) >= 1
    top = data["results"][0]
    assert top["name"] == "generate_access_token"
    assert top["symbol_type"] == "function"
    assert top["file_path"] == "auth/jwt_service.py"
    assert top["score"] == 1.0
    assert "start_line" in top
    assert "def generate_access_token" in top["source_code"]

    # 2. Substring query
    resp_sub = client.post(
        f"/repos/{repo_id}/search",
        json={"query": "token", "top_k": 5},
        headers=headers,
    )
    assert resp_sub.status_code == 200
    sub_results = resp_sub.json()["results"]
    assert len(sub_results) == 2
    names = {r["name"] for r in sub_results}
    assert "generate_access_token" in names
    assert "verify_access_token" in names


def test_search_by_file_path(search_fixture):
    """Verify searching for file path returns symbols located in that file."""
    user_id = search_fixture["user_id"]
    repo_id = search_fixture["repo_id"]
    token = create_session_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/repos/{repo_id}/search",
        json={"query": "jwt_service", "top_k": 5},
        headers=headers,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) > 0
    assert all(r["file_path"] == "auth/jwt_service.py" for r in results)


def test_search_tenant_isolation(search_fixture):
    """Verify other users cannot search repositories they do not own (403 Forbidden)."""
    repo_id = search_fixture["repo_id"]
    other_user_token = create_session_token("stranger_user_id_999")
    headers = {"Authorization": f"Bearer {other_user_token}"}

    # Unauthenticated / invalid user
    resp = client.post(
        f"/repos/{repo_id}/search",
        json={"query": "token", "top_k": 5},
        headers=headers,
    )
    assert resp.status_code in (401, 403)
