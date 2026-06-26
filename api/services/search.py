"""Search service for the language-brain vault (T20+).

This module is the *service-layer* half of SPEC §5.3's search endpoint.
T20 covers AC16 (lexical search); T21 adds AC17 (semantic search
over the FAISS index). T22–T23 will wire kind toggles and type
filters into the public entry point; T24 will enforce the
``english``/``meaning`` payload hygiene invariants (AC20); T25
will polish the snippet string hygiene (AC21).

Design for additive extension
-----------------------------

T20 deliberately uses a *pure ranker function* pattern (mirroring
:mod:`api.services.connector`'s ``_compute_sentence_lexical_edges`)
so future kinds can plug in cleanly without rewriting the public
entry point. The pipeline is:

1. :func:`lexical_rank` — pure, no I/O. Takes a tokenized query
   plus in-memory sentence and word lists and returns a list of
   ``(unit_id, unit_type, score)`` tuples. This is the "algorithm
   layer" half, unit-testable in isolation.

2. :func:`_assemble_hits` — small adapter that turns the ranker's
   output into :class:`SearchHit` objects, reading the original
   unit dict for ``name`` and ``snippet``. This layer is the only
   place that introspects the unit dict's ``properties`` shape.

3. :func:`lexical_search` — the I/O-bound public entry point for
   the lexical pass. Reads units from disk, calls the ranker,
   calls the assembler, applies the limit, and returns the list.

4. :func:`semantic_search` — the I/O-bound public entry point for
   the semantic pass (T21). Loads the FAISS index from
   ``<vault>/index/``, embeds the query via the provided
   embedder (or :func:`api.services.embedder.get_embedder` if
   ``None``), and returns hits whose cosine similarity to the
   query exceeds ``threshold``. Only sentence units live in the
   FAISS index (per SPEC §6 AC9), so all semantic hits have
   ``unit_type="sentence"``.

5. :func:`merge_hits` — deterministic union-by-id merger that
   combines the lexical and semantic hit lists, keeping the
   maximum score per id. This is what the route layer (T21) and
   the future kinds toggle (T22) call after the per-kind passes.

Adding a new kind is additive — the existing lexical pass keeps
running untouched and a new ranker is unioned via
:func:`merge_hits`.

T24 hygiene helpers
-------------------

:func:`has_english_or_meaning_key` and :func:`has_natural_language_english`
are payload-sanity utilities that the AC20/AC21 acceptance tests
will assert against. They're implemented in this module early
(T20) so future tests can compose them, and so a future ``audit``
tool can call them directly. The lexical ranker itself never
copies ``english``/``meaning`` into a :class:`SearchHit`, so the
AC20 invariant already holds at T20.

I/O
---
All disk reads go through :mod:`api.services.unit_writer` for
unit dicts and :mod:`api.services.indexer` for the FAISS index.
This module never opens files directly, so the atomic-write
contract of ``write_unit`` is preserved. No writes happen here —
search is purely a read path.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

from api.services.embedder import Embedder, get_embedder
from api.services.indexer import Index
from api.services.lexical import jaccard, tokenize_sentence
from api.services.unit_writer import list_units_by_type, read_unit

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Cosine-similarity cutoff for semantic search (SPEC §6 AC17). A
#: FAISS hit is included only if its cosine to the query embedding
#: is strictly greater than this value. Default 0.6 matches the
#: SPEC's stated threshold. Tunable per call via the ``threshold``
#: kwarg on :func:`semantic_search`.
SEMANTIC_THRESHOLD: float = 0.6


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    """A single lexical search hit (T20 only).

    Attributes
    ----------
    unit_id:
        The unit's stable id (e.g. ``"wo-xihuan-chi"`` for sentences,
        ``"chī"`` for words).
    unit_type:
        Either ``"sentence"`` or ``"word"``. Group units are out of
        scope for lexical search per SPEC §5.3.
    name:
        Display string. For sentences and words, this is the unit's
        ``properties.hanzi``. Hanzi never contains ASCII a-z runs of
        length 3+, so the AC21 invariant is trivially satisfied.
    snippet:
        Secondary display string. For sentences and words, this is
        the unit's ``properties.pinyin``. Pinyin contains accented
        vowels (ā á ǎ à …) rather than ASCII a-z runs of length 3+,
        so the AC21 invariant is trivially satisfied at T20.
    score:
        The Jaccard similarity over hanzi tokens between the query
        and the unit. Always in ``(0.0, 1.0]`` because the ranker
        drops zero-overlap hits before constructing the hit.
    """

    unit_id: str
    unit_type: str
    name: str
    snippet: str
    score: float


# ---------------------------------------------------------------------------
# Constants — the closed set of filter values for the ``types`` query param
# ---------------------------------------------------------------------------


#: Unit types that lexical search ranks over. Groups are intentionally
#: excluded — SPEC §5.3 reserves ``/api/groups/{id}`` for group retrieval
#: and lexical search only sees sentence + word units.
_LEXICAL_TYPES: frozenset[str] = frozenset({"sentence", "word"})


# ---------------------------------------------------------------------------
# Pure ranker (algorithm layer)
# ---------------------------------------------------------------------------


def lexical_rank(
    query_tokens: list[str],
    sentences: list[dict[str, Any]],
    words: list[dict[str, Any]],
) -> list[tuple[str, str, float]]:
    """Compute lexical Jaccard hits against a sentence + word list.

    This is the *pure* (I/O-free) algorithm layer. Given the query's
    token list and the in-memory unit dicts, it returns a list of
    ``(unit_id, unit_type, score)`` tuples covering every unit whose
    hanzi tokens share at least one element with the query.

    The function never opens a file — that's the job of the public
    entry point :func:`lexical_search`. Tests can call it directly
    by constructing fake unit dicts.

    Algorithm
    ---------
    1. If ``query_tokens`` is empty, return ``[]``. An empty query
       can't share any token by definition, so there are no lexical
       matches.
    2. For each sentence, tokenize its ``properties.hanzi`` (via
       :func:`api.services.lexical.tokenize_sentence`, which skips
       whitespace and dedupes). If the resulting token list is
       empty, skip the sentence — there's nothing to compare.
       Otherwise, compute :func:`api.services.lexical.jaccard`
       between ``query_tokens`` and the sentence tokens.
    3. Same for each word.
    4. Keep only hits with ``score > 0`` (i.e. at least one shared
       token). Jaccard returns 0.0 for disjoint token sets and for
       empty inputs, so this single comparison is sufficient.
    5. Sort by ``(-score, unit_id)`` so the highest-scoring hits
       come first, ties broken by id ascending.
    6. Deduplicate by ``unit_id`` — a unit should appear at most
       once in the result, even if both ``sentences`` and
       ``words`` lists happen to contain the same id (e.g. a
       vault that mis-tags a unit). The first occurrence wins.

    Parameters
    ----------
    query_tokens:
        The tokenized query (typically the result of
        :func:`api.services.lexical.tokenize_sentence` on the raw
        query string). Duplicates and order don't affect the
        Jaccard math.
    sentences:
        Sentence unit dicts. Each must have an ``id`` (str);
        sentences missing ``properties.hanzi`` or with an empty
        one are skipped silently.
    words:
        Word unit dicts. Same contract as ``sentences``.

    Returns
    -------
    list[tuple[str, str, float]]
        ``(unit_id, unit_type, score)`` tuples, sorted by score
        descending then id ascending. Empty input lists yield
        empty output. No duplicates by id.
    """
    if not query_tokens:
        return []

    raw: list[tuple[str, str, float]] = []

    for unit in sentences:
        hit = _score_unit(unit, "sentence", query_tokens)
        if hit is not None:
            raw.append(hit)

    for unit in words:
        hit = _score_unit(unit, "word", query_tokens)
        if hit is not None:
            raw.append(hit)

    # Deduplicate by id. Keep the first occurrence (which is a
    # sentence, then a word, since we iterate sentences first) so
    # a unit that somehow appears in both input lists resolves to
    # a single hit. _score_unit guarantees unit_type matches the
    # source list, so this is deterministic.
    seen: set[str] = set()
    deduped: list[tuple[str, str, float]] = []
    for entry in raw:
        uid, _, _ = entry
        if uid in seen:
            continue
        seen.add(uid)
        deduped.append(entry)

    # Sort by (-score, id) for deterministic ordering: best first,
    # ties broken by id ascending.
    deduped.sort(key=lambda entry: (-entry[2], entry[0]))
    return deduped


def _score_unit(
    unit: dict[str, Any],
    unit_type: str,
    query_tokens: list[str],
) -> tuple[str, str, float] | None:
    """Return ``(id, unit_type, score)`` for one unit or ``None`` to skip.

    Returns ``None`` when:

    * the unit is not a dict;
    * the unit's ``id`` is missing or not a non-empty string;
    * the unit's ``properties.hanzi`` is missing, non-string, or
      tokenizes to ``[]`` (so Jaccard would be 0.0 anyway).

    The Jaccard call itself returns 0.0 for empty inputs, but we
    short-circuit to keep the trace clean and avoid paying the
    set-construction cost on units that can't possibly match.
    """
    if not isinstance(unit, dict):
        return None
    unit_id = unit.get("id")
    if not isinstance(unit_id, str) or not unit_id:
        return None
    properties = unit.get("properties")
    hanzi = properties.get("hanzi") if isinstance(properties, dict) else None
    if not isinstance(hanzi, str) or not hanzi:
        return None
    unit_tokens = tokenize_sentence(hanzi)
    if not unit_tokens:
        return None
    score = jaccard(query_tokens, unit_tokens)
    if score <= 0.0:
        return None
    return (unit_id, unit_type, score)


# ---------------------------------------------------------------------------
# Assembly + public entry point
# ---------------------------------------------------------------------------


def _assemble_hits(
    ranked: Iterable[tuple[str, str, float]],
    units_by_id: dict[tuple[str, str], dict[str, Any]],
) -> list[SearchHit]:
    """Map ``(id, type, score)`` tuples to :class:`SearchHit` objects.

    Looks up each ``(id, type)`` in ``units_by_id`` to read its
    ``properties.hanzi`` (``name``) and ``properties.pinyin``
    (``snippet``). Missing or malformed fields fall back to the
    empty string so a corrupt unit file can't crash the search
    response — the user will see the hit, just without a snippet,
    rather than a 500.
    """
    out: list[SearchHit] = []
    for unit_id, unit_type, score in ranked:
        unit = units_by_id.get((unit_id, unit_type))
        if unit is None:
            # Defensive: the ranker built the id/type from a unit
            # we passed in, so it should always be present in the
            # lookup. If a future refactor breaks that invariant
            # we'd rather drop the hit than crash.
            continue
        properties = unit.get("properties")
        hanzi = ""
        pinyin = ""
        if isinstance(properties, dict):
            raw_hanzi = properties.get("hanzi")
            if isinstance(raw_hanzi, str):
                hanzi = raw_hanzi
            raw_pinyin = properties.get("pinyin")
            if isinstance(raw_pinyin, str):
                pinyin = raw_pinyin
        out.append(
            SearchHit(
                unit_id=unit_id,
                unit_type=unit_type,
                name=hanzi,
                snippet=pinyin,
                score=float(score),
            )
        )
    return out


def lexical_search(
    vault_root: str,
    query: str,
    limit: int = 20,
    types: list[str] | None = None,
) -> list[SearchHit]:
    """Lexical search over sentence and word units.

    Returns up to ``limit`` :class:`SearchHit` objects sorted by
    descending Jaccard similarity (tie-break by unit id ascending).
    An empty query or empty matches return ``[]``.

    ``types`` filters by unit type. ``None`` means all types
    (sentence + word). Pass ``["sentence"]`` or ``["word"]`` to
    restrict. Any value outside the closed set
    ``{"sentence", "word"}`` makes the function return ``[]``
    — this is the T20 guard against future callers passing group
    or unknown filters; it deliberately fails closed so a typo
    never silently returns wrong results.

    The function logs an INFO line at start and end of a
    successful call. Failures (e.g. unparseable ``types``)
    currently propagate; the route layer is responsible for
    converting them to HTTP 4xx/5xx.

    Parameters
    ----------
    vault_root:
        Filesystem path to the vault root.
    query:
        Raw query string. Will be tokenized via
        :func:`api.services.lexical.tokenize_sentence`.
    limit:
        Maximum number of hits to return. Must be a positive
        int; the route clamps to ``[1, 100]``.
    types:
        Optional filter. ``None`` means all lexical types;
        otherwise must be a list containing only ``"sentence"``
        and/or ``"word"``.

    Returns
    -------
    list[SearchHit]
        Ranked hits. Empty when the query is empty, no units
        match, or the ``types`` filter excludes everything.
    """
    # Step 1 — tokenize the query.
    query_tokens = tokenize_sentence(query) if isinstance(query, str) else []
    if not query_tokens:
        return []

    # Step 2 — validate the ``types`` filter. A list with values
    # outside the closed set returns [] rather than raising, so
    # the route can pass user-supplied input without pre-validating.
    if types is not None:
        if not isinstance(types, list):
            return []
        bad = [t for t in types if t not in _LEXICAL_TYPES]
        if bad or not types:
            # An empty list is treated as "no types allowed".
            # A list with at least one bad value also returns [].
            return []
        selected = set(types)
    else:
        selected = set(_LEXICAL_TYPES)

    include_sentences = "sentence" in selected
    include_words = "word" in selected

    # Step 3 — load units. list_units_by_type is sorted by id and
    # skips corrupt files, so the I/O layer mirrors the ranker's
    # determinism contract.
    sentences = list_units_by_type(vault_root, "sentence") if include_sentences else []
    words = list_units_by_type(vault_root, "word") if include_words else []

    # Step 4 — pure rank.
    ranked = lexical_rank(query_tokens, sentences, words)

    # Step 5 — limit.
    if limit is not None and limit >= 0:
        ranked = ranked[:limit]

    # Step 6 — assemble SearchHits. Index the units by (id, type)
    # so the assembler doesn't have to scan on every hit.
    units_by_id: dict[tuple[str, str], dict[str, Any]] = {}
    for unit in sentences:
        uid = unit.get("id")
        if isinstance(uid, str) and uid:
            units_by_id[(uid, "sentence")] = unit
    for unit in words:
        uid = unit.get("id")
        if isinstance(uid, str) and uid:
            units_by_id[(uid, "word")] = unit

    hits = _assemble_hits(ranked, units_by_id)

    log.info(
        "lexical_search query=%r tokens=%d hits=%d limit=%d types=%s",
        query,
        len(query_tokens),
        len(hits),
        limit,
        sorted(selected),
    )
    return hits


# ---------------------------------------------------------------------------
# Payload-hygiene helpers (AC20, AC21) — implemented in T20 for T24
# ---------------------------------------------------------------------------


#: Keys whose presence in any nested dict of the search payload
#: violates the AC20 invariant (SPEC §5.3, §6 AC20). Defined as a
#: frozen module constant so future tests and the upcoming T24
#: payload audit share a single source of truth.
_FORBIDDEN_KEYS: frozenset[str] = frozenset({"english", "meaning"})


def has_english_or_meaning_key(payload: dict | list | object) -> bool:
    """Return ``True`` if any dict in ``payload`` (recursively) has a
    key named ``'english'`` or ``'meaning'``.

    Used by AC20 tests; implemented early so T24 can compose it.
    For T20 this function exists but no search function exposes
    ``english`` / ``meaning`` keys yet — they're only on the
    underlying unit dicts which the ranker reads from. The
    function returns ``False`` for any non-container input
    (``None``, scalars) and ``False`` for containers whose
    contents are all scalars. A bare dict whose only keys are
    ``english`` or ``meaning`` (and nothing else) still returns
    ``True`` because the recursion visits it.

    The check is intentionally simple: we walk every nested
    dict and look at its keys. Tuples are treated like lists
    because the SPEC's payload is JSON, where only ``list``
    exists, but defensive tuple support keeps the helper
    composable from non-JSON call sites (tests, debug tools).

    Parameters
    ----------
    payload:
        Any Python value. Dicts and lists are walked
        recursively; everything else is treated as a leaf and
        contributes no forbidden keys.

    Returns
    -------
    bool
        ``True`` if any reachable dict has a forbidden key,
        ``False`` otherwise.
    """
    if isinstance(payload, dict):
        if any(k in _FORBIDDEN_KEYS for k in payload.keys()):
            return True
        return any(has_english_or_meaning_key(v) for v in payload.values())
    if isinstance(payload, list):
        return any(has_english_or_meaning_key(item) for item in payload)
    if isinstance(payload, tuple):
        return any(has_english_or_meaning_key(item) for item in payload)
    return False


#: Pre-compiled ASCII a-z run detector for AC21. The pattern
#: matches three or more consecutive ASCII letters. Pinyin
#: contains accented vowels (ā á ǎ à …) but no plain ASCII
#: ``a``/``e``/``i``/``o``/``u`` sequences longer than two in
#: normal usage; a 3+ length threshold avoids false positives
#: from "le" (了) or "ma" (吗). The regex is pre-compiled at
#: module import for speed — search results may include dozens
#: of hits and ``re.search`` is called once per item per test.
_ASCII_LETTER_RUN: re.Pattern[str] = re.compile(r"[A-Za-z]{3,}")


def has_natural_language_english(s: str) -> bool:
    """Return ``True`` if ``s`` contains any ASCII a-z run of length
    ``>= 3``.

    Per SPEC §6 AC21, search results must not leak natural-language
    English in ``name`` or ``snippet``. Pinyin contains accented
    vowels (ā á ǎ à etc.), not ASCII a-z runs of 3+, so a simple
    ASCII regex check is sufficient for the AC.

    The function is conservative — a 2-letter ASCII run like
    ``"le"`` (了 as a romanization fragment) does NOT trigger.
    Real natural-language English almost always contains at
    least one 3+ ASCII run per short phrase ("the", "and",
    "with", "I am eating", …), so the threshold catches the
    common cases without false positives on short pinyin
    substrings.

    Parameters
    ----------
    s:
        Any string. Non-strings return ``False`` defensively so
        the helper is safe to call on dict values or ``None``
        during audits.

    Returns
    -------
    bool
        ``True`` if ``s`` contains an ASCII a-z/A-Z run of
        length 3 or more.
    """
    if not isinstance(s, str):
        return False
    return _ASCII_LETTER_RUN.search(s) is not None


# ---------------------------------------------------------------------------
# Semantic search (T21 — SPEC §6 AC17)
# ---------------------------------------------------------------------------


def semantic_search(
    vault_root: str,
    query: str,
    limit: int = 20,
    threshold: float = SEMANTIC_THRESHOLD,
    embedder: Embedder | None = None,
) -> list[SearchHit]:
    """Semantic search over sentence units via the FAISS index.

    AC17 contract: returns sentence units whose ``meaning`` embedding
    has cosine similarity to the query embedding strictly greater
    than ``threshold``. Default ``threshold`` is ``SEMANTIC_THRESHOLD``
    (0.6 per the SPEC).

    The function never raises on a missing index — an empty vault
    returns ``[]``. It also never raises on a missing unit file: a
    FAISS hit whose sentence unit has been deleted from disk between
    reindex and search is silently dropped (the next reindex will
    reconcile; this is the same fall-forward policy used elsewhere
    in the indexer).
    """
    if not isinstance(query, str) or not query.strip():
        return []
    if embedder is None:
        embedder = get_embedder()
    index = Index.load_or_empty(vault_root)
    if len(index) == 0:
        return []
    query_vec = embedder.embed(query)
    raw_hits = index.search(query_vec, k=limit)
    sentences_by_id = {s["id"]: s for s in list_units_by_type(vault_root, "sentence")}
    out: list[SearchHit] = []
    for raw in raw_hits:
        if raw.score <= threshold:
            continue
        unit = sentences_by_id.get(raw.unit_id)
        if unit is None:
            continue
        properties = unit.get("properties", {})
        if not isinstance(properties, dict):
            continue
        hanzi = properties.get("hanzi") if isinstance(properties.get("hanzi"), str) else ""
        pinyin = properties.get("pinyin") if isinstance(properties.get("pinyin"), str) else ""
        out.append(
            SearchHit(
                unit_id=raw.unit_id,
                unit_type="sentence",
                name=hanzi,
                snippet=pinyin,
                score=float(raw.score),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Hit merger (T21 — supports future kinds toggle T22)
# ---------------------------------------------------------------------------


def merge_hits(*hit_lists: list[SearchHit]) -> list[SearchHit]:
    """Union of multiple hit lists, deduplicated by ``(unit_id, unit_type)``.

    When the same key appears in more than one input list, the hit
    with the maximum score wins; ties are broken by selecting the
    first occurrence (left-to-right argument order). The merged list
    is sorted by ``(-score, unit_id, unit_type)`` for determinism.
    """
    if not hit_lists:
        return []
    best_by_key: dict[tuple[str, str], SearchHit] = {}
    for hit_list in hit_lists:
        if not hit_list:
            continue
        for hit in hit_list:
            key = (hit.unit_id, hit.unit_type)
            existing = best_by_key.get(key)
            if existing is None or hit.score > existing.score:
                best_by_key[key] = hit
    return sorted(
        best_by_key.values(),
        key=lambda h: (-h.score, h.unit_id, h.unit_type),
    )


__all__ = [
    "SearchHit",
    "has_english_or_meaning_key",
    "has_natural_language_english",
    "lexical_rank",
    "lexical_search",
    "merge_hits",
    "semantic_search",
]
