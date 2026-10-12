"""
backend/automation/ci_diagnosis.py
-----------------------------------
GitHub Actions CI failure diagnosis and AI-driven repair with bounded retries
and loop prevention.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from ai.config import TaskType
from ai.router import get_ai_router
from auth import get_user_github_token
from codefix.patch_safety import validate_patch_format_and_safety, apply_patch_safely
from gitops.git_ops import create_branch_and_commit, sanitize_sensitive_text
from gitops.github_actions import fetch_github_run_jobs, fetch_github_job_logs
from gitops.pr_client import create_pull_request
from models import Repo, RepoCiConfig, RepoCiRun, User

logger = logging.getLogger(__name__)


# ── Failure Classification ───────────────────────────────────────────────────

UNFIXABLE_PATTERNS = [
    (re.compile(r"(bad credentials|invalid token|authentication failed|permission denied to|resource not accessible by integration)", re.I), "permission_denied", "GitHub Token or API credential lacks required permissions."),
    (re.compile(r"(secret [A-Za-z0-9_]+ is not defined|missing required secret|env var .* not set)", re.I), "missing_secret", "A required repository secret or environment variable is missing in GitHub Settings."),
    (re.compile(r"(rate limit exceeded|api rate limit|quota exceeded)", re.I), "quota_exhausted", "GitHub API or third-party quota exhausted."),
    (re.compile(r"(no space left on device|runner machine lost communication|hosted runner unavailable)", re.I), "runner_outage", "Infrastructure or GitHub runner outage."),
]

FIXABLE_PATTERNS = [
    (re.compile(r"(FAILURES|AssertionError|FAILED tests/|pytest\.PytestAssertRewriteWarning)", re.I), "test_failure"),
    (re.compile(r"(SyntaxError:|NameError:|TypeError:|IndentationError:|ReferenceError:)", re.I), "syntax_error"),
    (re.compile(r"(ModuleNotFoundError:|ImportError:|Cannot find module|No module named)", re.I), "dependency_error"),
    (re.compile(r"(tsc --noEmit|error TS\d+:|Type error:|Module not found)", re.I), "type_error"),
    (re.compile(r"(build failed|failed to compile|npm ERR! code ELIFECYCLE)", re.I), "build_failure"),
]


def classify_failure_logs(log_text: str) -> tuple[str, bool, str]:
    """
    Classifies CI log output into category.
    Returns:
        (category, is_fixable, explanation)
    """
    # 1. Check unfixable patterns first
    for pat, cat, expl in UNFIXABLE_PATTERNS:
        if pat.search(log_text):
            return cat, False, expl

    # 2. Check fixable patterns
    for pat, cat in FIXABLE_PATTERNS:
        if pat.search(log_text):
            return cat, True, f"Automated fixable {cat.replace('_', ' ')} detected."

    return "unknown_failure", True, "General failure detected in CI execution."


def extract_failing_lines(log_text: str, max_lines: int = 50) -> str:
    """Extract most relevant error context lines from raw job log."""
    lines = log_text.splitlines()
    error_indices = []

    for idx, l in enumerate(lines):
        if any(kw in l.lower() for kw in ("error", "fail", "fatal", "exception", "assert")):
            error_indices.append(idx)

    if not error_indices:
        return "\n".join(lines[-max_lines:])

    # Grab window around first few errors and last error
    selected: set[int] = set()
    for e in error_indices[:5]:
        start = max(0, e - 5)
        end = min(len(lines), e + 15)
        selected.update(range(start, end))

    sorted_indices = sorted(selected)
    return "\n".join(lines[i] for i in sorted_indices[:max_lines])


def compute_failure_fingerprint(job_name: str, step_name: str, log_snippet: str) -> str:
    """Create normalized SHA256 fingerprint of failure to prevent infinite fix loops."""
    # Strip timestamps and memory addresses
    norm = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z", "", log_snippet)
    norm = re.sub(r"0x[0-9a-fA-F]+", "", norm)
    key = f"{job_name}:{step_name}:{norm.strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# ── Diagnosis & AI Patch Generation ──────────────────────────────────────────

def diagnose_ci_failure(
    repo: Repo,
    run_id: str,
    db: Session,
    current_user: User,
) -> dict[str, Any]:
    """
    Retrieve real failed step logs for a run, classify the failure, check retry limits,
    and generate an AI repair proposal if fixable.
    """
    from automation.ci_setup import get_repo_full_name
    user_token = get_user_github_token(current_user)
    repo_full_name = get_repo_full_name(repo)

    # 1. Fetch jobs from GitHub Actions
    jobs = fetch_github_run_jobs(repo_full_name, run_id, token=user_token)
    failed_job = next((j for j in jobs if j.get("conclusion") in ("failure", "timed_out")), None)

    if not failed_job and jobs:
        failed_job = jobs[0]

    job_name = failed_job.get("name", "Build Job") if failed_job else "Unknown Job"
    job_id = failed_job.get("job_id") if failed_job else None

    # Find failing step
    failed_step_name = "Execution"
    if failed_job and failed_job.get("steps"):
        for step in failed_job["steps"]:
            if step.get("conclusion") in ("failure", "timed_out"):
                failed_step_name = step.get("name", "Execution")
                break

    # 2. Fetch logs
    raw_logs = ""
    if job_id:
        raw_logs = fetch_github_job_logs(repo_full_name, job_id, token=user_token)

    snippet = extract_failing_lines(raw_logs, max_lines=60)
    category, is_fixable, cat_expl = classify_failure_logs(snippet or raw_logs)
    fingerprint = compute_failure_fingerprint(job_name, failed_step_name, snippet)

    # 3. Retrieve or create RepoCiConfig and RepoCiRun
    ci_conf: RepoCiConfig = (
        db.query(RepoCiConfig).filter(RepoCiConfig.repo_id == repo.id).first()
    )
    if not ci_conf:
        ci_conf = RepoCiConfig(
            repo_id=repo.id,
            provider="github_actions",
            default_branch="main",
            setup_status="installed",
        )
        db.add(ci_conf)
        db.commit()

    run_record: RepoCiRun | None = (
        db.query(RepoCiRun)
        .filter(RepoCiRun.repo_id == repo.id, RepoCiRun.run_id == str(run_id))
        .first()
    )
    if not run_record:
        run_record = RepoCiRun(
            repo_id=repo.id,
            run_id=str(run_id),
            status="completed",
            conclusion="failure",
            failed_job_name=job_name,
            failed_step_name=failed_step_name,
            failure_category=category,
            logs_summary=snippet,
        )
        db.add(run_record)
        db.commit()

    # 4. Check Loop Prevention Safeguards
    if not is_fixable:
        diagnosis_text = (
            f"### 🛑 External / Unfixable Blocker: {category.upper()}\n\n"
            f"{cat_expl}\n\n"
            f"**Action Required**: Do not modify application code. Please review your GitHub repository settings, "
            f"secrets, or credentials."
        )
        run_record.fix_status = "blocked"
        run_record.ai_diagnosis = diagnosis_text
        db.commit()
        return {
            "is_fixable": False,
            "category": category,
            "status": "blocked",
            "message": cat_expl,
            "diagnosis": diagnosis_text,
            "failed_job": job_name,
            "failed_step": failed_step_name,
            "fingerprint": fingerprint,
            "retry_count": ci_conf.current_retry_count,
            "retry_budget": ci_conf.max_retry_budget,
            "log_snippet": snippet,
        }

    # Check retry budget
    if ci_conf.current_retry_count >= ci_conf.max_retry_budget:
        msg = f"Automatic fix retry budget exhausted ({ci_conf.current_retry_count}/{ci_conf.max_retry_budget} attempts used). Halting automated retries."
        run_record.fix_status = "exhausted"
        run_record.ai_diagnosis = f"### ⚠️ Retry Budget Exhausted\n\n{msg}"
        db.commit()
        return {
            "is_fixable": False,
            "category": category,
            "status": "exhausted",
            "message": msg,
            "diagnosis": run_record.ai_diagnosis,
            "failed_job": job_name,
            "failed_step": failed_step_name,
            "fingerprint": fingerprint,
            "retry_count": ci_conf.current_retry_count,
            "retry_budget": ci_conf.max_retry_budget,
            "log_snippet": snippet,
        }

    # Check duplicate failure fingerprint
    if ci_conf.last_failure_fingerprint == fingerprint and ci_conf.current_retry_count > 0:
        msg = "Identical failure fingerprint detected from previous fix attempt. Halting to prevent infinite loop."
        run_record.fix_status = "blocked"
        run_record.ai_diagnosis = f"### 🔄 Duplicate Failure Detected\n\n{msg}"
        db.commit()
        return {
            "is_fixable": False,
            "category": category,
            "status": "blocked",
            "message": msg,
            "diagnosis": run_record.ai_diagnosis,
            "failed_job": job_name,
            "failed_step": failed_step_name,
            "fingerprint": fingerprint,
            "retry_count": ci_conf.current_retry_count,
            "retry_budget": ci_conf.max_retry_budget,
            "log_snippet": snippet,
        }

    # 5. Invoke AI Router to diagnose root cause and generate minimal patch
    prompt = f"""You are an automated CI/CD debugging assistant for CodeBrain.
A GitHub Actions workflow run failed. Analyze the failure evidence and provide:
1. Root cause explanation (1-2 sentences).
2. A targeted unified diff patch to repair the failing code or test.

Repository: {repo.name}
Failed Job: {job_name}
Failed Step: {failed_step_name}
Failure Classification: {category}

Failing Log Snippet:
```
{snippet}
```

Format your response in markdown. If you propose code changes, include a standard unified diff block:
```diff
--- a/path/to/file.py
+++ b/path/to/file.py
@@ ... @@
-old code
+new code
```
"""
    ai_diagnosis = ""
    proposed_patch = ""

    try:
        router = get_ai_router()
        messages = [
            {"role": "system", "content": "You are a senior DevOps and software testing engineer. Provide precise diagnosis and minimal targeted unified diffs."},
            {"role": "user", "content": prompt},
        ]
        res = router.complete(TaskType.CODE_FIX, messages, max_tokens=2000, temperature=0.1)
        ai_diagnosis = res.get("content", "")

        # Extract diff if present
        diff_match = re.search(r"```diff\n(.*?)```", ai_diagnosis, re.DOTALL)
        if diff_match:
            proposed_patch = diff_match.group(1).strip()
    except Exception as exc:
        logger.warning("AI diagnosis call failed: %s. Using structured diagnosis.", exc)
        ai_diagnosis = (
            f"### Root Cause Diagnosis: {category.replace('_', ' ').title()}\n\n"
            f"The job `{job_name}` failed at step `{failed_step_name}`.\n\n"
            f"**Error Summary**:\n```\n{snippet[:400]}\n```"
        )

    run_record.ai_diagnosis = ai_diagnosis
    run_record.fix_status = "fix_proposed" if proposed_patch else "diagnosing"
    ci_conf.last_failure_fingerprint = fingerprint
    db.commit()

    return {
        "is_fixable": True,
        "category": category,
        "status": "fix_proposed" if proposed_patch else "diagnosed",
        "failed_job": job_name,
        "failed_step": failed_step_name,
        "diagnosis": ai_diagnosis,
        "proposed_patch": proposed_patch,
        "fingerprint": fingerprint,
        "retry_count": ci_conf.current_retry_count,
        "retry_budget": ci_conf.max_retry_budget,
        "log_snippet": snippet,
    }


def apply_ci_fix_and_commit(
    repo: Repo,
    run_id: str,
    patch: str,
    commit_message: str | None,
    db: Session,
    current_user: User,
) -> dict[str, Any]:
    """
    Apply authorized AI fix diff, commit to GitHub, and record state.
    Increments retry counter and records commit origin.
    """
    ci_conf: RepoCiConfig = (
        db.query(RepoCiConfig).filter(RepoCiConfig.repo_id == repo.id).first()
    )
    if not ci_conf:
        raise ValueError("CI Configuration not found for repository.")

    if not patch or not patch.strip():
        raise ValueError("Patch is empty. Cannot apply fix.")

    user_token = get_user_github_token(current_user)
    branch_name = f"codebrain/fix-ci-{run_id[-6:]}"
    msg = commit_message or f"fix(ci): repair failing test for CI run #{run_id} [CodeBrain Auto-Fix]"

    # 1. Branch & Commit via GitOps
    branch_result = create_branch_and_commit(
        repo_id=repo.id,
        patch=patch,
        branch_name=branch_name,
        commit_message=msg,
        token=user_token,
    )

    # 2. Open Pull Request on GitHub
    pr_result = create_pull_request(
        repo_full_name=branch_result.remote_url,
        branch_name=branch_name,
        base_branch=getattr(branch_result, "default_branch", "main") or "main",
        title=f"[CodeBrain Fix] Repair failing CI run #{run_id}",
        body=(
            f"## 🤖 Automated CI Repair\n\n"
            f"CodeBrain diagnosed a failure in workflow run `#{run_id}` and prepared this patch.\n\n"
            f"### Proposed Fix Commit: `{branch_result.commit_sha[:8]}`\n"
            f"Once merged, GitHub Actions will rerun verification checks automatically."
        ),
        token=user_token,
    )

    # 3. Update retry count and run record
    ci_conf.current_retry_count += 1
    run_record = (
        db.query(RepoCiRun)
        .filter(RepoCiRun.repo_id == repo.id, RepoCiRun.run_id == str(run_id))
        .first()
    )
    if run_record:
        run_record.fix_status = "fix_committed"
        run_record.fix_commit_sha = branch_result.commit_sha
        run_record.fix_pr_url = pr_result.get("pr_url")
    db.commit()

    return {
        "status": "fix_committed",
        "commit_sha": branch_result.commit_sha,
        "branch_name": branch_name,
        "pr_url": pr_result.get("pr_url"),
        "pr_number": pr_result.get("pr_number"),
        "current_retry_count": ci_conf.current_retry_count,
        "max_retry_budget": ci_conf.max_retry_budget,
    }
