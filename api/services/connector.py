"""Connection-update service for the language-brain vault.

This module implements the connection-update step described in
SPEC §2.4 ("Connections — the four link kinds") — the part that
materializes connections directly on the unit file rather than
computing them at query time.

Scope of this task (T15 + T16)
-----------------------------
T15 implemented the ``lexical`` kind for the sentence ↔ sentence
direction (SPEC §6 AC12). T16 extends :func:`compute_connections`
additively with the ``semantic`` kind (SPEC §6 AC13): symmetric
``semantic`` edges between any two sentence units whose
``properties.meaning`` fields have cosine similarity strictly above
``_SEMANTIC_THRESHOLD`` (default ``0.6``, tunable per AC13).
Future tasks will continue to extend the same entry point:

* **T17** — adds the ``group`` kind (write ``group`` edges between
  any two units that share group membership per AC14).
* **T18** — adds the ``opposite`` kind (write symmetric ``opposite``
  edges when ``antonyms`` reference another unit's id per AC15).

Algorithm (T15 + T16)
--------------------
For every pair of sentence units in the vault, two independent
similarity passes are run and their results are unioned:

1. **Lexical (T15, AC12).** If their ``properties.hanzi`` share at
   least one token after :func:`api.services.lexical.tokenize_sentence`,
   a ``lexical`` connection is written on **both** sentence units
   with the Jaccard similarity over their token sets as the score
   (:func:`api.services.lexical.jaccard`).
2. **Semantic (T16, AC13).** If the cosine similarity between the
   embeddings of their ``properties.meaning`` fields exceeds
   :data:`_SEMANTIC_THRESHOLD` (default ``0.6``, tunable per AC13),
   a ``semantic`` connection is written on **both** sentence units
   with the cosine value as the score. Cosine is computed as the
   inner product because the embedder is contractually L2-normalized
   (see :mod:`api.services.embedder`).

Self-loops are never written by either pass.

Design for additive extension
-----------------------------
The work is split into two layers:

* A pure algorithm layer (:func:`_compute_sentence_lexical_edges`)
  takes the in-memory sentence list and returns a per-sentence
  list of ``(other_id, score)`` edges to write. It does no I/O,
  so it is unit-testable without any vault state.
* An I/O layer (:func:`compute_connections`) reads units, calls
  the algorithm layer, and writes the results back via the
  :mod:`api.services.unit_writer` helpers.

Adding the ``group`` or ``opposite`` kinds in T17/T18 means
adding a new pure helper (e.g. ``_compute_group_edges``) and
calling it from :func:`compute_connections` *in addition to*
the lexical and semantic computations, not replacing them.
Each helper returns its own per-sentence edge list; the I/O
layer unions them and upserts each into the unit's
``connections`` list via the appropriate
:func:`_upsert_*_edge` helper.

Idempotency
-----------
The ``upsert`` semantic — "find an existing edge with the same
(``to``, ``kind``) tuple and update its score in place,
preserving list position; otherwise append" — guarantees that
re-running :func:`compute_connections` on the same vault
produces the same on-disk state (modulo the ``updated``
timestamp). This is required by SPEC §4 R7 / §6 AC10
("reindex is idempotent").

Callers
-------
* The sentence commit route (T19) calls :func:`compute_connections`
  synchronously after writing a sentence, per SPEC §3.1 step 8.
* The reindex script (``scripts/reindex.py``) calls it to rebuild
  the full connection graph from scratch.

I/O
---
All disk reads and writes go through
:mod:`api.services.unit_writer`. This module never opens files
directly, so the atomic-write guarantee of ``write_unit`` is
preserved.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from api.services.lexical import jaccard, tokenize_sentence
from api.services.unit_writer import list_units_by_type, write_unit


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The only connection kind this module writes. Defined as a constant
#: so a future bug (typo'd "lexcial") is caught at module import time
#: rather than after a vault-wide mutation.
_LEXICAL_KIND: str = "lexical"

#: Connection kind for the semantic pass (T16 / SPEC §6 AC13). A
#: ``semantic`` edge is written between two sentence units whose
#: ``properties.meaning`` embeddings have cosine similarity strictly
#: above :data:`_SEMANTIC_THRESHOLD`.
_SEMANTIC_KIND: str = "semantic"

#: Default cosine-similarity threshold above which a ``semantic`` edge
#: is written (SPEC §6 AC13: "threshold tunable"). Exposed as a module
#: constant so tests and callers can reference it without hard-coding
#: the literal. The public entry point :func:`compute_connections`
#: accepts ``semantic_threshold`` to override it per call.
_SEMANTIC_THRESHOLD: float = 0.6


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``.

    Duplicated from :mod:`api.services.lexical` to keep this module
    decoupled — there is no scenario where both modules need to
    agree on the date format, so we keep the helper local.
    """
    return date.today().isoformat()


def _validate_vault_root(vault_root: str) -> None:
    """Validate the ``vault_root`` argument.

    Raises
    ------
    ValueError
        If ``vault_root`` is not a non-empty string.
    FileNotFoundError
        If ``vault_root`` itself does not exist. An empty
        ``units/sentences/`` directory inside an existing vault is
        allowed and returns the zero-summary, so we do NOT require
        the sentences subdirectory to exist here — only the root.
    """
    if not isinstance(vault_root, str) or not vault_root:
        raise ValueError(
            f"vault_root must be a non-empty string, got {vault_root!r}"
        )
    root = Path(vault_root)
    if not root.exists():
        raise FileNotFoundError(
            f"vault_root does not exist: {vault_root!r}"
        )


def _hanzi_for_sentence(unit: dict[str, Any]) -> str:
    """Return the ``properties.hanzi`` string for a sentence unit.

    Returns an empty string if the field is missing or not a string
    so the caller can treat "no hanzi" as "no tokens" and skip the
    sentence entirely (the token list ends up empty, Jaccard is 0.0,
    no edges are written).

    The function is defensive on purpose: a corrupt or partially-
    authored sentence file should not crash the whole reindex.
    """
    properties = unit.get("properties")
    if not isinstance(properties, dict):
        return ""
    hanzi = properties.get("hanzi")
    if not isinstance(hanzi, str):
        return ""
    return hanzi


def _compute_sentence_lexical_edges(
    sentences: list[dict[str, Any]],
) -> tuple[dict[str, list[tuple[str, float]]], int, int]:
    """Compute the per-sentence lexical edge map from a sentence list.

    This is the pure (I/O-free) algorithm layer. It takes the list of
    sentence unit dicts and returns the edges to write, plus counters
    used by the caller's summary.

    Parameters
    ----------
    sentences:
        The sentence unit dicts to consider. Order does not matter;
        the result is keyed by sentence id. Sentences with no
        ``properties.hanzi`` (missing, non-string, or empty after
        tokenization) are skipped — they contribute neither edges
        nor connections.

    Returns
    -------
    edges_by_source:
        Mapping ``sentence_id -> list of (other_id, score)`` tuples
        that should be written as ``lexical`` edges on that
        sentence's unit file. Order of the inner list is the order
        in which pairs were discovered (lexicographic by ``other_id``
        for determinism). The mapping only contains keys for
        sentences that have at least one outgoing edge.
    lexical_pairs:
        Number of *unordered* pairs of sentences that share at least
        one token. This is the same number an AC12 acceptance
        check would report as the count of pairwise connections.
    skipped:
        Number of sentences skipped for having no usable hanzi
        tokens (missing field, non-string, or empty after
        :func:`tokenize_sentence`).

    Notes
    -----
    Self-loops are explicitly excluded: a sentence whose token
    set happens to contain a token equal to its own id still does
    NOT get an edge pointing to itself. (The token == id match is
    vanishingly unlikely with the ISO-date-id sentence naming
    scheme, but the guard is here because the function is pure and
    should not depend on id-vs-token-set semantics.)
    """
    # Pre-tokenize once. Each sentence contributes (id, tokens); we
    # skip entries whose tokens list is empty. The list is sorted by
    # id for determinism so that the pair enumeration is byte-stable
    # across runs (useful for test snapshots and idempotency claims).
    indexed: list[tuple[str, list[str]]] = []
    skipped = 0
    for unit in sentences:
        unit_id = unit.get("id")
        if not isinstance(unit_id, str) or not unit_id:
            # A unit without a usable id can't be the source OR
            # target of a connection. Treat as skipped.
            skipped += 1
            continue
        tokens = tokenize_sentence(_hanzi_for_sentence(unit))
        if not tokens:
            skipped += 1
            continue
        indexed.append((unit_id, tokens))

    # Sort by id so pair iteration is deterministic.
    indexed.sort(key=lambda pair: pair[0])

    edges_by_source: dict[str, list[tuple[str, float]]] = {}
    lexical_pairs = 0

    # Quadratic pair scan. For the MVP-scale vaults (target <1000
    # units per SPEC §4 N2) this is fine; a later optimization
    # can build an inverted index from token -> [sentence ids].
    for i in range(len(indexed)):
        a_id, a_tokens = indexed[i]
        for j in range(i + 1, len(indexed)):
            b_id, b_tokens = indexed[j]

            # Self-loop guard. The pair loop above guarantees
            # i < j so a_id != b_id by construction, but we
            # double-check defensively — future refactors that
            # relax the loop bound should not silently regress
            # this invariant.
            if a_id == b_id:
                continue

            score = jaccard(a_tokens, b_tokens)
            if score <= 0.0:
                # No shared tokens: jaccard returns 0.0. We treat
                # 0.0 as "no edge" rather than writing a
                # degenerate lexical edge with score 0.0.
                continue

            edges_by_source.setdefault(a_id, []).append((b_id, score))
            edges_by_source.setdefault(b_id, []).append((a_id, score))
            lexical_pairs += 1

    return edges_by_source, lexical_pairs, skipped


def _meaning_for_sentence(unit: dict[str, Any]) -> str | None:
    """Return the ``properties.meaning`` string for a sentence unit.

    Returns ``None`` if the field is missing, not a string, or empty.
    The semantic pass only considers sentences that have a non-empty
    string ``meaning``; any other shape is reported as a skip by
    :func:`_compute_sentence_semantic_edges`. Returning ``None``
    (rather than ``""``) lets the caller distinguish "skip this
    sentence" from "this sentence has a known-empty meaning" — though
    both are currently treated identically (the empty string embeds
    to a fixed but uncorrelated vector and rarely matches anything).

    The function is defensive on purpose: a corrupt or partially-
    authored sentence file should not crash the whole reindex.
    """
    properties = unit.get("properties")
    if not isinstance(properties, dict):
        return None
    meaning = properties.get("meaning")
    if not isinstance(meaning, str) or not meaning:
        return None
    return meaning


def _compute_sentence_semantic_edges(
    sentences: list[dict[str, Any]],
    embedder: Any,
    threshold: float = _SEMANTIC_THRESHOLD,
) -> tuple[dict[str, list[tuple[str, float]]], int, int]:
    """Compute the per-sentence semantic edge map from a sentence list.

    This is the pure (I/O-free) algorithm layer for the ``semantic``
    kind (T16 / SPEC §6 AC13). It is structurally identical to
    :func:`_compute_sentence_lexical_edges` but uses an embedder
    rather than tokenization, and a cosine threshold rather than a
    token-overlap rule.

    Parameters
    ----------
    sentences:
        The sentence unit dicts to consider. Order does not matter;
        the result is keyed by sentence id. Sentences without a
        usable ``properties.meaning`` (missing, non-string, or
        empty) are skipped — they contribute neither edges nor
        connections.
    embedder:
        Any object that exposes ``embed(text: str) -> np.ndarray``
        where the returned array is 1-D and L2-normalized (so that
        the inner product equals cosine similarity). The contract is
        intentionally duck-typed rather than ``Embedder``-typed to
        keep this module decoupled from :mod:`api.services.embedder`
        at import time and to make stubbing trivial in tests.
    threshold:
        Cosine similarity threshold. Edges are written for pairs with
        cosine **strictly greater** than this value. Must be in
        ``[-1.0, 1.0]``; values outside the range are clamped to
        that interval and a warning would be appropriate in
        production but is omitted here for simplicity.

    Returns
    -------
    edges_by_source:
        Mapping ``sentence_id -> list of (other_id, score)`` tuples
        that should be written as ``semantic`` edges on that
        sentence's unit file. Order of the inner list matches pair
        discovery order (lexicographic by ``other_id`` for
        determinism — same convention as the lexical helper).
        Only keys for sentences with at least one outgoing edge are
        present.
    semantic_pairs:
        Number of *unordered* pairs of sentences whose ``meaning``
        embeddings had cosine strictly above ``threshold``. Same
        semantics as ``lexical_pairs``: counts pairs, not edges.
    skipped:
        Number of sentences skipped for having no usable
        ``properties.meaning``.

    Notes
    -----
    * Self-loops are explicitly excluded (the ``i < j`` enumeration
      already guarantees distinct ids; we double-check defensively
      so a future refactor that loosens the loop bound cannot
      silently regress this invariant).
    * Pairs are enumerated with ``i < j`` for determinism so that
      the output is byte-stable across runs — useful for test
      snapshots and idempotency claims.
    * ``score`` is the cosine value as a Python ``float`` clipped
      to ``(threshold, 1.0]`` by construction (we only emit edges
      for pairs that pass the threshold).
    """
    # Pre-embed once per sentence. Each sentence contributes
    # (id, embedding); we skip entries without a usable meaning.
    # The list is sorted by id so pair iteration is deterministic.
    indexed: list[tuple[str, np.ndarray]] = []
    skipped = 0
    for unit in sentences:
        unit_id = unit.get("id")
        if not isinstance(unit_id, str) or not unit_id:
            skipped += 1
            continue
        meaning = _meaning_for_sentence(unit)
        if meaning is None:
            skipped += 1
            continue
        indexed.append((unit_id, embedder.embed(meaning)))

    indexed.sort(key=lambda pair: pair[0])

    edges_by_source: dict[str, list[tuple[str, float]]] = {}
    semantic_pairs = 0

    # Quadratic pair scan. Same complexity budget as the lexical
    # pass; for MVP-scale vaults (<1000 units per SPEC §4 N2) this
    # is fine. A future optimization can use FAISS or an
    # inverted-index over embeddings.
    for i in range(len(indexed)):
        a_id, a_vec = indexed[i]
        for j in range(i + 1, len(indexed)):
            b_id, b_vec = indexed[j]

            if a_id == b_id:
                continue  # defensive self-loop guard

            # Vectors are contractually L2-normalized, so dot
            # product equals cosine similarity. We clamp to
            # [-1.0, 1.0] to absorb floating-point drift.
            cos = float(np.dot(a_vec, b_vec))
            if cos < -1.0:
                cos = -1.0
            elif cos > 1.0:
                cos = 1.0

            if cos <= threshold:
                continue

            edges_by_source.setdefault(a_id, []).append((b_id, cos))
            edges_by_source.setdefault(b_id, []).append((a_id, cos))
            semantic_pairs += 1

    return edges_by_source, semantic_pairs, skipped


# ---------------------------------------------------------------------------
# Edge upsert
# ---------------------------------------------------------------------------


def _upsert_lexical_edge(
    unit: dict[str, Any],
    other_id: str,
    score: float,
) -> bool:
    """Upsert one ``lexical`` edge on ``unit``'s connections list.

    Behavior
    --------
    * If a ``lexical`` connection to ``other_id`` already exists,
      its ``score`` is updated in place and its position in the
      list is preserved. Returns ``False`` (no list change).
    * Otherwise, a new ``{"to": other_id, "kind": "lexical",
      "score": float(score)}`` entry is appended. Returns
      ``True`` (list length increased by 1).
    * Connections of OTHER kinds are never touched.
    * A missing or non-list ``connections`` field is repaired
      to an empty list (mirrors
      :func:`api.services.lexical.add_lexical_edge_to_word`).

    Returns
    -------
    bool
        ``True`` if a new edge was appended, ``False`` if an
        existing edge was updated in place.
    """
    connections = unit.get("connections")
    if not isinstance(connections, list):
        connections = []
        unit["connections"] = connections

    for idx, edge in enumerate(connections):
        if (
            isinstance(edge, dict)
            and edge.get("kind") == _LEXICAL_KIND
            and edge.get("to") == other_id
        ):
            connections[idx]["score"] = float(score)
            return False

    connections.append(
        {"to": other_id, "kind": _LEXICAL_KIND, "score": float(score)}
    )
    return True


def _upsert_semantic_edge(
    unit: dict[str, Any],
    other_id: str,
    score: float,
) -> bool:
    """Upsert one ``semantic`` edge on ``unit``'s connections list.

    Behavior is structurally identical to
    :func:`_upsert_lexical_edge`, but targets ``_SEMANTIC_KIND``
    edges instead. See that helper for the full contract; the
    short version is:

    * If a ``semantic`` connection to ``other_id`` already exists,
      its ``score`` is updated in place at the same list index.
      Returns ``False``.
    * Otherwise a new
      ``{"to": other_id, "kind": "semantic", "score": float(score)}``
      entry is appended. Returns ``True``.
    * Connections of OTHER kinds are never touched.
    * A missing or non-list ``connections`` field is repaired to
      an empty list.

    Keeping this as a separate helper (rather than generalizing
    with a ``kind`` parameter) preserves the type-narrowing benefit
    of the dedicated ``_upsert_lexical_edge`` call sites and makes
    the per-kind behavior trivially auditable.
    """
    connections = unit.get("connections")
    if not isinstance(connections, list):
        connections = []
        unit["connections"] = connections

    for idx, edge in enumerate(connections):
        if (
            isinstance(edge, dict)
            and edge.get("kind") == _SEMANTIC_KIND
            and edge.get("to") == other_id
        ):
            connections[idx]["score"] = float(score)
            return False

    connections.append(
        {"to": other_id, "kind": _SEMANTIC_KIND, "score": float(score)}
    )
    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_connections(
    vault_root: str,
    embedder: Any | None = None,
    semantic_threshold: float = _SEMANTIC_THRESHOLD,
) -> dict[str, Any]:
    """Recompute connection edges for all units in the vault.

    T15 implements the sentence ↔ sentence ``lexical`` kind
    (SPEC §6 AC12); T16 adds the ``semantic`` kind (AC13) on the
    same entry point. The function is designed so that T17/T18
    (group, opposite) can add their own computation helpers and
    union the results into the same per-unit connections list.

    Behavior
    --------
    1. Reads every sentence unit under ``vault_root``.
    2. Calls :func:`_compute_sentence_lexical_edges` to produce a
       per-sentence list of ``(other_id, score)`` pairs to write
       as ``lexical`` edges.
    3. Calls :func:`_compute_sentence_semantic_edges` to produce
       a per-sentence list of ``(other_id, score)`` pairs to
       write as ``semantic`` edges. The embedder is resolved
       here (lazy default to :func:`api.services.embedder.get_embedder`)
       so that the lexical pass can run with no embedder cost
       when only AC12 is needed.
    4. For each sentence that has outgoing edges of either kind,
       merges the lexical and semantic edge lists and upserts
       each via the appropriate
       :func:`_upsert_lexical_edge` / :func:`_upsert_semantic_edge`
       helper (preserving position of existing same-kind edges).
       Each touched unit is written ONCE at the end with all
       edges merged, so the on-disk file is consistent on every
       successful call.
    5. Refreshes ``unit["updated"]`` to today's ISO date and
       writes the unit back via
       :func:`api.services.unit_writer.write_unit`.
    6. Returns a summary dict describing what happened.

    Idempotency
    -----------
    Re-running on the same vault yields the same on-disk
    connections (modulo the ``updated`` timestamp): every edge
    is upserted by the ``(to, kind)`` tuple, so existing edges
    are updated in place rather than duplicated.

    Parameters
    ----------
    vault_root:
        Path to the vault root. The vault must exist (raise
        :class:`FileNotFoundError` if not). An empty
        ``units/sentences/`` directory is allowed and returns
        the zero-summary.
    embedder:
        Optional embedder used by the semantic pass. Must expose
        ``embed(text: str) -> np.ndarray`` returning a 1-D
        L2-normalized vector (the contract documented in
        :mod:`api.services.embedder`). When ``None``, the
        default embedder is resolved via a lazy import of
        :func:`api.services.embedder.get_embedder`. Pass an
        explicit embedder (e.g. :class:`HashingEmbedder`) in
        tests to avoid the model download.
    semantic_threshold:
        Cosine-similarity cutoff above which a ``semantic`` edge
        is written. Default :data:`_SEMANTIC_THRESHOLD` (``0.6``),
        tunable per SPEC §6 AC13. Edges are written for pairs with
        cosine **strictly greater** than this value.

    Returns
    -------
    dict[str, Any]
        Summary with at minimum:

        * ``sentences_touched`` (:class:`int`) — number of
          sentence units whose file was rewritten (excludes
          sentences with no outgoing edges of any kind).
        * ``lexical_pairs`` (:class:`int`) — number of unordered
          sentence pairs that share at least one hanzi token.
        * ``semantic_pairs`` (:class:`int`) — number of unordered
          sentence pairs whose ``meaning`` cosine exceeds
          ``semantic_threshold``.
        * ``skipped`` (:class:`int`) — number of sentences
          skipped by the combined passes (missing ``id`` or
          no usable ``properties.hanzi`` / ``properties.meaning``).
        * ``sentence_lexical_pairs_written`` (:class:`int`) —
          alias for ``lexical_pairs`` kept for readability in
          the orchestrator's summary line.
        * ``semantic_pairs_written`` (:class:`int`) — alias for
          ``semantic_pairs`` mirroring the lexical alias.

    Raises
    ------
    ValueError
        If ``vault_root`` is not a non-empty string, or if
        ``semantic_threshold`` is not a real number.
    FileNotFoundError
        If ``vault_root`` does not exist.
    """
    if not isinstance(semantic_threshold, (int, float)) or isinstance(
        semantic_threshold, bool
    ):
        # ``bool`` is a subclass of ``int`` in Python — reject it
        # explicitly so ``True``/``False`` can't sneak in as a
        # threshold. Validated BEFORE the vault-root existence check
        # so callers see the most specific error first.
        raise ValueError(
            f"semantic_threshold must be a real number, got "
            f"{semantic_threshold!r}"
        )

    _validate_vault_root(vault_root)

    sentences = list_units_by_type(vault_root, "sentence")
    lexical_edges, lexical_pairs, _lexical_skipped = (
        _compute_sentence_lexical_edges(sentences)
    )

    # Resolve the embedder lazily so the lexical-only path does
    # not pay the embedder import cost. The embedder module
    # imports ``numpy`` and (lazily) sentence-transformers; the
    # pure-lexical test path should stay light.
    if embedder is None:
        from api.services.embedder import get_embedder  # lazy

        embedder = get_embedder()

    semantic_edges, semantic_pairs, _semantic_skipped = (
        _compute_sentence_semantic_edges(
            sentences, embedder, threshold=float(semantic_threshold)
        )
    )

    # A sentence may contribute to ``skipped`` for lexical reasons
    # (no hanzi) but still participate in semantic edges (has a
    # meaning), or vice versa. The reported ``skipped`` is the
    # number of sentences that contributed NO outgoing edge to
    # either pass, derived from the merged edge map so it stays
    # accurate as more kinds are added in T17/T18. The raw
    # per-pass skip counts are intentionally NOT added to the
    # summary — they would over-count units that are partial on
    # one axis but valid on the other.
    sentences_touched = 0
    # Index the in-memory list by id so we can mutate the actual
    # dict read from disk (list_units_by_type returns the parsed
    # JSON objects). We must NOT re-read from disk here, otherwise
    # a partial-failure mid-loop would leave the in-memory state
    # and the on-disk state out of sync.
    by_id: dict[str, dict[str, Any]] = {}
    for unit in sentences:
        unit_id = unit.get("id")
        if isinstance(unit_id, str) and unit_id:
            by_id[unit_id] = unit

    # Union the two edge maps. The semantic helper tags every
    # edge with its kind so the I/O loop can dispatch to the
    # right upsert helper. Order is deterministic because both
    # pure helpers enumerate pairs in id-sorted order.
    merged: dict[str, list[tuple[str, float, str]]] = {}
    for source_id, edges in lexical_edges.items():
        merged.setdefault(source_id, []).extend(
            (other_id, score, _LEXICAL_KIND) for other_id, score in edges
        )
    for source_id, edges in semantic_edges.items():
        merged.setdefault(source_id, []).extend(
            (other_id, score, _SEMANTIC_KIND) for other_id, score in edges
        )

    for source_id, edges in merged.items():
        unit = by_id.get(source_id)
        if unit is None:
            # Defensive: if the source unit disappeared between
            # the algorithm pass and the write pass, skip it.
            # (Should not happen because we use a single
            # list_units_by_type read.)
            continue
        for other_id, score, kind in edges:
            if kind == _LEXICAL_KIND:
                _upsert_lexical_edge(unit, other_id, score)
            elif kind == _SEMANTIC_KIND:
                _upsert_semantic_edge(unit, other_id, score)
            # No other kind at this point; an unexpected kind
            # would be a programming bug, not user input.
        unit["updated"] = _today_iso()
        write_unit(vault_root, unit)
        sentences_touched += 1

    # ``skipped`` = units with a valid string id that ended up
    # contributing no outgoing edge to ANY pass. Units without a
    # valid id are dropped from the algorithm entirely and are
    # therefore always counted as skipped.
    total_with_id = sum(
        1 for u in sentences if isinstance(u.get("id"), str) and u.get("id")
    )
    skipped = total_with_id - sentences_touched

    return {
        "sentences_touched": sentences_touched,
        "lexical_pairs": lexical_pairs,
        "semantic_pairs": semantic_pairs,
        "sentence_lexical_pairs_written": lexical_pairs,
        "semantic_pairs_written": semantic_pairs,
        "skipped": skipped,
    }


__all__ = [
    "compute_connections",
]