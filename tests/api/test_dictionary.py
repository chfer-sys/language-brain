"""Tests for api/services/dictionary.py — v0.5.3 Bite 2."""

from __future__ import annotations

from pathlib import Path

import pytest

from api.services.dictionary import (
    Dictionary,
    PARKED_HANZI,
    WordToken,
    _strip_tones,
)
from scripts.build_dictionary import _import_source


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

SEGMENT_FIXTURE = Path(__file__).parent.parent / "fixtures" / "segment_fixture.txt"


def _seed_dictionary(vault_root: str) -> None:
    """Populate the word table using the segment_fixture."""
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
# Tone-strip helper
# ---------------------------------------------------------------------------

class TestStripTones:
    """Sanity-check the tone-strip helper used by pick_reading."""

    @pytest.mark.parametrize(
        "input_,expected",
        [
            ("liǎo", "liao"),
            ("le", "le"),
            ("liao3", "liao"),
            ("le5", "le"),
            ("wǒ", "wo"),
            ("ni3", "ni"),
            ("", ""),
            ("shi4", "shi"),
        ],
    )
    def test_strip_tones(self, input_: str, expected: str) -> None:
        assert _strip_tones(input_) == expected


# ---------------------------------------------------------------------------
# Dictionary._lookup
# ---------------------------------------------------------------------------

class TestLookup:
    """_lookup returns all rows for a hanzi string."""

    def test_single_row(self, tmp_path: Path) -> None:
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            rows = d._lookup("我")
        assert len(rows) == 1
        assert rows[0]["hanzi"] == "我"

    def test_polyphonic_hanzi(self, tmp_path: Path) -> None:
        """了 has two rows: le and liǎo."""
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            rows = d._lookup("了")
        assert len(rows) == 2, f"Expected 2 rows for polyphonic 了, got {len(rows)}"
        pinyins = {r["pinyin"] for r in rows}
        assert "le" in pinyins, f"'le' missing from {pinyins}"
        assert "liǎo" in pinyins, f"'liǎo' missing from {pinyins}"

    def test_absent_hanzi(self, tmp_path: Path) -> None:
        """Unknown hanzi → empty list."""
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            rows = d._lookup("僻")
        assert rows == []


# ---------------------------------------------------------------------------
# Dictionary.pick_reading
# ---------------------------------------------------------------------------

class TestPickReading:
    """pick_reading disambiguates polyphonic hanzi using sentence_pinyin."""

    def test_single_row_returns_that_row(self, tmp_path: Path) -> None:
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            rows = d._lookup("我")
            picked = d.pick_reading(rows, sentence_pinyin=None)
        assert picked["hanzi"] == "我"

    def test_picks_matching_tone_stripped(self, tmp_path: Path) -> None:
        """With sentence_pinyin='le', picks 了/le (not 了/liǎo)."""
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            rows = d._lookup("了")
            # sentence contains "le" → should pick le
            picked = d.pick_reading(rows, sentence_pinyin="chi1 le fan4")
        assert picked["pinyin"] == "le", f"Expected 'le', got {picked['pinyin']!r}"

    def test_picks_liao_when_sentence_contains_liao(self, tmp_path: Path) -> None:
        """With sentence_pinyin containing 'liao', picks 了/liǎo."""
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            rows = d._lookup("了")
            picked = d.pick_reading(rows, sentence_pinyin="liao3 jie3")
        assert picked["pinyin"] == "liǎo", f"Expected 'liǎo', got {picked['pinyin']!r}"

    def test_falls_back_to_frequency(self, tmp_path: Path) -> None:
        """Without sentence_pinyin, picks highest frequency (liǎo: 9876 > le entry)."""
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            rows = d._lookup("了")
            picked = d.pick_reading(rows, sentence_pinyin=None)
        # 了/liǎo has frequency 9876.2 vs 了/le frequency
        assert picked["pinyin"] == "liǎo", f"Expected 'liǎo' (higher freq), got {picked['pinyin']!r}"

    def test_raises_on_empty_rows(self, tmp_path: Path) -> None:
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            with pytest.raises(ValueError):
                d.pick_reading([], sentence_pinyin=None)


# ---------------------------------------------------------------------------
# Edge cases EC1–EC6
# ---------------------------------------------------------------------------

class TestSegmentEC:
    """EC1–EC6 from SPEC §5.7."""

    @pytest.fixture
    def dict_(self, tmp_path: Path) -> Dictionary:
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary
        return Dictionary(str(tmp_path))

    def test_EC1_我受不了这个(self, dict_: Dictionary) -> None:
        """EC1: 我 / 受不了 / 这个 (3-char compound 受不了)."""
        tokens = dict_.segment("我受不了这个")
        hanzis = [t.hanzi for t in tokens]
        assert hanzis == ["我", "受不了", "这个"], f"Got {hanzis!r}"
        # Check W/C ids
        assert tokens[0].id is not None and tokens[0].id.startswith("W"), tokens[0].id
        assert tokens[1].id is not None and tokens[1].id.startswith("C"), tokens[1].id
        assert tokens[2].id is not None and tokens[2].id.startswith("C"), tokens[2].id
        for t in tokens:
            assert t.source == "dict", f"{t.hanzi!r} source={t.source!r}"

    def test_EC2_吃了饭(self, dict_: Dictionary) -> None:
        """EC2: 吃 / 了 / 饭 — 了 is parked particle (le reading)."""
        tokens = dict_.segment("吃了饭")
        hanzis = [t.hanzi for t in tokens]
        assert hanzis == ["吃", "了", "饭"], f"Got {hanzis!r}"
        for t in tokens:
            assert t.source == "dict", f"{t.hanzi!r} source={t.source!r}"
        # 了 must be parked=True
        assert tokens[1].parked is True, "Expected 了 to be parked=True"
        assert tokens[1].id is not None and tokens[1].id.startswith("W"), tokens[1].id

    def test_EC3_了解(self, dict_: Dictionary) -> None:
        """EC3: 了解 — 2-char compound."""
        tokens = dict_.segment("了解")
        hanzis = [t.hanzi for t in tokens]
        assert hanzis == ["了解"], f"Got {hanzis!r}"
        assert tokens[0].id is not None and tokens[0].id.startswith("C"), tokens[0].id
        assert tokens[0].source == "dict"

    def test_EC4_世界上最(self, dict_: Dictionary) -> None:
        """EC4: 世界 / 上 / 最 (4-char-max FMM; 世界 is 2-char compound)."""
        tokens = dict_.segment("世界上最")
        hanzis = [t.hanzi for t in tokens]
        assert hanzis == ["世界", "上", "最"], f"Got {hanzis!r}"
        assert tokens[0].id.startswith("C")
        assert tokens[1].id.startswith("W")
        assert tokens[2].id.startswith("W")
        for t in tokens:
            assert t.source == "dict"

    def test_EC5_僻(self, dict_: Dictionary) -> None:
        """EC5: 僻 — not in dict, emits unknown placeholder."""
        tokens = dict_.segment("僻")
        assert len(tokens) == 1
        assert tokens[0].hanzi == "僻"
        assert tokens[0].source == "unknown"
        assert tokens[0].id is None
        assert tokens[0].pinyin is None
        assert tokens[0].english is None

    def test_EC6_现在几点(self, dict_: Dictionary) -> None:
        """EC6: 现在 / 几 / 点 — mixed."""
        tokens = dict_.segment("现在几点")
        hanzis = [t.hanzi for t in tokens]
        assert hanzis == ["现在", "几", "点"], f"Got {hanzis!r}"
        assert tokens[0].id.startswith("C")
        assert tokens[1].id.startswith("W")
        assert tokens[2].id.startswith("W")
        for t in tokens:
            assert t.source == "dict"


# ---------------------------------------------------------------------------
# Parked particle
# ---------------------------------------------------------------------------

class TestParkedParticle:
    """PARKED_HANZI tokens get parked=True (still from dict, with pinyin/english)."""

    def test_le_aspect_particle(self, tmp_path: Path) -> None:
        """了 in 吃了饭 is parked=True with its dict pinyin/english."""
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            tokens = d.segment("吃了饭")
        le_token = tokens[1]
        assert le_token.hanzi == "了"
        assert le_token.parked is True, "Expected parked=True for 了"
        assert le_token.source == "dict"
        assert le_token.pinyin is not None, "pinyin should be set"
        assert le_token.english is not None, "english should be set"

    @pytest.mark.parametrize("hanzi", sorted(PARKED_HANZI))
    def test_parked_hanzi_are_from_dict(self, hanzi: str, tmp_path: Path) -> None:
        """Each parked hanzi is in the dict and returns parked=True."""
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            tokens = d.segment(hanzi)
        assert len(tokens) == 1
        assert tokens[0].hanzi == hanzi
        assert tokens[0].parked is True, f"{hanzi} should be parked=True"


# ---------------------------------------------------------------------------
# Unknown char
# ---------------------------------------------------------------------------

class TestUnknownChar:
    """A character not in the word table → source='unknown', id=None, warning logged."""

    def test_unknown_char_returns_placeholder(self, tmp_path: Path, caplog) -> None:
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            tokens = d.segment("僻")
        assert len(tokens) == 1
        assert tokens[0].source == "unknown"
        assert tokens[0].id is None
        assert tokens[0].pinyin is None
        assert tokens[0].english is None
        assert "僻" in caplog.text or "Unknown character" in caplog.text


# ---------------------------------------------------------------------------
# Multi-reading disambiguation
# ---------------------------------------------------------------------------

class TestMultiReadingDisambiguation:
    """pick_reading uses sentence_pinyin to choose among multiple readings."""

    def test_disambiguation_via_sentence_pinyin(self, tmp_path: Path) -> None:
        """With sentence_pinyin containing 'le', picks 了/le (not 了/liǎo)."""
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            tokens = d.segment("吃了", sentence_pinyin="chi1 le")
        hanzis = [t.hanzi for t in tokens]
        assert hanzis == ["吃", "了"], f"Got {hanzis!r}"
        assert tokens[1].pinyin == "le", f"Expected 'le', got {tokens[1].pinyin!r}"

    def test_falls_back_to_frequency_without_sentence_pinyin(self, tmp_path: Path) -> None:
        """Without sentence_pinyin, pick_reading uses frequency (liǎo > le)."""
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            tokens = d.segment("吃了")
        hanzis = [t.hanzi for t in tokens]
        assert hanzis == ["吃", "了"], f"Got {hanzis!r}"
        # 了/liǎo has freq 9876.2 > 了/le freq 5000.0
        assert tokens[1].pinyin == "liǎo", f"Expected 'liǎo' (higher freq), got {tokens[1].pinyin!r}"


# ---------------------------------------------------------------------------
# Token shape
# ---------------------------------------------------------------------------

class TestTokenShape:
    """WordToken has the expected fields and types."""

    def test_token_fields_and_types(self, tmp_path: Path) -> None:
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            tokens = d.segment("我")
        assert len(tokens) == 1
        t = tokens[0]
        assert isinstance(t, WordToken)
        assert t.id is not None and isinstance(t.id, str)
        assert isinstance(t.hanzi, str)
        assert t.pinyin is None or isinstance(t.pinyin, str)
        assert t.english is None or isinstance(t.english, str)
        assert isinstance(t.source, str)
        assert isinstance(t.parked, bool)

    def test_token_from_unknown_has_none_fields(self, tmp_path: Path) -> None:
        _seed_dictionary(str(tmp_path))
        from api.services.dictionary import Dictionary

        with Dictionary(str(tmp_path)) as d:
            tokens = d.segment("僻")
        t = tokens[0]
        assert t.id is None
        assert t.pinyin is None
        assert t.english is None
        assert t.source == "unknown"
