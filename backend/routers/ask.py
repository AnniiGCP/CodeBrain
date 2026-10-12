"""
POST /repos/{repo_id}/ask — streaming RAG endpoint (supports text, voice, and screenshot/image inputs)
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_user_repo
from database import get_db
from models import User
from rate_limiter import enforce_ai_action_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/repos", tags=["rag"])

MAX_QUERY_CHARS = 50_000
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}


@router.post("/{repo_id}/ask")
async def ask_repo(
    repo_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stream an LLM answer grounded in the repo's code. Scoped to repo owner.
    Supports:
      - application/json: {"query": "...", "top_k": 8}
      - multipart/form-data: query, top_k, and optional image UploadFile

    Response is a text/event-stream.
    First line: JSON metadata with citations and matched error reports (prefixed 'data: [CONTEXT]').
    Subsequent lines: raw LLM tokens.
    """
    # 1. Enforce AI action rate limit for authenticated user
    enforce_ai_action_rate_limit(current_user.id)

    repo = get_user_repo(repo_id, db, current_user)

    content_type = request.headers.get("content-type", "")
    query = ""
    top_k = 8
    image_bytes = None
    image_mime_type = None
    provider = None
    model = None

    if "multipart" in content_type or "form-data" in content_type:
        form = await request.form()
        query = str(form.get("query", "") or "").strip()
        provider = str(form.get("provider", "") or "").strip() or None
        model = str(form.get("model", "") or "").strip() or None
        try:
            top_k = int(form.get("top_k", 8))
        except (ValueError, TypeError):
            top_k = 8

        image_item = form.get("image")
        if image_item is not None and hasattr(image_item, "read"):
            read_fn = image_item.read
            import inspect
            if inspect.iscoroutinefunction(read_fn):
                image_bytes = await read_fn()
            else:
                image_bytes = read_fn()
            image_mime_type = getattr(image_item, "content_type", None) or "image/png"
    else:
        try:
            body_json = await request.json()
            query = str(body_json.get("query", "") or "").strip()
            top_k = int(body_json.get("top_k", 8))
            provider = str(body_json.get("provider", "") or "").strip() or None
            model = str(body_json.get("model", "") or "").strip() or None
        except Exception:
            try:
                form = await request.form()
                query = str(form.get("query", "") or "").strip()
                provider = str(form.get("provider", "") or "").strip() or None
                model = str(form.get("model", "") or "").strip() or None
                image_item = form.get("image")
                if image_item is not None and hasattr(image_item, "read"):
                    read_fn = image_item.read
                    import inspect
                    if inspect.iscoroutinefunction(read_fn):
                        image_bytes = await read_fn()
                    else:
                        image_bytes = read_fn()
                    image_mime_type = getattr(image_item, "content_type", None) or "image/png"
            except Exception:
                pass

    if provider and provider.lower() == "auto":
        provider = None
    if model and model.lower() == "auto":
        model = None

    if not query and not image_bytes:
        raise HTTPException(
            status_code=422,
            detail="Either a text query or an image attachment must be provided.",
        )

    # 2. Strict Input Bounds and Format Validation
    if len(query) > MAX_QUERY_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Query length exceeds maximum limit of {MAX_QUERY_CHARS} characters.",
        )

    # Clamp top_k to safe bounds [1, 50]
    top_k = max(1, min(top_k, 50))

    if image_bytes is not None:
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Attached image exceeds maximum limit of {MAX_IMAGE_BYTES // (1024*1024)}MB.",
            )
        if image_mime_type and image_mime_type.lower() not in ALLOWED_IMAGE_MIMES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image MIME type '{image_mime_type}'. Supported: png, jpeg, webp, gif.",
            )

    import sys, importlib
    if "ai.policy" in sys.modules:
        import ai.policy
        importlib.reload(ai.policy)
    if "rag.answer" in sys.modules:
        import rag.answer
        importlib.reload(rag.answer)
    from rag.answer import answer_question
    gen = await answer_question(
        repo_id=repo.id,
        query=query,
        db=db,
        top_k=top_k,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
        provider=provider,
        model=model,
    )

    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )

