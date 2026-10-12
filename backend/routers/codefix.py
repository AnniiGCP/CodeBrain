"""
routers/codefix.py
------------------
POST /symbols/{symbol_id}/explain        — natural language explanation (scoped)
POST /symbols/{symbol_id}/fix            — generate unified diff fix (scoped)
POST /repos/{repo_id}/validate-patch     — apply patch + run tests (scoped)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, get_user_repo, get_user_symbol
from database import get_db
from models import User

logger = logging.getLogger(__name__)

symbols_router = APIRouter(prefix="/symbols", tags=["codefix"])
repos_router = APIRouter(prefix="/repos", tags=["codefix"])


# ── POST /symbols/{symbol_id}/explain ────────────────────────────────────────

@symbols_router.post("/{symbol_id}/explain", status_code=200)
def explain_symbol_endpoint(
    symbol_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a natural-language explanation of the symbol (scoped to owner)."""
    from codefix.explainer import explain_symbol

    symbol = get_user_symbol(symbol_id, db, current_user)

    try:
        explanation = explain_symbol(symbol.id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("explain_symbol failed for %d", symbol.id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"symbol_id": symbol.id, "explanation": explanation}


# ── POST /symbols/{symbol_id}/fix ────────────────────────────────────────────

class FixRequest(BaseModel):
    issue_description: str = Field(..., min_length=5, max_length=2000)
    provider: str | None = None
    model: str | None = None


@symbols_router.post("/{symbol_id}/fix", status_code=200)
def generate_fix_endpoint(
    symbol_id: int,
    body: FixRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a unified diff fixing the described issue in the symbol (scoped to owner)."""
    from codefix.fixer import generate_fix

    symbol = get_user_symbol(symbol_id, db, current_user)

    try:
        result = generate_fix(
            symbol_id=symbol.id,
            issue_description=body.issue_description,
            db=db,
            provider=body.provider,
            model=body.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("generate_fix failed for symbol %d", symbol.id)
        raise HTTPException(status_code=500, detail=str(exc))

    return result



# ── POST /repos/{repo_id}/validate-patch ─────────────────────────────────────

class ValidatePatchRequest(BaseModel):
    file_path: str = Field(..., min_length=1)
    diff: str | None = Field(None, description="Unified diff (git format)")
    patched_content: str | None = Field(None, description="Full new file content")
    test_command: str | None = Field(None, description="Override test command")


@repos_router.post("/{repo_id}/validate-patch", status_code=200)
def validate_patch_endpoint(
    repo_id: str,
    body: ValidatePatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Apply a patch (diff or full content) to a throwaway copy of the repo
    and run the auto-detected test suite (scoped to owner).
    """
    from codefix.sandbox import validate_patch, validate_diff

    repo = get_user_repo(repo_id, db, current_user)

    has_diff = bool(body.diff and body.diff.strip())
    has_content = bool(body.patched_content and body.patched_content.strip())

    if not has_diff and not has_content:
        return {
            "repo_id": repo.id,
            "file_path": body.file_path,
            "passed": False,
            "test_command": "(none)",
            "exit_code": -1,
            "output": "",
            "error": "Provide either 'diff' (unified diff) or 'patched_content' (full file). Empty patches cannot be validated.",
            "failure_type": "INVALID_PATCH",
        }

    try:
        if has_diff:
            vr = validate_diff(repo.id, body.diff.strip(), db, test_command=body.test_command, target_file_path=body.file_path)
        else:
            vr = validate_patch(
                repo.id, body.file_path, body.patched_content.strip(), db,
                test_command=body.test_command,
            )
    except Exception as exc:
        logger.exception("validate_patch failed for %s", repo.id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "repo_id": repo.id,
        "file_path": body.file_path,
        "passed": vr.passed,
        "test_command": vr.test_command,
        "exit_code": vr.exit_code,
        "output": vr.output,
        "error": vr.error,
        "failure_type": getattr(vr, "failure_type", "PASSED" if vr.passed else "TEST_FAILED"),
        "is_environment_failure": getattr(vr, "is_environment_failure", False),
        "working_directory": getattr(vr, "working_directory", ""),
        "python_executable": getattr(vr, "python_executable", ""),
        "python_version": getattr(vr, "python_version", ""),
        "repo_root": getattr(vr, "repo_root", ""),
        "project_root": getattr(vr, "project_root", ""),
        "detected_test_config": getattr(vr, "detected_test_config", ""),
        "patch_applied": getattr(vr, "patch_applied", True),
        "stdout": getattr(vr, "stdout", ""),
        "stderr": getattr(vr, "stderr", ""),
        "runtime_provider": getattr(vr, "runtime_provider", ""),
        "missing_dependencies": getattr(vr, "missing_dependencies", []),
        "diagnostic_details": getattr(vr, "diagnostic_details", {}),
    }
