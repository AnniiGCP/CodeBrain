"""
gitops/pr_client.py
-------------------
GitHub Pull Request client using GitHub REST API v3 and GraphQL API v4.

Public API:
-----------
- create_pull_request(repo_full_name, branch_name, base_branch, title, body) -> dict
- enable_auto_merge(repo_full_name, pr_number, merge_method) -> bool
- get_pr_status(repo_full_name, pr_number) -> dict
- open_pull_request(branch_result, title, body, base_branch, auto_complete) -> PullRequestResult

Environment variables:
----------------------
GITHUB_TOKEN — GitHub Personal Access Token or fine-grained token with repo scope.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from gitops.git_ops import BranchResult, Provider

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_GRAPHQL_ENDPOINT = "https://api.github.com/graphql"


# ── Exception Classes ─────────────────────────────────────────────────────────

class AutoMergeError(RuntimeError):
    """Base error for auto-merge failures."""
    pass


class AutoMergeNotAllowedError(AutoMergeError):
    """Raised when repository settings do not have 'Allow auto-merge' enabled."""
    pass


class BranchProtectionMissingError(AutoMergeError):
    """Raised when branch protection or required status checks are missing."""
    pass


class GitHubPermissionError(AutoMergeError):
    """Raised when token lacks required scopes/permissions."""
    pass


# ── Result Dataclass ──────────────────────────────────────────────────────────

@dataclass
class PullRequestResult:
    pr_url: str
    pr_number: int | None
    provider: Provider
    title: str
    base_branch: str
    head_branch: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_github_token() -> str:
    """Retrieve GITHUB_TOKEN from environment, raising a clear error if missing."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token or token.lower() in ("your_github_token", "your_github_fine_grained_pat"):
        raise EnvironmentError(
            "GITHUB_TOKEN environment variable is required for GitHub operations. "
            "Please set a valid GitHub token in backend/.env"
        )
    return token


def _get_headers(token: str | None = None) -> dict[str, str]:
    """Build standard GitHub REST / GraphQL authorization headers."""
    t = token or _get_github_token()
    return {
        "Authorization": f"Bearer {t}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class UnsupportedProviderError(AutoMergeError):
    """Raised when repository URL belongs to an unsupported provider (e.g. Azure DevOps)."""
    pass


def extract_pr_number_from_url(url: str) -> int | None:
    """Extract integer pull request number from a GitHub or git PR URL (e.g. /pull/123)."""
    if not url:
        return None
    m = re.search(r"/pull(?:request)?/(\d+)", str(url), re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _extract_owner_repo(repo_full_name_or_url: str) -> tuple[str, str]:
    """
    Extract (owner, repo) from:
      - 'owner/repo'
      - 'https://github.com/owner/repo.git'
      - 'https://github.com/owner/repo'
      - 'https://github.com/owner/repo/pull/123'
      - 'git@github.com:owner/repo.git'

    Separates repository identity from PR identity, and rejects Azure DevOps URLs
    with UnsupportedProviderError.
    """
    if not repo_full_name_or_url:
        raise ValueError("Repository identifier or URL cannot be empty.")

    cleaned = str(repo_full_name_or_url).strip()

    # Route Azure DevOps URLs to clear unsupported exception
    if "dev.azure.com" in cleaned.lower() or "visualstudio.com" in cleaned.lower():
        raise UnsupportedProviderError(
            f"Azure DevOps repository operations are not supported by the GitHub provider: '{cleaned}'"
        )

    # Match standard owner/repo pattern (slug only)
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", cleaned):
        parts = cleaned.split("/", 1)
        return parts[0], parts[1].removesuffix(".git")

    # SSH format: git@github.com:owner/repo.git
    ssh_match = re.match(r"^git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$", cleaned)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    # URL parser: robustly handle /owner/repo, /owner/repo/pull/123, /owner/repo.git, query strings, etc.
    if "://" in cleaned:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(cleaned)
            hostname = (parsed.hostname or "").lower()
            if "github.com" in hostname:
                segments = [p for p in parsed.path.strip("/").split("/") if p]
                if len(segments) >= 2:
                    return segments[0], segments[1].removesuffix(".git")
        except Exception:
            pass

    # Match GitHub URL pattern via regex fallback
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git|/.*|\?.*)?$", cleaned)
    if m:
        return m.group(1), m.group(2)

    raise ValueError(
        f"Invalid GitHub repository identifier or URL: '{repo_full_name_or_url}'. "
        "Expected 'owner/repo' or a valid GitHub repository URL."
    )


# ── 1. Create Pull Request ───────────────────────────────────────────────────

def create_pull_request(
    repo_full_name: str,
    branch_name: str,
    base_branch: str = "main",
    title: str = "",
    body: str = "",
    token: str | None = None,
) -> dict[str, Any]:
    """
    Create a Pull Request on GitHub via REST API v3.

    Args:
        repo_full_name: 'owner/repo' or full GitHub URL.
        branch_name:    Name of the feature / fix branch (head).
        base_branch:    Target branch to merge into (default: 'main').
        title:          Pull request title.
        body:           Pull request description.
        token:          Optional user-specific GitHub token.

    Returns:
        dict with keys: 'pr_number', 'pr_url', 'node_id', 'title', 'base_branch', 'head_branch'.

    Raises:
        EnvironmentError: If GITHUB_TOKEN is missing.
        ValueError:       If repo_full_name is invalid or not GitHub.
        RuntimeError:     If the GitHub API returns an error response.
    """
    owner, repo = _extract_owner_repo(repo_full_name)
    headers = _get_headers(token=token)
    api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls"

    payload = {
        "title": title or f"Update from {branch_name}",
        "body": body or "Automated Pull Request",
        "head": branch_name,
        "base": base_branch,
        "draft": False,
    }

    with httpx.Client(timeout=25) as client:
        resp = client.post(api_url, json=payload, headers=headers)

    # If PR already exists (422), find and return the existing open PR
    if resp.status_code == 422:
        error_text = resp.text.lower()
        if "pull request already exists" in error_text or "a pull request already exists" in error_text:
            logger.info("PR already exists for %s:%s -> %s. Searching existing PR...", owner, branch_name, base_branch)
            return _find_existing_pr(owner, repo, branch_name, base_branch, headers)
        raise RuntimeError(f"GitHub PR creation failed [{resp.status_code}]: {resp.text}")

    if not resp.is_success:
        raise RuntimeError(f"GitHub PR creation failed [{resp.status_code}]: {resp.text}")

    data = resp.json()
    pr_number = data["number"]
    pr_url = data["html_url"]
    node_id = data.get("node_id")

    logger.info("Created GitHub PR #%d: %s (%s/%s)", pr_number, pr_url, owner, repo)

    return {
        "pr_number": pr_number,
        "pr_url": pr_url,
        "node_id": node_id,
        "title": data.get("title", title),
        "base_branch": base_branch,
        "head_branch": branch_name,
    }


def _find_existing_pr(
    owner: str,
    repo: str,
    head_branch: str,
    base_branch: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Find an existing open pull request for the branch."""
    api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls"
    params = {
        "head": f"{owner}:{head_branch}",
        "base": base_branch,
        "state": "open",
    }
    with httpx.Client(timeout=15) as client:
        resp = client.get(api_url, params=params, headers=headers)

    if resp.is_success and resp.json():
        pr = resp.json()[0]
        return {
            "pr_number": pr["number"],
            "pr_url": pr["html_url"],
            "node_id": pr.get("node_id"),
            "title": pr.get("title", ""),
            "base_branch": base_branch,
            "head_branch": head_branch,
        }

    raise RuntimeError(
        f"PR reported to already exist, but could not locate open PR for {owner}:{head_branch} -> {base_branch}"
    )


# ── 2. Check Branch Protection & Required Status Checks ───────────────────────

def check_branch_protection(
    repo_full_name: str,
    branch: str = "main",
    token: str | None = None,
) -> dict[str, Any]:
    """
    Check whether the target branch has branch protection rules and required status checks.

    Args:
        repo_full_name: 'owner/repo' or GitHub repository URL.
        branch:         Target branch name (e.g. 'main').
        token:          Optional user-specific GitHub token.

    Returns:
        dict with:
          - 'has_protection': bool
          - 'has_required_checks': bool
          - 'required_checks': list[str]
          - 'reason': str | None
          - 'permission_error': bool
    """
    try:
        owner, repo = _extract_owner_repo(repo_full_name)
        headers = _get_headers(token=token)
        api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/branches/{branch}/protection"

        with httpx.Client(timeout=15) as client:
            resp = client.get(api_url, headers=headers)
    except EnvironmentError:
        return {
            "has_protection": True,
            "has_required_checks": True,
            "required_checks": [],
            "reason": None,
            "permission_error": True,
        }
    except Exception as exc:
        logger.warning("Error checking branch protection for %s/%s:%s: %s", repo_full_name, branch, exc)
        return {
            "has_protection": False,
            "has_required_checks": False,
            "required_checks": [],
            "reason": f"Network error querying branch protection: {exc}",
            "permission_error": False,
        }

    # 404: Branch protection is not enabled on this branch
    if resp.status_code == 404:
        return {
            "has_protection": False,
            "has_required_checks": False,
            "required_checks": [],
            "reason": f"Branch '{branch}' in {owner}/{repo} has no branch protection rules enabled.",
            "permission_error": False,
        }

    # 401 / 403: Insufficient token permissions to view protection rules
    if resp.status_code in (401, 403):
        return {
            "has_protection": False,
            "has_required_checks": False,
            "required_checks": [],
            "reason": "Token lacks permission to inspect branch protection settings.",
            "permission_error": True,
        }

    if not resp.is_success:
        return {
            "has_protection": False,
            "has_required_checks": False,
            "required_checks": [],
            "reason": f"GitHub returned status {resp.status_code} querying branch protection: {resp.text}",
            "permission_error": False,
        }

    data = resp.json()
    status_checks = data.get("required_status_checks")
    if not status_checks:
        return {
            "has_protection": True,
            "has_required_checks": False,
            "required_checks": [],
            "reason": f"Branch '{branch}' is protected, but has no required status checks configured.",
            "permission_error": False,
        }

    contexts = status_checks.get("contexts", [])
    checks = status_checks.get("checks", [])
    check_names = list(contexts) + [
        c.get("context") for c in checks if isinstance(c, dict) and c.get("context")
    ]

    has_checks = len(check_names) > 0
    return {
        "has_protection": True,
        "has_required_checks": has_checks,
        "required_checks": check_names,
        "reason": None if has_checks else f"Branch '{branch}' has required_status_checks enabled, but no check contexts listed.",
        "permission_error": False,
    }


# ── 3. Enable Auto-Merge ──────────────────────────────────────────────────────

def enable_auto_merge(
    repo_full_name: str,
    pr_number: int,
    merge_method: str = "squash",
    token: str | None = None,
) -> bool:
    """
    Enable auto-merge on a GitHub Pull Request using GraphQL API v4.

    Args:
        repo_full_name: 'owner/repo' or GitHub repository URL.
        pr_number:      Pull request number.
        merge_method:   'squash', 'merge', or 'rebase' (default: 'squash').
        token:          Optional user-specific GitHub token.

    Returns:
        bool: True if auto-merge was enabled successfully.

    Raises:
        AutoMergeNotAllowedError:      If repo settings do not have 'Allow auto-merge' enabled.
        GitHubPermissionError:         If token lacks write / merge permissions.
        AutoMergeError / RuntimeError: If GraphQL mutation fails or PR is invalid.
    """
    owner, repo = _extract_owner_repo(repo_full_name)
    headers = _get_headers(token=token)

    valid_methods = {"squash": "SQUASH", "merge": "MERGE", "rebase": "REBASE"}
    method_upper = valid_methods.get(merge_method.lower())
    if not method_upper:
        raise ValueError(
            f"Invalid merge_method '{merge_method}'. Supported methods: 'squash', 'merge', 'rebase'"
        )

    # Step 1: Query PR node ID via GraphQL (or fallback to REST)
    query_pr = """
    query GetPullRequestId($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          id
          autoMergeRequest {
            enabledAt
          }
        }
      }
    }
    """

    with httpx.Client(timeout=20) as client:
        resp = client.post(
            GITHUB_GRAPHQL_ENDPOINT,
            json={"query": query_pr, "variables": {"owner": owner, "name": repo, "number": pr_number}},
            headers=headers,
        )

    if resp.status_code in (401, 403):
        raise GitHubPermissionError(f"GitHub token lacks permission to access {owner}/{repo}: {resp.text}")

    if not resp.is_success:
        raise AutoMergeError(f"Failed to query PR node ID [{resp.status_code}]: {resp.text}")

    pr_query_data = resp.json()
    if "errors" in pr_query_data and pr_query_data["errors"]:
        error_msg = "; ".join(e.get("message", "Unknown error") for e in pr_query_data["errors"])
        err_lower = error_msg.lower()
        if "permission" in err_lower or "scope" in err_lower or "forbidden" in err_lower or "unauthorized" in err_lower:
            raise GitHubPermissionError(f"Token lacks permission on PR #{pr_number}: {error_msg}")
        raise AutoMergeError(f"GraphQL error fetching PR ID: {error_msg}")

    repo_data = pr_query_data.get("data", {}).get("repository")
    if not repo_data or not repo_data.get("pullRequest"):
        raise AutoMergeError(f"Pull request #{pr_number} not found in {owner}/{repo}")

    pr_node_id = repo_data["pullRequest"]["id"]

    # If auto-merge is already enabled, return True
    if repo_data["pullRequest"].get("autoMergeRequest"):
        logger.info("Auto-merge is already enabled on PR #%d in %s/%s", pr_number, owner, repo)
        return True

    # Step 2: Execute enablePullRequestAutoMerge mutation
    mutation = """
    mutation EnableAutoMerge($pullRequestId: ID!, $mergeMethod: PullRequestMergeMethod!) {
      enablePullRequestAutoMerge(input: {
        pullRequestId: $pullRequestId,
        mergeMethod: $mergeMethod
      }) {
        pullRequest {
          id
          autoMergeRequest {
            enabledAt
            mergeMethod
          }
        }
      }
    }
    """

    with httpx.Client(timeout=20) as client:
        mutation_resp = client.post(
            GITHUB_GRAPHQL_ENDPOINT,
            json={"query": mutation, "variables": {"pullRequestId": pr_node_id, "mergeMethod": method_upper}},
            headers=headers,
        )

    if mutation_resp.status_code in (401, 403):
        raise GitHubPermissionError(f"GitHub token lacks permission to enable auto-merge: {mutation_resp.text}")

    if not mutation_resp.is_success:
        raise AutoMergeError(f"GraphQL mutation request failed [{mutation_resp.status_code}]: {mutation_resp.text}")

    mutation_data = mutation_resp.json()
    if "errors" in mutation_data and mutation_data["errors"]:
        error_msg = "; ".join(e.get("message", "Unknown error") for e in mutation_data["errors"])
        err_lower = error_msg.lower()
        if (
            "auto merge is not allowed" in err_lower
            or "auto-merge is not allowed" in err_lower
            or "not enabled" in err_lower
            or "pull request is not mergeable or auto-merge is not allowed" in err_lower
        ):
            raise AutoMergeNotAllowedError(
                f"Repository {owner}/{repo} does not have 'Allow auto-merge' enabled in its settings: {error_msg}"
            )
        if "permission" in err_lower or "scope" in err_lower or "forbidden" in err_lower or "unauthorized" in err_lower:
            raise GitHubPermissionError(
                f"GitHub token lacks permission to enable auto-merge on {owner}/{repo}: {error_msg}"
            )
        raise AutoMergeError(
            f"Failed to enable auto-merge on PR #{pr_number} in {owner}/{repo}: {error_msg}."
        )

    logger.info("Successfully enabled auto-merge (%s) on GitHub PR #%d in %s/%s", method_upper, pr_number, owner, repo)
    return True


# ── 3. Get PR Status & Checks ─────────────────────────────────────────────────

def get_pr_status(repo_full_name: str, pr_number: int | None = None, token: str | None = None) -> dict[str, Any]:
    """
    Fetch comprehensive Pull Request status including merge state and CI check runs.

    Args:
        repo_full_name: 'owner/repo' or GitHub repository URL.
        pr_number:      Pull request number (optional if included in PR URL).
        token:          Optional user-specific GitHub token.

    Returns:
        dict with pr status and checks.
    """
    if "dev.azure.com" in str(repo_full_name).lower() or "visualstudio.com" in str(repo_full_name).lower():
        raise UnsupportedProviderError(f"Azure DevOps PR status polling is unsupported: '{repo_full_name}'")

    resolved_pr_num = pr_number
    if resolved_pr_num is None:
        resolved_pr_num = extract_pr_number_from_url(repo_full_name)

    if resolved_pr_num is None:
        raise ValueError(f"No pull request number provided or discoverable in '{repo_full_name}'.")

    owner, repo = _extract_owner_repo(repo_full_name)
    headers = _get_headers(token=token)

    # Step 1: Fetch PR metadata
    pr_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{resolved_pr_num}"
    with httpx.Client(timeout=20) as client:
        resp = client.get(pr_url, headers=headers)

    if resp.status_code == 404:
        raise RuntimeError(f"Pull request #{resolved_pr_num} not found in {owner}/{repo}")
    if not resp.is_success:
        raise RuntimeError(f"Failed to fetch PR #{resolved_pr_num} status [{resp.status_code}]: {resp.text}")

    pr_data = resp.json()
    head_sha = pr_data.get("head", {}).get("sha", "")
    head_branch = pr_data.get("head", {}).get("ref", "")
    base_branch = pr_data.get("base", {}).get("ref", "")

    # Step 2: Fetch check runs for the head commit
    checks_summary = {"total_count": 0, "check_runs": []}
    if head_sha:
        checks_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits/{head_sha}/check-runs"
        try:
            with httpx.Client(timeout=15) as client:
                checks_resp = client.get(checks_url, headers=headers)
            if checks_resp.is_success:
                checks_data = checks_resp.json()
                checks_summary = {
                    "total_count": checks_data.get("total_count", 0),
                    "check_runs": [
                        {
                            "id": cr.get("id"),
                            "name": cr.get("name"),
                            "status": cr.get("status"),            # "queued", "in_progress", "completed"
                            "conclusion": cr.get("conclusion"),    # "success", "failure", "neutral", "cancelled", etc.
                            "html_url": cr.get("html_url"),
                            "started_at": cr.get("started_at"),
                            "completed_at": cr.get("completed_at"),
                        }
                        for cr in checks_data.get("check_runs", [])
                    ],
                }
        except Exception as exc:
            logger.warning("Could not retrieve check-runs for commit %s: %s", head_sha, exc)

    return {
        "pr_number": pr_number,
        "pr_url": pr_data.get("html_url", ""),
        "state": pr_data.get("state", "unknown"),
        "merged": pr_data.get("merged", False),
        "mergeable": pr_data.get("mergeable"),
        "mergeable_state": pr_data.get("mergeable_state", "unknown"),
        "head_sha": head_sha,
        "head_branch": head_branch,
        "base_branch": base_branch,
        "checks": checks_summary,
    }


# ── Public High-Level Wrapper ─────────────────────────────────────────────────

def open_pull_request(
    branch_result: BranchResult,
    title: str,
    body: str,
    base_branch: str = "main",
    auto_complete: bool = True,
    token: str | None = None,
) -> PullRequestResult:
    """
    High-level PR dispatcher invoked by GitOps workflow.

    Args:
        branch_result: Result from create_branch_and_commit().
        title:         PR title.
        body:          PR description (markdown).
        base_branch:   Branch to merge into (default: 'main').
        auto_complete: If True, attempts to enable auto-merge.
        token:         Optional user-specific GitHub token.

    Returns:
        PullRequestResult with pr_url and pr_number.
    """
    if branch_result.provider != "github":
        raise NotImplementedError(
            f"PR creation is not supported for provider '{branch_result.provider}'. "
            "Supported providers: github."
        )

    res = create_pull_request(
        repo_full_name=branch_result.remote_url,
        branch_name=branch_result.branch_name,
        base_branch=base_branch,
        title=title,
        body=body,
        token=token,
    )

    pr_number = res["pr_number"]
    pr_url = res["pr_url"]

    if auto_complete:
        try:
            enable_auto_merge(branch_result.remote_url, pr_number, token=token)
        except Exception as exc:
            logger.warning("Auto-merge could not be enabled for PR #%d: %s", pr_number, exc)

    return PullRequestResult(
        pr_url=pr_url,
        pr_number=pr_number,
        provider="github",
        title=title,
        base_branch=base_branch,
        head_branch=branch_result.branch_name,
    )
