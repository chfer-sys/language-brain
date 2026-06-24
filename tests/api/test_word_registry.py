"""Tests for api.services.word_registry (SPEC §6 AC2).

Each test uses pytest's ``tmp_path`` fixture for full filesystem
isolation — we never read or set ``LANGUAGE_BRAIN_VAULT`` here; the
tmp path is passed straight through as ``vault_root``.

These tests cover AC2 (a new word not seen before is auto-created
under ``vault/units/words/<pinyin>.json`` when its first containing
sentence is saved) and the OQ2 invariant (pinyin-with-tones is the
word id; tone-marked and tone-stripped forms are distinct files).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.unit_writer import read_unit
from api.services.word_registry import ensure_word_unit, list_all_words


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _words_dir(vault_root: str | Path) -> Path:
    return Path(vault_root) / "units" / "words"


# ---------------------------------------------------------------------------
# AC2: word unit auto-created on first sentence save
# ---------------------------------------------------------------------------


def test_ensure_word_creates_when_absent(tmp_path: Path) -> None:
    """A new hanzi/pinyin pair produces a file at
    ``<vault>/units/words/chī.json`` with the correct shape."""
    vault = str(tmp_path)
    result = ensure_word_unit(vault, hanzi="吃", pinyin="chī")

    # File exists at the canonical path.
    word_path = _words_dir(vault) / "chī.json"
    assert word_path.is_file(), f"expected word file at {word_path}"

    # Returned dict matches the SPEC §2.2 word shape.
    assert result["id"] == "chī"
    assert result["name"] == "吃"
    assert result["type"] == "word"
    assert result["properties"]["hanzi"] == "吃"
    assert result["properties"]["pinyin"] == "chī"

    # AC2's invariant: the id is the tone-marked pinyin verbatim.
    assert result["id"] == "chī"


def test_ensure_word_idempotent(tmp_path: Path) -> None:
    """Calling ``ensure_word_unit`` twice with the same args is a no-op
    on the second call. The file is not overwritten — the existing
    dict is returned unchanged."""
    vault = str(tmp_path)
    first = ensure_word_unit(vault, hanzi="吃", pinyin="chī")
    word_path = _words_dir(vault) / "chī.json"
    mtime_after_first = word_path.stat().st_mtime_ns
    content_after_first = word_path.read_bytes()

    second = ensure_word_unit(vault, hanzi="吃", pinyin="chī")

    # File is byte-equal (not re-written).
    assert word_path.read_bytes() == content_after_first
    # mtime is unchanged (or, on coarse-resolution filesystems, equal).
    assert word_path.stat().st_mtime_ns == mtime_after_first
    # Returned dicts are equal.
    assert first == second


def test_ensure_word_with_compound_pinyin(tmp_path: Path) -> None:
    """A jieba compound token (e.g. ``口水`` -> ``kǒushuǐ``) is one word
    unit, id = the compound pinyin verbatim, file at
    ``kǒushuǐ.json``. This is the OQ3 invariant: one word per
    contiguous jieba token."""
    vault = str(tmp_path)
    result = ensure_word_unit(vault, hanzi="口水", pinyin="kǒushuǐ")

    word_path = _words_dir(vault) / "kǒushuǐ.json"
    assert word_path.is_file(), f"expected word file at {word_path}"
    assert result["id"] == "kǒushuǐ"
    assert result["name"] == "口水"
    assert result["properties"]["hanzi"] == "口水"
    assert result["properties"]["pinyin"] == "kǒushuǐ"


def test_ensure_word_uses_pinyin_with_tones_as_id(tmp_path: Path) -> None:
    """OQ2 invariant: ``chi`` (tone-stripped) and ``chī`` (tone-marked)
    are DIFFERENT ids and produce DIFFERENT files. The function does
    not normalize or de-tonify the id."""
    vault = str(tmp_path)

    no_tone = ensure_word_unit(vault, hanzi="吃", pinyin="chi")
    with_tone = ensure_word_unit(vault, hanzi="吃", pinyin="chī")

    # Distinct ids.
    assert no_tone["id"] == "chi"
    assert with_tone["id"] == "chī"
    assert no_tone["id"] != with_tone["id"]

    # Distinct files.
    assert (_words_dir(vault) / "chi.json").is_file()
    assert (_words_dir(vault) / "chī.json").is_file()
    assert no_tone is not with_tone


# ---------------------------------------------------------------------------
# list_all_words
# ---------------------------------------------------------------------------


def test_list_all_words_empty_vault(tmp_path: Path) -> None:
    """An empty vault (no ``units/words/`` directory) returns ``[]``."""
    assert list_all_words(str(tmp_path)) == []


def test_list_all_words_after_creates(tmp_path: Path) -> None:
    """After creating three distinct words, ``list_all_words`` returns
    all three dicts, each with the right id."""
    vault = str(tmp_path)
    ensure_word_unit(vault, hanzi="吃", pinyin="chī")
    ensure_word_unit(vault, hanzi="口水", pinyin="kǒushuǐ")
    ensure_word_unit(vault, hanzi="我", pinyin="wǒ")

    words = list_all_words(vault)
    ids = {w["id"] for w in words}
    assert ids == {"chī", "kǒushuǐ", "wǒ"}
    assert len(words) == 3


# ---------------------------------------------------------------------------
# Default values for english/meaning
# ---------------------------------------------------------------------------


def test_ensure_word_english_and_meaning_default_empty(tmp_path: Path) -> None:
    """If ``english``/``meaning`` are not passed, the stored
    ``properties.english`` and ``properties.meaning`` are empty strings,
    not ``None`` and not missing keys."""
    vault = str(tmp_path)
    result = ensure_word_unit(vault, hanzi="吃", pinyin="chī")

    assert "english" in result["properties"]
    assert "meaning" in result["properties"]
    assert result["properties"]["english"] == ""
    assert result["properties"]["meaning"] == ""


def test_ensure_word_english_and_meaning_stored(tmp_path: Path) -> None:
    """If ``english``/``meaning`` are passed, they are stored verbatim
    on the new word unit."""
    vault = str(tmp_path)
    result = ensure_word_unit(
        vault,
        hanzi="吃",
        pinyin="chī",
        english="to eat",
        meaning="the act of eating, consuming food",
    )
    assert result["properties"]["english"] == "to eat"
    assert result["properties"]["meaning"] == "the act of eating, consuming food"

    # And the on-disk file reflects the same values (round-trip via
    # the unit_writer, not via the in-memory dict).
    on_disk = read_unit(vault, "word", "chī")
    assert on_disk["properties"]["english"] == "to eat"
    assert on_disk["properties"]["meaning"] == "the act of eating, consuming food"


# ---------------------------------------------------------------------------
# AC2 / AC3 boundary: connections start empty (AC3 fills them)
# ---------------------------------------------------------------------------


def test_word_unit_connections_is_empty_list(tmp_path: Path) -> None:
    """AC2 creates a word with ``connections: []``. The lexical edge
    that AC3 requires is the responsibility of a separate task; here
    we just assert the invariant that AC2 does NOT pre-populate any
    connections."""
    vault = str(tmp_path)
    result = ensure_word_unit(vault, hanzi="吃", pinyin="chī")
    assert result["connections"] == []


# ---------------------------------------------------------------------------
# SPEC §2.2 structural invariants on a fresh word
# ---------------------------------------------------------------------------


def test_fresh_word_has_required_top_level_fields(tmp_path: Path) -> None:
    """A freshly-created word has every field required by SPEC §2.2
    plus the two spec-mandated arrays in properties: ``groups`` and
    ``antonyms``. ``created`` and ``updated`` are set to today's date
    and ``author_confirmed`` is True."""
    vault = str(tmp_path)
    result = ensure_word_unit(vault, hanzi="吃", pinyin="chī")

    assert result["id"] == "chī"
    assert result["type"] == "word"
    assert result["name"] == "吃"
    assert result["properties"]["groups"] == []
    assert result["properties"]["antonyms"] == []
    assert result["connections"] == []
    assert result["author_confirmed"] is True
    # created/updated are present and ISO-date-shaped (YYYY-MM-DD).
    assert isinstance(result["created"], str) and len(result["created"]) == 10
    assert isinstance(result["updated"], str) and len(result["updated"]) == 10


def test_fresh_word_persisted_file_is_valid_json(tmp_path: Path) -> None:
    """The on-disk file is valid JSON and matches the returned dict
    (modulo any timestamp drift between in-memory write and re-read)."""
    vault = str(tmp_path)
    ensure_word_unit(vault, hanzi="吃", pinyin="chī")

    raw = (_words_dir(vault) / "chī.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["id"] == "chī"
    assert parsed["type"] == "word"
    assert parsed["name"] == "吃"
    assert parsed["properties"]["hanzi"] == "吃"
    assert parsed["properties"]["pinyin"] == "chī"
