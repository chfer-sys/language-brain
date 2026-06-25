"""Sentence deletion: cascade removal across the vault.

SPEC §6 AC11: deleting a sentence unit must:

1. Remove the sentence file from ``<vault>/units/sentences/``.
2. Remove the sentence's vector from the FAISS index
   (``<vault>/index/``).
3. Remove the sentence id from every word's
   ``connections`` list (any ``kind``).
4. Remove the sentence id from every group's
   ``properties.members`` list.

The deletion is atomic from the caller's perspective — all four
side effects happen before the function returns. Failures during
cascade cleanup are logged but do not roll back the unit-file
deletion; the next reindex / repair pass will surface the
inconsistency.

The function does NOT cascade into:
* Other sentence units (a sentence doesn't appear in another
  sentence's connections list per SPEC §2.4 — connections are
  word→sentence or group→sentence, not sentence→sentence).
* The word units themselves (an orphan word with no containing
  sentences is fine; it's a discoverable bug for the user to fix).
"""

from __future__ import annotations

import logging
from pathlib import Path

from api.services.indexer import Index
from api.services.unit_writer import (
    list_units_by_type,
    list_all_groups_from_disk,
    read_unit,
    write_unit,
)

log = logging.getLogger(__name__)


def delete_sentence(vault_root: str, sentence_id: str) -> dict[str, int]:
    """Delete ``sentence_id`` and cascade the removal.

    Returns a small summary::

        {
            "sentence_deleted": 0 | 1,
            "faiss_removed": 0 | 1,
            "words_updated": <int>,
            "groups_updated": <int>,
        }

    The summary is for diagnostics; the function's success criterion
    is that all four side effects occurred.

    Raises :class:`FileNotFoundError` if the sentence file does
    not exist.
    """
    # 1. Delete the unit file (atomic).
    sentence_path = Path(vault_root) / "units" / "sentences" / f"{sentence_id}.json"
    if not sentence_path.is_file():
        raise FileNotFoundError(f"sentence {sentence_id!r} not found at {sentence_path}")

    sentence = read_unit(vault_root, "sentence", sentence_id)
    sentence_path.unlink()
    summary = {"sentence_deleted": 1, "faiss_removed": 0, "words_updated": 0, "groups_updated": 0}

    # 2. Remove from FAISS index.
    index = Index.load_or_empty(vault_root)
    if index.remove(sentence_id):
        index.save(vault_root)
        summary["faiss_removed"] = 1

    # 3. Cascade to words: every word whose connections list contains
    #    this sentence id has that entry removed.
    for word in list_units_by_type(vault_root, "word"):
        before = word.get("connections", [])
        after = [
            edge
            for edge in before
            if not (
                isinstance(edge, dict)
                and edge.get("to") == sentence_id
            )
        ]
        if len(after) != len(before):
            word["connections"] = after
            write_unit(vault_root, word)
            summary["words_updated"] += 1

    # 4. Cascade to groups: every group whose members list contains
    #    this sentence id has that entry removed.
    for group in list_all_groups_from_disk(vault_root):
        members = group.get("properties", {}).get("members", [])
        if sentence_id in members:
            new_members = [m for m in members if m != sentence_id]
            group.setdefault("properties", {})["members"] = new_members
            write_unit(vault_root, group)
            summary["groups_updated"] += 1

    log.info("delete_sentence %s: %s", sentence_id, summary)
    return summary


__all__ = ["delete_sentence"]
