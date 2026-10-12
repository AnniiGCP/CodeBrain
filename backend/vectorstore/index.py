"""
vectorstore/index.py
--------------------
FAISS index management — build, persist, search, incremental update.

Index type: IndexIDMap wrapping IndexFlatIP
  - IndexFlatIP computes exact inner-product (= cosine similarity after L2-norm)
  - IndexIDMap lets us map arbitrary integer IDs (Symbol.id) to vectors,
    enabling targeted removal for incremental re-embedding.

Public API
----------
embed_repo(repo_id, db)   -> dict with stats
search(repo_id, query, top_k, db) -> list of result dicts
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from vectorstore.embedder import embed_texts, embed_query

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"


# ─────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────

def _index_path(repo_id: str) -> Path:
    return STORAGE_ROOT / repo_id / "faiss.index"


def _load_faiss_index(repo_id: str):
    """Load a persisted FAISS index or return None."""
    import faiss  # lazy import

    p = _index_path(repo_id)
    if not p.exists():
        return None
    try:
        return faiss.read_index(str(p))
    except Exception as exc:
        logger.warning("Could not load FAISS index for %s: %s", repo_id, exc)
        return None


def _make_new_index(dim: int):
    """Create a fresh IndexIDMap(IndexFlatIP) index."""
    import faiss

    flat = faiss.IndexFlatIP(dim)
    return faiss.IndexIDMap(flat)


def _save_index(index, repo_id: str) -> None:
    import faiss

    p = _index_path(repo_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(p))


def _symbol_text(sym) -> str:
    """Format the text that gets embedded for a Symbol row."""
    return f"{sym.symbol_type} {sym.name}\n{sym.source_code}"


# ─────────────────────────────────────────────────────────
# Embedding pipeline helpers
# ─────────────────────────────────────────────────────────

def _parse_and_store_symbols(db, repo_file, repo_id: str) -> list:
    """
    Parse a RepoFile, upsert Symbol rows, return new Symbol objects.
    Deletes existing symbols for this file first (full re-parse).
    """
    from models import Symbol
    from code_parser import extract_symbols

    # Resolve the on-disk path
    storage_dir = STORAGE_ROOT / repo_id
    # The stored path is relative to the repo root inside storage_dir
    # Try direct match, or scan for the actual root subfolder
    file_path = storage_dir / repo_file.path
    if not file_path.exists():
        # The zip may have been extracted into a sub-folder
        for child in storage_dir.iterdir():
            if child.is_dir():
                candidate = child / repo_file.path
                if candidate.exists():
                    file_path = candidate
                    break

    if not file_path.exists():
        logger.debug("File not found on disk: %s", repo_file.path)
        return []

    raw_symbols = extract_symbols(file_path, repo_file.language)

    # Delete old symbols for this file
    db.query(Symbol).filter(Symbol.file_id == repo_file.id).delete()

    new_symbols = []
    for s in raw_symbols:
        sym = Symbol(
            file_id=repo_file.id,
            repo_id=repo_id,
            symbol_type=s["type"],
            name=s["name"],
            source_code=s["source_code"],
            embedded_file_hash=None,  # mark as not yet embedded
        )
        db.add(sym)
        new_symbols.append(sym)

    db.flush()  # get auto-incremented IDs assigned
    return new_symbols


# ─────────────────────────────────────────────────────────
# Public: embed_repo
# ─────────────────────────────────────────────────────────

def embed_repo(repo_id: str, db) -> dict:
    """
    Build / incrementally update the FAISS index for repo_id.

    Incremental logic:
    1. Load existing index (if any).
    2. For each RepoFile:
       - If content_hash == symbol.embedded_file_hash for ALL its symbols → skip.
       - Otherwise: remove old FAISS IDs, re-parse symbols, re-embed, re-add.
    3. Persist updated index.
    """
    import faiss
    from models import Repo, RepoFile, Symbol

    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if not repo:
        raise ValueError(f"Repo {repo_id!r} not found")

    files = db.query(RepoFile).filter(RepoFile.repo_id == repo_id).all()
    if not files:
        raise ValueError("No files ingested for this repo yet. Run /repos/upload or /repos/github first.")

    # Determine embedding dimension from model
    from vectorstore.embedder import get_model, _get_dim
    model = get_model()
    dim = _get_dim(model)

    # Load or create index
    index = _load_faiss_index(repo_id) or _make_new_index(dim)

    stats = {"files_scanned": 0, "files_changed": 0, "symbols_added": 0, "symbols_removed": 0}

    pending_symbols: list[tuple[Symbol, str]] = []

    for repo_file in files:
        stats["files_scanned"] += 1

        # Check if any symbol for this file has a stale hash (or none at all)
        existing_syms = db.query(Symbol).filter(Symbol.file_id == repo_file.id).all()

        needs_update = (
            not existing_syms
            or any(s.embedded_file_hash != repo_file.content_hash for s in existing_syms)
        )

        if not needs_update:
            continue

        stats["files_changed"] += 1

        # 1) Remove stale FAISS vectors
        if existing_syms:
            old_ids = np.array([s.id for s in existing_syms], dtype=np.int64)
            try:
                index.remove_ids(old_ids)
                stats["symbols_removed"] += len(old_ids)
            except Exception as exc:
                logger.warning("remove_ids failed for file %s: %s", repo_file.path, exc)

        # 2) Re-parse & store fresh Symbol rows
        new_symbols = _parse_and_store_symbols(db, repo_file, repo_id)
        for s in new_symbols:
            pending_symbols.append((s, repo_file.content_hash))

    # 3) Batch embed all pending symbols
    if pending_symbols:
        texts = [_symbol_text(s) for s, _ in pending_symbols]
        try:
            vecs = embed_texts(texts)  # shape (N, dim), L2-normalised
        except Exception as exc:
            logger.error("Embedding failed for repo %s: %s", repo_id, exc)
            db.rollback()
            raise

        ids = np.array([s.id for s, _ in pending_symbols], dtype=np.int64)
        index.add_with_ids(vecs, ids)
        stats["symbols_added"] += len(pending_symbols)

        # 4) Mark symbols as embedded with current hash
        for sym, c_hash in pending_symbols:
            sym.embedded_file_hash = c_hash

    db.commit()
    _save_index(index, repo_id)

    logger.info("embed_repo done for %s: %s", repo_id, stats)
    return stats


# ─────────────────────────────────────────────────────────
# Public: search
# ─────────────────────────────────────────────────────────
# Public: search
# ─────────────────────────────────────────────────────────

def _find_symbol_line(file_path: Path, sym_name: str) -> int:
    """Find line number (1-indexed) where symbol is declared in file."""
    if not file_path.exists():
        return 1
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        for line_idx, line in enumerate(content.splitlines(), start=1):
            if sym_name in line and any(kw in line for kw in ("def ", "class ", "function ", "const ", "let ", "var ")):
                return line_idx
        # Fallback to simple occurrence
        for line_idx, line in enumerate(content.splitlines(), start=1):
            if sym_name in line:
                return line_idx
    except Exception:
        pass
    return 1


def search(repo_id: str, query: str, top_k: int, db) -> list[dict]:
    """
    Hybrid semantic + keyword search over a repo's symbols and files.
    Returns list of dicts ordered by descending similarity score.
    """
    import re
    from models import Symbol, RepoFile

    q_clean = query.strip()
    if not q_clean:
        return []

    # Conversational stopword guard
    q_norm = re.sub(r"[^\w\s]", "", q_clean.lower()).strip()
    if q_norm in ("hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "bye", "goodbye"):
        return []

    storage_dir = STORAGE_ROOT / repo_id
    results_map: dict[int, dict] = {}

    # Extract search tokens (ignore 1-2 char words unless exact query is short)
    raw_tokens = re.findall(r"\b[A-Za-z0-9_]{3,}\b", q_clean)
    tokens = [t.lower() for t in raw_tokens if t.lower() not in {"what", "this", "that", "with", "from", "have", "here"}]

    # 1. Exact & Substring Keyword Matches (Symbols & Files)
    if len(q_clean) >= 3 or not tokens:
        # Build filter criteria
        filters = [
            Symbol.repo_id == repo_id,
            Symbol.name.ilike(q_clean),  # exact match
        ]
        if len(q_clean) >= 3:
            filters.append(Symbol.name.ilike(f"%{q_clean}%"))
            filters.append(RepoFile.path.ilike(f"%{q_clean}%"))

        for tok in tokens[:3]:
            filters.append(Symbol.name.ilike(f"%{tok}%"))
            filters.append(RepoFile.path.ilike(f"%{tok}%"))

        from sqlalchemy import or_
        keyword_syms = (
            db.query(Symbol)
            .join(RepoFile, Symbol.file_id == RepoFile.id)
            .filter(Symbol.repo_id == repo_id, or_(*filters[1:]))
            .limit(top_k * 2)
            .all()
        )
    else:
        keyword_syms = (
            db.query(Symbol)
            .filter(Symbol.repo_id == repo_id, Symbol.name.ilike(q_clean))
            .limit(top_k)
            .all()
        )

    for sym in keyword_syms:
        rf = db.query(RepoFile).filter(RepoFile.id == sym.file_id).first()
        rf_path = rf.path if rf else "unknown"
        disk_file = storage_dir / rf_path
        start_line = _find_symbol_line(disk_file, sym.name)

        # Higher score for exact matches
        sym_lower = sym.name.lower()
        if sym_lower == q_clean.lower():
            score = 1.0
        elif any(t == sym_lower for t in tokens):
            score = 0.95
        elif q_clean.lower() in sym_lower:
            score = 0.88
        else:
            score = 0.78

        results_map[sym.id] = {
            "symbol_id": sym.id,
            "symbol_type": sym.symbol_type,
            "name": sym.name,
            "file_path": rf_path,
            "language": rf.language if rf else None,
            "score": score,
            "start_line": start_line,
            "source_code": sym.source_code,
        }

    # 2. Semantic Vector Search via FAISS (if index exists)
    index = _load_faiss_index(repo_id)
    if index is not None and index.ntotal > 0:
        k = min(top_k * 2, index.ntotal)
        try:
            q_vec = embed_query(q_clean)
            scores, ids = index.search(q_vec, k)
            scores = scores[0].tolist()
            ids = ids[0].tolist()

            for score, sym_id in zip(scores, ids):
                # Filter out low-confidence semantic noise
                if sym_id < 0 or float(score) < 0.40 or sym_id in results_map:
                    continue
                sym = db.query(Symbol).filter(Symbol.id == int(sym_id)).first()
                if sym is None:
                    continue
                rf = db.query(RepoFile).filter(RepoFile.id == sym.file_id).first()
                rf_path = rf.path if rf else "unknown"
                disk_file = storage_dir / rf_path
                start_line = _find_symbol_line(disk_file, sym.name)

                results_map[sym.id] = {
                    "symbol_id": sym.id,
                    "symbol_type": sym.symbol_type,
                    "name": sym.name,
                    "file_path": rf_path,
                    "language": rf.language if rf else None,
                    "score": round(float(score), 4),
                    "start_line": start_line,
                    "source_code": sym.source_code,
                }
        except Exception as exc:
            logger.warning("FAISS search encountered error: %s", exc)

    # Sort results by descending score and trim to top_k
    sorted_results = sorted(results_map.values(), key=lambda r: r["score"], reverse=True)
    return sorted_results[:top_k]
