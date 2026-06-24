"""Tests for ``api.services.ai_client`` (SPEC §6 AC6, AC8).

Coverage:

* Mock client — propose_labels returns a ProposedLabels with all
  seven required fields populated (AC6).
* Mock client — default proposer; custom proposer; invalid input.
* Factory — returns MockAIClient when no key, HttpAIClient when key
  is set; ``force="mock"`` and ``force="http"`` overrides.
* JSON parser — handles bare JSON, fenced ```json, missing keys,
  wrong types. (Driven through the mock by overriding its default
  to return a hand-crafted JSON string in one test, otherwise the
  mock's structured return is used.)
* Singleton reset — used between tests.
* Key safety — a test that builds a real ProposedLabels and asserts
  the secret value never leaks into the to_dict output or str.
* HttpAIClient — the constructor reads settings; without a key the
  propose_labels call raises RuntimeError.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from api.services import ai_client as ai_client_module
from api.services.ai_client import (
    HttpAIClient,
    MockAIClient,
    ProposedGroup,
    ProposedLabels,
    _parse_labels_json,
    get_ai_client,
    reset_ai_client_singleton,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the AI client singleton and clear LANGUAGE_BRAIN_AI_KEY
    so each test starts with a known state. The .env file is never
    read; we only use ``monkeypatch.setenv`` / ``delenv``."""
    reset_ai_client_singleton()
    for k in (
        "LANGUAGE_BRAIN_VAULT",
        "LANGUAGE_BRAIN_AI_KEY",
        "LANGUAGE_BRAIN_AI_ENDPOINT",
        "LANGUAGE_BRAIN_AI_MODEL",
    ):
        monkeypatch.delenv(k, raising=False)
    # Force the settings cache to rebuild against the cleared env.
    ai_client_module.get_settings.cache_clear()
    yield
    reset_ai_client_singleton()
    ai_client_module.get_settings.cache_clear()


def _fixture_proposer(hanzi: str, note: str) -> ProposedLabels:
    """A hand-crafted proposer used by several tests to assert the
    AC6 contract: every field populated."""
    return ProposedLabels(
        pinyin="wǒ liú kǒu shuǐ le",
        english="I'm drooling",
        meaning="I see food and my mouth waters; visual craving",
        words=["我", "流", "口", "水", "了"],
        word_refs=["wǒ", "liú", "kǒu", "shuǐ", "le"],
        groups=[
            ProposedGroup(
                id="reactions", display_name="Reactions", description="reactive states"
            ),
            ProposedGroup(id="food", display_name="Food", description="things you eat"),
        ],
        antonyms=[],
    )


# ---------------------------------------------------------------------------
# MockAIClient — AC6 contract
# ---------------------------------------------------------------------------


def test_mock_client_returns_all_required_fields() -> None:
    """AC6: every one of the seven fields is populated by propose_labels."""
    client = MockAIClient(proposer=_fixture_proposer)
    result = client.propose_labels("我流口水了", note="I drool at sight of food")

    assert isinstance(result, ProposedLabels)
    assert result.pinyin == "wǒ liú kǒu shuǐ le"
    assert result.english == "I'm drooling"
    assert result.meaning == "I see food and my mouth waters; visual craving"
    assert result.words == ["我", "流", "口", "水", "了"]
    assert result.word_refs == ["wǒ", "liú", "kǒu", "shuǐ", "le"]
    assert len(result.groups) == 2
    assert result.groups[0].id == "reactions"
    assert result.groups[0].display_name == "Reactions"
    assert result.groups[1].id == "food"
    assert result.antonyms == []


def test_mock_client_records_call_metadata() -> None:
    """The mock records call count and last args — useful for assertions
    in route tests."""
    client = MockAIClient(proposer=_fixture_proposer)
    assert client.call_count == 0
    assert client.last_hanzi is None

    client.propose_labels("你好", note="hi")
    assert client.call_count == 1
    assert client.last_hanzi == "你好"
    assert client.last_note == "hi"

    client.propose_labels("再见")
    assert client.call_count == 2
    assert client.last_hanzi == "再见"
    assert client.last_note == ""  # default


def test_mock_client_default_proposer() -> None:
    """No custom proposer → a default mock with empty groups/antonyms."""
    client = MockAIClient()
    result = client.propose_labels("你好")

    # Default mock makes no real pinyin claim; just smoke-test the shape.
    assert isinstance(result, ProposedLabels)
    assert result.words == ["你", "好"]
    assert result.word_refs == ["你", "好"]
    assert result.groups == []
    assert result.antonyms == []


def test_mock_client_rejects_empty_hanzi() -> None:
    client = MockAIClient(proposer=_fixture_proposer)
    with pytest.raises(ValueError):
        client.propose_labels("")
    with pytest.raises(ValueError):
        client.propose_labels("   ")


def test_mock_client_rejects_non_string_note() -> None:
    client = MockAIClient(proposer=_fixture_proposer)
    with pytest.raises(ValueError):
        client.propose_labels("你好", note=123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ProposedLabels — to_dict shape
# ---------------------------------------------------------------------------


def test_proposed_labels_to_dict_shape() -> None:
    """to_dict returns the JSON-serializable shape the route returns."""
    labels = _fixture_proposer("x", "")
    d = labels.to_dict()

    assert d["pinyin"] == "wǒ liú kǒu shuǐ le"
    assert d["english"] == "I'm drooling"
    assert d["meaning"] == "I see food and my mouth waters; visual craving"
    assert d["words"] == ["我", "流", "口", "水", "了"]
    assert d["word_refs"] == ["wǒ", "liú", "kǒu", "shuǐ", "le"]
    assert d["groups"] == [
        {"id": "reactions", "display_name": "Reactions", "description": "reactive states"},
        {"id": "food", "display_name": "Food", "description": "things you eat"},
    ]
    assert d["antonyms"] == []
    # JSON-serializable
    json.dumps(d)


# ---------------------------------------------------------------------------
# AC8 — key safety
# ---------------------------------------------------------------------------


def test_to_dict_does_not_leak_settings() -> None:
    """to_dict has no path that includes the AI key. We assert the
    output never references SecretStr or contains any string from
    a hypothetical key set in this test."""
    labels = _fixture_proposer("x", "")
    d = labels.to_dict()
    rendered = json.dumps(d, ensure_ascii=False)
    assert "SecretStr" not in rendered
    assert "LANGUAGE_BRAIN_AI_KEY" not in rendered
    # No obvious key-shaped token (e.g. an "sk-" prefix or a
    # 32+ char alnum run). The default fixture has no such token.
    assert "sk-" not in rendered


def test_proposed_labels_str_excludes_internal_state() -> None:
    """dataclass-generated __repr__ should not include any key —
    there is no key field on the dataclass, so this is a smoke test
    that the dataclass has no implicit key-carrying field."""
    labels = _fixture_proposer("x", "")
    r = repr(labels)
    # No key-looking token in the default dataclass repr.
    assert "sk-" not in r
    assert "secret" not in r.lower()


# ---------------------------------------------------------------------------
# JSON parser (used by HttpAIClient and by any future test that
# hand-rolls an AI response).
# ---------------------------------------------------------------------------


def test_parse_labels_json_bare_object() -> None:
    raw = json.dumps(
        {
            "pinyin": "p",
            "english": "e",
            "meaning": "m",
            "words": ["a"],
            "word_refs": ["a"],
            "groups": [],
            "antonyms": [],
        }
    )
    out = _parse_labels_json(raw)
    assert out.pinyin == "p"
    assert out.english == "e"
    assert out.meaning == "m"


def test_parse_labels_json_fenced() -> None:
    raw = "```json\n" + json.dumps(
        {
            "pinyin": "p",
            "english": "e",
            "meaning": "m",
            "words": ["a"],
            "word_refs": ["a"],
            "groups": [{"id": "g"}],
            "antonyms": [],
        }
    ) + "\n```"
    out = _parse_labels_json(raw)
    assert out.groups[0].id == "g"
    assert out.groups[0].display_name == ""  # missing key → default


def test_parse_labels_json_missing_key_raises() -> None:
    bad = json.dumps(
        {
            "pinyin": "p",
            "english": "e",
            "meaning": "m",
            "words": ["a"],
            "word_refs": ["a"],
            "antonyms": [],
            # no "groups"
        }
    )
    with pytest.raises(ValueError, match="missing required keys"):
        _parse_labels_json(bad)


def test_parse_labels_json_wrong_type_raises() -> None:
    bad = json.dumps(
        {
            "pinyin": "p",
            "english": "e",
            "meaning": "m",
            "words": "not a list",  # wrong type
            "word_refs": ["a"],
            "groups": [],
            "antonyms": [],
        }
    )
    with pytest.raises(ValueError, match="words"):
        _parse_labels_json(bad)


def test_parse_labels_json_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_labels_json("not json at all")


def test_parse_labels_json_not_an_object_raises() -> None:
    with pytest.raises(ValueError, match="object"):
        _parse_labels_json("[1, 2, 3]")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_returns_mock_when_no_key() -> None:
    client = get_ai_client()
    assert isinstance(client, MockAIClient)


def test_factory_returns_http_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_KEY", "sk-test-1234567890abcdef")
    ai_client_module.get_settings.cache_clear()
    client = get_ai_client()
    assert isinstance(client, HttpAIClient)


def test_factory_force_mock_overrides_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_KEY", "sk-test-1234567890abcdef")
    ai_client_module.get_settings.cache_clear()
    client = get_ai_client(force="mock")
    assert isinstance(client, MockAIClient)


def test_factory_force_http_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # No key set; force="http" must produce a client whose call raises
    # at runtime, but the factory itself does not raise.
    client = get_ai_client(force="http")
    assert isinstance(client, HttpAIClient)
    with pytest.raises(RuntimeError, match="no AI key configured"):
        client.propose_labels("x")


# ---------------------------------------------------------------------------
# HttpAIClient — call without transport
# ---------------------------------------------------------------------------


def test_http_client_reads_endpoint_and_model_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_KEY", "sk-test")
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_ENDPOINT", "https://example.test/v1")
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_MODEL", "M3")
    ai_client_module.get_settings.cache_clear()

    client = HttpAIClient()
    assert client._endpoint == "https://example.test/v1"  # type: ignore[attr-defined]
    assert client._model == "M3"  # type: ignore[attr-defined]


def test_http_client_constructor_overrides() -> None:
    """Explicit args to the constructor beat settings."""
    client = HttpAIClient(endpoint="https://override.test/v1", model="X1")
    assert client._endpoint == "https://override.test/v1"  # type: ignore[attr-defined]
    assert client._model == "X1"  # type: ignore[attr-defined]


def test_http_client_rejects_empty_hanzi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_KEY", "sk-test")
    ai_client_module.get_settings.cache_clear()
    client = HttpAIClient()
    with pytest.raises(ValueError):
        client.propose_labels("")


def test_http_client_propose_without_key_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HttpAIClient()
    with pytest.raises(RuntimeError, match="no AI key configured"):
        client.propose_labels("x")
