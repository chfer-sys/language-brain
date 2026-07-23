"""Connection-update service for the language-brain vault.

This module implements the connection-update step described in
SPEC §2.4 ("Connections — the four link kinds") — the part that
materializes connections directly on the unit file rather than
computing them at query time.

Scope of this task (T15 + T16 + T17 + T18)
------------------------------------------
T15 implemented the ``lexical`` kind for the sentence ↔ sentence
direction (SPEC §6 AC12). T16 extends :func:`compute_connections`
additively with the ``semantic`` kind (SPEC §6 AC13): symmetric
``semantic`` edges between any two sentence units whose
``properties.meaning`` fields have cosine similarity strictly above
``_SEMANTIC_THRESHOLD`` (default ``0.6``, tunable per AC13).
T17 adds the ``group`` kind (SPEC §6 AC14): symmetric ``group``
edges between any two sentence units that share membership in at
least one group unit (score fixed at 1.0). T18 continues the
additive extension with:

* **T18** — the ``opposite`` kind (SPEC §6 AC15): for every word
  pair (a, b) where ``a.properties.antonyms`` contains ``b.id`` OR
  ``b.properties.antonyms`` contains ``a.id``, write a symmetric
  ``opposite`` edge on each word with score = 1.0. As a side
  effect, also write the missing ``antonyms`` entry on the OTHER
  word so the relation is symmetric in the user-visible ``antonyms``
  array as well. This pass operates on the ``word`` unit type and
  shares the same I/O loop as the sentence-level passes.

Algorithm (T15 + T16 + T17 + T18)
---------------------------------
For every pair of sentence units in the vault, three independent
passes are run and their results are unioned:

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
3. **Group (T17, AC14).** If two sentence units share membership in
   at least one group unit (a group whose ``properties.members`` list
   contains both unit ids), a ``group`` connection is written on
   **both** sentence units with score fixed at 1.0. Group units
   themselves are NEVER the source or target of a ``group`` edge
   from this pass — per AC14, ``group`` edges are written between
   the *members* of a group, not to the group. Word↔word and
   word↔sentence group-sharing edges are out of scope for T17
   (mirroring the sentence-only scope of the lexical and semantic
   passes); only sentence ↔ sentence group-sharing is considered.
4. **Opposite (T18, AC15).** For every word unit, look at its
   ``properties.antonyms`` list of OTHER word ids. For each pair
   (a, b) that the vocabulary declares as antonyms (via a's
   ``antonyms`` containing b, or vice versa), write a symmetric
   ``opposite`` edge on each word with score = 1.0. The pass also
   syncs the ``antonyms`` array on the OTHER word so that the
   declared relation is symmetric in both the connection graph and
   the user-visible ``antonyms`` field (this is the "writes
   symmetrically" half of AC15). Unknown target ids — ids that
   appear in a word's ``antonyms`` list but do not correspond to
   any word unit on disk — are SKIPPED: no edge is written, and no
   ``antonyms`` array sync is attempted. The rationale is that
   the connection graph should not carry dangling references;
   the user can declare the relation explicitly later by saving
   the missing target word. (See the test
   ``test_opposite_unknown_target_does_not_crash`` for the locked-in
   behavior.) Self-loops are explicitly excluded.

Self-loops are never written by any pass.

Design for additive extension
-----------------------------
The work is split into two layers:

* A pure algorithm layer (e.g. :func:`_compute_sentence_lexical_edges`,
  :func:`_compute_sentence_semantic_edges`,
  :func:`_compute_sentence_group_edges`) takes the in-memory
  sentence list (and, for the group pass, the in-memory group list)
  and returns a per-sentence list of ``(other_id, score)`` edges to
  write. It does no I/O, so it is unit-testable without any vault
  state.
* An I/O layer (:func:`compute_connections`) reads units, calls
  the algorithm layer, and writes the results back via the
  :mod:`api.services.unit_writer` helpers.

Adding further kinds in T18 means adding a new pure helper and
calling it from :func:`compute_connections` *in addition to* the
lexical, semantic, and group computations, not replacing them.
Each helper returns its own per-sentence edge list; the I/O layer
unions them and upserts each into the unit's ``connections`` list
via the appropriate :func:`_upsert_*_edge` helper.

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

#: Connection kind for the group pass (T17 / SPEC §6 AC14). A ``group``
#: edge is written between two sentence units that share membership in
#: at least one group unit. The kind is fixed by SPEC §2.4 / §6 AC14
#: so the constant exists primarily to keep typos from compiling.
_GROUP_KIND: str = "group"

#: The fixed score attached to every ``group`` edge (SPEC §6 AC14:
#: "score = 1.0"). The group pass has no continuous similarity to
#: compute — membership is a binary fact — so we store the score as
#: a module constant rather than a parameter.
_GROUP_SCORE: float = 1.0

#: Connection kind for the opposite pass (T18 / SPEC §6 AC15). An
#: ``opposite`` edge is written between two word units whose
#: ``properties.antonyms`` arrays reference each other (in either
#: direction). The kind is fixed by SPEC §2.4 / §6 AC15 so the
#: constant exists primarily to keep typos from compiling.
_OPPOSITE_KIND: str = "opposite"

#: The fixed score attached to every ``opposite`` edge (SPEC §2.4
#: / §6 AC15: "score = 1.0"). Antonymy is a binary relation — the
#: word IS the opposite of the other, not "90% opposite" — so the
#: score is a constant rather than a parameter.
_OPPOSITE_SCORE: float = 1.0


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
    #
    # ponytail: batched single forward pass via embed_batch; remaining
    # cost is O(N) file scan per commit — incremental edge compute is
    # the upgrade path if vault grows past ~500 sentences.
    indexed: list[tuple[str, np.ndarray]] = []
    skipped = 0
    pending: list[tuple[int, str, str]] = []  # (insert_idx, unit_id, meaning)
    for unit in sentences:
        unit_id = unit.get("id")
        if not isinstance(unit_id, str) or not unit_id:
            skipped += 1
            continue
        meaning = _meaning_for_sentence(unit)
        if meaning is None:
            skipped += 1
            continue
        pending.append((len(indexed), unit_id, meaning))
        indexed.append((unit_id, np.zeros(0, dtype=np.float32)))  # placeholder

    if pending:
        meanings = [m for _, _, m in pending]
        vecs: np.ndarray | None = None
        # ponytail: hasattr guard — custom embedders lacking embed_batch
        # fall back to the per-item loop without refactoring the call site.
        if hasattr(embedder, "embed_batch"):
            try:
                vecs = embedder.embed_batch(meanings)
            except AttributeError:
                vecs = None
        if vecs is None:
            vecs = np.stack([embedder.embed(m) for m in meanings])
        for (idx, unit_id, _meaning), vec in zip(pending, vecs):
            indexed[idx] = (unit_id, np.asarray(vec, dtype=np.float32))

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


def _members_of_group(group_unit: dict[str, Any]) -> list[str]:
    """Return the string-id ``properties.members`` of a group unit.

    Returns an empty list if ``properties.members`` is missing,
    not a list, or contains non-string entries. The function is
    defensive: a corrupt or partially-authored group file should
    not crash the whole reindex. Non-string member ids are
    silently dropped (the caller treats them as if they were
    absent), so a malformed group contributes fewer members
    rather than raising mid-loop.

    Note: per :mod:`api.services.group_registry`, members are
    unit ids (sentence or word), NOT group ids — group-to-group
    membership is out of scope for the MVP and this helper
    inherits that constraint implicitly.
    """
    properties = group_unit.get("properties")
    if not isinstance(properties, dict):
        return []
    raw_members = properties.get("members")
    if not isinstance(raw_members, list):
        return []
    return [m for m in raw_members if isinstance(m, str) and m]


def _compute_sentence_group_edges(
    sentences: list[dict[str, Any]],
    groups: list[dict[str, Any]],
) -> tuple[dict[str, list[tuple[str, float]]], int, int]:
    """Compute the per-sentence group edge map from a sentence and
    group list.

    This is the pure (I/O-free) algorithm layer for the ``group``
    kind (T17 / SPEC §6 AC14). It is structurally different from
    the lexical and semantic helpers because the input is a
    *membership relation* between two unit types rather than a
    pairwise similarity over one unit type.

    Scope of T17
    ------------
    For T17, ONLY sentence ↔ sentence pairs that share a group
    membership are considered. This matches the existing lexical
    and semantic passes, which are also sentence-only. Word ↔
    word and word ↔ sentence group-sharing edges can be added in
    a later task if the SPEC requires them; per AC14's plain
    reading, "two units that share group membership" is symmetric
    in unit type and extending to words is a forward-compatible
    change that does not alter the current public contract.

    Algorithm
    ---------
    1. Build ``group_membership: dict[member_id, set[group_id]]`` by
       scanning each group's ``properties.members``. Non-string
       members are dropped (see :func:`_members_of_group`).
    2. Restrict the universe to sentence ids (a sentence whose id
       has no group membership contributes no edges and is
       skipped).
    3. Enumerate unordered pairs of sentences in id-sorted order.
       For each pair, if ``group_membership[a] & group_membership[b]``
       is non-empty, write a symmetric ``group`` edge with score
       :data:`_GROUP_SCORE`. The pair counter increments once
       per shared-group pair (regardless of HOW MANY groups they
       share — AC14 says "share membership in at least one
       group", which yields a single edge, not one per group).

    Parameters
    ----------
    sentences:
        The sentence unit dicts to consider. Sentences without a
        usable string ``id`` are skipped.
    groups:
        The group unit dicts to consider. Their ``properties.members``
        is the membership index used for pair enumeration. Group
        units are NEVER sources or targets of edges from this
        helper — see the scope note above.

    Returns
    -------
    edges_by_source:
        Mapping ``sentence_id -> list of (other_id, score)`` tuples
        that should be written as ``group`` edges on that
        sentence's unit file. Only keys for sentences with at
        least one outgoing edge are present.
    group_pairs:
        Number of *unordered* pairs of sentences that share at
        least one group. Same semantics as ``lexical_pairs`` /
        ``semantic_pairs``: counts pairs, not edges, and
        deduplicates across multiple shared groups (two
        sentences sharing three groups still count as ONE pair,
        and receive ONE edge in each direction).
    skipped:
        Number of sentences skipped for having a non-string id.
        Sentences with no group membership are NOT counted as
        skipped — they simply contribute no edges, which is the
        desired AC14 behavior.

    Notes
    -----
    * Self-loops are explicitly excluded (the ``i < j`` enumeration
      already guarantees distinct ids; we double-check defensively
      so a future refactor that loosens the loop bound cannot
      silently regress this invariant).
    * Pairs are enumerated with ``i < j`` over id-sorted ids so
      the output is byte-stable across runs.
    * Multiple shared groups between the same pair collapse to
      a single edge because we only write an edge if
      ``group_membership[a] & group_membership[b]`` is non-empty;
      the size of the intersection does not affect the edge
      count or score. Idempotency follows from the same
      ``(to, kind)`` upsert contract used by the lexical and
      semantic passes.
    """
    # Step 1 — membership index.
    group_membership: dict[str, set[str]] = {}
    for group in groups:
        group_id = group.get("id")
        if not isinstance(group_id, str) or not group_id:
            # A group without a usable id can't be referenced as a
            # membership key. Skip silently — the algorithm must
            # tolerate a corrupt vault entry without crashing.
            continue
        for member_id in _members_of_group(group):
            group_membership.setdefault(member_id, set()).add(group_id)

    # Step 2 — sentence universe, restricted to usable string ids.
    sentence_ids: list[str] = []
    skipped = 0
    for unit in sentences:
        unit_id = unit.get("id")
        if isinstance(unit_id, str) and unit_id:
            sentence_ids.append(unit_id)
        else:
            skipped += 1

    # Sort for deterministic pair enumeration.
    sentence_ids.sort()

    edges_by_source: dict[str, list[tuple[str, float]]] = {}
    group_pairs = 0

    # Step 3 — pair scan. Same complexity budget as the lexical /
    # semantic passes; for MVP-scale vaults (<1000 sentences per
    # SPEC §4 N2) this is fine.
    for i in range(len(sentence_ids)):
        a_id = sentence_ids[i]
        a_groups = group_membership.get(a_id)
        if not a_groups:
            # Sentence is not a member of any group — it cannot
            # share a group with anyone. Skip the inner loop
            # entirely.
            continue
        for j in range(i + 1, len(sentence_ids)):
            b_id = sentence_ids[j]

            if a_id == b_id:
                continue  # defensive self-loop guard

            b_groups = group_membership.get(b_id)
            if not b_groups:
                continue

            # AC14: "share membership in at least one group".
            # Set intersection is non-empty iff the two sentences
            # are members of at least one common group. The
            # actual size of the intersection is irrelevant —
            # one shared group is enough for ONE edge per pair.
            if not (a_groups & b_groups):
                continue

            edges_by_source.setdefault(a_id, []).append(
                (b_id, _GROUP_SCORE)
            )
            edges_by_source.setdefault(b_id, []).append(
                (a_id, _GROUP_SCORE)
            )
            group_pairs += 1

    return edges_by_source, group_pairs, skipped


def _antonyms_of_word(unit: dict[str, Any]) -> list[str]:
    """Return the string ``antonyms`` list for a word unit.

    Returns an empty list if ``properties.antonyms`` is missing,
    not a list, or contains non-string entries. The helper is
    defensive on purpose: a corrupt or partially-authored word
    file should not crash the whole reindex. Non-string entries
    are silently dropped (the caller treats them as if they were
    absent) so a malformed ``antonyms`` list contributes fewer
    edges rather than raising mid-loop.

    Notes
    -----
    Per v0.5.2+, ``properties.antonyms`` is a list of typed word ids
    (``W{n}`` / ``C{n}``), NOT tone-marked pinyin strings. The list is
    the declared antonym relation; the connection graph mirrors it
    symmetrically (per SPEC §6 AC15).
    """
    properties = unit.get("properties")
    if not isinstance(properties, dict):
        return []
    raw_antonyms = properties.get("antonyms")
    if not isinstance(raw_antonyms, list):
        return []
    return [a for a in raw_antonyms if isinstance(a, str) and a]


def _compute_word_opposite_edges(
    words: list[dict[str, Any]],
) -> tuple[dict[str, list[tuple[str, float]]], int, set[tuple[str, str]]]:
    """Compute the per-word ``opposite`` edge map from a word list.

    This is the pure (I/O-free) algorithm layer for the
    ``opposite`` kind (T18 / SPEC §6 AC15). It is structurally
    different from the sentence-level helpers because the input
    is a DECLARED RELATION (the ``antonyms`` array) rather than a
    pairwise similarity computed from raw text.

    Scope of T18
    ------------
    For T18, ONLY word ↔ word pairs are considered. The pass is
    restricted to unit ids that exist as word units on disk — an
    antonym id that points at a missing word file is silently
    skipped (see the "Edges to unknown targets" decision below).
    This avoids dangling references in the connection graph that
    the search/UI passes would have to defensively resolve.

    Edges to unknown targets
    ------------------------
    AC15 says: "every word pair (a, b) where ``a.properties.antonyms``
    contains ``b.id`` OR ``b.properties.antonyms`` contains ``a.id``".
    The plain reading would also cover the case where ``b.id``
    points at a word that doesn't exist yet. We chose to SKIP that
    case (no edge written) because:

    * The connection graph is consumed by the search route, which
      tries to resolve ``edge["to"]`` to a unit dict. A dangling
      reference would silently drop out of results.
    * Writing a connection to a non-existent word would create
      on-disk state the user cannot inspect or delete until the
      target word is created.
    * The user retains full control: they can declare the antonym
      relation again once the target word is saved.

    The symmetry-sync set (the third return value) follows the
    same rule: only pairs whose BOTH ids correspond to known word
    units are added to the sync set.

    Parameters
    ----------
    words:
        The word unit dicts to consider. Words without a usable
        string ``id`` are skipped (they can be neither the source
        nor the target of an edge).

    Returns
    -------
    edges_by_source:
        Mapping ``word_id -> list of (other_id, score)`` tuples
        that should be written as ``opposite`` edges on that
        word's unit file. Order of the inner list matches pair
        discovery order (lexicographic by ``other_id`` for
        determinism — same convention as the sentence-level
        helpers). Only keys for words with at least one outgoing
        edge are present.
    opposite_pairs:
        Number of *unordered* word pairs (a, b) that are declared
        antonyms by at least one side. Same semantics as
        ``lexical_pairs`` / ``semantic_pairs`` / ``group_pairs``:
        counts pairs, not edges. The same pair counted twice
        (because both sides declare it) collapses to one.
    symmetry_pairs:
        Set of unordered (a, b) tuples (with sorted ids) that the
        I/O layer must MIRROR in the ``properties.antonyms`` array
        of the OTHER word. A pair (a, b) is in this set iff both
        ``a`` and ``b`` are known word ids AND ``b`` is NOT yet
        present in ``a.properties.antonyms``. (If both sides
        already declare the relation, no sync is needed.)

    Notes
    -----
    * Self-loops are explicitly excluded: a word whose
      ``antonyms`` list contains its own id still does NOT get an
      edge pointing to itself.
    * Duplicate edges collapse to one (per (to, kind) tuple at the
      I/O layer; the algorithm layer returns one edge per pair
      regardless).
    * Unknown target ids are SKIPPED — they contribute no edge
      and no symmetry sync.
    * Words with no ``antonyms`` array or an empty ``antonyms``
      array contribute no edges.
    * The symmetry-sync set is derived from the declared relation
      at algorithm time. If a stale file is on disk (the other
      side has a leftover ``antonyms`` entry that should be
      removed), this module does NOT prune it — pruning the
      ``antonyms`` array is a write-side concern that requires
      an explicit "remove" operation rather than the upsert
      contract this pass implements.
    """
    # Index known word ids. Only string, non-empty ids count.
    word_ids: set[str] = {
        w["id"]
        for w in words
        if isinstance(w.get("id"), str) and w.get("id")
    }

    # Build the pair set. An unordered pair (a, b) (with sorted
    # ids) is in the set iff at least one side declares the
    # relation via ``properties.antonyms``.
    pair_set: set[tuple[str, str]] = set()
    # Track, per pair, which side(s) declared the relation so the
    # I/O layer can decide which ``antonyms`` arrays need a sync
    # write. We store this as a set of "declared" sides to make
    # the symmetry-sync logic easy to audit.
    declared: dict[tuple[str, str], set[str]] = {}

    for unit in words:
        a_id = unit.get("id")
        if not isinstance(a_id, str) or not a_id:
            # A word without a usable id can't be a source. It
            # also can't be a target (the target id is always
            # referenced via a string), so dropping it here is
            # safe.
            continue
        for b_id in _antonyms_of_word(unit):
            if a_id == b_id:
                # Self-loop guard. Defensive even though the
                # caller is unlikely to declare a word as its
                # own antonym.
                continue
            if b_id not in word_ids:
                # Unknown target — skip. Documented choice; see
                # the "Edges to unknown targets" note above.
                continue
            pair = (a_id, b_id) if a_id < b_id else (b_id, a_id)
            pair_set.add(pair)
            declared.setdefault(pair, set()).add(a_id)

    # Build the edge map. Each unordered pair contributes one
    # outgoing edge to each side.
    edges_by_source: dict[str, list[tuple[str, float]]] = {}
    for a_id, b_id in pair_set:
        edges_by_source.setdefault(a_id, []).append(
            (b_id, _OPPOSITE_SCORE)
        )
        edges_by_source.setdefault(b_id, []).append(
            (a_id, _OPPOSITE_SCORE)
        )

    # Compute the symmetry-sync set: pairs where the OTHER side's
    # ``antonyms`` array does not yet list this side. We need to
    # look at the in-memory word list (not the disk state, which
    # could be stale) to decide. For each pair, if side A
    # declared the relation but side B's ``antonyms`` does not
    # contain A, then B's file needs a sync write adding A.
    # (And symmetrically.)
    # Index the words by id for the second pass.
    words_by_id: dict[str, dict[str, Any]] = {}
    for w in words:
        wid = w.get("id")
        if isinstance(wid, str) and wid:
            words_by_id[wid] = w

    symmetry_pairs: set[tuple[str, str]] = set()
    for pair in pair_set:
        a_id, b_id = pair
        a_word = words_by_id.get(a_id)
        b_word = words_by_id.get(b_id)
        if a_word is None or b_word is None:
            # Defensive: the word_ids set already filtered these
            # out, but if a future refactor relaxes that
            # invariant we still want to skip cleanly here.
            continue
        a_antonyms = set(_antonyms_of_word(a_word))
        b_antonyms = set(_antonyms_of_word(b_word))
        if b_id not in a_antonyms:
            symmetry_pairs.add(pair)
        if a_id not in b_antonyms:
            symmetry_pairs.add(pair)

    opposite_pairs = len(pair_set)
    return edges_by_source, opposite_pairs, symmetry_pairs


def _sync_antonyms_array(
    unit: dict[str, Any], other_id: str
) -> bool:
    """Append ``other_id`` to ``unit``'s ``properties.antonyms`` list
    if not already present.

    This is the AC15 "writes symmetrically" half: when an antonym
    relation is declared on one side, the connector also writes
    the OTHER side's ``antonyms`` array to keep the declared
    relation symmetric. The helper mutates ``unit`` in place and
    returns ``True`` iff a mutation occurred.

    Behavior
    --------
    * If ``unit["properties"]["antonyms"]`` is a list and
      ``other_id`` is already present: no-op. Returns ``False``.
    * If ``unit["properties"]["antonyms"]`` is a list and
      ``other_id`` is NOT present: append. Returns ``True``.
    * If ``properties`` is missing or not a dict: repair to a
      fresh dict containing ``antonyms: [other_id]``. Returns
      ``True``.
    * If ``properties.antonyms`` is present but not a list
      (e.g. a string or ``None``): repair to a fresh list
      containing ``other_id``. The previous malformed value is
      discarded — the connector always wants a list shape for
      ``antonyms`` because AC15 writes through it on every run.
      Returns ``True``.

    Parameters
    ----------
    unit:
        The word unit dict to mutate. The dict is modified in
        place — no copy is returned.
    other_id:
        The id of the OTHER word in the antonym pair. Must be a
        non-empty string (the caller filters upstream).

    Returns
    -------
    bool
        ``True`` if the dict was mutated (antonym appended or
        field repaired), ``False`` if no change was needed.
    """
    properties = unit.get("properties")
    if not isinstance(properties, dict):
        properties = {}
        unit["properties"] = properties

    raw = properties.get("antonyms")
    if isinstance(raw, list):
        if other_id in raw:
            return False
        raw.append(other_id)
        return True

    # Malformed (None, string, missing, etc.) — repair to a
    # fresh list containing ``other_id``. This is the safest
    # recovery: the connector's contract is that ``antonyms``
    # is always a list after a successful run.
    properties["antonyms"] = [other_id]
    return True


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


def _upsert_group_edge(
    unit: dict[str, Any],
    other_id: str,
    score: float = _GROUP_SCORE,
) -> bool:
    """Upsert one ``group`` edge on ``unit``'s connections list.

    Behavior is structurally identical to
    :func:`_upsert_lexical_edge` and :func:`_upsert_semantic_edge`,
    but targets ``_GROUP_KIND`` edges instead. See
    :func:`_upsert_lexical_edge` for the full contract; the short
    version is:

    * If a ``group`` connection to ``other_id`` already exists, its
      ``score`` is updated in place at the same list index.
      Returns ``False``.
    * Otherwise a new
      ``{"to": other_id, "kind": "group", "score": float(score)}``
      entry is appended. Returns ``True``.
    * Connections of OTHER kinds are never touched.
    * A missing or non-list ``connections`` field is repaired to
      an empty list.

    ``score`` defaults to :data:`_GROUP_SCORE` (``1.0``) per
    SPEC §6 AC14. The parameter is retained so the helper can
    be reused for tests or future AC14-style kinds without
    re-plumbing the upsert contract.

    Keeping this as a separate helper (rather than generalizing
    with a ``kind`` parameter) preserves the type-narrowing benefit
    of the dedicated ``_upsert_lexical_edge`` / ``_upsert_semantic_edge``
    call sites and makes the per-kind behavior trivially auditable.
    """
    connections = unit.get("connections")
    if not isinstance(connections, list):
        connections = []
        unit["connections"] = connections

    for idx, edge in enumerate(connections):
        if (
            isinstance(edge, dict)
            and edge.get("kind") == _GROUP_KIND
            and edge.get("to") == other_id
        ):
            connections[idx]["score"] = float(score)
            return False

    connections.append(
        {"to": other_id, "kind": _GROUP_KIND, "score": float(score)}
    )
    return True


def _upsert_opposite_edge(
    unit: dict[str, Any],
    other_id: str,
    score: float = _OPPOSITE_SCORE,
) -> bool:
    """Upsert one ``opposite`` edge on ``unit``'s connections list.

    Behavior is structurally identical to
    :func:`_upsert_lexical_edge` / :func:`_upsert_semantic_edge` /
    :func:`_upsert_group_edge`, but targets ``_OPPOSITE_KIND``
    edges instead. See :func:`_upsert_lexical_edge` for the full
    contract; the short version is:

    * If an ``opposite`` connection to ``other_id`` already
      exists, its ``score`` is updated in place at the same list
      index. Returns ``False``.
    * Otherwise a new
      ``{"to": other_id, "kind": "opposite", "score": float(score)}``
      entry is appended. Returns ``True``.
    * Connections of OTHER kinds are never touched.
    * A missing or non-list ``connections`` field is repaired to
      an empty list.

    ``score`` defaults to :data:`_OPPOSITE_SCORE` (``1.0``) per
    SPEC §6 AC15. The parameter is retained for symmetry with the
    other upsert helpers; in practice the opposite pass always
    uses the constant.
    """
    connections = unit.get("connections")
    if not isinstance(connections, list):
        connections = []
        unit["connections"] = connections

    for idx, edge in enumerate(connections):
        if (
            isinstance(edge, dict)
            and edge.get("kind") == _OPPOSITE_KIND
            and edge.get("to") == other_id
        ):
            connections[idx]["score"] = float(score)
            return False

    connections.append(
        {"to": other_id, "kind": _OPPOSITE_KIND, "score": float(score)}
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
    same entry point; T17 adds the ``group`` kind (AC14). T18
    adds the ``opposite`` kind (AC15), which operates on WORD
    units (not sentences). The function is designed so that
    future tasks can add more kinds additively to the same
    entry point.

    Behavior
    --------
    1. Reads every sentence unit, every group unit, and every
       word unit under ``vault_root``.
    2. Calls :func:`_compute_sentence_lexical_edges` to produce a
       per-sentence list of ``(other_id, score)`` pairs to write
       as ``lexical`` edges.
    3. Calls :func:`_compute_sentence_semantic_edges` to produce
       a per-sentence list of ``(other_id, score)`` pairs to
       write as ``semantic`` edges. The embedder is resolved
       here (lazy default to :func:`api.services.embedder.get_embedder`)
       so that the lexical pass can run with no embedder cost
       when only AC12 is needed.
    4. Calls :func:`_compute_sentence_group_edges` to produce a
       per-sentence list of ``(other_id, _GROUP_SCORE)`` pairs
       to write as ``group`` edges (T17 / AC14).
    5. Calls :func:`_compute_word_opposite_edges` to produce a
       per-word list of ``(other_id, _OPPOSITE_SCORE)`` pairs to
       write as ``opposite`` edges (T18 / AC15), plus a
       symmetry-sync set of word pairs whose ``antonyms`` arrays
       need to be mirrored.
    6. For each unit (sentence or word) that has outgoing edges
       of any kind, merges the per-kind edge lists and upserts
       each via the appropriate :func:`_upsert_lexical_edge` /
       :func:`_upsert_semantic_edge` / :func:`_upsert_group_edge` /
       :func:`_upsert_opposite_edge` helper (preserving position
       of existing same-kind edges). Each touched unit is written
       ONCE at the end with all edges merged, so the on-disk
       file is consistent on every successful call.
    7. For each pair in the symmetry-sync set, the OTHER side's
       ``properties.antonyms`` array is upserted via
       :func:`_sync_antonyms_array`. If the sync mutates a unit
       that wasn't already in the merged edge map (rare: the
       declared-on-the-other-side side), the unit is rewritten
       so the on-disk file reflects the symmetric declaration.
    8. Refreshes ``unit["updated"]`` to today's ISO date and
       writes the unit back via
       :func:`api.services.unit_writer.write_unit`.
    9. Returns a summary dict describing what happened.

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
        * ``words_touched`` (:class:`int`) — number of word
          units whose file was rewritten (excludes words with
          no outgoing ``opposite`` edges AND no antonym-array
          sync to perform).
        * ``lexical_pairs`` (:class:`int`) — number of unordered
          sentence pairs that share at least one hanzi token.
        * ``semantic_pairs`` (:class:`int`) — number of unordered
          sentence pairs whose ``meaning`` cosine exceeds
          ``semantic_threshold``.
        * ``group_pairs`` (:class:`int`) — number of unordered
          sentence pairs that share membership in at least one
          group (T17 / AC14).
        * ``opposite_pairs`` (:class:`int`) — number of unordered
          word pairs that are declared antonyms by at least one
          side (T18 / AC15).
        * ``skipped`` (:class:`int`) — number of sentences
          skipped by the combined passes (missing ``id`` or
          no usable ``properties.hanzi`` / ``properties.meaning``).
        * ``sentence_lexical_pairs_written`` (:class:`int`) —
          alias for ``lexical_pairs`` kept for readability in
          the orchestrator's summary line.
        * ``semantic_pairs_written`` (:class:`int`) — alias for
          ``semantic_pairs`` mirroring the lexical alias.
        * ``group_pairs_written`` (:class:`int`) — alias for
          ``group_pairs`` mirroring the lexical/semantic aliases.
        * ``opposite_pairs_written`` (:class:`int`) — alias for
          ``opposite_pairs`` mirroring the other pair-count
          aliases.

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

    # T17 / AC14 — group pass. Loads groups from disk and pairs up
    # sentences that share at least one group's membership. The
    # group pass is independent of the lexical and semantic passes
    # and uses no embedder, so its failure mode (no groups on
    # disk) gracefully degrades to "zero group pairs" without
    # affecting the other counts.
    groups = list_units_by_type(vault_root, "group")
    group_edges, group_pairs, _group_skipped = (
        _compute_sentence_group_edges(sentences, groups)
    )

    # T18 / AC15 — opposite pass. Loads word units from disk and
    # pairs up words whose ``properties.antonyms`` arrays declare
    # each other (in either direction). Returns the edge map plus
    # a symmetry-sync set used to mirror the declared relation in
    # the OTHER word's ``antonyms`` array. See
    # :func:`_compute_word_opposite_edges` for the full contract,
    # including the "skip unknown targets" decision.
    words = list_units_by_type(vault_root, "word")
    opposite_edges, opposite_pairs, symmetry_pairs = (
        _compute_word_opposite_edges(words)
    )

    # A sentence may contribute to ``skipped`` for lexical reasons
    # (no hanzi) but still participate in semantic edges (has a
    # meaning), or vice versa, or via a group edge (T17). The
    # reported ``skipped`` is the number of sentences that
    # contributed NO outgoing edge to ANY pass, derived from the
    # merged edge map so it stays accurate as more kinds are
    # added in T18. The raw per-pass skip counts are
    # intentionally NOT added to the summary — they would
    # over-count units that are partial on one axis but valid
    # on another.
    sentences_touched = 0
    # Index the in-memory lists by id so we can mutate the actual
    # dicts read from disk (list_units_by_type returns the parsed
    # JSON objects). We must NOT re-read from disk here, otherwise
    # a partial-failure mid-loop would leave the in-memory state
    # and the on-disk state out of sync. T18 extends this index
    # to cover WORDS as well as sentences so the unified I/O loop
    # below can dispatch on (unit_type, kind). Ids are unique
    # across types in practice (sentences are ISO dates, words
    # are tone-marked pinyin, groups are slugs), so a single
    # dict is safe.
    by_id: dict[str, dict[str, Any]] = {}
    for unit in sentences:
        unit_id = unit.get("id")
        if isinstance(unit_id, str) and unit_id:
            by_id[unit_id] = unit
    for unit in words:
        unit_id = unit.get("id")
        if isinstance(unit_id, str) and unit_id:
            by_id[unit_id] = unit

    # Union the four edge maps. Each helper tags every edge with
    # its kind so the I/O loop can dispatch to the right upsert
    # helper. Order is deterministic because all pure helpers
    # enumerate pairs in id-sorted order.
    merged: dict[str, list[tuple[str, float, str]]] = {}
    for source_id, edges in lexical_edges.items():
        merged.setdefault(source_id, []).extend(
            (other_id, score, _LEXICAL_KIND) for other_id, score in edges
        )
    for source_id, edges in semantic_edges.items():
        merged.setdefault(source_id, []).extend(
            (other_id, score, _SEMANTIC_KIND) for other_id, score in edges
        )
    for source_id, edges in group_edges.items():
        merged.setdefault(source_id, []).extend(
            (other_id, score, _GROUP_KIND) for other_id, score in edges
        )
    for source_id, edges in opposite_edges.items():
        merged.setdefault(source_id, []).extend(
            (other_id, score, _OPPOSITE_KIND) for other_id, score in edges
        )

    # T18 / AC15 — symmetry sync. For each (a, b) pair in the
    # symmetry-sync set, append the missing side to the OTHER
    # word's ``properties.antonyms`` array. We do this AFTER the
    # edge map is built (so we know which units to mutate) but
    # BEFORE the write loop (so the sync happens against the
    # same in-memory dicts we will write out). If a sync
    # mutates a unit that wasn't already in the merged edge map,
    # we add it to ``merged`` so the I/O loop will rewrite the
    # file — the on-disk file must reflect the symmetric
    # declaration.
    for a_id, b_id in symmetry_pairs:
        a_unit = by_id.get(a_id)
        b_unit = by_id.get(b_id)
        if a_unit is None or b_unit is None:
            # Defensive: the algorithm layer only adds pairs to
            # symmetry_pairs when both ids are known word ids,
            # so this branch is unreachable unless the in-memory
            # by_id index lost an entry.
            continue
        if _sync_antonyms_array(a_unit, b_id):
            merged.setdefault(a_id, [])
        if _sync_antonyms_array(b_unit, a_id):
            merged.setdefault(b_id, [])

    words_touched = 0
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
            elif kind == _GROUP_KIND:
                _upsert_group_edge(unit, other_id, score)
            elif kind == _OPPOSITE_KIND:
                _upsert_opposite_edge(unit, other_id, score)
            # No other kind at this point; an unexpected kind
            # would be a programming bug, not user input.
        unit["updated"] = _today_iso()
        write_unit(vault_root, unit)
        # Count touched units by their type. ``sentences_touched``
        # keeps its original T15 contract (only sentence units)
        # so existing AC12/AC13/AC14 tests stay green; T18 adds
        # the parallel ``words_touched`` counter for AC15.
        unit_type = unit.get("type")
        if unit_type == "word":
            words_touched += 1
        else:
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
        "words_touched": words_touched,
        "lexical_pairs": lexical_pairs,
        "semantic_pairs": semantic_pairs,
        "group_pairs": group_pairs,
        "opposite_pairs": opposite_pairs,
        "sentence_lexical_pairs_written": lexical_pairs,
        "semantic_pairs_written": semantic_pairs,
        "group_pairs_written": group_pairs,
        "opposite_pairs_written": opposite_pairs,
        "skipped": skipped,
    }


__all__ = [
    "compute_connections",
]