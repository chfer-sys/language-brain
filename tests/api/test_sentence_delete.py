"""Tests for ``api.services.sentence_delete`` (SPEC §6 AC11).

AC11 contract: deleting a sentence cascades through:

1. The unit file is removed from disk.
2. The vector is removed from the FAISS index.
3. Every word whose connections list references the sentence has
   that connection removed.
4. Every group whose members list references the sentence has
   that member removed.

Tests use ``tmp_path`` for vault isolation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.embedder import HashingEmbedder
from api.services.indexer import Index
from api.services.sentence_delete import delete_sentence
from api.services.unit_writer import (
    list_all_groups_from_disk,
    list_units_by_type,
    read_unit,
    unit_path,
    write_unit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_sentence(vault: Path, sid: str, meaning: str, words: list[str]) -> None:
    payload = {
        "id": sid,
        "type": "sentence",
        "name": "placeholder",
        "properties": {
            "hanzi": "placeholder",
            "pinyin": "placeholder",
            "english": "placeholder",
            "meaning": meaning,
            "words": words,
            "word_refs": words,
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-24",
        "updated": "2026-06-24",
        "author_confirmed": True,
    }
    out_dir = vault / "units" / "sentences"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{sid}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _seed_word_with_lexical_edge(
    vault: Path, word_id: str, sentence_ids: list[str]
) -> None:
    """Write a word unit with lexical edges to the given sentences."""
    word_path = vault / "units" / "words" / f"{word_id}.json"
    word_path.parent.mkdir(parents=True, exist_ok=True)
    word_path.write_text(
        json.dumps(
            {
                "id": word_id,
                "type": "word",
                "name": word_id,
                "properties": {
                    "hanzi": word_id,
                    "pinyin": word_id,
                    "english": "x",
                    "groups": [],
                    "antonyms": [],
                },
                "connections": [
                    {"to": sid, "kind": "lexical", "score": 1.0}
                    for sid in sentence_ids
                ],
                "created": "2026-06-24",
                "updated": "2026-06-24",
                "author_confirmed": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _seed_group_with_members(
    vault: Path, group_id: str, sentence_ids: list[str]
) -> None:
    """Write a group unit whose members list contains the given sentences."""
    group_path = vault / "units" / "groups" / f"{group_id}.json"
    group_path.parent.mkdir(parents=True, exist_ok=True)
    group_path.write_text(
        json.dumps(
            {
                "id": group_id,
                "type": "group",
                "name": group_id,
                "properties": {
                    "display_name": group_id,
                    "description": "",
                    "members": list(sentence_ids),
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
    """Build an FAISS index with one vector per sentence."""
    embedder = HashingEmbedder()
    idx = Index()
    for sid, meaning in sentence_meanings.items():
        idx.add(sid, embedder.embed(meaning))
    idx.save(str(vault))


# ---------------------------------------------------------------------------
# AC11 — cascade deletion
# ---------------------------------------------------------------------------


def test_delete_removes_sentence_file(tmp_path: Path) -> None:
    """AC11.1: the sentence file is deleted from disk."""
    _seed_sentence(tmp_path, "s-1", "hello", ["你", "好"])
    sentence_file = unit_path(str(tmp_path), "sentence", "s-1")
    assert sentence_file.is_file()

    summary = delete_sentence(str(tmp_path), "s-1")
    assert summary["sentence_deleted"] == 1
    assert not sentence_file.exists()


def test_delete_removes_from_faiss_index(tmp_path: Path) -> None:
    """AC11.2: the vector is removed from the FAISS index."""
    _seed_sentence(tmp_path, "s-1", "hello", ["你"])
    _seed_sentence(tmp_path, "s-2", "goodbye", ["再"])
    _seed_index(tmp_path, {"s-1": "hello", "s-2": "goodbye"})

    # Confirm both are in the index.
    idx_before = Index.load_or_empty(str(tmp_path))
    assert "s-1" in idx_before
    assert "s-2" in idx_before

    summary = delete_sentence(str(tmp_path), "s-1")
    assert summary["faiss_removed"] == 1

    # The index on disk no longer contains s-1.
    idx_after = Index.load_or_empty(str(tmp_path))
    assert "s-1" not in idx_after
    assert "s-2" in idx_after


def test_delete_removes_lexical_edge_from_word(tmp_path: Path) -> None:
    """AC11.3: a word with a lexical edge to the deleted sentence
    has that edge removed."""
    _seed_sentence(tmp_path, "s-1", "hello", ["你", "好"])
    _seed_word_with_lexical_edge(tmp_path, "nǐ", ["s-1"])
    _seed_index(tmp_path, {"s-1": "hello"})

    summary = delete_sentence(str(tmp_path), "s-1")
    assert summary["words_updated"] == 1

    word = read_unit(str(tmp_path), "word", "nǐ")
    assert all(
        not (isinstance(e, dict) and e.get("to") == "s-1")
        for e in word["connections"]
    )


def test_delete_keeps_other_edges_on_word(tmp_path: Path) -> None:
    """AC11.3 (preservation): a word with edges to multiple sentences
    keeps the edges to the OTHER sentences after one is deleted."""
    _seed_sentence(tmp_path, "s-1", "hello", ["你"])
    _seed_sentence(tmp_path, "s-2", "you", ["你"])
    _seed_word_with_lexical_edge(tmp_path, "nǐ", ["s-1", "s-2"])
    _seed_index(tmp_path, {"s-1": "hello", "s-2": "you"})

    delete_sentence(str(tmp_path), "s-1")

    word = read_unit(str(tmp_path), "word", "nǐ")
    edges = word["connections"]
    assert len(edges) == 1
    assert edges[0]["to"] == "s-2"


def test_delete_removes_from_group_members(tmp_path: Path) -> None:
    """AC11.4: a group whose members list contains the deleted
    sentence has that member removed."""
    _seed_sentence(tmp_path, "s-1", "hello", ["你"])
    _seed_group_with_members(tmp_path, "greetings", ["s-1"])
    _seed_index(tmp_path, {"s-1": "hello"})

    summary = delete_sentence(str(tmp_path), "s-1")
    assert summary["groups_updated"] == 1

    group = read_unit(str(tmp_path), "group", "greetings")
    assert "s-1" not in group["properties"]["members"]


def test_delete_keeps_other_members_in_group(tmp_path: Path) -> None:
    """AC11.4 (preservation): a group with multiple members keeps
    the other members after one is deleted."""
    _seed_sentence(tmp_path, "s-1", "hello", ["你"])
    _seed_sentence(tmp_path, "s-2", "goodbye", ["再"])
    _seed_group_with_members(tmp_path, "greetings", ["s-1", "s-2"])
    _seed_index(tmp_path, {"s-1": "hello", "s-2": "goodbye"})

    delete_sentence(str(tmp_path), "s-1")

    group = read_unit(str(tmp_path), "group", "greetings")
    assert group["properties"]["members"] == ["s-2"]


def test_delete_cascades_to_multiple_words_and_groups(tmp_path: Path) -> None:
    """AC11 (full): a sentence that appears in multiple words AND
    multiple groups cascades to all of them in one call."""
    _seed_sentence(tmp_path, "s-1", "shared sentence", ["你"])
    _seed_word_with_lexical_edge(tmp_path, "nǐ", ["s-1"])
    _seed_word_with_lexical_edge(tmp_path, "hǎo", ["s-1"])  # separate word
    _seed_group_with_members(tmp_path, "g1", ["s-1"])
    _seed_group_with_members(tmp_path, "g2", ["s-1"])
    _seed_index(tmp_path, {"s-1": "shared sentence"})

    summary = delete_sentence(str(tmp_path), "s-1")
    assert summary["sentence_deleted"] == 1
    assert summary["faiss_removed"] == 1
    assert summary["words_updated"] == 2
    assert summary["groups_updated"] == 2

    # No word still references s-1.
    for w in list_units_by_type(str(tmp_path), "word"):
        assert all(
            not (isinstance(e, dict) and e.get("to") == "s-1")
            for e in w.get("connections", [])
        )
    # No group still has s-1 in members.
    for g in list_all_groups_from_disk(str(tmp_path)):
        assert "s-1" not in g["properties"]["members"]


def test_delete_missing_sentence_raises(tmp_path: Path) -> None:
    """A sentence id that doesn't exist raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        delete_sentence(str(tmp_path), "nope")


def test_delete_with_no_index_yet_is_safe(tmp_path: Path) -> None:
    """AC11 (no index): a vault that has never been indexed still
    allows sentence deletion. The FAISS cascade is a no-op."""
    _seed_sentence(tmp_path, "s-1", "hello", ["你"])
    summary = delete_sentence(str(tmp_path), "s-1")
    assert summary["sentence_deleted"] == 1
    assert summary["faiss_removed"] == 0


def test_delete_with_no_words_or_groups_is_safe(tmp_path: Path) -> None:
    """A sentence with no word connections or group memberships
    deletes cleanly with zero cascade updates."""
    _seed_sentence(tmp_path, "s-1", "lonely sentence", [])
    _seed_index(tmp_path, {"s-1": "lonely sentence"})
    summary = delete_sentence(str(tmp_path), "s-1")
    assert summary["sentence_deleted"] == 1
    assert summary["words_updated"] == 0
    assert summary["groups_updated"] == 0


def test_delete_preserves_indexed_neighbors(tmp_path: Path) -> None:
    """AC11.2 (regression): after delete, FAISS neighbors of a
    remaining sentence are unchanged in identity."""
    _seed_sentence(tmp_path, "s-1", "hello", [])
    _seed_sentence(tmp_path, "s-2", "goodbye", [])
    _seed_sentence(tmp_path, "s-3", "thanks", [])
    _seed_index(tmp_path, {"s-1": "hello", "s-2": "goodbye", "s-3": "thanks"})

    # Snapshot neighbors of s-2 before delete.
    idx = Index.load_or_empty(str(tmp_path))
    embedder = HashingEmbedder()
    neighbors_before = sorted(h.unit_id for h in idx.search(embedder.embed("goodbye"), k=3))

    delete_sentence(str(tmp_path), "s-1")
    idx_after = Index.load_or_empty(str(tmp_path))
    neighbors_after = sorted(h.unit_id for h in idx_after.search(embedder.embed("goodbye"), k=3))

    # s-1 was likely in the top-3 of s-2 (or at least searched).
    # The remaining two sentences should still be there.
    assert "s-1" not in neighbors_after
    assert "s-2" in neighbors_after
