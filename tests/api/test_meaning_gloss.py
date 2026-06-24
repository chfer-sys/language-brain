"""Tests for SPEC §6 AC7 — the `meaning` field is a richer gloss
than `english` (the two strings are distinct and `meaning` adds
information not in `english`).

The contract is enforced two ways:

1. The system prompt sent to the AI explicitly forbids
   `meaning == english` and requires the gloss to add situational
   context, intent, or usage. We assert on the prompt text.

2. The route's response shape is asserted: the mock's hand-crafted
   labels include distinct `meaning` and `english` fields, and the
   integration test confirms the route preserves the distinction.

AC7 is also implicitly tested by every test that uses
``_fixture_proposer`` (in test_ai_client.py) — that proposer returns
distinct strings, and any test that fails to do so would surface
during the route test.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import add_sentence as add_sentence_route
from api.services import ai_client as ai_client_module
from api.services.ai_client import (
    ProposedGroup,
    ProposedLabels,
    _SYSTEM_PROMPT,
    reset_ai_client_singleton,
)


# ---------------------------------------------------------------------------
# System prompt — explicit contract
# ---------------------------------------------------------------------------


def test_system_prompt_forbids_meaning_equals_english() -> None:
    """The prompt must explicitly tell the AI not to set meaning == english.

    This is a prompt-level guard. We are not testing whether the AI
    obeys it (we can't, without a real API call) — we test that the
    prompt is unambiguous so that any reasonable model will produce
    distinct strings.
    """
    prompt = _SYSTEM_PROMPT
    assert "meaning" in prompt
    assert "english" in prompt
    # The "must be different" / "never" / "must add" language.
    lower = prompt.lower()
    assert any(
        phrase in lower
        for phrase in (
            "must be a different string",
            "must add information",
            "never set",
            "must add",
        )
    ), (
        "System prompt must explicitly require meaning to be richer than "
        "english. Update _SYSTEM_PROMPT in api/services/ai_client.py."
    )


def test_system_prompt_english_described_as_literal() -> None:
    """`english` is described as a literal / dictionary translation."""
    lower = _SYSTEM_PROMPT.lower()
    assert "literal" in lower or "dictionary" in lower, (
        "System prompt should describe `english` as a literal translation, "
        "to draw the line between it and `meaning`."
    )


def test_system_prompt_meaning_described_as_richer() -> None:
    """`meaning` is described as richer / intent-bearing."""
    lower = _SYSTEM_PROMPT.lower()
    assert "richer" in lower or "communicative" in lower or "intent" in lower, (
        "System prompt should describe `meaning` as a richer gloss."
    )


# ---------------------------------------------------------------------------
# Integration: route preserves the distinct-strings invariant
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _patch_ai_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Inject a fake client whose labels satisfy AC7."""
    reset_ai_client_singleton()

    class _FakeClient:
        def propose_labels(self, hanzi: str, note: str = "") -> ProposedLabels:
            return ProposedLabels(
                pinyin="kàn qǐlái hěn hǎochī",
                english="looks delicious",
                # A gloss that adds information not in the literal:
                # the speaker's visual perception and consequent craving.
                meaning=(
                    "On seeing the food, I want to eat it; an expression of "
                    "visual craving triggered by something appetizing"
                ),
                words=["看", "起来", "很", "好吃"],
                word_refs=["kàn", "qǐlái", "hěn", "hǎochī"],
                groups=[
                    ProposedGroup(id="reactions", display_name="Reactions"),
                ],
                antonyms=[],
            )

    fake = _FakeClient()
    monkeypatch.setattr(add_sentence_route, "get_ai_client", lambda: fake)
    yield fake


def test_route_response_has_distinct_meaning_and_english(client: TestClient) -> None:
    """AC7 — the two fields are different strings, and `meaning` adds info."""
    resp = client.post(
        "/api/sentences",
        json={"hanzi": "看起来很好吃", "note": "the food looks great"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["english"] != body["meaning"], (
        f"AC7 violated: english ({body['english']!r}) == meaning ({body['meaning']!r})"
    )
    # The meaning adds information not in the literal — the literal is
    # 18 chars; the meaning is much longer and contains "craving"
    # which is not in the literal.
    assert len(body["meaning"]) > len(body["english"])
    assert "craving" in body["meaning"] or "want" in body["meaning"]


def test_route_response_meaning_is_string(client: TestClient) -> None:
    """Both fields are strings; meaning is not empty."""
    body = client.post(
        "/api/sentences", json={"hanzi": "看起来很好吃"}
    ).json()
    assert isinstance(body["english"], str) and body["english"]
    assert isinstance(body["meaning"], str) and body["meaning"]


# ---------------------------------------------------------------------------
# Mock proposer — AC7 contract is the caller's responsibility
# ---------------------------------------------------------------------------


def test_default_mock_proposer_uses_note_for_meaning() -> None:
    """The default mock proposer (no custom function) treats the user's
    note as a stand-in for both english and meaning. This is documented
    behavior; tests that need distinct strings pass a custom proposer."""
    from api.services.ai_client import MockAIClient

    client = MockAIClient()
    labels = client.propose_labels("你好", note="hello")
    # Default mock: english and meaning are the same (both = note).
    # This is fine — AC7 is about real AI output, not the default mock.
    assert labels.english == "hello"
    assert labels.meaning == "hello"


def test_custom_proposer_can_satisfy_ac7() -> None:
    """Demonstrates the AC7 pattern: a custom proposer returns distinct
    strings. This is what production AI clients are expected to do,
    and what the test for AC6 (in test_ai_client.py) already uses.
    """
    from api.services.ai_client import MockAIClient

    def ac7_proposer(hanzi: str, note: str) -> ProposedLabels:
        return ProposedLabels(
            pinyin="x",
            english="hello",
            meaning="a casual greeting used when meeting someone",
            words=["你", "好"],
            word_refs=["nǐ", "hǎo"],
            groups=[],
            antonyms=[],
        )

    client = MockAIClient(proposer=ac7_proposer)
    labels = client.propose_labels("你好", note="hi")
    assert labels.english != labels.meaning
    assert "greeting" in labels.meaning
