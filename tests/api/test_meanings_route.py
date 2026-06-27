"""Tests for ``GET /api/meanings/{text}/sentences`` — SPEC §5.3, §6 AC27c.

T27 wires up the meaning-lookup endpoint that returns sentence
units whose ``meaning`` embedding is semantically similar to the
user's English query. The endpoint is privacy-sensitive: the
query text must not enter the shared log stream and the response
payload must carry no ``english`` or ``meaning`` keys.

Coverage
--------
The cases listed in the T27 task spec are exercised 1:1 below:

1. Empty / whitespace path → 422.
2. Empty index → empty results.
3. Query with no matches above threshold → empty.
4. Query with matches → sorted by score descending.
5. Threshold clamped to [0.0, 1.0]; out-of-range → 422.
6. Limit clamped to [1, 100]; out-of-range → 422.
7. Payload hygiene — no ``english``/``meaning`` keys at any
   level (covers both top-level and per-item checks).
8. Privacy — the route's INFO log does NOT contain the user's
   query text.
9. Live integration — write sentence units with ``meaning``
   fields, build a FAISS index, call the route with an English
   query, and assert a clean response with cosine-similar
   sentences.

Embedder injection mirrors T24/T25/T26: we patch
:func:`api.services.search.get_embedder` to a
:class:`HashingEmbedder` so tests don't pull the real
sentence-transformers model.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import config as config_module
from api.main import app
from api.services.embedder import HashingEmbedder
from api.services.search import (
    has_english_or_meaning_key,
    meanings_search,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> TestClient:
    """A TestClient bound to a fresh ``LANGUAGE_BRAIN_VAULT=tmp_path``.

    Mirrors the pattern in ``test_suggest_endpoint.py`` and
    ``test_semantic_search.py``: clear the settings cache, set
    the env var, and patch the module-level singleton so the
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
def hashing_embedder(monkeypatch: pytest.MonkeyPatch) -> HashingEmbedder:
    """Force the embedder factory to return a :class:`HashingEmbedder`.

    Patches the ``get_embedder`` symbol in
    :mod:`api.services.search`'s module namespace so the service-
    layer ``meanings_search`` call inside the route uses a
    deterministic, dependency-free embedder.

    Why patch ``api.services.search.get_embedder`` and not
    ``api.services.embedder.get_embedder``? Because
    :mod:`api.services.search` imports ``get_embedder`` via
    ``from api.services.embedder import Embedder, get_embedder``
    at module load time. Python's import system binds the name
    in the importer's namespace — patching the original module's
    attribute doesn't update already-imported references. So we
    patch the importer's namespace directly.
    """
    embedder = HashingEmbedder()
    monkeypatch.setattr(
        "api.services.search.get_embedder", lambda: embedder
    )
    return embedder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sentence(
    unit_id: str,
    hanzi: str,
    pinyin: str = "",
    english: str = "",
    meaning: str = "",
) -> dict[str, Any]:
    """Build a minimal sentence unit dict ready for :func:`write_unit`.

    ``english`` and ``meaning`` are populated so the AC20 leak
    check has something to leak if a regression introduced one —
    the route must still scrub them. ``meaning`` is the field the
    FAISS index embeds.
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
        "created": "2026-06-27",
        "updated": "2026-06-27",
        "author_confirmed": True,
    }


def _seed_sentence(
    vault: Path,
    sid: str,
    hanzi: str,
    pinyin: str,
    meaning: str,
    english: str = "(unused by meanings endpoint)",
) -> None:
    """Write a sentence unit file directly to ``vault/units/sentences/``.

    Uses raw JSON writes (instead of :func:`write_unit`) to mirror
    the seeding style in ``test_semantic_search.py``. The two
    approaches are functionally equivalent for these tests.
    """
    out_dir = vault / "units" / "sentences"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{sid}.json").write_text(
        json.dumps(
            _make_sentence(sid, hanzi, pinyin, english, meaning),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _seed_index(vault: Path, sentence_meanings: dict[str, str]) -> None:
    """Build a FAISS index over the given ``{sid: meaning}`` map.

    Uses :class:`HashingEmbedder` so the index is deterministic
    and dependency-free.
    """
    from api.services.indexer import Index

    embedder = HashingEmbedder()
    idx = Index()
    for sid, meaning in sentence_meanings.items():
        idx.add(sid, embedder.embed(meaning))
    idx.save(str(vault))


# ---------------------------------------------------------------------------
# 1. Empty / whitespace path → 422
# ---------------------------------------------------------------------------


def test_meanings_whitespace_only_text_returns_422(
    client: TestClient,
) -> None:
    """A whitespace-only path is rejected by the route's strip+validate.

    ``Path(min_length=1)`` accepts a single space (length 1) but
    the route strips and raises 422 explicitly. This is the SPEC
    AC27c input-validation contract: an empty / meaningless query
    is a 422, not a silent empty list.
    """
    resp = client.get("/api/meanings/%20%20%20/sentences")
    assert resp.status_code == 422, resp.text


def test_meanings_single_space_text_returns_422(
    client: TestClient,
) -> None:
    """A single-space path (the minimum that passes ``min_length=1``)
    is also rejected — the route's whitespace guard catches it."""
    resp = client.get("/api/meanings/%20/sentences")
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 2. Empty index → empty results
# ---------------------------------------------------------------------------


def test_meanings_empty_index_returns_empty_results(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
) -> None:
    """A vault with no units and no FAISS index returns ``results=[]``."""
    # tmp_path is empty by default; no seeding required.
    resp = client.get("/api/meanings/anything/sentences")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"query": "anything", "results": []}


# ---------------------------------------------------------------------------
# 3. Query with no matches above threshold → empty
# ---------------------------------------------------------------------------


def test_meanings_threshold_filters_all_hits(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
    tmp_path: Path,
) -> None:
    """When every hit's cosine is at or below the threshold, the
    response is an empty list. We use threshold=1.0 (impossible
    since cosine ≤ 1.0) to force the filter to drop everything.
    """
    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "a greeting")
    _seed_index(tmp_path, {"s-1": "a greeting"})
    resp = client.get(
        "/api/meanings/a%20greeting/sentences",
        params={"threshold": 1.0},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The exact same input against its own embedding has cosine
    # ≈ 1.0, but the filter is *strict* >, so threshold=1.0
    # drops it.
    assert body == {"query": "a greeting", "results": []}


# ---------------------------------------------------------------------------
# 4. Query with matches → sorted by score descending
# ---------------------------------------------------------------------------


def test_meanings_returns_matches_sorted_descending(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
    tmp_path: Path,
) -> None:
    """Querying with an input that matches its own embedding
    returns that sentence as the top hit with cosine ≈ 1.0.

    The FAISS result is already roughly sorted, but the service
    layer adds an explicit descending sort — so this test pins
    the order even on a single-hit response.
    """
    _seed_sentence(
        tmp_path, "s-1", "你好", "nǐ hǎo", "a casual greeting"
    )
    _seed_sentence(
        tmp_path, "s-2", "再见", "zài jiàn", "a farewell"
    )
    _seed_index(
        tmp_path,
        {"s-1": "a casual greeting", "s-2": "a farewell"},
    )
    resp = client.get(
        "/api/meanings/a%20casual%20greeting/sentences"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "a casual greeting"
    assert len(body["results"]) >= 1
    top = body["results"][0]
    assert top["id"] == "s-1"
    assert top["hanzi"] == "你好"
    assert top["pinyin"] == "nǐ hǎo"
    assert top["score"] == pytest.approx(1.0, abs=1e-5)

    # Sorted descending — scores monotonically non-increasing.
    scores = [item["score"] for item in body["results"]]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 5. Threshold clamping
# ---------------------------------------------------------------------------


def test_meanings_threshold_zero_accepted(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
    tmp_path: Path,
) -> None:
    """``threshold=0.0`` is the lower bound and passes Pydantic."""
    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "a greeting")
    _seed_index(tmp_path, {"s-1": "a greeting"})
    resp = client.get(
        "/api/meanings/anything/sentences",
        params={"threshold": 0.0},
    )
    assert resp.status_code == 200, resp.text


def test_meanings_threshold_one_accepted(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
    tmp_path: Path,
) -> None:
    """``threshold=1.0`` is the upper bound and passes Pydantic."""
    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "a greeting")
    _seed_index(tmp_path, {"s-1": "a greeting"})
    resp = client.get(
        "/api/meanings/a%20greeting/sentences",
        params={"threshold": 1.0},
    )
    assert resp.status_code == 200, resp.text


def test_meanings_threshold_negative_returns_422(
    client: TestClient,
) -> None:
    """``threshold=-0.1`` is below 0.0 and rejected by ``ge=0.0``."""
    resp = client.get(
        "/api/meanings/anything/sentences",
        params={"threshold": -0.1},
    )
    assert resp.status_code == 422


def test_meanings_threshold_above_one_returns_422(
    client: TestClient,
) -> None:
    """``threshold=1.5`` is above 1.0 and rejected by ``le=1.0``."""
    resp = client.get(
        "/api/meanings/anything/sentences",
        params={"threshold": 1.5},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 6. Limit clamping
# ---------------------------------------------------------------------------


def test_meanings_limit_one_accepted(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
    tmp_path: Path,
) -> None:
    """``limit=1`` is the lower bound and passes Pydantic."""
    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "a greeting")
    _seed_index(tmp_path, {"s-1": "a greeting"})
    resp = client.get(
        "/api/meanings/a%20greeting/sentences",
        params={"limit": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["results"]) == 1


def test_meanings_limit_one_hundred_accepted(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
    tmp_path: Path,
) -> None:
    """``limit=100`` is the upper bound and passes Pydantic."""
    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "a greeting")
    _seed_index(tmp_path, {"s-1": "a greeting"})
    resp = client.get(
        "/api/meanings/a%20greeting/sentences",
        params={"limit": 100},
    )
    assert resp.status_code == 200, resp.text


def test_meanings_limit_zero_returns_422(
    client: TestClient,
) -> None:
    """``limit=0`` is below 1 and rejected by ``ge=1``."""
    resp = client.get(
        "/api/meanings/anything/sentences",
        params={"limit": 0},
    )
    assert resp.status_code == 422


def test_meanings_limit_one_hundred_one_returns_422(
    client: TestClient,
) -> None:
    """``limit=101`` is above 100 and rejected by ``le=100``."""
    resp = client.get(
        "/api/meanings/anything/sentences",
        params={"limit": 101},
    )
    assert resp.status_code == 422


def test_meanings_respects_explicit_limit(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
    tmp_path: Path,
) -> None:
    """``limit=1`` returns at most 1 result even when more match."""
    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "a greeting")
    _seed_sentence(tmp_path, "s-2", "再见", "zài jiàn", "a farewell")
    _seed_index(
        tmp_path,
        {"s-1": "a greeting", "s-2": "a farewell"},
    )
    # Query with text that exactly matches one of the indexed
    # meanings — cosine ≈ 1.0 against s-1, near 0 against s-2.
    # ``limit=1`` keeps only the top hit.
    resp = client.get(
        "/api/meanings/a greeting/sentences",
        params={"threshold": 0.5, "limit": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["id"] == "s-1"


# ---------------------------------------------------------------------------
# 8. Payload hygiene — no english / meaning at any level
# ---------------------------------------------------------------------------


def test_meanings_response_never_contains_english_or_meaning_keys(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
    tmp_path: Path,
) -> None:
    """AC20 / AC27c: the response payload has no ``english`` or
    ``meaning`` keys at any level.

    We seed sentence units with rich ``english``/``meaning``
    fields so any regression that copies them through would be
    caught immediately.
    """
    _seed_sentence(
        tmp_path,
        "s-1",
        "你好世界",
        "nǐ hǎo shì jiè",
        "a common greeting",
        english="hello world",
    )
    _seed_index(tmp_path, {"s-1": "a common greeting"})
    resp = client.get("/api/meanings/a%20common%20greeting/sentences")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # Top-level schema lockdown — only ``query`` and ``results``.
    assert set(payload.keys()) == {"query", "results"}

    # Per-item schema lockdown — exactly the four keys.
    assert len(payload["results"]) >= 1
    for item in payload["results"]:
        assert set(item.keys()) == {"id", "hanzi", "pinyin", "score"}

    # Helper-driven recursive check.
    assert has_english_or_meaning_key(payload) is False, (
        f"AC20/AC27c violated: meanings payload leaked a forbidden "
        f"key: {payload!r}"
    )


def test_meanings_service_layer_dict_has_only_four_keys(
    tmp_path: Path,
    hashing_embedder: HashingEmbedder,
) -> None:
    """Service-layer contract: each result dict has exactly
    ``id``, ``hanzi``, ``pinyin``, ``score`` — no ``english`` /
    ``meaning`` (even though the underlying unit file has them).

    Direct call to :func:`meanings_search` so we can inspect
    the dict shape without going through Pydantic serialization.
    """
    _seed_sentence(
        tmp_path,
        "s-1",
        "你好",
        "nǐ hǎo",
        "a greeting",
        english="hello",
    )
    _seed_index(tmp_path, {"s-1": "a greeting"})
    out = meanings_search(
        str(tmp_path),
        text="a greeting",
        threshold=0.0,
        limit=10,
        embedder=hashing_embedder,
    )
    assert len(out) >= 1
    for item in out:
        assert set(item.keys()) == {"id", "hanzi", "pinyin", "score"}, (
            f"service-layer dict has extra keys: {set(item.keys())!r}"
        )


# ---------------------------------------------------------------------------
# 7. Privacy — INFO log never contains the user's query text
# ---------------------------------------------------------------------------


def test_meanings_info_log_does_not_contain_query_text(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC27c privacy requirement: the route's INFO log records the
    response size, threshold, and limit — never the user's query
    text.

    We pick a distinctive, easily-searchable English query and
    then scan every captured log record for it. The query text
    MUST NOT appear at INFO level anywhere in the captured log.
    """
    _seed_sentence(tmp_path, "s-1", "你好", "nǐ hǎo", "a greeting")
    _seed_index(tmp_path, {"s-1": "a greeting"})

    # A distinctive query string we can search for in the log.
    # Using a multi-word phrase so a substring match would be
    # extremely unlikely to be a false positive.
    distinctive_query = "DistinctivePrivSentinelText42 abcdef"

    # Capture from both the route module and the service module
    # so we can verify neither layer leaks the query. The
    # ``caplog.at_level`` context manager propagates the level
    # setting to the root logger so all child loggers inherit it.
    with caplog.at_level(logging.INFO):
        resp = client.get(
            f"/api/meanings/{distinctive_query}/sentences"
        )
    assert resp.status_code == 200, resp.text

    # Walk every captured record at INFO (or above) from the
    # route module — none of them must contain the query text.
    info_records = [
        rec for rec in caplog.records if rec.levelno >= logging.INFO
    ]
    for rec in info_records:
        formatted = rec.getMessage()
        assert distinctive_query not in formatted, (
            f"AC27c privacy violation: query text appeared in "
            f"{rec.name} log line: {formatted!r}"
        )
        assert distinctive_query not in (rec.msg or ""), (
            f"AC27c privacy violation: query text appeared in "
            f"unformatted record: {rec.msg!r}"
        )

    # Also assert the response shape still includes the query
    # field (the SPEC's contract), but that the *log* doesn't.
    body = resp.json()
    assert body["query"] == distinctive_query


# ---------------------------------------------------------------------------
# 8. Live integration — end-to-end via TestClient
# ---------------------------------------------------------------------------


def test_meanings_live_integration_with_real_index(
    client: TestClient,
    hashing_embedder: HashingEmbedder,
    tmp_path: Path,
) -> None:
    """Seed three sentence units with distinct meanings, build a
    FAISS index over their ``meaning`` fields, and exercise the
    full route. The response is asserted to be clean
    (hanzi + pinyin only, no english/meaning) and the top hit
    for a self-query is the seed with cosine ≈ 1.0.
    """
    _seed_sentence(
        tmp_path,
        "s-greet",
        "你好世界",
        "nǐ hǎo shì jiè",
        "a common everyday greeting in Chinese",
    )
    _seed_sentence(
        tmp_path,
        "s-bye",
        "再见",
        "zài jiàn",
        "a farewell said when parting",
    )
    _seed_sentence(
        tmp_path,
        "s-thanks",
        "谢谢",
        "xiè xie",
        "an expression of gratitude",
    )
    _seed_index(
        tmp_path,
        {
            "s-greet": "a common everyday greeting in Chinese",
            "s-bye": "a farewell said when parting",
            "s-thanks": "an expression of gratitude",
        },
    )

    # Query for the greeting — top hit should be s-greet.
    resp = client.get(
        "/api/meanings/a%20common%20everyday%20greeting%20in%20Chinese/sentences"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == (
        "a common everyday greeting in Chinese"
    )
    assert len(body["results"]) >= 1
    top = body["results"][0]
    assert top["id"] == "s-greet"
    assert top["hanzi"] == "你好世界"
    assert top["pinyin"] == "nǐ hǎo shì jiè"
    assert top["score"] == pytest.approx(1.0, abs=1e-5)

    # Payload hygiene at every level.
    assert has_english_or_meaning_key(body) is False
    assert set(body.keys()) == {"query", "results"}
    for item in body["results"]:
        assert set(item.keys()) == {"id", "hanzi", "pinyin", "score"}

    # Sorted descending by score.
    scores = [item["score"] for item in body["results"]]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Service-layer direct call — empty / no index
# ---------------------------------------------------------------------------


def test_meanings_search_empty_query_returns_empty(tmp_path: Path) -> None:
    """Direct service call: empty / whitespace / non-string query
    returns ``[]`` without touching the index."""
    out = meanings_search(str(tmp_path), text="")
    assert out == []
    out = meanings_search(str(tmp_path), text="   ")
    assert out == []
    out = meanings_search(str(tmp_path), text=None)  # type: ignore[arg-type]
    assert out == []


def test_meanings_search_empty_index_returns_empty(tmp_path: Path) -> None:
    """Direct service call: no FAISS files on disk → ``[]``."""
    embedder = HashingEmbedder()
    out = meanings_search(
        str(tmp_path),
        text="anything",
        threshold=0.0,
        limit=10,
        embedder=embedder,
    )
    assert out == []