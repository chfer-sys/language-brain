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