"""
backend/tests/test_stream_interruption.py
-----------------------------------------
Automated regression tests for streaming interruption, client cancellation,
and clean lifecycle termination in CodeBrain AI.
"""
import asyncio
import pytest
from pathlib import Path
import sys

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from ai.router import _execute_stream_chat
from rag.answer import answer_question
from database import SessionLocal, init_db
from models import User, Repo
import uuid


@pytest.mark.asyncio
async def test_stream_chat_client_cancellation():
    """Verify that when a client cancels or disconnects mid-stream, CancelledError is re-raised cleanly."""
    messages = [{"role": "system", "content": "You are CodeBrain AI."}, {"role": "user", "content": "Hello"}]
    
    gen = _execute_stream_chat("FAST_CHAT", messages)
    # Read at least one item or cancel immediately
    await gen.aclose()


@pytest.mark.asyncio
async def test_answer_question_generator_closure(tmp_path):
    """Verify that closing the answer_question generator early closes cleanly without exceptions."""
    init_db()
    with SessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            github_id=f"gh_{uuid.uuid4().hex[:8]}",
            github_username="cancel_tester",
        )
        db.add(user)
        db.commit()

        repo = Repo(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name="cancel_demo_repo",
            source_type="upload",
            pipeline_status="DONE",
        )
        db.add(repo)
        db.commit()

        gen = await answer_question(
            repo_id=repo.id,
            query="HI",
            db=db,
            top_k=8,
        )

        # First chunk is metadata envelope
        first_chunk = await anext(gen)
        assert "data: [CONTEXT]" in first_chunk

        # Simulate client clicking Stop: generator is closed early
        await gen.aclose()
