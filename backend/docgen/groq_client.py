"""
docgen/groq_client.py
---------------------
Universal AI Synthesis Client for Repository Documentation.
Primary AI: NVIDIA NIM (configured with retry and controlled backoff)
Fallback AI: Groq (ultra-low latency fallback)
Applies strict secret redaction and prevents host platform leakage.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator

from ai.router import route_chat, route_reasoning, route_vision
from docgen.secret_redactor import redact_secrets

logger = logging.getLogger(__name__)

BANNED_LEAKAGE_TERMS = ["codebrain", "anniigcp", "major-project"]


def call_documentation_ai(
    messages: list[dict],
    max_tokens: int = 3500,
    temperature: float = 0.2,
    project_name: str = "",
) -> str:
    """
    Synchronous documentation AI call routed through centralized AI router.
    Primary AI: NVIDIA NIM.
    Fallback AI: Groq.
    Enforces anti-hallucination rules, secret redaction, and host-platform leakage protection.
    """
    raw_ai = route_reasoning(
        messages=messages,
        task_type="document",
        stream=False,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    clean_ai = redact_secrets(raw_ai).strip()

    # Anti-leakage sanity check: reject if AI outputs host-platform names not part of project_name
    lower_ai = clean_ai.lower()
    proj_lower = project_name.lower() if project_name else ""
    for term in BANNED_LEAKAGE_TERMS:
        if term in lower_ai and term not in proj_lower:
            logger.warning("AI output contained host platform leakage ('%s'). Flagging output.", term)
            raise ValueError(f"AI output contained prohibited platform term: {term}")

    return clean_ai


# Backward-compatible alias
call_groq = call_documentation_ai


async def stream_groq(
    messages: list[dict],
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> AsyncGenerator[str, None]:
    """
    Async streaming routed through the centralized router (chat task).
    """
    async for token in route_chat(
        messages=messages,
        task_type="chat",
        stream=True,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        yield token


async def stream_groq_vision(
    messages: list[dict],
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> AsyncGenerator[str, None]:
    """
    Async vision streaming routed through the centralized router (vision task).
    """
    async for token in route_vision(
        messages=messages,
        stream=True,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        yield token
