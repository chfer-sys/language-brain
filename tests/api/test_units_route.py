"""Tests for GET /api/units/{id} (T32, AC26).

The endpoint reads a single unit by id, trying sentences/words/groups
in order and returning the first match. The author view is allowed
to include ``english`` and ``meaning`` fields, so this test does NOT
assert AC20/AC21 hygiene here (those are enforced in the search
endpoint, AC20).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.config as config_module
from api.main import app
from api.services.unit_writer import write_unit


@pytest.fixture
def client_with_vault(tmp_path, monkeypatch):
    """A TestClient bound to a fresh LANGUAGE_BRAIN_VAULT=tmp_path.

    Clears the Settings cache both before and after so no test leaks
    the tmp vault path into another test.
    """
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))
    try:
        yield TestClient(app), str(tmp_path)
    finally:
        config_module.get_settings.cache_clear()


def _seed_three_units(vault: str) -> None:
    """Write one sentence, one word, and one group into the vault."""
    write_unit(
        vault,
        {
            "id": "s-1",
            "type": "sentence",
            "name": "我喜欢吃",
            "properties": {
                "hanzi": "我喜欢吃",
                "pinyin": "wǒ xǐhuān chī",
                "english": "I like eating",
                "meaning": "expressing enjoyment of eating",
                "words": ["我", "喜欢", "吃"],
                "word_refs": ["wǒ", "xǐhuān", "chī"],
                "groups": ["food"],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-06-27",
            "updated": "2026-06-27",
            "author_confirmed": True,
        },
    )
    write_unit(
        vault,
        {
            "id": "chī",
            "type": "word",
            "name": "吃",
            "properties": {
                "hanzi": "吃",
                "pinyin": "chī",
                "english": "to eat",
                "meaning": "the act of eating",
                "groups": ["food"],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-06-27",
            "updated": "2026-06-27",
            "author_confirmed": True,
        },
    )
    write_unit(
        vault,
        {
            "id": "food",
            "type": "group",
            "name": "food",
            "properties": {
                "display_name": "Food",
                "description": "Things you can eat",
                "members": ["chī", "s-1"],
            },
            "connections": [],
            "created": "2026-06-27",
            "updated": "2026-06-27",
            "author_confirmed": True,
        },
    )


def test_get_sentence(client_with_vault):
    client, vault = client_with_vault
    _seed_three_units(vault)
    resp = client.get("/api/units/s-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "s-1"
    assert body["type"] == "sentence"
    # Author view: english and meaning are present.
    assert body["properties"]["english"] == "I like eating"
    assert body["properties"]["meaning"] == "expressing enjoyment of eating"


def test_get_word(client_with_vault):
    client, vault = client_with_vault
    _seed_three_units(vault)
    resp = client.get("/api/units/chī")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "chī"
    assert body["type"] == "word"


def test_get_group(client_with_vault):
    client, vault = client_with_vault
    _seed_three_units(vault)
    resp = client.get("/api/units/food")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "food"
    assert body["type"] == "group"
    assert body["properties"]["members"] == ["chī", "s-1"]


def test_get_missing_returns_404(client_with_vault):
    client, vault = client_with_vault
    _seed_three_units(vault)
    resp = client.get("/api/units/does-not-exist")
    assert resp.status_code == 404


def test_get_empty_id_is_rejected():
    config_module.get_settings.cache_clear()
    client = TestClient(app)
    # FastAPI routes don't match an empty segment, so this 404s at
    # the routing layer — we just confirm it doesn't 500.
    resp = client.get("/api/units/")
    assert resp.status_code in (404, 405)
    config_module.get_settings.cache_clear()


def test_word_unit_includes_containing_sentences(client_with_vault):
    """AC27: word detail response carries containing_sentences list."""
    client, vault = client_with_vault
    _seed_three_units(vault)
    resp = client.get("/api/units/chī")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "word"
    # s-1 references chī in word_refs; each entry is now {id, name}.
    assert len(body["containing_sentences"]) == 1
    assert body["containing_sentences"][0]["id"] == "s-1"
    assert body["containing_sentences"][0]["name"] == "我喜欢吃"


def test_word_unit_containing_sentences_empty_when_no_match(client_with_vault):
    """AC27: word with no containing sentences returns empty list."""
    client, vault = client_with_vault
    _seed_three_units(vault)
    # Add a word that nothing references.
    write_unit(
        vault,
        {
            "id": "lí",
            "type": "word",
            "name": "离",
            "properties": {
                "hanzi": "离",
                "pinyin": "lí",
                "english": "to leave",
                "meaning": "going away",
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-06-27",
            "updated": "2026-06-27",
            "author_confirmed": True,
        },
    )
    resp = client.get("/api/units/lí")
    assert resp.status_code == 200
    assert resp.json()["containing_sentences"] == []


def test_sentence_unit_does_not_carry_containing_sentences(client_with_vault):
    """AC27 only applies to words. Sentences and groups omit the field."""
    client, vault = client_with_vault
    _seed_three_units(vault)
    resp = client.get("/api/units/s-1")
    body = resp.json()
    assert "containing_sentences" not in body

    resp = client.get("/api/units/food")
    body = resp.json()
    assert "containing_sentences" not in body


def test_get_unit_includes_connection_names(client_with_vault):
    """Each connection entry carries a 'name' field with the target's hanzi
    (for word/sentence) or display_name (for group)."""
    client, vault = client_with_vault
    # Write a sentence with explicit connections to the seeded word and group.
    write_unit(
        vault,
        {
            "id": "test-s",
            "type": "sentence",
            "name": "测试句",
            "properties": {
                "hanzi": "测试句",
                "pinyin": "cèsì jù",
                "english": "test sentence",
                "meaning": "",
                "words": [],
                "word_refs": [],
                "groups": [],
                "antonyms": [],
            },
            "connections": [
                {"to": "chī", "kind": "lexical", "score": 0.9},
                {"to": "food", "kind": "group", "score": 0.5},
            ],
            "created": "2026-07-01",
            "updated": "2026-07-01",
            "author_confirmed": True,
        },
    )
    # Seed the word and group units that connections point to.
    _seed_three_units(vault)
    resp = client.get("/api/units/test-s")
    assert resp.status_code == 200
    body = resp.json()
    conn_by_to = {c["to"]: c for c in body["connections"]}
    # lexical to chī → name should be the word's hanzi
    assert conn_by_to["chī"]["name"] == "吃"
    # group to food → name should be the group's display_name
    assert conn_by_to["food"]["name"] == "Food"


def test_get_unit_connection_name_falls_back_to_id_for_missing_target(client_with_vault):
    """If a connection target does not exist, 'name' falls back to the bare id
    rather than raising an error."""
    client, vault = client_with_vault
    # Write a sentence whose connections point to a non-existent word.
    write_unit(
        vault,
        {
            "id": "orphan",
            "type": "sentence",
            "name": "orphan",
            "properties": {
                "hanzi": "虚拟句",
                "pinyin": "xūnǐ jù",
                "english": "orphan sentence",
                "meaning": "",
                "words": [],
                "word_refs": [],
                "groups": [],
                "antonyms": [],
            },
            "connections": [{"to": "nonexistent-word", "kind": "lexical", "score": 0.5}],
            "created": "2026-07-01",
            "updated": "2026-07-01",
            "author_confirmed": True,
        },
    )
    resp = client.get("/api/units/orphan")
    assert resp.status_code == 200
    conn = resp.json()["connections"][0]
    assert conn["to"] == "nonexistent-word"
    assert conn["name"] == "nonexistent-word"  # falls back to bare id


def test_get_unit_includes_containing_sentence_names(client_with_vault):
    """Word response carries containing_sentences as {id, name} objects so the
    frontend can render sentence hanzi directly."""
    client, vault = client_with_vault
    _seed_three_units(vault)
    resp = client.get("/api/units/chī")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "word"
    sentences = body["containing_sentences"]
    assert len(sentences) == 1
    assert sentences[0]["id"] == "s-1"
    assert sentences[0]["name"] == "我喜欢吃"


# ---------------------------------------------------------------------------
# Compound enrichment (v0.9)
# ---------------------------------------------------------------------------


def _seed_compound_with_sentence(vault: str) -> str:
    """Write a compound C2 (什么) and a sentence whose word_refs includes C2."""
    write_unit(
        vault,
        {
            "id": "C2",
            "type": "compound",
            "name": "什么",
            "properties": {
                "hanzi": "什么",
                "pinyin": "shénme",
                "english": "what",
                "meaning": "interrogative pronoun",
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-07-01",
            "updated": "2026-07-01",
            "author_confirmed": True,
        },
    )
    write_unit(
        vault,
        {
            "id": "s-compound-test",
            "type": "sentence",
            "name": "这是什么",
            "properties": {
                "hanzi": "这是什么",
                "pinyin": "zhè shì shénme",
                "english": "what is this",
                "meaning": "",
                "words": ["这", "是", "什么"],
                "word_refs": ["zhè", "shì", "C2"],
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-07-01",
            "updated": "2026-07-01",
            "author_confirmed": True,
        },
    )
    return "C2"


def _seed_compound_with_constituents(vault: str) -> str:
    """Write compound C2 (什么) plus single-char word units 什 and 么."""
    write_unit(
        vault,
        {
            "id": "C2",
            "type": "compound",
            "name": "什么",
            "properties": {
                "hanzi": "什么",
                "pinyin": "shénme",
                "english": "what",
                "meaning": "interrogative pronoun",
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-07-01",
            "updated": "2026-07-01",
            "author_confirmed": True,
        },
    )
    write_unit(
        vault,
        {
            "id": "shénme",
            "type": "word",
            "name": "什",
            "properties": {
                "hanzi": "什",
                "pinyin": "shén",
                "english": "什 (radical)",
                "meaning": "",
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-07-01",
            "updated": "2026-07-01",
            "author_confirmed": True,
        },
    )
    write_unit(
        vault,
        {
            "id": "me",
            "type": "word",
            "name": "么",
            "properties": {
                "hanzi": "么",
                "pinyin": "me",
                "english": "么 (structural)",
                "meaning": "",
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-07-01",
            "updated": "2026-07-01",
            "author_confirmed": True,
        },
    )
    return "C2"


def test_get_compound_includes_containing_sentences(client_with_vault):
    """Compound detail page carries containing_sentences — sentence whose
    word_refs includes the compound id."""
    client, vault = client_with_vault
    _seed_compound_with_sentence(vault)
    resp = client.get("/api/units/C2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "compound"
    assert len(body["containing_sentences"]) == 1
    assert body["containing_sentences"][0]["id"] == "s-compound-test"
    assert body["containing_sentences"][0]["name"] == "这是什么"


def test_get_compound_includes_constituent_characters(client_with_vault):
    """Compound detail page carries constituent_characters — single-char word
    units whose hanzi appear in the compound's hanzi string."""
    client, vault = client_with_vault
    _seed_compound_with_constituents(vault)
    resp = client.get("/api/units/C2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "compound"
    chars = body["constituent_characters"]
    assert len(chars) == 2
    ids = {c["id"] for c in chars}
    assert ids == {"shénme", "me"}
    names = {c["name"] for c in chars}
    assert names == {"什", "么"}


def test_get_compound_constituents_empty_when_no_matches(client_with_vault):
    """Compound whose hanzi characters have no matching word units returns
    constituent_characters as an empty list (not missing)."""
    client, vault = client_with_vault
    write_unit(
        vault,
        {
            "id": "C2",
            "type": "compound",
            "name": "什么",
            "properties": {
                "hanzi": "什么",
                "pinyin": "shénme",
                "english": "what",
                "meaning": "interrogative pronoun",
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-07-01",
            "updated": "2026-07-01",
            "author_confirmed": True,
        },
    )
    resp = client.get("/api/units/C2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "compound"
    assert body["constituent_characters"] == []


def test_get_word_response_unchanged(client_with_vault):
    """Regression guard: word units still carry containing_sentences and
    do NOT carry constituent_characters."""
    client, vault = client_with_vault
    _seed_three_units(vault)
    resp = client.get("/api/units/chī")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "word"
    assert "containing_sentences" in body
    assert "constituent_characters" not in body