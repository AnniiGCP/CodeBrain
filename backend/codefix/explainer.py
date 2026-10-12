"""
codefix/explainer.py
--------------------
explain_symbol(symbol_id, db) -> str

Uses Groq LLaMA 3 70B plus vector-retrieved related context to produce
a clear natural-language explanation of what a code symbol does.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a senior engineer explaining code to a junior developer.
Rules:
- Explain what the symbol does, why it exists, and any important edge cases.
- Reference specific lines/logic but do NOT just repeat the code line-by-line.
- Include: purpose, parameters (if any), return value, side effects, error cases.
- Keep it under 350 words. Use plain English — avoid jargon unless necessary.
- Use markdown formatting: bold key terms, use bullet lists for parameters.
"""

_USER_TEMPLATE = """\
## Symbol to explain
Type: {symbol_type}
Name: `{name}`
File: `{file_path}` (language: {language})

### Source code
```{language}
{source_code}
```

{related_context}

Explain what `{name}` does in plain English.
"""

_MAX_RELATED = 5
_MAX_RELATED_LINES = 15


def _fetch_related_context(symbol, db) -> str:
    """Pull up to _MAX_RELATED semantically close symbols via FAISS search."""
    try:
        from vectorstore.index import search as faiss_search
        results = faiss_search(
            symbol.repo_id,
            f"{symbol.symbol_type} {symbol.name}\n{symbol.source_code[:300]}",
            top_k=_MAX_RELATED + 1,  # +1 because the symbol itself may appear
            db=db,
        )
        # Remove the symbol itself
        results = [r for r in results if r["symbol_id"] != symbol.id][: _MAX_RELATED]
    except Exception:
        return ""  # no FAISS index yet — skip gracefully

    if not results:
        return ""

    lines = ["### Related symbols (for context)"]
    for r in results:
        snippet = "\n".join(r["source_code"].splitlines()[:_MAX_RELATED_LINES])
        lines.append(
            f"\n[{r['symbol_type']}] `{r['name']}` in `{r['file_path']}`:\n"
            f"```{r.get('language') or ''}\n{snippet}\n```"
        )
    return "\n".join(lines)


def explain_symbol(symbol_id: int, db) -> str:
    """Return a natural-language explanation of the symbol using centralized AI router."""
    from models import Symbol, RepoFile
    from ai.router import route_chat

    sym = db.query(Symbol).filter(Symbol.id == symbol_id).first()
    if not sym:
        raise ValueError(f"Symbol {symbol_id} not found")

    rf = db.query(RepoFile).filter(RepoFile.id == sym.file_id).first()
    language = (rf.language or "unknown") if rf else "unknown"
    file_path = rf.path if rf else "unknown"

    related_ctx = _fetch_related_context(sym, db)

    user_msg = _USER_TEMPLATE.format(
        symbol_type=sym.symbol_type,
        name=sym.name,
        file_path=file_path,
        language=language,
        source_code=sym.source_code,
        related_context=related_ctx,
    )

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    logger.info("Explaining symbol %d (%s `%s`)", symbol_id, sym.symbol_type, sym.name)
    return route_chat(messages, task_type="chat", temperature=0.3, max_tokens=1024)
