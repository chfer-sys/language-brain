"""Tests for ``POST /api/sentences`` (SPEC §6 AC6, AC8).

Uses FastAPI's TestClient. The AI client is monkey-patched at the
module level on the route module, so no real network call is made
and no key is needed.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import add_sentence as add_sentence_route
from api.services.ai_client import (
    AIClient,
    ProposedGroup,
    ProposedLabels,
    reset_ai_client_singleton,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _patch_ai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the AI client dependency with a deterministic fake.

    Also reset the AI client singleton so any cached HttpAIClient
    from a previous test is gone.
    """
    reset_ai_client_singleton()

    class _FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def propose_labels(self, hanzi: str, note: str = "") -> ProposedLabels:
            self.calls.append((hanzi, note))
            return ProposedLabels(
                pinyin="wǒ liú kǒu shuǐ le",
                english="I'm drooling",
                meaning="I see food and my mouth waters; visual craving",
                words=["我", "流", "口", "水", "了"],
                word_refs=["wǒ", "liú", "kǒu", "shuǐ", "le"],
                groups=[
                    ProposedGroup(
                        id="reactions",
                        display_name="Reactions",
                        description="reactive states",
                    ),
                ],
                antonyms=[],
            )

    fake = _FakeClient()
    monkeypatch.setattr(add_sentence_route, "get_ai_client", lambda: fake)
    yield fake


# ---------------------------------------------------------------------------
# AC6 — endpoint returns all required fields populated
# ---------------------------------------------------------------------------


def test_propose_returns_all_required_fields(client: TestClient) -> None:
    resp = client.post(
        "/api/sentences",
        json={"hanzi": "我流口水了", "note": "I drool at sight of food"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Every AC6 key is present and non-empty.
    assert body["pinyin"] == "wǒ liú kǒu shuǐ le"
    assert body["english"] == "I'm drooling"
    assert body["meaning"] == "I see food and my mouth waters; visual craving"
    assert body["words"] == ["我", "流", "口", "水", "了"]
    assert body["word_refs"] == ["wǒ", "liú", "kǒu", "shuǐ", "le"]
    assert isinstance(body["groups"], list)
    assert len(body["groups"]) == 1
    assert body["groups"][0]["id"] == "reactions"
    assert body["groups"][0]["display_name"] == "Reactions"
    assert body["antonyms"] == []


def test_propose_works_without_note(client: TestClient) -> None:
    """AC6 — note is optional."""
    resp = client.post("/api/sentences", json={"hanzi": "你好"})
    assert resp.status_code == 200, resp.text
    assert "pinyin" in resp.json()


def test_propose_passes_hanzi_and_note_to_ai_client(
    client: TestClient, _patch_ai_client: Any
) -> None:
    fake = _patch_ai_client
    resp = client.post(
        "/api/sentences", json={"hanzi": "再见", "note": "goodbye"}
    )
    assert resp.status_code == 200
    assert fake.calls == [("再见", "goodbye")]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_propose_rejects_empty_hanzi(client: TestClient) -> None:
    resp = client.post("/api/sentences", json={"hanzi": ""})
    # Pydantic catches min_length=1 → 422.
    assert resp.status_code == 422


def test_propose_rejects_whitespace_only_hanzi(client: TestClient) -> None:
    """min_length=1 lets a whitespace-only string through pydantic;
    the route must reject it with 422."""
    resp = client.post("/api/sentences", json={"hanzi": "   "})
    assert resp.status_code == 422
    assert "hanzi" in resp.text.lower()


def test_propose_rejects_missing_hanzi_field(client: TestClient) -> None:
    resp = client.post("/api/sentences", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# AC8 — AI client is the only LLM touchpoint. The route's dependency
# injection is the proof; the AI client module owns the network code.
# ---------------------------------------------------------------------------


def test_route_uses_ai_client_dependency(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the AI client module is patched, the route reflects the patch.
    A regression that imported the network code directly into the
    route would fail this test (the patch on ai_client has no effect
    in the route's import graph)."""
    sentinel = {"called": 0}

    class _Sentinel(AIClient):
        def propose_labels(self, hanzi: str, note: str = "") -> ProposedLabels:
            sentinel["called"] += 1
            return ProposedLabels(
                pinyin="x",
                english="x",
                meaning="x",
                words=["x"],
                word_refs=["x"],
                groups=[],
                antonyms=[],
            )

    monkeypatch.setattr(add_sentence_route, "get_ai_client", lambda: _Sentinel())
    resp = client.post("/api/sentences", json={"hanzi": "你好"})
    assert resp.status_code == 200
    assert sentinel["called"] == 1


# ---------------------------------------------------------------------------
# AI provider error → degraded 200 (local fallback)
# ---------------------------------------------------------------------------


def test_propose_returns_degraded_200_when_ai_raises_runtime(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the AI provider fails, the route serves a local fallback.

    The response is 200, ``degraded`` is true, ``pinyin`` and ``words``
    are non-empty, and ``english`` equals the user's note.
    """

    class _Broken(AIClient):
        def propose_labels(self, hanzi: str, note: str = "") -> ProposedLabels:
            raise RuntimeError("upstream exploded")

    monkeypatch.setattr(add_sentence_route, "get_ai_client", lambda: _Broken())
    resp = client.post(
        "/api/sentences", json={"hanzi": "你好", "note": "hello greeting"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["degraded"] is True
    assert body["pinyin"], "pinyin must be non-empty"
    assert body["words"], "words must be non-empty"
    assert body["english"] == "hello greeting"
    # The error message must not leak the underlying text.
    assert "upstream exploded" not in resp.text


def test_propose_returns_422_when_ai_raises_value(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Bad(AIClient):
        def propose_labels(self, hanzi: str, note: str = "") -> ProposedLabels:
            raise ValueError("bad input")

    monkeypatch.setattr(add_sentence_route, "get_ai_client", lambda: _Bad())
    resp = client.post("/api/sentences", json={"hanzi": "你好"})
    assert resp.status_code == 422
