"""
docgen/symbol_doc.py
--------------------
Generate a docstring / JSDoc / language-appropriate comment for a single symbol.

Public API
----------
generate_symbol_doc(symbol_id, db) -> str   (just the docstring text)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Docstring templates per language ─────────────────────────────────────────

_LANG_FORMAT: dict[str, str] = {
    "python":     "Google-style Python docstring (triple double-quotes)",
    "javascript": "JSDoc comment block (/** ... */)",
    "typescript": "JSDoc comment block (/** ... */)",
    "java":       "Javadoc comment block (/** ... */)",
    "csharp":     "XML documentation comment (/// <summary>...)",
    "kotlin":     "KDoc comment block (/** ... */)",
    "go":         "Go doc comment (// FunctionName ...)",
    "rust":       "Rust doc comment (/// ...)",
    "cpp":        "Doxygen comment block (/** @brief ... */)",
    "c":          "Doxygen comment block (/** @brief ... */)",
    "ruby":       "YARD doc comment (# @param ...)",
    "php":        "PHPDoc comment block (/** ... */)",
}

_SYSTEM = """\
You are a senior software engineer writing precise, concise code documentation.

Rules:
- Write ONLY the docstring/comment block — no surrounding code, no explanations.
- Use the exact format requested for the target language.
- Describe what the function/class does, its parameters, return value, and any
  notable side effects or exceptions.
- Do NOT describe implementation details line by line.
- Do NOT invent behaviour that is not visible in the source code.
- Keep it under 20 lines unless the symbol is genuinely complex.
"""

_USER_TEMPLATE = """\
Language: {language}
Format: {doc_format}
Symbol type: {symbol_type}
Symbol name: {name}
File: {file_path}

{caller_context}

Source code:
```{language}
{source_code}
```

Write the documentation comment for `{name}`. Output ONLY the comment block.
"""

_MAX_CALLER_LINES = 30


def _build_caller_context(db, symbol: "Symbol", repo_id: str) -> str:  # noqa: F821
    """
    Find other symbols in the same repo that textually reference this symbol's name,
    providing shallow caller/callee context.
    """
    from models import Symbol as Sym

    name = symbol.name
    # Simple text search — good enough for context; not a full call-graph
    referencing = (
        db.query(Sym)
        .filter(
            Sym.repo_id == repo_id,
            Sym.id != symbol.id,
            Sym.source_code.contains(name),
        )
        .limit(5)
        .all()
    )

    if not referencing:
        return ""

    lines: list[str] = ["Related symbols that reference this symbol:"]
    for ref in referencing:
        snippet = "\n".join(ref.source_code.splitlines()[:8])
        lines.append(f"\n[{ref.symbol_type}] `{ref.name}`:\n```\n{snippet}\n```")

    full = "\n".join(lines)
    # Cap total length
    all_lines = full.splitlines()
    if len(all_lines) > _MAX_CALLER_LINES:
        full = "\n".join(all_lines[:_MAX_CALLER_LINES]) + "\n..."
    return full


# ── Public function ────────────────────────────────────────────────────────────

def generate_symbol_doc(symbol_id: int, db) -> str:
    """
    Generate a language-appropriate docstring for a single Symbol.
    Returns just the docstring text (the comment block), not the whole function.
    """
    from models import Symbol, RepoFile
    from docgen.groq_client import call_groq

    sym = db.query(Symbol).filter(Symbol.id == symbol_id).first()
    if not sym:
        raise ValueError(f"Symbol {symbol_id} not found")

    rf = db.query(RepoFile).filter(RepoFile.id == sym.file_id).first()
    language = (rf.language or "unknown") if rf else "unknown"
    file_path = rf.path if rf else "unknown"

    doc_format = _LANG_FORMAT.get(language, "appropriate comment block for the language")
    caller_ctx = _build_caller_context(db, sym, sym.repo_id)

    user_msg = _USER_TEMPLATE.format(
        language=language,
        doc_format=doc_format,
        symbol_type=sym.symbol_type,
        name=sym.name,
        file_path=file_path,
        caller_context=caller_ctx,
        source_code=sym.source_code,
    )

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    logger.info(
        "Generating doc for symbol %d (%s `%s`) in %s",
        symbol_id, sym.symbol_type, sym.name, file_path,
    )
    return call_groq(messages, max_tokens=512, temperature=0.1)
