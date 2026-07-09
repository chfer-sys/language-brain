"""Dictionary segmentation service (v0.5.3 Bite 2).

Self-contained FMM segmentation over the ``word`` table populated by Bite 1's
import. No caching needed at personal scale.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from api.services.db import get_connection, init_schema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tone-strip helper
# ---------------------------------------------------------------------------
# ponytail: strips tone marks AND trailing tone digits → plain pinyin for comparison.
# E.g. "liǎo" / "liao3" / "liao" all → "liao".
# Coverage: standard Mandarin tone-mark vowels (a/o/e/i/u/ü × tones 1-4 = 24 chars).
# Ceiling: rare diacritics not in the map; upgrade path is to expand the maps.
_TONE_MARKS_SRC = (
    "āáǎà" "ōóǒò" "ēéěè" "īíǐì" "ūúǔù" "ǖǘǚǜ"
)
_TONE_MARKS_DST = (
    "a" "a" "a" "a"
    "o" "o" "o" "o"
    "e" "e" "e" "e"
    "i" "i" "i" "i"
    "u" "u" "u" "u"
    "ü" "ü" "ü" "ü"
)
assert len(_TONE_MARKS_SRC) == len(_TONE_MARKS_DST), (
    f"Tone-map length mismatch: {len(_TONE_MARKS_SRC)} != {len(_TONE_MARKS_DST)}"
)
_TONE_MARK_MAP = str.maketrans(_TONE_MARKS_SRC, _TONE_MARKS_DST)


def _strip_tones(pinyin: str) -> str:
    """Return pinyin with tone marks and trailing tone digits stripped.

    ``pinyin`` may be tone-marked (liǎo), tone-numbered (liao3), or already
    stripped (liao). All become the same base form for comparison.
    """
    if not pinyin:
        return ""
    # Remove tone marks first.
    base = pinyin.translate(_TONE_MARK_MAP)
    # Strip trailing tone digit (1-5).
    base = re.sub(r"[1-5]$", "", base)
    return base.lower()


# ---------------------------------------------------------------------------
# WordToken
# ---------------------------------------------------------------------------

@dataclass
class WordToken:
    """Segmented token from the dictionary."""

    id: Optional[str]          # W1/C1 from word table; None for unknown chars
    hanzi: str                  # the token text
    pinyin: Optional[str]       # from dict (disambiguated); None for unknown
    english: Optional[str]      # from dict; None for unknown
    source: str                 # "dict" or "unknown"
    parked: bool                # True for 了 的 吗 呢 吧 啊 嘛 啦


# ---------------------------------------------------------------------------
# Parked particles
# ---------------------------------------------------------------------------

PARKED_HANZI: frozenset[str] = frozenset({"了", "的", "吗", "呢", "吧", "啊", "嘛", "啦"})


# ---------------------------------------------------------------------------
# Dictionary
# ---------------------------------------------------------------------------

class Dictionary:
    """Dictionary segmentation service backed by the ``word`` table.

    ponytail: opens its own read-only connection per instance; the caller
    owns the vault_root. Simpler than accepting a connection, avoids
    connection-sharing edge cases at personal scale.
    """

    __slots__ = ("_vault_root", "_conn")

    def __init__(self, vault_root: str) -> None:
        self._vault_root = vault_root
        self._conn = get_connection(vault_root)
        init_schema(self._conn)

    def close(self) -> None:
        self._conn.close()

    def _lookup(self, hanzi: str) -> list[dict]:
        """Return all word-table rows matching ``hanzi`` (0..N).

        Query by the UNIQUE(hanzi, pinyin) index. Each row is a sqlite3.Row
        cast to dict.
        """
        rows = self._conn.execute(
            "SELECT id, hanzi, pinyin, english, frequency FROM word WHERE hanzi = ?",
            (hanzi,),
        ).fetchall()
        return [dict(r) for r in rows]

    def pick_reading(
        self,
        rows: list[dict],
        sentence_pinyin: Optional[str],
    ) -> dict:
        """Disambiguate among multiple rows for the same hanzi.

        Algorithm (SPEC §5.8):
        1. If ``sentence_pinyin`` is provided, pick the row whose tone-stripped
           pinyin appears in the tone-stripped sentence pinyin.
        2. Otherwise (or on no match), fall back to highest ``frequency``.
        3. If exactly one row, return it directly.

        Arguments:
            rows: output of ``_lookup(hanzi)`` — 1..N word rows.
            sentence_pinyin: optional space-separated tone-marked pinyin for the
                full sentence (used for disambiguation of polyphonic hanzi).

        Returns:
            The selected word row dict.

        Raises:
            ValueError: if ``rows`` is empty.
        """
        if not rows:
            raise ValueError("pick_reading called with empty rows")

        if len(rows) == 1:
            return rows[0]

        # Tone-strip the sentence pinyin once.
        sentence_base = _strip_tones(sentence_pinyin or "")

        # Look for a row whose tone-stripped pinyin appears in the sentence.
        if sentence_base:
            for row in rows:
                row_base = _strip_tones(row["pinyin"] or "")
                if row_base and row_base in sentence_base:
                    return row

        # Fall back: highest frequency.
        return max(rows, key=lambda r: r["frequency"] or 0.0)

    def segment(
        self,
        hanzi: str,
        sentence_pinyin: Optional[str] = None,
    ) -> list[WordToken]:
        """Forward-maximum-match segmentation over the ``word`` table.

        At each position tries lengths 4 → 1; the first candidate found in the
        word table wins. Characters not found emit a placeholder token with
        ``source="unknown"`` and advance by 1.

        Arguments:
            hanzi: the Chinese string to segment.
            sentence_pinyin: optional space-separated tone-marked pinyin for the
                full sentence (used to disambiguate polyphonic characters like 了).

        Returns:
            List of :class:`WordToken` in segmentation order.
        """
        tokens: list[WordToken] = []
        i = 0
        n = len(hanzi)

        while i < n:
            remaining = n - i
            matched = False

            # Try lengths 4 down to 1.
            for length in range(min(4, remaining), 0, -1):
                candidate = hanzi[i : i + length]
                rows = self._lookup(candidate)

                if rows:
                    # Found at least one entry for this candidate.
                    reading = self.pick_reading(rows, sentence_pinyin)
                    tokens.append(WordToken(
                        id=reading["id"],
                        hanzi=candidate,
                        pinyin=reading["pinyin"],
                        english=reading["english"],
                        source="dict",
                        parked=(candidate in PARKED_HANZI),
                    ))
                    i += length
                    matched = True
                    break

            if not matched:
                # Unknown character — emit placeholder and advance by 1.
                char = hanzi[i]
                logger.warning("Unknown character during segmentation: %s", char)
                tokens.append(WordToken(
                    id=None,
                    hanzi=char,
                    pinyin=None,
                    english=None,
                    source="unknown",
                    parked=(char in PARKED_HANZI),
                ))
                i += 1

        return tokens

    def __enter__(self) -> "Dictionary":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
