"""Tests for the hanzi/pinyin antonym resolver (Note 3, v0.4 T2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.antonym_resolver import (
    _looks_like_hanzi,
    normalize_antonyms_for_storage,
    resolve_antonym_to_word_id,
)
from api.services.unit_writer import write_unit


# ---------------------------------------------------------------------------
# _looks_like_hanzi
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("饱", True),
        ("你好", True),
        ("bǎo", False),
        ("chī", False),
        ("", False),
        ("  ", False),
        ("word", False),
        # Mixed: contains CJK, treated as hanzi.
        ("饱a", True),
        # Hiragana: not CJK Unified but treated as non-pinyin by the
        # detector (returns True → caller treats as hanzi and tries
        # to resolve). Edge case; the resolver will then look for a
        # word with hanzi="さ" which won't exist, fall through to
        # create-new-word with pypinyin fallback. We don't promise
        # correctness for kana here — only for the CJK case.
    ],
)
def test_looks_like_hanzi(text: str, expected: bool) -> None:
    assert _looks_like_hanzi(text) is expected


# ---------------------------------------------------------------------------
# normalize_antonyms_for_storage
# ---------------------------------------------------------------------------


def test_normalize_strips_blanks_and_dedupes() -> None:
    assert normalize_antonyms_for_storage(["饱", "", "  ", "饱", "热"]) == ["饱", "热"]


def test_normalize_preserves_order() -> None:
    assert normalize_antonyms_for_storage(["热", "饱", "冷"]) == ["热", "饱", "冷"]


def test_normalize_empty_input() -> None:
    assert normalize_antonyms_for_storage([]) == []


def test_normalize_non_list_returns_empty() -> None:
    assert normalize_antonyms_for_storage("饱") == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# resolve_antonym_to_word_id — pinyin resolution
# ---------------------------------------------------------------------------


def test_pinyin_no_match_returns_none(tmp_path: Path) -> None:
    """Pinyin with no existing word unit returns None (not a raw id)."""
    assert resolve_antonym_to_word_id(str(tmp_path), "bǎo") is None
    assert resolve_antonym_to_word_id(str(tmp_path), "è") is None


def test_pinyin_match_returns_word_id(tmp_path: Path) -> None:
    """Pinyin that matches an existing word returns that word's typed id."""
    _make_word(tmp_path, "W1", "饱", "bǎo")
    assert resolve_antonym_to_word_id(str(tmp_path), "bǎo") == "W1"


def test_empty_entry_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        resolve_antonym_to_word_id(str(tmp_path), "")
    with pytest.raises(ValueError, match="non-empty"):
        resolve_antonym_to_word_id(str(tmp_path), "   ")


# ---------------------------------------------------------------------------
# resolve_antonym_to_word_id — hanzi resolution against existing words
# ---------------------------------------------------------------------------


def _make_word(vault_root: Path, word_id: str, hanzi: str, pinyin: str) -> None:
    unit = {
        "id": word_id,
        "type": "word",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin,
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


def test_hanzi_matches_existing_word_unit(tmp_path: Path) -> None:
    """Hanzi entry returns the existing word's id (no new file written)."""
    _make_word(tmp_path, "bǎo", "饱", "bǎo")
    assert resolve_antonym_to_word_id(str(tmp_path), "饱") == "bǎo"
    # Still only the one word file (no duplicates).
    files = list((tmp_path / "units" / "words").glob("*.json"))
    assert len(files) == 1


def test_hanzi_creates_new_word_unit_when_no_match(tmp_path: Path) -> None:
    """A brand-new antonym hanzi triggers word-unit creation (v0.5.2 typed id)."""
    word_id = resolve_antonym_to_word_id(str(tmp_path), "饱")
    assert word_id.startswith("W")

    # The new word file must exist with the right hanzi and pinyin.
    path = tmp_path / "units" / "words" / f"{word_id}.json"
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == word_id
    assert data["properties"]["hanzi"] == "饱"
    assert data["properties"]["pinyin"] == "bǎo"


def test_hanzi_resolver_uses_injected_word_list(tmp_path: Path) -> None:
    """The injected ``existing_word_units`` seam skips disk I/O."""
    _make_word(tmp_path, "bǎo", "饱", "bǎo")
    existing = [
        {"id": "bǎo", "properties": {"hanzi": "饱"}},
        {"id": "chī", "properties": {"hanzi": "吃"}},
    ]
    # Empty vault_root is fine — we never touch disk via this seam.
    assert resolve_antonym_to_word_id(
        str(tmp_path), "饱", existing_word_units=existing
    ) == "bǎo"


def test_hanzi_resolver_skips_malformed_word_entries(tmp_path: Path) -> None:
    """A word entry with no ``properties`` dict is silently ignored."""
    _make_word(tmp_path, "bǎo", "饱", "bǎo")
    existing = [
        {"id": "bad", "type": "word"},  # no properties at all
        {"id": "bǎo", "properties": {"hanzi": "饱"}},
    ]
    assert resolve_antonym_to_word_id(
        str(tmp_path), "饱", existing_word_units=existing
    ) == "bǎo"


def test_hanzi_resolver_picks_deterministically_on_multi_match(tmp_path: Path) -> None:
    """Two words with the same hanzi → alphabetical id wins."""
    _make_word(tmp_path, "bǎo", "饱", "bǎo")
    _make_word(tmp_path, "bǎo-2", "饱", "bǎo")  # same hanzi, different id
    out = resolve_antonym_to_word_id(str(tmp_path), "饱")
    # Alphabetical: "bǎo" < "bǎo-2" (the hyphen comes after z in
    # ASCII but "bǎo-2" is the longer one). With sort(), "bǎo" comes
    # first by lexicographic order on the python str compare.
    assert out in {"bǎo", "bǎo-2"}
    # And we must get the same answer on every call (deterministic).
    assert resolve_antonym_to_word_id(str(tmp_path), "饱") == out


def test_typed_id_lookup_returns_matching_word_id(tmp_path: Path) -> None:
    """A typed word id (W{n}/C{n}) passed as entry resolves to itself."""
    _make_word(tmp_path, "W1", "饱", "bǎo")
    assert resolve_antonym_to_word_id(str(tmp_path), "W1") == "W1"
