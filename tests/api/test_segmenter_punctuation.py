"""Tests for punctuation handling in Dictionary.segment.

Bug: when a sentence like "我吃饭,你呢?" is segmented, punctuation
characters (comma, question mark) are returned as tokens in the word
list instead of being filtered out.

The Hanzi-only filter in Dictionary.segment should drop any token
whose hanzi is entirely outside the CJK Unified Ideographs range
(\\u4e00-\\u9fff), i.e. punctuation and whitespace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api.services.dictionary import Dictionary
from scripts.build_dictionary import _import_source


# ---------------------------------------------------------------------------
# Seed helper (same as conftest.py — kept here for test isolation)
# ---------------------------------------------------------------------------

SEGMENT_FIXTURE = Path(__file__).parent.parent / "fixtures" / "segment_fixture.txt"


def _seed_dictionary(vault_root: str) -> None:
    _import_source(
        vault_root=vault_root,
        source_id="segment-fixture",
        source_name="Segment Fixture",
        source_version="1.0",
        license="CC-BY",
        attribution="Test fixture",
        priority=50,
        csv_path=str(SEGMENT_FIXTURE),
    )


# ---------------------------------------------------------------------------
# Punctuation filter
# ---------------------------------------------------------------------------

# ponytail: all punctuation/whitespace tokens are non-Hanzi (outside U+4E00-U+9FFF).
# If the user ever wants to keep non-Hanzi tokens like digits, this check
# needs to be refined to a specific punctuation allowlist.
_PUNCT_HANZI = frozenset(",?。？？!！")


class TestPunctuationFilter:
    """Dictionary.segment must not return punctuation as word tokens."""

    @pytest.fixture
    def dict_(self, tmp_path: Path) -> Dictionary:
        _seed_dictionary(str(tmp_path))
        return Dictionary(str(tmp_path))

    @pytest.mark.parametrize(
        "hanzi,pinyin",
        [
            # Chinese comma
            ("我吃饭，你呢？", "wo3 chi1 fan4 ni3 ne5"),
            # ASCII comma and question mark
            ("我吃饭,你呢?", "wo3 chi1 fan4 ni3 ne5"),
            # English period
            ("我吃饭.你呢", "wo3 chi1 fan4 ni3 ne5"),
            # English exclamation
            ("我吃饭!你呢", "wo3 chi1 fan4 ni3 ne5"),
            # Mixed punctuation
            ("你好,世界!", "ni3 hao3 shi4 jie4"),
        ],
    )
    def test_no_punctuation_tokens_in_segmentation(
        self, dict_: Dictionary, hanzi: str, pinyin: str
    ) -> None:
        """Punctuation characters must not appear as tokens in segment()."""
        tokens = dict_.segment(hanzi, pinyin)
        token_hanzis = [t.hanzi for t in tokens]
        punct_tokens = [h for h in token_hanzis if h in _PUNCT_HANZI]
        assert punct_tokens == [], (
            f"Punctuation tokens found in segmentation of {hanzi!r}: {punct_tokens}. "
            f"Full tokens: {token_hanzis}"
        )

    @pytest.mark.parametrize(
        "hanzi,pinyin",
        [
            ("我吃饭,你呢?", "wo3 chi1 fan4 ni3 ne5"),
            ("你好,世界!", "ni3 hao3 shi4 jie4"),
        ],
    )
    def test_hanzi_tokens_still_present(
        self, dict_: Dictionary, hanzi: str, pinyin: str
    ) -> None:
        """Real hanzi words must still be returned after punctuation is filtered."""
        tokens = dict_.segment(hanzi, pinyin)
        token_hanzis = [t.hanzi for t in tokens]
        # All remaining tokens should be single CJK characters (not punctuation)
        for h in token_hanzis:
            assert "\u4e00" <= h <= "\u9fff", (
                f"Non-Hanzi token {h!r} found in {token_hanzis}"
            )
