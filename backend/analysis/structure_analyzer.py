"""
analysis/structure_analyzer.py
-------------------------------
Analyse the high-level structure of a repository:
  - Language distribution
  - Top-level module/package breakdown
  - Entry-point candidates
  - Dependency files detected
  - Symbol counts per language

Returns a JSON-serialisable dict stored in the Repo.pipeline_meta column.
Intentionally lightweight — zero LLM calls, pure static analysis.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"

# Files that mark a dependency manifest
DEPENDENCY_FILES = {
    "requirements.txt", "Pipfile", "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Gemfile", "Gemfile.lock",
    "go.mod", "go.sum",
    "Cargo.toml", "Cargo.lock",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "composer.json", "composer.lock",
    "*.csproj", "*.sln",
}

# Common entry-point filenames
ENTRY_POINTS = {
    "main.py", "app.py", "run.py", "server.py", "wsgi.py", "asgi.py",
    "index.js", "index.ts", "app.js", "app.ts", "server.js", "server.ts",
    "main.go", "main.rs", "Main.java", "Program.cs",
    "index.html",
}


def analyze_structure(repo_id: str, db: "Session") -> dict:
    """
    Perform static structure analysis on an ingested repository.

    Returns a dict with:
      - language_dist: {lang: file_count}
      - top_dirs: [str]           top-level directories
      - entry_points: [str]       likely entry-point files
      - dep_files: [str]          detected dependency manifests
      - symbol_counts: {lang: count}
      - total_files: int
      - total_symbols: int
    """
    from models import Repo, RepoFile, Symbol  # local import avoids circular deps

    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if repo is None:
        raise ValueError(f"Repo {repo_id!r} not found")

    files = db.query(RepoFile).filter(RepoFile.repo_id == repo_id).all()
    if not files:
        logger.warning("analyze_structure: no files for repo %s", repo_id)
        return {}

    lang_counter: Counter[str] = Counter()
    top_dirs: set[str] = set()
    found_entry_points: list[str] = []
    found_dep_files: list[str] = []
    symbol_counts: defaultdict[str, int] = defaultdict(int)

    for rf in files:
        lang = rf.language or "unknown"
        lang_counter[lang] += 1

        parts = rf.path.split("/")
        if len(parts) > 1:
            top_dirs.add(parts[0])

        filename = parts[-1]
        if filename in ENTRY_POINTS:
            found_entry_points.append(rf.path)

        if filename in DEPENDENCY_FILES:
            found_dep_files.append(rf.path)
        # pattern-based (e.g. *.csproj)
        for pat in DEPENDENCY_FILES:
            if pat.startswith("*") and filename.endswith(pat[1:]):
                found_dep_files.append(rf.path)
                break

    # Symbol counts per language
    all_symbols = db.query(Symbol).filter(Symbol.repo_id == repo_id).all()
    for sym in all_symbols:
        rf_row = db.query(RepoFile).filter(RepoFile.id == sym.file_id).first()
        lang = rf_row.language if rf_row else "unknown"
        symbol_counts[lang or "unknown"] += 1

    result = {
        "language_dist": dict(lang_counter.most_common()),
        "top_dirs": sorted(top_dirs),
        "entry_points": sorted(set(found_entry_points)),
        "dep_files": sorted(set(found_dep_files)),
        "symbol_counts": dict(symbol_counts),
        "total_files": len(files),
        "total_symbols": len(all_symbols),
    }

    logger.info("Structure analysis done for %s: %s files, %s symbols",
                repo_id, result["total_files"], result["total_symbols"])
    return result
