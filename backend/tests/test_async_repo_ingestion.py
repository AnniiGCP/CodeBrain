"""
backend/tests/test_async_repo_ingestion.py
-------------------------------------------
Tests for asynchronous repository ingestion, stage tracking,
and pre-flight rate limit resilience.
"""
import io
import os
import uuid
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from main import app
from database import SessionLocal
from models import Repo, User, RepoFile
from auth import hash_password, create_session_token

client = TestClient(app)


@pytest.fixture
def auth_user():
    db = SessionLocal()
    uid = uuid.uuid4().hex[:6]
    test_email = f"async_test_{uid}@example.com"
    test_username = f"user_{uid}"
    reg_payload = {
        "email": test_email,
        "username": test_username,
        "password": "StrongPassword123!"
    }
    res = client.post("/auth/register", json=reg_payload)
    data = res.json()
    u_id = data["user"]["id"]
    token = data["token"]
    user = db.query(User).filter(User.id == u_id).first()
    yield user, token
    # Cleanup
    db.query(RepoFile).filter(RepoFile.repo_id.in_([r.id for r in user.repos])).delete(synchronize_session=False)
    db.query(Repo).filter(Repo.user_id == user.id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    db.close()


def test_clone_github_repo_returns_immediate_status(auth_user):
    """Verify POST /repos/github returns immediately with status CLONING without blocking."""
    user, token = auth_user
    headers = {"Authorization": f"Bearer {token}"}

    with patch("routers.repos.GitRepo") as mock_git, \
         patch("routers.repos.httpx.Client") as mock_httpx, \
         patch("routers.repos.run_clone_and_pipeline") as mock_worker:

        # Mock pre-flight API to return 200
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.get.return_value = mock_resp
        mock_httpx.return_value = mock_client

        resp = client.post(
            "/repos/github",
            json={"url": "https://github.com/AnniiGCP/QuizGenAI.git"},
            headers=headers,
        )

        assert resp.status_code == 201
        data = resp.json()
        assert "repo_id" in data
        assert data["name"] == "QuizGenAI"
        assert data["source_type"] == "github"
        assert data["pipeline_status"] == "CLONING"
        assert data["file_count"] == 0


def test_clone_preflight_github_rate_limit_proceeds(auth_user):
    """Verify when unauthenticated GitHub API rate limit returns 403, clone is NOT aborted."""
    user, token = auth_user
    headers = {"Authorization": f"Bearer {token}"}

    with patch("routers.repos.GitRepo") as mock_git, \
         patch("routers.repos.httpx.Client") as mock_httpx, \
         patch("routers.repos.run_clone_and_pipeline") as mock_worker:

        # Mock unauthenticated GitHub API rate limit (403 without user token)
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_client.get.return_value = mock_resp
        mock_httpx.return_value = mock_client

        resp = client.post(
            "/repos/github",
            json={"url": "https://github.com/AnniiGCP/QuizGenAI.git"},
            headers=headers,
        )

        # Should proceed rather than blocking with 400
        assert resp.status_code == 201
        data = resp.json()
        assert data["pipeline_status"] == "CLONING"


def test_pipeline_status_polling_stages(auth_user):
    """Verify /repos/{repo_id}/pipeline-status reports stages and persistent last_activity."""
    user, token = auth_user
    db = SessionLocal()
    try:
        repo = Repo(
            id=f"test_stage_repo_{uuid.uuid4().hex[:8]}",
            user_id=user.id,
            name="StageTestRepo",
            source_type="github",
            pipeline_status="INGESTING",
            last_activity_summary="Discovering and indexing files…",
        )
        db.add(repo)
        db.commit()

        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get(f"/repos/{repo.id}/pipeline-status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["pipeline_status"] == "INGESTING"
        assert "Discovering and indexing files" in data["message"]
    finally:
        db.query(Repo).filter(Repo.id == repo.id).delete()
        db.commit()
        db.close()
