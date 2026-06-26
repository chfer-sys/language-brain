"""Tests for :mod:`api.services.connector`.

Covers SPEC §6 AC12 — sentence ↔ sentence ``lexical`` connection
materialization (T15). The connector's design is purely additive:
future T16/T17 work will add ``group`` and ``opposite`` kinds to
the same :func:`compute_connections` entry point. These tests
focus on the lexical kind for now.

All tests use ``tmp_path`` for vault isolation; no test mutates the
real vault. Units are written through
:func:`api.services.unit_writer.write_unit` so the test fixtures
mirror how the production code path constructs units.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.connector import (
    _compute_sentence_lexical_edges,
    compute_connections,
)
from api.services.unit_writer import read_unit, write_unit


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_sentence(
    *,
    unit_id: str,
    hanzi: str,
    connections: list | None = None,
) -> dict:
    """Build a minimal sentence-unit dict for fixture purposes.

    Mirrors the shape used by the rest of the codebase (see the
    SPEC §2 unit model). ``created`` / ``updated`` are pinned so
    tests can detect the ``updated`` refresh without depending on
    the wall clock.
    """
    return {
        "id": unit_id,
        "type": "sentence",
        "name": hanzi,
        "properties": {"hanzi": hanzi},
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


def _seed_vault(vault_root: str, sentences: list[dict]) -> None:
    """Write a list of sentence units to the vault."""
    for unit in sentences:
        _write_sentence(vault_root, unit)


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

    summary = compute_connections(str(vault_root))

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

    summary = compute_connections(vault_root)

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

    summary = compute_connections(vault_root)

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

    compute_connections(vault_root)

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

    summary = compute_connections(vault_root)

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

    first = compute_connections(vault_root)
    second = compute_connections(vault_root)

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

    compute_connections(vault_root)

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

    summary = compute_connections(vault_root)

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

    summary = compute_connections(vault_root)

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

    summary = compute_connections(vault_root)

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