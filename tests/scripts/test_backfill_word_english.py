"""Tests for scripts/backfill_word_english.py (v0.4.1 T2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.backfill_word_english import (
    PARKED_HANZI,
    _collect_sentence_englishes,
    _pick_representative,
    run_backfill,
)
from api.services.unit_writer import write_unit


# ---------------------------------------------------------------------------
# PARKED_HANZI
# ---------------------------------------------------------------------------


def test_parked_hanzi_matches_orphan_cleanup() -> None:
    # Same set as scripts/cleanup_orphan_words.py.
    for h in ("了", "的", "吗", "呢", "吧", "啊", "嘛", "啦"):
        assert h in PARKED_HANZI


# ---------------------------------------------------------------------------
# _collect_sentence_englishes
# ---------------------------------------------------------------------------


def _seed_sentence(
    vault_root: Path,
    sid: str,
    word_refs: list[str],
    english: str = "",
) -> None:
    write_unit(
        str(vault_root),
        {
            "id": sid,
            "type": "sentence",
            "properties": {
                "hanzi": "测试",
                "word_refs": word_refs,
                "english": english,
                "meaning": "",
            },
        },
    )


def _seed_word(
    vault_root: Path,
    pinyin: str,
    hanzi: str,
    english: str = "",
) -> None:
    write_unit(
        str(vault_root),
        {
            "id": pinyin,
            "type": "word",
            "name": hanzi,
            "properties": {
                "hanzi": hanzi,
                "pinyin": pinyin,
                "english": english,
                "meaning": "",
                "groups": [],
                "antonyms": [],
            },
        },
    )


def test_collect_returns_englishes_for_word_refs(tmp_path: Path) -> None:
    _seed_sentence(tmp_path, "s-1", ["chī", "fàn"], english="eat")
    _seed_sentence(tmp_path, "s-2", ["chī"], english="to eat")
    _seed_sentence(tmp_path, "s-3", ["chī"], english="")  # empty → ignored

    englishes = _collect_sentence_englishes(str(tmp_path), "chī")
    assert sorted(englishes) == ["eat", "to eat"]


def test_collect_returns_empty_when_no_sentence_refs_word(tmp_path: Path) -> None:
    _seed_sentence(tmp_path, "s-1", ["hé"], english="drink")
    englishes = _collect_sentence_englishes(str(tmp_path), "chī")
    assert englishes == []


def test_collect_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    # No sentences dir created at all.
    englishes = _collect_sentence_englishes(str(tmp_path), "chī")
    assert englishes == []


def test_collect_skips_malformed_files(tmp_path: Path) -> None:
    (tmp_path / "units" / "sentences").mkdir(parents=True, exist_ok=True)
    (tmp_path / "units" / "sentences" / "broken.json").write_text(
        "{ not json", encoding="utf-8"
    )
    _seed_sentence(tmp_path, "s-1", ["chī"], english="eat")
    englishes = _collect_sentence_englishes(str(tmp_path), "chī")
    assert englishes == ["eat"]


# ---------------------------------------------------------------------------
# _pick_representative
# ---------------------------------------------------------------------------


def test_pick_picks_shortest() -> None:
    assert _pick_representative(["a very long english gloss", "eat"]) == "eat"


def test_pick_empty_returns_none() -> None:
    assert _pick_representative([]) is None
    assert _pick_representative(["", "  "]) is None


def test_pick_filters_non_strings() -> None:
    # Defensive — the function should ignore non-string entries.
    assert _pick_representative(["eat", None, 123, ""]) == "eat"  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# run_backfill end-to-end
# ---------------------------------------------------------------------------


def test_run_backfill_dry_run_reports_without_writing(tmp_path: Path) -> None:
    _seed_word(tmp_path, "chī", "吃", english="")
    _seed_sentence(tmp_path, "s-1", ["chī"], english="eat")

    rc = run_backfill(str(tmp_path), dry_run=True)
    assert rc == 0

    # File untouched.
    from api.services.unit_writer import read_unit

    w = read_unit(str(tmp_path), "word", "chī")
    assert w["properties"]["english"] == ""


def test_run_backfill_fills_empty_word_with_shortest_context(
    tmp_path: Path,
) -> None:
    _seed_word(tmp_path, "chī", "吃", english="")
    _seed_sentence(tmp_path, "s-1", ["chī"], english="I want to eat")
    _seed_sentence(tmp_path, "s-2", ["chī"], english="eat")  # shortest wins

    rc = run_backfill(str(tmp_path), dry_run=False)
    assert rc == 0

    from api.services.unit_writer import read_unit

    w = read_unit(str(tmp_path), "word", "chī")
    assert w["properties"]["english"] == "eat"


def test_run_backfill_does_not_overwrite_existing(tmp_path: Path) -> None:
    _seed_word(tmp_path, "chī", "吃", english="user-edited")
    _seed_sentence(tmp_path, "s-1", ["chī"], english="eat")

    rc = run_backfill(str(tmp_path), dry_run=False)
    assert rc == 0

    from api.services.unit_writer import read_unit

    w = read_unit(str(tmp_path), "word", "chī")
    assert w["properties"]["english"] == "user-edited"


def test_run_backfill_skips_parked_particles(tmp_path: Path) -> None:
    _seed_word(tmp_path, "le", "了", english="")
    _seed_sentence(tmp_path, "s-1", ["le"], english="")

    rc = run_backfill(str(tmp_path), dry_run=False)
    assert rc == 0

    from api.services.unit_writer import read_unit

    w = read_unit(str(tmp_path), "word", "le")
    # No context for 了 AND it's parked → untouched.
    assert w["properties"]["english"] == ""


def test_run_backfill_leaves_word_alone_when_no_context(tmp_path: Path) -> None:
    """A word unit with no sentence context (or all-empty english)
    is not backfilled — we don't fabricate a value."""
    _seed_word(tmp_path, "hé", "喝", english="")
    _seed_sentence(tmp_path, "s-1", ["hé"], english="")

    rc = run_backfill(str(tmp_path), dry_run=False)
    assert rc == 0

    from api.services.unit_writer import read_unit

    w = read_unit(str(tmp_path), "word", "hé")
    assert w["properties"]["english"] == ""


def test_run_backfill_idempotent(tmp_path: Path) -> None:
    """A second run is a no-op — all slots are filled or skipped."""
    _seed_word(tmp_path, "chī", "吃", english="")
    _seed_sentence(tmp_path, "s-1", ["chī"], english="eat")

    assert run_backfill(str(tmp_path), dry_run=False) == 0
    assert run_backfill(str(tmp_path), dry_run=False) == 0  # second run

    from api.services.unit_writer import read_unit

    w = read_unit(str(tmp_path), "word", "chī")
    assert w["properties"]["english"] == "eat"


def test_run_backfill_handles_mixed_vault(tmp_path: Path) -> None:
    """Three words: one already filled (no-op), one empty with
    context (filled), one empty parked particle (no-op)."""
    _seed_word(tmp_path, "already", "已", english="already set")
    _seed_word(tmp_path, "chī", "吃", english="")
    _seed_word(tmp_path, "le", "了", english="")

    _seed_sentence(tmp_path, "s-1", ["already", "chī"], english="eat already")
    _seed_sentence(tmp_path, "s-2", ["chī", "le"], english="ate")

    rc = run_backfill(str(tmp_path), dry_run=False)
    assert rc == 0

    from api.services.unit_writer import read_unit

    assert read_unit(str(tmp_path), "word", "already")["properties"]["english"] == "already set"
    # "ate" (3 chars) wins over "eat already" (11 chars) — shortest wins.
    assert read_unit(str(tmp_path), "word", "chī")["properties"]["english"] == "ate"
    assert read_unit(str(tmp_path), "word", "le")["properties"]["english"] == ""