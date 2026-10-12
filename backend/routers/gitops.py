"""
routers/gitops.py
-----------------
POST /repos/{repo_id}/apply-fix
GET  /repos/{repo_id}/automation-log
POST /repos/{repo_id}/sync-prs

Orchestrates fix→branch→commit→PR pipeline and PR status synchronization (scoped).
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, get_user_repo
from database import get_db
from models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos", tags=["gitops"])

# ── Request / Response models ─────────────────────────────────────────────────


class ApplyFixRequest(BaseModel):
    diff: str = Field(..., min_length=10, description="Unified diff string from /symbols/{id}/fix")
    file_path: str = Field(..., min_length=1, description="Relative path of the file being patched")
    branch_name: str = Field(
        default="",
        description=(
            "Name for the new branch. Auto-generated from file_path if omitted. "
            "Convention: 'codebrain/fix-<slug>'"
        ),
    )
    commit_message: str = Field(
        default="",
        description="Git commit message. Auto-generated if omitted.",
    )
    pr_title: str = Field(
        default="",
        description="Pull request title. Auto-generated if omitted.",
    )
    pr_body: str = Field(
        default="",
        description="Pull request description (markdown). Auto-generated if omitted.",
    )
    base_branch: str = Field(
        default="main",
        description="Target branch to merge the PR into.",
    )


class ApplyFixResponse(BaseModel):
    repo_id: str
    branch_name: str
    commit_sha: str
    pr_url: str
    pr_number: int | None
    provider: str


# ── Helper: slug from file path ───────────────────────────────────────────────


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug[:50]  # keep branch names short


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post(
    "/{repo_id}/apply-fix",
    response_model=ApplyFixResponse,
    status_code=201,
    summary="Apply a diff patch, push a branch, and open a Pull Request",
)
def apply_fix_endpoint(
    repo_id: str,
    body: ApplyFixRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Full pipeline (scoped to owner):
      1. Verify the repo exists and belongs to current_user.
      2. create_branch_and_commit() — apply diff, push branch via GitPython.
      3. open_pull_request() — create PR on GitHub.
      4. Return PR URL + metadata.

    Required env vars:
      GitHub: GITHUB_TOKEN
    """
    from gitops.git_ops import create_branch_and_commit
    from gitops.pr_client import open_pull_request

    # 1. Verify repo and ownership
    repo = get_user_repo(repo_id, db, current_user)

    # 2. Build defaults for optional fields
    file_slug = _slugify(body.file_path.replace("/", "-").replace("\\", "-"))
    branch_name = body.branch_name or f"codebrain/fix-{file_slug}"
    commit_message = body.commit_message or (
        f"fix: AI-generated patch for {body.file_path}\n\n"
        f"Applied via CodeBrain auto-fix. Review before merging."
    )
    pr_title = body.pr_title or f"[CodeBrain] Auto-fix: {body.file_path}"
    pr_body = body.pr_body or (
        f"## AI-Generated Fix\n\n"
        f"**File:** `{body.file_path}`\n\n"
        f"This pull request was automatically created by **CodeBrain** based on "
        f"an AI-generated unified diff.\n\n"
        f"### Diff\n```diff\n{body.diff[:3000]}\n```\n\n"
        f"> ⚠️ Always review AI-generated changes carefully before merging."
    )

    # 3. Branch + commit
    from auth import get_user_github_token
    user_token = get_user_github_token(current_user)

    try:
        branch_result = create_branch_and_commit(
            repo_id=repo.id,
            patch=body.diff,
            branch_name=branch_name,
            commit_message=commit_message,
            token=user_token,
        )
    except RuntimeError as exc:
        logger.warning("create_branch_and_commit failed for %s: %s", repo.id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error in create_branch_and_commit for %s", repo.id)
        raise HTTPException(status_code=500, detail=f"Branch/commit failed: {exc}")

    # 4. Open PR
    try:
        pr_result = open_pull_request(
            branch_result=branch_result,
            title=pr_title,
            body=pr_body,
            base_branch=body.base_branch,
            token=user_token,
        )
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except NotImplementedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("open_pull_request failed for %s", repo.id)
        raise HTTPException(status_code=500, detail=f"PR creation failed: {exc}")

    return ApplyFixResponse(
        repo_id=repo.id,
        branch_name=branch_result.branch_name,
        commit_sha=branch_result.commit_sha,
        pr_url=pr_result.pr_url,
        pr_number=pr_result.pr_number,
        provider=branch_result.provider,
    )


# ── Automation Log & PR Sync Endpoints ────────────────────────────────────────

@router.get("/{repo_id}/automation-log", status_code=200)
def get_automation_log_endpoint(
    repo_id: str,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return a chronological list of every auto-fix attempt with its outcome.
    Synchronizes any open PR statuses with GitHub before returning.
    Includes aggregated summary statistics (scoped to owner).
    """
    from models import ErrorReport, AutomationLog
    from automation.auto_fix_pipeline import sync_pr_statuses_for_repo

    repo = get_user_repo(repo_id, db, current_user)

    # Sync any open PRs on GitHub
    try:
        sync_pr_statuses_for_repo(repo.id, db)
    except Exception as exc:
        logger.warning("Error syncing PR statuses for repo %s: %s", repo.id, exc)

    logs = (
        db.query(AutomationLog)
        .filter(AutomationLog.repo_id == repo.id)
        .order_by(AutomationLog.created_at.asc())
        .limit(limit)
        .all()
    )

    reports = db.query(ErrorReport).filter(ErrorReport.repo_id == repo.id).all()

    open_pr_statuses = ("OPEN", "OPEN_AUTO_MERGE_ENABLED", "OPEN_NO_CI", "OPEN_MANUAL_MERGE_REQUIRED", "MERGED", "FAILED_PIPELINE")
    total_issues = len(reports)
    attempted = sum(1 for r in reports if (r.auto_fix_attempted or 0) > 0)
    sandbox_passed = sum(
        1 for r in reports
        if r.pr_status in open_pr_statuses
        or r.fix_status in ("READY_TO_APPLY", "APPLIED", "APPLIED_LOCAL", "OPEN")
    )
    sandbox_failed = sum(1 for r in reports if r.fix_status in ("FAILED", "SANDBOX_FAILED") and (r.pr_status in ("NONE", None) or not r.pr_status))
    prs_opened = sum(1 for r in reports if r.pr_status in open_pr_statuses)
    merged = sum(1 for r in reports if r.pr_status == "MERGED")
    pipeline_failed = sum(1 for r in reports if r.pr_status == "FAILED_PIPELINE")

    return {
        "repo_id": repo.id,
        "repo_name": repo.name,
        "summary": {
            "total_issues": total_issues,
            "auto_fix_attempted": attempted,
            "sandbox_passed": sandbox_passed,
            "sandbox_failed": sandbox_failed,
            "prs_opened": prs_opened,
            "merged": merged,
            "pipeline_failed": pipeline_failed,
        },
        "logs": [
            {
                "id": l.id,
                "error_id": l.error_id,
                "stage": l.stage,
                "outcome": l.outcome,
                "message": l.message,
                "details": l.details,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }


@router.post("/{repo_id}/sync-prs", status_code=200)
def sync_prs_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly trigger status synchronization for open PRs with GitHub (scoped to owner)."""
    from automation.auto_fix_pipeline import sync_pr_statuses_for_repo

    repo = get_user_repo(repo_id, db, current_user)
    result = sync_pr_statuses_for_repo(repo.id, db)
    return {"repo_id": repo.id, **result}


# ── Full GitOps Source Control Endpoints ─────────────────────────────────────

from pathlib import Path
from fastapi import Query

STORAGE_ROOT = Path(__file__).parent.parent / "storage"

class GitStatusFile(BaseModel):
    path: str
    status: str  # "M" (modified), "A" (added), "D" (deleted), "?" (untracked), "R" (renamed)
    staged: bool = False
    additions: int = 0
    deletions: int = 0

class GitStatusResponse(BaseModel):
    repo_id: str
    branch: str
    clean: bool
    files: list[GitStatusFile]

class GitCommitRequest(BaseModel):
    files: list[str] = Field(..., description="List of relative file paths to commit")
    message: str = Field(..., min_length=1, description="Commit message")

class GitCommitResponse(BaseModel):
    success: bool
    commit_sha: str
    branch: str
    message: str
    files_committed: list[str]


def _get_git_repo(repo_id: str):
    import git
    from routers.errors import _find_repo_root
    repo_root = _find_repo_root(repo_id)
    if not repo_root or not repo_root.exists():
        repo_root = STORAGE_ROOT / repo_id
    if not repo_root.exists():
        raise HTTPException(status_code=404, detail=f"Repository storage for {repo_id} not found.")

    git_dir = repo_root / ".git"
    if not git_dir.exists():
        git_repo = git.Repo.init(repo_root)
    else:
        git_repo = git.Repo(repo_root)
    return git_repo


@router.get("/{repo_id}/git-status", response_model=GitStatusResponse, status_code=200)
def get_git_status_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch real git status: branch, modified, added, deleted, untracked files."""
    repo = get_user_repo(repo_id, db, current_user)
    git_repo = _get_git_repo(repo.id)

    branch = "main"
    try:
        branch = git_repo.active_branch.name
    except Exception:
        try:
            branch = git_repo.head.reference.name
        except Exception:
            branch = "HEAD"

    file_dict: dict[str, GitStatusFile] = {}

    # 1. Unstaged changes in working tree
    try:
        for diff in git_repo.index.diff(None):
            change_type = diff.change_type or "M"
            file_path = diff.a_path or diff.b_path
            if file_path:
                norm_path = file_path.replace("\\", "/")
                file_dict[norm_path] = GitStatusFile(
                    path=norm_path,
                    status=change_type,
                    staged=False,
                )
    except Exception as exc:
        logger.warning("Error getting unstaged diffs: %s", exc)

    # 2. Staged changes in index
    try:
        if git_repo.head.is_valid():
            for diff in git_repo.head.commit.diff():
                change_type = diff.change_type or "M"
                file_path = diff.a_path or diff.b_path
                if file_path:
                    norm_path = file_path.replace("\\", "/")
                    if norm_path in file_dict:
                        file_dict[norm_path].staged = True
                    else:
                        file_dict[norm_path] = GitStatusFile(
                            path=norm_path,
                            status=change_type,
                            staged=True,
                        )
    except Exception as exc:
        logger.warning("Error getting staged diffs: %s", exc)

    # 3. Untracked files
    try:
        for u in git_repo.untracked_files:
            norm_u = u.replace("\\", "/")
            if norm_u not in file_dict:
                file_dict[norm_u] = GitStatusFile(
                    path=norm_u,
                    status="?",
                    staged=False,
                )
    except Exception as exc:
        logger.warning("Error getting untracked files: %s", exc)

    files_list = sorted(file_dict.values(), key=lambda f: f.path)
    clean = len(files_list) == 0

    return GitStatusResponse(
        repo_id=repo.id,
        branch=branch,
        clean=clean,
        files=files_list,
    )


@router.get("/{repo_id}/git-diff", status_code=200)
def get_git_diff_endpoint(
    repo_id: str,
    path: str = Query(..., description="File path relative to repository"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve actual unified diff for a changed file."""
    import urllib.parse
    clean_path = urllib.parse.unquote(path).replace("\\", "/").lstrip("/")
    repo = get_user_repo(repo_id, db, current_user)
    git_repo = _get_git_repo(repo.id)
    repo_root = Path(git_repo.working_tree_dir)

    target_file = repo_root / clean_path

    # If untracked file, build diff from whole content
    if clean_path in git_repo.untracked_files and target_file.is_file():
        try:
            content = target_file.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            diff_lines = [
                "--- /dev/null",
                f"+++ b/{clean_path}",
                f"@@ -0,0 +1,{len(lines)} @@",
            ] + [f"+{line}" for line in lines]
            return {"path": clean_path, "diff": "\n".join(diff_lines)}
        except Exception as exc:
            return {"path": clean_path, "diff": f"// Error reading untracked file: {exc}"}

    try:
        diff_text = git_repo.git.diff(clean_path)
        if not diff_text and git_repo.head.is_valid():
            diff_text = git_repo.git.diff("HEAD", clean_path)
        if not diff_text and not target_file.exists():
            diff_text = f"--- a/{clean_path}\n+++ /dev/null\n@@ -1 +0,0 @@\n- [File deleted]"
        return {"path": clean_path, "diff": diff_text or "// No changes detected."}
    except Exception as exc:
        return {"path": clean_path, "diff": f"// Diff error: {exc}"}


SENSITIVE_PATTERNS = [
    re.compile(r"(^|/)\.env(\..+)?$", re.IGNORECASE),
    re.compile(r"(^|/)(id_rsa|id_ed25519|.*\.pem|.*\.key)$", re.IGNORECASE),
    re.compile(r".*(token|secret|credential|password).*", re.IGNORECASE),
]


@router.post("/{repo_id}/git-commit", response_model=GitCommitResponse, status_code=200)
def git_commit_endpoint(
    repo_id: str,
    body: GitCommitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate selected files, stage them, and commit with message."""
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="Commit message cannot be empty.")
    if not body.files:
        raise HTTPException(status_code=400, detail="No files selected for commit.")

    # 1. Sensitive file protection
    for file_path in body.files:
        norm_p = file_path.replace("\\", "/")
        for pat in SENSITIVE_PATTERNS:
            if pat.search(norm_p):
                raise HTTPException(
                    status_code=400,
                    detail=f"Security warning: Cannot commit sensitive file '{file_path}'. Exclude secrets from commits.",
                )

    repo = get_user_repo(repo_id, db, current_user)
    git_repo = _get_git_repo(repo.id)
    repo_root = Path(git_repo.working_tree_dir)

    # 2. Stage only selected files
    staged_any = False
    for file_path in body.files:
        norm_p = file_path.replace("\\", "/")
        target = repo_root / norm_p
        if target.exists():
            git_repo.git.add(norm_p)
            staged_any = True
        else:
            try:
                git_repo.git.rm(norm_p)
                staged_any = True
            except Exception:
                pass

    if not staged_any:
        raise HTTPException(status_code=400, detail="None of the selected files could be staged.")

    # 3. Create real commit
    from git import Actor
    author_name = current_user.github_username or "Developer"
    author_email = f"{author_name.lower().replace(' ', '_')}@codebrain.local"
    actor = Actor(author_name, author_email)

    try:
        commit = git_repo.index.commit(body.message.strip(), author=actor, committer=actor)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Git commit failed: {exc}")

    branch = "main"
    try:
        branch = git_repo.active_branch.name
    except Exception:
        pass

    # 4. Record AutomationLog
    from models import AutomationLog
    log_entry = AutomationLog(
        repo_id=repo.id,
        stage="BRANCH_PUSHED",
        outcome="SUCCESS",
        message=f"Commit [{commit.hexsha[:8]}]: {body.message.strip()}",
        details=f"Committed {len(body.files)} files: {', '.join(body.files[:5])}",
    )
    db.add(log_entry)
    db.commit()

    return GitCommitResponse(
        success=True,
        commit_sha=commit.hexsha[:8],
        branch=branch,
        message=body.message.strip(),
        files_committed=body.files,
    )


@router.get("/{repo_id}/git-history", status_code=200)
def git_history_endpoint(
    repo_id: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve recent git commit history."""
    repo = get_user_repo(repo_id, db, current_user)
    git_repo = _get_git_repo(repo.id)

    commits = []
    try:
        for c in git_repo.iter_commits(max_count=limit):
            commits.append({
                "sha": c.hexsha[:8],
                "full_sha": c.hexsha,
                "message": c.message.strip(),
                "author": c.author.name,
                "date": c.authored_datetime.isoformat(),
            })
    except Exception as exc:
        logger.warning("Could not read git commits: %s", exc)

    return {"repo_id": repo.id, "commits": commits}

