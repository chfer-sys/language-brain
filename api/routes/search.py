"""GET /api/search — search for units (T20+).

T20 implements the lexical half of SPEC §5.3's search endpoint
(AC16). T21 adds semantic search; T22 wires the ``kinds``
toggle into the response; T23 extends ``types`` to include
``group``; T24 enforces the ``english``/``meaning`` payload
hygiene invariants (AC20). This module is the *route layer* —
it parses query params, calls into :mod:`api.services.search`,
and shapes the JSON response per SPEC §5.3.

Endpoint shape (SPEC §5.3)
--------------------------
``GET /api/search?q=<query>&limit=<N>&types=<csv>&kinds=<csv>``

* ``q`` (required, ``min_length=1``) — the search query.
* ``limit`` (optional, default ``20``, range ``1..100``) — maximum
  number of hits to return.
* ``types`` (optional, comma-separated) — restrict to one or more
  of ``sentence``, ``word``, ``group``. Default = all three.
  T23 added ``group``; group hits are still exposed through the
  kinds-toggle plumbing as ``lexical`` matches (the group ranker
  runs as part of the lexical pass).
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

from fastapi import APIRouter, Path, Query

from api.config import settings
from api.schemas import (
    MeaningSentenceItem,
    MeaningsResponse,
    SearchResponse,
    SearchResultItem,
    SuggestResponse,
)
from api.services.search import (
    SearchHit,
    lexical_search,
    meanings_search,
    merge_hits_with_kinds,
    semantic_search,
    suggest_units,
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
_VALID_TYPES: frozenset[str] = frozenset({"sentence", "word", "group"})

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


@router.get("/search/suggest", response_model=SuggestResponse)
def suggest(
    q: str = Query(
        ...,
        min_length=1,
        description=(
            "The prefix to autocomplete. Must be non-empty after "
            "the route's whitespace strip; whitespace-only input "
            "returns 422."
        ),
    ),
    limit: int = Query(default=5, ge=1, le=20),
    types: str | None = Query(
        default=None,
        description=(
            "Comma-separated unit types to include. Default: "
            "sentence,word,group. Valid values: sentence, word, group."
        ),
    ),
) -> SuggestResponse:
    """GET /api/search/suggest — autocomplete unit names (T26).

    Implements SPEC §5.3's autocomplete endpoint and satisfies
    SPEC §6 AC27b. Returns up to ``limit`` (default 5, max 20)
    unit names whose display string starts with ``q``, sorted
    alphabetically. The response payload intentionally carries
    no ``english`` or ``meaning`` keys (AC20/AC27b invariant).

    Matching is prefix-based and case-insensitive:

    * Sentence units match against ``properties.hanzi``.
    * Word units match against ``properties.hanzi``.
    * Group units match against ``properties.display_name``;
      if that's empty, the match falls back to the slug id.

    The response shape is::

        {
          "prefix": "<stripped input>",
          "suggestions": [
            {"id": "...", "type": "sentence|word|group", "name": "..."},
            ...
          ]
        }

    Errors
    ------
    * Missing ``q`` or ``q=""`` — FastAPI returns 422 via
      ``min_length=1``.
    * ``q`` containing only whitespace — the route strips it and
      raises 422 (the stripped result is empty).
    * ``limit`` outside ``[1, 20]`` — 422.
    * Unknown ``types`` value — 422 (matches the main search
      route's behavior).
    """
    stripped = q.strip()
    if not stripped:
        # The Query() validator only enforces min_length=1 on the
        # raw string. A whitespace-only string passes that check
        # but is meaningless to the suggester, so we reject it
        # explicitly here rather than returning an empty list
        # silently.
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="q must be non-empty after stripping whitespace",
        )

    parsed_types = _parse_csv(types)
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

    vault_root = settings.vault
    items = suggest_units(
        vault_root,
        prefix=stripped,
        limit=limit,
        types=parsed_types,
    )

    log.info(
        "GET /api/search/suggest q=%r limit=%d types=%s returned=%d",
        stripped,
        limit,
        parsed_types,
        len(items),
    )

    return SuggestResponse(prefix=stripped, suggestions=items)  # type: ignore[arg-type]


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="The search query."),
    limit: int = Query(default=20, ge=1, le=100),
    types: str | None = Query(
        default=None,
        description=(
            "Comma-separated unit types to include. Default: "
            "sentence,word,group. Valid values: sentence, word, group."
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


@router.get("/meanings/{text}/sentences", response_model=MeaningsResponse)
def meanings_sentences(
    text: str = Path(
        ...,
        min_length=1,
        description=(
            "The English meaning fragment to look up. The text is "
            "embedded in-memory and discarded after the response — "
            "it is never persisted and never logged at INFO level."
        ),
    ),
    threshold: float = Query(
        default=0.6,
        ge=0.0,
        le=1.0,
        description=(
            "Cosine-similarity cutoff in [0.0, 1.0]. Hits at or below "
            "this value are dropped. Defaults to 0.6 per SPEC §6 AC27c."
        ),
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of sentence units to return.",
    ),
) -> MeaningsResponse:
    """GET /api/meanings/{text}/sentences — meaning-based lookup (T27).

    Implements SPEC §5.3's meaning-lookup endpoint and satisfies
    SPEC §6 AC27c. Given an English ``text`` path parameter,
    returns all sentence units whose ``meaning`` field is
    semantically similar to the query (FAISS cosine > threshold).

    The response payload contains only ``id``, ``hanzi``,
    ``pinyin``, and ``score`` per result. ``english`` and
    ``meaning`` are intentionally absent from both the service-
    layer dict and the Pydantic response model — FastAPI's
    serialization strips any field not declared on the model, so
    the two layers stay in lockstep by construction.

    Privacy
    -------
    The user's query text is held only in this function's local
    ``text`` parameter and the embedded vector; both are GC'd
    once the response is built. The INFO log line emitted on
    completion records only the response size, threshold, and
    limit — never the query text itself. This matches the SPEC's
    AC27c privacy posture: user input must not enter the shared
    log stream.

    Errors
    ------
    * Missing ``text`` or ``text=""`` — FastAPI returns 422 via
      the route's ``min_length=1`` constraint.
    * ``text`` containing only whitespace — the route strips it
      and raises 422 (the stripped result is empty).
    * ``threshold`` outside ``[0.0, 1.0]`` — 422 (Pydantic).
    * ``limit`` outside ``[1, 100]`` — 422 (Pydantic).
    """
    # ``min_length=1`` on the Path() validator only checks raw
    # string length. A whitespace-only path (e.g. ``%20%20``)
    # passes that check but is meaningless to the embedder, so
    # we strip and reject it explicitly — mirroring the
    # ``suggest`` route's whitespace guard.
    stripped = text.strip()
    if not stripped:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="text must be non-empty after stripping whitespace",
        )

    vault_root = settings.vault
    raw_items = meanings_search(
        vault_root,
        text=stripped,
        threshold=threshold,
        limit=limit,
    )

    items: list[MeaningSentenceItem] = [
        MeaningSentenceItem(
            id=item["id"],
            hanzi=item["hanzi"],
            pinyin=item["pinyin"],
            score=item["score"],
        )
        for item in raw_items
    ]

    # Privacy: the INFO log records the response size, the
    # threshold, and the limit — never the user's query text.
    # This is the SPEC §6 AC27c privacy requirement: user
    # English text must not enter the shared log stream.
    log.info(
        "GET /api/meanings/.../sentences threshold=%.4f limit=%d returned=%d",
        threshold,
        limit,
        len(items),
    )

    return MeaningsResponse(query=stripped, results=items)


__all__ = ["router"]