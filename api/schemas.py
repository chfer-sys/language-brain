"""Pydantic request/response models for the HTTP API.

These models are the contract between the SvelteKit frontend and
the FastAPI backend. They live in ``api/schemas.py`` so the route
modules can import them without circular dependency on the services.
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# POST /api/sentences — propose labels
# ---------------------------------------------------------------------------


class ProposeSentencesRequest(BaseModel):
    """Body for the propose-labels endpoint.

    ``hanzi`` is required. ``note`` is an optional English hint the
    user typed to disambiguate (e.g. a sentence with two readings).
    """

    hanzi: str = Field(..., min_length=1, description="The hanzi sentence to label.")
    note: str = Field(default="", description="Optional English hint from the user.")


class ProposedGroupOut(BaseModel):
    """One group proposal inside a propose-labels response."""

    id: str
    display_name: str = ""
    description: str = ""


class ProposeSentencesResponse(BaseModel):
    """Body of the propose-labels response.

    Mirrors the AI client's ``ProposedLabels`` dataclass. All seven
    fields are populated per SPEC §6 AC6.

    ``degraded`` is True when the response was served from a local
    fallback (dictionary lookup) because the AI provider was
    unavailable. The frontend may use this to surface a review
    banner; at runtime it is ignored.
    """

    pinyin: str
    english: str
    meaning: str
    words: list[str]
    word_refs: list[str]
    groups: list[ProposedGroupOut]
    antonyms: list[str]
    degraded: bool = False


# ---------------------------------------------------------------------------
# POST /api/sentences/commit — save a sentence with its proposed labels
# ---------------------------------------------------------------------------


class CommitSentenceRequest(BaseModel):
    """Body for the sentence-commit endpoint.

    The user has reviewed (and possibly edited) the AI's proposed
    labels and is now saving the sentence to the vault. The route
    assigns the sentence id via a monotonic counter (``S1``, ``S2``,
    ...); the caller no longer provides an id.
    """

    hanzi: str = Field(..., min_length=1, description="The hanzi sentence.")
    pinyin: str = Field(..., min_length=1, description="Tone-marked pinyin for the sentence.")
    english: str = Field(default="", description="Short English gloss (per AC6).")
    meaning: str = Field(default="", description="Richer gloss that powers semantic search (per AC7).")
    words: list[str] = Field(default_factory=list, description="Hanzi tokens from segmentation.")
    word_refs: list[str] = Field(
        default_factory=list,
        description="Tone-marked-pinyin of word units referenced by this sentence.",
    )
    groups: list[Union[ProposedGroupOut, str]] = Field(
        default_factory=list,
        description="Proposed group names (bare slug strings or ProposedGroupOut dicts).",
    )
    antonyms: list[str] = Field(
        default_factory=list,
        description="Hanzi strings (e.g. '饱') or bare pinyin (e.g. 'bǎo') "
        "identifying antonym words. On commit these are resolved to "
        "typed word-unit ids (W{n} / C{n}) and wired bidirectionally "
        "into word.properties.antonyms.",
    )
    author_confirmed: bool = Field(
        default=True,
        description="True if the user confirmed the AI's proposed labels.",
    )


class CommitSentenceResponse(BaseModel):
    """Body of the sentence-commit response.

    The route returns the saved sentence id plus a flat
    ``connections_summary`` dict copied from
    :func:`api.services.connector.compute_connections`. The
    keys are stable so the frontend can render "saved; updated
    4 lexical, 2 group edges" style messages.
    """

    id: str
    connections_summary: dict[str, int]


# ---------------------------------------------------------------------------
# Shared types (used by T19 commit, T20+ search, etc.)
# ---------------------------------------------------------------------------


UnitType = Literal["sentence", "word", "compound", "group"]
ConnectionKind = Literal["lexical", "semantic", "group", "opposite"]
VaultListType = Literal["sentence", "word", "compound", "group"]


# ---------------------------------------------------------------------------
# GET /api/search — search (T20+)
# ---------------------------------------------------------------------------


class SearchResultItem(BaseModel):
    """One entry in a :class:`SearchResponse`.

    Fields mirror SPEC §5.3:

    * ``id`` — the unit's stable id.
    * ``type`` — one of ``"sentence"`` or ``"word"`` (group units are
      not returned by lexical search; they're surfaced via
      ``/api/groups/{id}`` instead, per SPEC §5.3).
    * ``name`` — the display string. For sentences, this is the
      hanzi (``properties.hanzi``); for words, also hanzi.
    * ``snippet`` — a secondary display string. For sentences and
      words, this is the pinyin (``properties.pinyin``).
    * ``score`` — the similarity score. For T20 (lexical only),
      this is the Jaccard value over hanzi tokens, in ``(0.0, 1.0]``.
    * ``kinds`` — the connection kinds that link the unit back to
      the query's neighborhood. T20 leaves this empty for all hits
      because lexical ranker is naive (it doesn't look at the
      connection graph). T22/T23 will populate it from the
      ``connections`` array on each unit.
    * ``containing_sentences`` — for word hits, up to 3 example
      sentence hanzi strings that contain this word (per SPEC §2.2:
      word units never stand alone in the UI). None for sentence/group.
    """

    id: str
    type: str
    name: str
    snippet: str
    score: float
    kinds: list[str] = Field(default_factory=list)
    containing_sentences: list[str] | None = None


class SearchResponse(BaseModel):
    """Body of the search response (SPEC §5.3).

    ``query`` echoes the input string so the frontend can render
    "results for X" without bookkeeping. ``results`` is the ranked
    list — T20 sorts by Jaccard descending (tie-break by id
    ascending) and caps at the requested ``limit``.
    """

    query: str
    results: list[SearchResultItem]


# ---------------------------------------------------------------------------
# GET /api/search/suggest — autocomplete (T26, SPEC §5.3, §6 AC27b)
# ---------------------------------------------------------------------------


class SuggestionItem(BaseModel):
    """One entry in a :class:`SuggestResponse`.

    Fields mirror SPEC §5.3's autocomplete shape:

    * ``id`` — the unit's stable id.
    * ``type`` — one of ``"sentence"``, ``"word"``, or ``"group"``.
    * ``name`` — the display string the user typed against.
      For sentences and words, this is the unit's
      ``properties.hanzi``; for groups, it is
      ``properties.display_name`` (falling back to the slug id).

    The item intentionally carries no ``english`` or ``meaning``
    fields — that's the AC20/AC27b payload-hygiene invariant
    enforced by :func:`api.services.search.has_english_or_meaning_key`.
    """

    id: str
    type: str
    name: str


class SuggestResponse(BaseModel):
    """Body of the suggest / autocomplete response (SPEC §5.3).

    ``prefix`` echoes the (stripped) input prefix the caller
    supplied, so the frontend can render "matches for X" without
    bookkeeping. ``suggestions`` is the alphabetically-sorted
    list of unit names whose display string starts with
    ``prefix`` (case-insensitive). Empty prefix → ``[]``.
    """

    prefix: str
    suggestions: list[SuggestionItem]


# ---------------------------------------------------------------------------
# GET /api/meanings/{text}/sentences — meaning-based lookup (T27)
# ---------------------------------------------------------------------------


class MeaningSentenceItem(BaseModel):
    """One entry in a :class:`MeaningsResponse`.

    Carries only the fields the frontend needs to render a result
    card. Per SPEC §5.3 and §6 AC27c, ``english`` and ``meaning``
    are intentionally absent — those fields live on the underlying
    sentence unit but the route strips them. The Pydantic schema
    declaration is the canonical gate: any field not listed here
    is dropped by FastAPI's serialization layer.

    Fields
    ------
    id:
        The unit's stable id (e.g. ``"wo-xihuan-chi"``).
    hanzi:
        The unit's ``properties.hanzi`` — the Chinese sentence.
    pinyin:
        The unit's ``properties.pinyin`` — the tone-marked reading.
    score:
        The cosine similarity between the user's English query
        embedding and the unit's ``meaning`` embedding. Bounded
        in ``[-1, 1]`` (in practice ``(0.0, 1.0]`` for hits that
        passed the threshold filter).
    """

    id: str
    hanzi: str
    pinyin: str
    score: float


class MeaningsResponse(BaseModel):
    """Body of the meanings lookup response (SPEC §5.3, §6 AC27c).

    ``query`` echoes the (stripped) English text the caller supplied
    so the frontend can render "results for X" without bookkeeping.
    The query itself is **not** persisted anywhere by this endpoint —
    the service embeds it in-memory and discards both the text and
    the vector once the response has been built.

    ``results`` is the list of sentence units whose ``meaning``
    embedding has cosine similarity to the query above the
    threshold (default 0.6, configurable via the route's
    ``threshold`` query parameter). Empty list means no matches
    were above threshold, the index is empty, or the query was
    empty / whitespace-only.
    """

    query: str
    results: list[MeaningSentenceItem]


# ---------------------------------------------------------------------------
# GET /api/vault/list — browse vault by category (v0.7)
# ---------------------------------------------------------------------------


class VaultListItem(BaseModel):
    """One entry in a :class:`VaultListResponse`.

    Fields are deliberately minimal: only what the browse UI needs to
    render a row. Per SPEC §3 and AC2, ``english`` and ``meaning``
    are intentionally absent — the endpoint never surfaces them.
    """

    id: str
    name: str = Field(description="Hanzi — the unit's display string.")
    snippet: str = Field(description="Pinyin — the unit's tone-marked reading.")


class VaultListResponse(BaseModel):
    """Body of the vault-list response (SPEC §3).

    ``type`` echoes the requested category so the frontend can
    confirm which tab is active. ``total`` is the count of all
    matching units (before pagination). ``items`` is the paginated
    slice; each item carries ``id``, ``name`` (hanzi), and
    ``snippet`` (pinyin) — no ``english`` or ``meaning`` (AC2).
    """

    type: str
    total: int
    limit: int
    offset: int
    sort: str
    items: list[VaultListItem]


class VaultListParams(BaseModel):
    """Query parameters for :func:`api.routes.vault.list_vault`.

    Typed as a Pydantic model so FastAPI's validator machinery can
    enforce the constraints (range checks, literal union) and return
    a descriptive 422 when they are violated.
    """

    type: VaultListType
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    sort: Literal["id", "pinyin"] = "id"


__all__ = [
    "CommitSentenceRequest",
    "CommitSentenceResponse",
    "ConnectionKind",
    "MeaningSentenceItem",
    "MeaningsResponse",
    "ProposedGroupOut",
    "ProposeSentencesRequest",
    "ProposeSentencesResponse",
    "SearchResponse",
    "SearchResultItem",
    "SuggestionItem",
    "SuggestResponse",
    "UnitType",
    "VaultListItem",
    "VaultListParams",
    "VaultListResponse",
    "VaultListType",
]
