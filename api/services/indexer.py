"""FAISS-backed vector index over sentence unit embeddings.

SPEC §6 AC9, AC10, AC11, AC13, AC16, AC17, AC27c all touch the
index. This module owns:

* ``<vault>/index/faiss.index`` — the FAISS index file (binary).
* ``<vault>/index/embeddings.npy`` — the full float32 matrix of
  vectors, shape (N, EMBEDDING_DIM).
* ``<vault>/index/unit_index.json`` — the id-to-position map,
  ``{"<unit_id>": <int position>}`` plus ``order``: list of unit
  ids in FAISS row order.

Design notes
------------
* Cosine similarity is implemented as inner product on L2-normalized
  vectors. The embedder returns L2-normalized vectors, so
  ``index.search`` returns cosine scores in [-1, 1]. We keep them
  signed (no clamping at 0) so that ``opposite`` edges (negative
  cosine) stay negative in the data.
* ``add(id, vector)`` is idempotent: adding the same id twice is a
  no-op (the existing position's vector is NOT updated — to update,
  use ``update(id, vector)``). This makes re-running the connection
  script on a saved unit safe.
* ``remove(id)`` rebuilds the index without the removed vector.
  FAISS doesn't support in-place removal; the rebuild cost is
  O(N) for the affected id, which is fine at MVP scale.
* The on-disk files are the source of truth; the in-memory
  representation is rebuilt from them on load.
* This module never opens a network socket. Per SPEC §6 AC29, the
  only module that talks to the network is ``ai_client.py``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss  # type: ignore[import-untyped]
import numpy as np

from api.services.embedder import EMBEDDING_DIM, Embedder

log = logging.getLogger(__name__)


# On-disk filenames, relative to the vault root.
_FAISS_FILE = "faiss.index"
_EMBEDDINGS_FILE = "embeddings.npy"
_INDEX_FILE = "unit_index.json"


@dataclass(frozen=True)
class SearchHit:
    """A single result from ``Index.search``."""

    unit_id: str
    score: float  # cosine similarity in [-1, 1]


class Index:
    """FAISS-backed vector index over sentence unit embeddings.

    The index is fully serializable: ``save`` writes three files
    under ``<vault>/index/``; ``load`` reads them back. The
    constructor does NOT auto-load — call ``load(vault_root)``
    explicitly, or use the classmethod ``Index.load_or_empty``.

    Thread-safety: not thread-safe. A single instance is intended
    for a single FastAPI worker process. Concurrency at the worker
    level is handled by the ASGI server.
    """

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim
        # IndexFlatIP = exact inner product. We use it on L2-normalized
        # vectors, which gives exact cosine similarity.
        self._index: faiss.IndexFlatIP = faiss.IndexFlatIP(dim)
        # id -> row position
        self._id_to_pos: dict[str, int] = {}
        # row position -> id (parallel array for fast reverse lookup)
        self._pos_to_id: list[str] = []
        # All vectors in row order, for the embeddings.npy file.
        self._vectors: np.ndarray = np.empty((0, dim), dtype=np.float32)

    # ------------------------------------------------------------------
    # Classmethods
    # ------------------------------------------------------------------

    @classmethod
    def load_or_empty(cls, vault_root: str) -> "Index":
        """Load from disk if files exist; otherwise return an empty
        index ready to use. Never raises for a missing index."""
        idx = cls()
        index_dir = Path(vault_root) / "index"
        if (index_dir / _INDEX_FILE).is_file():
            idx.load(vault_root)
        return idx

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def dim(self) -> int:
        return self._dim

    def __len__(self) -> int:
        return self._index.ntotal

    def __contains__(self, unit_id: str) -> bool:
        return unit_id in self._id_to_pos

    @property
    def ids(self) -> list[str]:
        return list(self._pos_to_id)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, unit_id: str, vector: np.ndarray) -> None:
        """Add a vector under ``unit_id``.

        Idempotent: if the id is already present, the existing
        vector is preserved (no error, no overwrite). To change a
        vector, call :meth:`update` explicitly.
        """
        self._validate_vector(vector)
        if unit_id in self._id_to_pos:
            return
        v = np.asarray(vector, dtype=np.float32).reshape(1, self._dim)
        self._index.add(v)
        new_pos = len(self._pos_to_id)
        self._id_to_pos[unit_id] = new_pos
        self._pos_to_id.append(unit_id)
        # Append to the embeddings matrix.
        self._vectors = np.concatenate([self._vectors, v], axis=0)

    def update(self, unit_id: str, vector: np.ndarray) -> None:
        """Replace the vector for an existing id.

        FAISS IndexFlatIP doesn't support in-place updates; we
        rebuild the index from scratch with the new vector in place.
        O(N) — fine at MVP scale.
        """
        self._validate_vector(vector)
        if unit_id not in self._id_to_pos:
            raise KeyError(f"unit_id {unit_id!r} not in index")
        pos = self._id_to_pos[unit_id]
        new_v = np.asarray(vector, dtype=np.float32).reshape(1, self._dim)
        self._vectors[pos] = new_v[0]
        # Rebuild the FAISS index in place.
        self._index = faiss.IndexFlatIP(self._dim)
        if len(self._vectors) > 0:
            self._index.add(self._vectors)

    def remove(self, unit_id: str) -> bool:
        """Remove the vector for ``unit_id``. Returns True if removed,
        False if the id was not present. Rebuilds the index."""
        if unit_id not in self._id_to_pos:
            return False
        pos = self._id_to_pos[unit_id]
        # Remove from vectors matrix.
        if len(self._vectors) > 1:
            mask = np.ones(len(self._vectors), dtype=bool)
            mask[pos] = False
            self._vectors = self._vectors[mask]
        else:
            self._vectors = np.empty((0, self._dim), dtype=np.float32)
        # Remove from id maps and rebuild pos_to_id.
        del self._id_to_pos[unit_id]
        self._pos_to_id.pop(pos)
        # All positions after `pos` shift down by 1.
        for k, v in self._id_to_pos.items():
            if v > pos:
                self._id_to_pos[k] = v - 1
        # Rebuild FAISS.
        self._index = faiss.IndexFlatIP(self._dim)
        if len(self._vectors) > 0:
            self._index.add(self._vectors)
        return True

    def clear(self) -> None:
        """Drop all vectors. Used by ``reindex.py`` before rebuild."""
        self._index = faiss.IndexFlatIP(self._dim)
        self._id_to_pos = {}
        self._pos_to_id = []
        self._vectors = np.empty((0, self._dim), dtype=np.float32)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: np.ndarray, k: int = 10) -> list[SearchHit]:
        """Return the top-k most similar unit ids to the query.

        ``query`` is a 1-D vector of length ``self.dim``. Returns a
        list of :class:`SearchHit` ordered by descending cosine
        similarity.
        """
        if self._index.ntotal == 0:
            return []
        self._validate_vector(query)
        q = np.asarray(query, dtype=np.float32).reshape(1, self._dim)
        # FAISS returns (distances, indices) — for IndexFlatIP, the
        # values are inner products = cosine (on L2-normalized vecs).
        scores, indices = self._index.search(q, min(k, self._index.ntotal))
        hits: list[SearchHit] = []
        for score, idx in zip(scores[0].tolist(), indices[0].tolist()):
            if idx < 0 or idx >= len(self._pos_to_id):
                continue
            hits.append(SearchHit(unit_id=self._pos_to_id[idx], score=float(score)))
        return hits

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, vault_root: str) -> None:
        """Write the index to disk under ``<vault>/index/``."""
        index_dir = Path(vault_root) / "index"
        index_dir.mkdir(parents=True, exist_ok=True)

        # FAISS index.
        faiss.write_index(self._index, str(index_dir / _FAISS_FILE))

        # Embeddings matrix.
        np.save(str(index_dir / _EMBEDDINGS_FILE), self._vectors)

        # Id map.
        unit_index: dict[str, Any] = {
            "order": list(self._pos_to_id),
            "id_to_pos": dict(self._id_to_pos),
        }
        (index_dir / _INDEX_FILE).write_text(
            json.dumps(unit_index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, vault_root: str) -> None:
        """Load the index from disk. Raises FileNotFoundError if
        ``unit_index.json`` is missing; raises ValueError if the
        on-disk files are inconsistent."""
        index_dir = Path(vault_root) / "index"
        index_file = index_dir / _INDEX_FILE
        if not index_file.is_file():
            raise FileNotFoundError(f"missing {index_file}")

        unit_index = json.loads(index_file.read_text(encoding="utf-8"))
        order = unit_index.get("order")
        id_to_pos = unit_index.get("id_to_pos")
        if not isinstance(order, list) or not isinstance(id_to_pos, dict):
            raise ValueError("unit_index.json has malformed shape")

        # Load embeddings matrix.
        embeddings_path = index_dir / _EMBEDDINGS_FILE
        if embeddings_path.is_file():
            self._vectors = np.load(str(embeddings_path))
        else:
            self._vectors = np.empty((0, self._dim), dtype=np.float32)

        if self._vectors.shape[0] != len(order):
            raise ValueError(
                f"embeddings.npy has {self._vectors.shape[0]} rows but "
                f"unit_index.json declares {len(order)} ids — index is "
                f"corrupt; rebuild with scripts/reindex.py"
            )

        # Load FAISS index.
        faiss_path = index_dir / _FAISS_FILE
        if faiss_path.is_file():
            self._index = faiss.read_index(str(faiss_path))
        else:
            # Reconstruct from embeddings.
            self._index = faiss.IndexFlatIP(self._dim)
            if len(self._vectors) > 0:
                self._index.add(self._vectors)

        self._pos_to_id = list(order)
        self._id_to_pos = {k: int(v) for k, v in id_to_pos.items()}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_vector(self, v: np.ndarray) -> None:
        arr = np.asarray(v, dtype=np.float32)
        if arr.shape not in {(self._dim,), (1, self._dim)}:
            raise ValueError(
                f"vector shape {arr.shape} does not match dim {self._dim}"
            )
        if not np.all(np.isfinite(arr)):
            raise ValueError("vector contains non-finite values (nan/inf)")


__all__ = ["Index", "SearchHit"]
