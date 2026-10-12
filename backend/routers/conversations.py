"""
routers/conversations.py
-------------------------
Manages Copilot conversations with 7-day retention, scoped strictly to
(authenticated user, repository).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, get_user_repo
from database import get_db
from models import Conversation, ConversationMessage, Repo, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos", tags=["conversations"])

RETENTION_DAYS = 7


def _to_naive_utc(dt: datetime) -> datetime:
    if dt is None:
        return datetime.utcnow()
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _get_cutoff() -> datetime:
    return datetime.utcnow() - timedelta(days=RETENTION_DAYS)


def _enforce_retention(repo_id: str, user_id: str, db: Session) -> None:
    """Purge conversations whose last activity exceeds 7 days."""
    cutoff = _get_cutoff()
    try:
        deleted_count = (
            db.query(Conversation)
            .filter(
                Conversation.user_id == user_id,
                Conversation.repo_id == repo_id,
                Conversation.updated_at < cutoff,
            )
            .delete(synchronize_session=False)
        )
        if deleted_count > 0:
            db.commit()
            logger.info("Purged %d expired conversations (>%d days) for repo %s", deleted_count, RETENTION_DAYS, repo_id)
    except Exception as exc:
        logger.warning("Error enforcing conversation retention for repo %s: %s", repo_id, exc)
        db.rollback()


class MessageCreate(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., min_length=1)
    citations: Optional[List[dict]] = None
    error_reports: Optional[List[dict]] = None


class ConversationCreate(BaseModel):
    title: Optional[str] = "New Conversation"
    model_provider: Optional[str] = None
    model_name: Optional[str] = None


@router.get("/{repo_id}/conversations", status_code=200)
def list_conversations(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all active conversations for the repository (retained up to 7 days)."""
    repo = get_user_repo(repo_id, db, current_user)
    _enforce_retention(repo.id, current_user.id, db)

    convs = (
        db.query(Conversation)
        .filter(
            Conversation.user_id == current_user.id,
            Conversation.repo_id == repo.id,
        )
        .order_by(Conversation.updated_at.desc())
        .all()
    )

    result = []
    for c in convs:
        result.append({
            "id": c.id,
            "repo_id": c.repo_id,
            "title": c.title,
            "last_message_preview": c.last_message_preview,
            "model_provider": c.model_provider,
            "model_name": c.model_name,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "message_count": len(c.messages),
        })
    return {"conversations": result}


@router.post("/{repo_id}/conversations", status_code=201)
def create_conversation(
    repo_id: str,
    body: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new conversation session (+ New Chat)."""
    repo = get_user_repo(repo_id, db, current_user)
    _enforce_retention(repo.id, current_user.id, db)

    now = datetime.now(timezone.utc)
    conv = Conversation(
        user_id=current_user.id,
        repo_id=repo.id,
        title=body.title or "New Conversation",
        model_provider=body.model_provider,
        model_name=body.model_name,
        created_at=now,
        updated_at=now,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    return {
        "id": conv.id,
        "repo_id": conv.repo_id,
        "title": conv.title,
        "last_message_preview": None,
        "model_provider": conv.model_provider,
        "model_name": conv.model_name,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": [],
    }


@router.get("/{repo_id}/conversations/{conv_id}", status_code=200)
def get_conversation(
    repo_id: str,
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve a single conversation and its full chronological message list."""
    repo = get_user_repo(repo_id, db, current_user)
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
            Conversation.repo_id == repo.id,
        )
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or has expired.")

    # Check 7-day cutoff
    cutoff = _get_cutoff()
    if _to_naive_utc(conv.updated_at) < cutoff:
        db.delete(conv)
        db.commit()
        raise HTTPException(status_code=404, detail="Conversation expired past 7 days.")

    formatted_messages = []
    for m in conv.messages:
        cits = None
        if m.citations:
            try:
                cits = json.loads(m.citations)
            except Exception:
                cits = None
        errs = None
        if m.error_reports:
            try:
                errs = json.loads(m.error_reports)
            except Exception:
                errs = None

        formatted_messages.append({
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "citations": cits,
            "error_reports": errs,
            "created_at": m.created_at.isoformat(),
        })

    return {
        "id": conv.id,
        "repo_id": conv.repo_id,
        "title": conv.title,
        "model_provider": conv.model_provider,
        "model_name": conv.model_name,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": formatted_messages,
    }


@router.post("/{repo_id}/conversations/{conv_id}/messages", status_code=201)
def add_message(
    repo_id: str,
    conv_id: str,
    body: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Append a message turn to an existing active conversation."""
    repo = get_user_repo(repo_id, db, current_user)
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
            Conversation.repo_id == repo.id,
        )
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or has expired.")

    now = datetime.now(timezone.utc)
    cits_json = json.dumps(body.citations) if body.citations else None
    errs_json = json.dumps(body.error_reports) if body.error_reports else None

    msg = ConversationMessage(
        conversation_id=conv.id,
        role=body.role,
        content=body.content,
        citations=cits_json,
        error_reports=errs_json,
        created_at=now,
    )
    db.add(msg)

    # Update conversation timestamps & summary
    conv.updated_at = now
    preview = body.content[:120].strip()
    conv.last_message_preview = preview
    if conv.title == "New Conversation" and body.role == "user":
        # Auto-title from first user question
        conv.title = body.content[:45].strip() + ("…" if len(body.content) > 45 else "")

    # Update repo last activity
    repo.last_activity_at = now
    repo.last_activity_summary = f"Copilot chat: {conv.title}"

    db.commit()
    db.refresh(msg)

    return {
        "id": msg.id,
        "conversation_id": conv.id,
        "role": msg.role,
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
    }


@router.delete("/{repo_id}/conversations/{conv_id}", status_code=200)
def delete_conversation(
    repo_id: str,
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a conversation explicitly."""
    repo = get_user_repo(repo_id, db, current_user)
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
            Conversation.repo_id == repo.id,
        )
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    db.delete(conv)
    db.commit()
    return {"deleted": True, "id": conv_id}
