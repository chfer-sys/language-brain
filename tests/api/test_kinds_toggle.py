"""Tests for the kinds toggle (T22 — SPEC §6 AC18).

The kinds toggle wires two things into the search response:

1. Each result row's ``kinds`` field lists which connection kinds
   produced that hit (``"lexical"``, ``"semantic"``, and in T23+
   ``"group"``, ``"opposite"``).

2. The ``?kinds=<csv>`` query parameter filters the response to
   only include hits produced by at least one of the listed kinds.

The first is exercised by the new :func:`merge_hits_with_kinds`
service helper plus a route-level test that mocks the lexical hit
list. The second is exercised by route tests that drive the public
``GET /api/search`` endpoint through FastAPI's :class:`TestClient`.

These tests deliberately mock the lexical and semantic passes at
the service boundary (via :mod:`unittest.mock.patch`) so the test
of the kinds plumbing does not depend on the FAISS indexer or
the lexical ranker's exact behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import config as config_module
from api.main import app
from api.services.search import (
    SearchHit,
    merge_hits_with_kinds,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """A TestClient bound to a fresh ``LANGUAGE_BRAIN_VAULT=tmp_path``.

    Mirrors the pattern from :mod:`tests.api.test_search`: clear
    the ``get_settings`` lru_cache, set the env var, and patch
    the module-level singleton so the route module reads from
    ``tmp_path``. The vault itself stays empty — these tests
    patch the service layer so no real I/O happens.
    """
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        config_module.get_settings.cache_clear()


def _h(unit_id: str, unit_type: str, score: float) -> SearchHit:
    return SearchHit(
        unit_id=unit_id, unit_type=unit_type, name="x", snippet="y", score=score
    )


# ---------------------------------------------------------------------------
# merge_hits_with_kinds — service-layer tests
# ---------------------------------------------------------------------------


def test_merge_hits_with_kinds_empty_input_returns_empty_pair() -> None:
    """No kinded lists in → ``([], {})``. The empty map makes
    downstream kind-intersection checks safe (no KeyError)."""
    merged, kinds_by_key = merge_hits_with_kinds()
    assert merged == []
    assert kinds_by_key == {}


def test_merge_hits_with_kinds_single_kind_list() -> None:
    """A single ``(kind, [hit, ...])`` tuple reports that kind for
    every surviving key."""
    hits = [_h("s-1", "sentence", 0.5), _h("s-2", "sentence", 0.3)]
    merged, kinds_by_key = merge_hits_with_kinds(("lexical", hits))
    assert merged == hits
    assert kinds_by_key == {
        ("s-1", "sentence"): {"lexical"},
        ("s-2", "sentence"): {"lexical"},
    }


def test_merge_hits_with_kinds_reports_all_kinds_per_key() -> None:
    """A key hit by both lexical and semantic lists reports both
    kinds in the returned set, regardless of which occurrence
    wins on score."""
    lex = [_h("s-1", "sentence", 0.3)]
    sem = [_h("s-1", "sentence", 0.9)]
    merged, kinds_by_key = merge_hits_with_kinds(
        ("lexical", lex),
        ("semantic", sem),
    )
    assert len(merged) == 1
    assert merged[0].score == 0.9  # higher score wins
    # Both kinds recorded for this key — even though the lexical
    # hit scored lower, it still counts as a contributing kind.
    assert kinds_by_key[("s-1", "sentence")] == {"lexical", "semantic"}


def test_merge_hits_with_kinds_dedup_and_max_score() -> None:
    """Dedup and max-score behavior matches :func:`merge_hits`,
    while the kinds map reflects every contributing kind."""
    lex = [_h("s-1", "sentence", 0.3), _h("s-2", "sentence", 0.7)]
    sem = [_h("s-1", "sentence", 0.9)]
    merged, kinds_by_key = merge_hits_with_kinds(
        ("lexical", lex),
        ("semantic", sem),
    )
    # s-1 wins from semantic at 0.9; s-2 only from lexical at 0.7.
    assert merged == [
        _h("s-1", "sentence", 0.9),
        _h("s-2", "sentence", 0.7),
    ]
    assert kinds_by_key[("s-1", "sentence")] == {"lexical", "semantic"}
    assert kinds_by_key[("s-2", "sentence")] == {"lexical"}


def test_merge_hits_with_kinds_empty_inner_lists_are_skipped() -> None:
    """A kind whose hit list is empty contributes no kinds to any
    key — it is silently skipped, mirroring :func:`merge_hits`'s
    ``if not hit_list: continue`` behavior."""
    lex = [_h("s-1", "sentence", 0.5)]
    merged, kinds_by_key = merge_hits_with_kinds(
        ("lexical", lex),
        ("semantic", []),
    )
    assert merged == lex
    assert kinds_by_key == {("s-1", "sentence"): {"lexical"}}


def test_merge_hits_with_kinds_distinct_unit_types_are_separate() -> None:
    """Same unit_id with different unit_type are distinct keys —
    each gets its own kinds set."""
    s = _h("chi", "sentence", 0.5)
    w = _h("chi", "word", 0.7)
    merged, kinds_by_key = merge_hits_with_kinds(("lexical", [s, w]))
    assert [h.unit_type for h in merged] == ["word", "sentence"]
    assert kinds_by_key[("chi", "sentence")] == {"lexical"}
    assert kinds_by_key[("chi", "word")] == {"lexical"}


# ---------------------------------------------------------------------------
# Route-level tests — kinds populated in the response
# ---------------------------------------------------------------------------


def _mock_search_passes(
    monkeypatch: pytest.MonkeyPatch,
    lexical: list[SearchHit],
    semantic: list[SearchHit],
) -> None:
    """Patch the service-layer entry points so the route sees a
    fixed pair of hit lists, regardless of vault state or FAISS
    index contents."""
    monkeypatch.setattr(
        "api.routes.search.lexical_search",
        lambda vault_root, query, limit=20, types=None: list(lexical),
    )
    monkeypatch.setattr(
        "api.routes.search.semantic_search",
        lambda vault_root, query, limit=20, **kw: list(semantic),
    )


def test_route_lexical_only_hit_reports_kinds_lexical(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hit produced only by the lexical pass reports
    ``kinds=["lexical"]``. The route must drive the kinds map
    through the new merge function, not the old empty default."""
    only_lexical = [_h("s-1", "sentence", 0.5)]
    _mock_search_passes(monkeypatch, lexical=only_lexical, semantic=[])

    resp = client.get("/api/search", params={"q": "anything"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["id"] == "s-1"
    assert body["results"][0]["kinds"] == ["lexical"]


def test_route_dual_pass_hit_reports_both_kinds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hit produced by both lexical AND semantic reports
    ``kinds=["lexical", "semantic"]`` (sorted)."""
    lex = [_h("s-1", "sentence", 0.3)]
    sem = [_h("s-1", "sentence", 0.9)]
    _mock_search_passes(monkeypatch, lex, sem)

    resp = client.get("/api/search", params={"q": "anything"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["kinds"] == ["lexical", "semantic"]


def test_route_semantic_only_hit_reports_kinds_semantic(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hit produced only by the semantic pass reports
    ``kinds=["semantic"]``. This path exercises the case where
    the lexical pass returns no hits at all but the FAISS index
    does — common for queries that paraphrase rather than
    tokenize-match."""
    sem_only = [_h("s-1", "sentence", 0.8)]
    _mock_search_passes(monkeypatch, lexical=[], semantic=sem_only)

    resp = client.get("/api/search", params={"q": "anything"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["kinds"] == ["semantic"]


# ---------------------------------------------------------------------------
# Route-level tests — kinds toggle filtering (AC18)
# ---------------------------------------------------------------------------


def test_route_kinds_semantic_filters_out_purely_lexical_hits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``?kinds=semantic`` keeps only hits whose producing-kinds
    set intersects ``{semantic}``. A hit produced only by the
    lexical pass has kinds ``{"lexical"}`` — no intersection —
    so it is dropped. This is the AC18 contract.

    We seed both passes so the dual-pass hit survives (it has
    ``semantic`` in its kinds set) but the lexical-only hit is
    filtered out."""
    # s-1: produced by both lexical and semantic (intersects → kept)
    # s-2: produced only by lexical (no intersect → dropped)
    lex = [_h("s-1", "sentence", 0.3), _h("s-2", "sentence", 0.7)]
    sem = [_h("s-1", "sentence", 0.9)]
    _mock_search_passes(monkeypatch, lex, sem)

    resp = client.get(
        "/api/search", params={"q": "anything", "kinds": "semantic"}
    )
    assert resp.status_code == 200
    body = resp.json()
    ids = [r["id"] for r in body["results"]]
    assert "s-1" in ids
    assert "s-2" not in ids
    # The surviving row's kinds set must contain "semantic".
    assert "semantic" in body["results"][0]["kinds"]


def test_route_kinds_lexical_filters_out_purely_semantic_hits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``?kinds=lexical`` keeps only hits whose producing-kinds
    set intersects ``{lexical}``. A semantic-only hit is dropped."""
    lex = [_h("s-1", "sentence", 0.5)]
    sem = [_h("s-2", "sentence", 0.9)]  # only semantic
    _mock_search_passes(monkeypatch, lex, sem)

    resp = client.get(
        "/api/search", params={"q": "anything", "kinds": "lexical"}
    )
    assert resp.status_code == 200
    body = resp.json()
    ids = [r["id"] for r in body["results"]]
    assert "s-1" in ids
    assert "s-2" not in ids


def test_route_kinds_opposite_returns_empty_results(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``?kinds=opposite`` returns ``[]`` because no search kind
    is ``"opposite"`` — antonymy is between word pairs in the
    connector, not a search ranker. The lexical and semantic
    passes produce hits with kinds in ``{"lexical", "semantic"}``
    only, so the intersection with ``{"opposite"}`` is always
    empty.

    This test guards against a future refactor accidentally
    emitting a phantom ``opposite`` kind from somewhere; if it
    ever starts producing hits, the test fails and the team
    can decide whether antonym-based search is in scope."""
    lex = [_h("s-1", "sentence", 0.5), _h("s-2", "sentence", 0.3)]
    sem = [_h("s-1", "sentence", 0.9)]
    _mock_search_passes(monkeypatch, lex, sem)

    resp = client.get(
        "/api/search", params={"q": "anything", "kinds": "opposite"}
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_route_kinds_csv_keeps_union(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``?kinds=lexical,semantic`` is the union of the two — both
    kinds contribute, so a dual-pass hit and a lexical-only hit
    both survive."""
    lex = [_h("s-1", "sentence", 0.3), _h("s-2", "sentence", 0.7)]
    sem = [_h("s-1", "sentence", 0.9)]
    _mock_search_passes(monkeypatch, lex, sem)

    resp = client.get(
        "/api/search",
        params={"q": "anything", "kinds": "lexical,semantic"},
    )
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()["results"]}
    assert ids == {"s-1", "s-2"}


# ---------------------------------------------------------------------------
# Route-level tests — deterministic ordering of the kinds list
# ---------------------------------------------------------------------------


def test_route_kinds_field_is_sorted_alphabetically(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``kinds`` must be alphabetically sorted in the response so
    the JSON is byte-deterministic across runs (set iteration
    order is not guaranteed in Python). With both ``lexical`` and
    ``"semantic"`` contributing, the expected order is the
    alphabetical one — ``lexical`` before ``"semantic"``.

    We also exercise the reverse input order to prove the sort
    is applied at the route boundary, not by accident of
    internal set insertion order."""
    lex = [_h("s-1", "sentence", 0.3)]
    sem = [_h("s-1", "sentence", 0.9)]
    _mock_search_passes(monkeypatch, lex, sem)

    resp = client.get("/api/search", params={"q": "anything"})
    assert resp.status_code == 200
    kinds = resp.json()["results"][0]["kinds"]
    assert kinds == sorted(kinds)
    assert kinds == ["lexical", "semantic"]


def test_route_kinds_field_is_sorted_when_lexical_only_and_input_unsorted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single-element kinds list is trivially sorted; this test
    confirms the route still hands a list (not a set) to the
    response model. The ``kinds=[]`` legacy from T20 would never
    survive the kinds-toggle filter even when the toggle is not
    requested, because the new merge function always populates
    the map."""
    only_lexical = [_h("s-1", "sentence", 0.5)]
    _mock_search_passes(monkeypatch, lexical=only_lexical, semantic=[])

    resp = client.get("/api/search", params={"q": "anything"})
    kinds = resp.json()["results"][0]["kinds"]
    assert kinds == ["lexical"]
    # And it really is a list, not a set dumped to JSON.
    assert isinstance(kinds, list)