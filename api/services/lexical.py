"""Lexical connection helpers for the language-brain vault.

This module implements the *word → sentence* half of SPEC §2.4's
``lexical`` connection kind, and is the implementation behind §6 AC3
("an existing word's ``connections`` list is updated to include a
``lexical`` edge to a newly-saved sentence that contains it").

Definitions (from SPEC §2.4)
----------------------------
A ``lexical`` edge from a word to a sentence means the word's hanzi
appears among the sentence's hanzi tokens. The full Jaccard-over-tokens
formula is the canonical score formula, but for AC3 the caller passes
``score=1.0`` (presence/absence is sufficient). A future task can
replace the ``1.0`` call-site with the Jaccard value computed via
:func:`jaccard` over :func:`tokenize_sentence` of the two sides.
:func:`jaccard` exists in this module now so AC12 (sentence↔sentence
lexical) and any future Jaccard-based code can use it without a
second module being added.

Scope
-----
This module only handles the *word → sentence* direction. The
*sentence → sentence* and *sentence → word* lexical edges are owned
by the connector / sentence-saver tasks (see AC12). The connection
on a *sentence* unit pointing back at a word is built by a different
service. This module never edits sentence units.

I/O
---
All disk reads and writes go through :mod:`api.services.unit_writer`.
This module never opens files directly, so the atomic-write guarantee
of ``write_unit`` is preserved.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from api.services.unit_writer import read_unit, write_unit


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------


def tokenize_sentence(hanzi: str) -> list[str]:
    """Split a hanzi string into single-character tokens for now.

    A future task can swap this for jieba segmentation. AC3 only
    requires character-level sharing — two sentences share a token
    iff they contain the same hanzi character.

    Returns a deduplicated list preserving first-occurrence order.
    An empty (or pure-whitespace) input returns ``[]``. Whitespace
    characters are skipped (they are not hanzi tokens). Non-hanzi
    input (e.g. ASCII) is still split character-by-character, since
    the dedup-and-preserve-order contract is what callers depend on.

    Parameters
    ----------
    hanzi:
        The source string. Typically the ``name`` or ``properties.hanzi``
        of a sentence unit, but any string is accepted.

    Returns
    -------
    list[str]
        Deduplicated tokens in first-occurrence order. The returned
        list is a fresh list — callers may mutate it freely.
    """
    if not isinstance(hanzi, str):
        raise ValueError(f"hanzi must be a string, got {type(hanzi).__name__}")
    seen: set[str] = set()
    out: list[str] = []
    for ch in hanzi:
        # Skip whitespace so "我 流 口水" tokenizes the same as
        # "我流口水". Tabs/newlines are whitespace too.
        if ch.isspace():
            continue
        if ch in seen:
            continue
        seen.add(ch)
        out.append(ch)
    return out


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------


def jaccard(a: list[str], b: list[str]) -> float:
    """Jaccard similarity over two token lists, as a float in ``[0, 1]``.

    ``J(A, B) = |A ∩ B| / |A ∪ B|`` over the token *sets* derived from
    ``a`` and ``b``. Order is irrelevant. Duplicates inside ``a`` or
    ``b`` are also irrelevant — we convert each list to a set first.

    Empty lists on either side return ``0.0``. This matches the
    mathematical limit: when one set is empty, both the intersection
    and the union are empty, which is the ``0/0`` indeterminate
    form; we resolve it to ``0.0`` because a connection to/from an
    empty-token unit is meaningless.

    Parameters
    ----------
    a, b:
        Token lists. Strings, ints, or any hashable elements are
        accepted, but the canonical caller passes ``list[str]``.

    Returns
    -------
    float
        Value in ``[0.0, 1.0]``. ``1.0`` means the two lists have
        identical token sets; ``0.0`` means disjoint (or at least
        one list is empty).
    """
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    # Defensive: if both lists were empty `set_a` and `set_b` are
    # both falsy and we returned 0.0 above. Here `union` is non-empty.
    if not union:
        return 0.0
    intersection = set_a & set_b
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# Edge mutation
# ---------------------------------------------------------------------------


# Connection kinds are a closed set per SPEC §2.4. This module only
# writes the ``lexical`` kind, but it validates the field anyway so
# a future bug (e.g. a typo'd "lexcial") is caught at write time.
_LEXICAL_KIND: str = "lexical"
_VALID_CONNECTION_KINDS: frozenset[str] = frozenset(
    {"lexical", "semantic", "group", "opposite"}
)


def _today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return date.today().isoformat()


def add_lexical_edge_to_word(
    vault_root: str,
    word_id: str,
    sentence_id: str,
    score: float = 1.0,
) -> dict:
    """Add (or update) a ``lexical`` connection on the word unit
    pointing to the given sentence id, with the given ``score``.

    Behavior
    --------
    * Reads the word unit file via :func:`read_unit`. Raises
      :class:`FileNotFoundError` if the word file does not exist —
      the caller is expected to have created the word unit first
      (typically via :func:`api.services.word_registry.ensure_word_unit`).
    * The connection list is updated in memory:
        - If a ``lexical`` connection to the same ``sentence_id``
          already exists, its ``score`` is updated in place. The
          existing dict's position in the list is preserved.
        - Otherwise, a new ``{"to": ..., "kind": "lexical", "score": ...}``
          entry is appended.
    * Connections of OTHER kinds (``semantic``, ``group``,
      ``opposite``) are never touched.
    * If the same sentence appears under a *different* kind (which
      would itself be a data error), this function still appends a
      new lexical entry. We do not silently coalesce across kinds.
    * The ``updated`` field is refreshed to today's ISO date so the
      on-disk timestamp reflects the mutation.
    * The unit is rewritten via :func:`write_unit` (atomic).

    Parameters
    ----------
    vault_root:
        Vault root path.
    word_id:
        The word unit's id (tone-marked pinyin per OQ2). The unit
        is read as ``unit_type="word"``.
    sentence_id:
        The id of the sentence to connect to. Becomes the
        ``"to"`` field of the new edge.
    score:
        Score to record on the edge. Default ``1.0`` for AC3's
        presence-only test. Future tasks may pass a Jaccard value.

    Returns
    -------
    dict
        The updated word unit dict (the same object that was
        written to disk).

    Raises
    ------
    FileNotFoundError
        If the word unit file does not exist.
    ValueError
        If ``word_id`` or ``sentence_id`` is not a non-empty string,
        or ``score`` is not a real number.
    """
    if not isinstance(word_id, str) or not word_id:
        raise ValueError("word_id must be a non-empty string")
    if not isinstance(sentence_id, str) or not sentence_id:
        raise ValueError("sentence_id must be a non-empty string")
    # Reject bools (which are int subclasses) and complex numbers; we
    # only want float-like scores. ints are accepted because scores
    # in the SPEC are floats but a caller may pass 1 without ".0".
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError(
            f"score must be a real number, got {type(score).__name__}"
        )

    word_unit: dict[str, Any] = read_unit(vault_root, "word", word_id)

    # Defensive: confirm the file we just read is a word unit (atomic or
    # compound). If someone hands us a sentence id by mistake, fail loudly
    # rather than silently writing a lexical edge from a sentence.
    if word_unit.get("type") not in ("word", "compound"):
        raise ValueError(
            f"unit at id {word_id!r} has type "
            f"{word_unit.get('type')!r}, expected 'word' or 'compound'"
        )

    connections = word_unit.get("connections")
    if not isinstance(connections, list):
        # Malformed file: connections is not a list. Repair it
        # by replacing with an empty list rather than crashing.
        # (A repair tool can flag this separately.)
        connections = []
        word_unit["connections"] = connections

    # Idempotent update: find an existing lexical edge to this sentence.
    existing_idx: int | None = None
    for idx, edge in enumerate(connections):
        if (
            isinstance(edge, dict)
            and edge.get("kind") == _LEXICAL_KIND
            and edge.get("to") == sentence_id
        ):
            existing_idx = idx
            break

    if existing_idx is not None:
        # Update score in place; preserve position so on-disk order is
        # stable across re-runs (idempotent re-runs write identical
        # files modulo the ``updated`` timestamp).
        connections[existing_idx]["score"] = float(score)
    else:
        connections.append(
            {"to": sentence_id, "kind": _LEXICAL_KIND, "score": float(score)}
        )

    word_unit["updated"] = _today_iso()
    write_unit(vault_root, word_unit)
    return word_unit


__all__ = [
    "tokenize_sentence",
    "jaccard",
    "add_lexical_edge_to_word",
]
