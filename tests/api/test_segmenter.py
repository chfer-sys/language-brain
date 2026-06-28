"""Tests for the curated user-dictionary segmenter.

The segmenter wraps jieba and loads a curated USER_DICT on import. These
tests assert that the user-dict entries win against jieba's default
greedy segmentation.

Each test is paired with a specific user-dict entry — adding a new
compound to USER_DICT should be accompanied by at least one test that
fails without the entry (i.e. that would fail on plain jieba) and
passes with it.
"""

from __future__ import annotations

import pytest

# Importing the segmenter triggers init_userdict() at module load.
from api.services import segmenter
from api.services.segmenter import USER_DICT, lcut


@pytest.fixture(autouse=True)
def _reset_segmenter():
    """Tests should not leak segmentation state to each other."""
    yield
    # No mutable state to reset; init_userdict is idempotent.


def test_user_dict_is_loaded():
    """Sanity: USER_DICT is non-empty and well-formed."""
    assert len(USER_DICT) >= 20, "USER_DICT should have at least 20 entries"
    for word, freq in USER_DICT.items():
        assert isinstance(word, str) and word, f"bad word: {word!r}"
        assert isinstance(freq, int) and freq > 0, f"bad freq for {word}: {freq}"


@pytest.mark.parametrize(
    "text,expected",
    [
        # 了-complement compounds (must NOT be split at 了)
        ("受不了",   ["受不了"]),
        ("我受不了", ["我", "受不了"]),
        ("真受不了你", ["真", "受不了", "你"]),
        ("了解",     ["了解"]),
        ("了解他",   ["了解", "他"]),
        ("了不起",   ["了不起"]),
        ("真了不起", ["真", "了不起"]),
        # Common function-word compounds
        ("为了",     ["为了"]),
        ("为了什么", ["为了", "什么"]),
        ("除了",     ["除了"]),
        ("罢了",     ["罢了"]),
        # High-frequency compounds
        ("可以",     ["可以"]),
        ("没有",     ["没有"]),
        ("什么",     ["什么"]),
        ("怎么",     ["怎么"]),
        ("为什么",   ["为什么"]),
        ("因为",     ["因为"]),
        ("所以",     ["所以"]),
        ("但是",     ["但是"]),
        ("现在",     ["现在"]),
        ("今天",     ["今天"]),
        ("明天",     ["明天"]),
        ("昨天",     ["昨天"]),
        ("时候",     ["时候"]),
        ("意思",     ["意思"]),
        ("问题",     ["问题"]),
        ("喜欢",     ["喜欢"]),
        ("知道",     ["知道"]),
        ("觉得",     ["觉得"]),
    ],
)
def test_user_dict_compounds_segment_as_one_token(text, expected):
    """Each compound in USER_DICT must come out as one token."""
    assert lcut(text) == expected


def test_sentence_final_particles_still_split_off():
    """Sentences ending in aspect-particle 了/吗 should NOT include
    the particle as a word (the segmenter keeps it as its own token
    but the word_registry filters particles out on save — see Note 2
    of the v0.4 backlog).

    For the segmenter itself, particles are still split off — that's
    the right behavior. The word_registry then decides whether to
    create a unit for them.
    """
    # The particle 了 is a single token (the segmenter doesn't filter
    # at the segmenter level).
    assert lcut("吃了吗") == ["吃", "了", "吗"]
    assert lcut("你走了") == ["你", "走", "了"]


def test_unknown_compounds_fall_back_to_default_jieba():
    """Compounds not in USER_DICT use jieba's default segmentation.
    This is the failure mode we accept — the user notices and adds
    the compound to USER_DICT."""
    # 走路 isn't in USER_DICT; jieba defaults to ["走", "路"] which
    # is reasonable. Just confirm the segmenter doesn't crash.
    result = lcut("走路去学校")
    assert isinstance(result, list)
    assert all(isinstance(t, str) for t in result)


def test_init_userdict_is_idempotent():
    """Calling init_userdict() multiple times is a no-op."""
    # Should not raise and should not change behavior.
    segmenter.init_userdict()
    segmenter.init_userdict()
    assert lcut("我受不了") == ["我", "受不了"]


def test_lcut_validates_input_type():
    """Non-string input raises ValueError."""
    with pytest.raises(ValueError, match="must be a string"):
        lcut(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be a string"):
        lcut(None)  # type: ignore[arg-type]


def test_user_dict_compound_removed_in_jieba_only():
    """Sanity for the underlying jieba behavior: if we did NOT register
    a compound with jieba, it would default to greedy single-char
    matching. This test asserts that 'jǐ bù liǎo' as raw hanzi (without
    the user dict) would split, by checking that adding the dict
    changes the result.

    Concretely: without init_userdict, jieba.lcut('我受不了') returns
    ['我', '受', '不', '了']. After init_userdict, it returns
    ['我', '受不了']. This test verifies the latter, demonstrating
    that the dict is doing real work.
    """
    import jieba as _jieba

    # Reload jieba's state to before init_userdict's effect for this
    # specific word. We can do this by deleting the entry from jieba's
    # internal FREQ dict and re-segmenting.
    # NOTE: this is testing the *mechanism*, not the user-facing API.
    if "受不了" in segmenter.USER_DICT:
        # Temporarily undo.
        freq = segmenter.USER_DICT["受不了"]
        del _jieba.dt.FREQ["受不了"]
        try:
            without = _jieba.lcut("我受不了", HMM=False)
            # Restore.
            _jieba.add_word("受不了", freq=freq)
            # Sanity: the dict was doing real work if the segmentation
            # differs from the with-dict case.
            with_dict = lcut("我受不了")
            assert with_dict == ["我", "受不了"]
            assert without != with_dict, (
                "USER_DICT entry for '受不了' has no effect; "
                "either the freq is too low or jieba's longest-match "
                "behavior doesn't honor add_word at runtime"
            )
        except Exception:
            _jieba.add_word("受不了", freq=freq)
            raise