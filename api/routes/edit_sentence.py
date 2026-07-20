"""PUT /api/sentences/{sentence_id} — edit an existing sentence.

Editable fields: ``pinyin``, ``english``, ``meaning``, ``words``,
``word_refs``, ``groups``, ``antonyms``.

``hanzi`` is READ-ONLY — changing it would force re-segmentation.
The client echoes it back; the server validates it matches the
existing value and rejects a 422 on mismatch.

Group edit semantics: REPLACE. The new ``groups`` list is canonical;
the sentence is removed from any prior group not in the new list.

Flow (mirrors :func:`api.routes.commit_sentence` structure)
----------------------------------------------------
1. Load existing sentence. 404 if missing.
2. Validate ``hanzi`` matches existing. 422 on mismatch.
3. Diff old vs new groups: remove from dropped, add to new.
4. Update ``properties`` in memory (except ``hanzi``/``name``).
5. Write updated sentence unit.
6. Re-wire lexical edges for updated ``word_refs``.
7. Mirror antonyms into word-level ``antonyms`` arrays.
8. Run :func:`api.services.connector.compute_connections`.
9. If ``meaning`` changed and is non-empty: update FAISS index.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status

from api.config import settings
from api.schemas import EditSentenceRequest, EditSentenceResponse, ProposedGroupOut
from api.services.connector import compute_connections
from api.services.antonym_resolver import (
    normalize_antonyms_for_storage,
    resolve_antonym_to_word_id,
)
from api.services.embedder import Embedder, get_embedder
from api.services.group_helpers import ensure_groups_from_proposed
from api.services.group_registry import add_member_to_group, remove_member_from_group
from api.services.indexer import Index
from api.services.lexical import add_lexical_edge_to_word
from api.services.unit_writer import read_unit, write_unit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sentences", tags=["sentences"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    from datetime import date

    return date.today().isoformat()


def _get_embedder() -> Embedder:
    """Return the process embedder, with a monkey-patchable seam."""
    return get_embedder()


def _normalize_groups_input(
    raw: list[ProposedGroupOut | str],
) -> list[ProposedGroupOut | str | dict[str, Any]]:
    """Coerce ``ProposedGroupOut`` instances into plain dicts."""
    out: list[ProposedGroupOut | str | dict[str, Any]] = []
    for item in raw:
        if isinstance(item, ProposedGroupOut):
            out.append(item.model_dump())
        else:
            out.append(item)
    return out


def _extract_group_ids(groups: list[ProposedGroupOut | str | dict[str, Any]]) -> list[str]:
    """Extract bare group ids from a groups list (mixed shapes)."""
    out: list[str] = []
    for g in groups:
        if isinstance(g, str):
            out.append(g)
        elif isinstance(g, dict):
            gid = g.get("id")
            if isinstance(gid, str) and gid:
                out.append(gid)
    return out


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.put(
    "/{sentence_id}",
    response_model=EditSentenceResponse,
    status_code=status.HTTP_200_OK,
)
def edit_sentence(
    sentence_id: str,
    body: EditSentenceRequest,
) -> EditSentenceResponse:
    """Edit an existing sentence.

    Raises 404 if the sentence does not exist.
    Raises 422 if ``hanzi`` does not match the existing sentence's hanzi.
    """
    vault_root = settings.vault
    today = _today_iso()

    # ------------------------------------------------------------------
    # Step 1 — load existing sentence
    # ------------------------------------------------------------------
    try:
        sentence: dict[str, Any] = read_unit(vault_root, "sentence", sentence_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"sentence {sentence_id!r} not found",
        )

    existing_hanzi = sentence.get("properties", {}).get("hanzi", "")

    # ------------------------------------------------------------------
    # Step 2 — validate hanzi match (read-only guard)
    # ------------------------------------------------------------------
    if body.hanzi != existing_hanzi:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"hanzi mismatch: sentence has {existing_hanzi!r}, "
            f"request carries {body.hanzi!r} (hanzi is read-only)",
        )

    old_props = sentence.get("properties", {})
    old_groups_raw: list[ProposedGroupOut | str | dict[str, Any]] = old_props.get("groups", [])
    old_group_ids: set[str] = set(_extract_group_ids(old_groups_raw))

    new_groups_raw: list[ProposedGroupOut | str] = list(body.groups)
    new_group_ids: set[str] = set(_extract_group_ids(new_groups_raw))

    # ------------------------------------------------------------------
    # Step 3 — diff groups: remove from dropped, add to new
    # ------------------------------------------------------------------
    groups_removed: list[str] = sorted(old_group_ids - new_group_ids)
    groups_added: list[str] = sorted(new_group_ids - old_group_ids)

    # Remove from dropped groups.
    for gid in groups_removed:
        try:
            remove_member_from_group(vault_root, gid, sentence_id)
        except FileNotFoundError:
            log.warning("group=%r not found when removing sentence=%r", gid, sentence_id)
        except ValueError:
            log.warning("could not remove sentence=%r from group=%r", sentence_id, gid)

    # Ensure and add to new groups.
    normalized_new = _normalize_groups_input(new_groups_raw)
    group_units = ensure_groups_from_proposed(vault_root, normalized_new)
    for group_unit in group_units:
        gid = group_unit.get("id")
        if gid in old_group_ids:
            continue  # already a member, skip
        try:
            add_member_to_group(vault_root, group_id=gid, member_id=sentence_id)
        except (FileNotFoundError, ValueError):
            log.warning("could not add sentence=%r to group=%r", sentence_id, gid)

    # ------------------------------------------------------------------
    # Step 4 — update properties in memory (hanzi and name untouched)
    # ------------------------------------------------------------------
    old_meaning = old_props.get("meaning", "")

    updated_props: dict[str, Any] = dict(old_props)
    updated_props["pinyin"] = body.pinyin
    updated_props["english"] = body.english
    updated_props["meaning"] = body.meaning
    updated_props["words"] = list(body.words)
    updated_props["word_refs"] = list(body.word_refs)
    updated_props["groups"] = _extract_group_ids(new_groups_raw)
    updated_props["antonyms"] = normalize_antonyms_for_storage(list(body.antonyms))

    sentence["properties"] = updated_props
    sentence["updated"] = today

    # ------------------------------------------------------------------
    # Step 5 — write sentence unit
    # ------------------------------------------------------------------
    write_unit(vault_root, sentence)

    # ------------------------------------------------------------------
    # Step 6 — re-wire lexical edges for updated word_refs
    # ------------------------------------------------------------------
    for word_id in body.word_refs:
        try:
            add_lexical_edge_to_word(
                vault_root, word_id=word_id, sentence_id=sentence_id, score=1.0
            )
        except FileNotFoundError:
            log.warning(
                "word unit missing for id=%r; skipping lexical edge", word_id
            )

    # ------------------------------------------------------------------
    # Step 7 — mirror sentence-level antonyms into word-level antonyms
    # ------------------------------------------------------------------
    from api.services.antonym_service import mirror_antonyms
    from api.services.word_registry import list_all_words

    existing_word_units = list_all_words(vault_root)
    for word_id in body.word_refs:
        for antonym_entry in body.antonyms:
            if not isinstance(antonym_entry, str) or not antonym_entry.strip():
                continue
            try:
                antonym_id = resolve_antonym_to_word_id(
                    vault_root,
                    antonym_entry.strip(),
                    existing_word_units=existing_word_units,
                )
            except ValueError:
                continue
            if antonym_id and antonym_id != word_id:
                mirror_antonyms(vault_root, word_id, antonym_id)

    # ------------------------------------------------------------------
    # Step 8 — run the connector
    # ------------------------------------------------------------------
    try:
        summary: dict[str, Any] = compute_connections(
            vault_root, embedder=_get_embedder()
        )
    except Exception as exc:  # pragma: no cover
        log.error(
            "compute_connections failed for sentence=%r: %s",
            sentence_id,
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
    # Step 9 — update FAISS index if meaning changed and is non-empty
    # ------------------------------------------------------------------
    meaning_changed = body.meaning != old_meaning
    if meaning_changed and body.meaning.strip():
        try:
            index = Index.load_or_empty(vault_root)
            embedder = _get_embedder()
            if sentence_id in index:
                index.update(sentence_id, embedder.embed(body.meaning))
            else:
                index.add(sentence_id, embedder.embed(body.meaning))
            index.save(vault_root)
        except Exception as exc:  # pragma: no cover
            log.error(
                "FAISS index update failed for sentence=%r: %s",
                sentence_id,
                type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # Step 10 — assemble the response
    # ------------------------------------------------------------------
    connections_summary: dict[str, int] = {
        str(k): int(v) for k, v in summary.items() if isinstance(v, (int, float))
    }
    log.info("edited sentence id=%s", sentence_id)
    return EditSentenceResponse(
        id=sentence_id,
        updated=today,
        connections_summary=connections_summary,
        groups_added=groups_added,
        groups_removed=groups_removed,
    )


__all__ = ["router"]
