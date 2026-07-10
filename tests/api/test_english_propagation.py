"""Tests for v0.4.1 T2 — English propagates from sentence to word on commit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.english_slice import (
    _STOPWORDS,
    _slice_sentence_english,
    _tokenize_english,
)
from api.services.word_registry import backfill_word_english, ensure_word_unit


# ---------------------------------------------------------------------------
# _tokenize_english
# ---------------------------------------------------------------------------


def test_tokenize_basic() -> None:
    assert _tokenize_english("I want to eat") == ["want", "eat"]


def test_tokenize_drops_stopwords() -> None:
    assert _tokenize_english("a the of and") == []


def test_tokenize_handles_apostrophes() -> None:
    assert _tokenize_english("I'm here") == ["i'm", "here"]


def test_tokenize_empty_returns_empty() -> None:
    assert _tokenize_english("") == []
    assert _tokenize_english("   ") == []


def test_tokenize_non_string_returns_empty() -> None:
    assert _tokenize_english(None) == []  # type: ignore[arg-type]
    assert _tokenize_english(123) == []  # type: ignore[arg-type]


def test_stopwords_set_is_minimal() -> None:
    # Defensive: any non-stopword in here would be a regression
    # (we don't want to filter "want" or "eat" out of user queries).
    for word in ("want", "eat", "drink", "good", "no", "yes", "not"):
        assert word not in _STOPWORDS


# ---------------------------------------------------------------------------
# _slice_sentence_english — happy path
# ---------------------------------------------------------------------------


def test_slice_length_mismatch_falls_back() -> None:
    """English "I want to eat" has 4 tokens vs 3 words → fallback (whole english for each)."""
    out = _slice_sentence_english(
        "I want to eat", ["我", "想", "吃"], ["wǒ", "xiǎng", "chī"]
    )
    # 4 tokens vs 3 words triggers the fallback path — the whole
    # english string is used as a noisy default for every slot.
    assert out == ["I want to eat", "I want to eat", "I want to eat"]


def test_slice_strips_stopwords_at_matching_positions() -> None:
    """When token count matches, stopwords at known positions produce empty slots."""
    # "I eat want" → 3 tokens, 3 words → positional, stopword "I" → ""
    out = _slice_sentence_english(
        "I eat want",
        ["我", "吃", "想"],
        ["wǒ", "chī", "xiǎng"],
    )
    assert out == ["", "eat", "want"]


def test_slice_lowercases_output() -> None:
    """The slice function lowercases English tokens for consistency."""
    out = _slice_sentence_english(
        "I Like Eat", ["我", "喜欢", "吃"], ["wǒ", "xǐhuān", "chī"]
    )
    assert out == ["", "like", "eat"]


def test_slice_two_words_one_meaning() -> None:
    """Long english vs short word list → fallback."""
    out = _slice_sentence_english(
        "I like to eat",
        ["我喜欢吃"],
        ["wǒ xǐhuān chī"],
    )
    # 4 tokens vs 1 word → fallback.
    assert len(out) == 1
    assert "like" in out[0]


def test_slice_with_exact_token_count() -> None:
    """Sentence "I eat" → 2 tokens → 2 words → positional mapping."""
    out = _slice_sentence_english(
        "I eat",
        ["我", "吃"],
        ["wǒ", "chī"],
    )
    assert out == ["", "eat"]


# ---------------------------------------------------------------------------
# _slice_sentence_english — fallback paths
# ---------------------------------------------------------------------------


def test_slice_empty_english_returns_empty_strings() -> None:
    out = _slice_sentence_english("", ["我", "吃"], ["wǒ", "chī"])
    assert out == ["", ""]


def test_slice_mismatch_falls_back_to_full_english() -> None:
    """Tokens > words → use whole english as default."""
    out = _slice_sentence_english(
        "I really really want to eat the food",
        ["我", "吃"],
        ["wǒ", "chī"],
    )
    # After stopword drop: [really, really, want, eat, food] = 5 tokens
    # vs 2 words → fallback.
    assert out == ["I really really want to eat the food",
                    "I really really want to eat the food"]


def test_slice_empty_words_returns_empty() -> None:
    assert _slice_sentence_english("hello", [], []) == []


def test_slice_no_english_no_propagation() -> None:
    out = _slice_sentence_english("", ["我", "吃"], ["wǒ", "chī"])
    # No english → no propagation (empty strings).
    assert out == ["", ""]


# ---------------------------------------------------------------------------
# backfill_word_english — on-disk behavior
# ---------------------------------------------------------------------------


def _seed_word(vault_root: Path, pinyin: str, hanzi: str, english: str = "") -> None:
    """Write a word unit file directly (bypassing ensure_word_unit)."""
    unit = {
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
        "connections": [],
        "created": "2026-06-29",
        "updated": "2026-06-29",
        "author_confirmed": True,
    }
    from api.services.unit_writer import write_unit

    write_unit(str(vault_root), unit)
    return unit


def test_backfill_fills_empty_slot(tmp_path: Path) -> None:
    _seed_word(tmp_path, "chī", "吃", english="")
    wrote = backfill_word_english(str(tmp_path), "chī", "eat")
    assert wrote is True

    from api.services.unit_writer import read_unit

    word = read_unit(str(tmp_path), "word", "chī")
    assert word["properties"]["english"] == "eat"


def test_backfill_does_not_overwrite_existing(tmp_path: Path) -> None:
    """Pre-populated english must NOT be replaced by the backfill."""
    _seed_word(tmp_path, "chī", "吃", english="user-edited")
    wrote = backfill_word_english(str(tmp_path), "chī", "AI guess")
    assert wrote is False

    from api.services.unit_writer import read_unit

    word = read_unit(str(tmp_path), "word", "chī")
    assert word["properties"]["english"] == "user-edited"


def test_backfill_no_op_when_word_missing(tmp_path: Path) -> None:
    """A non-existent word is silently skipped."""
    wrote = backfill_word_english(str(tmp_path), "missing", "anything")
    assert wrote is False


def test_backfill_no_op_when_english_empty(tmp_path: Path) -> None:
    """An empty english arg doesn't clobber an existing value."""
    _seed_word(tmp_path, "chī", "吃", english="existing")
    wrote = backfill_word_english(str(tmp_path), "chī", "")
    assert wrote is False

    from api.services.unit_writer import read_unit

    word = read_unit(str(tmp_path), "word", "chī")
    assert word["properties"]["english"] == "existing"


def test_backfill_strips_whitespace(tmp_path: Path) -> None:
    _seed_word(tmp_path, "chī", "吃", english="")
    wrote = backfill_word_english(str(tmp_path), "chī", "  eat  ")
    assert wrote is True
    from api.services.unit_writer import read_unit

    word = read_unit(str(tmp_path), "word", "chī")
    assert word["properties"]["english"] == "eat"


def test_backfill_rejects_blank_pinyin(tmp_path: Path) -> None:
    assert backfill_word_english(str(tmp_path), "", "x") is False
    assert backfill_word_english(str(tmp_path), "   ", "x") is False


# ---------------------------------------------------------------------------
# Integration: ensure_word_unit writes the english on creation
# ---------------------------------------------------------------------------


def test_ensure_word_unit_writes_english_on_create(tmp_path: Path) -> None:
    """ensure_word_unit persists the english argument when the file is new."""
    word = ensure_word_unit(str(tmp_path), hanzi="吃", pinyin="chī", english="eat")
    word_id = word["id"]
    from api.services.unit_writer import read_unit

    loaded = read_unit(str(tmp_path), "word", word_id)
    assert loaded["properties"]["english"] == "eat"


def test_ensure_word_unit_no_op_collision(tmp_path: Path) -> None:
    """A pre-existing word is NOT overwritten (existing contract)."""
    word = _seed_word(tmp_path, "chī", "吃", english="user-edited")
    ensure_word_unit(str(tmp_path), hanzi="吃", pinyin="chī", english="AI guess")
    from api.services.unit_writer import read_unit

    loaded = read_unit(str(tmp_path), "word", word["id"])
    assert loaded["properties"]["english"] == "user-edited"


# ---------------------------------------------------------------------------
# Integration: full POST /api/sentences/commit propagates english to words
# ---------------------------------------------------------------------------


def test_commit_propagates_english_to_word_units(tmp_path: Path) -> None:
    """End-to-end: committing a sentence populates word.english from the dict.

    Per SPEC §5.9, word english comes from the dict first. For words
    with no dict english, backfill_word_english supplies the sentence
    english as fallback.
    """
    import os

    os.environ["LANGUAGE_BRAIN_VAULT"] = str(tmp_path)
    from api import config as config_module
    from tests.api.conftest import _seed_dictionary

    config_module.get_settings.cache_clear()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(config_module.settings, "vault", str(tmp_path))

    # Seed the dictionary so commit uses Dictionary.segment().
    _seed_dictionary(str(tmp_path))

    try:
        from fastapi.testclient import TestClient

        from api.main import app

        client = TestClient(app)
        resp = client.post(
            "/api/sentences/commit",
            json={
                "id": "i-want-to-eat",
                "hanzi": "我想吃",
                "pinyin": "wǒ xiǎng chī",
                "english": "I want to eat",
                "meaning": "I want to eat",
                "words": ["我", "想", "吃"],
                "word_refs": ["wǒ", "xiǎng", "chī"],
                "groups": [],
                "antonyms": [],
                "author_confirmed": True,
            },
        )
        assert resp.status_code == 200, resp.text

        # Word units are created for all dict-known words.
        words_dir = tmp_path / "units" / "words"
        word_files = list(words_dir.glob("*.json"))
        assert len(word_files) >= 3, f"expected 3 word files, found {len(word_files)}"

        # Each word unit has non-empty english (dict english; backfill
        # fills in the sentence english only when dict english is absent).
        by_hanzi = {
            json.loads(p.read_text(encoding="utf-8"))["properties"]["hanzi"]: json.loads(p.read_text(encoding="utf-8"))
            for p in word_files
        }
        assert by_hanzi["我"]["properties"]["english"] == "I (pronoun)"
        assert by_hanzi["想"]["properties"]["english"] == "to think / to want / to miss"
        assert by_hanzi["吃"]["properties"]["english"] == "to eat"
    finally:
        monkey.undo()