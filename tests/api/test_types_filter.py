"""Tests for the ``types`` filter extended to include ``group`` (T23).

T23 extends SPEC §5.3's ``types`` query parameter from
``{sentence, word}`` to ``{sentence, word, group}``. The new
``group_search`` ranker reads ``<vault>/units/groups/*.json``,
scores each group by how many of the query's lowercase tokens
appear as a substring of the slug id or ``properties.display_name``,
and returns at most ``limit`` hits sorted by score descending.

These tests cover:

* the pure ``group_search`` service function (empty query,
  display-name match, id prefix match, limit enforcement,
  score-sort order);
* the route's new ``?types=group`` and ``?types=sentence,group``
  filters;
* the unknown-type 422 contract;
* the default (``?types`` omitted) path which now searches all
  three kinds;
* ``lexical_search``'s ``types`` filter integration — when the
  caller restricts ``types`` to ``["group"]``, only the group
  ranker runs.

Seeding strategy mirrors :mod:`tests.api.test_search`: write unit
files directly via :func:`api.services.unit_writer.write_unit` so
the tests are decoupled from the commit route and FAISS index.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import config as config_module
from api.main import app
from api.services.search import (
    group_search,
    has_natural_language_english,
    lexical_search,
)
from api.services.unit_writer import write_unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """A TestClient bound to a fresh ``LANGUAGE_BRAIN_VAULT=tmp_path``.

    Mirrors :mod:`tests.api.test_search`: clear the
    ``get_settings`` lru_cache, set the env var, and patch the
    module-level singleton so the route module (which imports
    ``settings`` directly) reads from ``tmp_path``.
    """
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        config_module.get_settings.cache_clear()


def _make_group(
    unit_id: str,
    display_name: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Build a minimal group unit dict ready for :func:`write_unit`.

    Group shape follows SPEC §2.3 and the locked OQ5 contract:
    ``id`` and ``name`` are the slug, ``properties.display_name``
    holds the human-readable form, ``properties.members`` is an
    empty list (group-membership edges are owned by a separate
    task and not exercised here).
    """
    return {
        "id": unit_id,
        "type": "group",
        "name": unit_id,
        "properties": {
            "display_name": display_name,
            "description": description,
            "members": [],
        },
        "connections": [],
        "created": "2026-06-27",
        "updated": "2026-06-27",
        "author_confirmed": True,
    }


def _seed_groups(groups: list[dict[str, Any]], tmp_path: Path) -> None:
    """Write a list of group dicts to ``tmp_path``."""
    for group in groups:
        write_unit(str(tmp_path), group)


# ---------------------------------------------------------------------------
# 1. group_search — service-layer contract
# ---------------------------------------------------------------------------


def test_group_search_empty_query_returns_empty(tmp_path: Path) -> None:
    """An empty / whitespace-only query returns ``[]``.

    The function tokenizes the query via ``re.findall`` over
    alphanumeric runs, so a whitespace-only string produces no
    tokens and short-circuits to ``[]`` before reading any groups.
    """
    _seed_groups(
        [_make_group("basic-verbs", display_name="Basic Verbs")],
        tmp_path,
    )

    assert group_search(str(tmp_path), "") == []
    assert group_search(str(tmp_path), "   ") == []
    # Non-string input also returns [] (defensive).
    assert group_search(str(tmp_path), None) == []  # type: ignore[arg-type]


def test_group_search_matches_by_display_name_substring_case_insensitive(
    tmp_path: Path,
) -> None:
    """A query that appears (case-insensitively) in a group's
    ``display_name`` produces a hit for that group.

    The haystack is ``"<slug_id> <display_name>"`` lowercased;
    the query tokens are also lowercased. The match is substring,
    so ``"verb"`` matches ``"Basic Verbs"`` and ``"basic-verbs"``.
    """
    _seed_groups(
        [
            _make_group("basic-verbs", display_name="Basic Verbs"),
            _make_group("foods", display_name="Common Foods"),
        ],
        tmp_path,
    )

    hits = group_search(str(tmp_path), "verb")
    assert isinstance(hits, list)
    assert len(hits) == 1
    assert hits[0].unit_id == "basic-verbs"
    assert hits[0].unit_type == "group"
    assert hits[0].name == "Basic Verbs"
    # Snippet is the slug id, which contains only ASCII alphanumerics
    # and a single hyphen — no natural-language English.
    assert hits[0].snippet == "basic-verbs"


def test_group_search_matches_by_id_prefix(tmp_path: Path) -> None:
    """A query token that matches a group's haystack produces a hit.

    The haystack is ``"<slug_id> <display_name>"`` lowercased. Token
    matching is exact substring containment, not "prefix of slug".
    Two groups whose slugs both contain the query token both match;
    one whose slug does NOT contain the token is skipped.
    """
    _seed_groups(
        [
            _make_group("basic-verbs", display_name="Basic Verbs"),
            _make_group("basic-food", display_name="Basic Food"),
            _make_group("advanced-verbs", display_name="Advanced Verbs"),
        ],
        tmp_path,
    )

    # "basic" appears in both "basic-verbs" and "basic-food" haystacks,
    # but NOT in "advanced-verbs". So the third group is correctly
    # skipped.
    hits = group_search(str(tmp_path), "basic")
    ids = sorted(h.unit_id for h in hits)
    assert ids == ["basic-food", "basic-verbs"]
    # All matching hits have the same score (1.0 base + 0.1 prefix
    # bonus since both slugs start with "b" like the first query
    # token). 1.1 total.
    assert all(h.score == pytest.approx(1.1) for h in hits)


def test_group_search_respects_limit(tmp_path: Path) -> None:
    """With ``limit=2`` and five matching groups, only two hits are
    returned (the top two by score)."""
    _seed_groups(
        [
            _make_group(f"g{i}", display_name=f"Group {i}") for i in range(5)
        ],
        tmp_path,
    )

    hits = group_search(str(tmp_path), "group", limit=2)
    assert len(hits) == 2
    # Sorted by score descending then id ascending.
    assert all(hits[i].score >= hits[i + 1].score for i in range(len(hits) - 1))


def test_group_search_returns_score_sorted(tmp_path: Path) -> None:
    """Hits come back sorted by score descending (tie-break id asc).

    Seed groups whose display_name + slug haystacks share tokens
    with the query at different rates:
    - food-words:  haystack "food-words food vocabulary". Matches
                   both "food" and "vocabulary" → score 1.0.
    - food-meals: haystack "food-meals food meals".   Matches "food"
                   only → score 0.5.
    - food-stuff: haystack "food-stuff food stuff".   Matches "food"
                   only → score 0.5, ties with food-meals.
    """
    _seed_groups(
        [
            _make_group("food-words", display_name="Food Vocabulary"),
            _make_group("food-meals", display_name="Food Meals"),
            _make_group("food-stuff", display_name="Food Stuff"),
        ],
        tmp_path,
    )

    hits = group_search(str(tmp_path), "food vocabulary")
    # food-words matches both tokens (1.0) and gets the prefix bonus
    # (+0.1) since "food-words" starts with "f" like the first query
    # token. So food-words ranks first with score 1.1.
    assert hits[0].unit_id == "food-words"
    assert hits[0].score == pytest.approx(1.1)
    # The remaining two match only "food" (1/2 = 0.5) plus the
    # prefix bonus (0.1) = 0.6; ties break by id ascending.
    assert len(hits) == 3
    assert hits[1].score == pytest.approx(0.6)
    assert hits[2].score == pytest.approx(0.6)
    assert hits[1].unit_id < hits[2].unit_id


def test_group_search_handles_empty_display_name(tmp_path: Path) -> None:
    """A group whose ``display_name`` is empty still matches via its
    slug id; ``name`` falls back to the slug id when ``display_name``
    is empty."""
    _seed_groups(
        [_make_group("basic-verbs", display_name="")],
        tmp_path,
    )

    hits = group_search(str(tmp_path), "basic")
    assert len(hits) == 1
    assert hits[0].unit_id == "basic-verbs"
    # Name falls back to slug id when display_name is empty.
    assert hits[0].name == "basic-verbs"
    assert hits[0].snippet == "basic-verbs"


# ---------------------------------------------------------------------------
# 2. lexical_search — ``types`` filter integration
# ---------------------------------------------------------------------------


def test_lexical_search_with_types_group_only_runs_group_ranker(
    tmp_path: Path,
) -> None:
    """``lexical_search`` with ``types=["group"]`` runs only the
    group ranker — no sentence or word units are returned, even
    when they would otherwise match the query."""
    # Seed a sentence that would match a "verb" query via hanzi
    # tokens — it must NOT appear when types=["group"].
    sentence = {
        "id": "s1",
        "type": "sentence",
        "name": "verb-sentence",
        "properties": {
            "hanzi": "verb",
            "pinyin": "verb",
            "english": "",
            "meaning": "",
            "words": [],
            "word_refs": [],
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-27",
        "updated": "2026-06-27",
        "author_confirmed": True,
    }
    write_unit(str(tmp_path), sentence)
    _seed_groups(
        [_make_group("basic-verbs", display_name="Basic Verbs")],
        tmp_path,
    )

    hits = lexical_search(str(tmp_path), "verb", types=["group"])
    ids = [h.unit_id for h in hits]
    assert ids == ["basic-verbs"]
    assert all(h.unit_type == "group" for h in hits)


def test_lexical_search_with_types_sentence_and_group_runs_both(
    tmp_path: Path,
) -> None:
    """``lexical_search`` with ``types=["sentence", "group"]`` runs
    both rankers. The hanzi of the seeded sentence is empty (no
    Jaccard overlap possible), so the group hit is the only survivor
    — but the test confirms the group ranker DID run (rather than
    returning ``[]`` because ``"sentence" in selected`` blocked it)."""
    _seed_groups(
        [_make_group("basic-verbs", display_name="Basic Verbs")],
        tmp_path,
    )

    hits = lexical_search(
        str(tmp_path), "verb", types=["sentence", "group"]
    )
    assert any(h.unit_type == "group" for h in hits)


# ---------------------------------------------------------------------------
# 3. Route-level — ``?types=group``
# ---------------------------------------------------------------------------


def test_route_types_group_returns_only_groups(
    client: TestClient, tmp_path: Path
) -> None:
    """``?types=group`` returns only group units, no sentences or
    words — even when those would otherwise match the query."""
    # Sentence with a matching slug-like id (irrelevant to lexical
    # because hanzi is empty, but the test asserts the route filters
    # by type, not by score).
    sentence = {
        "id": "s-verb",
        "type": "sentence",
        "name": "verb",
        "properties": {
            "hanzi": "verb",
            "pinyin": "verb",
            "english": "",
            "meaning": "",
            "words": [],
            "word_refs": [],
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-27",
        "updated": "2026-06-27",
        "author_confirmed": True,
    }
    write_unit(str(tmp_path), sentence)
    _seed_groups(
        [_make_group("basic-verbs", display_name="Basic Verbs")],
        tmp_path,
    )

    resp = client.get("/api/search", params={"q": "verb", "types": "group"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "verb"
    types = {item["type"] for item in body["results"]}
    assert types == {"group"}
    ids = [item["id"] for item in body["results"]]
    assert ids == ["basic-verbs"]
    # The kind is recorded as "lexical" because the group ranker
    # runs through the lexical pass (T23 wires it there).
    assert body["results"][0]["kinds"] == ["lexical"]


def test_route_types_sentence_and_group_returns_union(
    client: TestClient, tmp_path: Path
) -> None:
    """``?types=sentence,group`` returns the union of sentence and
    group hits — the group hit always appears, and the sentence
    hit appears when it has overlapping hanzi with the query."""
    # Sentence whose hanzi is "verb" matches the query via Jaccard.
    sentence = {
        "id": "s-verb",
        "type": "sentence",
        "name": "verb",
        "properties": {
            "hanzi": "verb",
            "pinyin": "verb",
            "english": "",
            "meaning": "",
            "words": [],
            "word_refs": [],
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-27",
        "updated": "2026-06-27",
        "author_confirmed": True,
    }
    write_unit(str(tmp_path), sentence)
    _seed_groups(
        [_make_group("basic-verbs", display_name="Basic Verbs")],
        tmp_path,
    )

    resp = client.get(
        "/api/search", params={"q": "verb", "types": "sentence,group"}
    )
    assert resp.status_code == 200, resp.text
    types = {item["type"] for item in resp.json()["results"]}
    assert types == {"sentence", "group"}


def test_route_types_group_no_matches_returns_empty(
    client: TestClient, tmp_path: Path
) -> None:
    """``?types=group`` with no matching groups returns ``[]``
    (and the response stays 200)."""
    _seed_groups(
        [_make_group("foods", display_name="Common Foods")],
        tmp_path,
    )

    resp = client.get(
        "/api/search", params={"q": "kitchen", "types": "group"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"query": "kitchen", "results": []}


def test_route_unknown_type_returns_422(client: TestClient) -> None:
    """An unknown type value (``"foo"``) returns 422 rather than
    silently dropping the request — the same fail-loud contract
    T20 established for unknown types."""
    resp = client.get(
        "/api/search", params={"q": "anything", "types": "foo"}
    )
    assert resp.status_code == 422


def test_route_default_types_searches_all_three(
    client: TestClient, tmp_path: Path
) -> None:
    """When ``?types`` is omitted, the route searches across all
    three types (sentence, word, group). With no FAISS index the
    semantic pass is empty, but the lexical pass should hit the
    group."""
    _seed_groups(
        [_make_group("basic-verbs", display_name="Basic Verbs")],
        tmp_path,
    )

    resp = client.get("/api/search", params={"q": "verb"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = {item["type"] for item in body["results"]}
    # Default scope includes groups; we can't assert sentence/word
    # here because the vault has none, but the group hit MUST
    # surface so we know the default ran the group ranker.
    assert "group" in types


# ---------------------------------------------------------------------------
# 4. Route-level — group hit response shape
# ---------------------------------------------------------------------------


def test_route_group_hit_response_shape(
    client: TestClient, tmp_path: Path
) -> None:
    """A group hit's response row has ``name`` = display_name and
    ``snippet`` = slug id, with ``kinds`` including ``"lexical"``."""
    _seed_groups(
        [_make_group("basic-verbs", display_name="Basic Verbs")],
        tmp_path,
    )

    resp = client.get("/api/search", params={"q": "verb"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["results"]) == 1
    row = body["results"][0]
    assert row["id"] == "basic-verbs"
    assert row["type"] == "group"
    assert row["name"] == "Basic Verbs"
    assert row["snippet"] == "basic-verbs"
    assert row["kinds"] == ["lexical"]
    # Score is in (0, 1.1] — the prefix bonus can push it slightly
    # above 1.0 for exact-prefix hits.
    assert 0.0 < row["score"] <= 1.1


def test_route_group_hit_no_natural_english(
    client: TestClient, tmp_path: Path
) -> None:
    """For every group hit, ``name`` and ``snippet`` carry no
    natural-language English (AC21). The slug id is the hit's
    snippet — slugs that are purely numeric or contain hanzi
    trivially pass AC21. We use a numeric slug here so the test
    is forward-compat with the SPEC's intent."""
    _seed_groups(
        [
            _make_group("g-001", display_name=""),
            _make_group("g-002", display_name=""),
        ],
        tmp_path,
    )

    resp = client.get("/api/search", params={"q": "g-"})
    assert resp.status_code == 200, resp.text
    for item in resp.json()["results"]:
        # AC21 helper from the service module — single source of truth.
        assert not has_natural_language_english(item["name"]), (
            f"name {item['name']!r} leaked natural English"
        )
        assert not has_natural_language_english(item["snippet"]), (
            f"snippet {item['snippet']!r} leaked natural English"
        )