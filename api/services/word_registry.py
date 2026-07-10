"""Word registry: create and list word units on the local vault.

This module implements SPEC §6 AC2: when a sentence is saved for the
first time, every jieba-segmented token in its ``words[]``/``word_refs[]``
arrays becomes (or maps to) a word unit under
``<vault_root>/units/words/<id>.json``, where ``id`` is the tone-marked
pinyin (OQ2). A compound like ``口水`` is one word unit with id
``kǒushuǐ`` (OQ3).

Auto-create semantics: ``ensure_word_unit`` is a no-op if the word
already exists on disk. It never overwrites an existing word file. The
lexical-edge update for AC3 is a separate task and is not performed
here; this function only creates the empty shell with
``connections: []``.

All I/O goes through :mod:`api.services.unit_writer`.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from api.services.id_counter import next_id
from api.services.unit_writer import read_unit, unit_path, write_unit

log = logging.getLogger(__name__)


def _today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return date.today().isoformat()


def _find_word_by_hanzi_pinyin(
    vault_root: str, hanzi: str, pinyin: str
) -> dict | None:
    """Scan word files for one matching ``(hanzi, pinyin)``.

    ponytail: O(n) scan per lookup. Fine for <1000 words. Upgrade
    path: SQLite ``word`` table lookup (v0.5.5).
    """
    for word in list_all_words(vault_root):
        props = word.get("properties", {})
        if props.get("hanzi") == hanzi and props.get("pinyin") == pinyin:
            return word
    return None


def ensure_word_unit(
    vault_root: str,
    hanzi: str,
    pinyin: str,
    english: str = "",
    meaning: str = "",
) -> dict:
    """If a word unit for this ``hanzi``/``pinyin`` does not exist,
    create one. Return the (possibly newly created) word unit dict.

    The word's ``id`` is a typed counter id (``W1``, ``C1``, etc.)
    assigned by :mod:`api.services.id_counter`. The filename matches
    the id (``W1.json``). The word's ``name`` is the hanzi.

    Properties default to ``{hanzi, pinyin, english, meaning, groups: [],
    antonyms: []}``.

    Side effect: writes a new word unit file if it does not already
    exist. If the file already exists, it is NOT overwritten; the
    existing dict is returned.
    """
    if not isinstance(hanzi, str) or not hanzi:
        raise ValueError("hanzi must be a non-empty string")
    if not isinstance(pinyin, str) or not pinyin:
        raise ValueError("pinyin must be a non-empty string")
    if not isinstance(english, str):
        raise ValueError("english must be a string")
    if not isinstance(meaning, str):
        raise ValueError("meaning must be a string")

    existing = _find_word_by_hanzi_pinyin(vault_root, hanzi, pinyin)
    if existing is not None:
        return existing

    unit_type = "compound" if len(hanzi) >= 2 else "word"
    word_id = next_id(vault_root, unit_type)

    today = _today_iso()
    word_unit: dict[str, Any] = {
        "id": word_id,
        "type": unit_type,
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
        "created": today,
        "updated": today,
        "author_confirmed": True,
    }
    write_unit(vault_root, word_unit)
    return word_unit


def ensure_word_unit_from_dict(
    vault_root: str,
    word_id: str,
    hanzi: str,
    pinyin: str,
    english: str = "",
) -> dict:
    """Materialize a word/compound unit from a dictionary token.

    The unit id comes directly from the dict (not from ``id_counter.json``).
    This function is idempotent: if the file already exists it is NOT
    overwritten; the existing dict is returned.

    Arguments:
        vault_root: path to the vault root.
        word_id: dict-assigned id (e.g. ``"W4"``, ``"C12"``).
        hanzi: the hanzi string for this token.
        pinyin: pinyin from the dict (may be empty string).
        english: english gloss from the dict (may be empty string).
    """
    path = unit_path(vault_root, "word", word_id)
    if path.is_file():
        return read_unit(vault_root, "word", word_id)

    unit_type = "compound" if len(hanzi) >= 2 else "word"
    today = _today_iso()
    word_unit: dict[str, Any] = {
        "id": word_id,
        "type": unit_type,
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
        "created": today,
        "updated": today,
        "author_confirmed": True,
    }
    write_unit(vault_root, word_unit)
    return word_unit


def backfill_word_english(
    vault_root: str,
    word_id: str,
    english: str,
) -> bool:
    """If the word unit exists and its ``properties.english`` is empty,
    set it to ``english`` and persist. Returns True iff a write
    happened.

    ``word_id`` is the typed id (e.g. ``"W1"``).
    """
    if not isinstance(word_id, str) or not word_id.strip():
        return False
    if not isinstance(english, str) or not english.strip():
        return False
    path = unit_path(vault_root, "word", word_id)
    if not path.is_file():
        return False
    try:
        existing = read_unit(vault_root, "word", word_id)
    except (OSError, ValueError) as exc:
        log.warning("backfill_word_english: read failed for %s: %s", word_id, exc)
        return False
    properties = existing.get("properties")
    if not isinstance(properties, dict):
        return False
    current = properties.get("english")
    if not isinstance(current, str) or current.strip():
        return False
    properties["english"] = english.strip()
    existing["properties"] = properties
    existing["updated"] = _today_iso()
    try:
        write_unit(vault_root, existing)
    except OSError as exc:
        log.warning("backfill_word_english: write failed for %s: %s", word_id, exc)
        return False
    return True


def list_all_words(vault_root: str) -> list[dict]:
    """Return all word units under ``<vault_root>/units/words/``.

    Files that fail to deserialize as a dict are skipped (a corrupt
    file should not break the listing for the rest of the vault). The
    result is not sorted; callers that need stable ordering should
    sort by ``id`` themselves.
    """
    words_dir = Path(vault_root) / "units" / "words"
    if not words_dir.is_dir():
        return []

    results: list[dict] = []
    for entry in sorted(words_dir.iterdir()):
        if not entry.is_file() or entry.suffix != ".json":
            continue
        try:
            with open(entry, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        except (OSError, ValueError):
            # Corrupt or unreadable file — skip rather than blow up
            # the whole listing. A repair tool can pick this up later.
            continue
        if isinstance(data, dict):
            results.append(data)
    return results
