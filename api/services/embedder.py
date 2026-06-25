"""Sentence embedder: turns English text into a 384-dim vector.

The model is ``sentence-transformers/all-MiniLM-L6-v2`` (per SPEC §9).
It produces 384-dimensional L2-normalized vectors. We embed the
English ``meaning`` field of sentence units, NOT the hanzi — the
hanzi is the unit's identity, but the meaning is what semantic
search operates on. This is locked SPEC §2 / §6 AC17.

Two implementations:

* :class:`SentenceTransformerEmbedder` — the real model. Loads on
  first use, caches the encoder as a module-level singleton.

* :class:`HashingEmbedder` — a deterministic, dependency-free
  embedder that hashes the input text into a 384-dim L2-normalized
  vector. Used in tests so they don't need to download the real
  model (~80 MB) and don't need a GPU. NOT used in production.

The factory :func:`get_embedder` returns the real model by default;
tests pass ``force="hashing"`` or inject a custom encoder.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from typing import Protocol

import numpy as np


EMBEDDING_DIM: int = 384


class Embedder(Protocol):
    """The single contract the rest of the app uses."""

    def embed(self, text: str) -> np.ndarray:
        """Return a 1-D float32 numpy array of length ``EMBEDDING_DIM``.

        The vector is L2-normalized (so dot product = cosine
        similarity) for the real embedder. The hashing embedder
        also normalizes.
        """
        ...
    @property
    def dim(self) -> int:
        ...


# ---------------------------------------------------------------------------
# Hashing embedder — used in tests
# ---------------------------------------------------------------------------


class HashingEmbedder:
    """Deterministic, dependency-free embedder for tests.

    Hashes the input text with SHA-256, expands the digest into a
    384-dim float vector via a simple PRNG seeded by the digest, and
    L2-normalizes. Two identical inputs give identical vectors; two
    different inputs give different (uncorrelated) vectors with high
    probability. This is not a real embedding model — it's a stand-in
    that lets tests exercise the indexer without the real model.
    """

    @property
    def dim(self) -> int:
        return EMBEDDING_DIM

    def embed(self, text: str) -> np.ndarray:
        if not isinstance(text, str):
            raise ValueError(f"text must be a string, got {type(text).__name__}")
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # 32 bytes from SHA-256 → 8 uint32 seeds. We need 384 floats.
        # Use a simple xorshift PRNG seeded from the digest, with the
        # extra entropy from concatenating (digest, counter) for each
        # 32-float block.
        out = np.empty(self.dim, dtype=np.float32)
        out_per_block = 32  # 32 floats per SHA-256 expansion is enough entropy
        counter = 0
        filled = 0
        while filled < self.dim:
            block = hashlib.sha256(digest + counter.to_bytes(4, "big")).digest()
            # 32 bytes → 32 uint8 → 32 floats in [-1, 1]
            arr = np.frombuffer(block, dtype=np.uint8).astype(np.float32)
            arr = (arr - 127.5) / 127.5
            take = min(out_per_block, self.dim - filled)
            out[filled : filled + take] = arr[:take]
            filled += take
            counter += 1
        # L2 normalize so dot product = cosine similarity.
        norm = float(np.linalg.norm(out))
        if norm > 0:
            out /= norm
        return out


# ---------------------------------------------------------------------------
# Real embedder — sentence-transformers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_model(model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """Load the sentence-transformers model. Cached as a singleton.

    The first call downloads the model (~80 MB) and may take 10-30s
    on a cold cache. Subsequent calls return the in-process model
    instantly.
    """
    # Imported lazily so tests that only use HashingEmbedder don't
    # pay the import cost of sentence-transformers (which is heavy).
    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

    return SentenceTransformer(model_name)


class SentenceTransformerEmbedder:
    """Real-model embedder. Wraps ``sentence-transformers``."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None  # lazy; loaded on first embed()

    @property
    def dim(self) -> int:
        return EMBEDDING_DIM

    def _ensure_loaded(self) -> None:
        if self._model is None:
            self._model = _load_model(self._model_name)

    def embed(self, text: str) -> np.ndarray:
        if not isinstance(text, str):
            raise ValueError(f"text must be a string, got {type(text).__name__}")
        self._ensure_loaded()
        assert self._model is not None
        vec = self._model.encode(text, normalize_embeddings=True)
        arr = np.asarray(vec, dtype=np.float32)
        if arr.shape != (self.dim,):
            raise RuntimeError(
                f"embedder returned shape {arr.shape}, expected ({self.dim},)"
            )
        return arr

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Embed a list of texts. Returns shape (len(texts), dim)."""
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            raise ValueError("texts must be a list of strings")
        self._ensure_loaded()
        assert self._model is not None
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return np.asarray(vecs, dtype=np.float32)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


_embedder_singleton: Embedder | None = None


def get_embedder(force: str | None = None) -> Embedder:
    """Return a process-wide embedder.

    ``force``:
      * ``"hashing"`` — HashingEmbedder (no model download)
      * ``"real"`` — SentenceTransformerEmbedder
      * ``None`` (default) — real if available, else hashing
    """
    global _embedder_singleton
    if force == "hashing":
        return HashingEmbedder()
    if force == "real":
        return SentenceTransformerEmbedder()
    if _embedder_singleton is None:
        try:
            _embedder_singleton = SentenceTransformerEmbedder()
        except Exception:
            # Model download / load failure (no network, no torch, etc.)
            # — fall back to hashing. Production callers will see
            # degraded semantic search; tests will see deterministic
            # vectors.
            _embedder_singleton = HashingEmbedder()
    return _embedder_singleton


def reset_embedder_singleton() -> None:
    global _embedder_singleton
    _embedder_singleton = None


__all__ = [
    "EMBEDDING_DIM",
    "Embedder",
    "HashingEmbedder",
    "SentenceTransformerEmbedder",
    "get_embedder",
    "reset_embedder_singleton",
]
