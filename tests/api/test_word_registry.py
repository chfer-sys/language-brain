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
    ``<vault>/units/words/<W1>.json`` with the correct shape (v0.5.2)."""
    vault = str(tmp_path)
    result = ensure_word_unit(vault, hanzi="吃", pinyin="chī")

    # After v0.5.2 the id is a typed counter, not the pinyin.
    assert result["id"].startswith("W")
    word_path = _words_dir(vault) / f"{result['id']}.json"
    assert word_path.is_file(), f"expected word file at {word_path}"

    # Returned dict matches the SPEC §2.2 word shape.
    assert result["name"] == "吃"
    assert result["type"] == "word"
    assert result["properties"]["hanzi"] == "吃"
    assert result["properties"]["pinyin"] == "chī"


def test_ensure_word_idempotent(tmp_path: Path) -> None:
    """Calling ``ensure_word_unit`` twice with the same args is a no-op
    on the second call. The file is not overwritten — the existing
    dict is returned unchanged."""
    vault = str(tmp_path)
    first = ensure_word_unit(vault, hanzi="吃", pinyin="chī")
    word_path = _words_dir(vault) / f"{first['id']}.json"
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
    """A compound (multi-char hanzi) gets a typed C{n} id (v0.5.2)
    and ``type='compound'``."""
    vault = str(tmp_path)
    result = ensure_word_unit(vault, hanzi="口水", pinyin="kǒushuǐ")

    assert result["id"].startswith("C")
    word_path = _words_dir(vault) / f"{result['id']}.json"
    assert word_path.is_file(), f"expected word file at {word_path}"
    assert result["name"] == "口水"
    assert result["type"] == "compound"
    assert result["properties"]["hanzi"] == "口水"
    assert result["properties"]["pinyin"] == "kǒushuǐ"


def test_ensure_word_1hanzi_is_word_type(tmp_path: Path) -> None:
    """A 1-hanzi word gets ``type='word'`` (not 'compound')."""
    vault = str(tmp_path)
    result = ensure_word_unit(vault, hanzi="我", pinyin="wǒ")

    assert result["id"].startswith("W")
    assert result["type"] == "word"
    assert result["name"] == "我"


def test_ensure_word_distinguishes_pinyin_readings(tmp_path: Path) -> None:
    """``chi`` (tone-stripped) and ``chī`` (tone-marked) produce two
    separate word units with distinct typed ids (v0.5.2)."""
    vault = str(tmp_path)

    no_tone = ensure_word_unit(vault, hanzi="吃", pinyin="chi")
    with_tone = ensure_word_unit(vault, hanzi="吃", pinyin="chī")

    assert no_tone["id"] != with_tone["id"]
    assert no_tone["id"].startswith("W")
    assert with_tone["id"].startswith("W")

    # Both files exist.
    assert (_words_dir(vault) / f"{no_tone['id']}.json").is_file()
    assert (_words_dir(vault) / f"{with_tone['id']}.json").is_file()
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
    assert len(ids) == 3
    assert len(words) == 3
    # Each id is a typed counter; the compound kǒushuǐ starts with C.
    for w in words:
        assert w["id"].startswith(("W", "C"))


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
    on_disk = read_unit(vault, "word", result["id"])
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

    assert result["id"].startswith("W")
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

    # Find the actual file (id is a typed counter after v0.5.2)
    files = list(_words_dir(vault).glob("*.json"))
    assert len(files) == 1
    raw = files[0].read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["id"].startswith("W")
    assert parsed["type"] == "word"
    assert parsed["name"] == "吃"
    assert parsed["properties"]["hanzi"] == "吃"
    assert parsed["properties"]["pinyin"] == "chī"
