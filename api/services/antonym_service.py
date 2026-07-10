"""Antonym mirror service: bidirectional wiring of word-level antonym edges.

This module provides two operations:

* :func:`mirror_antonyms` — idempotent, additive-only wiring of a single
  (word, antonym) pair in both directions. Used by the commit path to
  record that two words are antonyms of each other.

* :func:`save_word_antonyms` — set a word's antonyms array to an explicit
  list, with reciprocal removal: any antonym id that was in the word's
  array but is NOT in the new list has this word removed from ITS
  antonyms array (AC6). Used by the word-edit path when a user
  explicitly changes a word's antonym list.

Both operations use :func:`api.services.unit_writer.write_unit` (atomic
per-file via ``os.replace``). Cross-file atomicity is not guaranteed —
the connector's symmetry pass reconciles any drift on the next
reindex or commit (ponytail: accepted gap for v0.5.4 single-user
runtime).

No new runtime dependencies. Uses only stdlib and existing vault I/O
helpers.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from api.services.unit_writer import read_unit, write_unit

log = logging.getLogger(__name__)


def _today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return date.today().isoformat()


def _read_word_antonyms(unit: dict) -> list[str]:
    """Return the validated antonyms list from a word unit, or []."""
    props = unit.get("properties")
    if not isinstance(props, dict):
        return []
    raw = props.get("antonyms")
    if not isinstance(raw, list):
        return []
    return [a for a in raw if isinstance(a, str) and a]


def _write_word_antonyms(unit: dict, antonyms: list[str]) -> None:
    """Set unit.properties.antonyms, repairing structure if needed."""
    props = unit.get("properties")
    if not isinstance(props, dict):
        props = {}
        unit["properties"] = props
    props["antonyms"] = antonyms
    unit["updated"] = _today_iso()


def _word_path(vault_root: str, word_id: str) -> Path:
    """Return the path to a word unit file."""
    root = Path(vault_root)
    return root / "units" / "words" / f"{word_id}.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def mirror_antonyms(vault_root: str, word_id: str, antonym_id: str) -> None:
    """Ensure both words reference each other in their antonyms arrays.

    Idempotent. Reads both word units via read_unit, appends the missing
    id to each one's properties.antonyms if not already present, writes
    both via write_unit. Skips self-references and non-existent target
    files. This is the extracted version of commit_sentence.py step 3b.

    Parameters
    ----------
    vault_root:
        Path to the vault root.
    word_id:
        The source word's typed id (W{n} / C{n}).
    antonym_id:
        The target word's typed id (W{n} / C{n}).
    """
    if not word_id or not antonym_id:
        return
    if word_id == antonym_id:
        return

    # Read source word; skip if missing.
    src_path = _word_path(vault_root, word_id)
    if not src_path.is_file():
        return
    try:
        src_unit = read_unit(vault_root, "word", word_id)
    except (OSError, ValueError) as exc:
        log.warning("mirror_antonyms: could not read word_id=%r: %s", word_id, exc)
        return

    # Read target word; skip if missing.
    tgt_path = _word_path(vault_root, antonym_id)
    if not tgt_path.is_file():
        return
    try:
        tgt_unit = read_unit(vault_root, "word", antonym_id)
    except (OSError, ValueError) as exc:
        log.warning("mirror_antonyms: could not read antonym_id=%r: %s", antonym_id, exc)
        return

    # Build updated antonyms lists (deduplicated, preserving order).
    src_antonyms = _read_word_antonyms(src_unit)
    tgt_antonyms = _read_word_antonyms(tgt_unit)

    changed = False

    if antonym_id not in src_antonyms:
        src_antonyms.append(antonym_id)
        changed = True

    if word_id not in tgt_antonyms:
        tgt_antonyms.append(word_id)
        changed = True

    if not changed:
        return  # Both already had each other — nothing to do

    _write_word_antonyms(src_unit, src_antonyms)
    _write_word_antonyms(tgt_unit, tgt_antonyms)

    write_unit(vault_root, src_unit)
    write_unit(vault_root, tgt_unit)


def save_word_antonyms(
    vault_root: str, word_id: str, antonym_ids: list[str]
) -> None:
    """Set word_id's antonyms to antonym_ids, mirroring reciprocally.

    For each antonym_id in antonym_ids:
        - If not already in word_id's antonyms: add it (and add word_id
          to antonym_id's antonyms).
    For each id that WAS in word_id's antonyms but is NOT in antonym_ids:
        - Remove word_id from that id's antonyms array (AC6: deletion
          removes the reciprocal).
    Finally: update word_id's own antonyms array to match antonym_ids.

    All writes via write_unit (atomic per-file). Cross-file atomicity
    is not guaranteed — the connector's opposite pass reconciles any
    drift on the next commit/reindex.

    Parameters
    ----------
    vault_root:
        Path to the vault root.
    word_id:
        The word whose antonyms are being set.
    antonym_ids:
        The desired complete antonyms list for word_id.
    """
    if not word_id:
        return

    # Normalize input.
    new_antonyms: list[str] = []
    seen: set[str] = set()
    for a in antonym_ids:
        if isinstance(a, str) and a and a not in seen:
            seen.add(a)
            new_antonyms.append(a)

    # Read current state of word_id (skip if missing).
    src_path = _word_path(vault_root, word_id)
    if not src_path.is_file():
        log.warning("save_word_antonyms: word_id=%r not found; skipping", word_id)
        return
    try:
        src_unit = read_unit(vault_root, "word", word_id)
    except (OSError, ValueError) as exc:
        log.warning("save_word_antonyms: could not read word_id=%r: %s", word_id, exc)
        return

    old_antonyms = _read_word_antonyms(src_unit)

    # --- Phase 1: add new antonyms (and their reciprocals) ---
    for antonym_id in new_antonyms:
        if antonym_id == word_id:
            continue
        mirror_antonyms(vault_root, word_id, antonym_id)

    # --- Phase 2: remove stale reciprocals ---
    # For each id that was in old_antonyms but is NOT in new_antonyms,
    # remove word_id from that id's antonyms array.
    new_set = set(new_antonyms)
    for stale_id in old_antonyms:
        if stale_id in new_set or stale_id == word_id:
            continue
        # Remove word_id from stale_id's antonyms.
        stale_path = _word_path(vault_root, stale_id)
        if not stale_path.is_file():
            continue
        try:
            stale_unit = read_unit(vault_root, "word", stale_id)
        except (OSError, ValueError) as exc:
            log.warning(
                "save_word_antonyms: could not read stale_id=%r: %s", stale_id, exc
            )
            continue
        stale_antonyms = _read_word_antonyms(stale_unit)
        if word_id in stale_antonyms:
            stale_antonyms.remove(word_id)
            _write_word_antonyms(stale_unit, stale_antonyms)
            write_unit(vault_root, stale_unit)

    # --- Phase 3: update word_id's own array ---
    _write_word_antonyms(src_unit, new_antonyms)
    write_unit(vault_root, src_unit)
