"""GET /api/pinyin/{text} — annotate a hanzi string with pinyin + tone.

Backing Note 4 of ``.specs/v0.4-backlog.md``: hover over any hanzi
character in the UI to see its pinyin tooltip with a tone-colored
underline. This endpoint is the server-side source of truth for the
pinyin mapping so the frontend doesn't ship the pypinyin library in
its JS bundle and so future tone-rule overrides can live in one
place.

Response shape
--------------
For a single hanzi character ``X`` and a hanzi string ``"你好"``, the
response is::

    [
      {"char": "你", "pinyin": "nǐ", "tone": 3},
      {"char": "好", "pinyin": "hǎo", "tone": 3}
    ]

* ``char`` is the input character verbatim. For multi-char input the
  response has one entry per character.
* ``pinyin`` is the tone-marked pinyin with diacritics (``Style.TONE``
  in pypinyin's vocabulary).
* ``tone`` is an integer in {1, 2, 3, 4, 5}. Tone 5 is the neutral
  tone (no diacritic on the vowel). For punctuation, ASCII, digits,
  and any character pypinyin can't decode, the entry is
  ``{"char": X, "pinyin": "", "tone": 5}`` — the frontend renders
  these as tone-5 / no-tooltip.

Punctuation, ASCII, and unknown characters are kept in the response
so the frontend can still position tooltips per-character; only the
``pinyin`` and ``tone`` fields are empty.

Caching
-------
We memoize per-character results in a module-level dict so repeated
hovers over the same sentence don't re-run pypinyin on every keystroke.
The cache is unbounded but small in practice (Chinese has ~3,500
common characters + user's curated compounds).

Performance
-----------
For a sentence of N characters this is O(N) after the per-char cache
warm-up. A 50-char sentence cold-call takes ~5ms in our test env.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter
from pypinyin import Style, lazy_pinyin


router = APIRouter(prefix="/api/pinyin", tags=["pinyin"])


# Module-level per-character cache. Key = the character, value =
# (pinyin, tone). Neutral-tone entries ARE cached so we don't repeat
# pypinyin's failure-to-decode path on every hover.
_CACHE: dict[str, tuple[str, int]] = {}

# Trailing digit in pypinyin's TONE3 output (e.g. "ni3" → tone 3).
_TONE3_TRAILING_RE = re.compile(r"(\d)$")


def _pinyin_and_tone_for_char(ch: str) -> tuple[str, int]:
    """Return (tone-marked pinyin, tone 1-5) for one character.

    Memoizes per character in :data:`_CACHE`.
    """
    if ch in _CACHE:
        return _CACHE[ch]

    # pypinyin's lazy_pinyin returns a list with one entry per input
    # string. We pass [ch] so we get one result back. TONE3 style
    # emits "ni3"; we parse the trailing digit. TONE style emits the
    # accented form "nǐ" but loses easy tone-extraction.
    #
    # The ``errors`` callback fires for any char pypinyin can't decode
    # (punctuation, ASCII, rare CJK extensions). It receives the
    # failing input string and must return a list of pinyin strings
    # of the same length as the input list. We return a single
    # empty string so the entry surfaces to the frontend as
    # ``pinyin="", tone=5``.
    def _on_error(_failed: str) -> list[str]:
        return [""]

    tone3_list = lazy_pinyin([ch], style=Style.TONE3, errors=_on_error)
    raw = tone3_list[0] if tone3_list else ""
    if not raw:
        _CACHE[ch] = ("", 5)
        return _CACHE[ch]

    m = _TONE3_TRAILING_RE.search(raw)
    if m is None:
        # No trailing digit → treat as neutral (5). This shouldn't
        # happen with TONE3, but we stay defensive.
        _CACHE[ch] = (raw, 5)
        return _CACHE[ch]
    tone = int(m.group(1))
    if tone == 5:
        # TONE3 with errors-handled neutral case (rare; some single-
        # char inputs decode with trailing "5"). Strip the digit.
        _CACHE[ch] = (raw[:-1], 5)
        return _CACHE[ch]

    # Re-decode with TONE style to get the accented form for the
    # user-facing pinyin label (e.g. "ni3" → "nǐ").
    tone_list = lazy_pinyin([ch], style=Style.TONE, errors=_on_error)
    pinyin_marked = tone_list[0] if tone_list else raw[:-1]
    _CACHE[ch] = (pinyin_marked, tone)
    return _CACHE[ch]


@router.get("/{text:path}", response_model=list[dict[str, Any]])
def get_pinyin(text: str) -> list[dict[str, Any]]:
    """Annotate ``text`` with per-character pinyin and tone.

    The ``:path`` converter accepts arbitrary UTF-8 hanzi strings in
    the URL path, including punctuation (which is preserved in the
    output with empty pinyin).
    """
    if not isinstance(text, str):
        return []

    out: list[dict[str, Any]] = []
    for ch in text:
        pinyin, tone = _pinyin_and_tone_for_char(ch)
        out.append({"char": ch, "pinyin": pinyin, "tone": tone})
    return out


__all__ = ["router", "get_pinyin", "_pinyin_and_tone_for_char"]
