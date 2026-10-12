"""
docgen/exporter.py
------------------
Bulk export: generate docs for all symbols in a repo and write them
to a /docs folder mirroring the source tree, plus a top-level README.md.

Public API
----------
export_repo_docs(repo_id, db) -> ExportResult
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"

# How many Groq calls per second we allow (free tier: ~30 RPM)
_CALL_DELAY_S = 2.5


@dataclass
class DocFile:
    relative_path: str   # e.g. "src/auth.py.md"
    content: str


@dataclass
class ExportResult:
    repo_id: str
    repo_name: str
    readme_path: str          # relative path of the README
    doc_files: list[DocFile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_symbols: int = 0
    documented_symbols: int = 0


def export_repo_docs(repo_id: str, db) -> ExportResult:
    """
    1. Generate README.md via generate_repo_readme().
    2. For each RepoFile that has symbols, generate docs for all symbols
       and write a mirrored .md file under /storage/{repo_id}/docs/.
    3. Return an ExportResult with paths and error list.
    """
    from models import Repo, RepoFile, Symbol
    from docgen.readme_gen import generate_repo_readme
    from docgen.symbol_doc import generate_symbol_doc

    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if not repo:
        raise ValueError(f"Repo {repo_id!r} not found")

    result = ExportResult(repo_id=repo_id, repo_name=repo.name, readme_path="README.md")

    docs_root = STORAGE_ROOT / repo_id / "docs"
    docs_root.mkdir(parents=True, exist_ok=True)

    # ── 1. README ──────────────────────────────────────────────────────────────
    logger.info("Generating README for repo %s", repo_id)
    try:
        readme_md = generate_repo_readme(repo_id, db)
        readme_path = docs_root / "README.md"
        readme_path.write_text(readme_md, encoding="utf-8")
        result.doc_files.append(DocFile("README.md", readme_md))
        time.sleep(_CALL_DELAY_S)
    except Exception as exc:
        logger.exception("Failed to generate README for %s", repo_id)
        result.errors.append(f"README: {exc}")

    # ── 2. Per-file symbol docs ────────────────────────────────────────────────
    files = db.query(RepoFile).filter(RepoFile.repo_id == repo_id).order_by(RepoFile.path).all()

    for rf in files:
        symbols = db.query(Symbol).filter(Symbol.file_id == rf.id).all()
        if not symbols:
            continue

        result.total_symbols += len(symbols)
        file_doc_sections: list[str] = [
            f"# `{rf.path}`\n\n"
            f"**Language:** {rf.language or 'unknown'}  \n"
            f"**Symbols:** {len(symbols)}\n\n---\n"
        ]

        for sym in symbols:
            try:
                docstring = generate_symbol_doc(sym.id, db)
                result.documented_symbols += 1
                file_doc_sections.append(
                    f"\n## `{sym.name}` ({sym.symbol_type})\n\n"
                    f"```{rf.language or ''}\n{docstring}\n```\n\n"
                    f"**Source:**\n```{rf.language or ''}\n{sym.source_code}\n```\n"
                )
                time.sleep(_CALL_DELAY_S)   # rate-limit
            except Exception as exc:
                logger.warning("Failed to doc symbol %d (%s): %s", sym.id, sym.name, exc)
                result.errors.append(f"{rf.path}::{sym.name}: {exc}")

        if len(file_doc_sections) > 1:  # has at least one symbol doc
            # Mirror path: src/auth.py  →  docs/src/auth.py.md
            out_rel = Path(rf.path).with_suffix(Path(rf.path).suffix + ".md")
            out_path = docs_root / out_rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            content = "\n".join(file_doc_sections)
            out_path.write_text(content, encoding="utf-8")
            result.doc_files.append(DocFile(str(out_rel).replace("\\", "/"), content))

    logger.info(
        "Export complete for %s: %d/%d symbols documented, %d errors",
        repo_id, result.documented_symbols, result.total_symbols, len(result.errors),
    )
    return result
