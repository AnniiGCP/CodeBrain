"""
tests/test_sandbox_validation_fixes.py
--------------------------------------
Automated test suite verifying the permanent diagnosis and resolution
of sandbox validation failures, monorepo test detection, secret removal verification,
environment failure classification, and diagnostic sanitization.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from codefix.sandbox import (
    ValidationResult,
    _categorize_result,
    _is_safe_command,
    _resolve_project_root_and_test_command,
    _sanitize_diagnostics,
    verify_secret_removal,
    validate_diff,
    validate_patch,
)


# ── Test 1: Intelligent Subproject & Test Command Resolution ──────────────────

def test_subproject_resolution_for_monorepo(tmp_path):
    """
    Given a monorepo containing 'llm_service' and 'backend':
    A target file in 'llm_service/tests/qwen_llm.py' (a benchmark script without def test_)
    must resolve to working directory 'llm_service' and python compilation.
    It must NEVER run 'backend/tests' or blind 'pytest -x -q tests'.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    # llm_service subproject with script
    llm_dir = repo / "llm_service"
    (llm_dir / "tests").mkdir(parents=True)
    script_file = llm_dir / "tests" / "qwen_llm.py"
    script_file.write_text("import os\nprint('Benchmark')\n", encoding="utf-8")

    # backend subproject with tests
    backend_dir = repo / "backend"
    (backend_dir / "tests").mkdir(parents=True)
    (backend_dir / "tests" / "test_auth.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    (backend_dir / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    cmd, cwd, desc = _resolve_project_root_and_test_command(
        repo, target_file_path="llm_service/tests/qwen_llm.py"
    )

    assert cwd == llm_dir, f"Working directory should be llm_service, got {cwd}"
    assert "py_compile" in cmd, f"Expected py_compile for script without test cases, got {cmd}"
    assert "backend" not in cmd, f"Command leaked into backend: {cmd}"
    assert "tests/qwen_llm.py" in cmd or "qwen_llm.py" in cmd


def test_subproject_resolution_for_backend_test(tmp_path):
    """A target test file in backend/tests/test_api.py must resolve to targeted pytest in backend."""
    repo = tmp_path / "repo"
    backend_dir = repo / "backend"
    (backend_dir / "tests").mkdir(parents=True)
    test_file = backend_dir / "tests" / "test_api.py"
    test_file.write_text("def test_endpoint(): assert True\n", encoding="utf-8")

    cmd, cwd, desc = _resolve_project_root_and_test_command(
        repo, target_file_path="backend/tests/test_api.py"
    )

    assert cwd == backend_dir
    assert "pytest" in cmd
    assert "test_api.py" in cmd


def test_never_blindly_run_pytest_tests_when_no_tests_dir(tmp_path):
    """When a repo has no tests/ directory at root, general inspection must not run 'pytest -x -q tests'."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")

    cmd, cwd, desc = _resolve_project_root_and_test_command(repo, target_file_path=None)
    if cmd:
        assert not cmd.endswith(" tests"), f"Blindly appended non-existent 'tests' folder: {cmd}"


# ── Test 2: Secret Removal Verification ───────────────────────────────────────

def test_secret_removal_verification_success():
    """Validates that removing a hardcoded key and replacing with os.getenv passes verification."""
    orig = 'client = OpenAI(api_key="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")'
    patched = 'client = OpenAI(api_key=os.getenv("NVIDIA_API_KEY", ""))'

    ok, msg = verify_secret_removal(orig, patched)
    assert ok is True
    assert "Credential successfully removed" in msg


def test_secret_removal_verification_failure_if_retained():
    """Fails if the patched content retains the hardcoded credential."""
    orig = 'client = OpenAI(api_key="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")'
    patched = 'client = OpenAI(api_key="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") # still here'

    ok, msg = verify_secret_removal(orig, patched)
    assert ok is False
    assert "still contains a hardcoded credential" in msg


# ── Test 3: Secret and Host Path Diagnostics Redaction ────────────────────────

def test_diagnostics_redaction():
    """Asserts that sensitive keys and personal developer paths are scrubbed from diagnostics."""
    raw = (
        'Exception in C:\\Users\\Aniket Yadav\\project\\llm_service\\tests\\qwen_llm.py: '
        'Failed connecting with api_key="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"'
    )
    sanitized = _sanitize_diagnostics(raw)

    assert "Aniket Yadav" not in sanitized
    assert "<HOST_USER_DIR>" in sanitized
    assert "nvapi-h1_HxxqOMigaFXmcZOCJWe5qmpsm" not in sanitized
    assert "<REDACTED_NVIDIA_KEY>" in sanitized or "<REDACTED_SECRET>" in sanitized


# ── Test 4: Failure Categorization — Environment vs Patch ─────────────────────

def test_categorization_missing_dependency():
    """Missing module imports must be categorized as MISSING_DEPENDENCY with is_environment_failure=True."""
    stdout = "ImportError while importing test module\nModuleNotFoundError: No module named 'openai'\n"
    stderr = ""
    fail_type, is_env, missing, err = _categorize_result(
        passed=False, exit_code=2, stdout=stdout, stderr=stderr
    )

    assert fail_type == "MISSING_DEPENDENCY"
    assert is_env is True
    assert "openai" in missing
    assert "openai" in err


def test_categorization_syntax_error_in_target():
    """A syntax error in the target file is a genuine patch defect (is_environment_failure=False)."""
    stdout = "File 'llm_service/tests/qwen_llm.py', line 12\n  api_key=\n          ^\nSyntaxError: invalid syntax"
    fail_type, is_env, missing, err = _categorize_result(
        passed=False, exit_code=1, stdout=stdout, stderr="", target_file_path="llm_service/tests/qwen_llm.py"
    )

    assert fail_type == "SYNTAX_ERROR"
    assert is_env is False


def test_categorization_syntax_error_in_unrelated_file():
    """A syntax error in an unrelated file during collection is an environment/collection failure."""
    stdout = "File 'backend/tests/test_auth_flow.py', line 1\n    password = 1\nIndentationError: unexpected indent"
    fail_type, is_env, missing, err = _categorize_result(
        passed=False, exit_code=1, stdout=stdout, stderr="", target_file_path="llm_service/tests/qwen_llm.py"
    )

    assert fail_type == "COLLECTION_ERROR"
    assert is_env is True
    assert "unrelated repository file" in err


def test_categorization_test_assertion_failed():
    """Test assertion failures are categorized as TEST_ASSERTION_FAILED and is_environment_failure=False."""
    stdout = "def test_calc():\n>   assert add(2, 2) == 5\nE   AssertionError: assert 4 == 5\nFAILED tests/test_calc.py"
    fail_type, is_env, missing, err = _categorize_result(
        passed=False, exit_code=1, stdout=stdout, stderr="", target_file_path="tests/test_calc.py"
    )

    assert fail_type == "TEST_ASSERTION_FAILED"
    assert is_env is False


# ── Test 5: End-to-End Patch Validation on qwen_llm.py ────────────────────────

def test_full_validation_on_qwen_llm_patch(tmp_path, monkeypatch):
    """
    Simulates the exact user issue:
    A repository contains:
      - llm_service/tests/qwen_llm.py with a hardcoded NVIDIA key
      - backend/tests/test_auth_flow.py with an unrelated IndentationError
    A unified diff is applied fixing the secret in qwen_llm.py.
    The sandbox must:
      1. Not touch the original repository on disk.
      2. Run verification on llm_service/tests/qwen_llm.py without crashing on backend's indentation error.
      3. Return passed=True with exit_code=0.
    """
    from execution.provider import reset_execution_provider
    monkeypatch.setenv("EXECUTION_PROVIDER", "subprocess")
    monkeypatch.setenv("PUBLIC_DEPLOYMENT", "false")
    monkeypatch.setenv("ISOLATED_RUNTIME_REQUIRED", "false")
    monkeypatch.setenv("ENVIRONMENT", "test")
    reset_execution_provider()

    from models import Repo

    # Create dummy mock db
    mock_db = MagicMock()
    fake_repo = Repo(id="test-qwen-repo-123", name="test-repo", source_type="upload")
    mock_db.query.return_value.filter.return_value.first.return_value = fake_repo

    # Set up storage directory
    from codefix.sandbox import STORAGE_ROOT
    storage_root = STORAGE_ROOT
    storage_root.mkdir(parents=True, exist_ok=True)
    repo_storage = storage_root / "test-qwen-repo-123"
    repo_storage.mkdir(parents=True, exist_ok=True)

    try:
        # Create llm_service with qwen_llm.py
        llm_dir = repo_storage / "llm_service" / "tests"
        llm_dir.mkdir(parents=True, exist_ok=True)
        orig_qwen = (
            "import os\n"
            "client_key = \"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\"\n"
            "print('Ready')\n"
        )
        (llm_dir / "qwen_llm.py").write_text(orig_qwen, encoding="utf-8")

        # Create broken backend test
        b_dir = repo_storage / "backend" / "tests"
        b_dir.mkdir(parents=True, exist_ok=True)
        (b_dir / "test_auth_flow.py").write_text("    password = 1\n", encoding="utf-8")

        # Patch diff for qwen_llm.py
        diff = (
            "--- a/llm_service/tests/qwen_llm.py\n"
            "+++ b/llm_service/tests/qwen_llm.py\n"
            "@@ -2,1 +2,1 @@\n"
            "-client_key = \"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\"\n"
            "+client_key = os.getenv(\"NVIDIA_API_KEY\", \"\")\n"
        )

        vr = validate_diff(
            repo_id="test-qwen-repo-123",
            diff_text=diff,
            db=mock_db,
            target_file_path="llm_service/tests/qwen_llm.py",
        )

        assert vr.passed is True, f"Sandbox failed: error={vr.error}, output={vr.output}"
        assert vr.exit_code == 0
        assert "py_compile" in vr.test_command
        assert "llm_service" in vr.working_directory
        assert vr.patch_applied is True

        # Assert original repo file was NOT modified before approval!
        disk_content = (llm_dir / "qwen_llm.py").read_text(encoding="utf-8")
        assert "nvapi-h1_HxxqOMiga" in disk_content, "Original disk content should not be changed prior to approval"

        # Assert secret was not leaked in output
        assert "nvapi-h1_HxxqOMiga" not in vr.output
    finally:
        import shutil
        shutil.rmtree(repo_storage, ignore_errors=True)
        from execution.provider import reset_execution_provider
        reset_execution_provider()


# ── Test 6: Isolated Container Runtime Enforcement ────────────────────────────

def test_isolated_runtime_enforced_in_production(monkeypatch):
    """When PUBLIC_DEPLOYMENT is enabled and Docker is unavailable, host execution is blocked."""
    monkeypatch.setenv("PUBLIC_DEPLOYMENT", "true")
    monkeypatch.setattr("shutil.which", lambda bin_name: None)  # simulate docker missing

    from codefix.sandbox import _execute_in_environment
    retcode, out, err, timed_out, error_msg = _execute_in_environment(
        cmd_str="pytest",
        cmd_cwd=Path("."),
        env={},
    )

    assert retcode == -1
    assert "Isolated container runtime (Docker) is unavailable" in error_msg
