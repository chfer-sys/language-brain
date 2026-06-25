"""Tests for the FAISS-backed indexer (SPEC §6 AC9, AC10, AC11, AC13).

The tests use ``tmp_path`` for vault isolation and the
``HashingEmbedder`` for deterministic, dependency-free vectors —
no model download, no GPU needed.

Coverage:

* AC9: after adding a sentence, the FAISS index contains one
  more vector; searching with the same vector returns the id.
* AC10: ``save`` then ``load`` reproduces the same content.
* AC11 (partial): ``remove`` shrinks the index and drops the id
  from search results.
* Idempotency: adding the same id twice is a no-op.
* ``update`` replaces a vector.
* Empty index: search returns ``[]``.
* Persistence: the three on-disk files (faiss.index,
  embeddings.npy, unit_index.json) are written.
* Search hits: scores are in [-1, 1], results are ordered.
* ``load`` raises on a missing index file.
* ``load`` raises on a corrupt index (size mismatch).
* ``clear`` empties the index.
* L2-normalization is enforced by the embedder, so cosine =
  inner product.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from api.services.embedder import EMBEDDING_DIM, HashingEmbedder
from api.services.indexer import _EMBEDDINGS_FILE, _INDEX_FILE, Index, SearchHit
from api.services import indexer as indexer_module


# ---------------------------------------------------------------------------
# AC9 — add a sentence grows the index by one
# ---------------------------------------------------------------------------


def test_add_grows_index_by_one(tmp_path: Path) -> None:
    """AC9: adding a sentence produces exactly one more vector in the
    FAISS index, and the new vector's nearest neighbor is itself."""
    vault = str(tmp_path)
    idx = Index.load_or_empty(vault)
    assert len(idx) == 0

    embedder = HashingEmbedder()
    v = embedder.embed("I see food and my mouth waters")
    idx.add("2026-06-24-001", v)

    assert len(idx) == 1
    assert "2026-06-24-001" in idx
    assert idx.ids == ["2026-06-24-001"]

    # Searching with the same vector returns the id as the top hit,
    # with cosine ≈ 1.0 (within float32 precision).
    hits = idx.search(v, k=1)
    assert len(hits) == 1
    assert hits[0].unit_id == "2026-06-24-001"
    assert math.isclose(hits[0].score, 1.0, abs_tol=1e-5)


def test_add_multiple_grows_linearly(tmp_path: Path) -> None:
    """Adding N distinct ids gives an index of size N."""
    vault = str(tmp_path)
    idx = Index.load_or_empty(vault)
    embedder = HashingEmbedder()
    for i in range(5):
        v = embedder.embed(f"sentence {i}")
        idx.add(f"s-{i}", v)
    assert len(idx) == 5
    assert set(idx.ids) == {f"s-{i}" for i in range(5)}


def test_add_is_idempotent(tmp_path: Path) -> None:
    """Re-adding the same id is a no-op (no error, no duplicate)."""
    vault = str(tmp_path)
    idx = Index.load_or_empty(vault)
    embedder = HashingEmbedder()
    v = embedder.embed("x")
    idx.add("dup", v)
    idx.add("dup", v)
    idx.add("dup", embedder.embed("different text"))  # still no-op
    assert len(idx) == 1
    assert idx.ids == ["dup"]


def test_add_rejects_wrong_dim(tmp_path: Path) -> None:
    idx = Index.load_or_empty(str(tmp_path))
    with pytest.raises(ValueError, match="shape"):
        idx.add("bad", np.zeros(EMBEDDING_DIM + 1, dtype=np.float32))


def test_add_rejects_non_finite(tmp_path: Path) -> None:
    idx = Index.load_or_empty(str(tmp_path))
    bad = np.full(EMBEDDING_DIM, np.nan, dtype=np.float32)
    with pytest.raises(ValueError, match="non-finite"):
        idx.add("nan", bad)


# ---------------------------------------------------------------------------
# AC10 (partial) — save / load round-trip
# ---------------------------------------------------------------------------


def test_save_writes_three_files(tmp_path: Path) -> None:
    """Persistence: three files under <vault>/index/."""
    vault = str(tmp_path)
    idx = Index.load_or_empty(vault)
    embedder = HashingEmbedder()
    idx.add("a", embedder.embed("alpha"))
    idx.add("b", embedder.embed("beta"))
    idx.save(vault)

    index_dir = tmp_path / "index"
    assert (index_dir / _INDEX_FILE).is_file()
    assert (index_dir / _EMBEDDINGS_FILE).is_file()
    # FAISS file name is loaded from the module constant.
    faiss_name = indexer_module._FAISS_FILE
    assert (index_dir / faiss_name).is_file()


def test_save_load_round_trip(tmp_path: Path) -> None:
    """Save the index, then load into a fresh Index, assert the
    loaded index matches."""
    vault = str(tmp_path)
    embedder = HashingEmbedder()

    idx1 = Index.load_or_empty(vault)
    v_a = embedder.embed("alpha")
    v_b = embedder.embed("beta")
    idx1.add("a", v_a)
    idx1.add("b", v_b)
    idx1.save(vault)

    # Fresh instance, loaded from disk.
    idx2 = Index.load_or_empty(vault)
    assert len(idx2) == 2
    assert set(idx2.ids) == {"a", "b"}
    # Searching for v_a on the loaded index returns "a" as top hit.
    hits = idx2.search(v_a, k=1)
    assert hits[0].unit_id == "a"
    assert math.isclose(hits[0].score, 1.0, abs_tol=1e-5)


def test_unit_index_json_has_order_and_id_to_pos(tmp_path: Path) -> None:
    """The JSON sidecar carries the insertion order and the id→pos
    map. Both are required to round-trip."""
    vault = str(tmp_path)
    idx = Index.load_or_empty(vault)
    embedder = HashingEmbedder()
    idx.add("z", embedder.embed("z"))
    idx.add("a", embedder.embed("a"))
    idx.add("m", embedder.embed("m"))
    idx.save(vault)

    data = json.loads((tmp_path / "index" / _INDEX_FILE).read_text(encoding="utf-8"))
    assert data["order"] == ["z", "a", "m"]
    assert data["id_to_pos"] == {"z": 0, "a": 1, "m": 2}


def test_load_missing_index_raises(tmp_path: Path) -> None:
    """If no index files exist, ``load`` raises FileNotFoundError."""
    idx = Index()
    with pytest.raises(FileNotFoundError):
        idx.load(str(tmp_path))


def test_load_corrupt_size_mismatch_raises(tmp_path: Path) -> None:
    """unit_index.json says 3 ids but embeddings.npy has 2 rows:
    the index is corrupt, load must raise."""
    index_dir = tmp_path / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / _INDEX_FILE).write_text(
        json.dumps({"order": ["a", "b", "c"], "id_to_pos": {"a": 0, "b": 1, "c": 2}}),
        encoding="utf-8",
    )
    np.save(index_dir / _EMBEDDINGS_FILE, np.zeros((2, EMBEDDING_DIM), dtype=np.float32))
    idx = Index()
    with pytest.raises(ValueError, match="corrupt"):
        idx.load(str(tmp_path))


# ---------------------------------------------------------------------------
# AC11 (partial) — remove
# ---------------------------------------------------------------------------


def test_remove_drops_id_and_shrinks_index(tmp_path: Path) -> None:
    """AC11: removing a sentence drops the vector from the index
    and removes the id from search results."""
    vault = str(tmp_path)
    idx = Index.load_or_empty(vault)
    embedder = HashingEmbedder()
    v_a = embedder.embed("alpha")
    v_b = embedder.embed("beta")
    idx.add("a", v_a)
    idx.add("b", v_b)

    assert len(idx) == 2
    assert idx.remove("a") is True
    assert len(idx) == 1
    assert "a" not in idx
    assert "b" in idx
    assert idx.ids == ["b"]  # order preserved for the survivor

    # Searching for v_a on the reduced index returns only "b" (or []).
    hits = idx.search(v_a, k=5)
    assert all(h.unit_id != "a" for h in hits)


def test_remove_missing_id_returns_false(tmp_path: Path) -> None:
    idx = Index.load_or_empty(str(tmp_path))
    assert idx.remove("never-added") is False


def test_remove_only_vector_clears_index(tmp_path: Path) -> None:
    """Removing the last vector leaves the index empty but usable."""
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    idx.add("only", embedder.embed("only"))
    assert len(idx) == 1
    idx.remove("only")
    assert len(idx) == 0
    assert idx.search(embedder.embed("anything")) == []


def test_remove_then_add_uses_new_position(tmp_path: Path) -> None:
    """After remove, add of the same id works and the position is
    fresh."""
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    v1 = embedder.embed("v1")
    idx.add("x", v1)
    idx.remove("x")
    v2 = embedder.embed("v2")
    idx.add("x", v2)
    assert len(idx) == 1
    hits = idx.search(v2, k=1)
    assert hits[0].unit_id == "x"
    assert math.isclose(hits[0].score, 1.0, abs_tol=1e-5)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_replaces_vector(tmp_path: Path) -> None:
    """update changes the vector; search reflects the new vector."""
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    v_old = embedder.embed("old text")
    v_new = embedder.embed("completely new text")
    idx.add("x", v_old)
    idx.update("x", v_new)
    # Search for v_new returns x; search for v_old does not.
    hits_new = idx.search(v_new, k=1)
    assert hits_new[0].unit_id == "x"
    assert math.isclose(hits_new[0].score, 1.0, abs_tol=1e-5)
    hits_old = idx.search(v_old, k=1)
    # v_old is unrelated; top hit may be x with low score, or may be empty.
    # The point is v_new is the new canonical match for "x".
    assert all(h.unit_id != "x" or h.score < 0.99 for h in hits_old)


def test_update_missing_id_raises(tmp_path: Path) -> None:
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    with pytest.raises(KeyError):
        idx.update("missing", embedder.embed("x"))


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_empty_index_returns_empty(tmp_path: Path) -> None:
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    assert idx.search(embedder.embed("anything")) == []


def test_search_returns_hits_in_score_order(tmp_path: Path) -> None:
    """Results are sorted by descending cosine similarity."""
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    v_target = embedder.embed("drooling")
    idx.add("target", v_target)
    idx.add("noise1", embedder.embed("unrelated noise 1"))
    idx.add("noise2", embedder.embed("unrelated noise 2"))
    idx.add("noise3", embedder.embed("unrelated noise 3"))

    hits = idx.search(v_target, k=10)
    assert len(hits) == 4
    # Sorted by descending score.
    for a, b in zip(hits, hits[1:]):
        assert a.score >= b.score
    # The target is the top hit.
    assert hits[0].unit_id == "target"
    assert math.isclose(hits[0].score, 1.0, abs_tol=1e-5)


def test_search_scores_in_minus_one_to_one(tmp_path: Path) -> None:
    """Cosine is in [-1, 1]."""
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    for i in range(10):
        idx.add(f"u-{i}", embedder.embed(f"unit {i}"))
    hits = idx.search(embedder.embed("query"), k=10)
    for h in hits:
        assert -1.0 - 1e-6 <= h.score <= 1.0 + 1e-6


def test_search_hit_dataclass(tmp_path: Path) -> None:
    """SearchHit has unit_id and score as documented."""
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    idx.add("a", embedder.embed("a"))
    hits = idx.search(embedder.embed("a"), k=1)
    assert isinstance(hits[0], SearchHit)
    assert hits[0].unit_id == "a"
    assert isinstance(hits[0].score, float)


def test_search_k_caps_results(tmp_path: Path) -> None:
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    for i in range(10):
        idx.add(f"u-{i}", embedder.embed(f"unit {i}"))
    hits = idx.search(embedder.embed("x"), k=3)
    assert len(hits) == 3


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


def test_clear_empties_index(tmp_path: Path) -> None:
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    for i in range(5):
        idx.add(f"u-{i}", embedder.embed(f"u-{i}"))
    assert len(idx) == 5
    idx.clear()
    assert len(idx) == 0
    assert idx.ids == []


# ---------------------------------------------------------------------------
# Embedder integration
# ---------------------------------------------------------------------------


def test_hashing_embedder_is_deterministic() -> None:
    """The hashing embedder returns the same vector for the same
    input — required for test reproducibility."""
    e = HashingEmbedder()
    a = e.embed("hello world")
    b = e.embed("hello world")
    assert np.array_equal(a, b)


def test_hashing_embedder_is_l2_normalized() -> None:
    """Vectors are unit length, so dot product = cosine."""
    e = HashingEmbedder()
    v = e.embed("anything")
    norm = float(np.linalg.norm(v))
    assert math.isclose(norm, 1.0, abs_tol=1e-5)


def test_hashing_embedder_distinguishes_inputs() -> None:
    """Two different inputs give very different vectors (cosine
    near 0) for the hashing embedder — it's a stand-in for a real
    semantic model and does NOT learn semantics."""
    e = HashingEmbedder()
    a = e.embed("hello world")
    b = e.embed("completely different text")
    cosine = float(np.dot(a, b))
    assert abs(cosine) < 0.5  # not perfectly orthogonal but uncorrelated


def test_hashing_embedder_rejects_non_string() -> None:
    e = HashingEmbedder()
    with pytest.raises(ValueError):
        e.embed(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Real embedder: we do NOT download the model in tests. The import
# alone is checked to make sure the package is installed.
# ---------------------------------------------------------------------------


def test_real_embedder_class_imports() -> None:
    """The real embedder class is importable. We do NOT call
    .embed() because that would download the model."""
    from api.services.embedder import SentenceTransformerEmbedder  # noqa: F401


def test_real_embedder_lazy_load() -> None:
    """The real embedder does not load the model in __init__ —
    it loads on first .embed() call. This keeps module import
    cheap and lets tests inject a different embedder."""
    from api.services.embedder import SentenceTransformerEmbedder

    e = SentenceTransformerEmbedder()
    # No model loaded yet.
    assert e._model is None  # type: ignore[attr-defined]
