"""POST /api/sentences — propose labels for a hanzi sentence.

This is the propose step only. No file is written, no word units
are created, no groups are created. The endpoint calls the AI
client (mock or HTTP per configuration), and returns the AI's
labels to the user. The user then edits any field and POSTs to
``/api/sentences/commit`` (implemented in T19) to actually save.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from api.schemas import (
    ProposedGroupOut,
    ProposeSentencesRequest,
    ProposeSentencesResponse,
)
from api.services.ai_client import AIClient, get_ai_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sentences", tags=["sentences"])


def _ai_client_dependency() -> AIClient:
    """FastAPI dependency wrapper around ``get_ai_client``.

    The ``force`` arg is omitted; tests that need a specific client
    type monkey-patch the module-level ``get_ai_client`` function.
    """
    return get_ai_client()


@router.post("", response_model=ProposeSentencesResponse, status_code=status.HTTP_200_OK)
def propose_sentence_labels(
    body: ProposeSentencesRequest,
    client: AIClient = Depends(_ai_client_dependency),
) -> ProposeSentencesResponse:
    """Return the AI's proposed labels for a hanzi sentence.

    Per SPEC §6 AC6, the response always populates every one of:
    ``pinyin``, ``english``, ``meaning``, ``words``, ``word_refs``,
    ``groups``, ``antonyms``. Per AC7 (T8) and AC8 (T9), the AI
    client is the only LLM touchpoint and ``meaning`` is a richer
    gloss than ``english``.
    """
    if not body.hanzi.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="hanzi must be a non-empty string",
        )

    try:
        proposed = client.propose_labels(hanzi=body.hanzi, note=body.note)
    except ValueError as exc:
        # The mock client raises ValueError for empty hanzi. The HTTP
        # client should not (it has its own validation), but if a
        # future provider does, surface it cleanly.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        # The HTTP client raises RuntimeError on transport / parse
        # failures. 502 because the upstream is a third-party service.
        log.error("AI propose_labels failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider unavailable",
        ) from exc

    return ProposeSentencesResponse(
        pinyin=proposed.pinyin,
        english=proposed.english,
        meaning=proposed.meaning,
        words=list(proposed.words),
        word_refs=list(proposed.word_refs),
        groups=[
            ProposedGroupOut(
                id=g.id, display_name=g.display_name, description=g.description
            )
            for g in proposed.groups
        ],
        antonyms=list(proposed.antonyms),
    )


__all__ = ["router"]
