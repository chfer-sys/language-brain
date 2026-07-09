"""Helpers for resolving ``antonyms`` entries to word-unit ids.

The :class:`CommitSentenceRequest` carries ``antonyms`` as a list of
strings. Per Note 3 of ``.specs/v0.4-backlog.md`` the canonical user-
facing form is **hanzi** (e.g. ``["饱"]``), but the on-disk word-unit
identifier scheme is **pinyin-with-tones** (e.g. ``"bǎo"``) per OQ2.

This module bridges the two: given a free-form antonym string, decide
whether it's hanzi or pinyin, and return the word-unit id the
:mod:`api.routes.commit_sentence` save flow should use to wire the
opposite edge.

Resolution rules
----------------
1. If the entry contains any CJK character (Unified Ideographs or
   extensions), treat it as **hanzi**:
     a. Look up existing word units whose ``properties.hanzi`` equals
        the entry. If exactly one match, return that word's id.
     b. If multiple match (rare — e.g. two homograph words), return
        the first by alphabetical id for determinism.
     c. If no match, create a fresh word unit with ``id`` derived
        from :func:`pypinyin.lazy_pinyin` of the hanzi (TONE style).
        Return the new id. This keeps the invariant "every word
        referenced by an antonym relation exists as a unit on disk"
        without forcing the user to pre-save every word.
2. Otherwise treat it as a **pinyin id** (existing v0.3 behavior).
   Return the entry verbatim. If the word unit doesn't exist yet,
   the connector's opposite pass will skip it (locked-in behavior
   per :func:`api.services.connector._compute_opposite_edges`).
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

log = logging.getLogger(__name__)


# CJK Unified Ideographs + Extensions A–F + Compatibility Ideographs.
# Tilde-broad to keep the detector fast and forgiving — anything in the
# CJK block is treated as hanzi regardless of which extension it lives in.
_CJK_RE = re.compile(
    r"["
    "\u3040-\u30ff"  # Hiragana + Katakana (treat Japanese kana as "not pinyin")
    "\u3400-\u4dbf"  # CJK Extension A
    "\u4e00-\u9fff"  # CJK Unified Ideographs (the main hanzi block)
    "\uf900-\ufaff"  # CJK Compatibility Ideographs
    "\U00020000-\U0002a6df"  # CJK Extension B
    "\U0002a700-\U0002b73f"  # CJK Extension C
    "\U0002b740-\U0002b81f"  # CJK Extension D
    "\U0002b820-\U0002ceaf"  # CJK Extension E
    "\U0002ceb0-\U0002ebef"  # CJK Extension F
    "\U00030000-\U0003134f"  # CJK Extension G
    "]"
)


def _looks_like_hanzi(entry: str) -> bool:
    """True if ``entry`` contains any CJK character."""
    return bool(_CJK_RE.search(entry))


def _hanzi_to_pinyin_id(hanzi: str) -> str:
    """Derive a pinyin id for ``hanzi`` using pypinyin's TONE style.

    Used as the word-unit id when a sentence commits a brand-new
    antonym hanzi that has no existing word file. Returns the tone-
    marked pinyin string (e.g. ``"bǎo"`` for ``"饱"``). Falls back to
    the hanzi verbatim if pypinyin can't decode the characters (rare
    — pypinyin handles the whole CJK Unified block).

    Imports pypinyin lazily so tests that don't exercise the create-
    new-word path don't pay the import cost.
    """
    from pypinyin import Style, lazy_pinyin  # type: ignore[import-untyped]

    parts = lazy_pinyin(hanzi, style=Style.TONE)
    # Concatenate without separator — word-unit ids are single tokens.
    # If pypinyin returned empty for any reason, fall back to the
    # hanzi so we always have a non-empty id to write.
    pinyin = "".join(parts).strip()
    return pinyin or hanzi


def resolve_antonym_to_word_id(
    vault_root: str,
    entry: str,
    existing_word_units: Iterable[dict] | None = None,
) -> str:
    """Resolve a single ``antonyms[]`` entry to a word-unit id.

    See the module docstring for the resolution rules. The
    ``existing_word_units`` parameter is an injection seam for tests
    — production callers let it default to ``None`` and the
    function reads the on-disk vault itself.

    Parameters
    ----------
    vault_root
        Path to the vault root (used when creating a new word unit
        or when ``existing_word_units`` is not supplied).
    entry
        One element of ``CommitSentenceRequest.antonyms``. May be
        hanzi (``"饱"``) or pinyin (``"bǎo"``).
    existing_word_units
        Optional pre-loaded list of word unit dicts. When ``None``
        the function loads them from disk via
        :func:`api.services.word_registry.list_all_words`.

    Returns
    -------
    str
        The word-unit id (pinyin-with-tones) to wire into the
        :func:`api.services.connector._compute_opposite_edges`
        pass. If the entry was already pinyin, returns it verbatim.
        If it was hanzi, returns either the existing word's id or
        a newly-created id.
    """
    if not isinstance(entry, str) or not entry.strip():
        raise ValueError("antonym entry must be a non-empty string")

    entry = entry.strip()

    if existing_word_units is None:
        from api.services.word_registry import list_all_words

        existing_word_units = list_all_words(vault_root)

    # Look up by hanzi OR pinyin — return the word unit's typed id (W{n}).
    matches: list[str] = []
    for w in existing_word_units:
        if not isinstance(w, dict):
            continue
        props = w.get("properties")
        if not isinstance(props, dict):
            continue
        if (props.get("hanzi") == entry or props.get("pinyin") == entry) and isinstance(
            w.get("id"), str
        ):
            matches.append(w["id"])

    if matches:
        matches.sort()
        return matches[0]

    # No existing word — if it's hanzi, create one.
    if _looks_like_hanzi(entry):
        pinyin_id = _hanzi_to_pinyin_id(entry)
        from api.services.word_registry import ensure_word_unit

        word_unit = ensure_word_unit(
            vault_root,
            hanzi=entry,
            pinyin=pinyin_id,
            english="",
            meaning="",
        )
        log.info(
            "antonym hanzi=%r had no matching word unit; created new word id=%r",
            entry,
            word_unit["id"],
        )
        return word_unit["id"]

    # Pinyin entry with no matching word — return as-is (connector skips unknown targets).
    return entry


def normalize_antonyms_for_storage(antonyms: list[str]) -> list[str]:
    """Strip whitespace, drop blanks, preserve order, de-dupe.

    Used on the inbound :class:`CommitSentenceRequest.antonyms`
    before persisting to the sentence unit. The set of accepted
    strings is unchanged (hanzi or pinyin); this helper only
    normalizes formatting so the on-disk array is tidy.
    """
    if not isinstance(antonyms, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for a in antonyms:
        if not isinstance(a, str):
            continue
        s = a.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


__all__ = [
    "resolve_antonym_to_word_id",
    "normalize_antonyms_for_storage",
    "_looks_like_hanzi",
]
