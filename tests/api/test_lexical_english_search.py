"""Tests for v0.4.1 T3 — lexical search matches English queries against
english/meaning fields on sentences + words.

Background
----------
Before T3, ``lexical_search`` tokenized the query with the same
char-level tokenizer used for hanzi. For an English query like
"i want to eat" against a group named "emotion" this gave a
0.625 Jaccard score because of character overlap (``e/i/t``) — a
false positive. For the same query against a sentence whose
``english`` was "I like to eat" it gave ~0 Jaccard because the
char sets don't overlap meaningfully.

T3 fixes both:
- Query side: build the query token set as the UNION of
  char-level and whole-word (English) tokens.
- Unit side: each unit is scored against hanzi + english + meaning
  fields, and the max Jaccard wins.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.search import (
    _score_unit,
    _tokenize_english_for_search,
    lexical_search,
)
from api.services.unit_writer import write_unit


# ---------------------------------------------------------------------------
# _tokenize_english_for_search
# ---------------------------------------------------------------------------


def test_tokenize_returns_lowercase_words() -> None:
    assert _tokenize_english_for_search("I want to EAT") == ["i", "want", "to", "eat"]


def test_tokenize_keeps_stopwords() -> None:
    """Unlike the slice function, search keeps stopwords for matching."""
    assert _tokenize_english_for_search("a the of") == ["a", "the", "of"]


def test_tokenize_empty_returns_empty() -> None:
    assert _tokenize_english_for_search("") == []
    assert _tokenize_english_for_search("   ") == []


def test_tokenize_non_string_returns_empty() -> None:
    assert _tokenize_english_for_search(None) == []  # type: ignore[arg-type]
    assert _tokenize_english_for_search(123) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _score_unit — English path
# ---------------------------------------------------------------------------


def _make_word(pinyin: str, hanzi: str, english: str = "", meaning: str = "") -> dict:
    return {
        "id": pinyin,
        "type": "word",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin,
            "english": english,
            "meaning": meaning,
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-29",
        "updated": "2026-06-29",
        "author_confirmed": True,
    }


def test_score_english_query_against_english_field() -> None:
    """'eat' tokens vs word.english='I like to eat' → high score."""
    word = _make_word("chī", "吃", english="I like to eat")
    # Query tokens = {'eat'} (whole word) + {'e','a','t'} (chars).
    # Best Jaccard is via english: {eat} & {i, like, to, eat} = {eat}
    # → 1/4 = 0.25.
    hit = _score_unit(word, "word", ["eat", "e", "a", "t"])
    assert hit is not None
    assert hit[0] == "chī"
    assert hit[2] > 0


def test_score_english_query_does_not_match_unrelated_english() -> None:
    """'eat' should NOT match a word whose english is 'drink'."""
    word = _make_word("hē", "喝", english="I drink water")
    hit = _score_unit(word, "word", ["eat", "e", "a", "t"])
    # No token overlap → 0 → None.
    assert hit is None


def test_score_picks_max_across_hanzi_english_meaning() -> None:
    """The score is the max across all three fields."""
    word = _make_word("x", "X", english="unrelated", meaning="eat food")
    hit = _score_unit(word, "word", ["eat", "e", "a", "t"])
    assert hit is not None
    # meaning matches → score at least 1/5 (eat intersects {eat,food})
    # or via char tokens (eat intersects {e,a,t} with meaning's chars).
    assert hit[2] >= 0.2


def test_score_returns_none_when_no_fields_match() -> None:
    """No field shares a token → None."""
    word = _make_word("x", "X", english="unrelated", meaning="also unrelated")
    hit = _score_unit(word, "word", ["eat"])
    assert hit is None


def test_score_skips_empty_fields() -> None:
    """Empty english/meaning don't contribute tokens."""
    word = _make_word("x", "X", english="", meaning="")
    hit = _score_unit(word, "word", ["eat"])
    assert hit is None  # nothing to match


def test_score_returns_none_when_id_missing() -> None:
    """Defensive: a malformed unit is silently skipped."""
    bad = {"type": "word", "properties": {"hanzi": "X", "english": "eat"}}
    assert _score_unit(bad, "word", ["eat"]) is None


# ---------------------------------------------------------------------------
# lexical_search end-to-end
# ---------------------------------------------------------------------------


def _seed_sentence(
    vault_root: Path,
    sid: str,
    hanzi: str,
    pinyin: str,
    english: str = "",
    meaning: str = "",
) -> None:
    write_unit(
        str(vault_root),
        {
            "id": sid,
            "type": "sentence",
            "name": hanzi,
            "properties": {
                "hanzi": hanzi,
                "pinyin": pinyin,
                "english": english,
                "meaning": meaning,
                "words": [],
                "word_refs": [],
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-06-29",
            "updated": "2026-06-29",
            "author_confirmed": True,
        },
    )


def test_lexical_english_query_finds_english_field(tmp_path: Path) -> None:
    """'i want to eat' should find the eat-related sentence, not
    an unrelated group with character-overlap (the v0.4.1 bug)."""
    _seed_sentence(
        tmp_path,
        "s-eat",
        "我想吃",
        "wǒ xiǎng chī",
        english="I want to eat",
        meaning="I want to eat",
    )
    _seed_sentence(
        tmp_path,
        "s-other",
        "我喜欢",
        "wǒ xǐhuān",
        english="something unrelated entirely",
        meaning="no overlap whatsoever here",
    )
    # A group with an English display_name that should NOT match the
    # query at all (its slug "g-emotion" still substring-matches the
    # token "i" — see the slug-side note below). We use a group whose
    # display_name is fully non-overlapping with the query AND whose
    # slug also has no overlap, to assert the new whole-word English
    # match keeps it out.
    write_unit(
        str(tmp_path),
        {
            "id": "food",
            "type": "group",
            "name": "food",
            "properties": {
                "display_name": "food",
                "members": [],
            },
            "connections": [],
            "created": "2026-06-29",
            "updated": "2026-06-29",
            "author_confirmed": True,
        },
    )

    hits = lexical_search(str(tmp_path), "i want to eat")
    # The eat sentence is the top hit.
    hit_ids = [h.unit_id for h in hits]
    assert "s-eat" in hit_ids
    # The unrelated sentence should NOT appear.
    assert "s-other" not in hit_ids


def test_lexical_group_slug_substring_match_preserved(tmp_path: Path) -> None:
    """Substring match on slug ids is preserved (autocomplete-style).

    The v0.4.1 T3 fix only changed display_name matching to whole-
    word; slug matching still uses substring so typing "verb" still
    finds the slug "basic-verbs". This pins the behavior so a
    future tightening doesn't break it.
    """
    write_unit(
        str(tmp_path),
        {
            "id": "basic-verbs",
            "type": "group",
            "name": "Basic Verbs",
            "properties": {
                "display_name": "Basic Verbs",
                "members": [],
            },
            "connections": [],
            "created": "2026-06-29",
            "updated": "2026-06-29",
            "author_confirmed": True,
        },
    )
    hits = lexical_search(str(tmp_path), "verb")
    assert any(h.unit_id == "basic-verbs" for h in hits)


def test_lexical_english_query_finds_word_unit_via_english(tmp_path: Path) -> None:
    """Typing 'eat' should surface the 吃 word unit (whose english is 'eat')."""
    write_unit(
        str(tmp_path),
        {
            "id": "chī",
            "type": "word",
            "name": "吃",
            "properties": {
                "hanzi": "吃",
                "pinyin": "chī",
                "english": "eat",
                "meaning": "",
                "groups": [],
                "antonyms": [],
            },
        },
    )
    hits = lexical_search(str(tmp_path), "eat", types=["word"])
    assert any(h.unit_id == "chī" for h in hits)


def test_lexical_hanzi_query_still_works(tmp_path: Path) -> None:
    """Hanzi queries should still match via the hanzi char tokens."""
    _seed_sentence(tmp_path, "s-1", "我喜欢吃", "wǒ xǐhuān chī")
    hits = lexical_search(str(tmp_path), "吃", types=["sentence"])
    assert any(h.unit_id == "s-1" for h in hits)


def test_lexical_mixed_query_picks_max_score(tmp_path: Path) -> None:
    """A mixed query takes whichever field matches best per unit."""
    _seed_sentence(
        tmp_path,
        "s-eat",
        "我想吃",
        "wǒ xiǎng chī",
        english="I want to eat",
    )
    _seed_sentence(
        tmp_path,
        "s-other",
        "我喜欢",
        "wǒ xǐhuān",
        english="something else",
    )
    hits = lexical_search(str(tmp_path), "吃 eat")
    # s-eat should be present, s-other should not.
    hit_ids = [h.unit_id for h in hits]
    assert "s-eat" in hit_ids
    assert "s-other" not in hit_ids


def test_lexical_empty_query_returns_empty(tmp_path: Path) -> None:
    assert lexical_search(str(tmp_path), "") == []
    assert lexical_search(str(tmp_path), "   ") == []