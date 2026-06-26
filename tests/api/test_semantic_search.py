"""Tests for the semantic search pass (SPEC §6 AC17) and the hit merger.

AC17 contract: ``semantic_search`` returns sentence units whose
``meaning`` embedding has cosine similarity to the query embedding
strictly greater than the threshold (default 0.6). Returns empty
list for empty query, missing index, or all-below-threshold.

The hit merger test focuses on the dedup-by-(id,type), max-score,
deterministic-sort contract that the future kinds toggle (T22)
will rely on.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from api.services.embedder import HashingEmbedder
from api.services.indexer import Index
from api.services.search import (
    SEMANTIC_THRESHOLD,
    SearchHit,
    merge_hits,
    semantic_search,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_sentence(
    vault: Path,
    sid: str,
    hanzi: str,
    pinyin: str,
    meaning: str,
) -> None:
    out_dir = vault / "units" / "sentences"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{sid}.json").write_text(
        json.dumps(
            {
                "id": sid,
                "type": "sentence",
                "name": hanzi,
                "properties": {
                    "hanzi": hanzi,
                    "pinyin": pinyin,
                    "english": "(unused by search)",
                    "meaning": meaning,
                    "words": [],
                    "word_refs": [],
                    "groups": [],
                    "antonyms": [],
                },
                "connections": [],
                "created": "2026-06-24",
                "updated": "2026-06-24",
                "author_confirmed": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _seed_index(vault: Path, sentence_meanings: dict[str, str]) -> None:
    embedder = HashingEmbedder()
    idx = Index()
    for sid, meaning in sentence_meanings.items():
        idx.add(sid, embedder.embed(meaning))
    idx.save(str(vault))


# ---------------------------------------------------------------------------
# AC17 — semantic search returns sentence units with cosine > threshold
# ---------------------------------------------------------------------------


def test_semantic_threshold_default_is_0_6() -> None:
    """AC17 specifies a default cosine threshold of 0.6."""
    assert SEMANTIC_THRESHOLD == pytest.approx(0.6)


def test_semantic_empty_query_returns_empty(tmp_path: Path) -> None:
    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "a greeting")
    _seed_index(tmp_path, {"s-1": "a greeting"})
    assert semantic_search(str(tmp_path), "") == []
    assert semantic_search(str(tmp_path), "   ") == []
    assert semantic_search(str(tmp_path), None) == []  # type: ignore[arg-type]


def test_semantic_empty_index_returns_empty(tmp_path: Path) -> None:
    """No index/ dir on disk → empty result, not an error."""
    embedder = HashingEmbedder()
    assert semantic_search(str(tmp_path), "anything", embedder=embedder) == []


def test_semantic_returns_self_as_top_hit(tmp_path: Path) -> None:
    """Searching with the same embedding returns the seed id as the
    top hit with cosine ≈ 1.0."""
    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "a casual greeting")
    _seed_index(tmp_path, {"s-1": "a casual greeting"})
    embedder = HashingEmbedder()
    hits = semantic_search(str(tmp_path), "a casual greeting", embedder=embedder)
    assert len(hits) == 1
    assert hits[0].unit_id == "s-1"
    assert hits[0].unit_type == "sentence"
    assert hits[0].name == "你好"
    assert hits[0].snippet == "nǐ hǎo"
    assert math.isclose(hits[0].score, 1.0, abs_tol=1e-5)


def test_semantic_filters_below_threshold(tmp_path: Path) -> None:
    """Hits at or below the threshold are dropped, even if FAISS
    returned them."""
    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "completely unrelated")
    _seed_index(tmp_path, {"s-1": "completely unrelated"})
    embedder = HashingEmbedder()
    # Threshold of 1.5 is unreachable on cosine (max is 1.0).
    hits = semantic_search(
        str(tmp_path),
        "anything",
        threshold=1.5,
        embedder=embedder,
    )
    assert hits == []


def test_semantic_skips_missing_unit_file(tmp_path: Path) -> None:
    """If a FAISS hit references a sentence whose file is gone
    (deleted without reindex), the hit is silently dropped, not
    raised."""
    embedder = HashingEmbedder()
    idx = Index()
    idx.add("orphan", embedder.embed("a sentence with no file"))
    idx.save(str(tmp_path))
    # Note: no units/sentences/orphan.json on disk.
    hits = semantic_search(str(tmp_path), "a sentence with no file", embedder=embedder)
    assert hits == []


def test_semantic_all_hits_above_threshold(tmp_path: Path) -> None:
    """With a very low threshold (e.g. -1.0), every indexed sentence
    that FAISS returns passes the cosine filter, since cosine is
    bounded below by -1.0.

    Note: with the ``HashingEmbedder``, two unrelated inputs can
    have negative cosine (anti-correlated hashes), so threshold=0.0
    is not safe for a 'return all hits' test. The FAISS result list
    itself is bounded by the k we asked for, so the upper bound on
    returned hits is the smaller of (vault size, k)."""
    for i in range(3):
        _seed_sentence(tmp_path, f"s-{i}", f"句子{i}", f"jù{i}", f"meaning number {i}")
    _seed_index(tmp_path, {f"s-{i}": f"meaning number {i}" for i in range(3)})
    embedder = HashingEmbedder()
    hits = semantic_search(str(tmp_path), "anything", threshold=-1.0, embedder=embedder)
    assert {h.unit_id for h in hits} == {"s-0", "s-1", "s-2"}


def test_semantic_result_payload_omits_english_and_meaning(tmp_path: Path) -> None:
    """AC20 (forward-looking): the SearchHit returned by semantic
    search contains no 'english' or 'meaning' field. The
    has_english_or_meaning_key helper must return False."""
    from api.services.search import has_english_or_meaning_key

    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "a greeting")
    _seed_index(tmp_path, {"s-1": "a greeting"})
    embedder = HashingEmbedder()
    hits = semantic_search(str(tmp_path), "a greeting", embedder=embedder)
    payload = [h.__dict__ for h in hits]
    assert not has_english_or_meaning_key(payload)


# ---------------------------------------------------------------------------
# merge_hits — union, dedup, max score, deterministic order
# ---------------------------------------------------------------------------


def _h(unit_id: str, unit_type: str, score: float) -> SearchHit:
    return SearchHit(
        unit_id=unit_id, unit_type=unit_type, name="x", snippet="y", score=score
    )


def test_merge_hits_empty_returns_empty() -> None:
    assert merge_hits() == []
    assert merge_hits([], []) == []
    assert merge_hits([], [_h("a", "sentence", 0.5)]) == [_h("a", "sentence", 0.5)]


def test_merge_hits_keeps_max_score_per_key() -> None:
    """Same (unit_id, unit_type) appears in two lists with different
    scores — the higher-score copy wins."""
    a_low = _h("s-1", "sentence", 0.3)
    a_high = _h("s-1", "sentence", 0.9)
    b = _h("s-2", "sentence", 0.5)
    merged = merge_hits([a_low, b], [a_high])
    assert merged == [a_high, b]


def test_merge_hits_distinct_unit_types_are_separate() -> None:
    """Same unit_id with different unit_type are kept as separate
    entries (the merger keys on (id, type))."""
    s = _h("chi", "sentence", 0.5)
    w = _h("chi", "word", 0.7)
    merged = merge_hits([s], [w])
    assert merged == [w, s]  # w has higher score → first


def test_merge_hits_sort_is_deterministic() -> None:
    """Output is sorted by (-score, unit_id, unit_type) regardless
    of input order."""
    a = _h("s-a", "sentence", 0.5)
    b = _h("s-b", "sentence", 0.9)
    c = _h("s-c", "sentence", 0.5)
    forward = merge_hits([a, b, c])
    reverse = merge_hits([c, b, a])
    assert forward == reverse == [b, a, c]


def test_merge_hits_tie_breaks_on_unit_id_then_type() -> None:
    """Two hits with identical scores: lower unit_id wins; on same
    unit_id, lower unit_type wins."""
    a = _h("s-b", "sentence", 0.5)
    b = _h("s-a", "sentence", 0.5)
    c = _h("s-a", "group", 0.5)  # same id, different type
    merged = merge_hits([a, b, c])
    # All tied at 0.5. Sort key is (-score, unit_id, unit_type).
    # s-a appears with both sentence and group — group sorts first
    # alphabetically. Then s-b.
    assert merged == [c, b, a]


def test_merge_hits_preserves_name_and_snippet_from_winner() -> None:
    """When the same key appears in both lists, the surviving hit's
    name/snippet come from the higher-scoring instance, not the
    first-seen."""
    loser = SearchHit(
        unit_id="s-1", unit_type="sentence",
        name="loser-hanzi", snippet="loser-pinyin", score=0.3,
    )
    winner = SearchHit(
        unit_id="s-1", unit_type="sentence",
        name="winner-hanzi", snippet="winner-pinyin", score=0.9,
    )
    merged = merge_hits([loser], [winner])
    assert merged == [winner]


# ---------------------------------------------------------------------------
# Integration — lexical + semantic merge end-to-end
# ---------------------------------------------------------------------------


def test_lexical_then_semantic_merge_produces_deduped_results(
    tmp_path: Path,
) -> None:
    """A sentence that scores on both lexical AND semantic passes
    appears only once in the merged output, with the higher of
    the two scores."""
    # Seed: "你好世界" has hanzi tokens 你/好/世/界 and meaning
    # "a common greeting in everyday speech".
    _seed_sentence(tmp_path, "s-1", "你好世界", "nǐ hǎo shì jiè", "a common greeting")
    _seed_sentence(tmp_path, "s-2", "再见", "zài jiàn", "a farewell")
    _seed_index(tmp_path, {"s-1": "a common greeting", "s-2": "a farewell"})

    from api.services.search import lexical_search

    embedder = HashingEmbedder()
    # Query "你好" matches s-1 lexically (shared tokens 你, 好).
    lexical = lexical_search(str(tmp_path), "你好")
    semantic = semantic_search(
        str(tmp_path), "a common greeting", embedder=embedder
    )
    assert lexical  # s-1 is there
    assert semantic  # s-1 is there (perfect cosine on its own meaning)

    merged = merge_hits(lexical, semantic)
    # s-1 should appear at most once in the merge.
    s1_in_merge = [h for h in merged if h.unit_id == "s-1"]
    assert len(s1_in_merge) == 1
    # The merged entry has the higher of the two scores.
    assert s1_in_merge[0].score == max(
        h.score for h in lexical + semantic if h.unit_id == "s-1"
    )
