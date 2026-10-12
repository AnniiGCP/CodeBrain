"""
POST /repos/{repo_id}/embed  — trigger embedding (background task)
POST /repos/{repo_id}/search — semantic search
GET  /repos/{repo_id}/embed/status — check embedding status
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, get_user_repo
from database import get_db
from models import User
from vectorstore.index import embed_repo, search

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/repos", tags=["embeddings"])

# ── simple in-process status tracker ────────────────────────────────────────
_embed_status: dict[str, dict] = {}
_status_lock = threading.Lock()


def _run_embed(repo_id: str) -> None:
    from database import SessionLocal

    db = SessionLocal()
    try:
        with _status_lock:
            _embed_status[repo_id] = {"status": "running", "error": None, "stats": None}

        stats = embed_repo(repo_id, db)

        with _status_lock:
            _embed_status[repo_id] = {"status": "done", "error": None, "stats": stats}
        logger.info("Embedding finished for %s: %s", repo_id, stats)
    except Exception as exc:
        logger.exception("Embedding failed for %s", repo_id)
        with _status_lock:
            _embed_status[repo_id] = {"status": "error", "error": str(exc), "stats": None}
    finally:
        db.close()


# ── POST /repos/{repo_id}/embed ──────────────────────────────────────────────

@router.post("/{repo_id}/embed", status_code=202)
def trigger_embed(
    repo_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Kick off (incremental) embedding in a background thread.
    Scoped to repo owner.
    """
    repo = get_user_repo(repo_id, db, current_user)

    with _status_lock:
        current = _embed_status.get(repo_id, {})
        if current.get("status") == "running":
            return {"repo_id": repo_id, "status": "already_running"}

    background_tasks.add_task(_run_embed, repo.id)

    return {"repo_id": repo.id, "status": "accepted", "message": "Embedding started in background."}


# ── GET /repos/{repo_id}/embed/status ────────────────────────────────────────

@router.get("/{repo_id}/embed/status", status_code=200)
def embed_status(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check embedding progress/status. Scoped to repo owner."""
    repo = get_user_repo(repo_id, db, current_user)
    with _status_lock:
        status = _embed_status.get(repo.id)
    if status is None:
        return {"repo_id": repo.id, "status": "not_started"}
    return {"repo_id": repo.id, **status}


# ── POST /repos/{repo_id}/search ─────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(8, ge=1, le=50)


@router.post("/{repo_id}/search", status_code=200)
def search_repo(
    repo_id: str,
    body: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Semantic search over a repo's embedded symbols. Scoped to repo owner."""
    repo = get_user_repo(repo_id, db, current_user)

    try:
        results = search(repo.id, body.query, body.top_k or 8, db)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Search failed for %s", repo.id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "repo_id": repo.id,
        "query": body.query,
        "top_k": body.top_k,
        "results": results,
    }
