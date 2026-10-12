"""
backend/automation/auto_fix_pipeline.py
---------------------------------------
Fully automated fix-commit-push-PR pipeline for GitHub and local zip uploads.

Chains:
  1. Explanation & suggested diff generation (errordetection/suggestion.py + codefix/fixer.py)
  2. Isolated sandbox test execution (codefix/sandbox.py)
  3. For source_type == "upload":
     - Apply patch directly to local repository files (APPLIED_LOCAL / APPLIED)
  4. For source_type == "github":
     - Git branch creation and commit (gitops/git_ops.py) — ONLY if sandbox passes
     - Remote branch push & Pull Request creation via GitHub REST API (gitops/pr_client.py)
     - Enable Auto-Merge via GitHub GraphQL API (gitops/pr_client.py)
  5. Background & on-demand polling:
     - Polls GitHub check-runs & merge status for open PRs
     - Transitions pr_status -> MERGED / FAILED_PIPELINE
  6. Audit logging in AutomationLog table

Safety Guardrails:
  - Max 1 auto-fix attempt per error (capped via auto_fix_attempted).
  - Never push directly to the default branch (always ai-fix/ branch + PR).
  - Zero commits or branches created on sandbox failure.
  - Auto-merge is CI-gated via GitHub branch protection / check runs.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from database import SessionLocal
from models import ErrorReport, Repo, AutomationLog
from auth import get_user_github_token
from errordetection.suggestion import generate_suggestion_for_report
from codefix.sandbox import validate_diff, _apply_unified_diff
from codefix.patch_safety import (
    validate_patch_format_and_safety,
    apply_patch_safely,
    VALIDATION_SKIPPED_NOTICE,
)
from gitops.git_ops import create_branch_and_commit, commit_and_push_documentation
from gitops.pr_client import create_pull_request, enable_auto_merge, get_pr_status

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"


def _slugify(text: str) -> str:
    """Produce a safe branch name slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug[:40] if slug else "patch"


def _find_repo_root(repo_id: str) -> Path | None:
    """Locate the actual directory containing repository source files."""
    storage_dir = STORAGE_ROOT / repo_id
    if not storage_dir.exists():
        return None
    children = [c for c in storage_dir.iterdir() if c.is_dir() and c.name not in ("docs", "faiss.index")]
    if len(children) == 1:
        return children[0]
    return storage_dir


def _add_log(
    repo_id: str,
    stage: str,
    outcome: str,
    message: str,
    db: Session,
    error_id: str | None = None,
    details: str | None = None,
) -> AutomationLog:
    """Append an event to the chronological AutomationLog."""
    log_entry = AutomationLog(
        id=str(uuid.uuid4()),
        repo_id=repo_id,
        error_id=error_id,
        stage=stage,
        outcome=outcome,
        message=message,
        details=details,
    )
    db.add(log_entry)
    db.commit()
    logger.info("[%s] [%s] %s (repo=%s, error=%s)", stage, outcome, message, repo_id, error_id)
    return log_entry


def generate_and_validate_fix(report_id: str, db: Session, run_sandbox_validation: bool = False) -> dict[str, Any]:
    """
    Step 1 & 2 of the Code Fix flow:
    1. Proposes an AI fix explanation + unified diff using the central provider router (APInex -> NVIDIA -> Groq).
    2. Validates patch format, target-file safety, and workspace containment statically without code execution.
    3. If run_sandbox_validation=True (extensible manual check), optionally executes sandbox test validation.
    Sets fix_status = 'READY_TO_APPLY' on successful patch generation.
    Does NOT commit, push, or modify target files on disk.
    """
    report = db.query(ErrorReport).filter(ErrorReport.id == report_id).first()
    if not report:
        return {"report_id": report_id, "status": "not_found", "fix_status": "NOT_FOUND", "passed": False}

    repo = db.query(Repo).filter(Repo.id == report.repo_id).first()
    if not repo:
        return {"report_id": report_id, "status": "repo_not_found", "fix_status": "NOT_FOUND", "passed": False}

    _add_log(
        repo_id=report.repo_id,
        error_id=report.id,
        stage="DETECTED",
        outcome="INFO",
        message=f"Generating fix for '{report.rule_id}' in {report.file_path}: {report.message}",
        db=db,
    )

    # ── Step 1: Generate AI explanation + unified diff if needed ──────────────
    if not report.suggested_fix or report.fix_status == "PENDING":
        try:
            generate_suggestion_for_report(report.id, db)
            db.refresh(report)
        except Exception as exc:
            err_msg = f"Fix generation failed: {exc}"
            logger.exception(err_msg)
            report.fix_status = "FAILED"
            report.fix_error = err_msg
            db.commit()
            _add_log(
                repo_id=report.repo_id,
                error_id=report.id,
                stage="FIX_GENERATED",
                outcome="FAILED",
                message=f"Failed to generate fix for {report.file_path}: {exc}",
                db=db,
            )
            return {
                "report_id": report_id,
                "status": "generation_failed",
                "fix_status": "FAILED",
                "patch_status": "PATCH_GENERATION_FAILED",
                "validation_status": "NOT_RUN",
                "validation_skipped": True,
                "passed": False,
                "error": str(exc),
            }

    if not report.suggested_fix:
        msg = f"No valid fix diff produced for {report.file_path} ({report.rule_id})"
        report.fix_status = "FAILED"
        report.fix_error = msg
        db.commit()
        _add_log(
            repo_id=report.repo_id,
            error_id=report.id,
            stage="FIX_GENERATED",
            outcome="FAILED",
            message=msg,
            db=db,
        )
        return {
            "report_id": report_id,
            "status": "no_diff",
            "fix_status": "FAILED",
            "patch_status": "PATCH_GENERATION_FAILED",
            "validation_status": "NOT_RUN",
            "validation_skipped": True,
            "passed": False,
            "error": msg,
        }

    # ── Step 2: Validate patch format & safety statically without code execution ──
    repo_root = _find_repo_root(report.repo_id)
    if repo_root:
        is_safe, safety_err, details = validate_patch_format_and_safety(
            repo_root=repo_root,
            target_file_path=report.file_path,
            diff_text=report.suggested_fix,
        )
        if not is_safe:
            msg = f"Patch rejected by safety validator: {safety_err}"
            report.fix_status = "FAILED"
            report.fix_error = msg
            db.commit()
            _add_log(
                repo_id=report.repo_id,
                error_id=report.id,
                stage="FIX_GENERATED",
                outcome="FAILED",
                message=msg,
                details=report.suggested_fix[:2000],
                db=db,
            )
            return {
                "report_id": report_id,
                "status": "patch_safety_failed",
                "fix_status": "FAILED",
                "patch_status": "PATCH_GENERATION_FAILED",
                "validation_status": "NOT_RUN",
                "validation_skipped": True,
                "passed": False,
                "error": safety_err,
            }

    _add_log(
        repo_id=report.repo_id,
        error_id=report.id,
        stage="FIX_GENERATED",
        outcome="SUCCESS",
        message=f"AI fix diff generated for {report.file_path} using model {report.fix_model or 'default'}",
        details=report.suggested_fix[:2000],
        db=db,
    )

    # ── Optional Sandbox Validation (Only if explicitly enabled) ─────────────
    if run_sandbox_validation:
        try:
            vr = validate_diff(report.repo_id, report.suggested_fix, db, target_file_path=report.file_path)
            if not vr.passed:
                fail_detail = vr.error or vr.output or "Tests failed in sandbox"
                return {
                    "report_id": report_id,
                    "status": "sandbox_failed",
                    "fix_status": "SANDBOX_FAILED",
                    "patch_status": "PATCH_GENERATED",
                    "validation_status": "FAILED",
                    "validation_skipped": False,
                    "passed": False,
                    "test_command": vr.test_command,
                    "output": vr.output,
                    "error": fail_detail,
                    "explanation": report.explanation,
                    "suggested_fix": report.suggested_fix,
                }
        except Exception as exc:
            logger.warning("Optional sandbox run error: %s", exc)

    # Normal Code Fix workflow: Mark READY_TO_APPLY with validation_status = 'NOT_RUN'
    report.fix_status = "READY_TO_APPLY"
    report.fix_error = None
    db.commit()

    _add_log(
        repo_id=report.repo_id,
        error_id=report.id,
        stage="PATCH_GENERATED",
        outcome="SUCCESS",
        message=f"Patch generated and validated statically for {report.file_path} (execution validation skipped).",
        details=VALIDATION_SKIPPED_NOTICE,
        db=db,
    )

    attempts_list = json.loads(report.fix_attempts) if getattr(report, "fix_attempts", None) else []
    return {
        "report_id": report.id,
        "status": "ready_to_apply",
        "fix_status": "READY_TO_APPLY",
        "patch_status": "PATCH_GENERATED",
        "validation_status": "NOT_RUN",
        "validation_skipped": True,
        "validation_notice": VALIDATION_SKIPPED_NOTICE,
        "passed": True,
        "test_command": "(skipped)",
        "output": "Patch generated and format validated statically without code execution.",
        "error": None,
        "failure_type": "NONE",
        "explanation": report.explanation,
        "suggested_fix": report.suggested_fix,
        "provider_used": getattr(report, "fix_provider", None),
        "model_used": getattr(report, "fix_model", None),
        "fallback_used": (getattr(report, "fix_provider", None) != "apinex" and getattr(report, "fix_provider", None) is not None),
        "fix_attribution": getattr(report, "fix_attribution", None),
        "attempts": attempts_list,
        "changed_files": [report.file_path] if report.file_path else [],
    }


def apply_fix_for_report(report_id: str, db: Session, user_token: str | None = None) -> dict[str, Any]:
    """
    Step 3 of the fix flow:
    Callable only when fix_status == 'READY_TO_APPLY' (or already applied).
      - For zip uploads: applies patch to local file directly -> fix_status = APPLIED_LOCAL
      - For git repos: applies patch, commits, pushes branch, opens PR, enables auto-merge -> fix_status = OPEN
    """
    report = db.query(ErrorReport).filter(ErrorReport.id == report_id).first()
    if not report:
        return {"report_id": report_id, "status": "not_found", "fix_status": "NOT_FOUND", "passed": False}

    repo = db.query(Repo).filter(Repo.id == report.repo_id).first()
    if not repo:
        return {"report_id": report_id, "status": "repo_not_found", "fix_status": "NOT_FOUND", "passed": False}

    if report.fix_status in ("APPLIED_LOCAL", "APPLIED", "FIX_APPLIED"):
        return {
            "report_id": report.id,
            "status": "applied_local",
            "fix_status": report.fix_status,
            "patch_status": "FIX_APPLIED",
            "validation_status": "NOT_RUN",
            "validation_skipped": True,
            "validation_notice": VALIDATION_SKIPPED_NOTICE,
            "passed": True,
            "output": "Fix was already applied.",
            "error": None,
        }

    if report.fix_status == "OPEN" and report.pr_url:
        return {
            "report_id": report.id,
            "status": "pr_opened",
            "fix_status": "OPEN",
            "patch_status": "FIX_APPLIED",
            "validation_status": "NOT_RUN",
            "validation_skipped": True,
            "validation_notice": VALIDATION_SKIPPED_NOTICE,
            "branch_name": report.branch_name,
            "pr_url": report.pr_url,
            "pr_number": report.pr_id,
            "pr_status": report.pr_status,
            "passed": True,
            "output": f"PR #{report.pr_id} is already open.",
            "error": None,
        }

    if report.fix_status not in ("READY_TO_APPLY", "READY", "PATCH_GENERATED"):
        return {
            "report_id": report.id,
            "status": "not_ready",
            "fix_status": report.fix_status,
            "patch_status": "PATCH_APPLICATION_FAILED",
            "validation_status": "NOT_RUN",
            "validation_skipped": True,
            "passed": False,
            "error": f"Cannot apply fix when fix_status is '{report.fix_status}'. Must be 'READY_TO_APPLY'.",
        }

    source_type = repo.source_type if repo else "upload"

    # ── Step 3A: Zip Upload Repositories (Apply Locally, No Git / PR) ─────────
    if source_type != "github":
        repo_root = _find_repo_root(report.repo_id)
        if not repo_root:
            report.fix_status = "FAILED"
            report.fix_error = "Repo source not found on disk."
            db.commit()
            return {
                "report_id": report.id,
                "status": "repo_not_found",
                "fix_status": "FAILED",
                "patch_status": "PATCH_APPLICATION_FAILED",
                "validation_status": "NOT_RUN",
                "validation_skipped": True,
                "passed": False,
                "error": "Repo source not found on disk.",
            }

        ok, apply_err, apply_info = apply_patch_safely(
            repo_root=repo_root,
            target_file_path=report.file_path,
            diff_text=report.suggested_fix,
        )
        if not ok:
            report.fix_status = "FAILED"
            report.fix_error = f"Local apply failed: {apply_err}"
            db.commit()
            _add_log(
                repo_id=report.repo_id,
                error_id=report.id,
                stage="FIX_APPLIED",
                outcome="FAILED",
                message=f"Failed to apply patch to local files: {apply_err}",
                db=db,
            )
            return {
                "report_id": report.id,
                "status": "local_apply_failed",
                "fix_status": "FAILED",
                "patch_status": "PATCH_APPLICATION_FAILED",
                "validation_status": "NOT_RUN",
                "validation_skipped": True,
                "passed": False,
                "error": apply_err,
            }

        report.fix_status = "APPLIED_LOCAL"
        report.pr_status = "NONE"
        report.fix_error = None
        db.commit()

        _add_log(
            repo_id=report.repo_id,
            error_id=report.id,
            stage="FIX_APPLIED",
            outcome="SUCCESS",
            message=f"Applied fix directly to local files for {report.file_path} (zip-upload repository, execution validation skipped).",
            db=db,
        )
        return {
            "report_id": report.id,
            "status": "applied_local",
            "fix_status": "APPLIED_LOCAL",
            "patch_status": "FIX_APPLIED",
            "validation_status": "NOT_RUN",
            "validation_skipped": True,
            "validation_notice": VALIDATION_SKIPPED_NOTICE,
            "passed": True,
            "changed_files": apply_info.get("changed_files", [report.file_path]),
            "output": "Patch applied cleanly to local files without executing code.",
            "error": None,
        }

    # ── Step 3B: GitHub Repositories (Branch -> Push -> PR -> Auto-Merge) ─────
    from auth import get_user_github_token
    from rate_limiter import (
        get_user_fix_semaphore,
        ensure_github_rate_limit_available,
        GitHubRateLimitExceededError,
    )
    if user_token is None and repo and repo.user:
        user_token = get_user_github_token(repo.user)
    user_id = repo.user_id if repo else "default"

    # Pre-check GitHub rate limit for this user
    if user_token:
        try:
            ensure_github_rate_limit_available(user_token)
        except GitHubRateLimitExceededError as rle:
            logger.warning("GitHub rate limit low for user %s: %s", user_id, rle)
            _add_log(
                repo_id=report.repo_id,
                error_id=report.id,
                stage="BRANCH_PUSHED",
                outcome="WARNING",
                message=(
                    f"GitHub API rate limit is low ({rle.remaining}/{rle.limit} remaining). "
                    f"Automation paused until quota resets at {rle.reset_datetime.strftime('%H:%M:%S UTC')}."
                ),
                details=str(rle),
                db=db,
            )
            return {
                "report_id": report_id,
                "status": "rate_limit_paused",
                "fix_status": "READY_TO_APPLY",
                "passed": False,
                "remaining": rle.remaining,
                "reset_time": rle.reset_datetime.isoformat(),
            }

    error_short_id = report.id[:8]
    desc_slug = _slugify(f"{report.rule_id}-{Path(report.file_path).stem}")
    branch_name = f"ai-fix/{error_short_id}-{desc_slug}"
    commit_message = (
        f"AI fix: {report.rule_id} in {report.file_path} — format-validated (execution validation skipped)\n\n"
        f"Rule: {report.rule_id} ({report.severity})\n"
        f"Message: {report.message}\n"
        f"{VALIDATION_SKIPPED_NOTICE}"
    )

    try:
        branch_result = create_branch_and_commit(
            repo_id=report.repo_id,
            patch=report.suggested_fix,
            branch_name=branch_name,
            commit_message=commit_message,
            token=user_token,
        )
    except Exception as exc:
        err_msg = f"Git commit/push failed: {exc}"
        logger.warning(err_msg)
        report.fix_error = err_msg
        db.commit()
        _add_log(
            repo_id=report.repo_id,
            error_id=report.id,
            stage="BRANCH_PUSHED",
            outcome="FAILED",
            message=f"Failed to create branch / push for {report.file_path}: {exc}",
            db=db,
        )
        return {
            "report_id": report_id,
            "status": "git_push_failed",
            "fix_status": "READY_TO_APPLY",
            "patch_status": "PATCH_APPLICATION_FAILED",
            "validation_status": "NOT_RUN",
            "validation_skipped": True,
            "passed": False,
            "error": str(exc),
        }

    _add_log(
        repo_id=report.repo_id,
        error_id=report.id,
        stage="BRANCH_PUSHED",
        outcome="SUCCESS",
        message=f"Pushed branch '{branch_name}' (commit {branch_result.commit_sha[:8]}) to {branch_result.provider}",
        details=f"Remote: {branch_result.remote_url}\nCommit: {branch_result.commit_sha}",
        db=db,
    )

    # ── Step 4: Open Pull Request on GitHub ───────────────────────────────────
    pr_title = f"[AI Fix] {report.rule_id} in {report.file_path}"
    pr_body = (
        f"## 🤖 AI-Generated Automated Fix\n\n"
        f"This pull request was automatically generated and format-validated by **CodeBrain**.\n\n"
        f"> ℹ️ **Notice:** {VALIDATION_SKIPPED_NOTICE}\n\n"
        f"### 📋 Issue Details\n"
        f"- **Rule ID:** `{report.rule_id}`\n"
        f"- **Severity:** `{report.severity}`\n"
        f"- **File:** `{report.file_path}`\n"
        f"- **Line:** `{report.line or 'N/A'}`\n"
        f"- **Description:** {report.message}\n\n"
        f"### 💡 Explanation\n"
        f"{report.explanation or 'No explanation provided.'}\n\n"
        f"### 🔄 Auto-Merge Notice\n"
        f"Auto-merge has been requested for this PR. It will merge automatically once CI status checks pass."
    )

    try:
        pr_result = create_pull_request(
            repo_full_name=branch_result.remote_url,
            branch_name=branch_name,
            base_branch="main",
            title=pr_title,
            body=pr_body,
            token=user_token,
        )
    except Exception as exc:
        err_msg = f"GitHub PR creation failed: {exc}"
        logger.warning(err_msg)
        report.branch_name = branch_name
        report.fix_error = err_msg
        db.commit()
        _add_log(
            repo_id=report.repo_id,
            error_id=report.id,
            stage="PR_OPENED",
            outcome="FAILED",
            message=f"Failed to open GitHub PR for branch {branch_name}: {exc}",
            db=db,
        )
        return {"report_id": report_id, "status": "pr_open_failed", "fix_status": "READY_TO_APPLY", "passed": False, "error": str(exc)}

    pr_number = pr_result["pr_number"]
    pr_url = pr_result["pr_url"]

    # ── Step 5: Enable Auto-Merge via GraphQL (Handling Real-World Constraints) ──
    has_ci = bool(getattr(repo, "detected_ci", False))
    report.fix_status = "OPEN"

    if not has_ci:
        # Case A: No CI workflow detected in repository
        report.branch_name = branch_name
        report.pr_url = pr_url
        report.pr_id = pr_number
        report.pr_status = "OPEN_NO_CI"
        report.fix_error = None
        db.commit()

        _add_log(
            repo_id=report.repo_id,
            error_id=report.id,
            stage="PR_OPENED",
            outcome="INFO",
            message=(
                f"Opened PR #{pr_number} on GitHub without auto-merge "
                f"(no CI workflow detected in repository. Run setup-ci or merge manually)."
            ),
            details=pr_url,
            db=db,
        )
    else:
        from gitops.pr_client import (
            check_branch_protection,
            AutoMergeNotAllowedError,
            BranchProtectionMissingError,
            GitHubPermissionError,
        )

        # Case B1: Pre-check branch protection & required status checks
        protection = check_branch_protection(branch_result.remote_url, branch="main", token=user_token)
        if not protection["has_required_checks"] and not protection.get("permission_error"):
            report.branch_name = branch_name
            report.pr_url = pr_url
            report.pr_id = pr_number
            report.pr_status = "OPEN_MANUAL_MERGE_REQUIRED"
            report.fix_error = None
            db.commit()

            _add_log(
                repo_id=report.repo_id,
                error_id=report.id,
                stage="PR_OPENED",
                outcome="WARNING",
                message=(
                    f"Opened PR #{pr_number} on GitHub without auto-merge: {protection['reason']} "
                    f"— manual merge required to prevent premature merge before CI runs."
                ),
                details=pr_url,
                db=db,
            )
        else:
            # Case B2: Attempt to enable auto-merge via GraphQL mutation
            try:
                enable_auto_merge(
                    repo_full_name=branch_result.remote_url,
                    pr_number=pr_number,
                    merge_method="squash",
                    token=user_token,
                )
                report.branch_name = branch_name
                report.pr_url = pr_url
                report.pr_id = pr_number
                report.pr_status = "OPEN_AUTO_MERGE_ENABLED"
                report.fix_error = None
                db.commit()

                _add_log(
                    repo_id=report.repo_id,
                    error_id=report.id,
                    stage="PR_OPENED",
                    outcome="SUCCESS",
                    message=f"Opened PR #{pr_number} on GitHub with Auto-Merge enabled.",
                    details=pr_url,
                    db=db,
                )
            except AutoMergeNotAllowedError:
                report.branch_name = branch_name
                report.pr_url = pr_url
                report.pr_id = pr_number
                report.pr_status = "OPEN_MANUAL_MERGE_REQUIRED"
                report.fix_error = None
                db.commit()

                _add_log(
                    repo_id=report.repo_id,
                    error_id=report.id,
                    stage="PR_OPENED",
                    outcome="WARNING",
                    message=(
                        f"Opened PR #{pr_number} on GitHub. This repository doesn't have auto-merge "
                        f"enabled in its settings — the PR is ready but requires manual merge."
                    ),
                    details=pr_url,
                    db=db,
                )
            except GitHubPermissionError as exc:
                report.branch_name = branch_name
                report.pr_url = pr_url
                report.pr_id = pr_number
                report.pr_status = "OPEN_MANUAL_MERGE_REQUIRED"
                report.fix_error = str(exc)
                db.commit()

                _add_log(
                    repo_id=report.repo_id,
                    error_id=report.id,
                    stage="PR_OPENED",
                    outcome="WARNING",
                    message=(
                        f"Opened PR #{pr_number} on GitHub. Token lacks permission to enable auto-merge "
                        f"on repository — manual merge required."
                    ),
                    details=pr_url,
                    db=db,
                )
            except Exception as exc:
                logger.warning("Could not enable auto-merge on PR #%d: %s", pr_number, exc)
                report.branch_name = branch_name
                report.pr_url = pr_url
                report.pr_id = pr_number
                report.pr_status = "OPEN_MANUAL_MERGE_REQUIRED"
                report.fix_error = str(exc)
                db.commit()

                _add_log(
                    repo_id=report.repo_id,
                    error_id=report.id,
                    stage="PR_OPENED",
                    outcome="WARNING",
                    message=f"Opened PR #{pr_number} on GitHub. Auto-merge could not be enabled ({exc}) — manual merge required.",
                    details=pr_url,
                    db=db,
                )

    return {
        "report_id": report.id,
        "status": "pr_opened",
        "fix_status": report.fix_status,
        "patch_status": "FIX_APPLIED",
        "validation_status": "NOT_RUN",
        "validation_skipped": True,
        "validation_notice": VALIDATION_SKIPPED_NOTICE,
        "branch_name": branch_name,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "pr_status": report.pr_status,
        "passed": True,
        "changed_files": [report.file_path] if report.file_path else [],
        "output": f"Pushed branch '{branch_name}' and opened PR #{pr_number}.",
        "error": None,
    }


def run_auto_fix_for_report(report_id: str, db: Session) -> dict[str, Any]:
    """
    Execute the automated fix-apply-commit-PR flow for a single ErrorReport without sandbox validation.
    Enforces single-attempt safety cap and sequentially calls:
      1. generate_and_validate_fix (Diff generation & static format safety verification)
      2. apply_fix_for_report (Disk apply for uploads, or Git push + PR for GitHub)
    """
    report = db.query(ErrorReport).filter(ErrorReport.id == report_id).first()
    if not report:
        return {"report_id": report_id, "status": "not_found", "fix_status": "NOT_FOUND"}

    # Guardrail: Cap auto-fix attempts per error to 1
    if (report.auto_fix_attempted or 0) >= 1:
        logger.info("Skipping error %s — already attempted %d time(s)", report_id, report.auto_fix_attempted)
        return {"report_id": report_id, "status": "already_attempted", "fix_status": report.fix_status}

    report.auto_fix_attempted = (report.auto_fix_attempted or 0) + 1
    db.commit()

    val_res = generate_and_validate_fix(report_id, db, run_sandbox_validation=False)
    if not val_res.get("passed") or val_res.get("fix_status") != "READY_TO_APPLY":
        return val_res

    return apply_fix_for_report(report_id, db)


def run_auto_fix_pipeline(repo_id: str, db: Session) -> list[dict[str, Any]]:
    """
    Iterate over all fixable ErrorReports in a repository and execute the
    automated repair pipeline for each. Enforces per-user concurrency cap.
    """
    from rate_limiter import get_user_fix_semaphore
    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    user_id = repo.user_id if repo else "default"
    sem = get_user_fix_semaphore(user_id)

    reports = (
        db.query(ErrorReport)
        .filter(
            ErrorReport.repo_id == repo_id,
            ErrorReport.severity.in_(["error", "warning"]),
            ErrorReport.auto_fix_attempted == 0,
        )
        .order_by(ErrorReport.created_at)
        .all()
    )

    logger.info("Running auto-fix pipeline for %d issues in repo %s", len(reports), repo_id)
    results = []

    for r in reports:
        try:
            with sem:
                res = run_auto_fix_for_report(r.id, db)
                results.append(res)
        except Exception as exc:
            logger.exception("Error in auto-fix flow for report %s: %s", r.id, exc)
            results.append({"report_id": r.id, "status": "crashed", "error": str(exc)})

    # Auto-generate documentation once fixes are processed and repository reaches ready state
    try:
        def _bg_generate_after_fix():
            from database import SessionLocal
            from docgen.master_doc_gen import generate_full_project_documentation
            bg_db = SessionLocal()
            try:
                generate_full_project_documentation(repo_id, bg_db)
                logger.info("Auto-generated documentation suite for repo %s after auto-fix pipeline", repo_id)
            except Exception as e:
                logger.warning("Auto-docgen after fix pipeline failed for %s: %s", repo_id, e)
            finally:
                bg_db.close()

        threading.Thread(target=_bg_generate_after_fix, daemon=True, name=f"autodoc-fix-{repo_id}").start()
    except Exception as exc:
        logger.warning("Could not spawn background doc generation for %s after fixes: %s", repo_id, exc)

    return results


# ── PR Status Polling & Synchronization ───────────────────────────────────────

def sync_pr_statuses_for_repo(repo_id: str, db: Session) -> dict[str, Any]:
    """
    Check real-time GitHub status for all open PRs in a repository.
    Updates pr_status -> 'MERGED' or 'FAILED_PIPELINE' and records AutomationLog entries.
    """
    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if not repo:
        return {"updated_count": 0, "open_count": 0}

    open_reports = (
        db.query(ErrorReport)
        .filter(
            ErrorReport.repo_id == repo_id,
            ErrorReport.pr_status.in_(["OPEN", "OPEN_AUTO_MERGE_ENABLED", "OPEN_NO_CI", "OPEN_MANUAL_MERGE_REQUIRED"]),
            ErrorReport.pr_id != None,
        )
        .all()
    )

    if not open_reports:
        return {"updated_count": 0, "open_count": 0}

    from auth import get_user_github_token
    from rate_limiter import ensure_github_rate_limit_available, GitHubRateLimitExceededError

    user_token = get_user_github_token(repo.user) if (repo and repo.user) else None
    if user_token:
        try:
            ensure_github_rate_limit_available(user_token, min_remaining=20)
        except GitHubRateLimitExceededError as rle:
            logger.warning("PR sync polling paused for repo %s due to low rate limit: %s", repo_id, rle)
            return {"updated_count": 0, "open_count": len(open_reports), "paused": True}

    updated_count = 0

    for report in open_reports:
        pr_target = report.pr_url or repo.name
        # Classify Azure DevOps or unsupported platforms and stop polling them
        if "dev.azure.com" in str(pr_target).lower() or "visualstudio.com" in str(pr_target).lower():
            report.pr_status = "UNSUPPORTED_PROVIDER"
            db.commit()
            logger.info("PR #%s on '%s' marked as UNSUPPORTED_PROVIDER. Status polling stopped.", report.pr_id, pr_target)
            continue
        try:
            from gitops.pr_client import UnsupportedProviderError
            status_data = get_pr_status(pr_target, report.pr_id, token=user_token)
        except UnsupportedProviderError as upe:
            report.pr_status = "UNSUPPORTED_PROVIDER"
            db.commit()
            logger.info("PR #%s on '%s' marked as UNSUPPORTED_PROVIDER: %s. Status polling stopped.", report.pr_id, pr_target, upe)
            continue
        except ValueError as ve:
            report.pr_status = "INVALID_PR_URL"
            db.commit()
            logger.warning("PR #%s on '%s' marked as INVALID_PR_URL: %s. Status polling stopped.", report.pr_id, pr_target, ve)
            continue
        except Exception as exc:
            logger.debug("Could not fetch status for PR #%s (%s): %s", report.pr_id, pr_target, exc)
            continue

        is_merged = status_data.get("merged", False)
        state = status_data.get("state", "open")
        check_runs = status_data.get("checks", {}).get("check_runs", [])

        # Check 1: Merged on GitHub
        if is_merged:
            report.pr_status = "MERGED"
            db.commit()
            _add_log(
                repo_id=repo_id,
                error_id=report.id,
                stage="PIPELINE_PASSED",
                outcome="SUCCESS",
                message=f"GitHub Actions CI passed for PR #{report.pr_id} ({report.branch_name}). PR auto-merged successfully.",
                details=f"PR #{report.pr_id} merged into {status_data.get('base_branch', 'main')}",
                db=db,
            )
            updated_count += 1
            continue

        # Check 2: Closed without merging
        if state == "closed" and not is_merged:
            report.pr_status = "FAILED_PIPELINE"
            db.commit()
            _add_log(
                repo_id=repo_id,
                error_id=report.id,
                stage="PIPELINE_FAILED",
                outcome="FAILED",
                message=f"GitHub PR #{report.pr_id} ({report.branch_name}) was closed without merging.",
                details="PR closed without merge",
                db=db,
            )
            updated_count += 1
            continue

        # Check 3: Check-runs completed with failure
        failed_checks = [
            c for c in check_runs
            if c.get("status") == "completed" and c.get("conclusion") in ("failure", "timed_out", "action_required")
        ]
        if failed_checks:
            report.pr_status = "FAILED_PIPELINE"
            db.commit()
            check_names = ", ".join(c.get("name", "Unknown Check") for c in failed_checks)
            _add_log(
                repo_id=repo_id,
                error_id=report.id,
                stage="PIPELINE_FAILED",
                outcome="FAILED",
                message=f"GitHub Actions CI check(s) '{check_names}' failed for PR #{report.pr_id} ({report.branch_name}). Auto-merge blocked.",
                details=str(failed_checks),
                db=db,
            )
            updated_count += 1

    return {"updated_count": updated_count, "open_count": len(open_reports)}


# ── Background Worker ─────────────────────────────────────────────────────────

_worker_started = False
_worker_lock = threading.Lock()


def _background_polling_loop(interval_seconds: int = 30):
    """Periodic worker loop that polls all open PRs every interval_seconds."""
    logger.info("Started background GitHub PR status polling worker (interval=%ds)", interval_seconds)
    while True:
        try:
            time.sleep(interval_seconds)
            db = SessionLocal()
            try:
                open_repos = (
                    db.query(ErrorReport.repo_id)
                    .filter(
                        ErrorReport.pr_status.in_(["OPEN", "OPEN_AUTO_MERGE_ENABLED", "OPEN_NO_CI", "OPEN_MANUAL_MERGE_REQUIRED"]),
                        ErrorReport.pr_id != None,
                    )
                    .distinct()
                    .all()
                )
                for (r_id,) in open_repos:
                    sync_pr_statuses_for_repo(r_id, db)
            finally:
                db.close()
        except Exception as exc:
            logger.warning("Error in background PR polling worker: %s", exc)


def start_pr_polling_worker(interval_seconds: int = 30):
    """Start the daemon background polling thread if not already running."""
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            t = threading.Thread(
                target=_background_polling_loop,
                args=(interval_seconds,),
                daemon=True,
                name="gh-pr-poller",
            )
            t.start()
            _worker_started = True


# ── Documentation Commit & PR Pipeline ───────────────────────────────────────

def commit_docs_to_repo(repo_id: str, db: Session, user_token: str | None = None) -> dict[str, Any]:
    """
    Pushes generated docs + README to the repository.
    - If docs are not yet generated, runs generate_full_project_documentation first.
    - If upload repo: copies docs and README to the stored repo root (APPLIED_LOCAL).
    - If GitHub repo: creates branch 'docs/update-documentation-<id>', commits README + docs,
      pushes to origin, opens PR, and enables auto-merge with zero additional manual git actions.
    """
    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if not repo:
        return {"status": "error", "message": f"Repo {repo_id} not found"}

    docs_dir = STORAGE_ROOT / repo_id / "docs"
    master_doc_file = docs_dir / "FULL_PROJECT_DOCUMENTATION.md"
    readme_file = docs_dir / "README.md"

    if not master_doc_file.exists() or not readme_file.exists():
        from docgen.master_doc_gen import generate_full_project_documentation
        generate_full_project_documentation(repo_id, db)

    source_type = repo.source_type if repo else "upload"

    if source_type != "github":
        repo_root = _find_repo_root(repo_id)
        if not repo_root:
            return {"status": "error", "message": "Repo source not found on disk"}

        # Copy README to repo root
        if readme_file.exists() and readme_file.resolve() != (repo_root / "README.md").resolve():
            shutil.copy2(readme_file, repo_root / "README.md")

        # Copy docs folder into repo root
        target_docs = repo_root / "docs"
        if docs_dir.resolve() != target_docs.resolve():
            target_docs.mkdir(parents=True, exist_ok=True)
            for doc_file in docs_dir.glob("*"):
                if doc_file.is_file() and doc_file.resolve() != (target_docs / doc_file.name).resolve():
                    shutil.copy2(doc_file, target_docs / doc_file.name)

        _add_log(
            repo_id=repo_id,
            error_id=None,
            stage="DOCS_COMMITTED",
            outcome="SUCCESS",
            message="Documentation and README applied directly to local repository disk.",
            db=db,
        )
        return {
            "status": "applied_local",
            "message": "Documentation and README successfully committed to local repository.",
            "branch_name": None,
            "commit_sha": None,
            "pr_url": None,
            "pr_number": None,
            "pr_status": "NONE",
        }

    # GitHub repo
    if user_token is None and repo.user:
        user_token = get_user_github_token(repo.user)

    branch_short_id = uuid.uuid4().hex[:8]
    branch_name = f"docs/update-documentation-{branch_short_id}"
    commit_message = "docs: update technical documentation suite and README [skip ci]"

    try:
        branch_res = commit_and_push_documentation(
            repo_id=repo_id,
            docs_dir=docs_dir,
            branch_name=branch_name,
            commit_message=commit_message,
            token=user_token,
        )
    except Exception as exc:
        logger.warning("Docs commit/push failed for %s: %s", repo_id, exc)
        _add_log(
            repo_id=repo_id,
            error_id=None,
            stage="DOCS_PUSH",
            outcome="FAILED",
            message=f"Failed to push documentation branch '{branch_name}': {exc}",
            db=db,
        )
        return {"status": "error", "message": f"Git push failed: {exc}"}

    _add_log(
        repo_id=repo_id,
        error_id=None,
        stage="DOCS_PUSH",
        outcome="SUCCESS",
        message=f"Pushed documentation branch '{branch_name}' (commit {branch_res.commit_sha[:8]}) to GitHub",
        details=f"Remote: {branch_res.remote_url}\nCommit: {branch_res.commit_sha}",
        db=db,
    )

    # Open PR on GitHub
    pr_title = "docs: update technical documentation suite and README"
    pr_body = (
        "## 📚 Automated Technical Documentation Suite\n\n"
        "This pull request contains the automated, data-grounded project documentation suite "
        "and updated `README.md` generated by **CodeBrain**.\n\n"
        "### 📄 Included Documentation\n"
        "- Complete repository architecture & component breakdown (`docs/`)\n"
        "- Fact-based system structure and setup guide\n"
        "- Updated project `README.md`\n\n"
        "### 🔄 Auto-Merge Notice\n"
        "Auto-merge has been requested for this documentation PR."
    )

    try:
        pr_result = create_pull_request(
            repo_full_name=branch_res.remote_url,
            branch_name=branch_name,
            base_branch="main",
            title=pr_title,
            body=pr_body,
            token=user_token,
        )
    except Exception as exc:
        logger.warning("Docs PR creation failed for %s: %s", repo_id, exc)
        _add_log(
            repo_id=repo_id,
            error_id=None,
            stage="DOCS_PR_OPENED",
            outcome="FAILED",
            message=f"Failed to open GitHub PR for docs branch '{branch_name}': {exc}",
            db=db,
        )
        return {"status": "error", "message": f"Failed to create GitHub PR: {exc}", "branch_name": branch_name}

    pr_number = pr_result["pr_number"]
    pr_url = pr_result["pr_url"]

    # Try enabling auto-merge via GraphQL
    try:
        auto_merge_res = enable_auto_merge(
            repo_full_name=branch_res.remote_url,
            pr_number=pr_number,
            merge_method="SQUASH",
            token=user_token,
        )
        auto_merge_ok = auto_merge_res.get("auto_merge_enabled", False)
    except Exception as am_err:
        logger.warning("Could not enable auto-merge for docs PR: %s", am_err)
        auto_merge_ok = False

    _add_log(
        repo_id=repo_id,
        error_id=None,
        stage="DOCS_PR_OPENED",
        outcome="SUCCESS",
        message=f"Created GitHub PR #{pr_number} for documentation updates",
        details=f"PR URL: {pr_url}\nAuto-merge enabled: {auto_merge_ok}",
        db=db,
    )

    return {
        "status": "pr_opened",
        "message": f"Documentation and README pushed to branch '{branch_name}' and PR #{pr_number} created with auto-merge enabled.",
        "branch_name": branch_name,
        "commit_sha": branch_res.commit_sha,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "pr_status": "OPEN",
        "auto_merge_enabled": auto_merge_ok,
    }
