"""
routers/pipeline.py
--------------------
Background auto-pipeline that runs automatically after repo ingestion:
  CLONING → PARSING → EMBEDDING → ANALYZING → DETECTING_ERRORS → DONE

Exposes:
  GET  /repos/{repo_id}/pipeline-status   — poll progress
  POST /repos/{repo_id}/pipeline/run      — manually re-trigger (fallback)
"""
from __future__ import annotations

import json
import logging
import threading

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from auth import get_current_user, get_user_repo
from models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos", tags=["pipeline"])

# Thread-safe in-process current-step message tracker
# (pipeline_status on the DB is the ground truth; this gives a richer message)
_step_messages: dict[str, str] = {}
_step_lock = threading.Lock()


def _set_status(repo_id: str, status: str, message: str, db: Session, error: str | None = None) -> None:
    """Update pipeline_status on the Repo row and the in-memory message."""
    from models import Repo

    with _step_lock:
        _step_messages[repo_id] = message

    try:
        repo = db.query(Repo).filter(Repo.id == repo_id).first()
        if repo:
            repo.pipeline_status = status
            if error is not None:
                repo.pipeline_error = error
            db.commit()
    except Exception as exc:
        logger.exception("_set_status failed for %s: %s", repo_id, exc)


def run_pipeline(repo_id: str) -> None:
    """
    The full ingestion pipeline.  Runs in a background thread opened with its own DB session.
    Steps:
      1. PARSING    — embed_repo internally handles symbol extraction via code_parser
      2. EMBEDDING  — FAISS index build
      3. ANALYZING  — static structure analysis
      4. DETECTING_ERRORS — heuristic error scan
    """
    db = SessionLocal()
    try:
        # ── Step 1: PARSING (symbol extraction is done inside embed_repo) ─────
        _set_status(repo_id, "PARSING", "Extracting code symbols…", db)

        from vectorstore.index import embed_repo

        # ── Step 2: EMBEDDING ─────────────────────────────────────────────────
        _set_status(repo_id, "EMBEDDING", "Building semantic index…", db)
        try:
            stats = embed_repo(repo_id, db)
            logger.info("Embedding done for %s: %s", repo_id, stats)
        except Exception as exc:
            logger.exception("Embedding failed for %s", repo_id)
            _set_status(repo_id, "FAILED", "Embedding failed.", db, error=str(exc))
            return

        # ── Step 3: ANALYZING ─────────────────────────────────────────────────
        _set_status(repo_id, "ANALYZING", "Analysing repository structure…", db)
        try:
            from analysis.structure_analyzer import analyze_structure
            structure = analyze_structure(repo_id, db)
        except Exception as exc:
            logger.exception("Structure analysis failed for %s", repo_id)
            _set_status(repo_id, "FAILED", "Structure analysis failed.", db, error=str(exc))
            return

        # ── Step 4: DETECTING_ERRORS ──────────────────────────────────────────
        _set_status(repo_id, "DETECTING_ERRORS", "Scanning for code issues…", db)
        try:
            from errordetection.scanner import detect_errors
            error_report = detect_errors(repo_id, db)
        except Exception as exc:
            logger.exception("Error detection failed for %s", repo_id)
            _set_status(repo_id, "FAILED", "Error detection failed.", db, error=str(exc))
            return

        # ── Step 4b: Persist ErrorReport rows ────────────────────────────────
        _persist_error_reports(repo_id, error_report["issues"], db)

        # ── Step 4c: CI workflow detection ──────────────────────────────────
        try:
            from automation.ci_setup import detect_ci_workflows
            detect_ci_workflows(repo_id, db)
        except Exception as exc:
            logger.warning("CI detection warning for %s: %s", repo_id, exc)

        # ── Persist combined meta ─────────────────────────────────────────────
        from models import Repo
        repo = db.query(Repo).filter(Repo.id == repo_id).first()
        if repo:
            repo.pipeline_meta = json.dumps({
                "structure": structure,
                "error_report": {
                    "total_symbols_scanned": error_report["total_symbols_scanned"],
                    "total_issues": error_report["total_issues"],
                    # Store only first 200 issues to keep the DB column bounded
                    "issues": error_report["issues"][:200],
                },
            })
            repo.pipeline_status = "DONE"
            repo.pipeline_error = None
            db.commit()

        with _step_lock:
            _step_messages[repo_id] = "Pipeline complete ✓"

        logger.info("Pipeline DONE for repo %s (errors detected: %d, fixes remain manual)", repo_id, error_report.get("total_issues", 0))

        # ── Step 5: Automatically generate documentation suite for the repository
        try:
            def _bg_generate():
                from database import SessionLocal
                from docgen.master_doc_gen import generate_full_project_documentation
                bg_db = SessionLocal()
                try:
                    generate_full_project_documentation(repo_id, bg_db)
                    logger.info("Auto-generated documentation suite for repo %s on pipeline completion", repo_id)
                except Exception as doc_exc:
                    logger.warning("Background auto-docgen failed for repo %s: %s", repo_id, doc_exc)
                finally:
                    bg_db.close()

            threading.Thread(target=_bg_generate, daemon=True, name=f"autodoc-{repo_id}").start()
        except Exception as exc:
            logger.warning("Could not spawn background doc generation for %s: %s", repo_id, exc)

    except Exception as exc:
        logger.exception("Unhandled pipeline error for %s", repo_id)
        _set_status(repo_id, "FAILED", "Unexpected pipeline error.", db, error=str(exc))
    finally:
        db.close()


# ── ErrorReport persistence helpers ──────────────────────────────────────────

def _persist_error_reports(repo_id: str, issues: list[dict], db: Session) -> None:
    """
    Persist ErrorReport rows from the scanner's genuine issue dicts.
    Synchronizes errors so resolved issues are pruned and new/existing issues reflect the latest scan.
    """
    import uuid
    from models import ErrorReport

    current_keys = {(issue["rule_id"], issue["file_path"], issue.get("line")) for issue in issues}

    # Delete any existing reports that are no longer present in the fresh scan (issue was fixed)
    existing_reports = db.query(ErrorReport).filter(ErrorReport.repo_id == repo_id).all()
    for er in existing_reports:
        er_key = (er.rule_id, er.file_path, er.line)
        if er_key not in current_keys and er.fix_status not in ("APPLIED", "APPLIED_LOCAL"):
            db.delete(er)
    db.flush()

    existing = {
        (r.rule_id, r.file_path, r.line)
        for r in db.query(
            ErrorReport.rule_id, ErrorReport.file_path, ErrorReport.line
        ).filter(ErrorReport.repo_id == repo_id).all()
    }

    new_count = 0
    for issue in issues:
        key = (issue["rule_id"], issue["file_path"], issue.get("line"))
        if key in existing:
            continue  # already persisted

        row = ErrorReport(
            id=str(uuid.uuid4()),
            repo_id=repo_id,
            symbol_id=issue.get("symbol_id"),
            rule_id=issue["rule_id"],
            source=issue.get("source", "static_analysis"),
            severity=issue["severity"],
            message=issue["message"],
            file_path=issue["file_path"],
            symbol_name=issue.get("symbol_name"),
            symbol_type=issue.get("symbol_type"),
            language=issue.get("language"),
            line=issue.get("line"),
            column=issue.get("column"),
            stack_trace=issue.get("stack_trace"),
            fix_status="PENDING",
        )
        db.add(row)
        existing.add(key)
        new_count += 1

    db.commit()
    logger.info("Persisted %d new ErrorReport rows for repo %s (total issues: %d)", new_count, repo_id, len(issues))


def _run_suggestion_generation(repo_id: str) -> None:
    """Entry point for the suggestions background thread."""
    db = SessionLocal()
    try:
        from errordetection.suggestion import generate_suggestions_for_repo
        with _step_lock:
            _step_messages[repo_id] = "Generating AI fix suggestions…"
        generate_suggestions_for_repo(repo_id, db)
        with _step_lock:
            _step_messages[repo_id] = "Pipeline complete ✓"
        logger.info("Suggestion generation complete for repo %s", repo_id)
    except Exception as exc:
        logger.exception("Suggestion generation crashed for repo %s: %s", repo_id, exc)
    finally:
        db.close()


def _spawn_suggestion_thread(repo_id: str) -> None:
    """Start a daemon thread to generate suggestions so pipeline stays DONE."""
    t = threading.Thread(
        target=_run_suggestion_generation,
        args=(repo_id,),
        daemon=True,
        name=f"suggestions-{repo_id[:8]}",
    )
    t.start()
    logger.info("Suggestion thread started for repo %s", repo_id)


# ── GET /repos/{repo_id}/pipeline-status ─────────────────────────────────────

@router.get("/{repo_id}/pipeline-status", status_code=200)
@router.get("/{repo_id}/pipeline/status", status_code=200)
def get_pipeline_status(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Poll the current pipeline progress for a repository (scoped to owner)."""
    repo = get_user_repo(repo_id, db, current_user)

    with _step_lock:
        message = _step_messages.get(repo.id, _default_message(repo.pipeline_status))

    # Parse meta for summary counts if DONE
    meta_summary: dict | None = None
    if repo.pipeline_status == "DONE" and repo.pipeline_meta:
        try:
            meta = json.loads(repo.pipeline_meta)
            structure = meta.get("structure", {})
            error_report = meta.get("error_report", {})
            meta_summary = {
                "total_files": structure.get("total_files"),
                "total_symbols": structure.get("total_symbols"),
                "language_dist": structure.get("language_dist"),
                "total_issues": error_report.get("total_issues"),
            }
        except Exception:
            pass

    return {
        "repo_id": repo.id,
        "pipeline_status": repo.pipeline_status,
        "message": message,
        "error": repo.pipeline_error,
        "meta_summary": meta_summary,
    }


# ── POST /repos/{repo_id}/pipeline/run  (manual re-trigger / fallback) ────────

@router.post("/{repo_id}/pipeline/run", status_code=202)
def retrigger_pipeline(
    repo_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually re-trigger the full pipeline (scoped to owner)."""
    repo = get_user_repo(repo_id, db, current_user)

    from rate_limiter import check_and_record_user_pipeline_run
    check_and_record_user_pipeline_run(current_user.id)

    current = repo.pipeline_status
    if current in ("PARSING", "EMBEDDING", "ANALYZING", "DETECTING_ERRORS"):
        return {"repo_id": repo.id, "status": "already_running", "pipeline_status": current}

    # Reset to PARSING
    repo.pipeline_status = "PARSING"
    repo.pipeline_error = None
    db.commit()

    background_tasks.add_task(run_pipeline, repo.id)
    return {"repo_id": repo.id, "status": "accepted", "message": "Pipeline re-triggered."}


# ── GET /repos/{repo_id}/pipeline/results  (structured results) ───────────────

@router.get("/{repo_id}/pipeline/results", status_code=200)
def get_pipeline_results(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the full pipeline results (scoped to owner)."""
    repo = get_user_repo(repo_id, db, current_user)

    if repo.pipeline_status != "DONE":
        raise HTTPException(
            status_code=409,
            detail=f"Pipeline not finished yet (status: {repo.pipeline_status}).",
        )

    if not repo.pipeline_meta:
        return {"repo_id": repo.id, "structure": {}, "error_report": {}}

    try:
        meta = json.loads(repo.pipeline_meta)
    except Exception:
        meta = {}

    return {"repo_id": repo.id, **meta}


# ── GET /repos/{repo_id}/structure ───────────────────────────────────────────

@router.get("/{repo_id}/structure", status_code=200)
def get_repo_structure(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the static structure analysis for a repository (scoped to owner)."""
    from analysis.structure_analyzer import analyze_structure

    repo = get_user_repo(repo_id, db, current_user)

    if repo.pipeline_meta:
        try:
            meta = json.loads(repo.pipeline_meta)
            if "structure" in meta and meta["structure"]:
                return {"repo_id": repo.id, **meta["structure"]}
        except Exception:
            pass

    # Fallback to computing on demand
    structure = analyze_structure(repo.id, db)
    return {"repo_id": repo.id, **structure}


# ── Helper ────────────────────────────────────────────────────────────────────

def _default_message(status: str) -> str:
    return {
        "PENDING": "Waiting to start…",
        "CLONING": "Cloning repository…",
        "PARSING": "Extracting code symbols…",
        "EMBEDDING": "Building semantic index…",
        "ANALYZING": "Analysing structure…",
        "DETECTING_ERRORS": "Scanning for code issues…",
        "AUTO_FIXING": "Auto-fixing issues & validating sandbox…",
        "DONE": "Pipeline complete ✓",
        "FAILED": "Pipeline failed.",
    }.get(status, status)
