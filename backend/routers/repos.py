"""
POST /repos/upload  — accepts a zip file
POST /repos/github  — accepts a GitHub URL + optional token
GET  /repos/        — list authenticated user's repositories
GET  /repos/{repo_id}/files — returns the file tree (scoped)
DELETE /repos/{repo_id}     — deletes a repository (scoped)
"""
import logging
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

try:
    from git import Repo as GitRepo, GitCommandError, InvalidGitRepositoryError
except ImportError:
    GitRepo = None  # type: ignore

from auth import get_current_user, get_user_github_token, get_user_repo
from database import get_db
from file_walker import walk_repo
from gitops.pr_client import _extract_owner_repo
from gitops.git_ops import sanitize_sensitive_text
from models import Repo, RepoFile, User
from routers.pipeline import run_pipeline

import ipaddress
import socket
import urllib.parse
from docgen.secret_redactor import sanitize_host_paths

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/repos", tags=["repos"])


# ──────────────────────────────────────────────
# Security: Repository URL & SSRF Validation
# ──────────────────────────────────────────────

def validate_github_repo_url(raw_url: str) -> tuple[str, str, str]:
    """
    Strictly validate and normalize GitHub repository URL.
    Protects against:
      - SSRF attacks against internal network, loopback, link-local, and cloud metadata.
      - Unsupported schemes (file://, git://, ssh://, http://).
      - Malformed or command-injection formatted repository identifiers.
      - Provider confusion (e.g. Azure DevOps URLs sent to GitHub).
    Returns:
      (owner: str, repo_slug: str, canonical_url: str)
    """
    clean = (raw_url or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Repository URL must not be empty.")

    # Explicitly reject Azure DevOps URLs
    if "dev.azure.com" in clean.lower() or "visualstudio.com" in clean.lower():
        raise HTTPException(
            status_code=400,
            detail="Azure DevOps repository operations are not supported by the GitHub provider.",
        )

    # Reject non-https protocols
    if clean.startswith("http://"):
        raise HTTPException(status_code=400, detail="Insecure HTTP repository URLs are disallowed. Please use https://.")
    if clean.startswith(("file://", "ssh://", "git://", "gopher://", "ftp://")):
        raise HTTPException(status_code=400, detail="Unsupported protocol. Only HTTPS repository URLs are permitted.")

    # Match standard owner/repo pattern (slug only)
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", clean):
        parts = clean.split("/", 1)
        owner, raw_slug = parts[0], parts[1].removesuffix(".git")
        return owner, raw_slug, f"https://github.com/{owner}/{raw_slug}.git"

    # Match SSH format: git@github.com:owner/repo.git -> normalize to https
    ssh_match = re.match(r"^git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$", clean)
    if ssh_match:
        owner, raw_slug = ssh_match.group(1), ssh_match.group(2)
        return owner, raw_slug, f"https://github.com/{owner}/{raw_slug}.git"

    try:
        parsed = urllib.parse.urlparse(clean)
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed repository URL.")

    if parsed.scheme.lower() != "https":
        raise HTTPException(status_code=400, detail="Only https:// GitHub repository URLs are permitted.")

    hostname = (parsed.hostname or "").lower()
    if hostname not in ("github.com", "www.github.com"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported repository host '{hostname}'. Only github.com is supported.",
        )

    # SSRF Protection: verify resolved DNS addresses are strictly public
    try:
        addr_infos = socket.getaddrinfo(hostname, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _, _, _, _, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_reserved
                or ip_obj.is_multicast
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Security violation: Target repository hostname resolves to a restricted network address.",
                )
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="Could not resolve repository host name.")

    # Validate path segments: /owner/repo or /owner/repo.git
    path_segments = [s for s in parsed.path.strip("/").split("/") if s]
    if len(path_segments) < 2:
        raise HTTPException(status_code=400, detail="Invalid GitHub URL format. Expected 'https://github.com/owner/repo'.")

    owner, raw_repo = path_segments[0], path_segments[1]
    repo_slug = raw_repo.removesuffix(".git")

    valid_ident = r"^[A-Za-z0-9_.-]+$"
    if not re.match(valid_ident, owner) or not re.match(valid_ident, repo_slug):
        raise HTTPException(status_code=400, detail="Repository owner or name contains invalid characters.")

    canonical_url = f"https://github.com/{owner}/{repo_slug}.git"
    return owner, repo_slug, canonical_url


# ──────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────

def _create_repo(db: Session, name: str, source_type: str, user_id: str) -> Repo:
    repo = Repo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=name,
        source_type=source_type,
        pipeline_status="CLONING",
    )
    db.add(repo)
    db.flush()  # get the id without committing
    return repo


def _ingest_files(db: Session, repo: Repo, repo_root: Path) -> None:
    """Walk repo_root and insert RepoFile rows."""
    for file_info in walk_repo(repo_root):
        rf = RepoFile(
            id=str(uuid.uuid4()),
            repo_id=repo.id,
            path=file_info["path"],
            language=file_info["language"],
            size=file_info["size"],
            content_hash=file_info["content_hash"],
        )
        db.add(rf)
    db.commit()


# ──────────────────────────────────────────────
# POST /repos/upload
# ──────────────────────────────────────────────

@router.post("/upload", status_code=201)
async def upload_repo(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept a zip archive and extract it as a new repository for current_user."""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted.")

    # Abuse protection checks
    from rate_limiter import check_user_repo_limit, check_and_record_user_pipeline_run
    check_user_repo_limit(current_user.id, db)
    check_and_record_user_pipeline_run(current_user.id)

    repo_name = Path(file.filename).stem
    repo = _create_repo(db, name=repo_name, source_type="upload", user_id=current_user.id)

    repo_dir = STORAGE_ROOT / repo.id
    repo_dir.mkdir(parents=True, exist_ok=True)
    zip_path = repo_dir / "upload.zip"

    MAX_ZIP_UPLOAD_BYTES = 100 * 1024 * 1024       # 100 MB max zip
    MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024     # 300 MB max uncompressed
    MAX_ZIP_ENTRIES = 10_000                       # 10,000 max entries (DoS protection)
    MAX_SINGLE_FILE_BYTES = 50 * 1024 * 1024       # 50 MB single file limit
    MAX_NESTING_DEPTH = 20                         # Directory depth limit

    try:
        content = await file.read()
        if len(content) > MAX_ZIP_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"Zip archive exceeds maximum limit of {MAX_ZIP_UPLOAD_BYTES // (1024*1024)}MB.")
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded zip file is empty.")

        zip_path.write_bytes(content)

        with zipfile.ZipFile(zip_path, "r") as zf:
            total_uncompressed = 0
            resolved_repo_dir = repo_dir.resolve()
            infos = zf.infolist()

            if len(infos) > MAX_ZIP_ENTRIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Archive contains too many entries ({len(infos)} exceeds maximum limit of {MAX_ZIP_ENTRIES}).",
                )

            for info in infos:
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail="Archive uncompressed size exceeds safety limit (potential zip bomb detected).",
                    )
                if info.file_size > MAX_SINGLE_FILE_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Individual archive file exceeds safety limit of {MAX_SINGLE_FILE_BYTES // (1024*1024)}MB: {info.filename}",
                    )

                # Nesting depth check
                entry_parts = Path(info.filename).parts
                if len(entry_parts) > MAX_NESTING_DEPTH:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Directory nesting depth exceeds maximum allowable depth ({MAX_NESTING_DEPTH}): {info.filename}",
                    )

                # Symlink abuse protection (Unix mode 0o120000 indicates S_IFLNK)
                if (info.external_attr >> 16) & 0o120000 == 0o120000:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Security violation: Symbolic links in archives are strictly forbidden: {info.filename}",
                    )

                # Path traversal and absolute path protection
                if info.filename.startswith(("/", "\\")) or ":" in info.filename or ".." in entry_parts:
                    raise HTTPException(status_code=400, detail=f"Unsafe path detected in zip entry: {info.filename}")

                target_path = (repo_dir / info.filename).resolve()
                try:
                    target_path.relative_to(resolved_repo_dir)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Unsafe path traversal detected in zip: {info.filename}")

            # Safe extraction
            zf.extractall(repo_dir)

        zip_path.unlink(missing_ok=True)

        # Some zips nest everything inside a single top-level folder; detect & unwrap
        children = list(repo_dir.iterdir())
        if len(children) == 1 and children[0].is_dir():
            repo_root = children[0]
        else:
            repo_root = repo_dir

        _ingest_files(db, repo, repo_root)

    except HTTPException:
        shutil.rmtree(repo_dir, ignore_errors=True)
        db.rollback()
        raise
    except zipfile.BadZipFile:
        shutil.rmtree(repo_dir, ignore_errors=True)
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid or corrupted zip file.")
    except Exception as exc:
        shutil.rmtree(repo_dir, ignore_errors=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=sanitize_host_paths(str(exc)))

    # Detect CI workflows if any exist
    from automation.ci_setup import detect_ci_workflows
    ci_info = detect_ci_workflows(repo.id, db)

    # Kick off the auto-pipeline in background
    background_tasks.add_task(run_pipeline, repo.id)

    file_count = db.query(RepoFile).filter(RepoFile.repo_id == repo.id).count()
    return {
        "repo_id": repo.id,
        "name": repo.name,
        "source_type": repo.source_type,
        "file_count": file_count,
        "pipeline_status": "PARSING",
        "detected_ci": ci_info["detected_ci"],
        "detected_ci_files": ci_info["detected_ci_files"],
        "needs_ci_setup": ci_info["needs_ci_setup"],
    }


# ──────────────────────────────────────────────
# POST /repos/github
# ──────────────────────────────────────────────

class GithubCloneRequest(BaseModel):
    url: str
    access_token: Optional[str] = None


@router.post("/github", status_code=201)
def clone_github_repo(
    body: GithubCloneRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clone a GitHub repository and ingest its files for current_user with strict URL and SSRF validation."""
    if GitRepo is None:
        raise HTTPException(status_code=500, detail="gitpython is not installed.")

    # Strict URL validation and SSRF filtering
    owner, repo_slug, canonical_url = validate_github_repo_url(body.url)

    # Abuse protection checks
    from rate_limiter import (
        check_user_repo_limit,
        check_and_record_user_pipeline_run,
        ensure_github_rate_limit_available,
        GitHubRateLimitExceededError,
    )
    check_user_repo_limit(current_user.id, db)
    check_and_record_user_pipeline_run(current_user.id)

    # 1. Resolve user token (body override -> current user encrypted token -> env fallback)
    user_token = body.access_token or get_user_github_token(current_user)
    if not user_token:
        env_token = os.environ.get("GITHUB_TOKEN", "").strip()
        if env_token and not env_token.startswith("your_"):
            user_token = env_token

    # 2. Check GitHub API rate limit for this user
    if user_token:
        try:
            ensure_github_rate_limit_available(user_token)
        except GitHubRateLimitExceededError as rle:
            raise HTTPException(
                status_code=429,
                detail=f"GitHub API rate limit is low ({rle.remaining}/{rle.limit} remaining). Please wait until quota resets at {rle.reset_datetime.strftime('%H:%M:%S UTC')}.",
            )

    # 3. Pre-Flight Access Check against GitHub API
    gh_headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if user_token:
        gh_headers["Authorization"] = f"Bearer {user_token}"

    try:
        with httpx.Client(timeout=15) as client:
            check_resp = client.get(f"https://api.github.com/repos/{owner}/{repo_slug}", headers=gh_headers)
        if check_resp.status_code in (401, 404):
            raise HTTPException(
                status_code=400,
                detail="You don't have access to this repository, or it doesn't exist.",
            )
        elif check_resp.status_code == 403:
            if user_token:
                raise HTTPException(
                    status_code=400,
                    detail="Your GitHub token does not have permission to access this repository.",
                )
            else:
                logger.warning(
                    "GitHub API pre-flight returned 403 (unauthenticated rate limit). Proceeding with direct git clone for %s/%s",
                    owner, repo_slug,
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Pre-flight check network warning for %s/%s: %s", owner, repo_slug, exc)

    # 4. Construct authenticated clone URL using sanitized canonical URL
    clone_url = canonical_url
    if user_token:
        clone_url = canonical_url.replace("https://", f"https://{user_token}@", 1)

    repo_name = repo_slug
    repo = _create_repo(db, name=repo_name, source_type="github", user_id=current_user.id)
    repo.pipeline_status = "CLONING"
    repo.last_activity_summary = "Cloning repository from GitHub…"
    db.commit()

    repo_dir = STORAGE_ROOT / repo.id

    # Spawn background task for asynchronous clone and ingestion pipeline
    background_tasks.add_task(
        run_clone_and_pipeline,
        repo.id,
        clone_url,
        canonical_url,
        str(repo_dir),
    )

    return {
        "repo_id": repo.id,
        "name": repo.name,
        "source_type": repo.source_type,
        "file_count": 0,
        "pipeline_status": "CLONING",
        "detected_ci": False,
        "detected_ci_files": [],
        "needs_ci_setup": False,
    }


def run_clone_and_pipeline(
    repo_id: str,
    clone_url: str,
    canonical_url: str,
    repo_dir_str: str,
) -> None:
    """Background worker for asynchronous repository cloning and ingestion pipeline."""
    from database import SessionLocal
    from models import Repo
    from docgen.secret_redactor import sanitize_sensitive_text
    from routers.pipeline import _set_status, run_pipeline

    db = SessionLocal()
    repo_dir = Path(repo_dir_str)
    try:
        repo = db.query(Repo).filter(Repo.id == repo_id).first()
        if not repo:
            logger.error("Repo %s not found for async clone pipeline", repo_id)
            return

        _set_status(repo_id, "CLONING", "Cloning repository from GitHub…", db)
        logger.info("[PIPELINE] Starting background Git clone for %s (%s)", repo_id, repo.name)

        repo_dir.mkdir(parents=True, exist_ok=True)
        try:
            git_repo = GitRepo.clone_from(clone_url, str(repo_dir), depth=1)
            try:
                git_repo.remotes.origin.set_url(canonical_url)
            except Exception:
                pass
        except GitCommandError as exc:
            shutil.rmtree(repo_dir, ignore_errors=True)
            sanitized_err = sanitize_sensitive_text(str(exc))
            logger.error("Git clone failed for repo %s: %s", repo_id, sanitized_err)
            _set_status(repo_id, "FAILED", f"Git clone failed: {sanitized_err}", db, error=sanitized_err)
            return
        except Exception as exc:
            shutil.rmtree(repo_dir, ignore_errors=True)
            sanitized_err = sanitize_sensitive_text(str(exc))
            logger.error("Git clone unexpected error for repo %s: %s", repo_id, sanitized_err)
            _set_status(repo_id, "FAILED", f"Git clone failed: {sanitized_err}", db, error=sanitized_err)
            return

        # Stage 2: Ingest files
        _set_status(repo_id, "INGESTING", "Discovering and indexing files…", db)
        logger.info("[PIPELINE] Ingesting files for repo %s", repo_id)
        try:
            _ingest_files(db, repo, repo_dir)
        except Exception as exc:
            sanitized_err = sanitize_sensitive_text(str(exc))
            logger.error("File ingestion failed for repo %s: %s", repo_id, sanitized_err)
            _set_status(repo_id, "FAILED", f"File ingestion failed: {sanitized_err}", db, error=sanitized_err)
            return

        # Detect CI workflows if any exist
        try:
            from automation.ci_setup import detect_ci_workflows
            detect_ci_workflows(repo_id, db)
        except Exception as exc:
            logger.warning("CI detection warning for %s: %s", repo_id, exc)

        # Run the full pipeline (EMBEDDING, ANALYZING, DETECTING_ERRORS, etc.)
        run_pipeline(repo_id)

    except Exception as exc:
        sanitized_err = sanitize_sensitive_text(str(exc))
        logger.exception("Unhandled async clone error for repo %s: %s", repo_id, sanitized_err)
        _set_status(repo_id, "FAILED", f"Pipeline error: {sanitized_err}", db, error=sanitized_err)
    finally:
        db.close()


# ──────────────────────────────────────────────
# GET /repos — list current user's repos
# ──────────────────────────────────────────────

@router.get("/", status_code=200)
def list_repos(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all repositories owned by the current authenticated user, deduplicated by project identity."""
    import json
    repos = (
        db.query(Repo)
        .filter(Repo.user_id == current_user.id)
        .order_by(Repo.created_at.desc())
        .all()
    )

    # Deduplicate re-ingested repositories by name & source_type, keeping latest active
    seen_keys: set[str] = set()
    deduped_repos = []
    for r in repos:
        key = f"{r.name.strip().lower()}::{r.source_type}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_repos.append(r)

    res = []
    for r in deduped_repos:
        ci_files = []
        if r.detected_ci_files:
            try:
                ci_files = json.loads(r.detected_ci_files)
            except Exception:
                ci_files = []

        # Read Git commit info from model or live worktree
        commit_sha = r.last_commit_sha
        commit_msg = r.last_commit_message
        commit_branch = r.last_commit_branch
        commit_time = r.last_commit_time.isoformat() if r.last_commit_time else None

        if not commit_sha and GitRepo:
            repo_dir = STORAGE_ROOT / r.id
            if (repo_dir / ".git").exists():
                try:
                    gr = GitRepo(repo_dir)
                    if gr.head.is_valid():
                        c = gr.head.commit
                        commit_sha = c.hexsha[:7]
                        commit_msg = c.message.strip().split("\n")[0]
                        try:
                            commit_branch = gr.active_branch.name
                        except Exception:
                            commit_branch = "main"
                        commit_time = datetime.fromtimestamp(c.committed_date, timezone.utc).isoformat()
                except Exception:
                    pass

        # Factual activity summary
        last_act_at = r.last_activity_at or r.created_at
        last_act_summary = r.last_activity_summary or f"Indexed {len(r.files)} files and AST symbols"

        res.append({
            "repo_id": r.id,
            "name": r.name,
            "source_type": r.source_type,
            "created_at": r.created_at.isoformat(),
            "file_count": len(r.files),
            "pipeline_status": r.pipeline_status,
            "detected_ci": r.detected_ci,
            "detected_ci_files": ci_files,
            "needs_ci_setup": r.needs_ci_setup,
            "last_activity_at": last_act_at.isoformat() if last_act_at else None,
            "last_activity_summary": last_act_summary,
            "last_commit_sha": commit_sha,
            "last_commit_message": commit_msg,
            "last_commit_branch": commit_branch,
            "last_commit_time": commit_time,
        })
    return res


# ──────────────────────────────────────────────
# GET /repos/{repo_id}/ci-preview (Preview CI Workflow)
# ──────────────────────────────────────────────

@router.get("/{repo_id}/ci-preview", status_code=200, summary="Preview proposed CI workflow and diff before user approval")
def preview_ci_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate diff preview and explanation for proposed GitHub Actions CI workflow.
    Provides user with full visibility and control before creating the workflow PR.
    """
    from automation.ci_setup import get_ci_workflow_preview
    repo = get_user_repo(repo_id, db, current_user)
    return get_ci_workflow_preview(repo, db)


# ──────────────────────────────────────────────
# POST /repos/{repo_id}/setup-ci (Propose CI PR)
# ──────────────────────────────────────────────

@router.post("/{repo_id}/setup-ci", status_code=201, summary="Propose GitHub Actions CI workflow via Pull Request")
def setup_ci_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate a tailored GitHub Actions CI workflow for this repository and
    open a proposal Pull Request on GitHub for user review. (Does NOT auto-merge).
    """
    from automation.ci_setup import create_ci_setup_pr
    repo = get_user_repo(repo_id, db, current_user)

    if repo.source_type != "github":
        raise HTTPException(
            status_code=400,
            detail="CI setup via Pull Request is only supported for GitHub repositories.",
        )

    from rate_limiter import (
        ensure_github_rate_limit_available,
        check_and_record_user_pipeline_run,
        GitHubRateLimitExceededError,
    )
    check_and_record_user_pipeline_run(current_user.id)
    user_token = get_user_github_token(current_user)
    if user_token:
        try:
            ensure_github_rate_limit_available(user_token)
        except GitHubRateLimitExceededError as rle:
            raise HTTPException(
                status_code=429,
                detail=f"GitHub API rate limit is low ({rle.remaining}/{rle.limit} remaining). Please wait until quota resets at {rle.reset_datetime.strftime('%H:%M:%S UTC')}.",
            )

    try:
        result = create_ci_setup_pr(repo, db, current_user)
        return {"repo_id": repo.id, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Error proposing CI workflow PR for repo %s: %s", repo.id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to create CI setup PR: {exc}")


# ──────────────────────────────────────────────
# GET /repos/{repo_id}/files
# ──────────────────────────────────────────────

@router.get("/{repo_id}/files", status_code=200)
def get_repo_files(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the file tree for a repository as JSON (scoped to owner)."""
    repo = get_user_repo(repo_id, db, current_user)

    files = (
        db.query(RepoFile)
        .filter(RepoFile.repo_id == repo_id)
        .order_by(RepoFile.path)
        .all()
    )

    # Build a nested tree structure
    tree: dict = {"name": repo.name, "type": "directory", "children": {}}

    for rf in files:
        parts = rf.path.split("/")
        node = tree["children"]
        for part in parts[:-1]:
            if part not in node:
                node[part] = {"name": part, "type": "directory", "children": {}}
            node = node[part]["children"]
        filename = parts[-1]
        node[filename] = {
            "name": filename,
            "type": "file",
            "path": rf.path,
            "language": rf.language,
            "size": rf.size,
        }

    def _flatten(node: dict) -> dict:
        """Convert dict-of-children to list-of-children (sorted: dirs first)."""
        if node.get("type") == "file":
            return node
        children_raw = node.get("children", {})
        children = [_flatten(v) for v in children_raw.values()]
        children.sort(key=lambda c: (0 if c["type"] == "directory" else 1, c["name"]))
        return {k: v for k, v in node.items() if k != "children"} | {"children": children}

    return {
        "repo_id": repo.id,
        "name": repo.name,
        "source_type": repo.source_type,
        "tree": _flatten(tree),
        "total_files": len(files),
    }


# ──────────────────────────────────────────────
# GET /repos/{repo_id}/file-content
# ──────────────────────────────────────────────

@router.get("/{repo_id}/file-content", status_code=200)
def get_file_content(
    repo_id: str,
    path: str = Query(..., description="Relative file path inside the repository"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve full source code for a specific file in the repository (scoped to owner)."""
    repo = get_user_repo(repo_id, db, current_user)
    import urllib.parse
    raw_path = urllib.parse.unquote(path).strip()
    
    # Path traversal and absolute path protection
    if ".." in Path(raw_path).parts or raw_path.startswith(("/", "\\")) or ":" in raw_path:
        raise HTTPException(status_code=400, detail="Invalid file path: path traversal detected.")

    clean_path = raw_path.replace("\\", "/").lstrip("/")

    repo_dir = STORAGE_ROOT / repo.id
    resolved_repo_dir = repo_dir.resolve()
    target_file = (repo_dir / clean_path).resolve()

    # Try locating via _find_repo_root helper
    from routers.errors import _find_repo_root
    actual_root = _find_repo_root(repo.id)
    if actual_root and (actual_root / clean_path).is_file():
        target_file = (actual_root / clean_path).resolve()

    # If not directly at repo_dir/path, check sub-levels (e.g. unzipped root folders)
    if not target_file.is_file() and repo_dir.exists():
        found = None
        for item in repo_dir.iterdir():
            if item.is_dir() and item.name not in ("faiss.index", "docs"):
                sub_target = (item / clean_path).resolve()
                if sub_target.is_file():
                    found = sub_target
                    break
        if found:
            target_file = found

    # If clean_path starts with repo name or 'quizgenai'
    if not target_file.is_file() and "/" in clean_path and repo_dir.exists():
        first_segment, rest = clean_path.split("/", 1)
        if first_segment.lower() == repo.name.lower() or first_segment.lower() == "quizgenai":
            candidate = (repo_dir / rest).resolve()
            if candidate.is_file():
                target_file = candidate
            elif actual_root and (actual_root / rest).is_file():
                target_file = (actual_root / rest).resolve()

    # Fallback search by relative suffix
    if not target_file.is_file() and repo_dir.exists():
        norm_suffix = clean_path.replace("\\", "/")
        for p in repo_dir.rglob(Path(clean_path).name):
            if p.is_file() and p.as_posix().endswith(norm_suffix):
                target_file = p.resolve()
                break

    # Security check: verify resolved target is strictly contained inside repository workspace
    try:
        target_file.relative_to(resolved_repo_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Security violation: file path escapes repository workspace.")

    from file_walker import detect_language

    BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar", ".gz", ".exe", ".bin", ".pyc", ".woff", ".woff2"}
    if target_file.is_file():
        if target_file.suffix.lower() in BINARY_EXTS:
            return {
                "repo_id": repo.id,
                "path": clean_path,
                "content": f"// [Binary file: {target_file.name} ({target_file.stat().st_size} bytes)]",
                "language": "plaintext",
                "size": target_file.stat().st_size,
            }
        try:
            content = target_file.read_text(encoding="utf-8", errors="replace")
            return {
                "repo_id": repo.id,
                "path": clean_path,
                "content": content,
                "language": detect_language(target_file) or "plaintext",
                "size": len(content),
            }
        except PermissionError:
            raise HTTPException(status_code=403, detail=f"Permission denied reading '{clean_path}'.")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=sanitize_host_paths(f"Failed to read file: {exc}"))

    # Fallback: check if we have symbols stored in database for this file
    from models import Symbol
    symbols = (
        db.query(Symbol)
        .join(RepoFile, Symbol.file_id == RepoFile.id)
        .filter(RepoFile.repo_id == repo.id, RepoFile.path == clean_path)
        .all()
    )
    if symbols:
        content = "\n\n".join(s.source_code for s in symbols if s.source_code)
        return {
            "repo_id": repo.id,
            "path": clean_path,
            "content": content,
            "language": detect_language(Path(clean_path)) or "plaintext",
            "size": len(content),
        }
    raise HTTPException(status_code=404, detail=f"File '{clean_path}' not found in repository.")


# ──────────────────────────────────────────────
# DELETE /repos/{repo_id}
# ──────────────────────────────────────────────

@router.delete("/{repo_id}", status_code=200)
def delete_repo(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a repository, its files, symbols, and disk storage (scoped to owner)."""
    from models import Symbol

    repo = get_user_repo(repo_id, db, current_user)

    # 1. Delete symbols
    db.query(Symbol).filter(Symbol.repo_id == repo_id).delete(synchronize_session=False)

    # 2. Delete files
    db.query(RepoFile).filter(RepoFile.repo_id == repo_id).delete(synchronize_session=False)

    # 3. Delete repo record
    db.delete(repo)
    db.commit()

    # 4. Remove on-disk storage
    repo_dir = STORAGE_ROOT / repo_id
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)

    # 5. Clear status from memory if present
    try:
        from routers.embeddings import _embed_status, _status_lock
        with _status_lock:
            _embed_status.pop(repo_id, None)
    except Exception:
        pass

    return {"status": "deleted", "repo_id": repo_id}
