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
    """

    pinyin: str
    english: str
    meaning: str
    words: list[str]
    word_refs: list[str]
    groups: list[ProposedGroupOut]
    antonyms: list[str]


# ---------------------------------------------------------------------------
# POST /api/sentences/commit — save a sentence with its proposed labels
# ---------------------------------------------------------------------------


class CommitSentenceRequest(BaseModel):
    """Body for the sentence-commit endpoint (T19).

    The user has reviewed (and possibly edited) the AI's proposed
    labels and is now saving the sentence to the vault. The route
    assigns the sentence id; the caller provides it as a stable
    slug so re-saves don't churn filenames.

    Fields
    ------
    id:
        The sentence unit's id (e.g. a slugified version of the
        pinyin like ``"wo-xihuan-chi"``, or a date-based id).
        Must be a non-empty string; Pydantic enforces ``min_length=1``
        and the route adds a strip-and-validate pass.
    hanzi, pinyin, english, meaning:
        Core sentence content. ``hanzi`` and ``pinyin`` are
        required (per AC1). ``english`` and ``meaning`` default
        to empty strings so the frontend can omit them when
        author has not supplied them, but ``english`` is required
        by AC6 and the route validates non-empty downstream.
    words, word_refs:
        Tokenization output. ``words`` are the hanzi tokens;
        ``word_refs`` are the matching tone-marked-pinyin ids
        (per OQ2). The route zips them when lengths match and
        creates a word unit per entry in ``word_refs``.
    groups:
        Proposed group names. May mix bare slugs and
        :class:`ProposedGroupOut` dicts (the AI client may
        return either shape). The route passes the list
        unchanged to ``ensure_groups_from_proposed``.
    antonyms:
        Tone-marked pinyin of word ids that this sentence's
        words are antonyms of. Used by the connector's
        opposite-pass to write symmetric ``opposite`` edges.
    author_confirmed:
        Defaults to ``True``. Frontend sets this to ``False``
        if the user explicitly un-confirmed the AI's labels
        before saving.
    """

    id: str = Field(..., min_length=1, description="Stable id for the sentence unit.")
    hanzi: str = Field(..., min_length=1, description="The hanzi sentence.")
    pinyin: str = Field(..., min_length=1, description="Tone-marked pinyin for the sentence.")
    english: str = Field(default="", description="Short English gloss (per AC6).")
    meaning: str = Field(default="", description="Richer gloss that powers semantic search (per AC7).")
    words: list[str] = Field(default_factory=list, description="Hanzi tokens from segmentation.")
    word_refs: list[str] = Field(
        default_factory=list,
        description="Tone-marked-pinyin ids of word units referenced by this sentence.",
    )
    groups: list[Union[ProposedGroupOut, str]] = Field(
        default_factory=list,
        description="Proposed group names (bare slug strings or ProposedGroupOut dicts).",
    )
    antonyms: list[str] = Field(
        default_factory=list,
        description="Pinyin-with-tones of antonym word ids.",
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


UnitType = Literal["sentence", "word", "group"]
ConnectionKind = Literal["lexical", "semantic", "group", "opposite"]


__all__ = [
    "CommitSentenceRequest",
    "CommitSentenceResponse",
    "ConnectionKind",
    "ProposedGroupOut",
    "ProposeSentencesRequest",
    "ProposeSentencesResponse",
    "UnitType",
]
