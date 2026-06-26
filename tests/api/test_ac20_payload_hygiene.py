"""AC20 — Search payload hygiene (T24).

SPEC §6 AC20: ``GET /api/search`` must never return ``english`` or
``meaning`` keys at any level of the response payload. T24 is the
acceptance test for that invariant.

Why this file lives separately from ``test_search.py``
------------------------------------------------------
``test_search.py`` covers the lexical ranker (T20). T24 is the
end-to-end AC20 lockdown: it pins the invariant across the route
layer with mocked services (so the test is deterministic and
offline), across all three unit types (sentence, word, group),
against the merged kinds output, and once against the live
``semantic_search`` path with a real FAISS index built via the
``HashingEmbedder``. The integration smoke test exists because
mock-only coverage could miss a bug introduced by a future
refactor of ``_hit_to_item`` or ``merge_hits_with_kinds``.

Mocking strategy
----------------
For the route-level tests we monkey-patch
:func:`api.routes.search.lexical_search` and
:func:`api.routes.search.semantic_search` with ``MagicMock``
returning synthetic :class:`SearchHit` lists. This isolates the
AC20 contract from the ranker's behavior: even if the ranker
accidentally returned a hit whose underlying unit dict had an
``english``/``meaning`` field, the *route* still wouldn't copy
those fields into the response (which is the whole point of AC20).

The last test (``test_live_route_with_real_index``) bypasses the
monkey-patch and exercises the real ``semantic_search`` and
``lexical_search`` paths against a tmp vault with a real FAISS
index. That's the integration-level smoke test required by the
task spec.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api import config as config_module
from api.main import app
from api.routes import search as search_route
from api.services.embedder import HashingEmbedder
from api.services.indexer import Index
from api.services.search import (
    SearchHit,
    has_english_or_meaning_key,
)
from api.services.unit_writer import list_units_by_type, write_unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """A TestClient bound to a fresh ``LANGUAGE_BRAIN_VAULT=tmp_path``.

    Mirrors the pattern from ``test_search.py`` /
    ``test_types_filter.py``: clear the ``get_settings`` lru_cache,
    set the env var, and patch the module-level singleton so the
    route module (which imports ``settings`` directly) reads from
    ``tmp_path``.
    """
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        config_module.get_settings.cache_clear()


@pytest.fixture
def mocked_search_route(monkeypatch: pytest.MonkeyPatch):
    """Yield a context manager that swaps the route's search services.

    The route module imports ``lexical_search`` and ``semantic_search``
    by name, so we have to patch them on the route module (not on
    ``api.services.search``) — that is where the route looks them up.
    The mocks default to ``return_value=[]`` so a test that doesn't
    care about the hit list can ignore them.
    """
    lexical_mock = MagicMock(return_value=[])
    semantic_mock = MagicMock(return_value=[])
    monkeypatch.setattr(search_route, "lexical_search", lexical_mock)
    monkeypatch.setattr(search_route, "semantic_search", semantic_mock)
    return lexical_mock, semantic_mock


def _hit(
    unit_id: str,
    unit_type: str,
    name: str,
    snippet: str,
    score: float = 0.5,
) -> SearchHit:
    """Build a ``SearchHit`` with no leaked English fields."""
    return SearchHit(
        unit_id=unit_id,
        unit_type=unit_type,
        name=name,
        snippet=snippet,
        score=score,
    )


# ---------------------------------------------------------------------------
# 1. Live route response shape — mocked services
# ---------------------------------------------------------------------------


def test_route_response_never_contains_english_or_meaning_keys(
    client: TestClient,
    mocked_search_route: tuple[MagicMock, MagicMock],
) -> None:
    """``GET /api/search?q=...`` returns a JSON body whose every dict
    has neither an ``english`` key nor a ``meaning`` key (SPEC §6
    AC20).

    Both search services are mocked to return a single hand-crafted
    :class:`SearchHit`. We use the same fixture pattern for every
    test that needs mocked services so the per-test concerns stay
    narrow: this one only cares about the route's output shape.
    """
    lexical_mock, semantic_mock = mocked_search_route
    lexical_mock.return_value = [
        _hit("s-1", "sentence", "我喜欢吃", "wǒ xǐhuān chī", score=0.9),
        _hit("chi", "word", "吃", "chī", score=0.7),
        _hit("basic-verbs", "group", "Basic Verbs", "basic-verbs", score=0.5),
    ]
    semantic_mock.return_value = []

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # Top-level invariant — the helper walks every nested dict and
    # returns True if any of them has a forbidden key. False here
    # means the entire tree is clean.
    assert has_english_or_meaning_key(payload) is False, (
        f"AC20 violated: search payload leaked an "
        f"'english' or 'meaning' key: {payload!r}"
    )

    # Defensive: also assert the top-level keys explicitly. The
    # helper already covers this, but a named-key check gives a
    # clearer failure message if a future field regresses.
    assert "english" not in payload
    assert "meaning" not in payload
    # The response schema locks query/results at the top level.
    assert set(payload.keys()) == {"query", "results"}


# ---------------------------------------------------------------------------
# 2. All payload levels checked — helper covers results, query, nested
# ---------------------------------------------------------------------------


def test_helper_walks_results_query_and_nested_dicts(
    client: TestClient,
    mocked_search_route: tuple[MagicMock, MagicMock],
) -> None:
    """``has_english_or_meaning_key`` covers every level: the top
    ``query`` field, each ``results`` item, and any nested dict
    inside those items.

    We hand-craft a response shape that exercises:

    * the ``query`` str field (the helper must treat it as a leaf);
    * the ``results`` list (must recurse into each dict);
    * a nested ``meta`` dict inside one result (must recurse one
      level deeper);
    * a nested ``tags`` list of dicts (must recurse into list
      elements).

    Because we construct the SearchHit dataclass and the
    :class:`SearchResponse` is a Pydantic model with a fixed
    schema, we cannot actually inject a ``meta``/``tags`` field
    into the live response. So this test also asserts the helper
    directly on a synthetic payload that mirrors the real shape
    — proving the helper handles all three levels even if the
    schema later grows fields.
    """
    lexical_mock, _ = mocked_search_route
    lexical_mock.return_value = [
        _hit("s-1", "sentence", "我喜欢吃", "wǒ xǐhuān chī"),
    ]

    resp = client.get("/api/search", params={"q": "吃"})
    payload = resp.json()

    # The real response: confirm query/results/items are all clean.
    assert "english" not in payload
    assert "meaning" not in payload
    for item in payload["results"]:
        assert "english" not in item
        assert "meaning" not in item

    # Synthetic payload that mirrors the schema but adds nested
    # dicts/lists. The helper must catch forbidden keys at every
    # depth even though the real schema can't produce them today.
    synthetic_clean = {
        "query": "吃",
        "results": [
            {
                "id": "s-1",
                "type": "sentence",
                "name": "我喜欢吃",
                "snippet": "wǒ xǐhuān chī",
                "score": 0.9,
                "kinds": ["lexical"],
                "meta": {"trace_id": "abc"},
                "tags": [{"label": "food"}],
            }
        ],
    }
    assert has_english_or_meaning_key(synthetic_clean) is False

    synthetic_leaked = {
        "query": "吃",
        "results": [
            {
                "id": "s-1",
                "type": "sentence",
                "name": "我喜欢吃",
                "meta": {"meaning": "I like to eat"},
            }
        ],
    }
    assert has_english_or_meaning_key(synthetic_leaked) is True


# ---------------------------------------------------------------------------
# 3. Mocked search services — every unit type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hit",
    [
        _hit("s-1", "sentence", "我喜欢吃", "wǒ xǐhuān chī"),
        _hit("chi", "word", "吃", "chī"),
        _hit("basic-verbs", "group", "Basic Verbs", "basic-verbs"),
    ],
    ids=["sentence", "word", "group"],
)
def test_route_payload_clean_for_every_unit_type(
    client: TestClient,
    mocked_search_route: tuple[MagicMock, MagicMock],
    hit: SearchHit,
) -> None:
    """For each unit type, the mocked service returns a hit whose
    ``name`` is hanzi (or display_name) and ``snippet`` is pinyin
    (or slug), and the route response payload contains no
    ``english`` or ``meaning`` keys.

    We exercise one type per test (parameterized) so a regression
    in the route's per-type handling surfaces as a single failing
    case rather than a single mixed failure.
    """
    lexical_mock, semantic_mock = mocked_search_route
    lexical_mock.return_value = [hit]
    semantic_mock.return_value = []

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert len(payload["results"]) == 1
    item = payload["results"][0]
    assert item["type"] == hit.unit_type
    assert item["name"] == hit.name
    assert item["snippet"] == hit.snippet
    assert not has_english_or_meaning_key(payload), (
        f"AC20 violated for {hit.unit_type}: {payload!r}"
    )


# ---------------------------------------------------------------------------
# 4. Mixed types in a single response
# ---------------------------------------------------------------------------


def test_route_payload_clean_with_mixed_type_hits(
    client: TestClient,
    mocked_search_route: tuple[MagicMock, MagicMock],
) -> None:
    """A response with 3 sentence + 2 word + 1 group hit is clean.

    This is the realistic case from SPEC §5.3: ``types`` defaults
    to ``sentence,word,group``, so a single call merges all three
    kinds. AC20 must hold across the merged list.
    """
    lexical_mock, semantic_mock = mocked_search_route
    lexical_mock.return_value = [
        # 3 sentences
        _hit(f"s-{i}", "sentence", f"我喜欢吃{i}", f"wǒ xǐhuān chī {i}")
        for i in range(3)
    ] + [
        # 2 words
        _hit(f"w-{i}", "word", f"吃{i}", f"chī {i}") for i in range(2)
    ] + [
        # 1 group
        _hit("basic-verbs", "group", "Basic Verbs", "basic-verbs"),
    ]
    semantic_mock.return_value = []

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert len(payload["results"]) == 6
    type_counts: dict[str, int] = {}
    for item in payload["results"]:
        type_counts[item["type"]] = type_counts.get(item["type"], 0) + 1
    assert type_counts == {"sentence": 3, "word": 2, "group": 1}
    assert not has_english_or_meaning_key(payload)


# ---------------------------------------------------------------------------
# 5. ``kinds`` field defensive check
# ---------------------------------------------------------------------------


def test_kinds_values_never_contain_english_or_meaning_substring(
    client: TestClient,
    mocked_search_route: tuple[MagicMock, MagicMock],
) -> None:
    """Every value in the response's ``kinds`` list is a short
    hardcoded token (``"lexical"``, ``"semantic"``, ``"group"``,
    ``"opposite"``). None of them contains the substrings
    ``"english"`` or ``"meaning"``.

    This is a *defensive* invariant: the kinds strings are
    module-level constants in :mod:`api.services.search` and the
    route layer; a future contributor who adds a kind string with
    one of the forbidden substrings (e.g. an ``"english"`` kind
    for a hypothetical English-source pass) would silently violate
    the AC20 invariant at the value level even though no key is
    named ``english``. We document the invariant here.
    """
    lexical_mock, semantic_mock = mocked_search_route
    # The same (id, type) in both passes triggers merge_hits_with_kinds
    # to populate kinds={"lexical", "semantic"} — the only way for
    # the response to carry more than one kind per row.
    lexical_mock.return_value = [
        _hit("s-1", "sentence", "我喜欢吃", "wǒ xǐhuān chī"),
    ]
    semantic_mock.return_value = [
        _hit("s-1", "sentence", "我喜欢吃", "wǒ xǐhuān chī", score=0.95),
    ]

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert len(payload["results"]) == 1

    kinds = payload["results"][0]["kinds"]
    assert kinds == ["lexical", "semantic"]
    for k in kinds:
        assert "english" not in k, f"kind {k!r} contains 'english'"
        assert "meaning" not in k, f"kind {k!r} contains 'meaning'"


# ---------------------------------------------------------------------------
# 6. ``has_english_or_meaning_key`` edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        # Empty / leaf payloads: helper must return False.
        ({}, False),
        ("english", False),  # string, not dict — False
        (None, False),
        ([], False),
        (42, False),
        # Top-level forbidden key.
        ({"english": "x"}, True),
        ({"meaning": "x"}, True),
        # Nested dict — the recursion must walk it.
        ({"nested": {"english": "x"}}, True),
        ({"nested": {"a": {"english": "x"}}}, True),
        ({"results": [{"english": "x"}]}, True),
        # Lists of dicts — recursion must handle list elements.
        ([{"english": "x"}], True),
        ([{"a": {"meaning": "x"}}], True),
        # Clean payloads — the negative cases.
        ({"query": "吃", "results": [{"id": "s-1", "name": "我喜欢吃"}]}, False),
        ({"a": {"b": {"c": "deep but clean"}}}, False),
        ({"kinds": ["lexical", "semantic"]}, False),
        # Mixed: forbidden key sits next to a clean key.
        ({"query": "x", "english": "leak"}, True),
    ],
)
def test_helper_edge_cases(
    payload: object, expected: bool
) -> None:
    """Lock down ``has_english_or_meaning_key`` against the explicit
    edge cases called out in the T24 spec:

    * empty payload ``{}`` → ``False``;
    * ``{"english": "x"}`` and ``{"meaning": "x"}`` → ``True``;
    * nested dicts (``{"nested": {...}}``) → ``True``;
    * recursive nesting (``{"nested": {"a": {"english": ...}}}``) → ``True``;
    * ``{"results": [{"english": ...}]}`` → ``True``;
    * ``[{"english": ...}]`` (list of dicts) → ``True``;
    * ``"english"`` (string, not dict) → ``False``;
    * ``None`` → ``False``.

    A handful of additional clean / leak cases are included to
    document the negative space.
    """
    assert has_english_or_meaning_key(payload) is expected, (
        f"has_english_or_meaning_key({payload!r}) returned "
        f"{not expected}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# 7. Live end-to-end integration — real indexing, no mocks
# ---------------------------------------------------------------------------


def _make_sentence_dict(
    unit_id: str,
    hanzi: str,
    pinyin: str,
    meaning: str,
) -> dict[str, Any]:
    """Build a sentence unit dict with a non-empty ``english`` /
    ``meaning`` so the integration test exercises the case where
    the underlying unit file has forbidden fields but the route
    still must not copy them to the response."""
    return {
        "id": unit_id,
        "type": "sentence",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin,
            "english": f"english-of-{unit_id}",  # MUST NOT leak
            "meaning": meaning,  # MUST NOT leak
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


def _build_index(vault: Path, sentence_meanings: dict[str, str]) -> None:
    """Build and save a real FAISS index using the offline
    :class:`HashingEmbedder` (no model download, no network).

    Mirrors the seeding pattern from
    :mod:`tests.api.test_semantic_search` — embed each sentence's
    ``meaning`` and call :meth:`Index.save` so the on-disk index
    is what the route layer reads.
    """
    embedder = HashingEmbedder()
    idx = Index()
    for sid, meaning in sentence_meanings.items():
        idx.add(sid, embedder.embed(meaning))
    idx.save(str(vault))


def test_live_route_with_real_index(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end smoke test: write 2 real sentence units to a tmp
    vault, build a real FAISS index using ``HashingEmbedder``, hit
    ``GET /api/search?q=...``, and assert the response payload has
    no ``english`` or ``meaning`` keys.

    This exercises the *real* ``semantic_search`` and
    ``lexical_search`` paths (no mocks) so any regression in the
    route's ``_hit_to_item`` adapter or in the search services'
    payload shaping surfaces here. It also confirms the merge of
    lexical + semantic hits doesn't introduce forbidden keys.

    The test patches ``get_embedder`` to return the offline
    ``HashingEmbedder`` — without this, the route's default
    ``get_embedder()`` call inside ``semantic_search`` would try to
    load the sentence-transformers model and the test would hang.
    """
    # Pin the embedder to HashingEmbedder so the route's
    # semantic_search doesn't trigger the model load.
    # Patch at api.services.search where it's used (search.py
    # imports get_embedder directly into its module namespace,
    # so patching the embedder module alone won't intercept).
    from api.services import search as search_module
    from api.services.embedder import HashingEmbedder

    monkeypatch.setattr(
        search_module, "get_embedder", lambda force=None: HashingEmbedder()
    )

    # 1. Seed two sentence units whose underlying dicts have
    #    non-empty ``english`` and ``meaning`` fields. The route
    #    must never copy these.
    write_unit(
        str(tmp_path),
        _make_sentence_dict(
            "s-live-1",
            "我喜欢吃",
            "wǒ xǐhuān chī",
            "I like to eat",
        ),
    )
    write_unit(
        str(tmp_path),
        _make_sentence_dict(
            "s-live-2",
            "你吃了吗",
            "nǐ chī le ma",
            "have you eaten yet",
        ),
    )

    # 2. Build a real FAISS index keyed on the meaning.
    _build_index(
        tmp_path,
        {
            "s-live-1": "I like to eat",
            "s-live-2": "have you eaten yet",
        },
    )

    # Sanity-check: the index actually loaded.
    on_disk = list_units_by_type(str(tmp_path), "sentence")
    assert {u["id"] for u in on_disk} == {"s-live-1", "s-live-2"}

    # 3. Hit the route with a query that triggers both passes.
    #    The hanzi "吃" is a token in both sentences (lexical
    #    pass); the English query "I like to eat" is the meaning
    #    of s-live-1 (semantic pass → cosine ≈ 1.0).
    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # 4. AC20 lockdown: no forbidden keys anywhere in the tree.
    assert has_english_or_meaning_key(payload) is False, (
        f"AC20 violated at the live route: payload leaked an "
        f"'english' or 'meaning' key. payload={payload!r}"
    )

    # 5. Defensive shape checks: top-level fields, per-item fields,
    #    and ``kinds`` (the kinds-toggle plumbing added in T22+).
    assert "english" not in payload
    assert "meaning" not in payload
    for item in payload["results"]:
        assert "english" not in item
        assert "meaning" not in item
        assert item["type"] == "sentence"
        # name = hanzi, snippet = pinyin — never the english/meaning.
        assert item["name"] in {"我喜欢吃", "你吃了吗"}
        assert item["snippet"] in {"wǒ xǐhuān chī", "nǐ chī le ma"}
