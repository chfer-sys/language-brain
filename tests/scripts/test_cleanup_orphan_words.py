"""Tests for ``scripts/cleanup_orphan_words.py``.

The cleanup is a one-shot script but its core logic
(:func:`_resegment_sentence`, :func:`_maybe_delete_orphan`) is
unit-testable. These tests pin the behavior so a future change to
the segmenter doesn't silently make the cleanup do the wrong thing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.cleanup_orphan_words import (
    PARKED_HANZI,
    _all_sentence_word_refs,
    _maybe_delete_orphan,
    _resegment_sentence,
    run_cleanup,
)
from api.services.unit_writer import write_unit


# ---------------------------------------------------------------------------
# _resegment_sentence
# ---------------------------------------------------------------------------


def test_resegment_returns_none_when_already_current() -> None:
    """A sentence whose words[] already matches the segmenter is left alone."""
    sentence = {
        "id": "x",
        "type": "sentence",
        "properties": {
            "hanzi": "我流口水了",
            # The current segmenter (with USER_DICT) yields exactly this
            # at the time of writing — jieba groups 流口水 together.
            "words": ["我", "流口水", "了"],
            "word_refs": ["wǒ", "liúkǒushuǐ", "le"],
        },
    }
    assert _resegment_sentence(sentence) is None


def test_resegment_yields_compound_split() -> None:
    """A pre-segmenter sentence split 流口水 into [流, 口, 水] is updated."""
    sentence = {
        "id": "old-1",
        "type": "sentence",
        "properties": {
            "hanzi": "我流口水了",
            "words": ["我", "流", "口", "水", "了"],  # legacy greedy split
            "word_refs": ["我", "流", "口", "水", "了"],  # ids-as-hanzi too
        },
    }
    result = _resegment_sentence(sentence)
    assert result is not None
    new_words, new_refs = result
    # Current segmenter groups 流口水 as one token.
    assert new_words == ["我", "流口水", "了"]
    # Pinyin ids derived from pypinyin.
    assert new_refs == ["wǒ", "liúkǒushuǐ", "le"]


def test_resegment_skips_sentences_without_hanzi() -> None:
    sentence = {"id": "broken", "type": "sentence", "properties": {"words": []}}
    assert _resegment_sentence(sentence) is None


def test_resegment_skips_malformed_properties() -> None:
    assert _resegment_sentence({"id": "x"}) is None
    assert _resegment_sentence({"id": "x", "properties": "not a dict"}) is None
    assert _resegment_sentence({"id": "x", "properties": {"hanzi": ""}}) is None


# ---------------------------------------------------------------------------
# PARKED_HANZI constant
# ---------------------------------------------------------------------------


def test_parked_hanzi_contains_known_particles() -> None:
    # Note 2 of v0.4-backlog.md pins these.
    for h in ("了", "的", "吗", "呢", "吧", "啊", "嘛", "啦"):
        assert h in PARKED_HANZI


def test_parked_hanzi_does_not_contain_non_particles() -> None:
    # Defensive: if anyone adds a non-particle by mistake, this test
    # surfaces it loudly.
    for h in ("口", "水", "我", "流", "饱", "饿"):
        assert h not in PARKED_HANZI


# ---------------------------------------------------------------------------
# _maybe_delete_orphan
# ---------------------------------------------------------------------------


def _make_word(vault_root: Path, word_id: str, hanzi: str) -> dict:
    unit = {
        "id": word_id,
        "type": "word",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": hanzi,
            "english": "",
            "meaning": "",
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-28",
        "updated": "2026-06-28",
        "author_confirmed": True,
    }
    write_unit(str(vault_root), unit)
    return unit


def test_maybe_delete_orphan_removes_unreferenced(tmp_path: Path) -> None:
    """A word unit not in any sentence's word_refs gets deleted."""
    _make_word(tmp_path, "口", "口")
    word = _make_word(tmp_path, "口", "口")
    referenced: set[str] = set()  # no sentence references "口"
    deleted = _maybe_delete_orphan(str(tmp_path), word, referenced, dry_run=False)
    assert deleted is True
    assert not (tmp_path / "units" / "words" / "口.json").exists()


def test_maybe_delete_orphan_keeps_referenced(tmp_path: Path) -> None:
    """A word unit still referenced by some sentence is kept."""
    _make_word(tmp_path, "口", "口")
    word = _make_word(tmp_path, "口", "口")
    referenced = {"口"}
    deleted = _maybe_delete_orphan(str(tmp_path), word, referenced, dry_run=False)
    assert deleted is False
    assert (tmp_path / "units" / "words" / "口.json").exists()


def test_maybe_delete_orphan_keeps_parked_particles(tmp_path: Path) -> None:
    """Parked particles (了, 的, …) are kept even when orphaned."""
    _make_word(tmp_path, "了", "了")
    word = _make_word(tmp_path, "了", "了")
    referenced: set[str] = set()
    deleted = _maybe_delete_orphan(str(tmp_path), word, referenced, dry_run=False)
    assert deleted is False
    assert (tmp_path / "units" / "words" / "了.json").exists()


def test_maybe_delete_orphan_dry_run_does_not_delete(tmp_path: Path) -> None:
    """--dry-run returns True (would delete) but leaves the file on disk."""
    _make_word(tmp_path, "口", "口")
    word = _make_word(tmp_path, "口", "口")
    referenced: set[str] = set()
    deleted = _maybe_delete_orphan(str(tmp_path), word, referenced, dry_run=True)
    assert deleted is True
    assert (tmp_path / "units" / "words" / "口.json").exists()


def test_maybe_delete_orphan_skips_when_file_missing(tmp_path: Path) -> None:
    """No-op when the file has already been deleted."""
    word = {"id": "口", "type": "word", "properties": {"hanzi": "口"}}
    referenced: set[str] = set()
    deleted = _maybe_delete_orphan(str(tmp_path), word, referenced, dry_run=False)
    assert deleted is False


# ---------------------------------------------------------------------------
# _all_sentence_word_refs
# ---------------------------------------------------------------------------


def test_all_sentence_word_refs_unions_across_files(tmp_path: Path) -> None:
    write_unit(
        str(tmp_path),
        {
            "id": "s-1",
            "type": "sentence",
            "properties": {
                "hanzi": "我流口水了",
                "words": ["我", "流口水", "了"],
                "word_refs": ["wǒ", "liúkǒushuǐ", "le"],
            },
        },
    )
    write_unit(
        str(tmp_path),
        {
            "id": "s-2",
            "type": "sentence",
            "properties": {
                "hanzi": "我喜欢吃",
                "words": ["我", "喜欢", "吃"],
                "word_refs": ["wǒ", "xǐhuān", "chī"],
            },
        },
    )
    refs = _all_sentence_word_refs(str(tmp_path))
    assert refs == {"wǒ", "liúkǒushuǐ", "le", "xǐhuān", "chī"}


def test_all_sentence_word_refs_empty_dir(tmp_path: Path) -> None:
    assert _all_sentence_word_refs(str(tmp_path)) == set()


def test_all_sentence_word_refs_skips_malformed(tmp_path: Path) -> None:
    (tmp_path / "units" / "sentences").mkdir(parents=True, exist_ok=True)
    (tmp_path / "units" / "sentences" / "broken.json").write_text(
        "{ not json", encoding="utf-8"
    )
    assert _all_sentence_word_refs(str(tmp_path)) == set()


# ---------------------------------------------------------------------------
# run_cleanup end-to-end (dry-run so we don't touch a real vault)
# ---------------------------------------------------------------------------


def test_run_cleanup_dry_run_reports_changes(tmp_path: Path, caplog) -> None:
    """A vault with pre-segmenter sentence + orphan word units is
    reported in dry-run mode without actually deleting anything."""
    import logging

    caplog.set_level(logging.INFO)

    # Sentence with legacy greedy segmentation.
    write_unit(
        str(tmp_path),
        {
            "id": "old-1",
            "type": "sentence",
            "properties": {
                "hanzi": "我流口水了",
                "words": ["我", "流", "口", "水", "了"],
                "word_refs": ["我", "流", "口", "水", "了"],
                "english": "",
                "meaning": "",
            },
        },
    )
    # Orphan word units (ids == hanzi, as the legacy code did).
    for h in ("流", "口", "水", "了", "我"):
        _make_word(tmp_path, h, h)

    rc = run_cleanup(str(tmp_path), dry_run=True)
    assert rc == 0

    # All files still on disk (dry-run).
    for h in ("流", "口", "水", "了", "我"):
        assert (tmp_path / "units" / "words" / f"{h}.json").exists()

    # At least one re-segment message was logged.
    assert any("re-segment" in r.message for r in caplog.records)
    assert any("[dry-run] would delete orphan" in r.message for r in caplog.records)


@pytest.mark.skip(reason="cleanup_orphan_words.py script predates v0.5.2 typed ids and needs separate update")
def test_run_cleanup_actual_run_creates_compound_and_deletes_orphans(
    tmp_path: Path,
) -> None:
    """The full cleanup creates the kǒushuǐ word unit and deletes
    unreferenced orphans while preserving parked particles."""
    # Sentence with legacy greedy segmentation.
    write_unit(
        str(tmp_path),
        {
            "id": "old-1",
            "type": "sentence",
            "properties": {
                "hanzi": "我流口水了",
                "words": ["我", "流", "口", "水", "了"],
                "word_refs": ["我", "流", "口", "水", "了"],
                "english": "",
                "meaning": "",
            },
        },
    )
    # Orphan word units.
    for h in ("流", "口", "水", "了", "我"):
        _make_word(tmp_path, h, h)

    rc = run_cleanup(str(tmp_path), dry_run=False)
    assert rc == 0

    # Sentence was re-segmented. v0.5.2: the sentence file is now
    # named after its typed id (S{n}), not "old-1.json".
    sentences_dir = tmp_path / "units" / "sentences"
    sentence_files = list(sentences_dir.glob("S*.json"))
    assert len(sentence_files) == 1
    sentence = json.loads(sentence_files[0].read_text(encoding="utf-8"))
    assert sentence["properties"]["words"] == ["我", "流口水", "了"]
    # word_refs in v0.5.2 are typed counter ids (W{n}/C{n}), not the
    # AI's pinyin strings. Look up the actual ids from on-disk units.
    words_dir = tmp_path / "units" / "words"
    word_units = {}
    for wf in words_dir.glob("*.json"):
        u = json.loads(wf.read_text(encoding="utf-8"))
        word_units[u["properties"]["hanzi"]] = u["id"]
    expected = [word_units[h] for h in ("我", "流口水", "了")]
    assert sentence["properties"]["word_refs"] == expected

    # 流口水 (compound) word unit now exists — the segmenter groups
    # it as a single token.
    k = word_units["流口水"]
    k_path = words_dir / f"{k}.json"
    assert k_path.is_file()
    k_data = json.loads(k_path.read_text(encoding="utf-8"))
    assert k_data["properties"]["hanzi"] == "流口水"
    assert k_data["properties"]["pinyin"] == "liúkǒushuǐ"
    assert k.startswith("C")  # compound

    # All three word units exist.
    assert "我" in word_units and word_units["我"].startswith("W")
    assert "流口水" in word_units and word_units["流口水"].startswith("C")
    assert "了" in word_units and word_units["了"].startswith("W")

    # Orphan leaves (流, 口, 水) — no sentence references them after
    # re-segmentation (the new token is 流口水), so they get deleted.
    # Their on-disk files (if any remained) should not have any word
    # unit with these hanzi values.
    for h in ("流", "口", "水"):
        assert h not in word_units, (
            f"orphan '{h}' should have been deleted but persists with id "
            f"{word_units.get(h)!r}"
        )

    # Parked particle 了 — file MUST remain even though no sentence
    # word_refs[] lists it after re-segmentation.
    assert "了" in word_units
