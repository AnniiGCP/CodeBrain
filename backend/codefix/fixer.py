"""
codefix/fixer.py
----------------
generate_fix(symbol_id, issue_description, db) -> str

Calls NVIDIA NIM CodeLlama 70B (OpenAI-compatible endpoint) to produce a
unified diff fixing the described issue in the given symbol's source.

Falls back to Groq LLaMA 3 70B if NVIDIA_NIM_API_KEY is absent.

The prompt instructs the LLM to return ONLY a valid git-style unified diff
(--- a/... / +++ b/... / @@ ... @@) with no surrounding prose.
"""
from __future__ import annotations

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

# ── NIM config ────────────────────────────────────────────────────────────────
_NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_NIM_MODEL = "meta/codellama-70b-instruct"
_NIM_FALLBACK_MODEL = "meta/llama3-70b-instruct"

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are an expert software engineer producing minimal, correct code fixes.

STRICT OUTPUT RULES — violating any rule makes your answer useless:
1. Output ONLY a unified diff in git format.
2. Start with: --- a/<file_path>
3. Then:       +++ b/<file_path>
4. Then one or more hunks starting with @@ -L,S +L,S @@
5. Context lines (unchanged) start with a space.
6. Removed lines start with -.
7. Added lines start with +.
8. DO NOT output any explanation, prose, markdown code fences, or commentary.
9. The diff must be syntactically valid and apply cleanly with `patch -p1`.
"""

_USER_TEMPLATE = """\
File: {file_path}
Language: {language}

Issue to fix:
{issue_description}

Current source code of `{name}`:
```
{source_code}
```

{context_block}

Produce the unified diff to fix the issue. Nothing else.
"""

_MAX_CTX_LINES = 20


def _fetch_context(symbol, db) -> str:
    """Get a few related symbols for additional context."""
    try:
        from vectorstore.index import search as faiss_search
        results = faiss_search(symbol.repo_id, symbol.name, top_k=3, db=db)
        results = [r for r in results if r["symbol_id"] != symbol.id][:3]
    except Exception:
        return ""

    if not results:
        return ""

    lines = ["Additional context from the codebase:"]
    for r in results:
        snippet = "\n".join(r["source_code"].splitlines()[:_MAX_CTX_LINES])
        lines.append(f"\n`{r['name']}` ({r['file_path']}):\n```\n{snippet}\n```")
    return "\n".join(lines)


# ── NIM call ──────────────────────────────────────────────────────────────────

def _call_nim(messages: list[dict]) -> str | None:
    """Try NVIDIA NIM. Returns None if key is absent."""
    api_key = os.environ.get("NVIDIA_NIM_API_KEY", "").strip()
    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for model in (_NIM_MODEL, _NIM_FALLBACK_MODEL):
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": 0.05,   # very low — we want deterministic diff
            "max_tokens": 2048,
        }
        try:
            resp = httpx.post(_NIM_URL, headers=headers, json=payload, timeout=120.0)
            if resp.status_code in (404, 422) and model == _NIM_MODEL:
                logger.warning("NIM model %s unavailable, trying %s", _NIM_MODEL, _NIM_FALLBACK_MODEL)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            logger.warning("NIM request timed out")
            return None
        except Exception as exc:
            logger.warning("NIM call failed (%s): %s", model, exc)
            if model == _NIM_FALLBACK_MODEL:
                return None

    return None


# ── Diff cleaner ──────────────────────────────────────────────────────────────

def _clean_diff(raw: str) -> str:
    """
    Strip any prose/markdown fences the LLM may have accidentally included,
    extracting only the unified diff block.
    """
    # Remove ```diff ... ``` fences
    raw = re.sub(r"```(?:diff)?\s*\n", "", raw)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)

    # Find the first line starting with '---'
    lines = raw.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("---")), None)
    if start is not None:
        return "\n".join(lines[start:]).strip()
    return raw.strip()


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_fix(
    symbol_id: int,
    issue_description: str,
    db,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """
    Generate a unified diff fixing the described issue in the given symbol.
    Uses centralized AI router with code/hard_reasoning task types.

    Returns:
        {
            "symbol_id": int,
            "file_path": str,
            "language": str,
            "diff": str,
            "model_used": str,
            "model_display_name": str,
            "provider": str,
        }
    """
    from models import Symbol, RepoFile
    from ai.router import route_chat, route_reasoning
    from ai.config import get_large_context_threshold
    from ai.registry import clean_display_name

    sym = db.query(Symbol).filter(Symbol.id == symbol_id).first()
    if not sym:
        raise ValueError(f"Symbol {symbol_id} not found")

    rf = db.query(RepoFile).filter(RepoFile.id == sym.file_id).first()
    language = (rf.language or "unknown") if rf else "unknown"
    file_path = rf.path if rf else "unknown"

    context_block = _fetch_context(sym, db)

    user_msg = _USER_TEMPLATE.format(
        file_path=file_path,
        language=language,
        issue_description=issue_description,
        name=sym.name,
        source_code=sym.source_code,
        context_block=context_block,
    )
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    threshold = get_large_context_threshold()
    total_len = len(user_msg)

    from ai.issue_fix_router import route_issue_fix

    fix_res = route_issue_fix(
        messages=messages,
        expected_file_path=file_path,
        source_code=sym.source_code,
        user_preferred_provider=provider,
        user_preferred_model=model,
        temperature=0.05,
        max_tokens=2048,
    )

    logger.info(
        "Generated fix for symbol %d via %s (%s) (%d diff lines, fallback=%s)",
        symbol_id, fix_res.provider, fix_res.model_display_name, fix_res.diff.count("\n"), fix_res.fallback_used,
    )

    return {
        "symbol_id": symbol_id,
        "file_path": file_path,
        "language": language,
        "diff": fix_res.diff,
        "model_used": fix_res.model,
        "model_display_name": fix_res.model_display_name,
        "provider": fix_res.provider,
        "fallback_used": fix_res.fallback_used,
        "fix_attribution": fix_res.fix_attribution,
        "attempts": fix_res.attempts,
    }

