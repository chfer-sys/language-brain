"""GET /api/search — search for units (T20+).

T20 implements the lexical half of SPEC §5.3's search endpoint
(AC16). T21 adds semantic search; T22–T23 wire the ``kinds``
toggle into the response; T24 enforces the ``english``/``meaning``
payload-hygiene invariants (AC20). This module is the *route
layer* — it parses query params, calls into
:mod:`api.services.search`, and shapes the JSON response per
SPEC §5.3.

Endpoint shape (SPEC §5.3)
--------------------------
``GET /api/search?q=<query>&limit=<N>&types=<csv>&kinds=<csv>``

* ``q`` (required, ``min_length=1``) — the search query.
* ``limit`` (optional, default ``20``, range ``1..100``) — maximum
  number of hits to return.
* ``types`` (optional, comma-separated) — restrict to one or more
  of ``sentence``, ``word``. Default = both. Group units are not
  searchable via this endpoint; per SPEC §5.3 they live behind
  ``/api/groups/{id}``.
* ``kinds`` (optional, comma-separated) — connection-kind filter.
  T20 ignores ``kinds``; the field is parsed and stored in the
  response shape so T22/T23 can wire it without changing the
  schema. Accepted values are the four kinds from SPEC §2.4
  (``lexical``, ``semantic``, ``group``, ``opposite``).

Response shape (SPEC §5.3)
--------------------------
``{"query": str, "results": [{"id": str, "type": str, "name": str,
"snippet": str, "kinds": [str], "score": float}, ...]}``

For T20:

* ``kinds`` is always ``[]`` because the lexical ranker does not
  look at the connection graph — that's the connector's domain.
  T22/T23 will populate ``kinds`` from the matched unit's
  ``connections`` field.
* ``name`` is the hanzi (``properties.hanzi``) and ``snippet`` is
  the pinyin (``properties.pinyin``). Neither field contains
  natural-language English (AC21) and the payload never contains
  ``english``/``meaning`` keys (AC20).

Error handling
--------------
* Missing ``q`` — FastAPI returns 422 via the ``min_length=1``
  constraint.
* ``limit`` outside ``[1, 100]`` — 422.
* Any other error — 500 with a generic message; the underlying
  exception is logged at ERROR.

Logging
-------
A successful search emits one INFO line at the service layer
(:func:`api.services.search.lexical_search`). The route adds
no extra logging so test output stays uncluttered.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from api.config import settings
from api.schemas import SearchResponse, SearchResultItem
from api.services.search import (
    SearchHit,
    lexical_search,
    merge_hits_with_kinds,
    semantic_search,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


#: The closed set of valid ``types`` filter values for the search
#: route. Mirrors the closed set in :mod:`api.services.search`
#: but duplicated here so the route can validate the CSV string
#: before calling the service (and reject unknown values with
#: 422 rather than silently returning []).
_VALID_TYPES: frozenset[str] = frozenset({"sentence", "word"})

#: The closed set of valid ``kinds`` filter values. T20 ignores
#: the filter but parses it; T22/T23 will use the set to gate
#: which connection kinds contribute to a result's ``kinds`` list.
_VALID_KINDS: frozenset[str] = frozenset(
    {"lexical", "semantic", "group", "opposite"}
)


def _parse_csv(raw: str | None) -> list[str] | None:
    """Parse a comma-separated query-string value into a list.

    Returns ``None`` for missing or empty input (the route's
    default). Returns a list of stripped, non-empty tokens for
    non-empty input. The tokens are returned in the order they
    appeared in the CSV string — the service layer handles
    de-duplication and validation against the closed sets.
    """
    if raw is None:
        return None
    parts = [p.strip() for p in raw.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    return parts


def _hit_to_item(hit: SearchHit, kinds: list[str]) -> SearchResultItem:
    """Map a :class:`SearchHit` to its API response shape.

    ``kinds`` is the alphabetically-sorted list of connection kinds
    that produced at least one hit for ``(hit.unit_id, hit.unit_type)``
    in the kinded merge (T22). The route layer pre-sorts before
    calling so the JSON serialization is deterministic regardless
    of set-iteration order.
    """
    return SearchResultItem(
        id=hit.unit_id,
        type=hit.unit_type,
        name=hit.name,
        snippet=hit.snippet,
        score=hit.score,
        kinds=sorted(kinds),
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="The search query."),
    limit: int = Query(default=20, ge=1, le=100),
    types: str | None = Query(
        default=None,
        description=(
            "Comma-separated unit types to include. Default: "
            "sentence,word. Valid values: sentence, word."
        ),
    ),
    kinds: str | None = Query(
        default=None,
        description=(
            "Comma-separated connection kinds to include. "
            "Default: all. T20 ignores this; T22+ will gate it."
        ),
    ),
) -> SearchResponse:
    """GET /api/search — search for units.

    T20 implements lexical search only. Semantic search and the
    toggle/filter behavior land in T21–T23. The endpoint never
    returns ``english`` or ``meaning`` keys (AC20) and never
    returns ASCII a-z runs of length >= 3 in ``name`` or
    ``snippet`` (AC21), because those fields are populated
    from the unit's ``properties.hanzi`` and
    ``properties.pinyin`` respectively.
    """
    parsed_types = _parse_csv(types)
    parsed_kinds = _parse_csv(kinds)

    # Validate types against the closed set early. An unknown
    # value returns 422 rather than silently dropping the
    # request — a typo ("sentences" vs "sentence") should fail
    # loud so the user knows their filter didn't take effect.
    if parsed_types is not None:
        bad = [t for t in parsed_types if t not in _VALID_TYPES]
        if bad:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"unknown type(s): {bad}; valid types: "
                    f"{sorted(_VALID_TYPES)}"
                ),
            )

    # Validate kinds against the closed set; the filter is
    # ignored for T20 but a typo shouldn't sneak through.
    if parsed_kinds is not None:
        bad = [k for k in parsed_kinds if k not in _VALID_KINDS]
        if bad:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"unknown kind(s): {bad}; valid kinds: "
                    f"{sorted(_VALID_KINDS)}"
                ),
            )

    # The lexical service accepts ``types=None`` as "both". We
    # pass the parsed list through as-is when the caller
    # supplied one (the service does its own validation), or
    # ``None`` when the caller didn't.
    service_types = parsed_types  # may be None

    vault_root = settings.vault

    # T21: run both lexical and semantic passes and merge. T22
    # will filter by the ``kinds`` toggle; T23 will filter by
    # ``types``. For now, all hits flow through.
    lexical_hits = lexical_search(
        vault_root,
        query=q,
        limit=limit,
        types=service_types,
    )
    # Semantic search only operates on sentences (per SPEC §6 AC9,
    # only sentences are in the FAISS index). When the caller
    # restricts ``types`` to ``["word"]``, the semantic pass is
    # a no-op anyway, but we still call it because the merge is
    # cheap and the kinds-toggle in T22 may want to know what
    # kinds contributed.
    semantic_hits: list[SearchHit] = []
    if (service_types is None) or ("sentence" in service_types):
        semantic_hits = semantic_search(vault_root, query=q, limit=limit)

    merged, kinds_by_key = merge_hits_with_kinds(
        ("lexical", lexical_hits),
        ("semantic", semantic_hits),
    )

    # AC18 — kinds toggle. When the caller restricted ``parsed_kinds``
    # (e.g. ``?kinds=semantic``), drop any hit whose producing-kinds
    # set has empty intersection with the request set. This is what
    # "disabling the semantic toggle removes all semantic-kind results"
    # means in the SPEC.
    if parsed_kinds is not None:
        allowed = set(parsed_kinds)
        merged = [
            hit
            for hit in merged
            if kinds_by_key[(hit.unit_id, hit.unit_type)] & allowed
        ]

    # Apply the limit AFTER merge so the user gets the best of
    # both passes, not just the lexical top-N.
    if limit > 0:
        merged = merged[:limit]

    items = [
        _hit_to_item(
            hit,
            kinds=sorted(
                kinds_by_key[(hit.unit_id, hit.unit_type)]
            ),
        )
        for hit in merged
    ]

    log.info(
        "GET /api/search q=%r limit=%d types=%s kinds=%s lexical=%d semantic=%d returned=%d",
        q,
        limit,
        parsed_types,
        parsed_kinds,
        len(lexical_hits),
        len(semantic_hits),
        len(items),
    )

    return SearchResponse(query=q, results=items)


__all__ = ["router"]