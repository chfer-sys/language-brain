"""Chinese segmentation via jieba, with a curated user dictionary.

The default jieba dictionary does greedy left-to-right longest-match
segmentation. That works for common single characters but **fails** for
compound words that aren't in its dictionary, e.g.:

  - ``受不了`` ("can't stand") — default cuts to ``["受", "不", "了"]``,
    creating three orphan word units. The 了 here is the 3rd-tone result
    complement (``liǎo``), not the aspect particle (``le``).
  - ``了解`` ("to understand") — default cuts to ``["了", "解"]``,
    creating an orphan ``le`` particle word.
  - ``为了``, ``除了``, ``罢了`` — all get split at the function word.

The :data:`USER_DICT` below is a curated set of compounds the user has
encountered and wants to keep as single words. Frequencies are set high
enough to win against jieba's default single-character matches.

When to add entries:

  1. Save a sentence that contains a compound.
  2. Notice the resulting word units include orphans (e.g. ``受``, ``不``,
     ``了`` from ``受不了``).
  3. Add the compound to ``USER_DICT`` with a high frequency.
  4. Re-save the sentence (or run reindex after a cleanup task).

This module is imported once at process start; ``init_userdict()`` is
idempotent and called from the module body.
"""

from __future__ import annotations

import threading
from typing import Final

import jieba


# ---------------------------------------------------------------------------
# User-curated dictionary of compounds.
#
# Format: compound -> frequency. The frequency just needs to exceed jieba's
# default single-character matches (which score ~3-50). Values of 50_000+ win
# reliably. Compounds in the 20_000-50_000 range still beat single chars
# when the surrounding context makes the compound more probable.
#
# Add entries as you encounter mis-segmentation. The dict is the single
# source of truth — the AI system prompt lists the same entries so the
# AI's propose-labels response agrees with what this segmenter will produce.
# ---------------------------------------------------------------------------

USER_DICT: Final[dict[str, int]] = {
    # --- Verbs with 了-complement (3rd tone) ---
    "受不了": 100_000,
    "了解":   100_000,
    "了不起": 100_000,
    "得到":   50_000,
    "觉得":   80_000,
    "感到":   30_000,
    "看懂":   30_000,
    "听懂":   30_000,
    "学会":   30_000,
    "记得":   30_000,
    "忘记":   30_000,
    "遇见":   20_000,
    "遇到":   30_000,
    "想到":   30_000,
    "发现":   30_000,
    # --- Function-word compounds ---
    "为了":   80_000,
    "除了":   50_000,
    "罢了":   30_000,
    "完了":   20_000,    # verb "to be done/finished" (wán le) — context-dependent
    "得了":   20_000,    # "that'll do", "come down with"
    "好的":   20_000,    # "okay" — casual response
    "好了":   20_000,    # "enough", "that's enough"
    # --- High-frequency function words ---
    "可以":   80_000,
    "没有":   80_000,
    "什么":   80_000,
    "怎么":   50_000,
    "为什么": 50_000,
    "因为":   50_000,
    "所以":   50_000,
    "但是":   50_000,
    "现在":   50_000,
    "今天":   30_000,
    "明天":   30_000,
    "昨天":   30_000,
    "时候":   30_000,
    "东西":   30_000,
    "意思":   30_000,
    "问题":   30_000,
    "一下":   30_000,
    "一些":   30_000,
    "这样":   30_000,
    "那样":   30_000,
    "以后":   30_000,
    "以前":   30_000,
    "已经":   30_000,
    "应该":   30_000,
    "可能":   30_000,
    "需要":   30_000,
    "喜欢":   50_000,
    "知道":   50_000,
}


_init_lock = threading.Lock()
_initialized = False


def init_userdict() -> None:
    """Register :data:`USER_DICT` entries with jieba. Idempotent.

    Called automatically at module import. Safe to call again (no-op after
    first successful call). Tests can call this directly to assert
    segmentation behavior with the dict loaded.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        for word, freq in USER_DICT.items():
            jieba.add_word(word, freq=freq)
        _initialized = True


def lcut(text: str, hmm: bool = False) -> list[str]:
    """Segment ``text`` into a list of hanzi tokens.

    Wrapper around :func:`jieba.lcut` that guarantees the user dict is
    loaded. ``hmm`` is forwarded to jieba's HMM model toggle; the default
    (``False``) uses jieba's deterministic longest-match segmentation.

    The user dict is loaded at module import time, so this function is
    safe to call without explicit initialization.
    """
    if not isinstance(text, str):
        raise ValueError(f"text must be a string, got {type(text).__name__}")
    init_userdict()
    return jieba.lcut(text, HMM=hmm)


def lcut_for_search(text: str) -> list[str]:
    """Segment for search indexing — full-mode (cuts more aggressively).

    Use this for the indexer and search-query tokenization. The default
    ``lcut`` is for storing the user's intended segmentation in
    ``properties.words[]``.
    """
    if not isinstance(text, str):
        raise ValueError(f"text must be a string, got {type(text).__name__}")
    init_userdict()
    return jieba.lcut_for_search(text)


# Initialize at import so any module that uses ``lcut`` picks up the
# user dict without an explicit call.
init_userdict()


__all__ = ["USER_DICT", "init_userdict", "lcut", "lcut_for_search"]