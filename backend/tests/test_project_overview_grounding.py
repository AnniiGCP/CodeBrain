"""
backend/tests/test_project_overview_grounding.py
------------------------------------------------
Comprehensive tests verifying:
1. Accurate intent classification for project overview questions:
   - "Tell me about the project."
   - "Explain this repository."
   - "What problem does this project solve?"
   - "How does the application work?"
   - "Explain the major modules and technologies."
2. 8-section structured project overview prompt integrity.
3. High-quality repository context assembly without random vector chunk pollution.
4. Model routing for PROJECT_OVERVIEW task with manual selection preservation.
5. Real-time analysis status indicator streaming (Requirement D).
"""
import asyncio
import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

import pytest
from ai.policy import (
    QueryIntent,
    classify_intent,
    should_retrieve_context,
    get_system_prompt_for_intent,
)
from ai.config import get_model_for_task
from rag.answer import answer_question, build_project_overview_context
from database import SessionLocal
from models import Repo


# ── 1. Intent Classification Tests ──────────────────────────────────────────

def test_project_overview_intent_classification():
    """Project overview questions deterministically classify as PROJECT_OVERVIEW."""
    test_queries = [
        "Tell me about the project.",
        "tell me about project",
        "tell me about this project",
        "Explain this repository.",
        "explain this repo",
        "What problem does this project solve?",
        "What problem does this solve?",
        "How does the application work?",
        "how does the app work?",
        "How does this application work",
        "Explain the major modules and technologies.",
        "what does this project do",
        "overview of the project",
        "walk me through this project",
    ]
    for q in test_queries:
        intent = classify_intent(q)
        assert intent == QueryIntent.PROJECT_OVERVIEW, f"Expected PROJECT_OVERVIEW for '{q}', got {intent}"
        assert should_retrieve_context(intent) is True, f"Retrieval should be enabled for '{q}'"


def test_greeting_and_general_skip_overview():
    """Greetings and general programming questions do not trigger project overview."""
    assert classify_intent("Hi") == QueryIntent.GREETING
    assert classify_intent("Hello CodeBrain") == QueryIntent.GREETING
    assert classify_intent("What is a database?") == QueryIntent.GENERAL_PROGRAMMING
    assert classify_intent("Explain REST API difference between PUT and PATCH") == QueryIntent.GENERAL_PROGRAMMING


# ── 2. System Prompt Structure Tests ────────────────────────────────────────

def test_project_overview_prompt_contains_all_8_sections():
    """The system prompt for PROJECT_OVERVIEW enforces the exact 8-part mental model."""
    prompt = get_system_prompt_for_intent(QueryIntent.PROJECT_OVERVIEW)
    
    assert "## 1. Project Overview" in prompt
    assert "## 2. Main Features" in prompt
    assert "## 3. Technology Stack" in prompt
    assert "## 4. How the Project Works" in prompt
    assert "## 5. Architecture" in prompt
    assert "## 6. Important Implementation Details" in prompt
    assert "## 7. Current Status and Limitations" in prompt
    assert "## 8. Summary" in prompt

    # Prohibitions & quality constraints
    assert "Do NOT start with a generic description" in prompt
    assert "Technology or Layer" in prompt
    assert "Actual Role in the Project" in prompt
    assert "Do NOT dump every dependency" in prompt
    assert "Do NOT begin with microscopic code snippets" in prompt


# ── 3. Context Grounding & Extraction Tests ─────────────────────────────────

def test_project_overview_context_extraction():
    """build_project_overview_context extracts verified facts for the test repository."""
    db = SessionLocal()
    try:
        repo = db.query(Repo).filter(Repo.name.in_(["QuizGenAI", "myapp", "test-auto-repo"])).first()
        if not repo:
            repo = db.query(Repo).first()
        if not repo:
            pytest.skip("No test repo found in database")

        context_block, citations = build_project_overview_context(repo.id, db)
        assert context_block, "Expected non-empty context block"
        assert "VERIFIED REPOSITORY PROJECT OVERVIEW" in context_block
        assert "VERIFIED PROJECT IDENTITY & DOMAIN PURPOSE" in context_block
        assert "VERIFIED TECHNOLOGY STACK BY LAYER" in context_block
        assert "CURRENT STATUS & LIMITATIONS" in context_block
    finally:
        db.close()


# ── 4. Model Routing Tests ──────────────────────────────────────────────────

def test_model_routing_for_project_overview():
    """Auto routing selects strong reasoning model for PROJECT_OVERVIEW."""
    route = get_model_for_task("PROJECT_OVERVIEW")
    assert route["provider"] in ("apinex", "nvidia", "groq")
    assert route["modelId"] in ("free/gpt-6-luna", "glm-5-3", "deepseek-v4.1-flash", "openai/gpt-oss-120b")
    assert len(route["fallbackChain"]) >= 1


def test_manual_model_selection_preserved():
    """User-specified model override is preserved and not replaced by Auto."""
    from ai.config import _MODEL_HEALTH
    _MODEL_HEALTH.clear()
    manual_route = get_model_for_task(
        "PROJECT_OVERVIEW",
        user_preferred_provider="nvidia",
        user_preferred_model="deepseek-v4.1-flash",
    )
    assert manual_route["provider"] == "nvidia"
    assert manual_route["modelId"] == "deepseek-v4.1-flash"


# ── 5. Status Streaming Tests (Requirement D) ───────────────────────────────

@pytest.mark.asyncio
async def test_status_sse_events_emitted_for_overview():
    """answer_question emits real-time data: [STATUS] SSE events for project overview queries."""
    db = SessionLocal()
    try:
        repo = db.query(Repo).first()
        if not repo:
            pytest.skip("No repo in DB to test generator")

        gen = await answer_question(repo.id, "Tell me about the project.", db)
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)
            if "data: [CONTEXT]" in chunk:
                break  # Test only the initial pre-stream status phase

        joined = "".join(chunks)
        assert "data: [STATUS] Analyzing repository…" in joined
        assert "data: [STATUS] Inspecting relevant components…" in joined
        assert "data: [STATUS] Preparing explanation…" in joined
        assert "data: [CONTEXT]" in joined
    finally:
        db.close()


@pytest.mark.asyncio
async def test_no_status_for_greeting():
    """Greetings do NOT emit data: [STATUS] analysis events."""
    db = SessionLocal()
    try:
        repo = db.query(Repo).first()
        if not repo:
            pytest.skip("No repo in DB to test generator")

        gen = await answer_question(repo.id, "Hi", db)
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)
            if "data: [CONTEXT]" in chunk:
                break

        joined = "".join(chunks)
        assert "data: [STATUS]" not in joined
        assert "data: [CONTEXT]" in joined
    finally:
        db.close()
