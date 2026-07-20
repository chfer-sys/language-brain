"""PUT /api/words/{word_id} — edit a word or compound unit's user-editable fields.

Editable fields: ``english``, ``meaning``, ``groups``, ``antonyms``.
``hanzi`` and ``pinyin`` are read-only (they come from the dictionary).

Group edit semantics: REPLACE — the new group list is canonical. A
group not in the new list has this unit REMOVED from its ``members``.

Antonym edit semantics: the existing ``mirror_antonyms`` helper handles
additions symmetrically; this route provides the symmetric removal via
an inline ``_unmirror_antonym_pair`` helper.

The route handles BOTH ``word`` and ``compound`` types — they share the
``words/`` directory and have identical property shapes. The concrete
type is read from the unit's ``type`` field on disk.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, status

from api.config import settings
from api.schemas import EditWordRequest, EditWordResponse, ProposedGroupOut
from api.services.antonym_service import mirror_antonyms
from api.services.connector import compute_connections
from api.services.embedder import Embedder, get_embedder
from api.services.group_helpers import ensure_groups_from_proposed
from api.services.group_registry import add_member_to_group, ensure_group_unit, remove_member_from_group
from api.services.unit_writer import read_unit, write_unit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/words", tags=["words"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today_iso() -> str:
    return date.today().isoformat()


def _get_embedder() -> Embedder:
    return get_embedder()


def _resolve_group_ids(groups: list[ProposedGroupOut | str]) -> list[str]:
    """Extract the canonical group id from a groups list.

    ``ProposedGroupOut`` dicts carry ``id`` as the slug; bare strings
    ARE the slug.
    """
    out: list[str] = []
    for g in groups:
        if isinstance(g, ProposedGroupOut):
            out.append(g.id)
        elif isinstance(g, str):
            out.append(g)
    return out


def _unmirror_antonym_pair(
    vault_root: str, word_id: str, other_id: str
) -> None:
    """Remove the symmetric antonym relationship between two word units.

    * Removes ``other_id`` from ``word_id.properties.antonyms``.
    * Removes ``word_id`` from ``other_id.properties.antonyms``.
    * Removes any ``opposite`` connection edges between the two units.

    Idempotent — a missing unit or already-removed entry is a no-op.
    """
    if not word_id or not other_id or word_id == other_id:
        return

    # Read source.
    try:
        src = read_unit(vault_root, "word", word_id)
    except (FileNotFoundError, OSError, ValueError):
        return

    # Read target.
    try:
        tgt = read_unit(vault_root, "word", other_id)
    except (FileNotFoundError, OSError, ValueError):
        return

    changed = False

    # Remove other_id from src's antonyms.
    src_antonyms = src.get("properties", {}).get("antonyms")
    if isinstance(src_antonyms, list) and other_id in src_antonyms:
        src_antonyms.remove(other_id)
        changed = True

    # Remove word_id from tgt's antonyms.
    tgt_antonyms = tgt.get("properties", {}).get("antonyms")
    if isinstance(tgt_antonyms, list) and word_id in tgt_antonyms:
        tgt_antonyms.remove(word_id)
        changed = True

    # Remove opposite connections in both directions.
    def _remove_opposite_edge(unit: dict, to_remove: str) -> bool:
        connections = unit.get("connections")
        if not isinstance(connections, list):
            return False
        orig_len = len(connections)
        unit["connections"] = [
            c
            for c in connections
            if not (
                isinstance(c, dict)
                and c.get("kind") == "opposite"
                and c.get("to") == to_remove
            )
        ]
        return len(unit["connections"]) < orig_len

    src_changed_conn = _remove_opposite_edge(src, other_id)
    tgt_changed_conn = _remove_opposite_edge(tgt, word_id)

    if changed or src_changed_conn or tgt_changed_conn:
        src["updated"] = _today_iso()
        tgt["updated"] = _today_iso()
        write_unit(vault_root, src)
        write_unit(vault_root, tgt)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.put(
    "/{word_id}",
    response_model=EditWordResponse,
    status_code=status.HTTP_200_OK,
)
def edit_word(word_id: str, body: EditWordRequest) -> EditWordResponse:
    """Edit a word or compound unit's user-editable fields.

    The unit is located by trying ``word`` first, then ``compound``
    (they share the ``words/`` directory). Returns 404 if neither
    file exists or if the on-disk type is neither ``word`` nor
    ``compound``.

    Editable fields: ``english``, ``meaning``, ``groups``, ``antonyms``.
    ``hanzi`` and ``pinyin`` are not editable — they are sourced from
    the dictionary.

    Group semantics: REPLACE. The new groups list is canonical; this
    unit is removed from any group that was in the old list but is not
    in the new list.

    Antonym semantics: additions are wired bidirectionally via
    ``mirror_antonyms``; removals are unwired bidirectionally via the
    inline ``_unmirror_antonym_pair`` helper in this module.
    """
    vault_root = settings.vault

    # ------------------------------------------------------------------
    # Step 1 — locate the unit (word then compound — they share words/ dir)
    # ------------------------------------------------------------------
    unit: dict[str, Any] | None = None
    found_type: str = ""

    for candidate_type in ("word", "compound"):
        try:
            candidate = read_unit(vault_root, candidate_type, word_id)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            log.warning("read_unit failed for type=%r id=%r: %s", candidate_type, word_id, exc)
            continue
        unit = candidate
        # Use the on-disk type field, not candidate_type, because "word"
        # and "compound" both map to the "words/" directory — a file
        # written as compound is readable via the "word" path.
        found_type = candidate.get("type", "")
        if found_type in ("word", "compound"):
            break
        # Found a file but it's the wrong type — keep searching.
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Word or compound {word_id!r} not found",
        )

    if unit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Word or compound {word_id!r} not found",
        )

    # ------------------------------------------------------------------
    # Step 2 — defense: confirm the on-disk type is word or compound
    # ------------------------------------------------------------------
    if found_type not in ("word", "compound"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unit {word_id!r} has type {found_type!r}; only word/compound are editable",
        )

    # ------------------------------------------------------------------
    # Step 3 — diff groups (REPLACE semantics)
    # ------------------------------------------------------------------
    old_group_ids: set[str] = set(unit.get("properties", {}).get("groups", []))
    new_group_ids: set[str] = set(_resolve_group_ids(body.groups))

    groups_added: list[str] = sorted(new_group_ids - old_group_ids)
    groups_removed: list[str] = sorted(old_group_ids - new_group_ids)

    # Normalize proposed groups for ensure_groups_from_proposed.
    normalized_proposed: list[ProposedGroupOut | str | dict[str, Any]] = []
    for g in body.groups:
        if isinstance(g, ProposedGroupOut):
            normalized_proposed.append(g.model_dump())
        elif isinstance(g, str):
            normalized_proposed.append(g)

    # Ensure new groups + add this unit as a member.
    group_units = ensure_groups_from_proposed(vault_root, normalized_proposed)
    for group_unit in group_units:
        try:
            add_member_to_group(vault_root, group_id=group_unit["id"], member_id=word_id)
        except (FileNotFoundError, ValueError) as exc:
            log.warning("could not add word=%r to group=%r: %s", word_id, group_unit.get("id"), exc)

    # Remove from groups that are no longer referenced.
    for gid in groups_removed:
        remove_member_from_group(vault_root, gid, word_id)

    # ------------------------------------------------------------------
    # Step 4 — diff antonyms
    # ------------------------------------------------------------------
    old_antonyms: list[str] = unit.get("properties", {}).get("antonyms", [])
    if not isinstance(old_antonyms, list):
        old_antonyms = []
    old_antonyms_set: set[str] = {a for a in old_antonyms if isinstance(a, str) and a}

    new_antonyms_set: set[str] = {a for a in body.antonyms if isinstance(a, str) and a}

    antonyms_added: list[str] = sorted(new_antonyms_set - old_antonyms_set)
    antonyms_removed: list[str] = sorted(old_antonyms_set - new_antonyms_set)

    # Additions: mirror symmetrically.
    for other_id in antonyms_added:
        mirror_antonyms(vault_root, word_id, other_id)

    # Removals: unmirror symmetrically.
    for other_id in antonyms_removed:
        _unmirror_antonym_pair(vault_root, word_id, other_id)

    # ------------------------------------------------------------------
    # Step 5 — update properties
    # ------------------------------------------------------------------
    properties = unit.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
        unit["properties"] = properties

    properties["english"] = body.english
    properties["meaning"] = body.meaning
    properties["groups"] = sorted(new_group_ids)
    properties["antonyms"] = sorted(new_antonyms_set)

    # ------------------------------------------------------------------
    # Step 6 — update timestamp
    # ------------------------------------------------------------------
    unit["updated"] = _today_iso()

    # ------------------------------------------------------------------
    # Step 7 — write
    # ------------------------------------------------------------------
    write_unit(vault_root, unit)

    # ------------------------------------------------------------------
    # Step 8 — run connector
    # ------------------------------------------------------------------
    try:
        summary: dict[str, Any] = compute_connections(
            vault_root, embedder=_get_embedder()
        )
    except Exception as exc:
        log.error(
            "compute_connections failed for word=%r: %s",
            word_id,
            type(exc).__name__,
        )
        summary = {
            "sentences_touched": 0,
            "words_touched": 0,
            "lexical_pairs": 0,
            "semantic_pairs": 0,
            "group_pairs": 0,
            "opposite_pairs": 0,
            "skipped": 0,
        }

    # ------------------------------------------------------------------
    # Step 9 — build response
    # ------------------------------------------------------------------
    connections_summary: dict[str, int] = {
        str(k): int(v) for k, v in summary.items() if isinstance(v, (int, float))
    }

    log.info("edited word id=%s type=%s", word_id, found_type)
    return EditWordResponse(
        id=word_id,
        type=found_type,
        updated=unit["updated"],
        connections_summary=connections_summary,
        groups_added=groups_added,
        groups_removed=groups_removed,
        antonyms_added=antonyms_added,
        antonyms_removed=antonyms_removed,
    )


__all__ = ["router"]
