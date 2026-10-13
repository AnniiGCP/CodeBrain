"""
vectorstore/embedder.py
-----------------------
Loads a sentence-transformer model with automatic fallback:
  Primary  : BAAI/bge-code-v1
  Fallback  : microsoft/codebert-base

Exposes:
  get_model()            -> SentenceTransformer (cached singleton)
  embed_texts(texts)     -> np.ndarray of float32, shape (N, D), L2-normalised
  embed_query(query)     -> np.ndarray of float32, shape (1, D), L2-normalised
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

logger = logging.getLogger(__name__)

_PRIMARY_MODEL   = "sentence-transformers/all-MiniLM-L6-v2"
_FALLBACK_MODELS = [
    "BAAI/bge-small-en-v1.5",
]


def _get_dim(model) -> int:
    if hasattr(model, "get_embedding_dimension"):
        return model.get_embedding_dimension()
    return model.get_sentence_embedding_dimension()


@lru_cache(maxsize=1)
def get_model():
    """Return a cached SentenceTransformer. Tries models in order."""
    try:
        import torch
        torch.set_num_threads(1)
    except Exception:
        pass

    from sentence_transformers import SentenceTransformer  # lazy import

    for model_name in [_PRIMARY_MODEL, *_FALLBACK_MODELS]:
        try:
            logger.info("Loading embedding model: %s", model_name)
            model = SentenceTransformer(model_name)
            dim = _get_dim(model)
            logger.info("Loaded model %s (dim=%d)", model_name, dim)
            return model
        except Exception as exc:
            logger.warning("Could not load %s: %s — trying next.", model_name, exc)

    raise RuntimeError("No embedding model could be loaded.")


def _l2_normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return arr / norms


def embed_texts(texts: list[str]) -> np.ndarray:
    """Encode a list of texts → float32 array, L2-normalised (for inner-product == cosine)."""
    model = get_model()
    vecs = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=False,
        convert_to_numpy=True,
    ).astype(np.float32)
    return _l2_normalize(vecs)


def embed_query(query: str) -> np.ndarray:
    """Encode a single query string → float32 array shape (1, D)."""
    return embed_texts([query])
