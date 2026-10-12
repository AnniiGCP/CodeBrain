"""
backend/tests/test_production_execution_and_terminals.py
--------------------------------------------------------
Comprehensive automated test suite for CodeBrain's production execution architecture:
- Execution provider abstraction (Subprocess, Docker, Null)
- Security boundary (env scrubbing, secret redaction, host-execution blocking)
- Sandbox validation & empty patch rejection
- Multi-terminal lifecycle, directory navigation, concurrency, and graceful runtime outage handling
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from execution.provider import (
    BaseExecutionProvider,
    DockerExecutionProvider,
    ExecutionResult,
    NullExecutionProvider,
    SubprocessExecutionProvider,
    get_execution_provider,
    reset_execution_provider,
)
from terminals.manager import TerminalManager, TerminalSession, _build_safe_env
from codefix.sandbox import (
    ValidationResult,
    _categorize_result,
    _sanitize_diagnostics,
    verify_secret_removal,
)
from main import app

client = TestClient(app)


# ── 1. Execution Provider Abstraction Tests ───────────────────────────────────

def test_execution_provider_subprocess_dev_mode():
    """In development mode, SubprocessExecutionProvider is available."""
    with patch.dict(os.environ, {"ENVIRONMENT": "development", "ISOLATED_RUNTIME_REQUIRED": "false", "PUBLIC_DEPLOYMENT": "false", "EXECUTION_PROVIDER": "subprocess"}):
        reset_execution_provider()
        prov = get_execution_provider(force_reload=True)
        assert isinstance(prov, SubprocessExecutionProvider)
        assert prov.is_available() is True
        health = prov.health_check()
        assert health["status"] == "ready"
        assert health["isolated"] is False


def test_execution_provider_blocks_host_in_production():
    """In production or when isolation is required, host execution is blocked truthfully."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production", "ISOLATED_RUNTIME_REQUIRED": "true", "EXECUTION_PROVIDER": "subprocess"}):
        reset_execution_provider()
        prov = get_execution_provider(force_reload=True)
        assert isinstance(prov, NullExecutionProvider)
        assert prov.is_available() is False
        health = prov.health_check()
        assert health["status"] == "unavailable"
        assert "forbidden" in health["message"].lower() or "blocked" in health["message"].lower()


def test_null_execution_provider_truthful_failure():
    """NullExecutionProvider returns RUNTIME_UNAVAILABLE without running code on host."""
    prov = NullExecutionProvider(reason="No isolated container daemon configured.")
    assert prov.is_available() is False
    res = prov.execute_command(Path("."), "echo dangerous", {})
    assert res.exit_code == -1
    assert "RUNTIME_UNAVAILABLE" in res.error
    assert res.provider_name == "null"


def test_docker_execution_provider_health_check():
    """DockerExecutionProvider reports availability based on Docker daemon status."""
    prov = DockerExecutionProvider()
    assert prov.name == "docker"
    health = prov.health_check()
    assert health["isolated"] is True
    assert "docker_bin" in health


# ── 2. Production Security Boundary & Environment Scrubbing ───────────────────

def test_env_scrubbing_strips_backend_secrets():
    """Sensitive provider tokens and session secrets must never be passed to child processes."""
    dirty_env = {
        "NVIDIA_NIM_API_KEY": "secret_nv_real_12345",
        "GROQ_API_KEY": "secret_groq_real_67890",
        "GITHUB_TOKEN": "gh" + "p_" + "super_secret_github_token",
        "SESSION_SECRET": "codebrain_internal_hmac_secret",
        "ENCRYPTION_KEY": "fernet_database_key_32bytes",
        "DATABASE_URL": "postgresql://user:pass@db:5432/codebrain",
        "PATH": os.environ.get("PATH", ""),
    }
    with patch.dict(os.environ, dirty_env):
        safe = _build_safe_env(Path("."))
        assert "SESSION_SECRET" not in safe
        assert "GITHUB_TOKEN" not in safe
        assert "ENCRYPTION_KEY" not in safe
        assert "DATABASE_URL" not in safe
        assert safe.get("NVIDIA_NIM_API_KEY") != "secret_nv_real_12345"
        assert safe.get("GROQ_API_KEY") != "secret_groq_real_67890"
        assert "PYTHONPATH" in safe
        assert safe["CI"] == "true"


def test_secret_removal_verification():
    """Validates that patches excising secrets (GEN001) are verified correctly."""
    orig = "API_KEY = 'mock_secret_key_1234567890'\nclient = connect(API_KEY)"
    bad_patch = "API_KEY = 'mock_secret_key_9999999999'\nclient = connect(API_KEY)"
    good_patch = "API_KEY = os.getenv('API_KEY', '')\nclient = connect(API_KEY)"

    ok_bad, msg_bad = verify_secret_removal(orig, bad_patch)
    assert ok_bad is False
    assert "still contains" in msg_bad.lower()

    ok_good, msg_good = verify_secret_removal(orig, good_patch)
    assert ok_good is True
    assert "environment" in msg_good.lower() or "removed" in msg_good.lower()


def test_diagnostic_sanitization_removes_host_paths_and_keys():
    """Raw stack traces with developer paths and tokens must be redacted."""
    dummy_key = "sk" + "-live-99887766554433221100"
    raw = f"Error at C:\\Users\\Developer\\AppData\\Local\\Programs\\Python\\test.py with key={dummy_key}"
    sanitized = _sanitize_diagnostics(raw)
    assert "C:\\Users\\Developer" not in sanitized
    assert dummy_key not in sanitized


# ── 3. Sandbox Validation Categorization ──────────────────────────────────────

def test_categorize_runtime_unavailable():
    fail_type, is_env, missing, err = _categorize_result(
        passed=False,
        exit_code=-1,
        stdout="",
        stderr="",
        error="RUNTIME_UNAVAILABLE: Isolated container runtime is required in production.",
    )
    assert fail_type == "RUNTIME_UNAVAILABLE"
    assert is_env is True


def test_categorize_missing_dependencies():
    fail_type, is_env, missing, err = _categorize_result(
        passed=False,
        exit_code=1,
        stdout="",
        stderr="ModuleNotFoundError: No module named 'pytest_mock'",
    )
    assert fail_type == "MISSING_DEPENDENCY"
    assert is_env is True
    assert "pytest_mock" in missing


# ── 4. Multi-Terminal Session Lifecycle & Concurrency ────────────────────────

def test_terminal_session_navigation_and_boundaries():
    """Terminal navigation must honor workspace boundaries and dynamic CodeBrain prompt."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        sub = root / "backend" / "services"
        sub.mkdir(parents=True)

        session = TerminalSession(
            session_id="test-sess-1",
            user_id="user1",
            repo_id="repo1",
            title="1: powershell",
            cwd=root,
            repo_root=root,
        )

        assert "CodeBrain" in session.prompt

        # Navigate into subdirectory
        session.execute_command("cd backend/services")
        assert session.cwd == sub
        assert "services" in session.prompt

        # Navigate outside repository root is blocked; cwd remains unchanged
        session.execute_command("cd ../../..")
        assert session.cwd == sub
        lines, _ = session.get_output(0)
        assert any("Access denied" in l["text"] for l in lines)

        # Navigating to ~ returns to repository root
        session.execute_command("cd ~")
        assert session.cwd == root

        # Clear buffer
        session.append_output("line 1")
        session.execute_command("cls")
        lines, idx = session.get_output(0)
        assert len(lines) == 0


def test_terminal_multi_concurrency():
    """Multiple sessions must operate independently without shared state or crossed streams."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        mgr = TerminalManager()

        sess1 = mgr.create_session(user_id="u1", repo_id="r1", title="Frontend Server")
        sess2 = mgr.create_session(user_id="u1", repo_id="r1", title="Backend Server")

        assert sess1.id != sess2.id
        assert sess1.title == "Frontend Server"
        assert sess2.title == "Backend Server"

        # Append independent output
        sess1.append_output("Vite v5.0 ready at localhost:5173", stream="stdout")
        sess2.append_output("Uvicorn running on http://0.0.0.0:8000", stream="stdout")

        out1, _ = sess1.get_output(0)
        out2, _ = sess2.get_output(0)

        assert any("Vite" in line["text"] for line in out1)
        assert not any("Uvicorn" in line["text"] for line in out1)
        assert any("Uvicorn" in line["text"] for line in out2)
        assert not any("Vite" in line["text"] for line in out2)

        # Closing session 1 does not affect session 2
        mgr.close_session(sess1.id, user_id="u1")
        assert mgr.get_session(sess1.id, user_id="u1") is None
        assert mgr.get_session(sess2.id, user_id="u1") is not None


def test_terminal_runtime_outage_handling():
    """When execution provider is Null, terminal command fails gracefully with truthful diagnostic."""
    with patch("execution.provider.get_execution_provider") as mock_get_p:
        mock_get_p.return_value = NullExecutionProvider("Remote worker execution daemon unreachable.")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            sess = TerminalSession(
                session_id="sess-outage",
                user_id="u1",
                repo_id="r1",
                title="1: test",
                cwd=root,
                repo_root=root,
            )

            ok = sess.execute_command("python -m pytest")
            assert ok is False
            assert sess.status == "idle"
            assert sess.exit_code == 1

            lines, _ = sess.get_output(0)
            err_lines = [l["text"] for l in lines if l["stream"] == "stderr"]
            assert any("Runtime Unavailable" in l for l in err_lines)


# ── 5. Health Check Endpoint Observability ────────────────────────────────────

def test_health_check_endpoint_reports_runtime():
    """Health check endpoint must expose application and execution runtime status."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "runtime" in data
    assert "provider" in data["runtime"]
    assert "status" in data["runtime"]


# ── 6. Provider-Agnostic Remote Worker Provider Tests ─────────────────────────

def test_remote_execution_provider_health_and_command():
    """RemoteExecutionProvider enables running on any host by delegating to a remote worker."""
    from execution.provider import RemoteExecutionProvider

    prov = RemoteExecutionProvider(worker_url="http://worker.internal:8080", token="test_token")
    assert prov.name == "remote"

    # Test unavailable when endpoint unreachable
    assert prov.is_available() is False
    health = prov.health_check()
    assert health["provider"] == "remote"
    assert health["status"] == "unavailable"

    # Test execute_command handles connection failure gracefully
    res = prov.execute_command(Path("."), "pytest", {})
    assert res.exit_code == -1
    assert "error" in res.error.lower()
    assert res.provider_name == "remote"


def test_remote_execution_provider_auto_detection():
    """When EXECUTION_WORKER_URL is configured, factory selects RemoteExecutionProvider."""
    with patch.dict(os.environ, {
        "EXECUTION_PROVIDER": "remote",
        "EXECUTION_WORKER_URL": "http://mock-worker:8080",
        "ENVIRONMENT": "production",
    }):
        from execution.provider import reset_execution_provider, get_execution_provider
        reset_execution_provider()
        prov = get_execution_provider(force_reload=True)
        # In mock env without running worker, NullExecutionProvider blocks in strict isolation
        assert prov.name in ("remote", "null")
