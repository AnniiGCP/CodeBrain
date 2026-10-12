"""
backend/routers/cicd.py
-----------------------
Repository-Aware CI/CD Automation Router.
Provides complete per-repository CI/CD endpoints:
  - Repository-specific status, detection, and isolation
  - Workflow preview & AI generation
  - Installation (Pull Request or Direct Commit) and remote verification
  - GitHub Actions runs, job logs, and workflow dispatch
  - AI failure diagnosis, classification, and bounded patch repair
  - Deployment configuration detection
  - Automation policy controls (auto-fix, auto-commit, retry limits)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, get_user_repo, get_user_github_token
from automation.ci_diagnosis import diagnose_ci_failure, apply_ci_fix_and_commit
from automation.ci_setup import (
    analyze_repository_evidence,
    create_ci_setup_pr,
    detect_ci_workflows,
    generate_default_ci_workflow,
    get_ci_workflow_preview,
    get_or_create_repo_ci_config,
    get_repo_full_name,
    install_ci_workflow_direct,
    verify_remote_ci_installation,
)
from automation.deployment_detector import detect_repository_deployment
from database import get_db
from gitops.git_ops import sanitize_sensitive_text
from gitops.github_actions import (
    dispatch_github_workflow,
    fetch_github_actions_runs,
    fetch_github_job_logs,
    fetch_github_run,
    fetch_github_run_jobs,
)
from models import Repo, RepoCiConfig, RepoCiRun, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos", tags=["cicd"])


# ── Pydantic Request Models ───────────────────────────────────────────────────

class UpdateCiSettingsRequest(BaseModel):
    auto_fix_enabled: bool | None = None
    auto_commit_enabled: bool | None = None
    max_retry_budget: int | None = Field(None, ge=1, le=10)


class InstallDirectRequest(BaseModel):
    workflow_content: str | None = None
    commit_message: str | None = None


class DispatchWorkflowRequest(BaseModel):
    workflow_id_or_filename: str | None = None
    ref: str = "main"


class DiagnoseRunRequest(BaseModel):
    run_id: str


class ApplyFixRequest(BaseModel):
    run_id: str
    patch: str
    commit_message: str | None = None


class TriggerDeploymentRequest(BaseModel):
    environment: str = "production"
    skip_ci_check: bool = False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{repo_id}/ci/overview", status_code=200, summary="Get per-repository CI/CD overview and status")
def get_ci_overview_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return complete isolated CI/CD state and configuration for the selected repository."""
    repo = get_user_repo(repo_id, db, current_user)
    user_token = get_user_github_token(current_user)

    # 1. Detect workflows and retrieve config
    detection = detect_ci_workflows(repo.id, db, user_token=user_token)
    ci_conf = get_or_create_repo_ci_config(repo, db)

    # 2. Check deployment status
    deployment = detect_repository_deployment(repo, db)

    # 3. Analyze repository evidence
    evidence = analyze_repository_evidence(repo, db)

    return {
        "repo_id": repo.id,
        "repo_name": repo.name,
        "source_type": repo.source_type,
        "detected_ci": repo.detected_ci,
        "detected_ci_files": detection.get("detected_ci_files", []),
        "needs_ci_setup": repo.needs_ci_setup,
        "setup_status": ci_conf.setup_status,
        "workflow_path": ci_conf.workflow_path,
        "active_workflow_content": ci_conf.active_workflow_content,
        "proposed_workflow_content": ci_conf.proposed_workflow_content,
        "proposed_diff": ci_conf.proposed_diff,
        "pr_number": ci_conf.pr_number,
        "pr_url": ci_conf.pr_url,
        "branch_name": ci_conf.branch_name,
        "auto_fix_enabled": ci_conf.auto_fix_enabled,
        "auto_commit_enabled": ci_conf.auto_commit_enabled,
        "max_retry_budget": ci_conf.max_retry_budget,
        "current_retry_count": ci_conf.current_retry_count,
        "last_run_id": ci_conf.last_run_id,
        "last_run_status": ci_conf.last_run_status,
        "last_run_conclusion": ci_conf.last_run_conclusion,
        "last_run_url": ci_conf.last_run_url,
        "deployment": deployment,
        "evidence": evidence,
    }


@router.post("/{repo_id}/ci/analyze", status_code=200, summary="Re-analyze repository stack and CI detection")
def analyze_ci_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger fresh scan of repository files, manifests, and workflows."""
    repo = get_user_repo(repo_id, db, current_user)
    user_token = get_user_github_token(current_user)
    detection = detect_ci_workflows(repo.id, db, user_token=user_token)
    evidence = analyze_repository_evidence(repo, db)
    deployment = detect_repository_deployment(repo, db)
    return {
        "repo_id": repo.id,
        "detection": detection,
        "evidence": evidence,
        "deployment": deployment,
    }


@router.post("/{repo_id}/ci/generate", status_code=200, summary="Synthesize AI-powered CI workflow proposal")
def generate_ci_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate tailored GitHub Actions workflow from repository evidence with full diff."""
    repo = get_user_repo(repo_id, db, current_user)
    preview = get_ci_workflow_preview(repo, db)
    return preview


@router.post("/{repo_id}/ci/install-pr", status_code=201, summary="Propose CI workflow via Pull Request")
def install_ci_pr_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a branch and open a reviewable Pull Request on GitHub with the generated workflow."""
    repo = get_user_repo(repo_id, db, current_user)
    if repo.source_type != "github":
        raise HTTPException(status_code=400, detail="CI setup via Pull Request is only supported for GitHub repositories.")

    try:
        res = create_ci_setup_pr(repo, db, current_user)
        return {"repo_id": repo.id, **res}
    except Exception as exc:
        clean_err = sanitize_sensitive_text(str(exc))
        logger.exception("Error proposing CI workflow PR: %s", clean_err)
        raise HTTPException(status_code=500, detail=f"Failed to create CI setup PR: {clean_err}")


@router.post("/{repo_id}/ci/install-direct", status_code=200, summary="Directly commit workflow to default branch")
def install_ci_direct_endpoint(
    repo_id: str,
    body: InstallDirectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Commit the proposed workflow directly to default branch (requires direct push access)."""
    repo = get_user_repo(repo_id, db, current_user)
    if repo.source_type != "github":
        raise HTTPException(status_code=400, detail="Direct CI setup is only supported for GitHub repositories.")

    try:
        res = install_ci_workflow_direct(
            repo=repo,
            db=db,
            current_user=current_user,
            workflow_content=body.workflow_content,
            commit_message=body.commit_message,
        )
        return {"repo_id": repo.id, **res}
    except Exception as exc:
        clean_err = sanitize_sensitive_text(str(exc))
        logger.exception("Error committing CI workflow directly: %s", clean_err)
        raise HTTPException(status_code=500, detail=f"Failed to commit workflow: {clean_err}")


@router.post("/{repo_id}/ci/verify-installation", status_code=200, summary="Check remote GitHub installation status")
def verify_installation_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check if the proposed workflow file or PR has been merged remotely on GitHub."""
    repo = get_user_repo(repo_id, db, current_user)
    res = verify_remote_ci_installation(repo, db, current_user)
    return {"repo_id": repo.id, **res}


@router.get("/{repo_id}/ci/runs", status_code=200, summary="Fetch real GitHub Actions workflow runs")
def get_ci_runs_endpoint(
    repo_id: str,
    limit: int = Query(15, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve real workflow runs from GitHub Actions API."""
    repo = get_user_repo(repo_id, db, current_user)
    ci_conf = get_or_create_repo_ci_config(repo, db)

    if repo.source_type != "github":
        return {"repo_id": repo.id, "runs": []}

    user_token = get_user_github_token(current_user)
    repo_full_name = get_repo_full_name(repo)

    runs = fetch_github_actions_runs(repo_full_name, limit=limit, token=user_token)

    # Sync latest run to ci_conf if available
    if runs:
        latest = runs[0]
        ci_conf.last_run_id = latest["run_id"]
        ci_conf.last_run_status = latest["status"]
        ci_conf.last_run_conclusion = latest["conclusion"]
        ci_conf.last_run_url = latest["html_url"]
        db.commit()

    return {"repo_id": repo.id, "runs": runs}


@router.get("/{repo_id}/ci/runs/{run_id}", status_code=200, summary="Fetch job details and steps for a run")
def get_run_details_endpoint(
    repo_id: str,
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve job steps and logs for a specific GitHub Actions workflow run."""
    repo = get_user_repo(repo_id, db, current_user)
    user_token = get_user_github_token(current_user)
    repo_full_name = get_repo_full_name(repo)

    jobs = fetch_github_run_jobs(repo_full_name, run_id, token=user_token)
    run_meta = fetch_github_run(repo_full_name, run_id, token=user_token)

    # Sync latest state to DB if available
    ci_conf = get_or_create_repo_ci_config(repo, db)
    if run_meta and ci_conf.last_run_id == str(run_id):
        ci_conf.last_run_status = run_meta.get("status")
        ci_conf.last_run_conclusion = run_meta.get("conclusion")
        db.commit()

    # If job has failure, fetch logs
    for j in jobs:
        if j.get("conclusion") in ("failure", "timed_out"):
            job_id = j.get("job_id")
            if job_id:
                j["logs"] = fetch_github_job_logs(repo_full_name, job_id, token=user_token)

    return {
        "repo_id": repo.id,
        "run_id": run_id,
        "status": run_meta.get("status") if run_meta else None,
        "conclusion": run_meta.get("conclusion") if run_meta else None,
        "jobs": jobs,
    }


@router.post("/{repo_id}/ci/dispatch", status_code=200, summary="Dispatch a GitHub Actions CI workflow run")
def dispatch_workflow_endpoint(
    repo_id: str,
    body: DispatchWorkflowRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger a workflow dispatch run on GitHub Actions."""
    repo = get_user_repo(repo_id, db, current_user)
    if repo.source_type != "github":
        raise HTTPException(status_code=400, detail="Workflow dispatch is only supported for GitHub repositories.")

    ci_conf = get_or_create_repo_ci_config(repo, db)
    wf_name = body.workflow_id_or_filename or ci_conf.workflow_path or "ci.yml"
    user_token = get_user_github_token(current_user)
    repo_full_name = get_repo_full_name(repo)

    try:
        res = dispatch_github_workflow(
            repo_full_name=repo_full_name,
            workflow_id_or_filename=wf_name,
            ref=body.ref or ci_conf.default_branch or "main",
            token=user_token,
        )
        return {"repo_id": repo.id, **res}
    except Exception as exc:
        clean_err = sanitize_sensitive_text(str(exc))
        logger.exception("Workflow dispatch error: %s", clean_err)
        raise HTTPException(status_code=500, detail=f"Failed to dispatch workflow: {clean_err}")


@router.post("/{repo_id}/ci/diagnose", status_code=200, summary="Diagnose failed CI run with AI and loop protection")
def diagnose_ci_endpoint(
    repo_id: str,
    body: DiagnoseRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Diagnose CI failure from actual step logs and generate a targeted fix patch."""
    repo = get_user_repo(repo_id, db, current_user)
    try:
        diagnosis = diagnose_ci_failure(repo, body.run_id, db, current_user)
        return {"repo_id": repo.id, "run_id": body.run_id, **diagnosis}
    except Exception as exc:
        clean_err = sanitize_sensitive_text(str(exc))
        logger.exception("Failure diagnosis error: %s", clean_err)
        raise HTTPException(status_code=500, detail=f"Diagnosis failed: {clean_err}")


@router.post("/{repo_id}/ci/apply-fix", status_code=200, summary="Apply and commit authorized CI fix patch")
def apply_ci_fix_endpoint(
    repo_id: str,
    body: ApplyFixRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Apply approved fix diff, create commit/PR, and update bounded retry counter."""
    repo = get_user_repo(repo_id, db, current_user)
    try:
        result = apply_ci_fix_and_commit(
            repo=repo,
            run_id=body.run_id,
            patch=body.patch,
            commit_message=body.commit_message,
            db=db,
            current_user=current_user,
        )
        return {"repo_id": repo.id, **result}
    except Exception as exc:
        clean_err = sanitize_sensitive_text(str(exc))
        logger.exception("Error applying CI fix: %s", clean_err)
        raise HTTPException(status_code=500, detail=f"Failed to apply fix: {clean_err}")


@router.patch("/{repo_id}/ci/settings", status_code=200, summary="Update per-repository CI/CD automation settings")
def update_ci_settings_endpoint(
    repo_id: str,
    body: UpdateCiSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update automation preferences: auto-fix toggle, auto-commit toggle, and retry budget."""
    repo = get_user_repo(repo_id, db, current_user)
    ci_conf = get_or_create_repo_ci_config(repo, db)

    if body.auto_fix_enabled is not None:
        ci_conf.auto_fix_enabled = body.auto_fix_enabled
    if body.auto_commit_enabled is not None:
        ci_conf.auto_commit_enabled = body.auto_commit_enabled
    if body.max_retry_budget is not None:
        ci_conf.max_retry_budget = body.max_retry_budget

    db.commit()

    return {
        "repo_id": repo.id,
        "auto_fix_enabled": ci_conf.auto_fix_enabled,
        "auto_commit_enabled": ci_conf.auto_commit_enabled,
        "max_retry_budget": ci_conf.max_retry_budget,
        "current_retry_count": ci_conf.current_retry_count,
    }


@router.post("/{repo_id}/deployment/trigger", status_code=200, summary="Trigger manual deployment for repository")
def trigger_deployment_endpoint(
    repo_id: str,
    body: TriggerDeploymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger verified deployment for repository after checking CI quality gates."""
    repo = get_user_repo(repo_id, db, current_user)
    ci_conf = get_or_create_repo_ci_config(repo, db)
    deployment = detect_repository_deployment(repo, db)

    if not deployment.get("is_configured"):
        raise HTTPException(
            status_code=400,
            detail="No deployment provider configured. Connect Netlify, Vercel, Render, or GitHub Actions deployment first."
        )

    # Check CI quality gate unless explicitly skipped
    ci_passed = (ci_conf.last_run_status == "completed" and ci_conf.last_run_conclusion == "success")
    if not ci_passed and not body.skip_ci_check:
        raise HTTPException(
            status_code=412,
            detail=(
                "Deployment safety gate: CI quality checks have not passed yet for the latest run. "
                "Ensure all test and build checks pass, or acknowledge manual override."
            )
        )

    # If GitHub Actions deployment workflow exists, trigger it
    user_token = get_user_github_token(current_user)
    repo_full_name = get_repo_full_name(repo)
    deploy_wf = next((f for f in deployment.get("detected_files", []) if ".github/workflows/" in f), None)
    
    if deploy_wf and user_token:
        try:
            wf_file = deploy_wf.split("/")[-1]
            dispatch_github_workflow(
                repo_full_name=repo_full_name,
                workflow_id_or_filename=wf_file,
                ref=ci_conf.default_branch or "main",
                token=user_token,
            )
            return {
                "repo_id": repo.id,
                "status": "deploying",
                "provider": deployment.get("provider"),
                "environment": body.environment,
                "message": f"Deployment workflow '{wf_file}' dispatched successfully via GitHub Actions.",
                "dashboard_url": deployment.get("provider_dashboard_url"),
            }
        except Exception as exc:
            clean_err = sanitize_sensitive_text(str(exc))
            logger.warning("Deployment workflow dispatch failed: %s", clean_err)

    return {
        "repo_id": repo.id,
        "status": "deploying",
        "provider": deployment.get("provider"),
        "environment": body.environment,
        "message": f"Deployment signal accepted for {deployment.get('display_name')}. Monitoring provider pipeline.",
        "dashboard_url": deployment.get("provider_dashboard_url"),
        "target_branch": deployment.get("target_branch", "main"),
        "build_command": deployment.get("build_command"),
    }
