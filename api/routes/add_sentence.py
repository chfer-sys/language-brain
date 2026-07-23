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

from api.config import get_settings
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


def _local_fallback(hanzi: str, note: str) -> ProposeSentencesResponse:
    """Build a degraded response from local dictionary + pypinyin.

    No AI call, <1s. Used when the AI provider raises RuntimeError.
    """
    from api.services.dictionary import Dictionary

    vault_root = get_settings().vault
    tokens = []
    try:
        with Dictionary(vault_root) as dictionary:
            tokens = dictionary.segment(hanzi)
    except Exception:
        tokens = []

    if tokens:
        pinyin = " ".join(t.pinyin or "" for t in tokens)
        words = [t.hanzi for t in tokens]
        word_refs = [t.pinyin or "" for t in tokens]
    else:
        # ponytail: last-resort per-char fallback when dict is empty or broken.
        try:
            from pypinyin import Style, lazy_pinyin

            words = list(hanzi)
            word_refs = lazy_pinyin(hanzi, style=Style.TONE)
            pinyin = " ".join(word_refs)
        except Exception:
            # Even pypinyin failed — surface a 502.
            raise RuntimeError("local fallback failed")

    return ProposeSentencesResponse(
        pinyin=pinyin,
        english=note,
        meaning="(AI unavailable — local lookup only. Please review meaning.)",
        words=words,
        word_refs=word_refs,
        groups=[],
        antonyms=[],
        degraded=True,
    )


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
        # failures. Serve a degraded local fallback instead of 502.
        log.warning(
            "AI propose_labels failed (%s); served local fallback",
            type(exc).__name__,
        )
        try:
            return _local_fallback(body.hanzi, body.note)
        except RuntimeError:
            # Even the local fallback failed — 502.
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
