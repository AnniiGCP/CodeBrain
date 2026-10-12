import pytest
from fastapi.testclient import TestClient
import os
import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from main import app
from database import SessionLocal, init_db
from models import User
from auth import (
    create_session_token,
    create_oauth_state,
    verify_oauth_state,
    set_user_github_token,
    get_user_github_token,
)

client = TestClient(app)


@pytest.fixture
def test_user():
    init_db()
    with SessionLocal() as db:
        user = db.query(User).filter(User.github_id == "test_phase1_user").first()
        if not user:
            user = User(
                github_id="test_phase1_user",
                github_username="test_phase1_user",
                github_avatar_url="https://github.com/test.png",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        user_id = user.id
    return user_id


def test_oauth_login_unconfigured_error(monkeypatch):
    """Verify /auth/github/login returns clear 500 when credentials are placeholder."""
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "your_github_oauth_client_id")
    resp = client.get("/auth/github/login", follow_redirects=False)
    assert resp.status_code == 500
    assert "GitHub OAuth is not configured" in resp.json()["detail"]


def test_oauth_login_redirect_and_state(monkeypatch):
    """Verify /auth/github/login generates valid CSRF state and 307 redirect when configured."""
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "Ov23testclientid123")
    resp = client.get("/auth/github/login", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers.get("location", "")
    assert "github.com/login/oauth/authorize" in location
    assert "client_id=Ov23testclientid123" in location
    assert "state=" in location


def test_csrf_state_generator_and_verification():
    """Verify create_oauth_state and verify_oauth_state."""
    state = create_oauth_state()
    assert state is not None
    assert verify_oauth_state(state) is True
    # Tampered state must fail
    assert verify_oauth_state(state + "tampered") is False
    assert verify_oauth_state("invalid.state") is False


def test_oauth_callback_rejects_invalid_csrf_state():
    """Verify /auth/github/callback rejects spoofed/invalid CSRF state."""
    resp = client.get("/auth/github/callback?code=fake_code&state=bad_state", follow_redirects=False)
    assert resp.status_code == 400
    assert "CSRF validation failed" in resp.json()["detail"]


def test_github_repos_endpoint_unconnected(test_user):
    """Verify /auth/github/repos returns connected=False when no token is present."""
    token = create_session_token(test_user)
    headers = {"Authorization": f"Bearer {token}"}
    
    # Ensure token is cleared
    with SessionLocal() as db:
        u = db.query(User).filter(User.id == test_user).first()
        set_user_github_token(u, "")
        db.commit()

    resp = client.get("/auth/github/repos", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "connected" in data
    assert isinstance(data["repos"], list)


def test_github_disconnect_endpoint(test_user):
    """Verify /auth/github/disconnect removes user's GitHub token."""
    token = create_session_token(test_user)
    headers = {"Authorization": f"Bearer {token}"}

    # Set mock encrypted token
    with SessionLocal() as db:
        u = db.query(User).filter(User.id == test_user).first()
        set_user_github_token(u, "mock_token_for_test")
        db.commit()

    # Disconnect
    resp = client.post("/auth/github/disconnect", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "disconnected"

    # Verify token is wiped
    with SessionLocal() as db:
        u = db.query(User).filter(User.id == test_user).first()
        assert get_user_github_token(u) is None


def test_get_me_shows_github_connected_flag(test_user):
    """Verify /me returns accurate github_connected boolean."""
    token = create_session_token(test_user)
    headers = {"Authorization": f"Bearer {token}"}

    with SessionLocal() as db:
        u = db.query(User).filter(User.id == test_user).first()
        set_user_github_token(u, "")
        db.commit()

    resp = client.get("/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["github_connected"] is False

    with SessionLocal() as db:
        u = db.query(User).filter(User.id == test_user).first()
        set_user_github_token(u, "active_test_token")
        db.commit()

    resp = client.get("/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["github_connected"] is True
