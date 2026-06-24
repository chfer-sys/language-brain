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
from datetime import date
from pathlib import Path
from typing import Any

from api.services.unit_writer import read_unit, unit_path, write_unit


def _today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return date.today().isoformat()


def ensure_word_unit(
    vault_root: str,
    hanzi: str,
    pinyin: str,
    english: str = "",
    meaning: str = "",
) -> dict:
    """If a word unit for this ``hanzi``/``pinyin`` does not exist,
    create one. Return the (possibly newly created) word unit dict.

    The word's ``id`` is its tone-marked pinyin (e.g. ``"chī"``). The
    word's ``name`` is the hanzi. The ``pinyin`` argument MUST include
    tone marks; the id is the pinyin string verbatim. The caller is
    expected to pass a single contiguous token (jieba-segmented); this
    function does not segment.

    Properties default to ``{hanzi, pinyin, english, meaning, groups: [],
    antonyms: []}``. ``english`` and ``meaning`` default to the empty
    string. ``connections`` is always an empty list on creation —
    lexical/semantic/group/opposite edges are a separate concern (AC3+).

    Side effect: writes a new word unit file at
    ``<vault_root>/units/words/<pinyin>.json`` if it does not already
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

    path = unit_path(vault_root, "word", pinyin)
    if path.exists():
        # Idempotent re-save: read the existing unit and return it.
        # We deliberately do NOT re-write, so callers can rely on
        # "ensure" being a true no-op on collision.
        existing = read_unit(vault_root, "word", pinyin)
        # Defensive: if the existing file is malformed (missing id),
        # read_unit would have raised, so we know we have a dict.
        return existing

    today = _today_iso()
    word_unit: dict[str, Any] = {
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
        "created": today,
        "updated": today,
        "author_confirmed": True,
    }
    write_unit(vault_root, word_unit)
    return word_unit


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
