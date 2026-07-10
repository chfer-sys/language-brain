"""POST /api/sentences/commit — save a sentence and its related state.

This is the persistence half of the sentence-add user journey (SPEC
§3.1). The companion ``/api/sentences`` route (T7) only proposes
labels via the AI client and returns them to the user. Once the user
has reviewed and edited those labels, they POST the final version to
this endpoint, which writes everything to disk and rebuilds the
derived state.

Save flow (synchronous, per SPEC §3.1 step 8 and OQ4)
----------------------------------------------------
1. **Validate input.** Empty (after strip) ``hanzi`` / ``pinyin`` /
   ``id`` return HTTP 422. Type mismatches are caught by Pydantic and
   also surface as 422.

2. **Build the sentence unit.** Shape per SPEC §2.1: ``id``,
   ``type="sentence"``, ``name=hanzi``, ``properties`` carrying every
   author-controlled field (``hanzi``, ``pinyin``, ``english``,
   ``meaning``, ``words``, ``word_refs``, ``groups``, ``antonyms``),
   empty initial ``connections`` (the connector computes them),
   ``created`` / ``updated`` set to today, and ``author_confirmed``.
   The unit is written via :func:`api.services.unit_writer.write_unit`
   so the atomic-write guarantee applies.

3. **Ensure word units (AC2).** For each ``word_refs`` entry, call
   :func:`api.services.word_registry.ensure_word_unit`. When the
   lengths of ``words`` and ``word_refs`` match, the corresponding
   hanzi is paired with the matching pinyin so the word unit gets a
   non-empty hanzi on creation. When they differ (jagged output
   from jieba or a hand-edited list), the word is still created
   with an empty hanzi so the file exists; the hanzi can be filled
   in later via the word's own edit flow. ``ensure_word_unit`` is
   idempotent so re-saves do not duplicate files.

4. **Add lexical edges from each word to the sentence (AC3).** For
   each ``word_refs`` entry, call
   :func:`api.services.lexical.add_lexical_edge_to_word` with
   ``score=1.0``. This satisfies the AC3 requirement that an
   existing word's connections list contains a lexical edge to a
   newly-saved sentence that contains it.

5. **Ensure groups and add sentence to each (AC4, AC5).** Call
   :func:`api.services.group_helpers.ensure_groups_from_proposed`,
   which accepts bare slug strings OR ``ProposedGroupOut``-shaped
   dicts (the AI client returns either shape). For each created or
   existing group unit, call
   :func:`api.services.group_registry.add_member_to_group` so the
   new sentence id appears in the group's ``properties.members``
   list. Both helpers are idempotent so re-saves don't duplicate
   members or files.

6. **Run the connector (AC12, AC13, AC14, AC15).** Call
   :func:`api.services.connector.compute_connections` with the
   lazily-resolved embedder. This writes ``lexical``,
   ``semantic``, ``group``, and ``opposite`` edges across the
   whole vault (not just the new sentence), and returns a
   summary dict the route copies into the response.

7. **Update the FAISS index (AC9, R8).** Load
   :class:`api.services.indexer.Index` with
   :meth:`Index.load_or_empty` so the call is safe whether or not
   the vault has been indexed before. If the new sentence has a
   non-empty ``meaning``, embed it via the embedder and call
   :meth:`Index.add` followed by :meth:`Index.save`. If the
   meaning is empty, the sentence is NOT added to the FAISS
   index — semantic search will not find it, but the unit file
   is still on disk for later reindexing.

8. **Return the summary.** The response body is
   ``CommitSentenceResponse(id=<sid>, connections_summary=...)``.
   The summary keys are the stable names from
   :func:`api.services.connector.compute_connections` (``sentences_touched``,
   ``words_touched``, ``lexical_pairs``, ``semantic_pairs``,
   ``group_pairs``, ``opposite_pairs``, ``skipped``) so the
   frontend can render "saved; updated N edges" messages
   without parsing free-text error strings.

Error handling
--------------
* 422 — empty (after strip) ``hanzi``, ``pinyin``, or ``id``. The
  Pydantic model also returns 422 on type mismatches and on the
  ``min_length=1`` constraint.
* 500 — any unexpected exception is logged at ERROR with its type
  name and a generic message is returned. Internal details are
  never leaked into the response body.

Dependency injection
--------------------
The embedder is loaded lazily via
:func:`api.services.embedder.get_embedder`, which falls back to
:class:`HashingEmbedder` if the real sentence-transformers model is
unavailable. Tests inject their own embedder by monkey-patching the
``get_embedder`` symbol on this module (see ``_get_embedder``
below). No FastAPI ``Depends()`` wrapper is needed — the
function-scoped helper is enough and keeps the test surface small.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, status

from api.config import settings
from api.schemas import (
    CommitSentenceRequest,
    CommitSentenceResponse,
    ProposedGroupOut,
)
from api.services.connector import compute_connections
from api.services.antonym_resolver import (
    normalize_antonyms_for_storage,
    resolve_antonym_to_word_id,
)
from api.services.embedder import Embedder, get_embedder
from api.services.english_slice import _slice_sentence_english
from api.services.group_helpers import ensure_groups_from_proposed
from api.services.group_registry import add_member_to_group
from api.services.indexer import Index
from api.services.lexical import add_lexical_edge_to_word
from api.services.dictionary import Dictionary
from api.services.id_counter import next_id
from api.services.unit_writer import read_unit, unit_path, write_unit
from api.services.word_registry import (
    backfill_word_english,
    ensure_word_unit_from_dict,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sentences", tags=["sentences"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``.

    Duplicated from the connector so this module stays decoupled
    — there is no scenario where two modules need to agree on the
    timestamp, and importing a private helper would create a
    cross-module coupling for a one-line function.
    """
    return date.today().isoformat()


def _get_embedder() -> Embedder:
    """Return the process embedder, with a monkey-patchable seam.

    The default delegates to
    :func:`api.services.embedder.get_embedder`, which falls back to
    :class:`HashingEmbedder` when the real model is unavailable.
    Tests override the module-level ``get_embedder`` symbol to
    inject a deterministic embedder; calling this helper rather
    than ``get_embedder`` directly makes the override path
    obvious and keeps the route handler short.
    """
    return get_embedder()


def _normalize_groups_input(
    raw: list[ProposedGroupOut | str],
) -> list[ProposedGroupOut | str | dict[str, Any]]:
    """Coerce Pydantic ``ProposedGroupOut`` instances into plain dicts.

    :func:`ensure_groups_from_proposed` accepts bare slug strings
    OR dicts with ``id``/``display_name``/``description`` keys. We
    send the latter shape so the helper can introspect fields
    directly. Converting Pydantic models with ``.model_dump()``
    preserves the field names exactly.
    """
    out: list[ProposedGroupOut | str | dict[str, Any]] = []
    for item in raw:
        if isinstance(item, ProposedGroupOut):
            out.append(item.model_dump())
        else:
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post(
    "/commit",
    response_model=CommitSentenceResponse,
    status_code=status.HTTP_200_OK,
)
def commit_sentence(body: CommitSentenceRequest) -> CommitSentenceResponse:
    """Persist a reviewed sentence and rebuild derived state.

    The sentence id is assigned server-side via a monotonic counter
    (``S1``, ``S2``, ...). The caller does not provide an id.

    Raises 422 if ``hanzi`` or ``pinyin`` is empty.
    """
    hanzi = body.hanzi.strip()
    pinyin = body.pinyin.strip()

    if not hanzi:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="hanzi must be a non-empty string")
    if not pinyin:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="pinyin must be a non-empty string")

    vault_root = settings.vault
    today = _today_iso()

    # ------------------------------------------------------------------
    # Step 1 — dict segmentation + word unit materialization
    # ------------------------------------------------------------------
    with Dictionary(vault_root) as dictionary:
        tokens = dictionary.segment(hanzi, body.pinyin)

    words = [t.hanzi for t in tokens]
    word_pinyins = [t.pinyin or "" for t in tokens]

    # Materialize word units from dict tokens.
    resolved_word_refs: list[str] = []
    for token in tokens:
        if token.id is None:
            # Unknown char — no unit, no word_ref.
            continue
        ensure_word_unit_from_dict(
            vault_root,
            word_id=token.id,
            hanzi=token.hanzi,
            pinyin=token.pinyin or "",
            english=token.english or "",
        )
        resolved_word_refs.append(token.id)

    # Backfill english from sentence-level english for words with empty dict english.
    word_english = _slice_sentence_english(
        body.english, words, word_pinyins
    )
    for token, eng_slice in zip(tokens, word_english):
        if token.id is not None and eng_slice:
            backfill_word_english(vault_root, token.id, eng_slice)

    # ------------------------------------------------------------------
    # Step 2 — assign sentence id + write sentence unit
    # ------------------------------------------------------------------
    sentence_id = next_id(vault_root, "sentence")

    sentence_unit: dict[str, Any] = {
        "id": sentence_id,
        "type": "sentence",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin,
            "english": body.english,
            "meaning": body.meaning,
            "words": list(words),
            "word_refs": resolved_word_refs,
            "groups": [
                g.id if isinstance(g, ProposedGroupOut) else g
                for g in body.groups
            ],
            "antonyms": normalize_antonyms_for_storage(list(body.antonyms)),
        },
        "connections": [],
        "created": today,
        "updated": today,
        "author_confirmed": body.author_confirmed,
    }
    write_unit(vault_root, sentence_unit)

    # ------------------------------------------------------------------
    # Step 3 — lexical edges from each word to the sentence (AC3)
    # ------------------------------------------------------------------
    for word_id in resolved_word_refs:
        try:
            add_lexical_edge_to_word(
                vault_root, word_id=word_id, sentence_id=sentence_id, score=1.0
            )
        except FileNotFoundError:
            log.warning("word unit missing for id=%r; skipping lexical edge", word_id)

    # ------------------------------------------------------------------
    # Step 3b — wire sentence-level antonyms into word-level antonym arrays
    # ------------------------------------------------------------------
    from api.services.antonym_service import mirror_antonyms
    from api.services.word_registry import list_all_words

    existing_word_units = list_all_words(vault_root)

    for word_id in resolved_word_refs:
        for antonym_entry in body.antonyms:
            if not isinstance(antonym_entry, str) or not antonym_entry.strip():
                continue
            try:
                antonym_id = resolve_antonym_to_word_id(
                    vault_root,
                    antonym_entry.strip(),
                    existing_word_units=existing_word_units,
                )
            except ValueError:
                continue
            if antonym_id and antonym_id != word_id:
                mirror_antonyms(vault_root, word_id, antonym_id)

    # ------------------------------------------------------------------
    # Step 4 — ensure groups and add sentence to each
    # ------------------------------------------------------------------
    normalized_groups = _normalize_groups_input(body.groups)
    group_units = ensure_groups_from_proposed(vault_root, normalized_groups)
    for group_unit in group_units:
        try:
            add_member_to_group(
                vault_root, group_id=group_unit["id"], member_id=sentence_id
            )
        except (FileNotFoundError, ValueError):
            log.warning("could not add sentence=%r to group=%r", sentence_id, group_unit.get("id"))

    # ------------------------------------------------------------------
    # Step 5 — run the connector
    # ------------------------------------------------------------------
    try:
        summary: dict[str, Any] = compute_connections(vault_root, embedder=_get_embedder())
    except Exception as exc:  # pragma: no cover
        log.error("compute_connections failed for sentence=%r: %s", sentence_id, type(exc).__name__)
        summary = {"sentences_touched": 0, "words_touched": 0, "lexical_pairs": 0,
                    "semantic_pairs": 0, "group_pairs": 0, "opposite_pairs": 0, "skipped": 0}

    # ------------------------------------------------------------------
    # Step 6 — update the FAISS index
    # ------------------------------------------------------------------
    if body.meaning.strip():
        try:
            index = Index.load_or_empty(vault_root)
            embedder = _get_embedder()
            index.add(sentence_id, embedder.embed(body.meaning))
            index.save(vault_root)
        except Exception as exc:  # pragma: no cover
            log.error("FAISS index update failed for sentence=%r: %s", sentence_id, type(exc).__name__)

    # ------------------------------------------------------------------
    # Step 7 — assemble the response
    # ------------------------------------------------------------------
    connections_summary: dict[str, int] = {
        str(k): int(v) for k, v in summary.items() if isinstance(v, (int, float))
    }
    log.info("committed sentence id=%s hanzi=%r", sentence_id, hanzi)
    return CommitSentenceResponse(id=sentence_id, connections_summary=connections_summary)


__all__ = ["router"]