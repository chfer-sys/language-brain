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
from api.services.unit_writer import (
    VALID_UNIT_TYPES,
    read_unit,
    unit_path,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/units", tags=["units"])


def _sentence_ids_containing_word(vault_root: str, word_id: str, word_hanzi: str) -> list[str]:
    """Return sentence ids whose word_refs include ``word_id`` or whose
    words include ``word_hanzi``.

    Used to back AC27 (word detail page lists containing sentences).
    Each sentence unit's ``properties.words`` is the list of hanzi
    tokens; ``properties.word_refs`` is the matching list of
    tone-marked-pinyin ids (per OQ2). A match on either is a hit.

    Order is filesystem-glob order, which is stable enough for MVP.
    """
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
            data["containing_sentences"] = _sentence_ids_containing_word(
                settings.vault, unit_id, word_hanzi
            )

        return data

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"unit {unit_id!r} not found in any of {sorted(VALID_UNIT_TYPES)}",
    ) from last_error


__all__ = ["router"]