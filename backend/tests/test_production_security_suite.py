"""
tests/test_production_security_suite.py
----------------------------------------
Comprehensive automated security test suite validating:
1. Rate Limiting, Abuse Prevention & Failed Login Backoff
2. Strict Repository URL & SSRF Validation
3. Zip Slip, Archive Bombs & Symlink Traversal Protection
4. File Workspace Containment & Path Traversal Guard
5. Session Secret Production Enforcement & Dev-Login Gating
6. Browser Defense-in-Depth Security Headers
7. Centralized Error Sanitization & Secret Redaction
"""
import io
import os
import uuid
import zipfile
import pytest
from fastapi.testclient import TestClient

from main import app
from rate_limiter import (
    reset_rate_limit_tracking,
    check_rate_limit,
    get_client_ip,
    check_login_rate_limit,
    record_login_failure,
    record_login_success,
)
from routers.repos import validate_github_repo_url
from docgen.secret_redactor import redact_secrets, sanitize_host_paths
from auth import _get_session_secret


@pytest.fixture(autouse=True)
def clean_rate_limits():
    reset_rate_limit_tracking()
    yield
    reset_rate_limit_tracking()


# ── 1. Rate Limiting & Abuse Prevention Tests ─────────────────────────────────

def test_sliding_window_rate_limiter():
    """Verify that atomic sliding window rate limiter permits within quota and rejects with Retry-After."""
    key = "test_key_user_1"
    # Allow 3 requests in 60s
    for _ in range(3):
        allowed, retry_after = check_rate_limit(key, max_requests=3, window_seconds=60)
        assert allowed is True
        assert retry_after == 0

    # 4th request must be rejected with positive retry_after
    allowed, retry_after = check_rate_limit(key, max_requests=3, window_seconds=60)
    assert allowed is False
    assert retry_after > 0


def test_login_brute_force_failed_attempts_backoff():
    """Verify failed login attempts trigger HTTP 429 when threshold exceeded."""
    from fastapi import HTTPException, Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/auth/login",
        "headers": [],
        "client": ("198.51.100.1", 12345),
    }
    mock_request = Request(scope)
    identifier = "victim@example.com"

    # Simulate 4 failures (under max of 5)
    for _ in range(4):
        check_login_rate_limit(mock_request, identifier)
        record_login_failure(mock_request, identifier)

    # 5th failure exceeds threshold
    record_login_failure(mock_request, identifier)
    with pytest.raises(HTTPException) as exc_info:
        check_login_rate_limit(mock_request, identifier)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers

    # Success clears failure counter
    record_login_success(mock_request, identifier)
    # Should now pass without raising
    check_login_rate_limit(mock_request, identifier)


def test_trusted_proxy_client_ip_resolution():
    """Verify client IP extraction safely respects trusted proxies while ignoring spoofed headers from untrusted sources."""
    from fastapi import Request

    # Case A: Untrusted direct peer with forged X-Forwarded-For
    scope_untrusted = {
        "type": "http",
        "method": "GET",
        "path": "/me",
        "headers": [(b"x-forwarded-for", b"203.0.113.195")],
        "client": ("198.51.100.5", 54321),  # Not in TRUSTED_PROXIES (127.0.0.1, ::1)
    }
    req_untrusted = Request(scope_untrusted)
    # Must return direct client IP, ignoring spoofed header
    assert get_client_ip(req_untrusted) == "198.51.100.5"

    # Case B: Trusted local proxy (127.0.0.1) forwarding client IP
    scope_trusted = {
        "type": "http",
        "method": "GET",
        "path": "/me",
        "headers": [(b"x-forwarded-for", b"203.0.113.195, 127.0.0.1")],
        "client": ("127.0.0.1", 54321),
    }
    req_trusted = Request(scope_trusted)
    assert get_client_ip(req_trusted) == "203.0.113.195"


# ── 2. Strict Repository URL & SSRF Protection Tests ─────────────────────────

def test_repo_url_ssrf_and_protocol_rejection():
    """Verify rejection of internal addresses, loopback, cloud metadata, and unsupported protocols."""
    from fastapi import HTTPException

    # SSRF: Localhost and internal loopback
    with pytest.raises(HTTPException) as exc:
        validate_github_repo_url("http://127.0.0.1/test/repo")
    assert exc.value.status_code == 400

    # SSRF: AWS metadata address
    with pytest.raises(HTTPException) as exc:
        validate_github_repo_url("http://169.254.169.254/latest/meta-data")
    assert exc.value.status_code == 400

    # Non-HTTPS protocol
    with pytest.raises(HTTPException) as exc:
        validate_github_repo_url("file:///etc/passwd")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        validate_github_repo_url("ssh://git@github.com/owner/repo")
    assert exc.value.status_code == 400

    # Insecure plaintext HTTP
    with pytest.raises(HTTPException) as exc:
        validate_github_repo_url("http://github.com/owner/repo")
    assert exc.value.status_code == 400

    # Non-GitHub host
    with pytest.raises(HTTPException) as exc:
        validate_github_repo_url("https://malicious-domain.com/owner/repo")
    assert exc.value.status_code == 400

    # Azure DevOps URL rejected explicitly
    with pytest.raises(HTTPException) as exc:
        validate_github_repo_url("https://dev.azure.com/org/proj/_git/repo")
    assert exc.value.status_code == 400


def test_repo_url_valid_github_canonicalization():
    """Verify valid GitHub URLs and slug shorthands are properly validated and normalized."""
    owner, slug, canonical = validate_github_repo_url("https://github.com/torvalds/linux")
    assert owner == "torvalds"
    assert slug == "linux"
    assert canonical == "https://github.com/torvalds/linux.git"

    owner2, slug2, canonical2 = validate_github_repo_url("octocat/Hello-World")
    assert owner2 == "octocat"
    assert slug2 == "Hello-World"
    assert canonical2 == "https://github.com/octocat/Hello-World.git"


# ── 3. Zip Slip & Archive Security Tests ─────────────────────────────────────

def test_zip_upload_rejection_of_symlink_and_traversal(monkeypatch):
    """Verify ZIP extraction rejects Zip Slip directory traversal and symlinks."""
    client = TestClient(app)

    uid = uuid.uuid4().hex[:8]
    dev_res = client.post("/auth/dev-login", json={"github_id": f"sec_test_user_{uid}", "github_username": f"sec_user_{uid}"})
    assert dev_res.status_code == 200
    token = dev_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create malicious ZIP with directory traversal (Zip Slip)
    slip_buf = io.BytesIO()
    with zipfile.ZipFile(slip_buf, "w") as zf:
        zf.writestr("../../etc/cron.d/evil", b"echo malicious")
    slip_buf.seek(0)

    res_slip = client.post(
        "/repos/upload",
        files={"file": ("slip.zip", slip_buf.getvalue(), "application/zip")},
        headers=headers,
    )
    assert res_slip.status_code == 400
    assert "Unsafe path" in res_slip.json()["detail"] or "traversal" in res_slip.json()["detail"].lower()

    # Create ZIP containing a symlink entry
    symlink_buf = io.BytesIO()
    with zipfile.ZipFile(symlink_buf, "w") as zf:
        zinfo = zipfile.ZipInfo("symlink_entry")
        zinfo.create_system = 3  # Unix
        zinfo.external_attr = 0o120777 << 16  # S_IFLNK
        zf.writestr(zinfo, "/etc/shadow")
    symlink_buf.seek(0)

    res_sym = client.post(
        "/repos/upload",
        files={"file": ("symlink.zip", symlink_buf.getvalue(), "application/zip")},
        headers=headers,
    )
    assert res_sym.status_code == 400
    assert "Symbolic links" in res_sym.json()["detail"] or "forbidden" in res_sym.json()["detail"].lower()


# ── 4. File Workspace Containment & Path Traversal ───────────────────────────

def test_file_content_path_traversal_blocked():
    """Verify GET /repos/{repo_id}/file-content prevents directory traversal."""
    client = TestClient(app)

    uid = uuid.uuid4().hex[:8]
    dev_res = client.post("/auth/dev-login", json={"github_id": f"sec_test_user2_{uid}", "github_username": f"sec_user2_{uid}"})
    assert dev_res.status_code == 200
    headers = {"Authorization": f"Bearer {dev_res.json()['token']}"}

    # Upload a legitimate minimal repository
    valid_buf = io.BytesIO()
    with zipfile.ZipFile(valid_buf, "w") as zf:
        zf.writestr("main.py", b"print('safe')\n")
    valid_buf.seek(0)

    upload_res = client.post(
        "/repos/upload",
        files={"file": ("valid.zip", valid_buf.getvalue(), "application/zip")},
        headers=headers,
    )
    assert upload_res.status_code == 201
    repo_id = upload_res.json()["repo_id"]

    # Traversal attempt with ..
    res_trav = client.get(
        f"/repos/{repo_id}/file-content?path=../../main.py",
        headers=headers,
    )
    assert res_trav.status_code == 400
    assert "path traversal" in res_trav.json()["detail"].lower()

    # Absolute path attempt
    res_abs = client.get(
        f"/repos/{repo_id}/file-content?path=/etc/passwd",
        headers=headers,
    )
    assert res_abs.status_code == 400


# ── 5. Session Secret & Dev-Login Production Gating ───────────────────────────

def test_dev_login_blocked_in_production(monkeypatch):
    """Verify /auth/dev-login is strictly blocked when ENVIRONMENT=production."""
    client = TestClient(app)

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOW_DEV_LOGIN", "false")

    res = client.post(
        "/auth/dev-login",
        json={"github_id": "attacker", "github_username": "attacker"},
    )
    assert res.status_code == 403
    assert "disabled in production" in res.json()["detail"]


def test_session_secret_production_enforcement(monkeypatch):
    """Verify RuntimeError is raised in production if SESSION_SECRET is missing or left as default."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    with pytest.raises(RuntimeError) as exc:
        _get_session_secret()
    assert "SESSION_SECRET must be set in production" in str(exc.value)

    monkeypatch.setenv("SESSION_SECRET", "codebrain-super-secret-session-key-2026")
    with pytest.raises(RuntimeError) as exc2:
        _get_session_secret()
    assert "Default hardcoded SESSION_SECRET is not permitted in production" in str(exc2.value)


# ── 6. Browser Security Headers ──────────────────────────────────────────────

def test_browser_security_headers_present():
    """Verify all standard browser security defense headers are attached."""
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200

    headers = res.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in headers
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "Permissions-Policy" in headers


# ── 7. Error Sanitization & Secret Redaction ─────────────────────────────────

def test_secret_redaction_and_host_path_scrubbing():
    """Verify secret credentials and local host paths are stripped from output."""
    mock_ghp = "gh" + "p_" + "123456789012345678901234567890123456"
    mock_aws = "AKIA" + "IOSFODNN7EXAMPLE"
    raw_text = (
        f"Found AWS key {mock_aws} and GitHub token {mock_ghp}. "
        "File located at C:\\Users\\Administrator\\projects\\secret.py"
    )
    redacted = redact_secrets(raw_text)
    sanitized = sanitize_host_paths(redacted)

    assert mock_aws not in sanitized
    assert "<REDACTED_AWS_KEY>" in sanitized
    assert mock_ghp not in sanitized
    assert "<REDACTED_GITHUB_TOKEN>" in sanitized
    assert "Administrator" not in sanitized
    assert "<HOST_USER_DIR>" in sanitized
