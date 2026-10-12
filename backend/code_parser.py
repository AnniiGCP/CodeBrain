"""
Code symbol extractor.

Extracts functions, classes, and methods from source files.
Uses regex-based heuristics per language — lightweight, zero native-lib deps.
Falls back to a single "module" symbol (the whole file) for unknown languages.

Returned symbol dict shape:
    {
        "type": "function" | "class" | "method" | "module",
        "name": str,
        "source_code": str,   # the full extracted block
    }
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Generator


# ──────────────────────────────────────────────────────────────────
# Generic helpers
# ──────────────────────────────────────────────────────────────────

def _read_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _chunk_by_blank_lines(text: str, name_hint: str) -> list[dict]:
    """Last-resort: split on double blank lines, each chunk = one 'module' symbol."""
    chunks = re.split(r"\n{2,}", text.strip())
    out = []
    for i, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if chunk:
            out.append({"type": "module", "name": f"{name_hint}_chunk_{i}", "source_code": chunk})
    return out or [{"type": "module", "name": name_hint, "source_code": text}]


# ──────────────────────────────────────────────────────────────────
# Python extractor
# ──────────────────────────────────────────────────────────────────

_PY_DEF = re.compile(
    r"^(?P<indent>[ \t]*)(?P<kw>class|def|async def)\s+(?P<name>\w+)",
    re.MULTILINE,
)


def _extract_python(text: str) -> list[dict]:
    lines = text.splitlines(keepends=True)
    symbols: list[dict] = []

    matches = list(_PY_DEF.finditer(text))
    for idx, m in enumerate(matches):
        indent = len(m.group("indent").expandtabs(4))
        kw = m.group("kw").replace("async ", "")  # normalise "async def" → "def"
        name = m.group("name")
        start_line = text[: m.start()].count("\n")

        # Collect all lines until next same-or-outer-indent def/class
        end_line = len(lines)
        if idx + 1 < len(matches):
            next_m = matches[idx + 1]
            next_indent = len(next_m.group("indent").expandtabs(4))
            if next_indent <= indent:
                end_line = text[: next_m.start()].count("\n")

        snippet = "".join(lines[start_line:end_line]).rstrip()
        sym_type = "class" if kw == "class" else ("method" if indent > 0 else "function")
        symbols.append({"type": sym_type, "name": name, "source_code": snippet})

    return symbols or [{"type": "module", "name": "module", "source_code": text}]


# ──────────────────────────────────────────────────────────────────
# JavaScript / TypeScript extractor
# ──────────────────────────────────────────────────────────────────

_JS_SYMBOL = re.compile(
    r"""
    (?:^|\n)
    [ \t]*
    (?:export\s+)?
    (?:
        (?:async\s+)?function\s+(?P<fn>\w+)   # function foo
        |class\s+(?P<cls>\w+)                 # class Foo
        |(?:const|let|var)\s+(?P<arrow>\w+)\s*=\s*(?:async\s*)?\(  # const foo = (
    )
    """,
    re.VERBOSE,
)

_JS_BRACE = re.compile(r"[{}]")


def _find_block_end(text: str, brace_pos: int) -> int:
    """Walk forward from first '{' and find its matching '}'."""
    depth = 0
    for m in _JS_BRACE.finditer(text, brace_pos):
        if m.group() == "{":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.end()
    return len(text)


def _extract_js(text: str) -> list[dict]:
    symbols: list[dict] = []
    for m in _JS_SYMBOL.finditer(text):
        name = m.group("fn") or m.group("cls") or m.group("arrow")
        sym_type = "class" if m.group("cls") else "function"
        # Find opening brace after match
        brace_idx = text.find("{", m.end())
        if brace_idx == -1:
            continue
        end = _find_block_end(text, brace_idx)
        snippet = text[m.start() :end].strip()
        symbols.append({"type": sym_type, "name": name, "source_code": snippet})
    return symbols or [{"type": "module", "name": "module", "source_code": text}]


# ──────────────────────────────────────────────────────────────────
# Java / C# extractor (brace-based)
# ──────────────────────────────────────────────────────────────────

_JAVA_SYMBOL = re.compile(
    r"""
    (?:^|\n)[ \t]*
    (?:(?:public|private|protected|static|final|abstract|override|async|virtual)\s+)*
    (?:class|interface|enum|record|void|[A-Z]\w*(?:<[^>]*>)?|\w+)\s+
    (?P<name>\w+)\s*
    (?:\([^)]*\)\s*)?       # optional param list
    (?:throws\s+\w+\s*)?    # optional throws
    \{
    """,
    re.VERBOSE,
)


def _extract_java(text: str) -> list[dict]:
    symbols: list[dict] = []
    for m in _JAVA_SYMBOL.finditer(text):
        name = m.group("name")
        brace_idx = text.rfind("{", m.start(), m.end())
        if brace_idx == -1:
            continue
        end = _find_block_end(text, brace_idx)
        snippet = text[m.start() : end].strip()
        # Rough heuristic: if name starts with capital it's likely a class
        sym_type = "class" if name[0].isupper() else "function"
        symbols.append({"type": sym_type, "name": name, "source_code": snippet})
    return symbols or [{"type": "module", "name": "module", "source_code": text}]


# ──────────────────────────────────────────────────────────────────
# C / C++ extractor
# ──────────────────────────────────────────────────────────────────

_C_FUNC = re.compile(
    r"""
    (?:^|\n)
    (?![ \t]*\#)                         # skip preprocessor
    [ \t]*
    (?:(?:static|inline|extern|const|virtual|override)\s+)*
    [\w:*&<>\[\]]+\s+                   # return type
    \**\s*
    (?P<name>[\w:]+)\s*                 # function name (allow :: for C++)
    \([^;{]*\)\s*                       # params
    (?:const\s*)?
    \{
    """,
    re.VERBOSE,
)


def _extract_c(text: str) -> list[dict]:
    symbols: list[dict] = []
    for m in _C_FUNC.finditer(text):
        name = m.group("name")
        if not name or name in ("if", "for", "while", "switch", "else"):
            continue
        brace_idx = text.rfind("{", m.start(), m.end())
        if brace_idx == -1:
            continue
        end = _find_block_end(text, brace_idx)
        snippet = text[m.start() : end].strip()
        symbols.append({"type": "function", "name": name, "source_code": snippet})
    return symbols or [{"type": "module", "name": "module", "source_code": text}]


# ──────────────────────────────────────────────────────────────────
# Go extractor
# ──────────────────────────────────────────────────────────────────

_GO_FUNC = re.compile(r"\nfunc\s+(?:\([^)]+\)\s+)?(?P<name>\w+)\s*\(")


def _extract_go(text: str) -> list[dict]:
    symbols: list[dict] = []
    for m in _GO_FUNC.finditer(text):
        name = m.group("name")
        brace_idx = text.find("{", m.end())
        if brace_idx == -1:
            continue
        end = _find_block_end(text, brace_idx)
        snippet = text[m.start() : end].strip()
        symbols.append({"type": "function", "name": name, "source_code": snippet})
    return symbols or [{"type": "module", "name": "module", "source_code": text}]


# ──────────────────────────────────────────────────────────────────
# Rust extractor
# ──────────────────────────────────────────────────────────────────

_RS_ITEM = re.compile(
    r"\n(?:pub\s+)?(?:async\s+)?(?P<kw>fn|struct|enum|impl|trait)\s+(?P<name>\w+)"
)


def _extract_rust(text: str) -> list[dict]:
    symbols: list[dict] = []
    for m in _RS_ITEM.finditer(text):
        kw = m.group("kw")
        name = m.group("name")
        sym_type = "class" if kw in ("struct", "enum", "impl", "trait") else "function"
        brace_idx = text.find("{", m.end())
        if brace_idx == -1:
            continue
        end = _find_block_end(text, brace_idx)
        snippet = text[m.start() : end].strip()
        symbols.append({"type": sym_type, "name": name, "source_code": snippet})
    return symbols or [{"type": "module", "name": "module", "source_code": text}]


# ──────────────────────────────────────────────────────────────────
# Dispatch table
# ──────────────────────────────────────────────────────────────────

_EXTRACTORS: dict[str, Any] = {  # type: ignore[name-defined]
    "python": _extract_python,
    "javascript": _extract_js,
    "typescript": _extract_js,
    "vue": _extract_js,
    "svelte": _extract_js,
    "java": _extract_java,
    "csharp": _extract_java,
    "kotlin": _extract_java,
    "scala": _extract_java,
    "c": _extract_c,
    "cpp": _extract_c,
    "go": _extract_go,
    "rust": _extract_rust,
}


def extract_symbols(path: Path, language: str | None) -> list[dict]:
    """
    Parse a source file and return a list of symbol dicts.
    Falls back to whole-file chunking for unsupported languages.
    """
    text = _read_safe(path)
    if not text or not text.strip():
        return []

    extractor = _EXTRACTORS.get(language or "")
    if extractor:
        try:
            return extractor(text) or [{"type": "module", "name": path.stem, "source_code": text}]
        except Exception:
            pass

    # Generic fallback — split on blank lines
    return _chunk_by_blank_lines(text, path.stem)
