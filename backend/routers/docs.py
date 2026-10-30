"""
POST /repos/{repo_id}/docs/readme  — generate + return README.md
POST /repos/{repo_id}/docs/master  — generate 16-section docs
GET  /repos/{repo_id}/docs/sections — get generated sections
POST /repos/{repo_id}/docs/export  — bulk export (background task)
GET  /repos/{repo_id}/docs/export/status — poll export job
GET  /repos/{repo_id}/docs/export/download — download docs as zip
POST /symbols/{symbol_id}/docs     — generate docstring for one symbol
"""
from __future__ import annotations

import io
import logging
import re
import threading
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_user_repo, get_user_symbol
from database import get_db
from models import User

logger = logging.getLogger(__name__)

# Two routers — one for /repos, one for /symbols
repos_router = APIRouter(prefix="/repos", tags=["docs"])
symbols_router = APIRouter(prefix="/symbols", tags=["docs"])

STORAGE_ROOT = Path(__file__).parent.parent / "storage"

# ── In-process export job tracker & README concurrency locks ─────────────────
_export_jobs: dict[str, dict] = {}
_job_lock = threading.Lock()

_readme_locks: dict[str, threading.Lock] = {}
_readme_locks_meta = threading.Lock()


def _get_readme_lock(repo_id: str) -> threading.Lock:
    with _readme_locks_meta:
        if repo_id not in _readme_locks:
            _readme_locks[repo_id] = threading.Lock()
        return _readme_locks[repo_id]


def compute_repo_source_fingerprint(repo_id: str, db: Session) -> str:
    """
    Computes a deterministic hash fingerprint representing the current repository content.
    Includes git commit SHA (if available), file count, and file paths + content hashes.
    """
    import hashlib
    from models import Repo, RepoFile

    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if not repo:
        return ""

    parts = []
    if getattr(repo, "last_commit_sha", None):
        parts.append(f"commit:{repo.last_commit_sha}")

    files = (
        db.query(RepoFile.path, RepoFile.content_hash, RepoFile.size)
        .filter(RepoFile.repo_id == repo_id)
        .order_by(RepoFile.path)
        .all()
    )
    parts.append(f"count:{len(files)}")
    for f in files:
        parts.append(f"{f.path}:{f.content_hash}:{f.size}")

    raw_data = "\n".join(parts)
    return hashlib.sha256(raw_data.encode("utf-8")).hexdigest()[:24]


# ── GET /repos/{repo_id}/docs/readme ──────────────────────────────────────────

@repos_router.get("/{repo_id}/docs/readme", status_code=200)
def get_readme_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve saved README.md for the repository without calling AI."""
    import uuid
    from datetime import datetime, timezone
    from models import RepoReadme

    repo = get_user_repo(repo_id, db, current_user)
    current_fingerprint = compute_repo_source_fingerprint(repo.id, db)

    saved = db.query(RepoReadme).filter(RepoReadme.repo_id == repo.id).first()

    # Fallback to disk if DB row not present yet
    out_path = STORAGE_ROOT / repo.id / "docs" / "README.md"
    if not saved and out_path.exists():
        try:
            content = out_path.read_text(encoding="utf-8")
            if content.strip():
                now = datetime.now(timezone.utc)
                saved = RepoReadme(
                    id=str(uuid.uuid4()),
                    repo_id=repo.id,
                    content=content,
                    source_fingerprint=current_fingerprint,
                    status="READY",
                    created_at=now,
                    updated_at=now,
                )
                db.add(saved)
                db.commit()
                db.refresh(saved)
        except Exception:
            pass

    if saved and saved.content and saved.content.strip():
        is_stale = bool(saved.source_fingerprint and saved.source_fingerprint != current_fingerprint)
        return {
            "repo_id": repo.id,
            "has_readme": True,
            "readme": saved.content,
            "source_fingerprint": saved.source_fingerprint,
            "current_fingerprint": current_fingerprint,
            "is_stale": is_stale,
            "generator_model": saved.generator_model,
            "status": saved.status or "READY",
            "created_at": saved.created_at.isoformat() if saved.created_at else None,
            "updated_at": saved.updated_at.isoformat() if saved.updated_at else None,
        }

    return {
        "repo_id": repo.id,
        "has_readme": False,
        "readme": "",
        "current_fingerprint": current_fingerprint,
        "is_stale": False,
        "status": "NOT_FOUND",
    }


# ── POST /repos/{repo_id}/docs/readme ─────────────────────────────────────────

@repos_router.post("/{repo_id}/docs/readme", status_code=200)
def generate_readme_endpoint(
    repo_id: str,
    force: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate or retrieve a README.md for the repository (scoped to owner)."""
    import uuid
    from datetime import datetime, timezone
    from docgen.readme_gen import generate_repo_readme
    from models import RepoReadme

    repo = get_user_repo(repo_id, db, current_user)
    current_fingerprint = compute_repo_source_fingerprint(repo.id, db)

    # 1. If not forcing regeneration, check if existing saved README is valid
    saved = db.query(RepoReadme).filter(RepoReadme.repo_id == repo.id).first()
    if not force:
        if saved and saved.content and saved.content.strip():
            return {
                "repo_id": repo.id,
                "readme": saved.content,
                "is_fresh": False,
                "source_fingerprint": saved.source_fingerprint,
                "status": saved.status or "READY",
                "message": "Returned existing persisted README.",
            }

    # 2. Concurrency-safe generation using repo-level lock
    lock = _get_readme_lock(repo.id)
    with lock:
        # Re-check in case another thread just completed generation while waiting
        if not force:
            saved_again = db.query(RepoReadme).filter(RepoReadme.repo_id == repo.id).first()
            if saved_again and saved_again.content and saved_again.content.strip():
                return {
                    "repo_id": repo.id,
                    "readme": saved_again.content,
                    "is_fresh": False,
                    "source_fingerprint": saved_again.source_fingerprint,
                    "status": saved_again.status or "READY",
                    "message": "Returned existing persisted README.",
                }

        try:
            readme = generate_repo_readme(repo.id, db)
        except EnvironmentError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except Exception as exc:
            logger.exception("README generation failed for %s", repo.id)
            # IMPORTANT: Do NOT erase existing valid README if regeneration failed!
            raise HTTPException(status_code=500, detail=f"README generation failed: {exc}")

        # Persist to database
        now = datetime.now(timezone.utc)
        saved = db.query(RepoReadme).filter(RepoReadme.repo_id == repo.id).first()
        if saved:
            saved.content = readme
            saved.source_fingerprint = current_fingerprint
            saved.generator_model = "groq-llama-3.3-70b"
            saved.status = "READY"
            saved.error = None
            saved.updated_at = now
        else:
            saved = RepoReadme(
                id=str(uuid.uuid4()),
                repo_id=repo.id,
                content=readme,
                source_fingerprint=current_fingerprint,
                generator_model="groq-llama-3.3-70b",
                status="READY",
                error=None,
                created_at=now,
                updated_at=now,
            )
            db.add(saved)
        db.commit()

        # Also persist to disk
        out_path = STORAGE_ROOT / repo.id / "docs" / "README.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(readme, encoding="utf-8")

        return {
            "repo_id": repo.id,
            "readme": readme,
            "is_fresh": True,
            "source_fingerprint": current_fingerprint,
            "status": "READY",
        }


_doc_gen_progress: Dict[str, Dict[str, Any]] = {}


# ── POST /repos/{repo_id}/docs/master ─────────────────────────────────────────

@repos_router.post("/{repo_id}/docs/master", status_code=200)
def generate_master_docs_endpoint(
    repo_id: str,
    force: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate complete 16-Section Project Documentation Suite with validation metadata (scoped)."""
    from docgen.master_doc_gen import generate_full_project_documentation

    repo = get_user_repo(repo_id, db, current_user)

    def on_progress(disp_num: int, total_sections: int, title: str):
        pct = int(((disp_num - 1) / max(total_sections, 1)) * 100)
        _doc_gen_progress[repo.id] = {
            "status": "generating",
            "percentage": pct,
            "current_section": title,
            "section_number": disp_num,
            "completed": disp_num - 1,
            "total": total_sections,
        }

    _doc_gen_progress[repo.id] = {
        "status": "generating",
        "percentage": 0,
        "current_section": "Analyzing repository...",
        "section_number": 0,
        "completed": 0,
        "total": 16,
    }

    try:
        suite = generate_full_project_documentation(
            repo.id,
            db,
            resume=not force,
            progress_callback=on_progress,
        )
        _doc_gen_progress[repo.id] = {
            "status": "completed",
            "percentage": 100,
            "current_section": "Complete",
            "section_number": len(suite.sections),
            "completed": len(suite.sections),
            "total": len(suite.sections),
        }
        return {
            "repo_id": repo.id,
            "commit_sha": suite.commit_sha,
            "timestamp": suite.timestamp,
            "doc_version": suite.doc_version,
            "is_complete": suite.is_complete,
            "master_readme": suite.master_readme,
            "validation_summary": suite.validation_summary,
            "schema_data": suite.schema_data,
            "sections": [
                {
                    "section_number": s.section_number,
                    "title": s.title,
                    "schema_key": s.schema_key,
                    "filename": s.filename,
                    "content": s.content,
                    "status": s.status,
                    "is_complete": s.is_complete,
                    "has_diagram": s.has_diagram,
                    "warnings": s.warnings,
                }
                for s in suite.sections
            ],
        }
    except Exception as exc:
        _doc_gen_progress[repo.id] = {
            "status": "failed",
            "percentage": 0,
            "current_section": f"Failed: {exc}",
            "completed": 0,
            "total": 16,
        }
        logger.exception("Master doc generation failed for %s", repo.id)
        raise HTTPException(status_code=500, detail=str(exc))


@repos_router.get("/{repo_id}/docs/progress", status_code=200)
def get_doc_generation_progress_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve real-time percentage progress of documentation generation."""
    repo = get_user_repo(repo_id, db, current_user)
    prog = _doc_gen_progress.get(repo.id)
    if not prog:
        return {
            "status": "idle",
            "percentage": 0,
            "current_section": "",
            "section_number": 0,
            "completed": 0,
            "total": 16,
        }
    return prog


# ── POST /repos/{repo_id}/docs/commit-to-repo ─────────────────────────────────

@repos_router.post("/{repo_id}/docs/commit-to-repo", status_code=200)
def commit_docs_to_repo_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Commit and push generated documentation + README to the repository.
    - For GitHub repos: creates branch 'docs/update-documentation-<id>', commits README + docs,
      pushes to origin, opens PR, and enables auto-merge with zero manual git steps.
    - For Zip uploads: directly commits/applies README + docs to local disk storage.
    """
    from automation.auto_fix_pipeline import commit_docs_to_repo
    from auth import get_user_github_token

    repo = get_user_repo(repo_id, db, current_user)
    token = get_user_github_token(current_user)

    res = commit_docs_to_repo(repo.id, db, user_token=token)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to commit docs to repo"))

    return {
        "repo_id": repo.id,
        **res,
    }


# ── POST /repos/{repo_id}/docs/commit-readme ─────────────────────────────────

@repos_router.post("/{repo_id}/docs/commit-readme", status_code=200)
def commit_readme_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Commit and push ONLY the generated README.md to the repository.
    - For GitHub repos: creates branch 'docs/update-readme-<id>', commits README.md,
      pushes to origin, opens PR with zero manual git steps.
    - For Zip uploads: directly writes/applies README.md to local repo disk.
    """
    import uuid
    import difflib
    from auth import get_user_github_token
    from automation.auto_fix_pipeline import _find_repo_root, _add_log
    from gitops.git_ops import create_branch_and_commit
    from gitops.pr_client import create_pull_request
    from models import RepoReadme

    repo = get_user_repo(repo_id, db, current_user)
    saved_rm = db.query(RepoReadme).filter(RepoReadme.repo_id == repo.id).first()

    docs_dir = STORAGE_ROOT / repo.id / "docs"
    readme_file = docs_dir / "README.md"

    content = ""
    if saved_rm and saved_rm.content and saved_rm.content.strip():
        content = saved_rm.content
    elif readme_file.exists():
        content = readme_file.read_text(encoding="utf-8")

    if not content.strip():
        raise HTTPException(status_code=400, detail="No generated README.md found to commit. Click 'Generate README' first.")

    source_type = getattr(repo, "source_type", "upload")
    if source_type != "github":
        repo_root = _find_repo_root(repo.id)
        if not repo_root:
            raise HTTPException(status_code=404, detail="Repository root directory not found on disk")

        target_readme = repo_root / "README.md"
        target_readme.write_text(content, encoding="utf-8")

        _add_log(
            repo_id=repo.id,
            error_id=None,
            stage="DOCS_COMMITTED",
            outcome="SUCCESS",
            message="README.md committed directly to local repository root.",
            db=db,
        )
        return {
            "status": "applied_local",
            "message": "README.md successfully committed to local repository.",
            "branch_name": None,
            "commit_sha": None,
            "pr_url": None,
            "pr_number": None,
            "pr_status": "NONE",
        }

    # GitHub repository
    token = get_user_github_token(current_user)
    branch_short_id = uuid.uuid4().hex[:8]
    branch_name = f"docs/update-readme-{branch_short_id}"
    commit_message = f"docs: update README.md for {repo.name} [skip ci]"

    repo_root = _find_repo_root(repo.id) or (STORAGE_ROOT / repo.id)
    existing_readme = (repo_root / "README.md").read_text(encoding="utf-8") if (repo_root / "README.md").exists() else ""

    diff_lines = list(difflib.unified_diff(
        existing_readme.splitlines(keepends=True),
        content.splitlines(keepends=True),
        fromfile="a/README.md",
        tofile="b/README.md",
    ))
    patch = "".join(diff_lines)
    if not patch:
        patch = f"--- /dev/null\n+++ b/README.md\n@@ -0,0 +1,{len(content.splitlines())} @@\n" + "".join([f"+{line}\n" for line in content.splitlines()])

    branch_res = create_branch_and_commit(
        repo_id=repo.id,
        patch=patch,
        branch_name=branch_name,
        commit_message=commit_message,
        token=token,
    )

    pr_url = None
    pr_number = None
    if branch_res.provider == "github":
        try:
            pr_res = create_pull_request(
                repo_id=repo.id,
                head_branch=branch_name,
                base_branch=getattr(branch_res, "default_branch", "main"),
                title="docs: update README.md",
                body="## CodeBrain Automated Documentation\n\nUpdates developer `README.md` based on verified repository AST analysis.",
                token=token,
            )
            pr_url = pr_res.pr_url
            pr_number = pr_res.pr_number
        except Exception as exc:
            logger.warning("Failed to open PR for README commit: %s", exc)

    return {
        "status": "committed",
        "message": "README.md committed and pushed successfully.",
        "branch_name": branch_name,
        "commit_sha": branch_res.commit_sha,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "pr_status": "OPEN" if pr_url else "NONE",
    }


# ── GET /repos/{repo_id}/docs/sections ─────────────────────────────────────────

@repos_router.get("/{repo_id}/docs/sections", status_code=200)
def get_doc_sections_endpoint(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve existing generated documentation, strictly mapped to the exact 16 schema sections."""
    import json
    from docgen.schema import SECTIONS_META, LEGACY_FILENAMES_BY_ID

    repo = get_user_repo(repo_id, db, current_user)

    from models import RepoDoc, RepoReadme
    saved_rm = db.query(RepoReadme).filter(RepoReadme.repo_id == repo.id).first()
    saved_rm_content = saved_rm.content if (saved_rm and saved_rm.content) else ""

    # 1. Primary: Database check for permanent persistence across cloud container restarts & page reloads
    saved_doc = db.query(RepoDoc).filter(RepoDoc.repo_id == repo.id).first()
    if saved_doc and saved_doc.sections_json:
        try:
            sections = json.loads(saved_doc.sections_json)
            if sections:
                return {
                    "repo_id": repo.id,
                    "has_docs": True,
                    "is_complete": saved_doc.is_complete,
                    "total_sections": len(sections),
                    "completed_sections": sum(1 for s in sections if s.get("is_complete")),
                    "sections": sections,
                    "master_content": saved_doc.master_content or "",
                    "readme_content": saved_rm_content,
                }
        except Exception as p_err:
            logger.warning("Failed parsing saved RepoDoc sections for %s: %s", repo.id, p_err)

    # 2. Secondary: Local disk check
    docs_dir = STORAGE_ROOT / repo.id / "docs"
    if not docs_dir.exists():
        return {
            "repo_id": repo.id,
            "has_docs": bool(saved_rm_content),
            "is_complete": False,
            "total_sections": 16,
            "completed_sections": 0,
            "sections": [],
            "master_content": "",
            "readme_content": saved_rm_content,
        }

    manifest_file = docs_dir / "metadata" / "documentation-manifest.json"
    manifest_data = {}
    if manifest_file.exists():
        try:
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    sections = []
    completed_count = 0
    manifest_sections = manifest_data.get("included_sections") or manifest_data.get("sections")

    meta_items = []
    if manifest_sections:
        for ms in manifest_sections:
            disp_num = ms.get("display_number") or ms.get("section_number") or ms.get("section_id")
            canon_id = ms.get("canonical_id") or ms.get("section_id") or disp_num
            t = ms.get("title")
            sk = ms.get("schema_key")
            fn = ms.get("filename")
            meta_items.append((disp_num, canon_id, t, sk, fn))
    else:
        for sec_num, title, schema_key, canonical_filename in SECTIONS_META:
            meta_items.append((sec_num, sec_num, title, schema_key, canonical_filename))

    total_target = len(meta_items)

    for disp_num, canon_id, title, schema_key, canonical_filename in meta_items:
        sec_file = docs_dir / canonical_filename
        if not sec_file.exists():
            legacy_name = LEGACY_FILENAMES_BY_ID.get(canon_id)
            if legacy_name and (docs_dir / legacy_name).exists():
                sec_file = docs_dir / legacy_name

        if sec_file.exists():
            try:
                content = sec_file.read_text(encoding="utf-8")
                has_diag = "```mermaid" in content
                is_comp = len(content.strip()) > 80 and not content.startswith("> [!WARNING]")
                if is_comp:
                    completed_count += 1
                sections.append({
                    "section_number": disp_num,
                    "canonical_id": canon_id,
                    "title": title,
                    "schema_key": schema_key,
                    "filename": canonical_filename,
                    "content": content,
                    "status": "COMPLETE" if is_comp else "FAILED",
                    "is_complete": is_comp,
                    "has_diagram": has_diag,
                })
            except Exception:
                sections.append({
                    "section_number": disp_num,
                    "canonical_id": canon_id,
                    "title": title,
                    "schema_key": schema_key,
                    "filename": canonical_filename,
                    "content": "",
                    "status": "FAILED",
                    "is_complete": False,
                    "has_diagram": False,
                })
        else:
            sections.append({
                "section_number": disp_num,
                "canonical_id": canon_id,
                "title": title,
                "schema_key": schema_key,
                "filename": canonical_filename,
                "content": "",
                "status": "PENDING",
                "is_complete": False,
                "has_diagram": False,
            })

    master_content = ""
    full_doc_path = docs_dir / "FULL_PROJECT_DOCUMENTATION.md"
    if full_doc_path.exists():
        master_content = full_doc_path.read_text(encoding="utf-8")

    readme_content = ""
    from models import RepoReadme
    saved_rm = db.query(RepoReadme).filter(RepoReadme.repo_id == repo.id).first()
    if saved_rm and saved_rm.content:
        readme_content = saved_rm.content
    else:
        rm_path = docs_dir / "README.md"
        if rm_path.exists():
            try:
                readme_content = rm_path.read_text(encoding="utf-8")
            except Exception:
                pass

    suite_is_complete = manifest_data.get("is_complete", (completed_count == total_target and total_target > 0))

    return {
        "repo_id": repo.id,
        "has_docs": completed_count > 0 or bool(master_content) or bool(readme_content),
        "is_complete": suite_is_complete,
        "total_sections": total_target,
        "master_content": master_content,
        "readme_content": readme_content,
        "sections": sections,
        "omitted_sections": manifest_data.get("omitted_sections", []),
    }


# ── POST /symbols/{symbol_id}/docs ────────────────────────────────────────────

@symbols_router.post("/{symbol_id}/docs", status_code=200)
def generate_symbol_doc_endpoint(
    symbol_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a docstring/comment for a single symbol (scoped to symbol repo owner)."""
    from docgen.symbol_doc import generate_symbol_doc

    symbol = get_user_symbol(symbol_id, db, current_user)

    try:
        docstring = generate_symbol_doc(symbol.id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("Symbol doc generation failed for symbol %d", symbol.id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"symbol_id": symbol.id, "docstring": docstring}


# ── POST /repos/{repo_id}/docs/export ─────────────────────────────────────────

def _run_export(repo_id: str) -> None:
    """Background export job."""
    from database import SessionLocal
    from docgen.exporter import export_repo_docs

    db = SessionLocal()
    try:
        with _job_lock:
            _export_jobs[repo_id] = {"status": "running", "result": None, "error": None}

        result = export_repo_docs(repo_id, db)

        with _job_lock:
            _export_jobs[repo_id] = {
                "status": "done",
                "result": {
                    "total_symbols": result.total_symbols,
                    "documented_symbols": result.documented_symbols,
                    "doc_files": [
                        {"path": f.relative_path, "size": len(f.content)}
                        for f in result.doc_files
                    ],
                    "errors": result.errors,
                },
                "error": None,
            }
    except Exception as exc:
        logger.exception("Export job failed for %s", repo_id)
        with _job_lock:
            _export_jobs[repo_id] = {"status": "error", "result": None, "error": str(exc)}
    finally:
        db.close()


@repos_router.post("/{repo_id}/docs/export", status_code=202)
def trigger_export(
    repo_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger a background bulk-documentation export job (scoped)."""
    repo = get_user_repo(repo_id, db, current_user)

    with _job_lock:
        current = _export_jobs.get(repo.id, {})
        if current.get("status") == "running":
            return {"repo_id": repo.id, "status": "already_running"}

    background_tasks.add_task(_run_export, repo.id)
    return {
        "repo_id": repo.id,
        "status": "accepted",
        "message": "Documentation export started. Poll /docs/export/status for progress.",
    }


# ── GET /repos/{repo_id}/docs/export/status ───────────────────────────────────

@repos_router.get("/{repo_id}/docs/export/status", status_code=200)
def export_status(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Poll the status of a running docs export job (scoped)."""
    repo = get_user_repo(repo_id, db, current_user)
    with _job_lock:
        job = _export_jobs.get(repo.id)
    if job is None:
        return {"repo_id": repo.id, "status": "not_started"}
    return {"repo_id": repo.id, **job}


# ── GET /repos/{repo_id}/docs/download/{fmt} ─────────────────────────────────

@repos_router.get("/{repo_id}/docs/download/{fmt}")
def download_doc_format(
    repo_id: str,
    fmt: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    allow_draft: bool = False,
):
    """
    Stream documentation in specified format: md, pdf, or zip bundle (scoped).
    Final publication downloads (PDF / ZIP) require suite completion unless allow_draft=True.
    """
    import json
    from docgen.schema import SECTIONS_META

    repo = get_user_repo(repo_id, db, current_user)

    docs_dir = STORAGE_ROOT / repo.id / "docs"
    if not docs_dir.exists():
        raise HTTPException(status_code=404, detail="No documentation generated yet. Generate docs first.")

    manifest_file = docs_dir / "metadata" / "documentation-manifest.json"
    manifest_data = {}
    if manifest_file.exists():
        try:
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    is_complete = manifest_data.get("is_complete", False)
    fmt = fmt.lower()

    if fmt in ("pdf", "zip") and not is_complete and not allow_draft:
        raise HTTPException(
            status_code=409,
            detail="Documentation suite is incomplete. All 16 canonical sections must be generated and pass validation before the final complete suite can be downloaded.",
        )

    if fmt == "pdf":
        file_path = docs_dir / "FULL_PROJECT_DOCUMENTATION.pdf"
        if not file_path.exists():
            try:
                from docgen.pdf_exporter import generate_pdf_documentation
                from docgen.schema import DocSection
                manifest_sections = manifest_data.get("sections", [])
                sec_objs = []
                for idx, s in enumerate(manifest_sections):
                    fn = s.get("filename")
                    fpath = docs_dir / fn if fn else None
                    cnt = fpath.read_text(encoding="utf-8") if fpath and fpath.exists() else ""
                    sec_objs.append(DocSection(
                        section_number=s.get("section_number") or (idx + 1),
                        title=s.get("title", f"Section {idx+1}"),
                        schema_key=s.get("schema_key", ""),
                        filename=fn or f"section_{idx+1}.md",
                        content=cnt,
                    ))
                if sec_objs:
                    generate_pdf_documentation(
                        project_name=repo.name,
                        sections=sec_objs,
                        master_md="",
                        output_path=file_path,
                        metadata=manifest_data.get("metadata", {}),
                        assets_dir=docs_dir / "assets",
                    )
            except Exception as auto_pdf_err:
                logger.error("On-demand PDF compilation failed for %s: %s", repo.id, auto_pdf_err)

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="PDF documentation not generated yet.")
        return FileResponse(
            path=str(file_path),
            media_type="application/pdf",
            filename=f"{repo.name}-documentation.pdf",
        )
    elif fmt == "md":
        file_path = docs_dir / "FULL_PROJECT_DOCUMENTATION.md"
        if not file_path.exists():
            file_path = docs_dir / "README.md"
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Markdown documentation not generated yet.")
        return FileResponse(
            path=str(file_path),
            media_type="text/markdown; charset=utf-8",
            filename=f"{repo.name}-documentation.md",
        )
    elif fmt == "html":
        file_path = docs_dir / "FULL_PROJECT_DOCUMENTATION.html"
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="HTML documentation not generated yet.")
        return FileResponse(
            path=str(file_path),
            media_type="text/html; charset=utf-8",
            filename=f"{repo.name}-documentation.html",
        )
    elif fmt == "json":
        file_path = docs_dir / "FULL_PROJECT_DOCUMENTATION.json"
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="JSON documentation not generated yet.")
        return FileResponse(
            path=str(file_path),
            media_type="application/json",
            filename=f"{repo.name}-documentation.json",
        )
    elif fmt == "zip":
        from datetime import datetime, timezone
        buf = io.BytesIO()
        root_prefix = "project-documentation"
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Project README
            readme_p = docs_dir / "README.md"
            if readme_p.exists():
                zf.write(readme_p, arcname=f"{root_prefix}/README.md")

            # 2. Master documentation (Both canonical root and markdown subfolder)
            master_md_p = docs_dir / "FULL_PROJECT_DOCUMENTATION.md"
            if master_md_p.exists():
                zf.write(master_md_p, arcname=f"{root_prefix}/FULL_PROJECT_DOCUMENTATION.md")
                zf.write(master_md_p, arcname=f"{root_prefix}/master-documentation.md")
                zf.write(master_md_p, arcname=f"{root_prefix}/markdown/project-documentation.md")

            # 3. Individual canonical section markdown files
            for sec_num, title, schema_key, canonical_filename in SECTIONS_META:
                sec_p = docs_dir / canonical_filename
                if sec_p.exists():
                    zf.write(sec_p, arcname=f"{root_prefix}/markdown/{canonical_filename}")

            # 4. PDF publication
            pdf_p = docs_dir / "FULL_PROJECT_DOCUMENTATION.pdf"
            if not pdf_p.exists():
                # Attempt on-demand compilation
                try:
                    from docgen.pdf_exporter import generate_pdf_documentation
                    from docgen.schema import DocSection
                    manifest_sections = manifest_data.get("sections", [])
                    sec_objs = []
                    for idx, s in enumerate(manifest_sections):
                        fn = s.get("filename")
                        fpath = docs_dir / fn if fn else None
                        cnt = fpath.read_text(encoding="utf-8") if fpath and fpath.exists() else ""
                        sec_objs.append(DocSection(
                            section_number=s.get("section_number") or (idx + 1),
                            title=s.get("title", f"Section {idx+1}"),
                            schema_key=s.get("schema_key", ""),
                            filename=fn or f"section_{idx+1}.md",
                            content=cnt,
                        ))
                    if sec_objs:
                        generate_pdf_documentation(
                            project_name=repo.name,
                            sections=sec_objs,
                            master_md="",
                            output_path=pdf_p,
                            metadata=manifest_data.get("metadata", {}),
                            assets_dir=docs_dir / "assets",
                        )
                except Exception as auto_pdf_err:
                    logger.warning("Could not build PDF for zip: %s", auto_pdf_err)

            if pdf_p.exists():
                zf.write(pdf_p, arcname=f"{root_prefix}/FULL_PROJECT_DOCUMENTATION.pdf")
                zf.write(pdf_p, arcname=f"{root_prefix}/pdf/project-documentation.pdf")

            # 5. Rendered Diagrams (.svg, .png)
            diag_dirs = [docs_dir / "diagrams", docs_dir / "assets"]
            seen_diags = set()
            for d_dir in diag_dirs:
                if d_dir.exists():
                    for d_file in sorted(d_dir.glob("*.*")):
                        if d_file.suffix.lower() in (".svg", ".png") and d_file.name not in seen_diags:
                            zf.write(d_file, arcname=f"{root_prefix}/diagrams/{d_file.name}")
                            seen_diags.add(d_file.name)

            # 6. Diagram source (.mmd)
            diag_src_dir = docs_dir / "diagram-source"
            if diag_src_dir.exists():
                for mmd_file in sorted(diag_src_dir.glob("*.mmd")):
                    zf.write(mmd_file, arcname=f"{root_prefix}/diagram-source/{mmd_file.name}")

            # 7. Evidence model & verification summary
            evidence_file = docs_dir / "evidence" / "analysis-summary.json"
            if evidence_file.exists():
                zf.write(evidence_file, arcname=f"{root_prefix}/evidence/analysis-summary.json")

            # 8. Documentation metadata manifest
            manifest_file = docs_dir / "metadata" / "documentation-manifest.json"
            if manifest_file.exists():
                zf.write(manifest_file, arcname=f"{root_prefix}/metadata/documentation-manifest.json")

            # Additional multi-format bundles (HTML, JSON)
            for extra_name in ("FULL_PROJECT_DOCUMENTATION.html", "FULL_PROJECT_DOCUMENTATION.json"):
                extra_p = docs_dir / extra_name
                if extra_p.exists():
                    zf.write(extra_p, arcname=f"{root_prefix}/{extra_name}")

            # 9. Package Manifest
            pkg_manifest = {
                "repository": repo.name,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "canonical_sections_count": len(SECTIONS_META),
                "format": "CodeBrain Documentation Package v2.0",
                "contents": [
                    "FULL_PROJECT_DOCUMENTATION.md",
                    "FULL_PROJECT_DOCUMENTATION.pdf",
                    "README.md",
                    "markdown/ (16 Canonical Sections 01..16)",
                    "diagrams/ (Rendered SVG and PNG visual assets)",
                    "diagram-source/ (Raw Mermaid specifications)",
                    "evidence/ (Verification model & analysis summary)",
                    "metadata/ (Documentation manifest & quality gate)",
                ]
            }
            zf.writestr(f"{root_prefix}/manifest.json", json.dumps(pkg_manifest, indent=2))

        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{repo.name}-docs-bundle.zip"'},
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid format. Supported: md, pdf, html, json, zip")



# ── GET /repos/{repo_id}/docs/export/download ─────────────────────────────────

@repos_router.get("/{repo_id}/docs/export/download")
def download_docs(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return download_doc_format(repo_id, "zip", current_user, db)
