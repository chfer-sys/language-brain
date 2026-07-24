"""Search service for the language-brain vault (T20+).

This module is the *service-layer* half of SPEC §5.3's search endpoint.
T20 covers AC16 (lexical search); T21 adds AC17 (semantic search
over the FAISS index). T22 wires the kinds toggle; T23 extends the
``types`` filter to include ``group`` and adds :func:`group_search`.
T24 will enforce the ``english``/``meaning`` payload hygiene
invariants (AC20); T25 will polish the snippet string hygiene (AC21).

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

from api.services.db import (
    get_units_by_ids_sqlite,
    list_units_by_type_sqlite,
    list_units_by_types_sqlite,
)
from api.services.embedder import Embedder, get_embedder
from api.services.indexer import Index
from api.services.lexical import _strip_diacritics, jaccard, tokenize_sentence
from api.services.unit_writer import list_units_by_type

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    """A single lexical search hit (T20+).

    Attributes
    ----------
    unit_id:
        The unit's stable id (e.g. ``"wo-xihuan-chi"`` for sentences,
        ``"chī"`` for words, ``"basic-verbs"`` for groups).
    unit_type:
        One of ``"sentence"``, ``"word"``, ``"group"``. Group hits
        were added in T23 alongside the extended ``types`` filter.
    name:
        Display string. For sentences and words, this is the unit's
        ``properties.hanzi``. Hanzi never contains ASCII a-z runs of
        length 3+, so the AC21 invariant is trivially satisfied. For
        groups, this is the unit's ``properties.display_name``
        (falling back to the slug id).
    snippet:
        Secondary display string. For sentences and words, this is
        the unit's ``properties.pinyin``. Pinyin contains accented
        vowels (ā á ǎ à …) rather than ASCII a-z runs of length 3+,
        so the AC21 invariant is trivially satisfied at T20. For
        groups, this is the slug id (e.g. ``"basic-verbs"``) — a
        ASCII run of length 3+ appears only when the slug itself
        contains one, which the caller controls. The group hit's
        name and snippet therefore both satisfy AC21 forward-compat.
    score:
        The similarity score between the query and the unit.
        For sentence and word units, this is the Jaccard
        similarity over hanzi tokens (always in ``(0.0, 1.0]``
        because the ranker drops zero-overlap hits before
        constructing the hit). For groups, this is the fraction
        of query tokens that appear in the slug/display-name
        haystack, plus a small prefix-match bonus, so the score
        can be up to ``1.1``.
    containing_sentences:
        For word-type hits, up to 3 example sentence hanzi strings
        that contain this word (via lexical edges). None for
        sentence/group hits.
    """

    unit_id: str
    unit_type: str
    name: str
    snippet: str
    score: float
    containing_sentences: list[str] | None = None


# ---------------------------------------------------------------------------
# Constants — the closed set of filter values for the ``types`` query param
# ---------------------------------------------------------------------------


#: Unit types that lexical search ranks over. T23 adds ``"group"``
#: alongside ``"sentence"`` and ``"word"`` so callers can filter
#: the search response to groups only (per SPEC §5.3's expanded
#: ``types`` query parameter). Group units still have their own
#: canonical endpoint at ``/api/groups/{id}`` — search just gets a
#: lexical pass over their slugs and display names.
_LEXICAL_TYPES: frozenset[str] = frozenset({"sentence", "word", "compound", "group"})


# ---------------------------------------------------------------------------
# Pure ranker (algorithm layer)
# ---------------------------------------------------------------------------


def lexical_rank(
    query_tokens: list[str],
    sentences: list[dict[str, Any]],
    words: list[dict[str, Any]],
    raw_query: str | None = None,
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
    raw_query:
        The original query string before tokenization. Used for
        pinyin syllable-level scoring when the query is a multi-syllable
        ASCII pinyin string (e.g. "wo xiang chi").

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
        hit = _score_unit(unit, "sentence", query_tokens, raw_query)
        if hit is not None:
            raw.append(hit)

    for unit in words:
        hit = _score_unit(unit, "word", query_tokens, raw_query)
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


def _is_pinyin_query(query: str) -> bool:
    """Return True if ``query`` looks like a pinyin query (ASCII letters + spaces only).

    A pinyin query contains only ASCII letters a-z (after stripping diacritics)
    and spaces, with at least one space to indicate multi-syllable input.
    This distinguishes pinyin from:
      - CJK hanzi queries (e.g. "吃")
      - English word queries (e.g. "eat" — no spaces, but also no CJK)
    """
    if not isinstance(query, str):
        return False
    stripped = _strip_diacritics(query)
    # Must contain at least one space (multi-syllable) to be treated as pinyin.
    # Single-word ASCII like "eat" is treated as English, not pinyin.
    if " " not in stripped:
        return False
    # Every character must be ASCII letter or space.
    return all(c.isascii() and (c.isalpha() or c.isspace()) for c in stripped)


def _score_unit(
    unit: dict[str, Any],
    unit_type: str,
    query_tokens: list[str],
    raw_query: str | None = None,
) -> tuple[str, str, float] | None:
    """Return ``(id, unit_type, score)`` for one unit or ``None`` to skip.

    Returns ``None`` when:

    * the unit is not a dict;
    * the unit's ``id`` is missing or not a non-empty string;
    * the unit has no tokenizable text in any of its scored fields
      (hanzi + english + meaning + pinyin).

    Scoring
    -------
    Four fields are scored against ``query_tokens``:

    1. ``properties.hanzi`` — char-level tokens (CJK-aware via
       :func:`api.services.lexical.tokenize_sentence`).
    2. ``properties.english`` — lowercased whole-word tokens (via
       :func:`_tokenize_english_for_search`).
    3. ``properties.meaning`` — same whole-word tokenizer.
    4. ``properties.pinyin`` — syllable-level Jaccard for pinyin queries
       (bonus: 1.5× multiplier rewards multi-syllable matches).

    The final score is the **max** of the Jaccard values across all fields.
    For pinyin queries, syllable-level Jaccard is computed against the stored
    pinyin syllables, then boosted by 1.5× before taking the max.

    Empty fields are silently skipped (no penalty). A unit with
    no tokenizable text returns ``None``.
    """
    if not isinstance(unit, dict):
        return None
    unit_id = unit.get("id")
    if not isinstance(unit_id, str) or not unit_id:
        return None
    properties = unit.get("properties")
    if not isinstance(properties, dict):
        return None

    best_score = 0.0

    hanzi = properties.get("hanzi")
    if isinstance(hanzi, str) and hanzi:
        hanzi_tokens = tokenize_sentence(hanzi)
        if hanzi_tokens:
            best_score = max(best_score, jaccard(query_tokens, hanzi_tokens))

    for field_name in ("english", "meaning"):
        text = properties.get(field_name)
        if not isinstance(text, str) or not text.strip():
            continue
        text_tokens = _tokenize_english_for_search(text)
        if text_tokens:
            best_score = max(best_score, jaccard(query_tokens, text_tokens))

    # Pinyin-aware scoring: syllable-level Jaccard for pinyin queries.
    # ponytail: _is_pinyin_query is O(n) on query string length (n ≤ ~50 for pinyin),
    # called once per unit. For large vaults consider caching, but n is small.
    if raw_query is not None and _is_pinyin_query(raw_query):
        stored_pinyin = properties.get("pinyin")
        if isinstance(stored_pinyin, str) and stored_pinyin:
            # Split stored pinyin into syllables (whitespace-separated).
            stored_syllables = _strip_diacritics(stored_pinyin).split()
            if stored_syllables:
                # Split the raw query into syllables too.
                query_syllables = _strip_diacritics(raw_query).split()
                if query_syllables:
                    syllable_jacc = jaccard(query_syllables, stored_syllables)
                    best_score = max(best_score, syllable_jacc * 1.5)

    if best_score <= 0.0:
        return None
    return (unit_id, unit_type, best_score)


#: Regex used to split English text into whole-word tokens for
#: search scoring. Same shape as
#: :data:`api.services.english_slice._TOKEN_RE` — kept in sync so
#: the search ranker and the commit-time slice use the same token
#: definition. We don't import from english_slice to avoid a
#: layering dependency (search is lower-level than services that
#: already depend on settings).
_ENGLISH_WORD_RE = re.compile(r"[A-Za-z']+")


def _tokenize_english_for_search(text: str) -> list[str]:
    """Lowercased whole-word tokens for English search scoring.

    Unlike :func:`api.services.english_slice._tokenize_english` this
    does NOT drop stopwords — search needs to match ``"a"`` /
    ``"the"`` too so a user typing those characters doesn't get an
    empty result. The token shape is the same (whole words, not
    characters) so the char-Jaccard false positives disappear.

    Returns ``[]`` for non-string, empty, or whitespace-only input.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    return [t for t in _ENGLISH_WORD_RE.findall(text.lower())]


# ---------------------------------------------------------------------------
# Assembly + public entry point
# ---------------------------------------------------------------------------


def _assemble_hits(
    ranked: Iterable[tuple[str, str, float]],
    units_by_id: dict[tuple[str, str], dict[str, Any]],
    sentences: list[dict[str, Any]] | None = None,
) -> list[SearchHit]:
    """Map ``(id, type, score)`` tuples to :class:`SearchHit` objects.

    Looks up each ``(id, type)`` in ``units_by_id`` to read its
    ``properties.hanzi`` (``name``) and ``properties.pinyin``
    (``snippet``). Missing or malformed fields fall back to the
    empty string so a corrupt unit file can't crash the search
    response — the user will see the hit, just without a snippet,
    rather than a 500.

    For word-type hits, if ``sentences`` is provided, the function
    extracts up to 3 example sentence hanzi strings from the word's
    lexical connections (per SPEC §2.2: word units never stand alone).
    """
    # Build sentence lookup for containing_sentences resolution.
    sentences_by_id: dict[str, dict[str, Any]] = {}
    if sentences:
        for s in sentences:
            sid = s.get("id")
            if isinstance(sid, str) and sid:
                sentences_by_id[sid] = s

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

        # Extract containing_sentences for word units.
        containing: list[str] | None = None
        if unit_type == "word" and sentences_by_id:
            containing = []
            connections = unit.get("connections")
            if isinstance(connections, list):
                for conn in connections:
                    if isinstance(conn, dict) and conn.get("kind") == "lexical":
                        to_id = conn.get("to")
                        if isinstance(to_id, str) and to_id in sentences_by_id:
                            sent = sentences_by_id[to_id]
                            sent_props = sent.get("properties")
                            if isinstance(sent_props, dict):
                                sh = sent_props.get("hanzi")
                                if isinstance(sh, str) and sh:
                                    containing.append(sh)
                                    if len(containing) >= 3:
                                        break
            if not containing:
                containing = None

        out.append(
            SearchHit(
                unit_id=unit_id,
                unit_type=unit_type,
                name=hanzi,
                snippet=pinyin,
                score=float(score),
                containing_sentences=containing,
            )
        )
    return out


def lexical_search(
    vault_root: str,
    query: str,
    limit: int = 20,
    types: list[str] | None = None,
) -> list[SearchHit]:
    """Lexical search over sentence, word, and group units.

    Returns up to ``limit`` :class:`SearchHit` objects sorted by
    descending score (Jaccard for sentence + word, substring
    overlap for groups, tie-break by unit id ascending). An empty
    query or empty matches return ``[]``.

    ``types`` filters by unit type. ``None`` means all lexical types
    (sentence + word + compound + group). Pass any subset of
    ``{"sentence", "word", "compound", "group"}`` to restrict. Any value outside
    the closed set makes the function return ``[]`` — this is the
    T20 guard against future callers passing unknown filters; it
    deliberately fails closed so a typo never silently returns wrong
    results.

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
        :func:`api.services.lexical.tokenize_sentence` for the
        sentence/word pass and via :func:`group_search`'s own
        alphanumeric tokenizer for the group pass.
    limit:
        Maximum number of hits to return. Must be a positive
        int; the route clamps to ``[1, 100]``.
    types:
        Optional filter. ``None`` means all lexical types;
        otherwise must be a list containing only values from
        ``{"sentence", "word", "compound", "group"}``.

    Returns
    -------
    list[SearchHit]
        Ranked hits. Empty when the query is empty, no units
        match, or the ``types`` filter excludes everything.
    """
    # Step 1 — tokenize the query.
    # We build the canonical query token set as the UNION of
    # char-level tokens (good for hanzi queries) and whole-word
    # tokens (good for English queries). The ranker's max-of-three
    # Jaccard scoring on each unit field then naturally picks the
    # right field for the query type:
    #
    #   - Hanzi query "吃" → char tokens {吃}; unit's hanzi tokens
    #     share 吃 → max Jaccard is via the hanzi field.
    #   - English query "eat" → word tokens {eat}; unit's english
    #     tokens share eat → max Jaccard is via the english field.
    #   - Mixed query "吃 eat" → both sets; whichever field matches
    #     best wins.
    #
    # Before v0.4.1 T3, only char tokens were used, which made
    # "i want to eat" match `emotion` (0.625 char overlap) instead
    # of the eat-related sentences.
    if isinstance(query, str):
        normalized = _strip_diacritics(query)
        char_tokens = tokenize_sentence(normalized)
        word_tokens = _tokenize_english_for_search(normalized)
        # De-dupe via set union, then back to a list (order
        # doesn't matter for Jaccard).
        query_tokens = list(set(char_tokens) | set(word_tokens))
    else:
        query_tokens = []
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
    include_groups = "group" in selected

    # Step 3 — load units. v0.10: route through SQLite instead of JSON
    # file scan. Consolidate all needed types into ONE query via
    # list_units_by_types_sqlite (AC2: ≤2 SELECTs total; this is 1).
    # Falls back per-type to JSON path if SQLite returns empty (database
    # not migrated).
    types_to_fetch: list[str] = []
    if include_sentences or include_words:
        types_to_fetch.append("sentence")
    if include_words:
        types_to_fetch.append("word")
    if include_groups:
        types_to_fetch.append("group")

    if types_to_fetch:
        by_type = list_units_by_types_sqlite(vault_root, types_to_fetch)
        # JSON fallback per type
        for t in types_to_fetch:
            if not by_type.get(t):
                by_type[t] = list_units_by_type(vault_root, t)
        sentences = by_type.get("sentence", [])
        words = by_type.get("word", [])
        group_units = by_type.get("group", [])
    else:
        sentences = []
        words = []
        group_units = []

    # Step 4 — pure rank. Sentence + word pass uses Jaccard over
    # hanzi tokens. The group pass uses :func:`group_search`,
    # which scores over slug ids and display names. We merge them
    # here so the limit applies to the combined top-N.
    ranked_sentences = sentences if include_sentences else []
    ranked = lexical_rank(query_tokens, ranked_sentences, words, raw_query=query)
    group_hits: list[SearchHit] = []
    if include_groups:
        group_hits = group_search(vault_root, query, limit=limit)
        # Convert the group SearchHits into ranker-shape tuples so
        # _assemble_hits can consume them uniformly.
        for hit in group_hits:
            ranked.append((hit.unit_id, hit.unit_type, hit.score))

    # Step 5 — re-sort the combined ranking so group hits interleave
    # with sentence/word hits by score, then trim to ``limit``.
    ranked.sort(key=lambda entry: (-entry[2], entry[0]))
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
    if include_groups:
        for unit in group_units:
            uid = unit.get("id")
            if isinstance(uid, str) and uid:
                units_by_id[(uid, "group")] = unit

    hits = _assemble_hits(ranked, units_by_id, sentences=sentences)

    # If the group ranker contributed, _assemble_hits fell back to
    # empty name/snippet because groups don't carry hanzi/pinyin.
    # Patch each group hit's name/snippet to the group's
    # display_name and slug id so the AC21 invariant (no natural
    # English in name/snippet) holds for groups too.
    if include_groups and hits:
        # ponytail: reuse groups already fetched in the consolidated
        # query at step 3 — no second SELECT needed.
        patched: list[SearchHit] = []
        for hit in hits:
            if hit.unit_type != "group":
                patched.append(hit)
                continue
            unit = units_by_id.get((hit.unit_id, "group"))
            display_name = ""
            if isinstance(unit, dict):
                properties = unit.get("properties")
                if isinstance(properties, dict):
                    raw_dn = properties.get("display_name")
                    if isinstance(raw_dn, str):
                        display_name = raw_dn
            patched.append(
                SearchHit(
                    unit_id=hit.unit_id,
                    unit_type=hit.unit_type,
                    name=display_name if display_name else hit.unit_id,
                    snippet=hit.unit_id,
                    score=hit.score,
                )
            )
        hits = patched

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
# Group search (T23 — extends the ``types`` filter to include ``group``)
# ---------------------------------------------------------------------------


#: Bonus added to a group's score when the first character of the
#: query's first token matches the first character of the group's
#: slug id. This is a cheap "the query starts where the id starts"
#: hint that pushes exact-prefix hits above substring hits. The
#: value is small (0.1) so it never outweighs a meaningful fraction
#: of matched tokens.
_GROUP_ID_PREFIX_BONUS: float = 0.1


def group_search(
    vault_root: str,
    query: str,
    limit: int = 20,
) -> list[SearchHit]:
    """Lexical search over group units (T23).

    Ranks every group unit by how many of the query's lowercase
    tokens appear as a substring of either the group's
    ``properties.display_name`` or its slug ``id``. Returns at most
    ``limit`` :class:`SearchHit` objects sorted by score descending
    (tie-break by unit id ascending).

    Algorithm
    ---------
    1. If ``query`` is empty or non-string, return ``[]``. An empty
       query can't share any token.
    2. Read all group units via
       :func:`api.services.unit_writer.list_units_by_type`. This
       reads them off disk and skips corrupt files.
    3. Tokenize the query into lowercase substrings. The tokenizer
       is intentionally simple — :func:`api.services.lexical.
       tokenize_sentence` would split per-character, which is wrong
       for ASCII slug lookups (we want whole words like "basic" to
       match a slug like ``basic-verbs``). So we lowercase the
       query and split on non-alphanumeric runs.
    4. For each group, build a single haystack of
       ``"<slug_id> <display_name>"`` (lowercased) and count how many
       query tokens appear as substrings of that haystack. Score is
       ``matched / total_query_tokens``. If no token matches, the
       group is skipped (no zero-score noise).
    5. Add :data:`_GROUP_ID_PREFIX_BONUS` when the first character
       of the first query token equals the first character of the
       group's slug id — an exact-prefix hint.
    6. Sort by ``(-score, unit_id)`` and slice to ``limit``.

    Parameters
    ----------
    vault_root:
        Filesystem path to the vault root.
    query:
        Raw query string. Non-string input returns ``[]``.
    limit:
        Maximum number of hits to return.

    Returns
    -------
    list[SearchHit]
        Ranked hits. Empty when the query is empty, no groups match,
        or the vault has no groups. The hit's ``name`` is the
        group's display_name (falling back to the slug id when
        display_name is empty), and ``snippet`` is the slug id so
        the response carries no natural-language English (AC21).
        ``score`` is in ``(0.0, 1.1]``.
    """
    if not isinstance(query, str) or not query.strip():
        return []

    # Strip tone diacritics before tokenizing so "wǒ xiǎng chī"
    # produces ["wo", "xiang", "chi"] instead of partial ASCII chunks.
    normalized = _strip_diacritics(query)

    # Lowercase tokens, split on any non-alphanumeric character so
    # ASCII slug queries like "basic-verbs" or "Basic Verbs" both
    # produce {basic, verbs}.
    raw_tokens = re.findall(r"[A-Za-z0-9]+", normalized.lower())
    if not raw_tokens:
        return []

    groups = list_units_by_type_sqlite(vault_root, "group")
    if not groups:
        groups = list_units_by_type(vault_root, "group")

    ranked: list[tuple[str, str, float]] = []
    first_token_first_char = raw_tokens[0][:1]
    # Match against each group via two separate checks so we keep
    # the existing substring-match behavior on slug ids (lets a user
    # type "verb" and find the slug ``basic-verbs``) but switch to
    # whole-word match on display names (so typing "i want to eat"
    # no longer false-positives on the "Emotion" group via the
    # substring ``"i" in "g-emotion emotion"``).
    #
    # A token matches when EITHER:
    #   (a) it appears as a substring of the slug (preserves the
    #       existing partial-type behavior on kebab-case ids), OR
    #   (b) it equals a whole-word token of the display_name (new
    #       v0.4.1 path that kills the ASCII false positives).
    for group in groups:
        if not isinstance(group, dict):
            continue
        slug_id = group.get("id")
        if not isinstance(slug_id, str) or not slug_id:
            continue
        properties = group.get("properties")
        display_name = ""
        if isinstance(properties, dict):
            raw_dn = properties.get("display_name")

            if isinstance(raw_dn, str):
                display_name = raw_dn

        slug_lower = slug_id.lower()
        display_words = set(
            re.findall(r"[A-Za-z0-9]+", display_name.lower())
        )

        def _match(tok: str) -> bool:
            # Whole-word match on display_name kills the
            # ASCII-char-false-positive bug (typing "i" no longer
            # hits the "Ability" group via "i" in "ability").
            if display_words and tok in display_words:
                return True
            # Substring on slug preserves autocomplete (typing "verb"
            # finds "basic-verbs"), but only for tokens that are long
            # enough to be meaningful. A single character matches too
            # many slugs — every slug containing that letter fires.
            if len(tok) >= 2 and tok in slug_lower:
                return True
            return False

        matched = sum(1 for tok in raw_tokens if _match(tok))
        if matched <= 0:
            continue
        score = matched / len(raw_tokens)
        if slug_id[:1] and slug_id[:1].lower() == first_token_first_char:
            score += _GROUP_ID_PREFIX_BONUS

        ranked.append((slug_id, "group", float(score)))

    ranked.sort(key=lambda entry: (-entry[2], entry[0]))
    if limit is not None and limit >= 0:
        ranked = ranked[:limit]

    # Assemble hits: name = display_name (fallback to slug), snippet = slug id.
    units_by_id = {(g.get("id"), "group"): g for g in groups if isinstance(g, dict)}
    hits: list[SearchHit] = []
    for unit_id, unit_type, score in ranked:
        unit = units_by_id.get((unit_id, unit_type))
        properties = unit.get("properties") if isinstance(unit, dict) else None
        display_name = ""
        if isinstance(properties, dict):
            raw_dn = properties.get("display_name")
            if isinstance(raw_dn, str):
                display_name = raw_dn
        name = display_name if display_name else unit_id
        hits.append(
            SearchHit(
                unit_id=unit_id,
                unit_type=unit_type,
                name=name,
                snippet=unit_id,
                score=float(score),
            )
        )

    log.info(
        "group_search query=%r tokens=%d hits=%d limit=%d",
        query,
        len(raw_tokens),
        len(hits),
        limit,
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
    """Return ``True`` if ``s`` contains a natural-language English
    word of length 3+ (per SPEC §6 AC21).

    A "natural-language English word" here is a contiguous ASCII
    letter run of length >= 3 whose immediate neighbors (if any)
    are NOT hyphens or digits. The hyphen exclusion is critical
    for slug identifiers like ``basic-verbs`` (the runs "basic"
    and "verbs" are *parts of an identifier*, not English words).
    The digit exclusion prevents accidental triggers on
    alphanumeric tokens.

    Examples
    --------
    - ``"hello"`` → True.
    - ``"I am eating"`` → True ("eating" is 7 ASCII, bounded by spaces).
    - ``"wǒ xǐhuān chī"`` → False (no pure-ASCII runs).
    - ``"basic-verbs"`` → False (the runs "basic" and "verbs" are
      bounded by hyphens — they're identifier parts).
    - ``"daily-life"`` → False.
    - ``"daily life"`` → True ("daily" and "life" are real words).
    - ``"abc123"`` → False (the run "abc" is bounded by a digit).
    - ``"a b c"`` → False (single-letter words don't trigger;
      threshold is 3+).
    - ``"the"`` → True (the shortest common English word).
    - ``"I"`` → False (single character).

    The threshold (3+) avoids false positives on short pinyin
    substrings like ``"le"`` (了) or ``"ma"`` (吗), which are
    2 letters and bounded by spaces in normal pinyin strings.

    Parameters
    ----------
    s:
        Any string. Non-strings return ``False`` defensively so
        the helper is safe to call on dict values or ``None``
        during audits.

    Returns
    -------
    bool
        ``True`` if ``s`` contains a 3+ ASCII letter run whose
        neighbors (if any) are not hyphens or digits. This is
        the strict reading of "natural-language English" used
        by AC21.
    """
    if not isinstance(s, str):
        return False
    for m in re.finditer(r"[A-Za-z]{3,}", s):
        # Inspect the character immediately before and after the match.
        # If either neighbor exists and is a hyphen or digit, the
        # match is part of an identifier like "basic-verbs" or
        # "abc123" and should not count.
        start, end = m.start(), m.end()
        before = s[start - 1] if start > 0 else None
        after = s[end] if end < len(s) else None
        if before in ("-",) or after in ("-",):
            continue
        if before is not None and before.isdigit():
            continue
        if after is not None and after.isdigit():
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# Semantic search (T21 — SPEC §6 AC17)
# ---------------------------------------------------------------------------


def semantic_search(
    vault_root: str,
    query: str,
    limit: int = 20,
    threshold: float | None = None,
    embedder: Embedder | None = None,
) -> list[SearchHit]:
    """Semantic search over sentence units via the FAISS index.

    AC17 contract: returns sentence units whose ``meaning`` embedding
    has cosine similarity to the query embedding strictly greater
    than ``threshold``. Default ``threshold`` is read from the
    process settings (:data:`api.config.Settings.semantic_threshold`,
    default 0.3 — observed max cosine scores range 0.17–0.51).

    The function never raises on a missing index — an empty vault
    returns ``[]``. It also never raises on a missing unit file: a
    FAISS hit whose sentence unit has been deleted from disk between
    reindex and search is silently dropped (the next reindex will
    reconcile; this is the same fall-forward policy used elsewhere
    in the indexer).
    """
    if not isinstance(query, str) or not query.strip():
        return []
    if threshold is None:
        from api.config import get_settings

        threshold = get_settings().semantic_threshold
    if embedder is None:
        embedder = get_embedder()
    index = Index.load_or_empty(vault_root)
    if len(index) == 0:
        return []
    query_vec = embedder.embed(query)
    raw_hits = index.search(query_vec, k=limit)
    # v0.10: resolve FAISS hit unit_ids via SQLite (1 query) instead of
    # loading all sentence JSON files. Falls back to JSON path if SQLite
    # returns empty (database not migrated).
    hit_ids = [raw.unit_id for raw in raw_hits]
    sentences_by_id = get_units_by_ids_sqlite(vault_root, hit_ids)
    if not sentences_by_id:
        # Fallback: JSON path (database not migrated or units not in SQLite).
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
# Autocomplete / suggest (T26 — SPEC §5.3, §6 AC27b)
# ---------------------------------------------------------------------------


#: Default limit for :func:`suggest_units`. Matches SPEC §5.3's
#: ``GET /api/search/suggest?q=...&limit=5`` contract.
_SUGGEST_DEFAULT_LIMIT: int = 5

#: Hard cap on the ``limit`` parameter; the route clamps with
#: Pydantic's ``le=20`` and the service clamps again defensively.
_SUGGEST_MAX_LIMIT: int = 20


def suggest_units(
    vault_root: str,
    prefix: str,
    limit: int = _SUGGEST_DEFAULT_LIMIT,
    types: list[str] | None = None,
) -> list[dict]:
    """Return up to ``limit`` unit names that start with ``prefix``.

    Implements SPEC §5.3's autocomplete endpoint and satisfies
    SPEC §6 AC27b (``<=5`` unit-name matches, no ``english`` or
    ``meaning`` keys in the response payload).

    Each returned entry is ``{"id": str, "type": "sentence" |
    "word" | "group", "name": str}``. The ``name`` field is the
    unit's display string:

    * For sentences and words, ``name`` is the unit's
      ``properties.hanzi``.
    * For groups, ``name`` is the unit's
      ``properties.display_name``; if that's empty, ``name`` falls
      back to the slug id.

    Matching
    --------
    The function compares the lowercased ``prefix`` against the
    lowercased display string for each unit and keeps every unit
    whose display string starts with that prefix. This is *prefix*
    matching, not substring — typing ``"Bas"`` matches
    ``"Basic Verbs"`` but not ``"Verbs Basic"``. The match is
    case-insensitive on both sides.

    Sort & limit
    ------------
    Results are sorted alphabetically by ``name`` (lowercased
    comparison for stability across scripts), then by ``id`` as a
    tie-break. The function clamps ``limit`` to ``[1, 20]`` and
    truncates the output list to ``limit`` entries.

    ``types`` filter
    ----------------
    ``None`` (the default) means all four types — sentences,
    words, compounds, and groups. Pass any subset of
    ``{"sentence", "word", "compound", "group"}`` to restrict. An empty list
    or a list containing a value outside the closed set returns
    ``[]`` rather than raising — the route is responsible for
    rejecting bad input with 422.

    Parameters
    ----------
    vault_root:
        Filesystem path to the vault root.
    prefix:
        The prefix to autocomplete. Empty / non-string / whitespace-
        only input returns ``[]`` without touching disk.
    limit:
        Maximum number of suggestions to return. Clamped to
        ``[1, 20]``. Default 5.
    types:
        Optional list of unit types to include. ``None`` means all
        four; otherwise must be a subset of
        ``{"sentence", "word", "compound", "group"}``.

    Returns
    -------
    list[dict]
        ``{"id", "type", "name"}`` dicts, alphabetically sorted by
        ``name`` (then ``id``), capped at the clamped ``limit``.
        Never contains ``english`` or ``meaning`` keys (AC20 / AC27b).
    """
    if not isinstance(prefix, str):
        return []

    # The route layer strips and re-validates; the service is
    # defensive so callers that bypass the route (e.g. an
    # internal indexer / CLI) still get safe behavior.
    normalized = prefix.strip().lower()
    if not normalized:
        return []

    # Clamp limit. Out-of-range ints collapse to the boundary,
    # matching the SPEC's "no payload leak of english/meaning"
    # posture: we silently fix a too-large/too-small limit rather
    # than error, so a typo can't deny service.
    try:
        limit_int = int(limit)
    except (TypeError, ValueError):
        limit_int = _SUGGEST_DEFAULT_LIMIT
    if limit_int < 1:
        limit_int = 1
    if limit_int > _SUGGEST_MAX_LIMIT:
        limit_int = _SUGGEST_MAX_LIMIT

    # ``types`` validation mirrors :func:`lexical_search`: an
    # empty list or a list with any non-closed-set value returns
    # ``[]`` rather than silently producing partial results.
    selected: set[str]
    if types is None:
        selected = {"sentence", "word", "compound", "group"}
    elif isinstance(types, list) and types:
        if any(not isinstance(t, str) for t in types):
            return []
        if any(t not in _LEXICAL_TYPES for t in types):
            return []
        selected = set(types)
    else:
        return []

    include_sentences = "sentence" in selected
    include_words = "word" in selected
    include_groups = "group" in selected

    out: list[tuple[str, str, str]] = []  # (sort_name, id, type)

    if include_sentences:
        sentence_units = list_units_by_type_sqlite(vault_root, "sentence")
        if not sentence_units:
            sentence_units = list_units_by_type(vault_root, "sentence")
        for unit in sentence_units:
            if not isinstance(unit, dict):
                continue
            uid = unit.get("id")
            if not isinstance(uid, str) or not uid:
                continue
            properties = unit.get("properties")
            hanzi = properties.get("hanzi") if isinstance(properties, dict) else None
            if not isinstance(hanzi, str) or not hanzi:
                continue
            if hanzi.lower().startswith(normalized):
                out.append((hanzi, uid, "sentence"))

    if include_words:
        word_units = list_units_by_type_sqlite(vault_root, "word")
        if not word_units:
            word_units = list_units_by_type(vault_root, "word")
        for unit in word_units:
            if not isinstance(unit, dict):
                continue
            uid = unit.get("id")
            if not isinstance(uid, str) or not uid:
                continue
            properties = unit.get("properties")
            hanzi = properties.get("hanzi") if isinstance(properties, dict) else None
            if not isinstance(hanzi, str) or not hanzi:
                continue
            if hanzi.lower().startswith(normalized):
                out.append((hanzi, uid, "word"))

    if include_groups:
        group_units = list_units_by_type_sqlite(vault_root, "group")
        if not group_units:
            group_units = list_units_by_type(vault_root, "group")
        for unit in group_units:
            if not isinstance(unit, dict):
                continue
            uid = unit.get("id")
            if not isinstance(uid, str) or not uid:
                continue
            properties = unit.get("properties")
            display_name = ""
            if isinstance(properties, dict):
                raw_dn = properties.get("display_name")
                if isinstance(raw_dn, str):
                    display_name = raw_dn
            # Match against display_name first; fall back to the
            # slug id when display_name is empty so groups without
            # a human label still autocomplete against their id.
            match_target = display_name if display_name else uid
            if not match_target:
                continue
            if match_target.lower().startswith(normalized):
                out.append((display_name if display_name else uid, uid, "group"))

    # Sort alphabetically by name (lowercased so ASCII and CJK
    # scripts both compare stably). Tie-break by id, then type, so
    # the response order is fully deterministic across calls.
    out.sort(key=lambda entry: (entry[0].lower(), entry[1], entry[2]))

    trimmed = out[:limit_int]

    log.info(
        "suggest_units prefix=%r limit=%d types=%s hits=%d",
        prefix,
        limit_int,
        sorted(selected),
        len(trimmed),
    )

    return [
        {"id": uid, "type": unit_type, "name": name}
        for name, uid, unit_type in trimmed
    ]


# ---------------------------------------------------------------------------
# Meanings lookup (T27 — SPEC §5.3, §6 AC27c)
# ---------------------------------------------------------------------------


def meanings_search(
    vault_root: str,
    text: str,
    threshold: float | None = None,
    limit: int = 20,
    embedder: Embedder | None = None,
) -> list[dict]:
    """Return sentence units whose ``meaning`` embedding has cosine
    similarity to the query text > ``threshold``.

    Implements SPEC §5.3's
    ``GET /api/meanings/{text}/sentences`` endpoint and satisfies
    SPEC §6 AC27c. The user's English query is embedded in-memory
    and discarded; it is **not** persisted anywhere and the
    function does not log the query text at INFO level (DEBUG-level
    diagnostics are fine, but the production log stream must not
    receive user text).

    ``threshold`` is the cosine cutoff; the route layer supplies a
    default (see :func:`api.routes.search.meanings_sentences`).

    Each result is a dict ``{"id": str, "hanzi": str, "pinyin": str,
    "score": float}``. The Pydantic response model
    (:class:`api.schemas.MeaningSentenceItem`) carries no
    ``english`` or ``meaning`` fields, and FastAPI's serialization
    layer drops any field not declared on the model — so the
    service-layer dict must also be restricted to those four keys
    to keep the two layers in lockstep.

    Algorithm
    ---------
    1. Empty / non-string ``text`` → ``[]``. Whitespace-only text
       also returns ``[]``; the meaning embedding of whitespace
       is meaningless and would yield noise hits.
    2. Empty FAISS index → ``[]`` (mirrors :func:`semantic_search`).
    3. Embed the query text via the provided ``embedder`` (or
       :func:`api.services.embedder.get_embedder` if ``None``).
    4. Run a FAISS inner-product search and collect every hit
       whose cosine is **strictly greater** than ``threshold``.
       Hits at or below the threshold are dropped.
    5. For each surviving hit, look up the sentence unit on disk
       and project only ``id``, ``properties.hanzi``, and
       ``properties.pinyin``. Missing or malformed unit files
       are silently skipped (matches :func:`semantic_search`).
    6. Sort by descending cosine similarity and truncate to
       ``limit``.

    The FAISS index only contains sentence units (per SPEC §6
    AC9), so this endpoint is sentence-only — words and groups
    have no ``meaning`` embeddings.

    Privacy
    -------
    The query text is held only in this function's local
    ``text`` parameter and the embedded vector. Both are GC'd
    once the function returns. The INFO log line emitted on
    completion records only the response size, the threshold,
    and the limit — never the query text.

    Parameters
    ----------
    vault_root:
        Filesystem path to the vault root.
    text:
        The English meaning query (e.g. ``"a casual greeting"``).
        Empty or whitespace-only returns ``[]``.
    threshold:
        Cosine-similarity cutoff in ``[0.0, 1.0]`` (route clamps).
        Hits at or below this value are dropped. Supplied by the
        route layer (default 0.6 at ``GET /api/meanings``).
    limit:
        Maximum number of results to return. Route clamps to
        ``[1, 100]``. Default 20.
    embedder:
        Optional :class:`Embedder` for test injection. ``None``
        uses the process-wide embedder from
        :func:`api.services.embedder.get_embedder`.

    Returns
    -------
    list[dict]
        ``{"id", "hanzi", "pinyin", "score"}`` dicts sorted by
        descending cosine. Each dict has exactly those four keys
        — no ``english`` or ``meaning`` (AC20/AC27c). Empty list
        means: empty query, empty index, or all hits filtered by
        the threshold.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    if embedder is None:
        embedder = get_embedder()
    index = Index.load_or_empty(vault_root)
    if len(index) == 0:
        # We still log the "empty index" path at INFO without the
        # query text so operators can see when this cold path is
        # taken, but the log carries only the boolean state and
        # the response size (zero) — never the query itself.
        log.info(
            "meanings_search empty_index=1 threshold=%.4f limit=%d returned=0",
            float(threshold),
            int(limit),
        )
        return []
    query_vec = embedder.embed(text)
    # Discard the local references to the query text immediately
    # after embedding. The embedding vector itself is small and
    # GC'd when this function returns; FastAPI's response
    # serialization doesn't echo it.
    text = ""
    raw_hits = index.search(query_vec, k=limit)
    # v0.10: resolve FAISS hit unit_ids via SQLite (1 query) instead of
    # loading all sentence JSON files. Falls back to JSON path if SQLite
    # returns empty (database not migrated).
    hit_ids = [raw.unit_id for raw in raw_hits]
    sentences_by_id = get_units_by_ids_sqlite(vault_root, hit_ids)
    if not sentences_by_id:
        # Fallback: JSON path (database not migrated or units not in SQLite).
        sentences_by_id = {
            s["id"]: s for s in list_units_by_type(vault_root, "sentence")
        }
    out: list[dict] = []
    for raw in raw_hits:
        # Strict-greater filter matches the SPEC's "cosine > threshold"
        # wording (and matches :func:`semantic_search`'s behavior).
        if raw.score <= threshold:
            continue
        unit = sentences_by_id.get(raw.unit_id)
        if unit is None:
            continue
        properties = unit.get("properties")
        if not isinstance(properties, dict):
            continue
        raw_hanzi = properties.get("hanzi")
        raw_pinyin = properties.get("pinyin")
        # Even on a hit we never copy ``english`` or ``meaning``
        # into the result dict. Missing hanzi/pinyin default to
        # the empty string so a corrupt file can't crash the
        # response — the user sees the hit, just without text.
        hanzi = raw_hanzi if isinstance(raw_hanzi, str) else ""
        pinyin = raw_pinyin if isinstance(raw_pinyin, str) else ""
        out.append(
            {
                "id": raw.unit_id,
                "hanzi": hanzi,
                "pinyin": pinyin,
                "score": float(raw.score),
            }
        )
    # Sort descending by score. The FAISS result list is already
    # roughly descending but a few-percent reordering can happen
    # if the index is rebuilt between search calls — explicit sort
    # keeps the response deterministic.
    out.sort(key=lambda item: -item["score"])
    # INFO log records only the response size, threshold, and
    # limit — never the query text. This is a privacy requirement
    # (AC27c): the production log stream must not carry user
    # English text. DEBUG logging is acceptable for diagnostics
    # and is left to the route layer's discretion.
    log.info(
        "meanings_search threshold=%.4f limit=%d returned=%d",
        float(threshold),
        int(limit),
        len(out),
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


def merge_hits_with_kinds(
    *kinded_lists: tuple[str, list[SearchHit]],
) -> tuple[list[SearchHit], dict[tuple[str, str], set[str]]]:
    """Union of per-kind hit lists, tracking which kinds produced each key.

    T22 introduces the kinds toggle (SPEC §6 AC18). The route layer
    needs to know, for each surviving hit, *which* kinds produced at
    least one match for that key — so it can populate the response
    row's ``kinds`` list and so it can filter out keys whose only
    producing kind has been disabled by the caller.

    Each positional argument is a ``(kind_str, [SearchHit, ...])``
    tuple. ``kind_str`` is a short label identifying the producing
    pass — ``"lexical"``, ``"semantic"``, and (in T23+) ``"group"``
    and ``"opposite"``. The kind string is opaque to this function;
    it is recorded verbatim in the returned set.

    Behavior mirrors :func:`merge_hits` for the dedup-and-max-score
    half: the surviving :class:`SearchHit` for a key is the
    highest-scoring occurrence across all input lists, ties broken
    by first occurrence (left-to-right argument order).

    Parameters
    ----------
    *kinded_lists:
        Zero or more ``(kind, hits)`` tuples. Order matters only
        for tie-breaking on identical scores; otherwise output is
        sorted deterministically by ``(-score, unit_id, unit_type)``.

    Returns
    -------
    tuple[list[SearchHit], dict[tuple[str, str], set[str]]]
        ``(merged_hits, kinds_by_key)`` where ``merged_hits`` is
        the sorted, deduplicated union and ``kinds_by_key[key]``
        is the set of kind strings that produced at least one hit
        for ``key``. A key produced by both ``"lexical"`` and
        ``"semantic"`` lists appears once in ``merged_hits`` with
        ``kinds_by_key[key] == {"lexical", "semantic"}``. Empty
        input returns ``([], {})``.

    Notes
    -----
    The kinds map is not sorted here — sorting belongs to the
    caller (the route layer) when it shapes the JSON response.
    Keeping it as a set lets the route test set intersection
    against the ``kinds`` query parameter cheaply.
    """
    if not kinded_lists:
        return [], {}
    best_by_key: dict[tuple[str, str], SearchHit] = {}
    kinds_by_key: dict[tuple[str, str], set[str]] = {}
    for kind, hit_list in kinded_lists:
        if not hit_list:
            continue
        for hit in hit_list:
            key = (hit.unit_id, hit.unit_type)
            existing = best_by_key.get(key)
            if existing is None or hit.score > existing.score:
                best_by_key[key] = hit
            # Record that *this* kind produced a hit for this key,
            # regardless of which occurrence wins on score. A key
            # hit by both lexical and semantic must report both
            # kinds in the response, even if one of them scores
            # lower than the winner.
            bucket = kinds_by_key.get(key)
            if bucket is None:
                kinds_by_key[key] = {kind}
            else:
                bucket.add(kind)
    merged = sorted(
        best_by_key.values(),
        key=lambda h: (-h.score, h.unit_id, h.unit_type),
    )
    return merged, kinds_by_key


__all__ = [
    "SearchHit",
    "group_search",
    "has_english_or_meaning_key",
    "has_natural_language_english",
    "lexical_rank",
    "lexical_search",
    "meanings_search",
    "merge_hits",
    "merge_hits_with_kinds",
    "semantic_search",
    "suggest_units",
]
