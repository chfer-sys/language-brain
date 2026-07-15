"""GET /api/vault/list — browse vault by category (v0.7).

Provides a read-only, paginated listing of units filtered by category
(type). Each item returns only ``id``, ``name`` (hanzi), and
``snippet`` (pinyin) — deliberately omitting ``english`` and
``meaning`` (payload hygiene, per AC2).

Sorting
-------
* ``sort=id`` — alphanumeric ascending (default), matching the sort
  order returned by :func:`unit_writer.list_units_by_type`.
* ``sort=pinyin`` — ascending string comparison of the ``snippet``
  field (pinyin A→Z).

Pagination
----------
``limit`` and ``offset`` operate on the full filtered+sorted list.
``total`` reports the count of all matching units before pagination.

Error cases
-----------
* Unknown ``type`` → 422 (FastAPI validates the ``VaultListType``
  literal).
* ``limit`` outside ``[1, 200]`` → 422.
* ``offset < 0`` → 422.
* Unknown ``sort`` value → 422 (FastAPI validates the
  ``Literal["id", "pinyin"]``).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.config import settings
from api.schemas import VaultListItem, VaultListParams, VaultListResponse
from api.services.unit_writer import list_units_by_type

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vault", tags=["vault"])


@router.get("/list", response_model=VaultListResponse)
def list_vault(
    params: VaultListParams = Depends(),
) -> VaultListResponse:
    """GET /api/vault/list — list units by category.

    Query parameters (all passed as a :class:`VaultListParams` model):

    * ``type`` — required; one of ``sentence``, ``word``, ``compound``,
      ``group``.
    * ``limit`` — items per page, default 50, range ``[1, 200]``.
    * ``offset`` — zero-based skip, default 0, must be ``>= 0``.
    * ``sort`` — ``id`` (default) or ``pinyin``.

    Response shape::

        {
          "type": "sentence",
          "total": 142,
          "limit": 50,
          "offset": 0,
          "sort": "id",
          "items": [
            {"id": "S1", "name": "我流口水了", "snippet": "wǒ liú kǒu shuǐ le"}
          ]
        }

    The response never contains ``english`` or ``meaning`` keys (AC2).
    """
    unit_type: str = params.type
    limit: int = params.limit
    offset: int = params.offset
    sort: str = params.sort

    # Fetch all units of the requested type. list_units_by_type already
    # returns them sorted by id (ascending). We re-sort in-memory only
    # when the caller asks for pinyin order.
    #
    # ponytail: ceiling — word and compound share the "words/" subdirectory,
    # so list_units_by_type returns both W{n} and C{n} files. We filter
    # by id prefix here to produce the correct subset per type.
    # Upgrade path: if a future storage model gives compounds their own
    # subdirectory, this filter becomes unnecessary.
    raw_units = list_units_by_type(settings.vault, unit_type)
    if unit_type == "word":
        raw_units = [u for u in raw_units if u["id"].startswith("W")]
    elif unit_type == "compound":
        raw_units = [u for u in raw_units if u["id"].startswith("C")]
    elif unit_type == "sentence":
        raw_units = [u for u in raw_units if u["id"].startswith("S")]
    elif unit_type == "group":
        raw_units = [u for u in raw_units if u["id"].startswith("G")]

    # Apply sort preference. id = already sorted by list_units_by_type;
    # pinyin = secondary sort on the snippet (pinyin) field, ascending A→Z.
    if sort == "pinyin":
        sorted_units = sorted(
            raw_units, key=lambda u: u.get("properties", {}).get("pinyin", "")
        )
    else:
        sorted_units = raw_units  # already sorted by id

    total = len(sorted_units)

    # Apply pagination.
    paginated = sorted_units[offset : offset + limit]

    # Map to the minimal VaultListItem shape (AC2: no english/meaning).
    items = [
        VaultListItem(
            id=u["id"],
            name=u.get("properties", {}).get("hanzi", u["id"]),
            snippet=u.get("properties", {}).get("pinyin", ""),
        )
        for u in paginated
    ]

    log.info(
        "GET /api/vault/list type=%r limit=%d offset=%d sort=%r total=%d returned=%d",
        unit_type,
        limit,
        offset,
        sort,
        total,
        len(items),
    )

    return VaultListResponse(
        type=unit_type,
        total=total,
        limit=limit,
        offset=offset,
        sort=sort,
        items=items,
    )


__all__ = ["router"]
