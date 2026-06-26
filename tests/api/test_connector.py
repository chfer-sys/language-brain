"""Tests for :mod:`api.services.connector`.

Covers SPEC §6 AC12 (lexical sentence ↔ sentence connection kind,
T15) and AC13 (semantic sentence ↔ sentence connection kind, T16).
The connector's design is purely additive: future T17/T18 work
will add ``group`` and ``opposite`` kinds to the same
:func:`compute_connections` entry point. These tests focus on
the lexical and semantic kinds for now.

All tests use ``tmp_path`` for vault isolation; no test mutates the
real vault. Units are written through
:func:`api.services.unit_writer.write_unit` so the test fixtures
mirror how the production code path constructs units.

The default embedder used in every :func:`compute_connections` call
is :class:`HashingEmbedder` — deterministic, dependency-free, and
matching the embedder contract documented in
:mod:`api.services.embedder`. The real sentence-transformers model
is intentionally not exercised here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from api.services.connector import (
    _compute_sentence_lexical_edges,
    _compute_sentence_semantic_edges,
    compute_connections,
)
from api.services.embedder import HashingEmbedder
from api.services.unit_writer import read_unit, write_unit


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_sentence(
    *,
    unit_id: str,
    hanzi: str,
    meaning: str | None = None,
    connections: list | None = None,
) -> dict:
    """Build a minimal sentence-unit dict for fixture purposes.

    Mirrors the shape used by the rest of the codebase (see the
    SPEC §2 unit model). ``created`` / ``updated`` are pinned so
    tests can detect the ``updated`` refresh without depending on
    the wall clock.

    ``meaning``: if provided, written as ``properties.meaning``
    (the T16 / AC13 field). If ``None``, the field is omitted so
    the sentence is skipped by the semantic pass. Tests that
    exercise AC12 behavior unchanged should leave ``meaning``
    unset; tests that exercise AC13 should set it explicitly.
    """
    properties: dict[str, Any] = {"hanzi": hanzi}
    if meaning is not None:
        properties["meaning"] = meaning
    return {
        "id": unit_id,
        "type": "sentence",
        "name": hanzi,
        "properties": properties,
        "connections": list(connections) if connections is not None else [],
        "created": "2026-06-24",
        "updated": "2026-06-24",
        "author_confirmed": True,
    }


def _write_sentence(vault_root: str, unit: dict) -> None:
    """Write a sentence unit via the canonical writer."""
    write_unit(vault_root, unit)


def _lexical_edges(unit: dict) -> list[dict]:
    """Return only the ``lexical`` edges of a unit, in list order."""
    return [
        edge
        for edge in unit.get("connections", [])
        if isinstance(edge, dict) and edge.get("kind") == "lexical"
    ]


def _semantic_edges(unit: dict) -> list[dict]:
    """Return only the ``semantic`` edges of a unit, in list order."""
    return [
        edge
        for edge in unit.get("connections", [])
        if isinstance(edge, dict) and edge.get("kind") == "semantic"
    ]


def _edges_of_kind(unit: dict, kind: str) -> list[dict]:
    """Return only the edges of the given ``kind`` of a unit."""
    return [
        edge
        for edge in unit.get("connections", [])
        if isinstance(edge, dict) and edge.get("kind") == kind
    ]


def _seed_vault(vault_root: str, sentences: list[dict]) -> None:
    """Write a list of sentence units to the vault."""
    for unit in sentences:
        _write_sentence(vault_root, unit)


def _emb() -> HashingEmbedder:
    """Return a fresh :class:`HashingEmbedder` for test injection.

    Every test that calls :func:`compute_connections` should
    pass this explicitly so the test suite never depends on the
    real sentence-transformers model being downloadable. The
    hashing embedder is deterministic and gives cosine = 1.0
    for identical input strings, which is exactly the property
    most AC13 tests need.
    """
    return HashingEmbedder()


# ---------------------------------------------------------------------------
# Vault validation
# ---------------------------------------------------------------------------


def test_validate_vault_root_rejects_empty_string(tmp_path: Path) -> None:
    """An empty ``vault_root`` is rejected before any disk I/O."""
    with pytest.raises(ValueError):
        compute_connections("")


def test_validate_vault_root_rejects_missing_path(tmp_path: Path) -> None:
    """A non-existent ``vault_root`` raises ``FileNotFoundError``.

    We point at a path inside ``tmp_path`` that we deliberately
    never create. The error must be raised by the public entry
    point, not deferred to a deeper call.
    """
    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        compute_connections(str(missing))


# ---------------------------------------------------------------------------
# AC12 — summary and edge cases
# ---------------------------------------------------------------------------


def test_empty_vault_returns_zero_summary(tmp_path: Path) -> None:
    """A vault with no sentence units returns the zero summary.

    The vault directory exists (we just created an empty ``tmp_path``
    and added the ``units/`` tree via the writer on a previous call —
    here we explicitly do NOT seed anything) and yields zero pairs
    and zero touched units.

    To avoid the writer auto-creating a sentence subdir, we pass
    a vault that has a sentinel file but no ``units/sentences/``
    directory. ``list_units_by_type`` returns ``[]`` for a
    missing directory, which is exactly the empty-vault case.
    """
    vault_root = tmp_path / "empty_vault"
    vault_root.mkdir()
    # No units/ tree at all.

    summary = compute_connections(str(vault_root), embedder=_emb())

    assert summary["lexical_pairs"] == 0
    assert summary["sentences_touched"] == 0
    assert summary["skipped"] == 0
    assert summary["sentence_lexical_pairs_written"] == 0


def test_no_shared_tokens_writes_no_connections(tmp_path: Path) -> None:
    """Two sentences with disjoint hanzi produce zero connections.

    AC12 requires that a connection is written ONLY when two
    sentences share ≥1 hanzi token. Disjoint sets must therefore
    produce an empty connections list (modulo any pre-existing
    non-lexical edges).
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="S1", hanzi="我喜欢"),
            _make_sentence(unit_id="S2", hanzi="她走了"),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["lexical_pairs"] == 0
    assert summary["sentences_touched"] == 0
    # And the on-disk state confirms no lexical edge was written.
    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")
    assert _lexical_edges(s1) == []
    assert _lexical_edges(s2) == []


def test_shared_hanzi_writes_symmetric_lexical_edges(tmp_path: Path) -> None:
    """Two sentences sharing one char get symmetric edges on both.

    ``我喜欢吃`` (``{我, 喜, 欢, 吃}``) and ``你吃了吗``
    (``{你, 吃, 了, 吗}``) share ``吃``. Both sentences should
    gain a ``lexical`` edge pointing at the other, with the same
    Jaccard score on both sides.
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="S1", hanzi="我喜欢吃"),
            _make_sentence(unit_id="S2", hanzi="你吃了吗"),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["lexical_pairs"] == 1
    assert summary["sentences_touched"] == 2

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")

    lex1 = _lexical_edges(s1)
    lex2 = _lexical_edges(s2)

    assert len(lex1) == 1
    assert len(lex2) == 1

    assert lex1[0]["to"] == "S2"
    assert lex2[0]["to"] == "S1"
    assert lex1[0]["kind"] == "lexical"
    assert lex2[0]["kind"] == "lexical"

    # The score must be identical on both sides because Jaccard
    # is symmetric.
    assert lex1[0]["score"] == lex2[0]["score"]


def test_score_equals_jaccard_value(tmp_path: Path) -> None:
    """The stored score is exactly ``jaccard(tokens_a, tokens_b)``.

    ``ab`` → ``{a, b}``, ``bc`` → ``{b, c}``: intersection
    ``{b}`` (size 1), union ``{a, b, c}`` (size 3), Jaccard
    ``1/3``. We assert the literal floating-point value with
    ``pytest.approx`` to guard against rounding accidents.
    """
    from api.services.lexical import jaccard, tokenize_sentence

    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="A", hanzi="ab"),
            _make_sentence(unit_id="B", hanzi="bc"),
        ],
    )

    expected = jaccard(tokenize_sentence("ab"), tokenize_sentence("bc"))
    assert expected == pytest.approx(1 / 3)

    compute_connections(vault_root, embedder=_emb())

    a = read_unit(vault_root, "sentence", "A")
    b = read_unit(vault_root, "sentence", "B")

    lex_a = _lexical_edges(a)
    lex_b = _lexical_edges(b)
    assert len(lex_a) == 1
    assert len(lex_b) == 1
    assert lex_a[0]["score"] == pytest.approx(expected)
    assert lex_b[0]["score"] == pytest.approx(expected)
    assert lex_a[0]["score"] == pytest.approx(1 / 3)
    assert lex_b[0]["score"] == pytest.approx(1 / 3)


def test_three_sentences_pairwise(tmp_path: Path) -> None:
    """A-B share, B-C share, A-C disjoint → 2 pairs total.

    This exercises the multi-pair code path: the algorithm must
    enumerate every unordered pair, not stop at the first match.
    """
    vault_root = str(tmp_path)
    # A: {a, b}  B: {b, c}  C: {c, e}
    # Pairs:
    #   A-B share {b}            → edge
    #   A-C share {} (disjoint)  → no edge
    #   B-C share {c}            → edge
    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="A", hanzi="ab"),
            _make_sentence(unit_id="B", hanzi="bc"),
            _make_sentence(unit_id="C", hanzi="ce"),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["lexical_pairs"] == 2
    # A has 1 outgoing (to B); B has 2 outgoing (to A and C);
    # C has 1 outgoing (to B). All three are touched.
    assert summary["sentences_touched"] == 3

    a = read_unit(vault_root, "sentence", "A")
    b = read_unit(vault_root, "sentence", "B")
    c = read_unit(vault_root, "sentence", "C")

    a_targets = sorted(e["to"] for e in _lexical_edges(a))
    b_targets = sorted(e["to"] for e in _lexical_edges(b))
    c_targets = sorted(e["to"] for e in _lexical_edges(c))

    assert a_targets == ["B"]
    assert b_targets == ["A", "C"]
    assert c_targets == ["B"]


def test_idempotent_rerun(tmp_path: Path) -> None:
    """Running ``compute_connections`` twice does not duplicate edges.

    Re-running on a vault where the edges are already present must
    leave exactly one edge per direction per pair. The second
    summary's ``lexical_pairs`` count is still the number of
    UNORDERED pairs that share a token (i.e. 1 for this vault) —
    the same as the first run, because the count is over pairs,
    not over edges.
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="S1", hanzi="我喜欢吃"),
            _make_sentence(unit_id="S2", hanzi="你吃了吗"),
        ],
    )

    first = compute_connections(vault_root, embedder=_emb())
    second = compute_connections(vault_root, embedder=_emb())

    assert first["lexical_pairs"] == 1
    assert second["lexical_pairs"] == 1

    # Both directions still have exactly one lexical edge each.
    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")
    assert len(_lexical_edges(s1)) == 1
    assert len(_lexical_edges(s2)) == 1

    # And the on-disk file has only one edge per direction.
    s1_path = Path(vault_root) / "units" / "sentences" / "S1.json"
    with s1_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    lexical_raw = [
        e for e in raw["connections"] if isinstance(e, dict) and e.get("kind") == "lexical"
    ]
    assert len(lexical_raw) == 1


def test_score_updated_in_place_on_rerun(tmp_path: Path) -> None:
    """A stale score in an existing lexical edge is corrected and
    the edge stays at its original list position.

    We pre-seed S2 with a connection list containing a stale
    lexical edge to S1 at index 1 (with a wrong score of 0.99).
    After ``compute_connections``, the score must be the correct
    Jaccard, and the edge must still be at index 1 — not moved
    to the end of the list.
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="S1", hanzi="我喜欢吃"),
            _make_sentence(
                unit_id="S2",
                hanzi="你吃了吗",
                connections=[
                    # Pre-existing non-lexical edge at index 0.
                    {"to": "basic-verbs", "kind": "group", "score": 1.0},
                    # Stale lexical edge at index 1.
                    {"to": "S1", "kind": "lexical", "score": 0.99},
                ],
            ),
        ],
    )

    from api.services.lexical import jaccard, tokenize_sentence

    expected = jaccard(
        tokenize_sentence("我喜欢吃"), tokenize_sentence("你吃了吗")
    )
    # Sanity: the stale score and the correct score must differ,
    # otherwise this test is not actually exercising the update.
    assert expected != pytest.approx(0.99)

    compute_connections(vault_root, embedder=_emb())

    s2 = read_unit(vault_root, "sentence", "S2")
    connections = s2["connections"]

    # Index 0 is the pre-existing group edge — untouched.
    assert connections[0] == {
        "to": "basic-verbs",
        "kind": "group",
        "score": 1.0,
    }
    # Index 1 is the lexical edge — score corrected in place.
    assert connections[1] == {
        "to": "S1",
        "kind": "lexical",
        "score": pytest.approx(expected),
    }
    # And exactly one lexical edge exists (no duplicate appended).
    assert len(_lexical_edges(s2)) == 1


def test_self_loop_never_written(tmp_path: Path) -> None:
    """A sentence never gets a lexical edge pointing at itself,
    even if its token set contains a token equal to its own id.

    AC12 forbids self-loops. We construct a contrived sentence
    whose id is ``"x"`` and whose hanzi is ``"x"`` so the
    token set is ``["x"]`` and the id matches a token. The pair
    loop must skip the (a, a) case — which it does trivially
    because we only enumerate ``i < j``. This test guards
    against future refactors that loosen that invariant.
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="x", hanzi="x"),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["lexical_pairs"] == 0
    assert summary["sentences_touched"] == 0

    x = read_unit(vault_root, "sentence", "x")
    assert _lexical_edges(x) == []


def test_sentences_with_missing_hanzi_skipped(tmp_path: Path) -> None:
    """A sentence with missing/empty ``properties.hanzi`` is skipped.

    Two good sentences (S1, S2) share a token; S3 has empty
    hanzi. The pair involving S3 contributes nothing, and the
    pair (S1, S2) still produces a lexical edge. S3 itself
    is reported in ``skipped``.
    """
    vault_root = str(tmp_path)
    # S3: no properties at all → hanzi missing → skipped.
    bad = _make_sentence(unit_id="S3", hanzi="ignored")
    bad["properties"] = {}  # wipe hanzi
    # Also exercise the empty-hanzi case on a separate sentence.
    empty = _make_sentence(unit_id="S4", hanzi="")

    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="S1", hanzi="我喜欢吃"),
            _make_sentence(unit_id="S2", hanzi="你吃了吗"),
            bad,
            empty,
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["skipped"] == 2  # S3 (missing) + S4 (empty)
    assert summary["lexical_pairs"] == 1  # only S1↔S2

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")
    s3 = read_unit(vault_root, "sentence", "S3")
    s4 = read_unit(vault_root, "sentence", "S4")

    assert len(_lexical_edges(s1)) == 1
    assert _lexical_edges(s1)[0]["to"] == "S2"
    assert len(_lexical_edges(s2)) == 1
    assert _lexical_edges(s2)[0]["to"] == "S1"
    assert _lexical_edges(s3) == []
    assert _lexical_edges(s4) == []


def test_summary_sentences_touched_counts_unique_units(tmp_path: Path) -> None:
    """In a triangle of mutual sharing, every sentence is touched once.

    A-B-C all share at least one token: 3 unordered pairs, 3
    sentences each with 2 outgoing lexical edges. ``sentences_touched``
    counts UNIQUE units (not edges), so it must be 3.
    """
    vault_root = str(tmp_path)
    # A: {a, b}  B: {b, c}  C: {c, a} — fully connected triangle.
    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="A", hanzi="ab"),
            _make_sentence(unit_id="B", hanzi="bc"),
            _make_sentence(unit_id="C", hanzi="ca"),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["lexical_pairs"] == 3
    assert summary["sentences_touched"] == 3

    # Each sentence has exactly two lexical edges.
    for unit_id in ("A", "B", "C"):
        unit = read_unit(vault_root, "sentence", unit_id)
        assert len(_lexical_edges(unit)) == 2


# ---------------------------------------------------------------------------
# Pure-algorithm tests (_compute_sentence_lexical_edges)
# ---------------------------------------------------------------------------


def test_compute_sentence_lexical_edges_pure_no_io(tmp_path: Path) -> None:
    """The pure algorithm helper accepts an in-memory sentence list
    and returns edges without ever touching the vault.

    This guarantees the I/O layer can be tested separately and that
    future kinds (T16/T17) can plug in alongside this helper
    without re-reading the vault.
    """
    sentences = [
        _make_sentence(unit_id="A", hanzi="ab"),
        _make_sentence(unit_id="B", hanzi="bc"),
        _make_sentence(unit_id="C", hanzi="ce"),
    ]

    edges, pairs, skipped = _compute_sentence_lexical_edges(sentences)

    assert skipped == 0
    assert pairs == 2  # A-B share {b}, B-C share {c}; A-C disjoint
    assert sorted(edges["A"]) == [("B", pytest.approx(1 / 3))]
    assert sorted(edges["B"]) == [
        ("A", pytest.approx(1 / 3)),
        ("C", pytest.approx(1 / 3)),
    ]
    assert sorted(edges["C"]) == [("B", pytest.approx(1 / 3))]


def test_compute_sentence_lexical_edges_skips_missing_hanzi() -> None:
    """Sentences without usable hanzi are counted as skipped and
    contribute no edges."""
    sentences = [
        _make_sentence(unit_id="A", hanzi="ab"),
        {"id": "B", "type": "sentence", "properties": {}, "connections": []},
        {"id": "C", "type": "sentence", "properties": {"hanzi": ""}, "connections": []},
    ]

    edges, pairs, skipped = _compute_sentence_lexical_edges(sentences)

    # B (missing) and C (empty) both skipped.
    assert skipped == 2
    assert pairs == 0
    assert edges == {}


def test_compute_sentence_lexical_edges_id_without_id_is_skipped() -> None:
    """A unit dict that lacks a string ``id`` is skipped.

    Without an id we cannot name it as a source OR target of an
    edge, so it must be dropped from the algorithm.
    """
    sentences = [
        _make_sentence(unit_id="A", hanzi="ab"),
        # Missing id entirely.
        {"type": "sentence", "properties": {"hanzi": "ab"}, "connections": []},
    ]

    edges, pairs, skipped = _compute_sentence_lexical_edges(sentences)

    assert skipped == 1
    assert pairs == 0
    assert edges == {}


# ---------------------------------------------------------------------------
# AC13 — semantic edges (T16)
# ---------------------------------------------------------------------------
#
# These tests cover the ``semantic`` connection kind: symmetric edges
# between sentence units whose ``properties.meaning`` embeddings have
# cosine similarity strictly above the threshold. They mirror the AC12
# lexical tests in structure and use the deterministic
# :class:`HashingEmbedder` so two identical strings give cosine = 1.0
# (well above the default 0.6 threshold).
#
# Conventions:
# * Two identical meaning strings → cosine 1.0 → edge written.
# * Orthogonal stub vectors → cosine 0.0 → no edge at default threshold.
# * A pure helper ``_compute_sentence_semantic_edges`` is exercised
#   directly so its I/O-free behavior is locked in.


class _OrthogonalStubEmbedder:
    """Embedder stub that returns one of N orthogonal unit vectors.

    Each distinct input string gets its own unique unit vector in
    ``R^N`` (where ``N >= n_distinct``); the cosine between any
    two distinct inputs is exactly ``0.0``. Inputs beyond
    ``n_distinct`` cycle through the first vector (cosine 1.0
    with it).

    This is intentionally minimal — no dependency on the real
    embedder module — and lets the AC13 "below threshold" tests
    assert the no-edge branch deterministically.
    """

    def __init__(self, n_distinct: int = 16) -> None:
        # Build N orthogonal unit vectors: the i-th vector has 1.0
        # at index i and 0.0 elsewhere. Stored as float32 to
        # match the embedder contract.
        n = max(1, n_distinct)
        self._vecs: list[np.ndarray] = []
        for i in range(n):
            v = np.zeros(n, dtype=np.float32)
            v[i] = 1.0
            self._vecs.append(v)
        self._n_distinct = n
        self._seen: dict[str, int] = {}

    @property
    def dim(self) -> int:
        return self._n_distinct

    def embed(self, text: str) -> np.ndarray:
        if text not in self._seen:
            # Assign the next available orthogonal vector,
            # cycling if we run out.
            idx = min(len(self._seen), self._n_distinct - 1)
            self._seen[text] = idx
        return self._vecs[self._seen[text]]


def test_semantic_edges_written_for_high_cosine_pair(tmp_path: Path) -> None:
    """Two sentences with identical ``meaning`` get a ``semantic``
    edge on both sides with score ≈ 1.0 (AC13 happy path).

    Uses :class:`HashingEmbedder`, which is deterministic and gives
    identical (hence cosine-1.0) vectors for identical input strings.
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(
                unit_id="S1", hanzi="我喜欢", meaning="I like it"
            ),
            _make_sentence(
                unit_id="S2", hanzi="你吃了", meaning="I like it"
            ),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["semantic_pairs"] == 1
    assert summary["semantic_pairs_written"] == 1
    assert summary["sentences_touched"] == 2

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")

    sem1 = _semantic_edges(s1)
    sem2 = _semantic_edges(s2)

    assert len(sem1) == 1
    assert len(sem2) == 1
    assert sem1[0]["to"] == "S2"
    assert sem2[0]["to"] == "S1"
    assert sem1[0]["kind"] == "semantic"
    assert sem2[0]["kind"] == "semantic"
    # Identical strings under HashingEmbedder ⇒ cosine == 1.0 exactly.
    assert sem1[0]["score"] == pytest.approx(1.0)
    assert sem2[0]["score"] == pytest.approx(1.0)
    # The two sides must agree (cosine is symmetric).
    assert sem1[0]["score"] == sem2[0]["score"]


def test_semantic_edges_skipped_below_threshold(tmp_path: Path) -> None:
    """An orthogonal stub embedder yields cosine = 0.0 across
    distinct inputs, so no ``semantic`` edge is written at the
    default threshold of 0.6.

    The stub cycles through two orthogonal 2-D unit vectors, so
    distinct meanings → cosine 0.0 → strictly NOT greater than
    0.6 → no edge.
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="S1", hanzi="a", meaning="alpha"),
            _make_sentence(unit_id="S2", hanzi="b", meaning="beta"),
            _make_sentence(unit_id="S3", hanzi="c", meaning="gamma"),
        ],
    )

    stub = _OrthogonalStubEmbedder()
    summary = compute_connections(vault_root, embedder=stub)

    assert summary["semantic_pairs"] == 0
    assert summary["semantic_pairs_written"] == 0
    for unit_id in ("S1", "S2", "S3"):
        unit = read_unit(vault_root, "sentence", unit_id)
        assert _semantic_edges(unit) == []


def test_semantic_idempotent_rerun(tmp_path: Path) -> None:
    """Running ``compute_connections`` twice does not duplicate
    semantic edges (AC13 + SPEC §4 R7 idempotency).

    After two runs, each direction has exactly one ``semantic``
    edge per partner pair. The ``semantic_pairs`` counter is the
    number of unordered pairs that exceed the threshold (1 in this
    vault) — unchanged across runs because it counts pairs, not
    edge objects.
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(
                unit_id="S1", hanzi="我喜欢", meaning="I like it"
            ),
            _make_sentence(
                unit_id="S2", hanzi="你吃了", meaning="I like it"
            ),
        ],
    )

    first = compute_connections(vault_root, embedder=_emb())
    second = compute_connections(vault_root, embedder=_emb())

    assert first["semantic_pairs"] == 1
    assert second["semantic_pairs"] == 1

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")
    assert len(_semantic_edges(s1)) == 1
    assert len(_semantic_edges(s2)) == 1

    # And the on-disk file has only one edge per direction.
    s1_path = Path(vault_root) / "units" / "sentences" / "S1.json"
    with s1_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    semantic_raw = _edges_of_kind(raw, "semantic")
    assert len(semantic_raw) == 1


def test_semantic_skips_sentences_without_meaning(tmp_path: Path) -> None:
    """Sentences without a usable ``properties.meaning`` are
    skipped by the semantic pass; sentences with a meaning still
    form edges among themselves.

    Three sentences: ``S1`` and ``S2`` share a meaning (cosine 1.0
    → edge), ``S3`` has no meaning (skipped). The expected outcome
    is exactly one semantic pair, between ``S1`` and ``S2``.
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(
                unit_id="S1", hanzi="abc", meaning="hello world"
            ),
            _make_sentence(
                unit_id="S2", hanzi="def", meaning="hello world"
            ),
            _make_sentence(unit_id="S3", hanzi="ghi"),  # no meaning
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["semantic_pairs"] == 1
    assert summary["sentences_touched"] == 2  # S1 and S2
    # S3 is skipped by the summary because it contributed no
    # edge to either pass (no lexical pair, no semantic pair).
    assert summary["skipped"] == 1

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")
    s3 = read_unit(vault_root, "sentence", "S3")

    sem1 = _semantic_edges(s1)
    sem2 = _semantic_edges(s2)
    sem3 = _semantic_edges(s3)

    assert len(sem1) == 1 and sem1[0]["to"] == "S2"
    assert len(sem2) == 1 and sem2[0]["to"] == "S1"
    assert sem3 == []


def test_semantic_threshold_is_tunable(tmp_path: Path) -> None:
    """The ``semantic_threshold`` argument controls when an edge
    is written (AC13 "threshold tunable").

    With identical meanings (cosine = 1.0):
      * threshold = 0.99 (default-ish): 1.0 > 0.99 → edge written.
      * threshold = 1.01: 1.0 ≯ 1.01 → no edge.
    """
    vault_root_a = str(tmp_path / "vault_a")
    vault_root_b = str(tmp_path / "vault_b")

    # Vault A: threshold 0.99 → edge written.
    _seed_vault(
        vault_root_a,
        [
            _make_sentence(
                unit_id="S1", hanzi="abc", meaning="same text"
            ),
            _make_sentence(
                unit_id="S2", hanzi="def", meaning="same text"
            ),
        ],
    )
    summary_a = compute_connections(
        vault_root_a, embedder=_emb(), semantic_threshold=0.99
    )
    assert summary_a["semantic_pairs"] == 1
    assert len(_semantic_edges(read_unit(vault_root_a, "sentence", "S1"))) == 1

    # Vault B: threshold 1.01 → no edge.
    _seed_vault(
        vault_root_b,
        [
            _make_sentence(
                unit_id="S1", hanzi="abc", meaning="same text"
            ),
            _make_sentence(
                unit_id="S2", hanzi="def", meaning="same text"
            ),
        ],
    )
    summary_b = compute_connections(
        vault_root_b, embedder=_emb(), semantic_threshold=1.01
    )
    assert summary_b["semantic_pairs"] == 0
    assert _semantic_edges(read_unit(vault_root_b, "sentence", "S1")) == []
    assert _semantic_edges(read_unit(vault_root_b, "sentence", "S2")) == []


def test_lexical_and_semantic_coexist(tmp_path: Path) -> None:
    """Two sentences with shared hanzi AND identical meaning get
    BOTH a ``lexical`` and a ``semantic`` edge on each unit.

    This is the AC12+AC13 co-existence test: neither pass
    interferes with the other, and a unit's connections list can
    carry multiple kinds pointing at the same partner.
    """
    vault_root = str(tmp_path)
    # Shared hanzi token ``吃`` AND identical meaning.
    _seed_vault(
        vault_root,
        [
            _make_sentence(
                unit_id="S1", hanzi="我喜欢吃", meaning="I love to eat"
            ),
            _make_sentence(
                unit_id="S2", hanzi="你也吃吗", meaning="I love to eat"
            ),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["lexical_pairs"] == 1
    assert summary["semantic_pairs"] == 1

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")

    lex1 = _lexical_edges(s1)
    sem1 = _semantic_edges(s1)
    lex2 = _lexical_edges(s2)
    sem2 = _semantic_edges(s2)

    # Each unit carries exactly one lexical edge AND one semantic
    # edge to the other — two edges total, two different kinds.
    assert len(lex1) == 1 and lex1[0]["to"] == "S2"
    assert len(sem1) == 1 and sem1[0]["to"] == "S2"
    assert len(lex2) == 1 and lex2[0]["to"] == "S1"
    assert len(sem2) == 1 and sem2[0]["to"] == "S1"

    # Kinds are distinct on both sides.
    assert lex1[0]["kind"] == "lexical"
    assert sem1[0]["kind"] == "semantic"
    assert lex2[0]["kind"] == "lexical"
    assert sem2[0]["kind"] == "semantic"


def test_semantic_does_not_duplicate_other_kinds(tmp_path: Path) -> None:
    """Re-running ``compute_connections`` preserves exactly one
    ``lexical`` AND exactly one ``semantic`` edge per partner
    pair on each unit. The two kinds coexist without stomping
    on each other.
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(
                unit_id="S1", hanzi="我喜欢吃", meaning="I love to eat"
            ),
            _make_sentence(
                unit_id="S2", hanzi="你也吃吗", meaning="I love to eat"
            ),
        ],
    )

    compute_connections(vault_root, embedder=_emb())
    compute_connections(vault_root, embedder=_emb())

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")

    # Two edges per unit: one lexical, one semantic.
    all_edges = s1["connections"]
    kinds = sorted(e["kind"] for e in all_edges if isinstance(e, dict))
    assert kinds == ["lexical", "semantic"]
    # No duplicate partners within a single kind.
    lex = _lexical_edges(s1)
    sem = _semantic_edges(s1)
    assert len(lex) == 1
    assert len(sem) == 1
    assert lex[0]["to"] == "S2"
    assert sem[0]["to"] == "S2"

    # Mirror on S2.
    all_edges_s2 = s2["connections"]
    kinds_s2 = sorted(e["kind"] for e in all_edges_s2 if isinstance(e, dict))
    assert kinds_s2 == ["lexical", "semantic"]


def test_semantic_pairs_summary_zero_when_no_meaning(tmp_path: Path) -> None:
    """A vault whose sentences all lack ``meaning`` produces
    zero semantic pairs and accounts for all units as ``skipped``.

    This guards against the summary silently under-counting when
    an entire vault is semantic-inert (e.g. legacy data before
    T16 was deployed).
    """
    vault_root = str(tmp_path)
    _seed_vault(
        vault_root,
        [
            _make_sentence(unit_id="S1", hanzi="我喜欢"),
            _make_sentence(unit_id="S2", hanzi="你吃了"),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["semantic_pairs"] == 0
    assert summary["semantic_pairs_written"] == 0
    # Both units contribute no semantic edge; they're skipped
    # because they contributed no edge to either pass.
    assert summary["skipped"] == 2


def test_semantic_threshold_validation() -> None:
    """``compute_connections`` rejects a non-numeric
    ``semantic_threshold`` before doing any I/O.

    The check runs against an empty vault path so we never need
    disk state; ``ValueError`` is raised before the embedder is
    resolved.
    """
    with pytest.raises(ValueError):
        compute_connections(
            "/tmp/__does_not_matter__", embedder=_emb(),
            semantic_threshold="not a number",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Pure-algorithm tests for the semantic pass
# ---------------------------------------------------------------------------


def test_compute_sentence_semantic_edges_pure_no_io() -> None:
    """The pure semantic helper returns edges from an in-memory
    sentence list without touching the vault.

    Three sentences with distinct meanings (all orthogonal vectors
    under the stub, cosine 0.0 across pairs) produce zero edges —
    this locks in the algorithm's "below threshold" branch in the
    pure layer, separate from the I/O layer.
    """
    sentences = [
        _make_sentence(unit_id="A", hanzi="ab", meaning="alpha"),
        _make_sentence(unit_id="B", hanzi="bc", meaning="beta"),
        _make_sentence(unit_id="C", hanzi="cd", meaning="gamma"),
    ]

    # Use the orthogonal stub so the cosine between distinct
    # inputs is exactly 0.0 — deterministic across machines and
    # HashingEmbedder's hashed vectors (which would give some
    # unpredictable cosine for the "goodbye" pair).
    stub = _OrthogonalStubEmbedder(n_distinct=3)
    edges, pairs, skipped = _compute_sentence_semantic_edges(
        sentences, embedder=stub
    )

    assert skipped == 0
    assert pairs == 0  # no pair has cosine > 0.6
    assert edges == {}


def test_compute_sentence_semantic_edges_skips_missing_meaning() -> None:
    """Sentences without a usable ``meaning`` are skipped by the
    semantic pass and contribute no edges."""
    sentences = [
        _make_sentence(unit_id="A", hanzi="ab", meaning="hello"),
        # properties dict is empty: no meaning field at all.
        {"id": "B", "type": "sentence", "properties": {}, "connections": []},
        # Meaning explicitly empty string.
        _make_sentence(unit_id="C", hanzi="cd", meaning=""),
    ]

    edges, pairs, skipped = _compute_sentence_semantic_edges(
        sentences, embedder=_emb()
    )

    assert skipped == 2  # B and C
    assert pairs == 0
    assert edges == {}


def test_compute_sentence_semantic_edges_respects_threshold() -> None:
    """Edges are written only when cosine is strictly greater
    than the threshold (AC13)."""
    sentences = [
        _make_sentence(unit_id="A", hanzi="ab", meaning="hello"),
        _make_sentence(unit_id="B", hanzi="bc", meaning="hello"),
    ]

    # Threshold at or above 1.0 suppresses the edge.
    edges_high, pairs_high, _ = _compute_sentence_semantic_edges(
        sentences, embedder=_emb(), threshold=1.0
    )
    assert pairs_high == 0
    assert edges_high == {}

    # Threshold strictly below 1.0 keeps it.
    edges_low, pairs_low, _ = _compute_sentence_semantic_edges(
        sentences, embedder=_emb(), threshold=0.99
    )
    assert pairs_low == 1
    assert edges_low["A"] == [("B", pytest.approx(1.0))]