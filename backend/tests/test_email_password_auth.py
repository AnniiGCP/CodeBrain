import uuid
import pytest
from fastapi.testclient import TestClient
from main import app
from models import User
from database import SessionLocal

client = TestClient(app)

def test_register_and_login_flow():
    uid = uuid.uuid4().hex[:6]
    test_email = f"tester_{uid}@example.com"
    test_username = f"dev_{uid}"

    # 1. Register a new user
    reg_payload = {
        "email": test_email,
        "username": test_username,
        "password": "StrongPassword123!"
    }
    res = client.post("/auth/register", json=reg_payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["user"]["github_username"] == test_username
    assert data["user"]["email"] == test_email
    assert "token" in data
    assert "session_token" in res.cookies

    # 2. Reject duplicate email
    dup_email_res = client.post("/auth/register", json={
        "email": test_email,
        "username": f"diff_{uid}",
        "password": "StrongPassword123!"
    })
    assert dup_email_res.status_code == 409

    # 3. Reject duplicate username
    dup_user_res = client.post("/auth/register", json={
        "email": f"another_{uid}@example.com",
        "username": test_username,
        "password": "StrongPassword123!"
    })
    assert dup_user_res.status_code == 409

    # 4. Reject invalid short password
    short_pw_res = client.post("/auth/register", json={
        "email": f"short_{uid}@example.com",
        "username": f"short_{uid}",
        "password": "123"
    })
    assert short_pw_res.status_code in (400, 422)

    # 5. Login with email
    login_email_res = client.post("/auth/login", json={
        "identifier": test_email,
        "password": "StrongPassword123!"
    })
    assert login_email_res.status_code == 200
    assert login_email_res.json()["user"]["github_username"] == test_username

    # 6. Login with username
    login_user_res = client.post("/auth/login", json={
        "identifier": test_username,
        "password": "StrongPassword123!"
    })
    assert login_user_res.status_code == 200

    # 7. Invalid password
    bad_login_res = client.post("/auth/login", json={
        "identifier": "tester_dev",
        "password": "WrongPassword!"
    })
    assert bad_login_res.status_code == 401

    # 8. Check /me with authenticated session
    me_res = client.get("/me", cookies=login_user_res.cookies)
    assert me_res.status_code == 200
    assert me_res.json()["github_username"] == test_username

    # 9. Logout
    logout_res = client.post("/logout")
    assert logout_res.status_code == 200

    # 10. Developer bypass login still works
    dev_res = client.post("/auth/dev-login", json={
        "github_id": "dev_bypass_999",
        "github_username": "DevBypassUser"
    })
    assert dev_res.status_code == 200
    assert dev_res.json()["user"]["github_username"] == "DevBypassUser"
