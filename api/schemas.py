"""Pydantic request/response models for the HTTP API.

These models are the contract between the SvelteKit frontend and
the FastAPI backend. They live in ``api/schemas.py`` so the route
modules can import them without circular dependency on the services.
"""

from __future__ import annotations

from typing import Literal

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
# Shared types (used by T19 commit, T20+ search, etc.)
# ---------------------------------------------------------------------------


UnitType = Literal["sentence", "word", "group"]
ConnectionKind = Literal["lexical", "semantic", "group", "opposite"]


__all__ = [
    "ConnectionKind",
    "ProposedGroupOut",
    "ProposeSentencesRequest",
    "ProposeSentencesResponse",
    "UnitType",
]
