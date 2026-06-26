"""Connection-update service for the language-brain vault.

This module implements the connection-update step described in
SPEC §2.4 ("Connections — the four link kinds") — the part that
materializes connections directly on the unit file rather than
computing them at query time.

Scope of this task (T15)
------------------------
T15 covers **only** the ``lexical`` kind for the sentence ↔ sentence
direction (SPEC §6 AC12). Future tasks will extend the same
:func:`compute_connections` entry point additively:

* **T16** — adds the ``group`` kind (write ``group`` edges between
  any two units that share group membership per AC14).
* **T17** — adds the ``opposite`` kind (write symmetric ``opposite``
  edges when ``antonyms`` reference another unit's id per AC15).

``semantic`` edges (AC13) will be added by a different module that
loads sentence-transformers; it may call :func:`compute_connections`
or call into a sibling helper, but it is out of scope here.

Algorithm (T15)
---------------
For every pair of sentence units in the vault, if their
``properties.hanzi`` share at least one token after
:func:`api.services.lexical.tokenize_sentence`, a ``lexical``
connection is written on **both** sentence units, with the
Jaccard similarity over their token sets as the score
(:func:`api.services.lexical.jaccard`). Self-loops are never
written.

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

Adding the ``group`` or ``opposite`` kinds in T16/T17 means
adding a new pure helper (e.g. ``_compute_group_edges``) and
calling it from :func:`compute_connections` *in addition to*
the lexical computation, not replacing it. Each helper returns
its own per-sentence edge list; the I/O layer unions them and
upserts each into the unit's ``connections`` list.

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

from api.services.lexical import jaccard, tokenize_sentence
from api.services.unit_writer import list_units_by_type, write_unit


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The only connection kind this module writes. Defined as a constant
#: so a future bug (typo'd "lexcial") is caught at module import time
#: rather than after a vault-wide mutation.
_LEXICAL_KIND: str = "lexical"


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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_connections(vault_root: str) -> dict[str, Any]:
    """Recompute connection edges for all units in the vault.

    T15 implements only the sentence ↔ sentence ``lexical`` kind
    (SPEC §6 AC12). The function is designed so that T16 (group)
    and T17 (opposite) can add their own computation helpers and
    union the results into the same per-unit connections list.

    Behavior
    --------
    1. Reads every sentence unit under ``vault_root``.
    2. Calls :func:`_compute_sentence_lexical_edges` to produce a
       per-sentence list of ``(other_id, score)`` pairs to write
       as ``lexical`` edges.
    3. For each sentence that has outgoing lexical edges, upserts
       them into the unit's ``connections`` list via
       :func:`_upsert_lexical_edge` (preserving position of
       existing edges of the same kind).
    4. Refreshes ``unit["updated"]`` to today's ISO date and
       writes the unit back via
       :func:`api.services.unit_writer.write_unit`.
    5. Returns a summary dict describing what happened.

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

    Returns
    -------
    dict[str, Any]
        Summary with at minimum:

        * ``sentences_touched`` (:class:`int`) — number of
          sentence units whose file was rewritten (excludes
          sentences with no edges).
        * ``lexical_pairs`` (:class:`int`) — number of unordered
          sentence pairs that share at least one token.
        * ``skipped`` (:class:`int`) — number of sentences
          skipped (missing ``id`` or no usable ``properties.hanzi``
          tokens).
        * ``sentence_lexical_pairs_written`` (:class:`int`) —
          alias for ``lexical_pairs`` kept for readability in
          the orchestrator's summary line.

    Raises
    ------
    ValueError
        If ``vault_root`` is not a non-empty string.
    FileNotFoundError
        If ``vault_root`` does not exist.
    """
    _validate_vault_root(vault_root)

    sentences = list_units_by_type(vault_root, "sentence")
    edges_by_source, lexical_pairs, skipped = _compute_sentence_lexical_edges(
        sentences
    )

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

    for source_id, edges in edges_by_source.items():
        unit = by_id.get(source_id)
        if unit is None:
            # Defensive: if the source unit disappeared between
            # the algorithm pass and the write pass, skip it.
            # (Should not happen because we use a single
            # list_units_by_type read.)
            continue
        for other_id, score in edges:
            _upsert_lexical_edge(unit, other_id, score)
        unit["updated"] = _today_iso()
        write_unit(vault_root, unit)
        sentences_touched += 1

    return {
        "sentences_touched": sentences_touched,
        "lexical_pairs": lexical_pairs,
        "sentence_lexical_pairs_written": lexical_pairs,
        "skipped": skipped,
    }


__all__ = [
    "compute_connections",
]