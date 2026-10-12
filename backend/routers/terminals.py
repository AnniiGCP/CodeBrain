"""
backend/routers/terminals.py
----------------------------
REST API endpoints for managing multiple independent terminal sessions per workspace.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, get_user_repo, verify_session_token
from database import get_db
from models import User
from terminals.manager import terminal_manager

logger = logging.getLogger("routers.terminals")

router = APIRouter(prefix="/repos", tags=["terminals"])


class CreateTerminalRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=64, description="Optional custom tab title (e.g. 'Frontend Server')")
    subpath: Optional[str] = Field(None, max_length=128, description="Optional subfolder relative to repo root")


class ExecuteCommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=2000, description="Shell command line to execute")


class SendInputRequest(BaseModel):
    text: str = Field(..., max_length=1000, description="Standard input text to stream to running process")


@router.post("/{repo_id}/terminals", status_code=201)
def create_terminal_session(
    repo_id: str,
    body: Optional[CreateTerminalRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new independent terminal session scoped to the authenticated user and repository."""
    repo = get_user_repo(repo_id, db, current_user)
    title = body.title if body else None
    subpath = body.subpath if body else None

    session = terminal_manager.create_session(
        user_id=current_user.id,
        repo_id=repo.id,
        title=title,
        subpath=subpath,
    )
    return session.to_dict()


@router.get("/{repo_id}/terminals", status_code=200)
def list_terminal_sessions(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all active terminal sessions for the given repository."""
    repo = get_user_repo(repo_id, db, current_user)
    sessions = terminal_manager.list_sessions(user_id=current_user.id, repo_id=repo.id)
    return [s.to_dict() for s in sessions]


@router.get("/{repo_id}/terminals/{session_id}", status_code=200)
def get_terminal_session(
    repo_id: str,
    session_id: str,
    since: int = Query(0, ge=0, description="Fetch output lines since this buffer index"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get session metadata and stream output lines generated since the given index."""
    repo = get_user_repo(repo_id, db, current_user)
    session = terminal_manager.get_session(session_id=session_id, user_id=current_user.id)
    if not session or session.repo_id != repo.id:
        raise HTTPException(status_code=404, detail="Terminal session not found.")

    lines, next_index = session.get_output(since_index=since)
    info = session.to_dict()
    info["lines"] = lines
    info["next_index"] = next_index
    return info


@router.post("/{repo_id}/terminals/{session_id}/command", status_code=200)
def execute_terminal_command(
    repo_id: str,
    session_id: str,
    body: ExecuteCommandRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Execute a shell command inside the independent terminal session."""
    repo = get_user_repo(repo_id, db, current_user)
    session = terminal_manager.get_session(session_id=session_id, user_id=current_user.id)
    if not session or session.repo_id != repo.id:
        raise HTTPException(status_code=404, detail="Terminal session not found.")

    ok = session.execute_command(body.command)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Session is already executing another process. Wait for completion or stop it first.",
        )
    return {"status": "running", "session_id": session_id, "command": body.command}


@router.post("/{repo_id}/terminals/{session_id}/input", status_code=200)
def send_terminal_input(
    repo_id: str,
    session_id: str,
    body: SendInputRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send standard input (stdin) to the currently running process in the session."""
    repo = get_user_repo(repo_id, db, current_user)
    session = terminal_manager.get_session(session_id=session_id, user_id=current_user.id)
    if not session or session.repo_id != repo.id:
        raise HTTPException(status_code=404, detail="Terminal session not found.")

    ok = session.send_input(body.text)
    return {"sent": ok}


@router.post("/{repo_id}/terminals/{session_id}/stop", status_code=200)
def stop_terminal_process(
    repo_id: str,
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stop/terminate the actively running process inside the session without closing the tab."""
    repo = get_user_repo(repo_id, db, current_user)
    session = terminal_manager.get_session(session_id=session_id, user_id=current_user.id)
    if not session or session.repo_id != repo.id:
        raise HTTPException(status_code=404, detail="Terminal session not found.")

    session.stop_process()
    return {"status": "stopped", "session_id": session_id}


@router.delete("/{repo_id}/terminals/{session_id}", status_code=200)
def close_terminal_session(
    repo_id: str,
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Close and destroy the terminal session and terminate its process tree."""
    repo = get_user_repo(repo_id, db, current_user)
    ok = terminal_manager.close_session(session_id=session_id, user_id=current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Terminal session not found.")
    return {"status": "closed", "session_id": session_id}


@router.websocket("/{repo_id}/terminals/{session_id}/ws")
async def terminal_websocket_endpoint(
    websocket: WebSocket,
    repo_id: str,
    session_id: str,
    token: Optional[str] = Query(None),
):
    """Real-time bidirectional WebSocket stream for interactive terminal execution and output."""
    await websocket.accept()

    user_id = verify_session_token(token) if token else None
    if not user_id:
        await websocket.send_json({"type": "error", "message": "Authentication failed or token expired."})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    session = terminal_manager.get_session(session_id=session_id, user_id=user_id)
    if not session or session.repo_id != repo_id:
        await websocket.send_json({"type": "error", "message": "Terminal session not found or unauthorized."})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    lines, next_idx = session.get_output(since_index=0)
    await websocket.send_json({
        "type": "init",
        "session": session.to_dict(),
        "lines": lines,
        "next_index": next_idx,
    })

    last_index = next_idx

    async def _send_output_loop():
        nonlocal last_index
        try:
            while True:
                lines, new_idx = session.get_output(since_index=last_index)
                if lines:
                    last_index = new_idx
                    await websocket.send_json({
                        "type": "output",
                        "lines": lines,
                        "next_index": new_idx,
                        "status": session.status,
                        "exit_code": session.exit_code,
                    })
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Output send loop ended: %s", exc)

    send_task = asyncio.create_task(_send_output_loop())

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "command":
                cmd = data.get("command", "")
                session.execute_command(cmd)
            elif msg_type == "input":
                txt = data.get("text", "")
                session.send_input(txt)
            elif msg_type == "stop":
                session.stop_process()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket error on session %s: %s", session_id, exc)
    finally:
        send_task.cancel()
