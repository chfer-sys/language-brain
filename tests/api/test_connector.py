"""Tests for :mod:`api.services.connector`.

Covers SPEC §6 AC12 (lexical sentence ↔ sentence connection kind,
T15), AC13 (semantic sentence ↔ sentence connection kind, T16),
and AC14 (group sentence ↔ sentence connection kind, T17). The
connector's design is purely additive: future T18 work will add
the ``opposite`` kind to the same :func:`compute_connections`
entry point. These tests focus on the lexical, semantic, and
group kinds.

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
    _compute_sentence_group_edges,
    _compute_word_opposite_edges,
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


def _group_edges(unit: dict) -> list[dict]:
    """Return only the ``group`` edges of a unit, in list order."""
    return [
        edge
        for edge in unit.get("connections", [])
        if isinstance(edge, dict) and edge.get("kind") == "group"
    ]


def _seed_vault(vault_root: str, sentences: list[dict]) -> None:
    """Write a list of sentence units to the vault."""
    for unit in sentences:
        _write_sentence(vault_root, unit)


def _make_group(
    group_id: str,
    member_ids: list[str],
) -> dict:
    """Build a minimal group-unit dict for fixture purposes.

    Mirrors the shape produced by
    :func:`api.services.group_registry.ensure_group_unit` so the
    connector sees the same on-disk shape it would see in
    production. ``display_name`` and ``description`` default to
    the empty string (the registry's default behavior). ``members``
    is copied so the caller can mutate the original list without
    affecting the fixture.
    """
    return {
        "id": group_id,
        "type": "group",
        "name": group_id,
        "properties": {
            "display_name": "",
            "description": "",
            "members": list(member_ids),
        },
        "connections": [],
        "created": "2026-06-24",
        "updated": "2026-06-24",
        "author_confirmed": True,
    }


def _seed_vault_with_groups(
    vault_root: str,
    sentences: list[dict],
    groups: list[dict],
) -> None:
    """Write a list of sentence units AND a list of group units
    to the vault.

    Both lists are written through :func:`write_unit` so the
    fixtures mirror how production code populates the vault.
    Order of writes does not matter for the connector — the
    algorithm layer reads both lists independently.
    """
    for unit in sentences:
        _write_sentence(vault_root, unit)
    for group in groups:
        write_unit(vault_root, group)


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


# ---------------------------------------------------------------------------
# AC14 — group edges (T17)
# ---------------------------------------------------------------------------
#
# These tests cover the ``group`` connection kind: symmetric edges
# between sentence units that share membership in at least one
# group. They mirror the AC12 / AC13 tests in structure but use
# group units as the membership source.
#
# Conventions:
# * Each pair of sentences that share a group yields exactly ONE
#   ``group`` edge on each side, with score 1.0.
# * Multiple shared groups between the same pair collapse to a
#   single edge (deduplicated by ``(to, kind)`` like other kinds).
# * Sentences with no group membership contribute no edges.
# * Group units are NEVER targets of ``group`` edges from member
#   sentences.


def test_group_edge_written_for_shared_membership(tmp_path: Path) -> None:
    """Two sentences both in group ``basic-verbs`` each get a
    ``group`` edge pointing at the other with score 1.0.

    AC14 happy path: shared membership ⇒ ``group`` edge, both
    directions, score fixed at 1.0. ``group_pairs`` is 1.
    """
    vault_root = str(tmp_path)
    _seed_vault_with_groups(
        vault_root,
        sentences=[
            _make_sentence(unit_id="S1", hanzi="我喜欢"),
            _make_sentence(unit_id="S2", hanzi="你走了"),
        ],
        groups=[
            _make_group("basic-verbs", ["S1", "S2"]),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["group_pairs"] == 1
    assert summary["group_pairs_written"] == 1

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")

    g1 = _group_edges(s1)
    g2 = _group_edges(s2)

    assert len(g1) == 1
    assert len(g2) == 1
    assert g1[0]["to"] == "S2"
    assert g2[0]["to"] == "S1"
    assert g1[0]["kind"] == "group"
    assert g2[0]["kind"] == "group"
    assert g1[0]["score"] == pytest.approx(1.0)
    assert g2[0]["score"] == pytest.approx(1.0)


def test_no_group_edge_without_shared_membership(tmp_path: Path) -> None:
    """Sentences in DIFFERENT groups (and a sentence with no group
    membership at all) get zero ``group`` edges.

    AC14: edges are written only when two sentences SHARE a group.
    Disjoint group membership — or no membership at all — must
    produce no ``group`` edges. ``group_pairs`` is 0.
    """
    vault_root = str(tmp_path)
    _seed_vault_with_groups(
        vault_root,
        sentences=[
            _make_sentence(unit_id="S1", hanzi="a"),  # in group A
            _make_sentence(unit_id="S2", hanzi="b"),  # in group B
            _make_sentence(unit_id="S3", hanzi="c"),  # no group at all
        ],
        groups=[
            _make_group("group-a", ["S1"]),
            _make_group("group-b", ["S2"]),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["group_pairs"] == 0
    assert summary["group_pairs_written"] == 0

    for unit_id in ("S1", "S2", "S3"):
        unit = read_unit(vault_root, "sentence", unit_id)
        assert _group_edges(unit) == []


def test_group_edge_symmetric_and_idempotent(tmp_path: Path) -> None:
    """Two sentences sharing one group, run twice: each side has
    exactly one ``group`` edge per direction (idempotent upsert).

    AC14 symmetry + idempotency. After TWO runs of
    ``compute_connections``, neither sentence has duplicate
    ``group`` edges. The summary's ``group_pairs`` count is 1
    both times (the count is over pairs, not over edges).
    """
    vault_root = str(tmp_path)
    _seed_vault_with_groups(
        vault_root,
        sentences=[
            _make_sentence(unit_id="S1", hanzi="ab"),
            _make_sentence(unit_id="S2", hanzi="cd"),
        ],
        groups=[
            _make_group("shared-group", ["S1", "S2"]),
        ],
    )

    first = compute_connections(vault_root, embedder=_emb())
    second = compute_connections(vault_root, embedder=_emb())

    assert first["group_pairs"] == 1
    assert second["group_pairs"] == 1

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")

    # Exactly one group edge per direction — the second run's
    # upsert updated the score in place rather than appending.
    g1 = _group_edges(s1)
    g2 = _group_edges(s2)
    assert len(g1) == 1
    assert len(g2) == 1
    assert g1[0]["to"] == "S2"
    assert g2[0]["to"] == "S1"
    assert g1[0]["score"] == pytest.approx(1.0)
    assert g2[0]["score"] == pytest.approx(1.0)

    # And the on-disk JSON has only one ``group`` edge per unit.
    s1_path = Path(vault_root) / "units" / "sentences" / "S1.json"
    with s1_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    assert len(_edges_of_kind(raw, "group")) == 1


def test_group_edge_multiple_shared_groups(tmp_path: Path) -> None:
    """Two sentences sharing THREE groups still get exactly ONE
    ``group`` edge to each other (deduplicated by ``(to, kind)``).

    The ``(to, kind)`` upsert contract guarantees that a second
    pass through ``_compute_sentence_group_edges`` for the same
    pair produces no new edge object — the existing one is
    updated in place. Score remains exactly 1.0 (group edges do
    not accumulate scores across shared groups; the relation is
    binary).
    """
    vault_root = str(tmp_path)
    _seed_vault_with_groups(
        vault_root,
        sentences=[
            _make_sentence(unit_id="S1", hanzi="x"),
            _make_sentence(unit_id="S2", hanzi="y"),
        ],
        groups=[
            _make_group("g1", ["S1", "S2"]),
            _make_group("g2", ["S1", "S2"]),
            _make_group("g3", ["S1", "S2"]),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    # Three groups, but the pair (S1, S2) is still ONE unordered
    # pair — ``group_pairs`` counts pairs, not shared groups.
    assert summary["group_pairs"] == 1

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")

    g1 = _group_edges(s1)
    g2 = _group_edges(s2)
    assert len(g1) == 1
    assert len(g2) == 1
    assert g1[0]["to"] == "S2"
    assert g2[0]["to"] == "S1"
    assert g1[0]["score"] == pytest.approx(1.0)
    assert g2[0]["score"] == pytest.approx(1.0)


def test_group_edge_skips_sentences_with_no_group_membership(
    tmp_path: Path,
) -> None:
    """A sentence with no group membership contributes no ``group``
    edges, even when other sentences in the vault DO share a group.

    AC14: "A unit that has no group memberships at all contributes
    no edges." We seed S1 + S2 in the same group and S3 in no
    group at all; S3 must end up with an empty ``group``-edges
    list after ``compute_connections``.
    """
    vault_root = str(tmp_path)
    _seed_vault_with_groups(
        vault_root,
        sentences=[
            _make_sentence(unit_id="S1", hanzi="a"),
            _make_sentence(unit_id="S2", hanzi="b"),
            _make_sentence(unit_id="S3", hanzi="c"),  # no membership
        ],
        groups=[
            _make_group("g-only-s1s2", ["S1", "S2"]),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["group_pairs"] == 1

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")
    s3 = read_unit(vault_root, "sentence", "S3")

    # S1 ↔ S2 share a group → each gets a ``group`` edge to the
    # other.
    g1 = _group_edges(s1)
    g2 = _group_edges(s2)
    assert len(g1) == 1 and g1[0]["to"] == "S2"
    assert len(g2) == 1 and g2[0]["to"] == "S1"

    # S3 is in no group → it must have ZERO ``group`` edges,
    # even though it is a sentence unit.
    assert _group_edges(s3) == []


def test_group_edge_score_is_one(tmp_path: Path) -> None:
    """The stored score on a shared-membership edge is exactly 1.0.

    AC14: "score = 1.0" — a literal, not a generic positive value.
    This test asserts equality with the exact float ``1.0`` (via
    ``pytest.approx`` for float-typed comparison safety) rather
    than just ``> 0`` so a future regression to "0.5" or "some
    similarity-derived value" is caught.
    """
    vault_root = str(tmp_path)
    _seed_vault_with_groups(
        vault_root,
        sentences=[
            _make_sentence(unit_id="S1", hanzi="aa"),
            _make_sentence(unit_id="S2", hanzi="bb"),
        ],
        groups=[
            _make_group("g", ["S1", "S2"]),
        ],
    )

    compute_connections(vault_root, embedder=_emb())

    s1 = read_unit(vault_root, "sentence", "S1")
    g1 = _group_edges(s1)
    assert len(g1) == 1
    assert g1[0]["score"] == pytest.approx(1.0)
    # Belt and suspenders: not just > 0 — exactly 1.0.
    assert g1[0]["score"] == 1.0


def test_group_does_not_affect_lexical_or_semantic(tmp_path: Path) -> None:
    """A shared-group pair that ALSO shares hanzi and meaning gets
    three DISTINCT edges on each unit: ``lexical``, ``semantic``,
    ``group``.

    The kinds coexist without stomping on each other. None of the
    summary counts change unexpectedly — ``lexical_pairs`` and
    ``semantic_pairs`` match what they would be on the same vault
    with no groups at all (1 each), and ``group_pairs`` is 1
    from the new pass. This is the AC12 + AC13 + AC14 coexistence
    test.
    """
    vault_root = str(tmp_path)
    # S1 and S2 share a hanzi token (``吃``) AND identical
    # meaning AND are both in the same group. After
    # compute_connections, each side must have THREE distinct
    # edges pointing at the other, one per kind.
    _seed_vault_with_groups(
        vault_root,
        sentences=[
            _make_sentence(
                unit_id="S1", hanzi="我喜欢吃", meaning="I love to eat"
            ),
            _make_sentence(
                unit_id="S2", hanzi="你也吃吗", meaning="I love to eat"
            ),
        ],
        groups=[
            _make_group("eating-group", ["S1", "S2"]),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    # Lexical and semantic counts are unaffected by the group
    # pass — they read the same sentence input and arrive at
    # the same pairwise scores.
    assert summary["lexical_pairs"] == 1
    assert summary["semantic_pairs"] == 1
    # Group pass adds exactly one unordered pair.
    assert summary["group_pairs"] == 1

    s1 = read_unit(vault_root, "sentence", "S1")
    s2 = read_unit(vault_root, "sentence", "S2")

    # Each unit has exactly one edge of each kind pointing at
    # the other. Total connections per unit: 3.
    kinds_s1 = sorted(
        e["kind"] for e in s1["connections"] if isinstance(e, dict)
    )
    kinds_s2 = sorted(
        e["kind"] for e in s2["connections"] if isinstance(e, dict)
    )
    assert kinds_s1 == ["group", "lexical", "semantic"]
    assert kinds_s2 == ["group", "lexical", "semantic"]

    # And within each kind, the partner is the other unit.
    for edge in _group_edges(s1):
        assert edge["to"] == "S2"
    for edge in _group_edges(s2):
        assert edge["to"] == "S1"


def test_group_pairs_summary_includes_alias(tmp_path: Path) -> None:
    """``summary["group_pairs"]`` and ``summary["group_pairs_written"]``
    agree — the alias is kept for consistency with the
    ``sentence_lexical_pairs_written`` / ``semantic_pairs_written``
    aliases already in the summary.

    This guards against a future refactor accidentally renaming
    one of the two keys without updating the other.
    """
    vault_root = str(tmp_path)
    _seed_vault_with_groups(
        vault_root,
        sentences=[
            _make_sentence(unit_id="S1", hanzi="a"),
            _make_sentence(unit_id="S2", hanzi="b"),
        ],
        groups=[
            _make_group("g", ["S1", "S2"]),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert "group_pairs" in summary
    assert "group_pairs_written" in summary
    assert summary["group_pairs"] == summary["group_pairs_written"] == 1


# ---------------------------------------------------------------------------
# Pure-algorithm tests for the group pass (T17)
# ---------------------------------------------------------------------------


def test_compute_sentence_group_edges_pure_no_io() -> None:
    """The pure group helper accepts in-memory sentence and group
    lists and returns edges without touching the vault.

    Two sentences are both in ``g1``; a third sentence is in
    ``g2`` alone. Expected outcome: one pair (S1, S2) with a
    shared group ⇒ one edge each direction, score 1.0. S3 is
    skipped (no shared group with anyone). ``group_pairs`` is 1.
    """
    sentences = [
        _make_sentence(unit_id="S1", hanzi="ab"),
        _make_sentence(unit_id="S2", hanzi="cd"),
        _make_sentence(unit_id="S3", hanzi="ef"),
    ]
    groups = [
        _make_group("g1", ["S1", "S2"]),
        _make_group("g2", ["S3"]),
    ]

    edges, pairs, skipped = _compute_sentence_group_edges(
        sentences, groups
    )

    assert skipped == 0
    assert pairs == 1
    assert edges.get("S1") == [("S2", pytest.approx(1.0))]
    assert edges.get("S2") == [("S1", pytest.approx(1.0))]
    # S3 has no shared group with S1 or S2 → no entry at all.
    assert "S3" not in edges


def test_compute_sentence_group_edges_deduplicates_multiple_groups() -> None:
    """Multiple shared groups between the same pair collapse to
    ONE edge per side (the ``(to, kind)`` upsert contract is the
    I/O layer's responsibility; the algorithm layer writes one
    edge per unordered pair regardless of how many groups they
    share).
    """
    sentences = [
        _make_sentence(unit_id="A", hanzi="a"),
        _make_sentence(unit_id="B", hanzi="b"),
    ]
    groups = [
        _make_group("g1", ["A", "B"]),
        _make_group("g2", ["A", "B"]),
        _make_group("g3", ["A", "B"]),
    ]

    edges, pairs, skipped = _compute_sentence_group_edges(
        sentences, groups
    )

    assert pairs == 1  # one unordered pair
    assert skipped == 0
    # Exactly one edge each direction, not three.
    assert edges["A"] == [("B", pytest.approx(1.0))]
    assert edges["B"] == [("A", pytest.approx(1.0))]


def test_compute_sentence_group_edges_skips_ungrouped_sentences() -> None:
    """A sentence with no group membership is not a key in the
    returned edge map and contributes no edges."""
    sentences = [
        _make_sentence(unit_id="S1", hanzi="a"),
        _make_sentence(unit_id="S2", hanzi="b"),
        _make_sentence(unit_id="S3", hanzi="c"),  # no membership
    ]
    groups = [
        _make_group("only-s1s2", ["S1", "S2"]),
    ]

    edges, pairs, skipped = _compute_sentence_group_edges(
        sentences, groups
    )

    assert pairs == 1
    assert "S3" not in edges
    # S3 is NOT counted as skipped — only sentences with a
    # non-string id are. It simply contributes no edges, which is
    # the AC14 contract.
    assert skipped == 0


def test_compute_sentence_group_edges_skips_sentences_without_id() -> None:
    """A sentence whose ``id`` is not a string is skipped (counted
    in the ``skipped`` counter) and contributes no edges.

    The group pass has no requirement on ``properties.hanzi`` or
    ``properties.meaning`` — only the id needs to be a usable
    string. A non-string id is the only thing that causes a
    sentence to be counted as skipped by this helper.
    """
    sentences = [
        _make_sentence(unit_id="S1", hanzi="a"),
        # id is an int, not a string → skipped.
        {
            "id": 99,  # type: ignore[dict-item]
            "type": "sentence",
            "properties": {"hanzi": "x"},
            "connections": [],
        },
    ]
    # The group has only one valid-string-id member (S1) so no
    # unordered pair can be formed regardless. The int-id unit
    # is counted as skipped.
    groups = [
        _make_group("g", ["S1"]),
    ]

    edges, pairs, skipped = _compute_sentence_group_edges(
        sentences, groups
    )

    assert pairs == 0
    assert skipped == 1  # the int-id unit
    assert edges == {}


def test_compute_sentence_group_edges_no_self_loops() -> None:
    """A sentence that is its own group member never gets a
    ``group`` edge pointing at itself.

    AC14 forbids self-loops. We construct a single-sentence
    vault where the sentence is a member of a group; the pair
    loop (which uses ``i < j``) cannot form a pair with itself,
    so no edge is written. This guards against future refactors
    that loosen the loop bound.
    """
    sentences = [
        _make_sentence(unit_id="S1", hanzi="a"),
    ]
    groups = [
        _make_group("g", ["S1"]),
    ]

    edges, pairs, skipped = _compute_sentence_group_edges(
        sentences, groups
    )

    assert pairs == 0
    assert skipped == 0
    assert edges == {}


def test_compute_sentence_group_edges_handles_missing_members_field() -> None:
    """A group unit with missing or malformed ``properties.members``
    is treated as if it has no members — it contributes nothing
    to the membership index and no edges are written.

    The algorithm must tolerate a corrupt vault entry without
    crashing.
    """
    sentences = [
        _make_sentence(unit_id="S1", hanzi="a"),
        _make_sentence(unit_id="S2", hanzi="b"),
    ]
    # Group with no ``properties`` at all.
    bad_group_no_props: dict = {
        "id": "g-no-props",
        "type": "group",
        "name": "g-no-props",
        "connections": [],
    }
    # Group whose ``properties.members`` is not a list.
    bad_group_bad_members: dict = {
        "id": "g-bad-members",
        "type": "group",
        "name": "g-bad-members",
        "properties": {"members": "not a list"},
        "connections": [],
    }

    edges, pairs, skipped = _compute_sentence_group_edges(
        sentences, [bad_group_no_props, bad_group_bad_members]
    )

    # Neither group contributes a member, so no pair shares a
    # group and no edges are written. The malformed groups are
    # silently ignored — no exception.
    assert pairs == 0
    assert skipped == 0
    assert edges == {}


# ---------------------------------------------------------------------------
# AC15 — opposite edges (T18)
# ---------------------------------------------------------------------------
#
# These tests cover the ``opposite`` connection kind: symmetric edges
# between word units whose ``properties.antonyms`` arrays reference each
# other (in either direction). They mirror the AC12 / AC13 / AC14 tests
# in structure but use word units and a declared-relation source
# (``antonyms``) rather than a pairwise similarity.
#
# Conventions:
# * Each unordered word pair declared as antonyms by at least one side
#   yields exactly ONE ``opposite`` edge on each side, with score 1.0.
# * The OTHER side's ``properties.antonyms`` array is synced so the
#   declared relation is symmetric in both the connection graph and
#   the user-visible field.
# * Unknown target ids are SKIPPED (no edge written, no sync attempted).
# * Self-loops are excluded.
# * A word with no ``antonyms`` array or an empty array contributes
#   nothing.
#
# The ``_make_word`` helper below produces a word unit dict matching
# the shape returned by :func:`api.services.word_registry.ensure_word_unit`
# so the connector sees the same on-disk shape it would see in
# production.


def _make_word(
    word_id: str,
    hanzi: str,
    pinyin: str,
    antonyms: list[str] | None = None,
) -> dict:
    """Build a minimal word-unit dict for fixture purposes.

    Mirrors the shape produced by
    :func:`api.services.word_registry.ensure_word_unit` so the
    connector sees the same on-disk shape it would see in
    production. ``english`` and ``meaning`` default to empty
    strings (the registry's default behavior). ``antonyms`` is
    copied so the caller can mutate the original list without
    affecting the fixture. ``created`` / ``updated`` are pinned
    so tests can detect the ``updated`` refresh without depending
    on the wall clock.
    """
    properties: dict[str, Any] = {
        "hanzi": hanzi,
        "pinyin": pinyin,
        "english": "",
        "meaning": "",
        "groups": [],
        "antonyms": list(antonyms) if antonyms is not None else [],
    }
    return {
        "id": word_id,
        "type": "word",
        "name": hanzi,
        "properties": properties,
        "connections": [],
        "created": "2026-06-24",
        "updated": "2026-06-24",
        "author_confirmed": True,
    }


def _seed_words(vault_root: str, words: list[dict]) -> None:
    """Write a list of word units to the vault.

    Goes through :func:`write_unit` so the fixtures mirror how
    production code populates the vault. Order of writes does not
    matter for the connector — the algorithm layer reads the
    word list independently.
    """
    for unit in words:
        write_unit(vault_root, unit)


def _seed_words_and_sentences(
    vault_root: str,
    words: list[dict],
    sentences: list[dict] | None = None,
) -> None:
    """Write a list of word units AND optionally a list of sentence
    units to the vault.

    Used by tests that need to confirm the sentence-level and
    word-level passes coexist (e.g. AC15 does not affect
    lexical/semantic/group counts). All units go through
    :func:`write_unit` so the fixtures mirror how production code
    populates the vault.
    """
    if sentences:
        for unit in sentences:
            _write_sentence(vault_root, unit)
    for unit in words:
        write_unit(vault_root, unit)


def _opposite_edges(unit: dict) -> list[dict]:
    """Return only the ``opposite`` edges of a unit, in list order."""
    return [
        edge
        for edge in unit.get("connections", [])
        if isinstance(edge, dict) and edge.get("kind") == "opposite"
    ]


def test_opposite_edge_written_for_antonym_pair(tmp_path: Path) -> None:
    """Two words, chi and è, each declare the OTHER as their
    antonym. After ``compute_connections``, each word has an
    ``opposite`` edge pointing to the other with score 1.0, and
    ``opposite_pairs`` in the summary is 1.

    AC15 happy path: declared relation on BOTH sides ⇒ one edge
    each direction, score fixed at 1.0.
    """
    vault_root = str(tmp_path)
    _seed_words(
        vault_root,
        [
            _make_word(
                word_id="chī", hanzi="吃", pinyin="chī", antonyms=["è"]
            ),
            _make_word(word_id="è", hanzi="饿", pinyin="è", antonyms=["chī"]),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["opposite_pairs"] == 1
    assert summary["opposite_pairs_written"] == 1
    assert summary["words_touched"] == 2
    # No sentences in this vault, so the sentence counters are zero.
    assert summary["sentences_touched"] == 0

    chi = read_unit(vault_root, "word", "chī")
    e = read_unit(vault_root, "word", "è")

    opp_chi = _opposite_edges(chi)
    opp_e = _opposite_edges(e)

    assert len(opp_chi) == 1
    assert len(opp_e) == 1
    assert opp_chi[0]["to"] == "è"
    assert opp_e[0]["to"] == "chī"
    assert opp_chi[0]["kind"] == "opposite"
    assert opp_e[0]["kind"] == "opposite"
    assert opp_chi[0]["score"] == pytest.approx(1.0)
    assert opp_e[0]["score"] == pytest.approx(1.0)


def test_opposite_edge_symmetric_when_only_one_side_declares(
    tmp_path: Path,
) -> None:
    """chi declares è as its antonym; è declares nothing. After
    ``compute_connections``:

    * chi has an ``opposite`` edge to è (score 1.0)
    * è has an ``opposite`` edge to chi (score 1.0)
    * è's ``properties.antonyms`` now contains ``"chī"`` (the
      AC15 "writes symmetrically" half)
    * chi's ``properties.antonyms`` still contains ``"è"``

    This is the AC15 symmetry test. The connector is responsible
    for materializing the symmetry in BOTH the connection graph
    AND the user-visible ``antonyms`` array.
    """
    vault_root = str(tmp_path)
    _seed_words(
        vault_root,
        [
            _make_word(
                word_id="chī", hanzi="吃", pinyin="chī", antonyms=["è"]
            ),
            _make_word(
                word_id="è", hanzi="饿", pinyin="è", antonyms=[]
            ),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["opposite_pairs"] == 1
    # Both words are touched: chi via its edge, è via both the
    # edge AND the antonym-array sync.
    assert summary["words_touched"] == 2

    chi = read_unit(vault_root, "word", "chī")
    e = read_unit(vault_root, "word", "è")

    # Edges.
    opp_chi = _opposite_edges(chi)
    opp_e = _opposite_edges(e)
    assert len(opp_chi) == 1 and opp_chi[0]["to"] == "è"
    assert len(opp_e) == 1 and opp_e[0]["to"] == "chī"
    assert opp_chi[0]["score"] == pytest.approx(1.0)
    assert opp_e[0]["score"] == pytest.approx(1.0)

    # Symmetry of antonym arrays.
    chi_ant = chi["properties"]["antonyms"]
    e_ant = e["properties"]["antonyms"]
    assert "è" in chi_ant  # preserved
    assert "chī" in e_ant  # mirrored
    # And the order of the original chi declaration is preserved
    # (sync only APPENDS — it does not reorder existing entries).
    assert chi_ant == ["è"]
    # è's array was empty; after sync it has exactly one entry.
    assert e_ant == ["chī"]


def test_opposite_edge_idempotent(tmp_path: Path) -> None:
    """Calling ``compute_connections`` twice does not duplicate
    either the ``opposite`` edge or the mirrored ``antonyms``
    entry on the OTHER side.

    AC15 + SPEC §4 R7 idempotency. After two runs:
    * Each word has exactly ONE ``opposite`` edge pointing to
      the other.
    * Each word's ``properties.antonyms`` array contains the
      other id exactly once (not twice).
    * ``opposite_pairs`` is 1 both times (it counts unordered
      pairs, not edge objects).
    """
    vault_root = str(tmp_path)
    _seed_words(
        vault_root,
        [
            _make_word(
                word_id="chī", hanzi="吃", pinyin="chī", antonyms=["è"]
            ),
            _make_word(word_id="è", hanzi="饿", pinyin="è", antonyms=[]),
        ],
    )

    first = compute_connections(vault_root, embedder=_emb())
    second = compute_connections(vault_root, embedder=_emb())

    assert first["opposite_pairs"] == 1
    assert second["opposite_pairs"] == 1

    chi = read_unit(vault_root, "word", "chī")
    e = read_unit(vault_root, "word", "è")

    # Exactly one opposite edge per direction.
    assert len(_opposite_edges(chi)) == 1
    assert len(_opposite_edges(e)) == 1

    # And the on-disk JSON has only one edge per direction.
    chi_path = Path(vault_root) / "units" / "words" / "chī.json"
    with chi_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    assert len(_edges_of_kind(raw, "opposite")) == 1

    # The mirrored antonym appears EXACTLY ONCE — the second
    # run's sync detected that the entry was already present
    # and appended nothing.
    assert e["properties"]["antonyms"] == ["chī"]
    assert chi["properties"]["antonyms"] == ["è"]


def test_opposite_no_edge_without_antonym_reference(tmp_path: Path) -> None:
    """Two words with empty ``antonyms`` arrays produce zero
    ``opposite`` edges and a zero ``opposite_pairs`` count.

    AC15: "A word with no ``antonyms`` array or an empty array
    contributes no edges." An empty declaration on BOTH sides is
    the empty-graph case; the function must not invent edges.
    """
    vault_root = str(tmp_path)
    _seed_words(
        vault_root,
        [
            _make_word(word_id="chī", hanzi="吃", pinyin="chī", antonyms=[]),
            _make_word(word_id="è", hanzi="饿", pinyin="è", antonyms=[]),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["opposite_pairs"] == 0
    assert summary["opposite_pairs_written"] == 0
    # Neither word contributed an edge AND neither required an
    # antonym-array sync (empty arrays, nothing to mirror).
    # The words exist on disk but contributed no edge, so they
    # are NOT counted as ``sentences_touched`` (that counter is
    # sentence-only). The ``words_touched`` counter is also
    # zero because the I/O loop only writes units that had at
    # least one entry in the merged edge map (or were added via
    # symmetry sync, which didn't fire here).
    assert summary["words_touched"] == 0

    chi = read_unit(vault_root, "word", "chī")
    e = read_unit(vault_root, "word", "è")
    assert _opposite_edges(chi) == []
    assert _opposite_edges(e) == []
    assert chi["properties"]["antonyms"] == []
    assert e["properties"]["antonyms"] == []


def test_opposite_score_is_one(tmp_path: Path) -> None:
    """The stored score on every ``opposite`` edge is exactly 1.0.

    AC15 / SPEC §2.4: "score = 1.0" — a literal, not a generic
    positive value. We assert equality with the exact float
    ``1.0`` (via ``pytest.approx`` for float-typed comparison
    safety) rather than just ``> 0`` so a future regression to
    "0.5" or "some similarity-derived value" is caught.
    """
    vault_root = str(tmp_path)
    _seed_words(
        vault_root,
        [
            _make_word(
                word_id="chī", hanzi="吃", pinyin="chī", antonyms=["è"]
            ),
            _make_word(
                word_id="è", hanzi="饿", pinyin="è", antonyms=["chī"]
            ),
        ],
    )

    compute_connections(vault_root, embedder=_emb())

    chi = read_unit(vault_root, "word", "chī")
    opp = _opposite_edges(chi)
    assert len(opp) == 1
    assert opp[0]["score"] == pytest.approx(1.0)
    # Belt and suspenders: not just > 0 — exactly 1.0.
    assert opp[0]["score"] == 1.0


def test_opposite_skips_self_loop(tmp_path: Path) -> None:
    """A word whose ``antonyms`` array contains its own id does
    NOT get an ``opposite`` edge pointing to itself.

    AC15 forbids self-loops. We construct a contrived word whose
    id is ``"w"`` and whose ``antonyms`` array contains
    ``["w"]``. The pass must drop the (w, w) pair — which it
    does via the self-loop guard in
    :func:`_compute_word_opposite_edges`. After
    ``compute_connections``, the word has no ``opposite`` edges
    at all, and ``opposite_pairs`` is 0.
    """
    vault_root = str(tmp_path)
    _seed_words(
        vault_root,
        [
            _make_word(word_id="w", hanzi="我", pinyin="w", antonyms=["w"]),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["opposite_pairs"] == 0
    assert summary["opposite_pairs_written"] == 0

    w = read_unit(vault_root, "word", "w")
    assert _opposite_edges(w) == []
    # The self-reference in ``antonyms`` is preserved verbatim —
    # pruning the array is a write-side concern that requires
    # an explicit "remove" operation, not the upsert contract
    # this pass implements.
    assert w["properties"]["antonyms"] == ["w"]


def test_opposite_unknown_target_does_not_crash(tmp_path: Path) -> None:
    """A word whose ``antonyms`` array references a target that
    does NOT exist as a word unit on disk contributes NO edge
    and does NOT crash the connector.

    Locked-in design decision (see
    :func:`_compute_word_opposite_edges` docstring and the
    "Edges to unknown targets" note in the connector module
    docstring): unknown target ids are SKIPPED. We do not write
    a dangling edge to a non-existent target, and we do not
    attempt to sync the OTHER side's ``antonyms`` array because
    there is no OTHER side on disk. The rationale is that the
    connection graph should not carry references that cannot
    be resolved by the search route.

    This test asserts the chosen behavior: no edge written,
    no crash, and no modification to the declared word's
    ``antonyms`` array (the connector never mutates the
    DECLARING side's array — it only mirrors onto the OTHER
    side, which doesn't exist here).
    """
    vault_root = str(tmp_path)
    _seed_words(
        vault_root,
        [
            _make_word(
                word_id="chī",
                hanzi="吃",
                pinyin="chī",
                antonyms=["nonexistent"],
            ),
        ],
    )

    # Must not raise.
    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["opposite_pairs"] == 0
    assert summary["opposite_pairs_written"] == 0
    # The declaring word has no outgoing edge (the only declared
    # target was unknown and was skipped), so it is NOT in the
    # merged edge map and is NOT written back. ``words_touched``
    # is therefore 0 in this scenario.
    assert summary["words_touched"] == 0

    chi = read_unit(vault_root, "word", "chī")
    assert _opposite_edges(chi) == []
    # The original declaration is preserved verbatim — the
    # connector only mutates OTHER sides, not the declaring side.
    assert chi["properties"]["antonyms"] == ["nonexistent"]


def test_opposite_does_not_affect_other_kinds(tmp_path: Path) -> None:
    """Three words forming an antonym chain (chi↔è, è↔lěng,
    lěng↔rè) get exactly the expected ``opposite`` edges and
    NO lexical/semantic/group edges (those are sentence-level
    and not exercised in a words-only vault).

    The summary's sentence counters (``sentences_touched``,
    ``lexical_pairs``, ``semantic_pairs``, ``group_pairs``) are
    all zero in this vault-of-words-only scenario — the AC15
    pass is fully independent of the sentence passes.
    """
    vault_root = str(tmp_path)
    _seed_words(
        vault_root,
        [
            _make_word(
                word_id="chī", hanzi="吃", pinyin="chī", antonyms=["è"]
            ),
            _make_word(
                word_id="è", hanzi="饿", pinyin="è", antonyms=["chī", "lěng"]
            ),
            _make_word(
                word_id="lěng",
                hanzi="冷",
                pinyin="lěng",
                antonyms=["è", "rè"],
            ),
            _make_word(
                word_id="rè", hanzi="热", pinyin="rè", antonyms=["lěng"]
            ),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    # Three unordered pairs: (chī, è), (è, lěng), (lěng, rè).
    assert summary["opposite_pairs"] == 3
    assert summary["opposite_pairs_written"] == 3

    # No sentences were involved in this vault — every
    # sentence-level counter is zero, and the word-level pass
    # did not touch them.
    assert summary["sentences_touched"] == 0
    assert summary["lexical_pairs"] == 0
    assert summary["semantic_pairs"] == 0
    assert summary["group_pairs"] == 0

    # All four words should be touched (each has at least one
    # outgoing opposite edge).
    assert summary["words_touched"] == 4

    chi = read_unit(vault_root, "word", "chī")
    e = read_unit(vault_root, "word", "è")
    leng = read_unit(vault_root, "word", "lěng")
    re_ = read_unit(vault_root, "word", "rè")

    # Verify the per-word edge sets.
    chi_targets = sorted(e["to"] for e in _opposite_edges(chi))
    e_targets = sorted(e["to"] for e in _opposite_edges(e))
    leng_targets = sorted(e["to"] for e in _opposite_edges(leng))
    re_targets = sorted(e["to"] for e in _opposite_edges(re_))

    assert chi_targets == ["è"]
    assert e_targets == ["chī", "lěng"]
    assert leng_targets == sorted(["è", "rè"])
    assert re_targets == ["lěng"]

    # And the mirrored antonym arrays are now symmetric on every
    # side: every declared partner appears in both directions'
    # ``antonyms`` list.
    assert set(chi["properties"]["antonyms"]) == {"è"}
    assert set(e["properties"]["antonyms"]) == {"chī", "lěng"}
    assert set(leng["properties"]["antonyms"]) == {"è", "rè"}
    assert set(re_["properties"]["antonyms"]) == {"lěng"}


def test_opposite_pairs_summary(tmp_path: Path) -> None:
    """``summary["opposite_pairs"]`` reflects the actual unordered
    pair count, regardless of how many sides declared the
    relation.

    We use three unordered pairs (declared via a single side
    each, to also exercise the symmetry-sync path on every
    pair). ``opposite_pairs`` is 3 — counting PAIRS, not edges
    or declarations. ``opposite_pairs_written`` is the alias
    and must equal ``opposite_pairs`` exactly.
    """
    vault_root = str(tmp_path)
    _seed_words(
        vault_root,
        [
            # chi declares è.
            _make_word(
                word_id="chī", hanzi="吃", pinyin="chī", antonyms=["è"]
            ),
            # lěng declares rè.
            _make_word(
                word_id="lěng",
                hanzi="冷",
                pinyin="lěng",
                antonyms=["rè"],
            ),
            # gāo declares dī.
            _make_word(
                word_id="gāo",
                hanzi="高",
                pinyin="gāo",
                antonyms=["dī"],
            ),
            # The OTHER sides start empty; the connector syncs.
            _make_word(word_id="è", hanzi="饿", pinyin="è", antonyms=[]),
            _make_word(word_id="rè", hanzi="热", pinyin="rè", antonyms=[]),
            _make_word(word_id="dī", hanzi="低", pinyin="dī", antonyms=[]),
        ],
    )

    summary = compute_connections(vault_root, embedder=_emb())

    assert summary["opposite_pairs"] == 3
    assert summary["opposite_pairs_written"] == 3
    assert summary["opposite_pairs"] == summary["opposite_pairs_written"]
    # Every word is touched: declaring sides via their edges,
    # OTHER sides via BOTH the edge and the antonym-array sync.
    assert summary["words_touched"] == 6


# ---------------------------------------------------------------------------
# Pure-algorithm tests for the opposite pass (T18)
# ---------------------------------------------------------------------------


def test_compute_word_opposite_edges_pure_no_io() -> None:
    """The pure opposite helper accepts an in-memory word list
    and returns edges + symmetry-sync set without touching the
    vault.

    Two words declare each other. Expected: one unordered pair,
    one edge each direction, score 1.0, and NO entry in the
    symmetry-sync set (because BOTH sides already declare the
    relation — there is nothing to mirror).
    """
    words = [
        _make_word(
            word_id="chī", hanzi="吃", pinyin="chī", antonyms=["è"]
        ),
        _make_word(
            word_id="è", hanzi="饿", pinyin="è", antonyms=["chī"]
        ),
    ]

    edges, pairs, sync = _compute_word_opposite_edges(words)

    assert pairs == 1
    # No sync needed: both sides already declare.
    assert sync == set()
    assert edges["chī"] == [("è", pytest.approx(1.0))]
    assert edges["è"] == [("chī", pytest.approx(1.0))]


def test_compute_word_opposite_edges_one_sided_pair_adds_to_sync() -> None:
    """When only ONE side declares the relation, the pair is in
    the symmetry-sync set so the I/O layer can mirror it onto
    the OTHER side.

    The edge map is identical to the both-sided case (one edge
    each direction). The sync set, however, contains the
    pair so the I/O layer will append the missing side to the
    OTHER word's ``antonyms`` array.
    """
    words = [
        _make_word(
            word_id="chī", hanzi="吃", pinyin="chī", antonyms=["è"]
        ),
        _make_word(word_id="è", hanzi="饿", pinyin="è", antonyms=[]),
    ]

    edges, pairs, sync = _compute_word_opposite_edges(words)

    assert pairs == 1
    assert edges["chī"] == [("è", pytest.approx(1.0))]
    assert edges["è"] == [("chī", pytest.approx(1.0))]
    # Sync set contains the unordered pair (sorted ids).
    assert sync == {("chī", "è")}


def test_compute_word_opposite_edges_skips_unknown_targets() -> None:
    """An antonym id that points at a missing word file is
    skipped entirely: no edge written, no sync attempted.

    This locks in the design decision documented at the top of
    the function: unknown target ids do not produce dangling
    references in the connection graph.
    """
    words = [
        _make_word(
            word_id="chī",
            hanzi="吃",
            pinyin="chī",
            antonyms=["nonexistent"],
        ),
    ]

    edges, pairs, sync = _compute_word_opposite_edges(words)

    assert pairs == 0
    assert sync == set()
    assert edges == {}


def test_compute_word_opposite_edges_skips_self_loops() -> None:
    """A word whose ``antonyms`` list contains its own id does
    NOT get a self-loop edge.

    The pure helper drops the (a, a) pair via the explicit
    self-loop guard.
    """
    words = [
        _make_word(word_id="w", hanzi="我", pinyin="w", antonyms=["w"]),
    ]

    edges, pairs, sync = _compute_word_opposite_edges(words)

    assert pairs == 0
    assert sync == set()
    assert edges == {}


def test_compute_word_opposite_edges_empty_antonyms_contributes_nothing() -> (
    None
):
    """A word with no ``antonyms`` array or an empty array
    contributes no edges and is not in the symmetry-sync set.

    The pure helper must tolerate missing or empty fields
    without raising.
    """
    # Word with explicit empty list.
    word_empty = _make_word(
        word_id="w1", hanzi="我", pinyin="w1", antonyms=[]
    )
    # Word with missing ``antonyms`` key entirely.
    word_missing = _make_word(
        word_id="w2", hanzi="你", pinyin="w2", antonyms=[]
    )
    del word_missing["properties"]["antonyms"]
    # Word with malformed ``antonyms`` (not a list).
    word_bad = _make_word(
        word_id="w3", hanzi="他", pinyin="w3", antonyms=[]
    )
    word_bad["properties"]["antonyms"] = "not a list"

    edges, pairs, sync = _compute_word_opposite_edges(
        [word_empty, word_missing, word_bad]
    )

    assert pairs == 0
    assert sync == set()
    assert edges == {}