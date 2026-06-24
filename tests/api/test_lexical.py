"""Tests for :mod:`api.services.lexical`.

Covers SPEC §6 AC3 (word's connections list is updated with a
``lexical`` edge to a newly-saved sentence that contains it),
plus the supporting pure functions :func:`tokenize_sentence` and
:func:`jaccard` that AC12 (sentence↔sentence lexical) and future
Jaccard-based scoring tasks will reuse.

All tests use ``tmp_path`` for vault isolation; no test mutates the
real vault.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.lexical import (
    add_lexical_edge_to_word,
    jaccard,
    tokenize_sentence,
)
from api.services.word_registry import ensure_word_unit


# ---------------------------------------------------------------------------
# tokenize_sentence
# ---------------------------------------------------------------------------


def test_tokenize_dedup_preserves_order() -> None:
    """Single-character tokenization, with first-occurrence dedup.

    Input ``"我流口水了"`` → ``["我", "流", "口", "水", "了"]``.
    No duplicates in this input, so the result equals the input
    characters verbatim. The contract — dedup while preserving
    first-occurrence order — is exercised by adding a duplicate
    in :func:`test_tokenize_dedup_with_duplicates`.
    """
    assert tokenize_sentence("我流口水了") == ["我", "流", "口", "水", "了"]


def test_tokenize_dedup_with_duplicates() -> None:
    """A repeated character only appears once, at first-occurrence."""
    # 我 appears three times; 流 once. Order: 我, 流, 我, 我 → 我, 流.
    assert tokenize_sentence("我流我我") == ["我", "流"]


def test_tokenize_empty_string() -> None:
    """Empty input → empty list (not None, not a string)."""
    assert tokenize_sentence("") == []


def test_tokenize_whitespace_only() -> None:
    """Whitespace-only input → empty list (whitespace is not a hanzi token)."""
    assert tokenize_sentence("   \t\n") == []


def test_tokenize_skips_whitespace() -> None:
    """Intervening whitespace is dropped; tokens are still single chars."""
    assert tokenize_sentence("我 流 口 水") == ["我", "流", "口", "水"]


def test_tokenize_returns_fresh_list() -> None:
    """The returned list is a fresh object; mutating it does not affect
    a second call."""
    first = tokenize_sentence("我流")
    first.append("zzz")
    second = tokenize_sentence("我流")
    assert second == ["我", "流"]


def test_tokenize_rejects_non_string() -> None:
    """Non-string input raises :class:`ValueError`."""
    with pytest.raises(ValueError):
        tokenize_sentence(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# jaccard
# ---------------------------------------------------------------------------


def test_jaccard_identical() -> None:
    """Identical token sets → 1.0."""
    assert jaccard(["a", "b"], ["a", "b"]) == 1.0


def test_jaccard_identical_different_order() -> None:
    """Order is irrelevant — Jaccard is a set similarity."""
    assert jaccard(["a", "b", "c"], ["c", "b", "a"]) == 1.0


def test_jaccard_disjoint() -> None:
    """No shared tokens → 0.0."""
    assert jaccard(["a", "b"], ["c", "d"]) == 0.0


def test_jaccard_partial() -> None:
    """Partial overlap → ``|intersection| / |union|``.

    ``jaccard(["a","b","c"], ["b","c","d"])``:
        intersection = {b, c} → 2
        union        = {a, b, c, d} → 4
        score        = 2 / 4 = 0.5
    """
    assert jaccard(["a", "b", "c"], ["b", "c", "d"]) == 0.5


def test_jaccard_partial_hanzi() -> None:
    """Sanity-check with hanzi tokens (mirrors the real use case)."""
    # 我流口水 vs 口水流 → both tokenize to {我, 流, 口, 水} → identical
    assert jaccard(["我", "流", "口", "水"], ["口", "水", "流", "我"]) == 1.0
    # 我流口水 vs 你喝水 → intersection {水} (1) / union {我, 流, 口, 水, 你, 喝} (6) → 1/6
    assert jaccard(["我", "流", "口", "水"], ["你", "喝", "水"]) == pytest.approx(1 / 6)


def test_jaccard_empty_left() -> None:
    """Empty left list → 0.0 (not NaN, not ZeroDivisionError)."""
    assert jaccard([], ["a"]) == 0.0


def test_jaccard_empty_right() -> None:
    """Empty right list → 0.0."""
    assert jaccard(["a"], []) == 0.0


def test_jaccard_both_empty() -> None:
    """Both lists empty → 0.0."""
    assert jaccard([], []) == 0.0


def test_jaccard_duplicates_in_list_ignored() -> None:
    """Duplicates inside a single input list do not inflate the score.

    ``["a","a","b"]`` and ``["a","b"]`` have the same token SET
    ``{a, b}``, so Jaccard is 1.0. This documents that the function
    treats inputs as multisets-as-sets.
    """
    assert jaccard(["a", "a", "b"], ["a", "b"]) == 1.0


# ---------------------------------------------------------------------------
# add_lexical_edge_to_word — AC3
# ---------------------------------------------------------------------------


def test_add_lexical_edge_creates_connection(tmp_path: Path) -> None:
    """Pre-seed a word unit, add a lexical edge, assert the connection
    appears with the expected shape (``to``, ``kind``, ``score``)."""
    vault_root = str(tmp_path)
    word = ensure_word_unit(vault_root, hanzi="我", pinyin="wǒ")

    updated = add_lexical_edge_to_word(
        vault_root, word_id="wǒ", sentence_id="2026-06-24-001"
    )

    connections = updated["connections"]
    assert len(connections) == 1
    edge = connections[0]
    assert edge == {
        "to": "2026-06-24-001",
        "kind": "lexical",
        "score": 1.0,
    }


def test_add_lexical_edge_preserves_other_edges(tmp_path: Path) -> None:
    """A pre-existing ``group`` connection survives a lexical edge add."""
    vault_root = str(tmp_path)
    word = ensure_word_unit(vault_root, hanzi="吃", pinyin="chī")

    # Seed a non-lexical edge by mutating the in-memory dict and
    # writing it back via unit_writer. Using word_registry's
    # ensure_word_unit alone gives us an empty connections list.
    from api.services.unit_writer import write_unit

    word["connections"] = [{"to": "basic-verbs", "kind": "group", "score": 1.0}]
    write_unit(vault_root, word)

    updated = add_lexical_edge_to_word(
        vault_root, word_id="chī", sentence_id="2026-06-24-001"
    )

    connections = updated["connections"]
    kinds = sorted(edge["kind"] for edge in connections)
    assert kinds == ["group", "lexical"]

    # And specifically: the group edge is unchanged.
    group_edges = [e for e in connections if e["kind"] == "group"]
    assert group_edges == [{"to": "basic-verbs", "kind": "group", "score": 1.0}]


def test_add_lexical_edge_idempotent(tmp_path: Path) -> None:
    """Adding the same lexical edge twice → exactly one entry."""
    vault_root = str(tmp_path)
    ensure_word_unit(vault_root, hanzi="我", pinyin="wǒ")

    add_lexical_edge_to_word(vault_root, word_id="wǒ", sentence_id="S1")
    updated = add_lexical_edge_to_word(vault_root, word_id="wǒ", sentence_id="S1")

    lexical_edges = [
        e for e in updated["connections"] if e.get("kind") == "lexical"
    ]
    assert len(lexical_edges) == 1
    assert lexical_edges[0]["to"] == "S1"


def test_add_lexical_edge_updates_score(tmp_path: Path) -> None:
    """Re-adding with a different score overwrites the existing edge's
    score in place. There is still exactly one entry."""
    vault_root = str(tmp_path)
    ensure_word_unit(vault_root, hanzi="我", pinyin="wǒ")

    add_lexical_edge_to_word(vault_root, word_id="wǒ", sentence_id="S1", score=0.5)
    updated = add_lexical_edge_to_word(
        vault_root, word_id="wǒ", sentence_id="S1", score=0.9
    )

    lexical_edges = [
        e for e in updated["connections"] if e.get("kind") == "lexical"
    ]
    assert len(lexical_edges) == 1
    assert lexical_edges[0]["score"] == 0.9


def test_added_edge_visible_on_disk(tmp_path: Path) -> None:
    """The edge is persisted to disk, not just returned in memory.

    We bypass the helper and re-read the JSON file directly to prove
    the write reached the filesystem.
    """
    vault_root = str(tmp_path)
    ensure_word_unit(vault_root, hanzi="我", pinyin="wǒ")

    add_lexical_edge_to_word(
        vault_root, word_id="wǒ", sentence_id="2026-06-24-001"
    )

    on_disk_path = tmp_path / "units" / "words" / "wǒ.json"
    assert on_disk_path.is_file(), f"expected word file at {on_disk_path}"

    with open(on_disk_path, encoding="utf-8") as fh:
        raw = json.load(fh)

    assert raw["type"] == "word"
    assert raw["id"] == "wǒ"
    connections = raw["connections"]
    assert connections == [
        {"to": "2026-06-24-001", "kind": "lexical", "score": 1.0}
    ]


def test_add_lexical_edge_updates_timestamp(tmp_path: Path) -> None:
    """The ``updated`` field reflects the mutation."""
    vault_root = str(tmp_path)
    ensure_word_unit(vault_root, hanzi="我", pinyin="wǒ")

    updated = add_lexical_edge_to_word(vault_root, word_id="wǒ", sentence_id="S1")

    # ISO date format: YYYY-MM-DD. We don't assert on a specific date
    # (clock-dependent); we just assert the field is present and
    # well-formed.
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", updated["updated"])


def test_add_lexical_edge_multiple_distinct_sentences(tmp_path: Path) -> None:
    """Distinct sentence ids produce distinct edges."""
    vault_root = str(tmp_path)
    ensure_word_unit(vault_root, hanzi="我", pinyin="wǒ")

    add_lexical_edge_to_word(vault_root, word_id="wǒ", sentence_id="S1")
    add_lexical_edge_to_word(vault_root, word_id="wǒ", sentence_id="S2")

    from api.services.unit_writer import read_unit

    final = read_unit(vault_root, "word", "wǒ")
    lexical_targets = sorted(
        e["to"] for e in final["connections"] if e.get("kind") == "lexical"
    )
    assert lexical_targets == ["S1", "S2"]


def test_add_lexical_edge_preserves_position_of_existing(tmp_path: Path) -> None:
    """Updating an existing edge's score preserves its position in the
    list (so re-runs are idempotent at the byte level modulo timestamp)."""
    vault_root = str(tmp_path)
    ensure_word_unit(vault_root, hanzi="吃", pinyin="chī")

    from api.services.unit_writer import write_unit

    word = ensure_word_unit(vault_root, hanzi="吃", pinyin="chī")
    word["connections"] = [
        {"to": "basic-verbs", "kind": "group", "score": 1.0},
        {"to": "S1", "kind": "lexical", "score": 0.5},
        {"to": "饿", "kind": "opposite", "score": 1.0},
    ]
    write_unit(vault_root, word)

    updated = add_lexical_edge_to_word(
        vault_root, word_id="chī", sentence_id="S1", score=0.9
    )

    # The lexical edge should still be at index 1 (between group and
    # opposite), not moved to the end.
    assert updated["connections"][1] == {
        "to": "S1",
        "kind": "lexical",
        "score": 0.9,
    }
    # And the other two edges are untouched.
    assert updated["connections"][0]["kind"] == "group"
    assert updated["connections"][2]["kind"] == "opposite"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_add_lexical_edge_missing_word_raises(tmp_path: Path) -> None:
    """If the word unit file does not exist, :class:`FileNotFoundError`
    is raised — the caller is expected to have created the word first."""
    vault_root = str(tmp_path)
    with pytest.raises(FileNotFoundError):
        add_lexical_edge_to_word(
            vault_root, word_id="missing", sentence_id="S1"
        )


def test_add_lexical_edge_rejects_non_word_unit(tmp_path: Path) -> None:
    """If the file at ``word_id`` is not a word unit (e.g. a sentence
    file got mis-routed), the function raises rather than corrupting it."""
    vault_root = str(tmp_path)
    from pathlib import Path as _P

    # Plant a sentence unit file DIRECTLY under the words/ subdir,
    # bypassing unit_writer's type-based routing. This simulates a
    # caller passing a sentence id where a word id was expected.
    words_dir = _P(vault_root) / "units" / "words"
    words_dir.mkdir(parents=True, exist_ok=True)
    bogus_path = words_dir / "mistake.json"
    bogus_path.write_text(
        json.dumps(
            {
                "id": "mistake",
                "type": "sentence",  # wrong type for a file in words/
                "name": "x",
                "properties": {},
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

    with pytest.raises(ValueError):
        add_lexical_edge_to_word(
            vault_root, word_id="mistake", sentence_id="S1"
        )


def test_add_lexical_edge_rejects_empty_ids(tmp_path: Path) -> None:
    """Empty / non-string ids are rejected before any disk I/O."""
    vault_root = str(tmp_path)
    with pytest.raises(ValueError):
        add_lexical_edge_to_word(vault_root, word_id="", sentence_id="S1")
    with pytest.raises(ValueError):
        add_lexical_edge_to_word(vault_root, word_id="wǒ", sentence_id="")


def test_add_lexical_edge_rejects_non_numeric_score(tmp_path: Path) -> None:
    """Score must be a real number."""
    vault_root = str(tmp_path)
    ensure_word_unit(vault_root, hanzi="我", pinyin="wǒ")
    with pytest.raises(ValueError):
        add_lexical_edge_to_word(
            vault_root, word_id="wǒ", sentence_id="S1", score="high"  # type: ignore[arg-type]
        )
    # bool is a subclass of int and would silently sneak through
    # otherwise; reject it explicitly.
    with pytest.raises(ValueError):
        add_lexical_edge_to_word(
            vault_root, word_id="wǒ", sentence_id="S1", score=True  # type: ignore[arg-type]
        )
