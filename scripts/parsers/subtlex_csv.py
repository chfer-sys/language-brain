"""Parser for SUBTLEX-CH tab-separated files.

Real format confirmed by research on subtlexch131210.zip:
  - Tab-separated, UTF-8
  - First 2 lines are corpus metadata (skip them)
  - Header columns: Word | Length | Pinyin | Pinyin.Input | W.million | ...
  - Polyphonic pinyin: slash-separated (e.g. le5//liǎo3)
  - Pinyin is in TONE NUMBERS; convert to tone marks before storing.
  - Eng.Tran may be empty (→ None)
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

# ponytail: isolated column mapping — one dict to change if header names change.
COLUMN_MAP: dict[str, str] = {
    "hanzi": "Word",
    "pinyin": "Pinyin",
    "english": "Eng.Tran",
    "frequency": "W.million",
    "part_of_speech": "Dominant.PoS",
}

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tone-number → tone-mark helper
# ---------------------------------------------------------------------------
# ponytail: standard Mandarin tone-placement rule (vowel priority: a→o→e→i/u→ü).
# Coverage: tone-number strings (1-5) on a, o, e, i, u, ü, and common combos.
# Known ceiling: rare syllables with diphthongs/triphthongs not in the priority
# list will fall through to last-vowel heuristic (upgrade path: expand mapping).

# a,o,e,i,u,ü ordering matches _SINGLE_VOWEL_TONE_INDEX indices.
_TONE_MARKS = {"1": "āōēīūǖ", "2": "áóéíúǘ", "3": "ǎǒěǐǔǚ", "4": "àòèìùǜ", "5": ""}
# Order matters: check "iu"/"ui" before single "i"/"u".
_VOWEL_PRIORITY = ["a", "o", "e", "iu", "ui", "ü", "i", "u"]
# ponytail: tone-mark arrays follow a,o,e,i,u,ü order → i at index 3, u at index 4.
_SINGLE_VOWEL_TONE_INDEX = {"a": 0, "o": 1, "e": 2, "i": 3, "u": 4, "ü": 5}


def tone_number_to_mark(syllable: str) -> str:
    """Convert a tone-number pinyin syllable to tone-marked pinyin.

    ``syllable`` is a single pinyin unit, e.g. ``ni3``, ``chuang1``, ``nv3``.
    Tone 5 / tone 0 = neutral → stripped of digit, returned unmarked.
    Handles ``v`` as a stand-in for ``ü`` (common in some pinyin conventions).

    Returns the syllable with the tone mark on the correct vowel.
    """
    # Strip tone-number suffix.
    m = re.match(r"^(.+?)(\d)$", syllable)
    if not m:
        return syllable  # already marked or neutral (no digit)
    base, tone = m.group(1), m.group(2)
    if tone == "5":
        return base  # neutral: no mark

    tone_char = _TONE_MARKS[tone]

    # Normalise ü alias.
    base = base.replace("v", "ü")

    # Find which vowel group carries the mark (priority order).
    for group in _VOWEL_PRIORITY:
        if group in base:
            idx = base.index(group)
            if len(group) == 1:
                # Single vowel: tone index comes from _SINGLE_VOWEL_TONE_INDEX.
                tone_idx = _SINGLE_VOWEL_TONE_INDEX[group]
                marked = tone_char[tone_idx]
                return base[:idx] + marked + base[idx + 1 :]
            else:
                # Compound vowels: "ui" stresses the 'i' (second vowel, at idx+1 in base);
                # "iu" stresses the 'u' (second vowel, at idx+1 in base).
                # ponytail: ui→idx+1 (i is stressed), iu→idx+1 (u is stressed).
                # Only the stressed character within the group is replaced.
                tone_idx = idx + 1
                stressed_char = base[tone_idx]
                # Map stressed char to its position in the vowel order for tone_char.
                stress_vowel_idx = _SINGLE_VOWEL_TONE_INDEX[stressed_char]
                marked = tone_char[stress_vowel_idx]
                return base[:tone_idx] + marked + base[tone_idx + 1 :]

    # Fallback: mark the last vowel using a-row as default marker.
    for i in range(len(base) - 1, -1, -1):
        if base[i] in "aeiouü":
            marked = tone_char[0]  # use a-row as default
            return base[:i] + marked + base[i + 1 :]

    return syllable  # no vowel found — return unchanged


# ponytail: self-check (runs only when executed directly).
if __name__ == "__main__":
    cases = [("ni3", "nǐ"), ("chuang1", "chuāng"), ("hao3", "hǎo"),
             ("nv3", "nǚ"), ("le5", "le"), ("xiang1", "xiāng"),
             ("gui4", "guì"), ("lü4", "lǜ"), ("n", "n"),
             # iao compound (liǎo3 → liao3 → liǎo)
             ("liao3", "liǎo")]
    for inp, expected in cases:
        out = tone_number_to_mark(inp)
        status = "OK" if out == expected else f"FAIL (got {out!r})"
        print(f"  {inp!r:>12} → {out!r:<10}  {status}")


# ---------------------------------------------------------------------------
# Column-index builder (unchanged logic, updated COLUMN_MAP reference)
# ---------------------------------------------------------------------------

_ALT_COLUMNS: dict[str, list[str]] = {
    "hanzi": ["Word", "Hanzi", "word"],
    "pinyin": ["Pinyin", "pinyin", "Portuguese"],
    "english": ["Eng.Tran", "English", "english", "Translation"],
    "frequency": ["W.million", "Frequency", "frequency", "Freq"],
    "part_of_speech": ["Dominant.PoS", "PoS", "POS", "PartOfSpeech"],
}


def _build_column_indices(header: list[str]) -> dict[str, int]:
    """Return {logical_field: column_index} by matching header names case-insensitively."""
    lower_header = [h.lower() for h in header]
    indices: dict[str, int] = {}
    for field, preferred in COLUMN_MAP.items():
        idx = -1
        try:
            idx = lower_header.index(preferred.lower())
        except ValueError:
            for alt in _ALT_COLUMNS.get(field, []):
                try:
                    idx = lower_header.index(alt.lower())
                    break
                except ValueError:
                    continue
        if idx == -1:
            raise ValueError(
                f"Could not find column for field {field!r} "
                f"(tried {preferred!r} and {_ALT_COLUMNS.get(field, [])!r}). "
                f"Header: {header!r}"
            )
        indices[field] = idx
    return indices


def _open_csv(path: str) -> tuple[Path, str]:
    """Open a TSV file, trying utf-8 then gbk. Returns (path, encoding)."""
    p = Path(path)
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
        try:
            p.read_text(encoding=enc)
            return p, enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode {path!r} with any known encoding")


def _guess_delimiter(sample: str) -> str:
    """Guess delimiter from the first non-empty line."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return "\t"  # SUBTLEX-CH is tab-separated


def _normalize_reading(reading: str) -> str:
    """Strip tone marks from a mixed-format reading → pure tone-number form.

    E.g. ``liǎo3`` → ``liao3`` (tone-mark → tone-number).
    Readings already in pure tone-number format are returned unchanged.
    """
    # Map each tone-mark to its (base_vowel, tone_digit).
    for marks, (base, digit) in [
        ("ǚ", ("ü", "4")), ("ǜ", ("ü", "4")), ("ǘ", ("ü", "2")), ("Ǜ", ("ü", "4")),
        ("ǔ", ("u", "4")), ("ù", ("u", "4")), ("ú", ("u", "2")), ("û", ("u", "1")),
        ("ǒ", ("o", "4")), ("ò", ("o", "4")), ("ó", ("o", "2")), ("ô", ("o", "1")),
        ("ǐ", ("i", "3")), ("ì", ("i", "4")), ("í", ("i", "2")), ("î", ("i", "1")),
        ("ě", ("e", "3")), ("è", ("e", "4")), ("é", ("e", "2")), ("ê", ("e", "1")),
        ("ǎ", ("a", "3")), ("à", ("a", "4")), ("á", ("a", "2")), ("â", ("a", "1")),
        ("ā", ("a", "1")), ("ō", ("o", "1")), ("ē", ("e", "1")), ("ī", ("i", "1")), ("ū", ("u", "1")), ("ǖ", ("ü", "1")),
    ]:
        if marks in reading:
            # Replace tone-mark with base vowel, strip any existing trailing
            # tone-digit (tone-marked readings always carry the tone digit at
            # the end, e.g. liǎo3), then append the correct tone digit.
            # ponytail: handles iao/iao3 and neutral-tone cases correctly.
            base_str = reading.replace(marks, base)
            if base_str and base_str[-1].isdigit():
                base_str = base_str[:-1]
            return base_str + digit
    return reading


def _split_polyphonic_pinyin(pinyin_raw: str | None) -> list[str]:
    """Split a polyphonic pinyin string on '/' → list of individual readings.

    E.g. ``le5//liǎo3`` → ``['le5', 'liao3']`` (liǎo3 normalized to tone-number).
    Readings already in pure tone-number format are returned unchanged.
    """
    if not pinyin_raw:
        return []
    readings = [_normalize_reading(r.strip()) for r in pinyin_raw.split("/") if r.strip()]
    return readings


def parse(path: str) -> list[dict[str, Any]]:
    """Parse a SUBTLEX-CH-format TSV file.

    Returns a list of entry dicts with keys:
      - ``hanzi`` (str)
      - ``pinyin`` (str) — tone-marked, one reading per entry
      - ``english`` (str or None)
      - ``frequency`` (float or None)
      - ``part_of_speech`` (str or None)

    One input row with polyphonic pinyin (e.g. ``le5//liǎo3``) yields one
    dict per reading, each with the same hanzi and frequency.

    Malformed rows are logged and skipped.

    Arguments:
        path: path to the TSV file.

    Returns:
        List of entry dicts.
    """
    p, encoding = _open_csv(path)
    text = p.read_text(encoding=encoding)
    delimiter = _guess_delimiter(text.splitlines()[0] if "\n" in text else text)

    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    rows = list(reader)

    if not rows:
        return []

    # Skip leading non-header lines when tab-delimited.
    # Real SUBTLEX-CH has 2 metadata lines before the header.
    # ponytail: skip exactly 2 lines when delimiter is tab; this is safe
    # because the header is always the 3rd line in that format.
    start = 3 if delimiter == "\t" else 0
    header = [h.strip() for h in rows[start - 1]] if start else [h.strip() for h in rows[0]]

    try:
        col_idx = _build_column_indices(header)
    except ValueError as exc:
        logger.warning("Column mapping failed: %s", exc)
        return []

    entries: list[dict[str, Any]] = []
    for lineno, row in enumerate(rows[start:], start=start + 1):
        if len(row) < len(header):
            logger.debug("Skipping short row %d (got %d cols, expected %d): %r",
                         lineno, len(row), len(header), row)
            continue
        try:
            hanzi = row[col_idx["hanzi"]].strip()
            if not hanzi:
                logger.debug("Skipping row %d: empty hanzi", lineno)
                continue

            pinyin_raw = row[col_idx["pinyin"]].strip() or None
            english_raw = row[col_idx["english"]].strip() or None
            freq_raw = row[col_idx["frequency"]].strip() or None
            pos_raw = row[col_idx["part_of_speech"]].strip() or None

            frequency: float | None = None
            if freq_raw is not None:
                try:
                    frequency = float(freq_raw)
                except ValueError:
                    logger.debug("Skipping row %d: non-numeric frequency %r", lineno, freq_raw)
                    continue

            # One entry per pinyin reading (split polyphonic on '/').
            readings = _split_polyphonic_pinyin(pinyin_raw)
            if not readings:
                # No pinyin at all — still create one entry with None pinyin.
                readings = [None]

            for reading in readings:
                pinyin_marked: str | None = None
                if reading is not None:
                    # Convert tone-number to tone-mark notation.
                    pinyin_marked = tone_number_to_mark(reading)

                entries.append({
                    "hanzi": hanzi,
                    "pinyin": pinyin_marked,
                    "english": english_raw or None,
                    "frequency": frequency,
                    "part_of_speech": pos_raw,
                })
        except Exception as exc:
            logger.warning("Skipping row %d due to error: %s", lineno, exc)
            continue

    return entries
