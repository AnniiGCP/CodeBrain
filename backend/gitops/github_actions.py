"""
backend/gitops/github_actions.py
---------------------------------
GitHub Actions and Repository REST API client.
Provides:
  - Workflow inspection (detecting .github/workflows/*.yml)
  - Workflow run fetching (real GitHub Actions runs, jobs, steps, logs)
  - Workflow dispatch (triggering CI runs)
  - Remote file and PR verification
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Any

import httpx

from gitops.pr_client import _extract_owner_repo, _get_headers, GITHUB_API_BASE

logger = logging.getLogger(__name__)


def fetch_remote_workflow_files(
    repo_full_name: str,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """
    List workflow files under .github/workflows from the remote GitHub repository.
    Returns list of dicts with {name, path, html_url, download_url, sha}.
    """
    try:
        owner, repo = _extract_owner_repo(repo_full_name)
        headers = _get_headers(token=token, require_token=False)
        api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/.github/workflows"

        with httpx.Client(timeout=15) as client:
            resp = client.get(api_url, headers=headers)
        if resp.status_code == 404:
            return []
        if not resp.is_success:
            logger.warning("Error fetching remote workflows for %s/%s [%d]: %s", owner, repo, resp.status_code, resp.text)
            return []

        data = resp.json()
        if not isinstance(data, list):
            return []

        workflows = []
        for item in data:
            name = item.get("name", "")
            if name.endswith(".yml") or name.endswith(".yaml"):
                workflows.append({
                    "name": name,
                    "path": item.get("path", f".github/workflows/{name}"),
                    "html_url": item.get("html_url"),
                    "download_url": item.get("download_url"),
                    "sha": item.get("sha"),
                })
        return workflows
    except Exception as exc:
        logger.warning("Failed to fetch remote workflows for %s/%s: %s", owner, repo, exc)
        return []


def fetch_remote_file_content(
    repo_full_name: str,
    path: str,
    ref: str | None = None,
    token: str | None = None,
) -> str | None:
    """Fetch raw UTF-8 content of a file from remote GitHub repository."""
    try:
        owner, repo = _extract_owner_repo(repo_full_name)
        headers = _get_headers(token=token, require_token=False)
        clean_path = path.lstrip("/")
        api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{clean_path}"
        params = {}
        if ref:
            params["ref"] = ref

        with httpx.Client(timeout=15) as client:
            resp = client.get(api_url, headers=headers, params=params)
        if not resp.is_success:
            return None
        data = resp.json()
        content_b64 = data.get("content", "")
        if content_b64:
            return base64.b64decode(content_b64).decode("utf-8", errors="replace")
        return None
    except Exception as exc:
        logger.warning("Failed to fetch file content for %s at %s: %s", repo_full_name, path, exc)
        return None


def check_remote_file_exists(
    repo_full_name: str,
    path: str,
    ref: str | None = None,
    token: str | None = None,
) -> bool:
    """Check if a file exists on remote repository at given ref/branch."""
    content = fetch_remote_file_content(repo_full_name, path, ref=ref, token=token)
    return content is not None


def check_pr_merged(
    repo_full_name: str,
    pr_number: int,
    token: str | None = None,
) -> bool:
    """Check whether a pull request has been merged into base branch."""
    try:
        owner, repo = _extract_owner_repo(repo_full_name)
        headers = _get_headers(token=token, require_token=False)
        api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}"

        with httpx.Client(timeout=15) as client:
            resp = client.get(api_url, headers=headers)
        if not resp.is_success:
            return False
        data = resp.json()
        return bool(data.get("merged", False))
    except Exception as exc:
        logger.warning("Failed to check PR merge status for %s PR#%d: %s", repo_full_name, pr_number, exc)
        return False


def fetch_github_actions_runs(
    repo_full_name: str,
    limit: int = 15,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch workflow runs from GitHub Actions API.
    Returns list of run metadata dictionaries.
    """
    try:
        owner, repo = _extract_owner_repo(repo_full_name)
        headers = _get_headers(token=token, require_token=False)
        api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/actions/runs"
        params = {"per_page": min(limit, 50)}

        with httpx.Client(timeout=20) as client:
            resp = client.get(api_url, headers=headers, params=params)
        if not resp.is_success:
            logger.warning("GitHub Actions runs fetch failed [%d]: %s", resp.status_code, resp.text)
            return []

        data = resp.json()
        raw_runs = data.get("workflow_runs", [])
        results = []
        for r in raw_runs:
            results.append({
                "run_id": str(r.get("id")),
                "run_number": r.get("run_number"),
                "workflow_id": r.get("workflow_id"),
                "name": r.get("name") or "CI Workflow",
                "path": r.get("path") or ".github/workflows/ci.yml",
                "event": r.get("event"),
                "status": r.get("status"),          # queued, in_progress, completed
                "conclusion": r.get("conclusion"),  # success, failure, neutral, cancelled, timed_out, etc.
                "html_url": r.get("html_url"),
                "head_branch": r.get("head_branch"),
                "head_sha": r.get("head_sha"),
                "commit_message": (r.get("head_commit") or {}).get("message", ""),
                "created_at": r.get("created_at"),
                "updated_at": r.get("updated_at"),
                "run_started_at": r.get("run_started_at"),
            })
        return results
    except Exception as exc:
        logger.warning("Failed to fetch GitHub Actions runs for %s/%s: %s", owner, repo, exc)
        return []


def fetch_github_run(
    repo_full_name: str,
    run_id: str | int,
    token: str | None = None,
) -> dict[str, Any] | None:
    """Fetch single workflow run metadata directly from GitHub Actions API."""
    try:
        owner, repo = _extract_owner_repo(repo_full_name)
        headers = _get_headers(token=token, require_token=False)
        api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/actions/runs/{run_id}"

        with httpx.Client(timeout=15) as client:
            resp = client.get(api_url, headers=headers)
        if not resp.is_success:
            return None
        r = resp.json()
        return {
            "run_id": str(r.get("id")),
            "run_number": r.get("run_number"),
            "workflow_id": r.get("workflow_id"),
            "name": r.get("name") or "CI Workflow",
            "path": r.get("path") or ".github/workflows/ci.yml",
            "event": r.get("event"),
            "status": r.get("status"),
            "conclusion": r.get("conclusion"),
            "html_url": r.get("html_url"),
            "head_branch": r.get("head_branch"),
            "head_sha": r.get("head_sha"),
            "commit_message": (r.get("head_commit") or {}).get("message", ""),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "run_started_at": r.get("run_started_at"),
        }
    except Exception as exc:
        logger.warning("Failed to fetch run %s for %s: %s", run_id, repo_full_name, exc)
        return None


def fetch_github_run_jobs(
    repo_full_name: str,
    run_id: str | int,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch jobs and steps for a specific workflow run."""
    try:
        owner, repo = _extract_owner_repo(repo_full_name)
        headers = _get_headers(token=token, require_token=False)
        api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"

        with httpx.Client(timeout=20) as client:
            resp = client.get(api_url, headers=headers)
        if not resp.is_success:
            return []
        data = resp.json()
        raw_jobs = data.get("jobs", [])
        jobs = []
        for j in raw_jobs:
            steps = []
            for s in j.get("steps", []):
                steps.append({
                    "name": s.get("name"),
                    "status": s.get("status"),
                    "conclusion": s.get("conclusion"),
                    "number": s.get("number"),
                    "started_at": s.get("started_at"),
                    "completed_at": s.get("completed_at"),
                })
            jobs.append({
                "job_id": str(j.get("id")),
                "name": j.get("name"),
                "status": j.get("status"),
                "conclusion": j.get("conclusion"),
                "html_url": j.get("html_url"),
                "started_at": j.get("started_at"),
                "completed_at": j.get("completed_at"),
                "steps": steps,
            })
        return jobs
    except Exception as exc:
        logger.warning("Failed to fetch jobs for run %s (%s): %s", run_id, repo_full_name, exc)
        return []


def fetch_github_job_logs(
    repo_full_name: str,
    job_id: str | int,
    token: str | None = None,
) -> str:
    """Fetch raw logs for a job via GitHub Actions API, following redirects."""
    try:
        owner, repo = _extract_owner_repo(repo_full_name)
        headers = _get_headers(token=token, require_token=False)
        api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/actions/jobs/{job_id}/logs"

        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(api_url, headers=headers)
        if not resp.is_success:
            return f"Log output unavailable (HTTP {resp.status_code})"
        return resp.text
    except Exception as exc:
        logger.warning("Failed to fetch logs for job %s: %s", job_id, exc)
        return f"Log fetch failed: {exc}"


def dispatch_github_workflow(
    repo_full_name: str,
    workflow_id_or_filename: str,
    ref: str = "main",
    inputs: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """
    Trigger workflow dispatch event on GitHub Actions.
    Requires workflow to have `workflow_dispatch` trigger.
    """
    owner, repo = _extract_owner_repo(repo_full_name)
    headers = _get_headers(token=token, require_token=True)
    clean_wf = workflow_id_or_filename.split("/")[-1]
    api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/actions/workflows/{clean_wf}/dispatches"

    payload: dict[str, Any] = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs

    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(api_url, headers=headers, json=payload)
        if resp.status_code == 204:
            logger.info("Successfully dispatched workflow %s on %s/%s (ref=%s)", clean_wf, owner, repo, ref)
            return {"status": "dispatched", "workflow": clean_wf, "ref": ref}
        clean_text = resp.text.replace("\n", " ").strip()
        raise RuntimeError(f"Workflow dispatch failed [{resp.status_code}]: {clean_text}")
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Network error during workflow dispatch: {exc}")


def create_or_update_remote_file(
    repo_full_name: str,
    path: str,
    content: str,
    commit_message: str,
    branch: str = "main",
    token: str | None = None,
) -> dict[str, Any]:
    """
    Create or update a file in a remote GitHub repository via the GitHub Contents API.
    Does not use local git push or CLI; completely avoids token exposure and URL issues.
    """
    owner, repo = _extract_owner_repo(repo_full_name)
    headers = _get_headers(token=token, require_token=True)
    clean_path = path.lstrip("/")
    api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{clean_path}"

    # 1. Check if the file already exists on this branch to obtain its current SHA
    current_sha: str | None = None
    try:
        with httpx.Client(timeout=15) as client:
            get_resp = client.get(api_url, headers=headers, params={"ref": branch})
            if get_resp.status_code == 200:
                current_sha = get_resp.json().get("sha")
    except Exception as exc:
        logger.warning("Could not check existing file SHA for %s/%s at %s: %s", owner, repo, clean_path, exc)

    # 2. Prepare payload with base64 encoded content
    content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    payload: dict[str, Any] = {
        "message": commit_message,
        "content": content_b64,
        "branch": branch,
    }
    if current_sha:
        payload["sha"] = current_sha

    # 3. Send PUT request
    try:
        with httpx.Client(timeout=25) as client:
            resp = client.put(api_url, headers=headers, json=payload)

        if resp.status_code in (200, 201):
            data = resp.json()
            commit_data = data.get("commit", {})
            return {
                "status": "success",
                "commit_sha": commit_data.get("sha", ""),
                "commit_url": commit_data.get("html_url", ""),
                "file_path": clean_path,
                "branch": branch,
                "message": f"Successfully committed {clean_path} to {branch} via GitHub API.",
            }

        # Handle specific error status codes
        if resp.status_code == 403:
            err_msg = resp.text.lower()
            if "protected" in err_msg:
                raise RuntimeError(
                    f"Direct commit to branch '{branch}' is blocked by GitHub branch protection rules. "
                    "Please use 'Install via Pull Request' to propose the workflow safely."
                )
            raise RuntimeError(
                f"GitHub permission error (HTTP 403) updating {clean_path}. "
                "Ensure your token has 'workflow' or 'repo' write permissions."
            )
        if resp.status_code == 409:
            raise RuntimeError(
                f"Conflict on branch '{branch}' when updating {clean_path}. "
                "The remote branch has diverged; please refresh or use a Pull Request."
            )
        if resp.status_code == 404:
            raise RuntimeError(
                f"Repository or branch '{branch}' not found on GitHub. "
                "Verify repository permissions and default branch."
            )

        clean_err = resp.text.replace("\n", " ").strip()
        raise RuntimeError(f"GitHub API file commit failed [HTTP {resp.status_code}]: {clean_err}")

    except httpx.HTTPError as exc:
        raise RuntimeError(f"Network error communicating with GitHub API: {exc}")


def get_remote_default_branch(repo_full_name: str, token: str | None = None) -> str:
    """Query GitHub API for repository default branch (e.g. main vs master)."""
    try:
        owner, repo = _extract_owner_repo(repo_full_name)
        headers = _get_headers(token=token)
        api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        with httpx.Client(timeout=15) as client:
            resp = client.get(api_url, headers=headers)
        if resp.is_success:
            return resp.json().get("default_branch") or "main"
    except Exception:
        pass
    return "main"
