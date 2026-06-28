"""GET /api/units/{id} — read a single unit by id.

SPEC §5.2 lists ``GET /api/units/{id}`` as the author-view endpoint
(it may include ``english``/``meaning``). The id alone does not tell
us the unit type, so this endpoint tries each of the three sub-
directories (sentences, words, groups) and returns the first hit.

Returns the full unit dict as it lives on disk. The frontend can
then render properties and connections for the author view.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from api.config import settings
from api.services.unit_writer import (
    VALID_UNIT_TYPES,
    read_unit,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/units", tags=["units"])


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
    """
    if not unit_id or not unit_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="unit_id must be a non-empty string",
        )

    last_error: Exception | None = None
    for unit_type in VALID_UNIT_TYPES:
        try:
            return read_unit(settings.vault, unit_type, unit_id)
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

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"unit {unit_id!r} not found in any of {sorted(VALID_UNIT_TYPES)}",
    ) from last_error


__all__ = ["router"]