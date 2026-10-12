import os
import uuid
import time
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
from auth import create_session_token
from database import SessionLocal
from models import User, Repo
from codefix.sandbox import _build_sandbox_env
from terminals.manager import terminal_manager

client = TestClient(app)

def test_sandbox_environment_scrubbing():
    """Verify that host API keys and database secrets are never passed into sandbox execution."""
    test_env = {
        "NVIDIA_NIM_API_KEY": "secret-nvidia-token",
        "GITHUB_TOKEN": "gh" + "p_" + "supersecretgithubtoken",
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
        "PATH": "C:\\Windows\\System32;C:\\Program Files\\Python",
        "SYSTEMROOT": "C:\\Windows",
        "TEMP": "C:\\Windows\\Temp",
    }
    with patch.dict(os.environ, test_env, clear=True):
        clean_env = _build_sandbox_env(Path("C:\\temp\\isolated_repo"))
        
        # Critical secrets MUST NOT leak
        assert clean_env.get("NVIDIA_NIM_API_KEY") is None
        assert clean_env.get("GITHUB_TOKEN") is None
        assert "DATABASE_URL" not in clean_env
        
        # Safe keys must be preserved
        assert "PATH" in clean_env
        assert "SYSTEMROOT" in clean_env
        assert "TEMP" in clean_env
        assert "C:\\temp\\isolated_repo" in clean_env.get("PYTHONPATH", "")

def test_empty_patch_validation_endpoint():
    """Verify that an empty or missing patch does NOT crash with HTTP 422, but returns structured INVALID_PATCH."""
    db = SessionLocal()
    unique = uuid.uuid4().hex[:8]
    user_id = f"test-u-{unique}"
    repo_id = f"test-r-{unique}"
    user = User(id=user_id, github_id=f"gh-{unique}", github_username=f"u_{unique}")
    repo = Repo(id=repo_id, user_id=user_id, name=f"R_{unique}", source_type="upload")
    db.add(user)
    db.add(repo)
    db.commit()
    db.close()

    token = create_session_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "repo_id": repo_id,
        "file_path": "app/main.py",
        "diff": "",
        "patched_content": None
    }
    response = client.post(f"/repos/{repo_id}/validate-patch", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["passed"] is False
    assert data["failure_type"] == "INVALID_PATCH"
    assert "Provide either 'diff'" in data["error"]

def test_whitespace_patch_validation_endpoint():
    """Whitespace-only diff should also return INVALID_PATCH cleanly."""
    db = SessionLocal()
    unique = uuid.uuid4().hex[:8]
    user_id = f"test-u-{unique}"
    repo_id = f"test-r-{unique}"
    user = User(id=user_id, github_id=f"gh-{unique}", github_username=f"u_{unique}")
    repo = Repo(id=repo_id, user_id=user_id, name=f"R_{unique}", source_type="upload")
    db.add(user)
    db.add(repo)
    db.commit()
    db.close()

    token = create_session_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "repo_id": repo_id,
        "file_path": "app/main.py",
        "diff": "   \n\t  \n  ",
        "patched_content": ""
    }
    response = client.post(f"/repos/{repo_id}/validate-patch", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["passed"] is False
    assert data["failure_type"] == "INVALID_PATCH"

def test_multi_terminal_session_isolation():
    """Verify multiple independent terminal sessions run concurrently with isolated buffers and processes."""
    manager = terminal_manager
    repo_id = "test-concurrent-repo"

    # Create session 1 and session 2
    sess1 = manager.create_session("dev_user", repo_id, "Frontend Server", subpath="frontend")
    sess2 = manager.create_session("dev_user", repo_id, "Backend Server", subpath="backend")

    assert sess1.id != sess2.id
    assert sess1.title == "Frontend Server"
    assert sess2.title == "Backend Server"

    # Run independent commands
    sess1.execute_command("python -c \"print('Hello from Frontend Terminal')\"")
    sess2.execute_command("python -c \"print('Hello from Backend Terminal')\"")

    # Wait for completion
    time.sleep(1.0)

    lines1, _ = sess1.get_output(0)
    lines2, _ = sess2.get_output(0)
    text1 = [l["text"] for l in lines1]
    text2 = [l["text"] for l in lines2]

    # Output isolation: sess1 should have Hello from Frontend, NOT Hello from Backend
    assert any("Hello from Frontend Terminal" in t for t in text1)
    assert not any("Hello from Backend Terminal" in t for t in text1)

    assert any("Hello from Backend Terminal" in t for t in text2)
    assert not any("Hello from Frontend Terminal" in t for t in text2)

    # Cleanup
    manager.close_session(sess1.id, "dev_user")
    manager.close_session(sess2.id, "dev_user")
    assert manager.get_session(sess1.id, "dev_user") is None
    assert manager.get_session(sess2.id, "dev_user") is None

def test_terminal_api_endpoints():
    """Verify REST API endpoints for terminal lifecycle with auth."""
    db = SessionLocal()
    unique = uuid.uuid4().hex[:8]
    user_id = f"test-u-{unique}"
    repo_id = f"test-r-{unique}"
    user = User(id=user_id, github_id=f"gh-{unique}", github_username=f"u_{unique}")
    repo = Repo(id=repo_id, user_id=user_id, name=f"R_{unique}", source_type="upload")
    db.add(user)
    db.add(repo)
    db.commit()
    db.close()

    token = create_session_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Create session via POST /repos/{repo_id}/terminals
    res_create = client.post(f"/repos/{repo_id}/terminals", json={"title": "Test Term"}, headers=headers)
    assert res_create.status_code in (200, 201)
    created = res_create.json()
    session_id = created["id"]
    assert created["title"] == "Test Term"

    # 2. List sessions via GET /repos/{repo_id}/terminals
    res_list = client.get(f"/repos/{repo_id}/terminals", headers=headers)
    assert res_list.status_code == 200
    sessions = res_list.json()
    assert any(s["id"] == session_id for s in sessions)

    # 3. Execute command via POST /repos/{repo_id}/terminals/{session_id}/command
    res_cmd = client.post(
        f"/repos/{repo_id}/terminals/{session_id}/command",
        json={"command": "python -c \"print('TERMINAL_API_OK')\""},
        headers=headers
    )
    assert res_cmd.status_code == 200

    # 4. Read output lines via GET /repos/{repo_id}/terminals/{session_id}
    time.sleep(1.0)
    res_read = client.get(f"/repos/{repo_id}/terminals/{session_id}", headers=headers)
    assert res_read.status_code == 200
    term_data = res_read.json()
    assert any("TERMINAL_API_OK" in l["text"] for l in term_data.get("lines", []))

    # 5. Delete session via DELETE /repos/{repo_id}/terminals/{session_id}
    res_del = client.delete(f"/repos/{repo_id}/terminals/{session_id}", headers=headers)
    assert res_del.status_code == 200


def test_terminal_cd_navigation_and_dynamic_prompt(tmp_path):
    """Verify that 'cd' navigates into subdirectories, updates prompt, and preserves state."""
    repo_root = tmp_path / "my_project"
    repo_root.mkdir()
    frontend_dir = repo_root / "frontend"
    frontend_dir.mkdir()
    backend_dir = repo_root / "backend"
    backend_dir.mkdir()

    sess = terminal_manager.create_session("u1", "r1", title="test_cd", subpath=None)
    sess.repo_root = repo_root
    sess.cwd = repo_root

    # Initial prompt is root (CodeBrain)
    assert "CodeBrain>" in sess.prompt or "CodeBrain$" in sess.prompt

    # Navigate into frontend
    sess.execute_command("cd frontend")
    assert sess.cwd == frontend_dir
    assert "CodeBrain\\frontend>" in sess.prompt or "CodeBrain/frontend$" in sess.prompt

    # Navigate to parent (..)
    sess.execute_command("cd ..")
    assert sess.cwd == repo_root
    assert sess.prompt.endswith("CodeBrain>") or sess.prompt.endswith("CodeBrain$ ")

    # Cleanup
    terminal_manager.close_session(sess.id, "u1")


def test_terminal_cd_traversal_blocked(tmp_path):
    """Verify that attempting to cd outside repository root is blocked."""
    repo_root = tmp_path / "restricted_repo"
    repo_root.mkdir()

    sess = terminal_manager.create_session("u1", "r_sec", title="test_sec")
    sess.repo_root = repo_root
    sess.cwd = repo_root

    # Attempting to navigate above repo root
    sess.execute_command("cd ..")
    assert sess.cwd == repo_root

    # Attempting path traversal ../../
    sess.execute_command("cd ../../")
    assert sess.cwd == repo_root

    # Cleanup
    terminal_manager.close_session(sess.id, "u1")


def test_terminal_cls_clears_buffer():
    """Verify that cls or clear empties the session output buffer."""
    sess = terminal_manager.create_session("u1", "r_cls", title="test_cls")
    sess.append_output("line 1", stream="stdout")
    sess.append_output("line 2", stream="stdout")
    assert len(sess.output_buffer) >= 2

    sess.execute_command("cls")
    assert len(sess.output_buffer) == 0

    terminal_manager.close_session(sess.id, "u1")


def test_sandbox_dynamic_pythonpath_discovery(tmp_path):
    """Verify that monorepo structures (e.g. backend/app, src/server) are discovered to avoid ModuleNotFoundError."""
    from codefix.sandbox import _discover_pythonpath_entries
    repo_root = tmp_path / "monorepo"
    repo_root.mkdir()
    backend_app = repo_root / "backend" / "app"
    backend_app.mkdir(parents=True)
    (backend_app / "__init__.py").write_text("# init", encoding="utf-8")
    (backend_app / "models.py").write_text("class Item: pass", encoding="utf-8")

    entries = _discover_pythonpath_entries(repo_root)
    # Both backend and backend/app should be discoverable
    assert any("backend" in e for e in entries)
    assert any("app" in e for e in entries)


def test_cleanup_stale_sessions():
    """Verify that terminal_manager purges stale or closed sessions."""
    sess1 = terminal_manager.create_session("u_stale", "r_stale", title="stale1")
    sess2 = terminal_manager.create_session("u_stale", "r_stale", title="stale2")
    sess1.last_activity = time.time() - 4000  # Older than 1 hour

    cleaned = terminal_manager.cleanup_stale_sessions(max_idle_seconds=3600)
    assert cleaned >= 1
    assert terminal_manager.get_session(sess1.id, "u_stale") is None

    # sess2 was active recently so it should still exist
    assert terminal_manager.get_session(sess2.id, "u_stale") is not None
    terminal_manager.close_session(sess2.id, "u_stale")


def test_concurrent_long_running_processes_independent_termination():
    """Verify two long-running processes run concurrently and stopping one leaves the other alive."""
    sess1 = terminal_manager.create_session("u_conc", "r_conc", title="Frontend Dev")
    sess2 = terminal_manager.create_session("u_conc", "r_conc", title="Backend API")

    # Start two long-running python loops simulating servers
    sess1.execute_command("python -c \"import time; print('FRONTEND_STARTED'); time.sleep(10)\"")
    sess2.execute_command("python -c \"import time; print('BACKEND_STARTED'); time.sleep(10)\"")

    time.sleep(1.0)
    assert sess1.status == "running"
    assert sess2.status == "running"

    # Stop sess1
    sess1.stop_process()
    assert sess1.status == "idle"

    # Verify sess2 is STILL RUNNING!
    assert sess2.status == "running"

    # Clean up sess2
    sess2.stop_process()
    assert sess2.status == "idle"

    terminal_manager.close_session(sess1.id, "u_conc")
    terminal_manager.close_session(sess2.id, "u_conc")


