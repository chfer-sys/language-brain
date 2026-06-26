"""Tests for ``GET /api/search`` — SPEC §5.3, §6 AC16/AC20/AC21 (T20).

T20 covers the lexical ranker only: tokenize the query, score every
sentence and word unit by Jaccard similarity over hanzi tokens, sort
by score desc (tie-break by id asc), and respect the ``limit`` and
``types`` query parameters. The AC20 (``english``/``meaning``
hygiene) and AC21 (no ASCII a-z runs of length 3+ in ``name`` or
``snippet``) invariants are tested early here because T20 already
satisfies them — the response only exposes ``name=hanzi`` and
``snippet=pinyin``, neither of which can leak English.

Setup
-----
Uses FastAPI's :class:`TestClient`. Each test isolates its vault under
``tmp_path`` and monkey-patches :func:`api.config.settings.vault` so
the route reads from a temp vault, mirroring the pattern in
``test_commit_sentence_route.py``.

Seeding strategy
----------------
We bypass the ``/api/sentences/commit`` route and write unit files
directly via :func:`api.services.unit_writer.write_unit`. The
commit route does too much (it also runs the connector and the
FAISS index) and would couple each search test to that behavior;
direct writes are clearer and faster.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import config as config_module
from api.main import app
from api.services.search import (
    SearchHit,
    has_english_or_meaning_key,
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

    Mirrors the pattern from ``test_commit_sentence_route.py``:
    clear the ``get_settings`` lru_cache, set the env var, and
    patch the module-level singleton so the route module (which
    imports ``settings`` directly) reads from ``tmp_path``.
    """
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        config_module.get_settings.cache_clear()


def _make_sentence(
    unit_id: str,
    hanzi: str,
    pinyin: str = "",
    english: str = "",
    meaning: str = "",
) -> dict[str, Any]:
    """Build a minimal sentence unit dict ready for :func:`write_unit`.

    The unit's ``name`` is the hanzi (matching SPEC §2.1 and the
    T19 commit route). ``properties.pinyin`` defaults to the
    ``unit_id`` if not supplied, which is enough for the search
    tests — we only assert that ``snippet`` equals
    ``properties.pinyin`` at the end.
    """
    return {
        "id": unit_id,
        "type": "sentence",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin or unit_id,
            "english": english,
            "meaning": meaning,
            "words": [],
            "word_refs": [],
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-26",
        "updated": "2026-06-26",
        "author_confirmed": True,
    }


def _make_word(
    unit_id: str,
    hanzi: str,
    pinyin: str = "",
    english: str = "",
    meaning: str = "",
) -> dict[str, Any]:
    """Build a minimal word unit dict ready for :func:`write_unit`."""
    return {
        "id": unit_id,
        "type": "word",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin or unit_id,
            "english": english,
            "meaning": meaning,
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-26",
        "updated": "2026-06-26",
        "author_confirmed": True,
    }


def _seed(units: list[dict[str, Any]], tmp_path: Path) -> None:
    """Write a list of unit dicts to ``tmp_path`` via :func:`write_unit`."""
    for unit in units:
        write_unit(str(tmp_path), unit)


# ---------------------------------------------------------------------------
# 1. Empty query
# ---------------------------------------------------------------------------


def test_lexical_search_empty_query_returns_empty(
    client: TestClient, tmp_path: Path
) -> None:
    """An empty ``q`` returns 200 with ``results=[]``.

    The route uses ``min_length=1`` so a truly empty string is
    caught by Pydantic as 422; a whitespace-only string passes
    the route but tokenizes to ``[]`` at the service layer and
    returns ``[]`` (no lexical matches possible).
    """
    resp = client.get("/api/search", params={"q": "   "})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"query": "   ", "results": []}


def test_lexical_search_missing_q_returns_422(client: TestClient) -> None:
    """A request with no ``q`` parameter is rejected at the route."""
    resp = client.get("/api/search")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 2. No matches
# ---------------------------------------------------------------------------


def test_lexical_search_no_matches_returns_empty(
    client: TestClient, tmp_path: Path
) -> None:
    """Disjoint tokens produce no hits."""
    _seed(
        [
            _make_sentence("s1", "我喜欢"),
            _make_sentence("s2", "她走了"),
        ],
        tmp_path,
    )

    # Query is ASCII letters, completely disjoint from the hanzi
    # characters in the seeded sentences — Jaccard is 0 across all.
    resp = client.get("/api/search", params={"q": "abcdef"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "abcdef"
    assert body["results"] == []


# ---------------------------------------------------------------------------
# 3. Shared tokens surface hits
# ---------------------------------------------------------------------------


def test_lexical_search_finds_sentences_with_shared_tokens(
    client: TestClient, tmp_path: Path
) -> None:
    """Two sentences sharing a token with the query both appear."""
    _seed(
        [
            _make_sentence("a", "我喜欢吃"),
            _make_sentence("b", "你吃了吗"),
        ],
        tmp_path,
    )

    # Query tokens: {吃} — Jaccard with each 4-token sentence is 1/4.
    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["query"] == "吃"
    assert len(body["results"]) == 2
    by_id = {item["id"]: item for item in body["results"]}
    assert by_id["a"]["score"] == pytest.approx(1 / 4)
    assert by_id["b"]["score"] == pytest.approx(1 / 4)
    assert by_id["a"]["type"] == "sentence"
    assert by_id["a"]["name"] == "我喜欢吃"
    assert by_id["a"]["snippet"] == "a"


# ---------------------------------------------------------------------------
# 4. Ranking by Jaccard descending
# ---------------------------------------------------------------------------


def test_lexical_search_ranks_by_jaccard_descending(
    client: TestClient, tmp_path: Path
) -> None:
    """A sentence with more overlap with the query ranks higher."""
    # tokenize_sentence splits per-character:
    # query "我喜欢吃" -> {我, 喜, 欢, 吃}        (4 tokens)
    # s_a   "我喜欢吃" -> {我, 喜, 欢, 吃}        (4 tokens) Jaccard = 4/4  = 1.0
    # s_b   "我吃"     -> {我, 吃}                (2 tokens) Jaccard = 2/4  = 0.5
    # s_c   "吃"       -> {吃}                    (1 token)  Jaccard = 1/4  = 0.25
    _seed(
        [
            _make_sentence("s_a", "我喜欢吃"),
            _make_sentence("s_b", "我吃"),
            _make_sentence("s_c", "吃"),
        ],
        tmp_path,
    )

    resp = client.get("/api/search", params={"q": "我喜欢吃"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = [item["id"] for item in body["results"]]
    assert ids == ["s_a", "s_b", "s_c"]
    scores = [item["score"] for item in body["results"]]
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.5)
    assert scores[2] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# 5. Words are included
# ---------------------------------------------------------------------------


def test_lexical_search_finds_words_too(
    client: TestClient, tmp_path: Path
) -> None:
    """A word unit that shares a token with the query appears with type='word'."""
    _seed(
        [
            _make_word("chī", "吃", pinyin="chī"),
            _make_sentence("s1", "我喜欢吃"),
        ],
        tmp_path,
    )

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = {item["type"] for item in body["results"]}
    assert types == {"sentence", "word"}
    word_hit = next(item for item in body["results"] if item["type"] == "word")
    assert word_hit["id"] == "chī"
    assert word_hit["name"] == "吃"
    assert word_hit["snippet"] == "chī"
    assert word_hit["score"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 6. ``types`` filter
# ---------------------------------------------------------------------------


def test_lexical_search_respects_types_filter(
    client: TestClient, tmp_path: Path
) -> None:
    """``types`` restricts the result set to the listed unit types."""
    _seed(
        [
            _make_word("chī", "吃", pinyin="chī"),
            _make_sentence("s1", "我喜欢吃"),
        ],
        tmp_path,
    )

    sentence_only = client.get(
        "/api/search", params={"q": "吃", "types": "sentence"}
    )
    assert sentence_only.status_code == 200, sentence_only.text
    types_sentence = {item["type"] for item in sentence_only.json()["results"]}
    assert types_sentence == {"sentence"}

    word_only = client.get("/api/search", params={"q": "吃", "types": "word"})
    assert word_only.status_code == 200, word_only.text
    types_word = {item["type"] for item in word_only.json()["results"]}
    assert types_word == {"word"}

    both = client.get(
        "/api/search", params={"q": "吃", "types": "sentence,word"}
    )
    assert both.status_code == 200, both.text
    types_both = {item["type"] for item in both.json()["results"]}
    assert types_both == {"sentence", "word"}


def test_lexical_search_types_filter_rejects_unknown_value(
    client: TestClient,
) -> None:
    """An unknown ``types`` value returns 422, not a silent empty list.

    ``group`` is now a valid type (added in T23), so we use a clearly
    bogus value here instead.
    """
    resp = client.get("/api/search", params={"q": "吃", "types": "bogus"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 7. ``limit`` parameter
# ---------------------------------------------------------------------------


def test_lexical_search_respects_limit(
    client: TestClient, tmp_path: Path
) -> None:
    """Five matching sentences, ``limit=2`` returns exactly two."""
    sentences = [_make_sentence(f"s{i}", "我喜欢吃") for i in range(5)]
    # Differentiate ids so the ranker produces five distinct hits
    # (the hanzi are identical; the ranker dedupes by id, so we
    # need different ids to get five results).
    for i, s in enumerate(sentences):
        s["id"] = f"s{i}"
    _seed(sentences, tmp_path)

    resp = client.get(
        "/api/search", params={"q": "我喜欢吃", "limit": 2}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["results"]) == 2


def test_lexical_search_limit_out_of_range_rejected(client: TestClient) -> None:
    """A ``limit`` outside ``[1, 100]`` returns 422."""
    too_small = client.get(
        "/api/search", params={"q": "吃", "limit": 0}
    )
    assert too_small.status_code == 422

    too_large = client.get(
        "/api/search", params={"q": "吃", "limit": 101}
    )
    assert too_large.status_code == 422


# ---------------------------------------------------------------------------
# 8. Deduplication by id
# ---------------------------------------------------------------------------


def test_lexical_search_deduplicates_by_id(
    client: TestClient, tmp_path: Path
) -> None:
    """A sentence with id X appears at most once even if enumerated twice.

    The vault can only carry one unit per id per type, so this is
    a defense-in-depth test: even if the ranker somehow saw the
    same id twice (e.g. via a future caller that lists both
    sentences and words with overlapping ids), the public entry
    point must dedupe. We exercise this through the pure ranker
    directly rather than through the I/O layer because the I/O
    layer cannot produce duplicates from a single vault.
    """
    from api.services.search import lexical_rank

    sentences = [
        {"id": "x", "type": "sentence", "properties": {"hanzi": "我喜欢吃"}},
        {"id": "x", "type": "sentence", "properties": {"hanzi": "我喜欢吃"}},
    ]
    words = [
        {"id": "x", "type": "word", "properties": {"hanzi": "我喜欢吃"}},
    ]

    ranked = lexical_rank(["我"], sentences, words)
    ids = [r[0] for r in ranked]
    assert ids.count("x") == 1


# ---------------------------------------------------------------------------
# 9. Skip empty-hanzi sentences
# ---------------------------------------------------------------------------


def test_lexical_search_skips_empty_hanzi_sentences(
    client: TestClient, tmp_path: Path
) -> None:
    """A sentence with ``properties.hanzi=""`` is skipped."""
    _seed(
        [
            _make_sentence("empty", ""),
            _make_sentence("real", "吃"),
        ],
        tmp_path,
    )

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    ids = [item["id"] for item in resp.json()["results"]]
    assert ids == ["real"]


# ---------------------------------------------------------------------------
# 10. Pure-function call works directly
# ---------------------------------------------------------------------------


def test_lexical_search_pure_function_no_io(
    tmp_path: Path,
) -> None:
    """``lexical_search`` works when called directly with ``tmp_path``."""
    _seed(
        [
            _make_sentence("s_a", "我喜欢吃"),
            _make_sentence("s_b", "我吃"),
        ],
        tmp_path,
    )

    hits = lexical_search(str(tmp_path), "我喜欢吃")
    assert isinstance(hits, list)
    assert all(isinstance(h, SearchHit) for h in hits)
    # Jaccard-desc ordering: s_a (full overlap) ahead of s_b (partial).
    assert [h.unit_id for h in hits] == ["s_a", "s_b"]
    assert hits[0].score == pytest.approx(1.0)
    assert hits[0].unit_type == "sentence"
    assert hits[0].name == "我喜欢吃"


# ---------------------------------------------------------------------------
# 11. AC20 — no ``english`` / ``meaning`` keys in payload
# ---------------------------------------------------------------------------


def test_response_never_contains_english_or_meaning_keys(
    client: TestClient, tmp_path: Path
) -> None:
    """No dict in the response payload has an ``english`` or ``meaning`` key.

    T20 already satisfies AC20 because the route only copies
    ``id``, ``type``, ``name``, ``snippet``, ``kinds``, and
    ``score`` from each :class:`SearchHit`. This test pins that
    invariant so T24's payload audit can compose on a green base.
    """
    _seed(
        [
            _make_sentence("s1", "我喜欢吃", english="I like to eat"),
            _make_word("chī", "吃", pinyin="chī", english="to eat"),
        ],
        tmp_path,
    )

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    assert not has_english_or_meaning_key(resp.json()), (
        "search payload leaked an 'english' or 'meaning' key"
    )


# ---------------------------------------------------------------------------
# 12. ``name`` is hanzi, ``snippet`` is pinyin
# ---------------------------------------------------------------------------


def test_response_name_is_hanzi_snippet_is_pinyin(
    client: TestClient, tmp_path: Path
) -> None:
    """For sentences and words, ``name == properties.hanzi`` and
    ``snippet == properties.pinyin``."""
    _seed(
        [
            _make_sentence("s1", "我喜欢吃", pinyin="wǒ xǐhuān chī"),
            _make_word("chī", "吃", pinyin="chī"),
        ],
        tmp_path,
    )

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    sentence_hit = next(
        item for item in body["results"] if item["type"] == "sentence"
    )
    assert sentence_hit["name"] == "我喜欢吃"
    assert sentence_hit["snippet"] == "wǒ xǐhuān chī"

    word_hit = next(
        item for item in body["results"] if item["type"] == "word"
    )
    assert word_hit["name"] == "吃"
    assert word_hit["snippet"] == "chī"


# ---------------------------------------------------------------------------
# 13. AC21 — no natural-language English in ``name`` or ``snippet``
# ---------------------------------------------------------------------------


def test_response_no_natural_english_in_name_or_snippet(
    client: TestClient, tmp_path: Path
) -> None:
    """For every hit, ``name`` and ``snippet`` contain no ASCII
    a-z run of length >= 3 (per AC21)."""
    _seed(
        [
            _make_sentence("s1", "我喜欢吃", pinyin="wǒ xǐhuān chī"),
            _make_word("chī", "吃", pinyin="chī"),
        ],
        tmp_path,
    )

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text

    for item in resp.json()["results"]:
        assert not has_natural_language_english(item["name"]), (
            f"name {item['name']!r} leaked natural English"
        )
        assert not has_natural_language_english(item["snippet"]), (
            f"snippet {item['snippet']!r} leaked natural English"
        )


# ---------------------------------------------------------------------------
# Auxiliary tests for the hygiene helpers themselves (cheap unit tests)
# ---------------------------------------------------------------------------


def test_helpers_detect_ascii_runs() -> None:
    """``has_natural_language_english`` catches 3+ ASCII letter runs."""
    assert has_natural_language_english("hello world") is True
    assert has_natural_language_english("the quick brown fox") is True
    # Pinyin with accented vowels is fine — no ASCII a-z run of 3+.
    assert has_natural_language_english("wǒ xǐhuān chī") is False
    # A 2-letter ASCII run is below the threshold.
    assert has_natural_language_english("le ma") is False
    # Empty / non-string inputs are safe.
    assert has_natural_language_english("") is False
    assert has_natural_language_english(None) is False  # type: ignore[arg-type]


def test_helpers_detect_forbidden_keys() -> None:
    """``has_english_or_meaning_key`` walks nested structures."""
    payload = {
        "query": "吃",
        "results": [
            {"id": "x", "type": "sentence", "name": "我喜欢吃", "score": 0.5},
        ],
    }
    assert has_english_or_meaning_key(payload) is False

    leaked = {
        "results": [{"english": "I like to eat"}],
    }
    assert has_english_or_meaning_key(leaked) is True

    nested = {
        "results": [
            {"nested": {"meaning": "expressing enjoyment"}},
        ],
    }
    assert has_english_or_meaning_key(nested) is True

    # Lists of dicts work too.
    assert has_english_or_meaning_key([{"english": "x"}]) is True
    assert has_english_or_meaning_key([]) is False