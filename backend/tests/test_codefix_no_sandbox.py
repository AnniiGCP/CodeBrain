"""
backend/tests/test_codefix_no_sandbox.py
----------------------------------------
Test suite validating that Code Fix workflow no longer invokes sandbox execution,
pytest, build, runtime, or credential checks, while safely validating patch format
and writing changes.
"""
import os
import sys
import uuid
import shutil
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
from codefix.patch_safety import (
    validate_patch_format_and_safety,
    apply_patch_safely,
    VALIDATION_SKIPPED_NOTICE,
)

client = TestClient(app)

SAMPLE_DIFF = """--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def compute(x):
-    return x - 10
+    return x + 10
"""


@pytest.fixture
def repo_env(tmp_path):
    init_db()
    with SessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            github_id=f"gh_{uuid.uuid4().hex[:8]}",
            github_username="no_sandbox_tester",
            preferred_ai_provider="apinex",
        )
        db.add(user)
        db.commit()

        repo = Repo(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name="test_no_sandbox_repo",
            source_type="upload",
            pipeline_status="DONE",
        )
        db.add(repo)
        db.commit()

        # Create physical repo storage directory
        storage_repo_dir = backend_root / "storage" / repo.id / "src"
        storage_repo_dir.mkdir(parents=True, exist_ok=True)
        calc_file = storage_repo_dir / "calculator.py"
        calc_file.write_text("def compute(x):\n    return x - 10\n", encoding="utf-8")

        rf = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo.id,
            path="calculator.py",
            language="python",
            size=len(calc_file.read_text()),
            content_hash="hcalc",
        )
        db.add(rf)
        db.commit()

        sym = Symbol(
            file_id=rf.id,
            repo_id=repo.id,
            symbol_type="function",
            name="compute",
            source_code="def compute(x):\n    return x - 10\n",
        )
        db.add(sym)
        db.commit()

        err = ErrorReport(
            id=str(uuid.uuid4()),
            repo_id=repo.id,
            symbol_id=None,
            rule_id="CALC001",
            severity="error",
            message="Subtraction error detected",
            file_path="calculator.py",
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
        "repo_dir": storage_repo_dir,
        "calc_file": calc_file,
    }

    # Clean up storage folder
    try:
        shutil.rmtree(backend_root / "storage" / r_id, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def mock_explanation():
    with patch("errordetection.suggestion._generate_explanation", return_value="Calculated subtraction bug."):
        yield


def test_1_valid_patch_generated_and_applied_without_sandbox(repo_env):
    """Case 1 & 2: Valid patch generated & applied without sandbox; validate_diff is NEVER called."""
    r_id = repo_env["repo_id"]
    e_id = repo_env["error_id"]
    headers = repo_env["headers"]

    from ai.issue_fix_router import IssueFixResult

    mock_fix_result = IssueFixResult(
        diff=SAMPLE_DIFF,
        model="free/gpt-6-luna",
        model_display_name="GPT-6 Luna (Free)",
        provider="apinex",
        fallback_used=False,
        fix_attribution="Fixed using APInex GPT-6 Luna",
        attempts=[{"provider": "apinex", "success": True}],
        raw_response=SAMPLE_DIFF,
    )

    with patch("ai.issue_fix_router.route_issue_fix", return_value=mock_fix_result), \
         patch("codefix.sandbox.validate_diff") as mock_validate_diff, \
         patch("codefix.sandbox.validate_patch") as mock_validate_patch:

        # Step 1: Generate fix
        gen_resp = client.post(f"/repos/{r_id}/errors/{e_id}/generate-fix", headers=headers)
        assert gen_resp.status_code == 200, gen_resp.text
        gen_data = gen_resp.json()

        assert gen_data["passed"] is True
        assert gen_data["fix_status"] == "READY_TO_APPLY"
        assert gen_data["patch_status"] == "PATCH_GENERATED"
        assert gen_data["validation_status"] == "NOT_RUN"
        assert gen_data["validation_skipped"] is True
        assert VALIDATION_SKIPPED_NOTICE in gen_data["validation_notice"]
        assert gen_data["changed_files"] == ["calculator.py"]

        # CRITICAL: sandbox validation was NOT called
        mock_validate_diff.assert_not_called()
        mock_validate_patch.assert_not_called()

        # Step 2: Apply fix
        apply_resp = client.post(f"/repos/{r_id}/errors/{e_id}/apply-fix", headers=headers)
        assert apply_resp.status_code == 200, apply_resp.text
        apply_data = apply_resp.json()

        assert apply_data["passed"] is True
        assert apply_data["fix_status"] == "APPLIED_LOCAL"
        assert apply_data["patch_status"] == "FIX_APPLIED"
        assert apply_data["validation_status"] == "NOT_RUN"
        assert apply_data["validation_skipped"] is True
        assert "calculator.py" in apply_data["changed_files"]

        # Confirm file on disk was actually updated
        updated_content = repo_env["calc_file"].read_text(encoding="utf-8")
        assert "return x + 10" in updated_content

        # Sandbox was STILL never called
        mock_validate_diff.assert_not_called()
        mock_validate_patch.assert_not_called()


def test_2_sandbox_validation_would_have_failed_syntax_error(repo_env):
    """Case 2: Even if sandbox would fail with SYNTAX_ERROR, code fix flow succeeds because sandbox is bypassed."""
    r_id = repo_env["repo_id"]
    e_id = repo_env["error_id"]
    headers = repo_env["headers"]

    from ai.issue_fix_router import IssueFixResult

    mock_fix_result = IssueFixResult(
        diff=SAMPLE_DIFF,
        model="free/gpt-6-luna",
        model_display_name="GPT-6 Luna (Free)",
        provider="apinex",
        fallback_used=False,
        fix_attribution="Fixed using APInex GPT-6 Luna",
        attempts=[{"provider": "apinex", "success": True}],
        raw_response=SAMPLE_DIFF,
    )

    # Make validate_diff raise or return SYNTAX_ERROR if it were mistakenly called
    with patch("ai.issue_fix_router.route_issue_fix", return_value=mock_fix_result), \
         patch("codefix.sandbox.validate_diff", side_effect=RuntimeError("SYNTAX_ERROR inside sandbox")) as mock_validate_diff:

        gen_resp = client.post(f"/repos/{r_id}/errors/{e_id}/generate-fix", headers=headers)
        assert gen_resp.status_code == 200
        gen_data = gen_resp.json()

        assert gen_data["passed"] is True
        assert gen_data["fix_status"] == "READY_TO_APPLY"
        assert gen_data["validation_status"] == "NOT_RUN"
        mock_validate_diff.assert_not_called()

        apply_resp = client.post(f"/repos/{r_id}/errors/{e_id}/apply-fix", headers=headers)
        assert apply_resp.status_code == 200
        apply_data = apply_resp.json()
        assert apply_data["fix_status"] == "APPLIED_LOCAL"
        assert apply_data["patch_status"] == "FIX_APPLIED"
        assert apply_data["validation_status"] == "NOT_RUN"


def test_3_credential_validation_failure_bypassed(repo_env):
    """Case 3: Credential validation failure from sandbox is bypassed."""
    r_id = repo_env["repo_id"]
    e_id = repo_env["error_id"]
    headers = repo_env["headers"]

    from ai.issue_fix_router import IssueFixResult

    mock_fix_result = IssueFixResult(
        diff=SAMPLE_DIFF,
        model="free/gpt-6-luna",
        model_display_name="GPT-6 Luna (Free)",
        provider="apinex",
        fallback_used=False,
        fix_attribution="Fixed using APInex GPT-6 Luna",
        attempts=[{"provider": "apinex", "success": True}],
        raw_response=SAMPLE_DIFF,
    )

    with patch("ai.issue_fix_router.route_issue_fix", return_value=mock_fix_result), \
         patch("codefix.sandbox._execute_in_environment", side_effect=RuntimeError("CREDENTIAL_VALIDATION_ERROR")) as mock_exec:

        gen_resp = client.post(f"/repos/{r_id}/errors/{e_id}/generate-fix", headers=headers)
        assert gen_resp.status_code == 200
        assert gen_resp.json()["fix_status"] == "READY_TO_APPLY"
        mock_exec.assert_not_called()


def test_4_patch_generation_failure_reports_honestly(repo_env):
    """Case 4: When AI generation fails, task reports failure honestly, NOT successful fix."""
    r_id = repo_env["repo_id"]
    e_id = repo_env["error_id"]
    headers = repo_env["headers"]

    with patch("ai.issue_fix_router.route_issue_fix", side_effect=RuntimeError("All AI providers quota exceeded")):
        gen_resp = client.post(f"/repos/{r_id}/errors/{e_id}/generate-fix", headers=headers)
        assert gen_resp.status_code == 200
        gen_data = gen_resp.json()

        assert gen_data["passed"] is False
        assert gen_data["fix_status"] == "FAILED"
        assert gen_data["patch_status"] == "PATCH_GENERATION_FAILED"
        assert bool(gen_data["error"]) is True


def test_5_patch_application_failure_reports_honestly(repo_env):
    """Case 5: When patch application fails (e.g. hunk conflict), task fails honestly."""
    r_id = repo_env["repo_id"]
    e_id = repo_env["error_id"]
    headers = repo_env["headers"]

    # Diff with conflicting context that doesn't exist in calculator.py
    conflicting_diff = """--- a/calculator.py
+++ b/calculator.py
@@ -100,2 +100,2 @@
 def nonexistent_function():
-    return 12345
+    return 67890
"""
    from ai.issue_fix_router import IssueFixResult

    mock_fix_result = IssueFixResult(
        diff=conflicting_diff,
        model="free/gpt-6-luna",
        model_display_name="GPT-6 Luna (Free)",
        provider="apinex",
        fallback_used=False,
        fix_attribution="Fixed using APInex GPT-6 Luna",
        attempts=[{"provider": "apinex", "success": True}],
        raw_response=conflicting_diff,
    )

    with patch("ai.issue_fix_router.route_issue_fix", return_value=mock_fix_result):
        # 1. Generation produces the patch and sets READY_TO_APPLY
        gen_resp = client.post(f"/repos/{r_id}/errors/{e_id}/generate-fix", headers=headers)
        assert gen_resp.status_code == 200
        gen_data = gen_resp.json()
        assert gen_data["passed"] is True
        assert gen_data["fix_status"] == "READY_TO_APPLY"

        # 2. Application attempts to apply the conflicting hunks and fails honestly
        apply_resp = client.post(f"/repos/{r_id}/errors/{e_id}/apply-fix", headers=headers)
        assert apply_resp.status_code == 422
        assert "hunk" in apply_resp.json()["detail"].lower() or "fail" in apply_resp.json()["detail"].lower()

        # 3. Check DB status persisted as FAILED
        with SessionLocal() as db:
            report = db.query(ErrorReport).filter(ErrorReport.id == e_id).first()
            assert report.fix_status == "FAILED"
            assert "Local apply failed" in (report.fix_error or "")


def test_6_empty_patch_rejected(repo_env):
    """Case 6: Empty patch is rejected safely without reporting success."""
    valid, err, details = validate_patch_format_and_safety(
        repo_root=repo_env["repo_dir"],
        target_file_path="calculator.py",
        diff_text="",
        patched_content="",
    )
    assert valid is False
    assert "Patch is empty" in err


def test_7_path_traversal_rejected_safely(repo_env):
    """Case 7: Path escaping repository root is rejected safely."""
    valid, err, details = validate_patch_format_and_safety(
        repo_root=repo_env["repo_dir"],
        target_file_path="../../windows/system32/cmd.exe",
        diff_text=SAMPLE_DIFF,
    )
    assert valid is False
    assert "path traversal" in err.lower() or "escapes" in err.lower()


def test_8_unsupported_patch_format_rejected(repo_env):
    """Case 8: Unsupported patch format without diff headers or hunks is rejected with clear error."""
    malformed_text = "This is just some conversational explanation without any unified diff headers."
    valid, err, details = validate_patch_format_and_safety(
        repo_root=repo_env["repo_dir"],
        target_file_path="calculator.py",
        diff_text=malformed_text,
    )
    assert valid is False
    assert "Unsupported patch format" in err


def test_9_status_model_persisted_and_consistent(repo_env):
    """Case 9 & 10: Task refresh and persisted status in DB reflect new semantics."""
    r_id = repo_env["repo_id"]
    e_id = repo_env["error_id"]
    headers = repo_env["headers"]

    from ai.issue_fix_router import IssueFixResult

    mock_fix_result = IssueFixResult(
        diff=SAMPLE_DIFF,
        model="free/gpt-6-luna",
        model_display_name="GPT-6 Luna (Free)",
        provider="apinex",
        fallback_used=False,
        fix_attribution="Fixed using APInex GPT-6 Luna",
        attempts=[{"provider": "apinex", "success": True}],
        raw_response=SAMPLE_DIFF,
    )

    with patch("ai.issue_fix_router.route_issue_fix", return_value=mock_fix_result):
        client.post(f"/repos/{r_id}/errors/{e_id}/generate-fix", headers=headers)
        client.post(f"/repos/{r_id}/errors/{e_id}/apply-fix", headers=headers)

    # Verify directly from DB
    with SessionLocal() as db:
        report = db.query(ErrorReport).filter(ErrorReport.id == e_id).first()
        assert report is not None
        assert report.fix_status == "APPLIED_LOCAL"
        assert report.fix_error is None

    # Fetch errors list endpoint (persisted query)
    list_resp = client.get(f"/repos/{r_id}/errors", headers=headers)
    assert list_resp.status_code == 200
    errors = list_resp.json()["errors"]
    target_err = next(e for e in errors if e["id"] == e_id)
    assert target_err["fix_status"] == "APPLIED_LOCAL"
