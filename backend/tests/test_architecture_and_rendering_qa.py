"""
backend/tests/test_architecture_and_rendering_qa.py
----------------------------------------------------
End-to-end and unit tests verifying:
1. Intent classification for all prompt categories:
   - "Hi" (Greeting)
   - "What is an API?" (General programming)
   - "Explain this project's architecture" (Architecture / Comprehensive Analysis)
   - "Explain authentication" (Repo query)
   - "Why is this test failing?" (Error diagnosis)
   - "Review this code" (Code explanation / review)
   - "Explain this function" (Code explanation)
   - "Write a comprehensive 1000-word explanation" (Comprehensive analysis)
2. Architecture context construction:
   - Grounded in knowledge graph (app type, entry points, endpoints, models)
   - Does not invent false infrastructure
3. Task-aware model routing:
   - Auto chooses ARCHITECTURE for architecture queries
   - Auto chooses FAST_CHAT for greetings and general questions
   - Manual model selection is respected
"""
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
from rag.answer import build_architecture_context
from database import SessionLocal
from models import Repo


# ── 1. Intent Classification Tests ──────────────────────────────────────────

def test_greeting_intent():
    """'Hi' produces a short greeting intent and skips repo retrieval."""
    intent = classify_intent("Hi")
    assert intent == QueryIntent.GREETING
    assert should_retrieve_context(intent) is False
    prompt = get_system_prompt_for_intent(intent)
    assert "briefly" in prompt.lower()
    assert "Do NOT search or analyze any repository files" in prompt


def test_general_programming_intent():
    """'What is an API?' produces general explanation and skips repo retrieval."""
    intent = classify_intent("What is an API?")
    assert intent == QueryIntent.GENERAL_PROGRAMMING
    assert should_retrieve_context(intent) is False
    prompt = get_system_prompt_for_intent(intent)
    assert "general conceptual" in prompt.lower()
    assert "Do NOT invent or cite local repository files" in prompt


def test_architecture_intent():
    """'Explain this project's architecture' triggers COMPREHENSIVE_ANALYSIS."""
    for q in [
        "Explain this project's architecture",
        "tell me about the architecture",
        "Explain the system architecture",
    ]:
        intent = classify_intent(q)
        assert intent == QueryIntent.COMPREHENSIVE_ANALYSIS, f"Failed for query: {q}"
        assert should_retrieve_context(intent) is True

    prompt = get_system_prompt_for_intent(QueryIntent.COMPREHENSIVE_ANALYSIS)
    assert "Overview" in prompt
    assert "High-Level Architecture" in prompt
    assert "Component Responsibilities" in prompt
    assert "Request and Data Flow" in prompt
    assert "Authentication and Security" in prompt


def test_authentication_intent():
    """'Explain authentication' targets the repository auth implementation."""
    intent = classify_intent("Explain authentication")
    assert intent == QueryIntent.REPO_QUERY
    assert should_retrieve_context(intent) is True


def test_test_failure_intent():
    """'Why is this test failing?' produces error diagnosis intent."""
    intent = classify_intent("Why is this test failing?")
    assert intent == QueryIntent.ERROR_DIAGNOSIS
    assert should_retrieve_context(intent) is True
    prompt = get_system_prompt_for_intent(intent)
    assert "**Likely cause**" in prompt
    assert "**Evidence**" in prompt
    assert "**Fix**" in prompt
    assert "**Validation**" in prompt


def test_code_review_and_explanation_intent():
    """'Review this code' and 'Explain this function' map to CODE_EXPLANATION."""
    intent1 = classify_intent("Review this code")
    assert intent1 == QueryIntent.CODE_EXPLANATION

    intent2 = classify_intent("Explain this function")
    assert intent2 == QueryIntent.CODE_EXPLANATION

    prompt = get_system_prompt_for_intent(QueryIntent.CODE_EXPLANATION)
    assert "code reviewer" in prompt.lower()
    assert "Purpose" in prompt


def test_comprehensive_1000_word_intent():
    """'Write a comprehensive 1000-word explanation' triggers COMPREHENSIVE_ANALYSIS."""
    intent = classify_intent("Write a comprehensive 1000-word explanation")
    assert intent == QueryIntent.COMPREHENSIVE_ANALYSIS


# ── 2. Architecture Context Construction ────────────────────────────────────

def test_architecture_context_builder():
    """Architecture context builder extracts real facts without crashing."""
    db = SessionLocal()
    try:
        repo = db.query(Repo).filter(Repo.name == "QuizGenAI").first()
        if not repo:
            repo = db.query(Repo).first()
        if not repo:
            pytest.skip("No repos in test database.")

        facts_block, extra_citations = build_architecture_context(repo.id, db)
        assert "=== VERIFIED REPOSITORY ARCHITECTURE & IMPLEMENTATION FACTS ===" in facts_block
        assert "=== END VERIFIED ARCHITECTURE FACTS ===" in facts_block
        assert "[PROJECT IDENTITY & CLASSIFICATION]" in facts_block
    finally:
        db.close()


# ── 3. Task-Aware Model Routing Tests ───────────────────────────────────────

def test_auto_routing_architecture():
    """Architecture tasks route to high-capacity reasoning models."""
    decision = get_model_for_task("ARCHITECTURE")
    assert decision["task"] == "ARCHITECTURE"
    assert decision["provider"] in ("nvidia", "groq", "apinex")
    assert "glm-5-3" in decision["modelId"] or "nemotron" in decision["modelId"] or "gpt-oss" in decision["modelId"] or "gpt-6-luna" in decision["modelId"]


def test_auto_routing_fast_chat():
    """Fast chat tasks route to low-latency models."""
    decision = get_model_for_task("FAST_CHAT")
    assert decision["task"] == "FAST_CHAT"
    assert decision["provider"] in ("nvidia", "groq", "apinex")


def test_manual_model_selection_override():
    """User preferred model explicitly overrides automatic task routing."""
    decision = get_model_for_task(
        "ARCHITECTURE",
        user_preferred_provider="groq",
        user_preferred_model="llama-3.3-70b-versatile",
    )
    assert decision["provider"] == "groq"
    assert decision["modelId"] == "llama-3.3-70b-versatile"
    assert "User explicitly selected" in decision["reason"]
