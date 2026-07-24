"""GET /api/units/{id} — read a single unit by id.

SPEC §5.2 lists ``GET /api/units/{id}`` as the author-view endpoint
(it may include ``english``/``meaning``). The id alone does not tell
us the unit type, so this endpoint tries each of the three sub-
directories (sentences, words, groups) and returns the first hit.

Returns the full unit dict as it lives on disk. The frontend can
then render properties and connections for the author view.

When the resolved unit is a word, the response additionally carries
``containing_sentences`` — a list of sentence ids whose
``properties.word_refs`` includes this word's id, or whose
``properties.words`` includes this word's hanzi. This is the
data backing AC27: "A word detail page shows the word's properties
AND every sentence unit whose words list contains this word's hanzi."
The word never renders alone — it is always shown in context of its
sentences.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from api.config import settings
from api.services.db import get_connection
from api.services.unit_writer import (
    VALID_UNIT_TYPES,
    list_units_by_type,
    read_unit,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/units", tags=["units"])


def _sentence_ids_containing_word(vault_root: str, word_id: str, word_hanzi: str) -> list[str]:
    """Return sentence ids whose word_refs include ``word_id`` or whose
    words include ``word_hanzi``.

    Used to back AC27 (word detail page lists containing sentences).
    v0.10: query the ``edge`` table (kind=word_of) instead of scanning
    all sentence JSON files. Falls back to JSON scan if SQLite returns
    no results (edge table may not be populated yet).

    Order is by sentence id ascending (stable).
    """
    # v0.10: query edge table for word_of edges where target is this word.
    import sqlite3

    try:
        conn = get_connection(vault_root)
        try:
            rows = conn.execute(
                "SELECT source_id FROM edge WHERE target_id = ? AND kind = 'word_of' ORDER BY source_id",
                (word_id,),
            ).fetchall()
            if rows:
                return [row["source_id"] for row in rows]
        finally:
            conn.close()
    except sqlite3.OperationalError:
        # Table doesn't exist yet (database not migrated). Fall through to JSON scan.
        pass

    # Fallback: JSON scan (edge table may not be populated yet).
    sentences_dir = Path(vault_root) / "units" / "sentences"
    if not sentences_dir.is_dir():
        return []
    hits: list[str] = []
    for path in sorted(sentences_dir.glob("*.json")):
        try:
            unit = read_unit(vault_root, "sentence", path.stem)
        except (FileNotFoundError, ValueError) as exc:
            log.warning("skipping malformed sentence %s: %s", path, exc)
            continue
        props = unit.get("properties", {})
        word_refs = props.get("word_refs", []) or []
        words = props.get("words", []) or []
        if word_id in word_refs or word_hanzi in words:
            hits.append(unit["id"])
    return hits


def _connection_name(vault_root: str, target_id: str, name_cache: dict[str, str]) -> str:
    """Return the display name for a connection target id, using name_cache
    to avoid reading the same target unit multiple times.

    Tries each unit type in order; returns the id as-is if not found.
    """
    if target_id in name_cache:
        return name_cache[target_id]
    for unit_type in VALID_UNIT_TYPES:
        try:
            unit = read_unit(vault_root, unit_type, target_id)
        except FileNotFoundError:
            continue
        props = unit.get("properties", {})
        # sentence/word/compound: hanzi; group: display_name
        name = props.get("hanzi") or props.get("display_name") or target_id
        name_cache[target_id] = name
        return name
    # Target unit not found in any type — fall back to the bare id.
    name_cache[target_id] = target_id
    return target_id


@router.get("/{unit_id}")
def get_unit(unit_id: str) -> dict:
    """Return a single unit (sentence, word, or group) by id.

    Tries each of the three sub-directories in turn. Returns the
    first match. If the id is not found in any of the three,
    responds with 404.

    Note: per SPEC §3.5, the author view may include ``english`` and
    ``meaning`` fields — the response is the full unit as stored on
    disk. The frontend is responsible for hiding those fields in
    contexts where they are not allowed (search results, AC20).

    When the unit is a word, the response carries an extra
    ``containing_sentences`` list (sorted, stable). See
    :func:`_sentence_ids_containing_word`.
    """
    if not unit_id or not unit_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="unit_id must be a non-empty string",
        )

    # Shared name cache: avoids re-reading the same target unit for each
    # connection.  Persists for the lifetime of this single request.
    _name_cache: dict[str, str] = {}
    last_error: Exception | None = None
    for unit_type in VALID_UNIT_TYPES:
        try:
            data = read_unit(settings.vault, unit_type, unit_id)
        except FileNotFoundError as exc:
            last_error = exc
            continue
        except ValueError as exc:
            # A unit file that does not deserialize is a real error,
            # not just 'not found in this directory'. Surface it.
            log.error(
                "unit file for id=%r type=%r is malformed: %s",
                unit_id,
                unit_type,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"unit file for id {unit_id!r} is malformed",
            ) from exc

        if data.get("type") == "word":
            props = data.get("properties", {})
            word_hanzi = props.get("hanzi", "") or ""
            sentence_ids = _sentence_ids_containing_word(
                settings.vault, unit_id, word_hanzi
            )
            # ponytail: name_cache shared with connection enrichment below;
            # each sentence is looked up once even if referenced by multiple paths.
            data["containing_sentences"] = [
                {"id": sid, "name": _connection_name(settings.vault, sid, _name_cache)}
                for sid in sentence_ids
            ]

        if data.get("type") == "compound":
            props = data.get("properties", {})
            compound_hanzi = props.get("hanzi", "") or ""
            sentence_ids = _sentence_ids_containing_word(
                settings.vault, unit_id, compound_hanzi
            )
            data["containing_sentences"] = [
                {"id": sid, "name": _connection_name(settings.vault, sid, _name_cache)}
                for sid in sentence_ids
            ]
            # ponytail: O(n) scan over all word files; ceiling is acceptable
            # at MVP scale (solo-dev vault, low thousands of word files);
            # upgrade path is v0.5.5 SQLite word table.
            # v0.10: route through SQLite instead of JSON scan.
            constituent_cache: dict[str, str] = {}
            compound_chars = set(compound_hanzi)
            # Query SQLite for single-character words whose hanzi is in the compound.
            import sqlite3

            try:
                conn = get_connection(settings.vault)
                try:
                    # Build a query that matches single-char words in the compound.
                    # ponytail: ceiling — uses LIKE for each char; upgrade path is
                    # a virtual table or FTS5 query for larger compound char sets.
                    for char in compound_chars:
                        rows = conn.execute(
                            "SELECT id, name FROM unit WHERE type = 'word' AND name = ?",
                            (char,),
                        ).fetchall()
                        for row in rows:
                            wid = row["id"]
                            if wid not in constituent_cache:
                                constituent_cache[wid] = _connection_name(
                                    settings.vault, wid, _name_cache
                                )
                finally:
                    conn.close()
            except sqlite3.OperationalError:
                # Table doesn't exist yet (database not migrated). Fall back to JSON scan.
                for word_unit in list_units_by_type(settings.vault, "word"):
                    if word_unit.get("type") != "word":
                        continue
                    w_props = word_unit.get("properties", {})
                    w_hanzi = w_props.get("hanzi", "") or ""
                    if len(w_hanzi) == 1 and w_hanzi in compound_chars:
                        if word_unit["id"] not in constituent_cache:
                            constituent_cache[word_unit["id"]] = _connection_name(
                                settings.vault, word_unit["id"], _name_cache
                            )
            data["constituent_characters"] = [
                {"id": wid, "name": name}
                for wid, name in sorted(constituent_cache.items())
            ]

        # Enrich every connection with its target's display name (hanzi or
        # display_name).  Missing targets fall back to the bare id — we never
        # raise here so a corrupt vault can't break the API for valid units.
        for conn in data.get("connections", []):
            conn["name"] = _connection_name(settings.vault, conn["to"], _name_cache)

        # Resolve word-unit antonym IDs → display names (hanzi).  Sentences
        # store hanzi strings directly so resolution is a no-op for them.
        # ponytail: this is O(k) lookups where k = len(antonyms).  The
        # _connection_name helper uses _name_cache so repeat calls for the
        # same id are free.  Accepted ceiling: very large antonym lists
        # (>1000) would do O(1000) disk reads; upgrade path is to batch-load
        # all word units once per request (v0.5.5 SQLite word table).
        if data.get("type") == "word":
            resolved_antonyms: list[str] = []
            for a in data.get("properties", {}).get("antonyms", []):
                if isinstance(a, str) and a:
                    resolved_antonyms.append(_connection_name(settings.vault, a, _name_cache))
                else:
                    resolved_antonyms.append(a)
            data["properties"]["antonyms"] = resolved_antonyms

        # Resolve word_refs (sentence property) IDs → hanzi.
        # Add a parallel word_refs_resolved dict so the frontend can
        # display the actual hanzi while keeping the ID in the href.
        if data.get("type") == "sentence":
            word_refs = data.get("properties", {}).get("word_refs", []) or []
            data["word_refs_resolved"] = {
                ref_id: _connection_name(settings.vault, ref_id, _name_cache)
                for ref_id in word_refs
                if isinstance(ref_id, str)
            }

        # Resolve groups (word/compound property) group-IDs → display_name.
        # Sentences store group handles (e.g. "travel") directly, no resolution needed.
        if data.get("type") in ("word", "compound"):
            groups = data.get("properties", {}).get("groups", []) or []
            data["groups_resolved"] = {
                grp_id: _connection_name(settings.vault, grp_id, _name_cache)
                for grp_id in groups
                if isinstance(grp_id, str)
            }

        return data

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"unit {unit_id!r} not found in any of {sorted(VALID_UNIT_TYPES)}",
    ) from last_error


__all__ = ["router"]