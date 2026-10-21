"""
routers/errors.py
------------------
Endpoints for ErrorReport management and automated fix application.

GET  /repos/{repo_id}/errors                         — list all error reports (scoped)
POST /repos/{repo_id}/errors/{error_id}/apply-fix    — sandbox validate + apply to disk (scoped)
POST /repos/{repo_id}/errors/{error_id}/reject       — mark REJECTED (skip fix) (scoped)
POST /repos/{repo_id}/errors/{error_id}/regenerate   — re-trigger suggestion generation (scoped)
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user, get_user_repo
from database import get_db
from models import ErrorReport, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos", tags=["errors"])

STORAGE_ROOT = Path(__file__).parent.parent / "storage"


# ── Helper: locate the actual repo root on disk ───────────────────────────────

def _find_repo_root(repo_id: str) -> Path | None:
    storage_dir = STORAGE_ROOT / repo_id
    if not storage_dir.exists():
        return None
    children = [c for c in storage_dir.iterdir() if c.is_dir() and c.name not in ("docs", "faiss.index")]
    if len(children) == 1:
        return children[0]
    return storage_dir


# ── GET /repos/{repo_id}/errors ───────────────────────────────────────────────

@router.get("/{repo_id}/errors", status_code=200)
def list_error_reports(
    repo_id: str,
    severity: str | None = None,   # filter: "error" | "warning" | "info"
    fix_status: str | None = None,  # filter: "PENDING" | "READY" | "APPLIED" | "FAILED" etc.
    include_resolved: bool = False,
    limit: int = 200,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all ErrorReport rows for a repository (scoped to owner). Excludes RESOLVED by default."""
    repo = get_user_repo(repo_id, db, current_user)

    q = db.query(ErrorReport).filter(ErrorReport.repo_id == repo.id)
    if not include_resolved:
        q = q.filter(~ErrorReport.fix_status.in_(["RESOLVED"]))
    if severity:
        q = q.filter(ErrorReport.severity == severity)
    if fix_status:
        q = q.filter(ErrorReport.fix_status == fix_status)
    reports = q.order_by(ErrorReport.created_at).limit(limit).all()

    serialized = [_serialize_report(r) for r in reports]
    error_cnt = sum(1 for r in reports if r.severity == "error")
    warn_cnt = sum(1 for r in reports if r.severity == "warning")
    rec_cnt = sum(1 for r in reports if r.severity in ("info", "recommendation"))
    msg = "No errors detected." if len(reports) == 0 else f"{error_cnt} error(s), {warn_cnt} warning(s), and {rec_cnt} recommendation(s) detected."

    return {
        "repo_id": repo.id,
        "total": len(reports),
        "total_errors": error_cnt,
        "total_warnings": warn_cnt,
        "total_recommendations": rec_cnt,
        "message": msg,
        "errors": serialized,
    }


# ── POST /repos/{repo_id}/errors/{error_id}/generate-fix ─────────────────────

@router.post("/{repo_id}/errors/{error_id}/generate-fix", status_code=200)
def generate_error_fix_endpoint(
    repo_id: str,
    error_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Propose an AI fix explanation + unified diff using the central provider router
    and validate patch format & target safety without executing code.
    Sets fix_status = 'READY_TO_APPLY' (or 'FAILED' if generation/safety fails).
    Execution validation is marked 'NOT_RUN'.
    Does NOT commit, push, or modify target files on disk.
    """
    from automation.auto_fix_pipeline import generate_and_validate_fix

    repo = get_user_repo(repo_id, db, current_user)

    report = db.query(ErrorReport).filter(
        ErrorReport.id == error_id,
        ErrorReport.repo_id == repo.id,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Error report not found.")

    res = generate_and_validate_fix(report.id, db, run_sandbox_validation=False)
    db.refresh(report)

    import json
    attempts_list = json.loads(report.fix_attempts) if getattr(report, "fix_attempts", None) else res.get("attempts", [])
    prov_used = getattr(report, "fix_provider", None) or res.get("provider_used")
    mod_used = report.fix_model or res.get("model_used")
    fix_attrib = getattr(report, "fix_attribution", None) or res.get("fix_attribution")
    fallback_used = (prov_used != "apinex" and prov_used is not None)

    return {
        "error_id": error_id,
        "fix_status": report.fix_status,
        "patch_status": res.get("patch_status", "PATCH_GENERATED" if res.get("passed") else "PATCH_GENERATION_FAILED"),
        "validation_status": res.get("validation_status", "NOT_RUN"),
        "validation_skipped": res.get("validation_skipped", True),
        "validation_notice": res.get("validation_notice", "Execution-based validation was skipped. Review the diff and run tests manually before relying on this change."),
        "passed": res.get("passed", False),
        "explanation": report.explanation,
        "suggested_fix": report.suggested_fix,
        "test_command": res.get("test_command", ""),
        "output": res.get("output", ""),
        "error": res.get("error") or report.fix_error,
        "failure_type": res.get("failure_type", "NONE" if res.get("passed") else "FAILED"),
        "provider_used": prov_used,
        "model_used": mod_used,
        "fallback_used": fallback_used,
        "fix_attribution": fix_attrib,
        "attempts": attempts_list,
        "changed_files": res.get("changed_files", [report.file_path] if report.file_path else []),
    }


# ── POST /repos/{repo_id}/errors/{error_id}/apply-fix ────────────────────────

@router.post("/{repo_id}/errors/{error_id}/apply-fix", status_code=200)
def apply_error_fix(
    repo_id: str,
    error_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Apply the validated fix (scoped to owner). Callable when fix_status == 'READY_TO_APPLY':
    - For zip uploads: applies patch to local file directly -> fix_status = APPLIED_LOCAL.
    - For git-cloned repos: applies patch, commits, pushes branch, opens PR -> fix_status = OPEN.
    Execution validation is explicitly marked 'NOT_RUN'.
    """
    from automation.auto_fix_pipeline import apply_fix_for_report
    from auth import get_user_github_token

    repo = get_user_repo(repo_id, db, current_user)

    report = db.query(ErrorReport).filter(
        ErrorReport.id == error_id,
        ErrorReport.repo_id == repo.id,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Error report not found.")

    if report.fix_status in ("APPLIED_LOCAL", "APPLIED", "FIX_APPLIED"):
        return {
            "error_id": error_id,
            "passed": True,
            "fix_status": report.fix_status,
            "patch_status": "FIX_APPLIED",
            "validation_status": "NOT_RUN",
            "validation_skipped": True,
            "validation_notice": "Execution-based validation was skipped. Review the diff and run tests manually before relying on this change.",
            "pr_status": getattr(report, "pr_status", "NONE"),
            "branch_name": getattr(report, "branch_name", None),
            "pr_url": getattr(report, "pr_url", None),
            "pr_id": getattr(report, "pr_id", None),
            "pr_number": getattr(report, "pr_id", None),
            "test_command": "",
            "output": "Fix was already applied.",
            "error": "",
            "changed_files": [report.file_path] if report.file_path else [],
        }

    if report.fix_status == "OPEN" and report.pr_url:
        return {
            "error_id": error_id,
            "passed": True,
            "fix_status": "OPEN",
            "patch_status": "FIX_APPLIED",
            "validation_status": "NOT_RUN",
            "validation_skipped": True,
            "validation_notice": "Execution-based validation was skipped. Review the diff and run tests manually before relying on this change.",
            "pr_status": report.pr_status,
            "branch_name": report.branch_name,
            "pr_url": report.pr_url,
            "pr_id": report.pr_id,
            "pr_number": report.pr_id,
            "test_command": "",
            "output": f"PR #{report.pr_id} is already open.",
            "error": "",
            "changed_files": [report.file_path] if report.file_path else [],
        }

    if report.fix_status not in ("READY_TO_APPLY", "READY", "PATCH_GENERATED"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot apply fix when fix_status is '{report.fix_status}'. Must be 'READY_TO_APPLY'. Generate fix first.",
        )

    user_token = get_user_github_token(current_user)
    res = apply_fix_for_report(report.id, db, user_token=user_token)
    db.refresh(report)

    if not res.get("passed", False):
        raise HTTPException(
            status_code=422 if res.get("status") == "local_apply_failed" else 500,
            detail=res.get("error") or "Failed to apply fix.",
        )

    return {
        "error_id": error_id,
        "passed": True,
        "fix_status": report.fix_status,
        "patch_status": "FIX_APPLIED",
        "validation_status": "NOT_RUN",
        "validation_skipped": True,
        "validation_notice": "Execution-based validation was skipped. Review the diff and run tests manually before relying on this change.",
        "pr_status": getattr(report, "pr_status", "NONE"),
        "branch_name": getattr(report, "branch_name", None),
        "pr_url": getattr(report, "pr_url", None),
        "pr_id": getattr(report, "pr_id", None),
        "pr_number": getattr(report, "pr_id", None),
        "test_command": "",
        "output": res.get("output", "Fix applied successfully."),
        "error": "",
        "changed_files": res.get("changed_files", [report.file_path] if report.file_path else []),
    }


# ── POST /repos/{repo_id}/errors/{error_id}/reject ───────────────────────────

@router.post("/{repo_id}/errors/{error_id}/reject", status_code=200)
def reject_error_fix(
    repo_id: str,
    error_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark an ErrorReport's fix as REJECTED (scoped to owner)."""
    repo = get_user_repo(repo_id, db, current_user)

    report = db.query(ErrorReport).filter(
        ErrorReport.id == error_id,
        ErrorReport.repo_id == repo.id,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Error report not found.")

    report.fix_status = "REJECTED"
    db.commit()
    return {"error_id": error_id, "fix_status": "REJECTED"}


# ── POST /repos/{repo_id}/errors/{error_id}/regenerate ───────────────────────

@router.post("/{repo_id}/errors/{error_id}/regenerate", status_code=202)
def regenerate_suggestion(
    repo_id: str,
    error_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Re-trigger suggestion generation for a single report (scoped to owner).
    """
    import threading

    repo = get_user_repo(repo_id, db, current_user)

    report = db.query(ErrorReport).filter(
        ErrorReport.id == error_id,
        ErrorReport.repo_id == repo.id,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Error report not found.")

    if report.fix_status in ("APPLIED",):
        return {"error_id": error_id, "status": "already_applied"}

    # Reset to PENDING so the generator picks it up
    report.fix_status = "PENDING"
    report.fix_error = None
    report.suggested_fix = None
    report.explanation = None
    db.commit()

    def _run():
        from database import SessionLocal
        _db = SessionLocal()
        try:
            from errordetection.suggestion import generate_suggestion_for_report
            generate_suggestion_for_report(error_id, _db)
        except Exception as exc:
            logger.exception("Regenerate crashed for %s: %s", error_id, exc)
        finally:
            _db.close()

    threading.Thread(target=_run, daemon=True, name=f"regen-{error_id[:8]}").start()
    return {"error_id": error_id, "status": "accepted", "message": "Regeneration started."}


# ── Serializer ────────────────────────────────────────────────────────────────

def _serialize_report(r) -> dict:
    import json
    attempts = []
    if getattr(r, "fix_attempts", None):
        try:
            attempts = json.loads(r.fix_attempts)
        except Exception:
            attempts = []
    prov_used = getattr(r, "fix_provider", None)
    return {
        "id": r.id,
        "repo_id": r.repo_id,
        "symbol_id": r.symbol_id,
        "rule_id": r.rule_id,
        "source": getattr(r, "source", "static_analysis") or "static_analysis",
        "severity": r.severity,
        "category": "ERROR" if r.severity == "error" else ("RECOMMENDATION" if r.severity == "info" else "WARNING"),
        "message": r.message,
        "file_path": r.file_path,
        "symbol_name": r.symbol_name,
        "symbol_type": r.symbol_type,
        "language": r.language,
        "line": r.line,
        "column": getattr(r, "column", None),
        "stack_trace": getattr(r, "stack_trace", None),
        "explanation": r.explanation,
        "suggested_fix": r.suggested_fix,
        "fix_status": r.fix_status,
        "fix_model": r.fix_model,
        "fix_provider": prov_used,
        "fix_attribution": getattr(r, "fix_attribution", None),
        "fix_attempts": attempts,
        "provider_used": prov_used,
        "model_used": r.fix_model,
        "fallback_used": (prov_used != "apinex" and prov_used is not None),
        "fix_error": r.fix_error,
        "branch_name": getattr(r, "branch_name", None),
        "pr_url": getattr(r, "pr_url", None),
        "pr_id": getattr(r, "pr_id", None),
        "pr_status": getattr(r, "pr_status", "NONE"),
        "auto_fix_attempted": getattr(r, "auto_fix_attempted", 0),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
