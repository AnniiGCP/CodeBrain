"""
voice/intent.py — Intent classification for voice commands.

Two-pass strategy:
  1. Fast keyword regex first pass (zero LLM cost, instant).
  2. If ambiguous, fall back to a single small Groq LLM call for disambiguation.

Supported intents (maps to frontend routing):
  - ask_question      → routes to ChatPanel / streamAsk
  - explain_symbol    → routes to FixPanel explain flow
  - generate_fix      → routes to FixPanel fix flow
  - generate_docs     → routes to docgen flow

Returns: IntentResult dataclass with (intent, target, confidence, raw_text).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from groq import Groq

# ── Keyword patterns ──────────────────────────────────────────────────────────

_EXPLAIN_PATTERNS = [
    r"\bexplain\b",
    r"\bdescribe\b",
    r"\bwhat(?:'s|\s+is)\s+(?:the\s+)?(?:error|bug|issue|problem|failure)\b",
    r"\bwhat\s+(?:does|is)\b",
    r"\bhow\s+does\b",
    r"\bwhy\s+(?:is|does)\b",
    r"\bdiagnose\b",
    r"\bwalk\s+me\s+through\b",
    r"\btell\s+me\s+about\b",
]

_FIX_PATTERNS = [
    r"\bfix\b",
    r"\brepair\b",
    r"\bdebug\b",
    r"\bpatch\b",
    r"\bcorrect\b",
    r"\bresolve\b",
]

_DOCS_PATTERNS = [
    r"\bdocument\b",
    r"\bgenerate\s+docs?\b",
    r"\bcreate\s+docs?\b",
    r"\badd\s+docstring\b",
    r"\bwrite\s+docs?\b",
    r"\bdocumentation\b",
]

# Compiled
_RE_EXPLAIN = re.compile("|".join(_EXPLAIN_PATTERNS), re.IGNORECASE)
_RE_FIX = re.compile("|".join(_FIX_PATTERNS), re.IGNORECASE)
_RE_DOCS = re.compile("|".join(_DOCS_PATTERNS), re.IGNORECASE)

# ── Target extraction heuristic ───────────────────────────────────────────────

_FILE_PATTERN = re.compile(
    r"\b([A-Za-z0-9_./\\-]+\.(?:py|js|ts|tsx|jsx|json|html|css|java|go|rs|cpp|c|h))\b",
    re.IGNORECASE,
)

_TARGET_PATTERN = re.compile(
    r"""
    (?:
        (?:in|for|of|on|to)\s+(?:the\s+)?
        (?:function|method|class|module|component|file|handler|route|endpoint|service|bug|error|issue)?\s*
        ([A-Za-z_][A-Za-z0-9_]*)
    ) |
    (?:
        (?:the\s+)?
        ([A-Za-z_][A-Za-z0-9_]*)
        \s+
        (?:function|method|class|module|component|file|handler|route|endpoint|service)
    ) |
    (?:
        (?:function|method|class|module|component|file|handler|route|endpoint|service)
        \s+
        ([A-Za-z_][A-Za-z0-9_]*)
    ) |
    (?:
        `([^`]+)`
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _extract_target(text: str) -> str:
    """Pull the most likely symbol / module / file name from the transcribed text."""
    # 1. File name match (e.g. auth.py, math_ops.py)
    fm = _FILE_PATTERN.search(text)
    if fm:
        return fm.group(1).strip()

    # 2. Identifier pattern
    m = _TARGET_PATTERN.search(text)
    if m:
        for g in m.groups():
            if g is not None and g.lower() not in ("the", "in", "for", "bug", "error", "issue", "fix", "explain"):
                return g.strip()

    # 3. Quoted phrase
    quoted = re.search(r'"([^"]+)"|\'([^\']+)\'', text)
    if quoted:
        return next(g for g in quoted.groups() if g is not None).strip()

    # 4. Fallback: stripped text
    return text.strip()


# ── Intent result ─────────────────────────────────────────────────────────────

@dataclass
class IntentResult:
    intent: str          # one of: ask_question | explain_symbol | generate_fix | generate_docs
    target: str          # extracted symbol / module name (may equal raw text for ask_question)
    confidence: float    # 0.0–1.0
    raw_text: str        # original transcribed text


# ── Public API ────────────────────────────────────────────────────────────────

def classify_intent(text: str, use_llm_fallback: bool = True) -> IntentResult:
    """
    Classify the transcribed text into one of the four intents.

    Args:
        text:             Transcribed voice command.
        use_llm_fallback: If True and keyword pass is ambiguous, call Groq LLM.

    Returns:
        IntentResult with intent, target, confidence, raw_text.
    """
    text_clean = text.strip()

    has_explain = bool(_RE_EXPLAIN.search(text_clean))
    has_fix = bool(_RE_FIX.search(text_clean))
    has_docs = bool(_RE_DOCS.search(text_clean))

    # Unambiguous keyword hits
    hits = sum([has_explain, has_fix, has_docs])

    if hits == 1:
        if has_explain:
            return IntentResult("explain_symbol", _extract_target(text_clean), 0.92, text_clean)
        if has_fix:
            return IntentResult("generate_fix", _extract_target(text_clean), 0.92, text_clean)
        if has_docs:
            return IntentResult("generate_docs", _extract_target(text_clean), 0.92, text_clean)

    # Multiple hits or zero hits — ask or ambiguous
    if hits == 0:
        # Probably a plain question
        return IntentResult("ask_question", text_clean, 0.80, text_clean)

    # Ambiguous: try LLM fallback
    if use_llm_fallback:
        try:
            return _llm_classify(text_clean)
        except Exception:
            pass  # degrade gracefully

    # Tie-break: explain > fix > docs > ask
    if has_explain:
        return IntentResult("explain_symbol", _extract_target(text_clean), 0.55, text_clean)
    if has_fix:
        return IntentResult("generate_fix", _extract_target(text_clean), 0.55, text_clean)
    return IntentResult("generate_docs", _extract_target(text_clean), 0.55, text_clean)


# ── LLM fallback classifier ───────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an intent classifier for a voice-controlled code assistant.
Classify the user's voice command into EXACTLY ONE of these intents:
  - ask_question      (general question about code / architecture)
  - explain_symbol    (explain a specific function, class, or module)
  - generate_fix      (fix / repair / debug a specific function or bug)
  - generate_docs     (generate documentation / docstrings for a symbol)

Also extract the primary target (function name, class name, or module name) the user is referring to.
If no specific target is mentioned, set target to the full command text.

Respond with ONLY a JSON object like:
{"intent": "explain_symbol", "target": "authentication module", "confidence": 0.95}
"""


def _llm_classify(text: str) -> IntentResult:
    from ai.router import route_chat

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]

    try:
        raw = route_chat(
            messages=messages,
            task_type="simple",
            temperature=0.0,
            max_tokens=80,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("Intent classification failed via router: %s", exc)
        return IntentResult(intent="ask_question", target=text, confidence=0.75, raw_text=text)

    try:
        data = json.loads(raw)
    except Exception:
        data = {}

    intent = data.get("intent", "ask_question")
    target = data.get("target", text)
    confidence = float(data.get("confidence", 0.75))

    return IntentResult(intent=intent, target=target, confidence=confidence, raw_text=text)
