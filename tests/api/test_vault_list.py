"""Tests for GET /api/vault/list (v0.7, AC1–AC6).

AC1: response shape has exactly `type`, `total`, `limit`, `offset`, `sort`, `items`.
AC2: each item has exactly `id`, `name`, `snippet` — no english/meaning.
AC3: `type=word`, `type=compound`, `type=sentence` all return 200; word/compound
     filter by id prefix (W vs C).
AC4: `limit=10&offset=0` and `offset=1` return correct slices.
AC5: `sort=pinyin` returns items in pinyin A→Z order.
AC6: unknown `type` → 422.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.config as config_module
from api.main import app
from api.services.unit_writer import write_unit


@pytest.fixture
def client_with_vault(tmp_path, monkeypatch):
    """A TestClient bound to a fresh LANGUAGE_BRAIN_VAULT=tmp_path."""
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))
    try:
        yield TestClient(app), str(tmp_path)
    finally:
        config_module.get_settings.cache_clear()


def _seed_vault(vault: str) -> None:
    """Seed a minimal vault with sentences, words, and compounds.

    Sentences (S{n} ids) are chosen out-of-order (S3, S1, S2) to verify
    that list_vault returns them sorted by id ascending by default.

    Words (W{n}) and compounds (C{n}) share the words/ directory but are
    distinguished by id prefix — this is the storage contract from
    SPEC §4 / v0.5.

    Pinyin values are chosen so that alphabetical pinyin order differs
    from id order (for AC5): zōng, bàozi, māo for compounds; and
    W3(zǎo), W1(bēi), W2(cài) for words.
    """
    # Sentences
    for unit in [
        {
            "id": "S3",
            "type": "sentence",
            "properties": {
                "hanzi": "我流口水了",
                "pinyin": "wǒ liú kǒu shuǐ le",
                "english": "I drooled",
                "meaning": "my mouth is watering",
            },
            "connections": [],
        },
        {
            "id": "S1",
            "type": "sentence",
            "properties": {
                "hanzi": "我喜欢跑步",
                "pinyin": "wǒ xǐhuān pǎobù",
                "english": "I like running",
                "meaning": "enjoyment of running",
            },
            "connections": [],
        },
        {
            "id": "S2",
            "type": "sentence",
            "properties": {
                "hanzi": "天气真好",
                "pinyin": "tiānqì zhēn hǎo",
                "english": "Great weather",
                "meaning": "the weather is lovely today",
            },
            "connections": [],
        },
    ]:
        write_unit(vault, unit)

    # Words (W{n})
    for unit in [
        {
            "id": "W3",
            "type": "word",
            "properties": {
                "hanzi": "早",
                "pinyin": "zǎo",
                "english": "early",
                "meaning": "morning/early",
            },
            "connections": [],
        },
        {
            "id": "W1",
            "type": "word",
            "properties": {
                "hanzi": "杯",
                "pinyin": "bēi",
                "english": "cup",
                "meaning": "a cup or glass",
            },
            "connections": [],
        },
        {
            "id": "W2",
            "type": "word",
            "properties": {
                "hanzi": "菜",
                "pinyin": "cài",
                "english": "dish",
                "meaning": "food/dish",
            },
            "connections": [],
        },
    ]:
        write_unit(vault, unit)

    # Compounds (C{n})
    for unit in [
        {
            "id": "C2",
            "type": "compound",
            "properties": {
                "hanzi": "包子",
                "pinyin": "bāozi",
                "english": "baozi",
                "meaning": "steamed bun",
            },
            "connections": [],
        },
        {
            "id": "C1",
            "type": "compound",
            "properties": {
                "hanzi": "猫",
                "pinyin": "māo",
                "english": "cat",
                "meaning": "feline",
            },
            "connections": [],
        },
        {
            "id": "C3",
            "type": "compound",
            "properties": {
                "hanzi": "综合",
                "pinyin": "zōnghé",
                "english": "comprehensive",
                "meaning": "synthesis/comprehensive",
            },
            "connections": [],
        },
    ]:
        write_unit(vault, unit)


# ---------------------------------------------------------------------------
# AC1 — response shape
# ---------------------------------------------------------------------------


def test_vault_list_response_shape(client_with_vault):
    """AC1: GET /api/vault/list?type=sentence returns 200 with exactly the
    documented top-level keys: type, total, limit, offset, sort, items."""
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=sentence")
    assert response.status_code == 200, response.text
    body = response.json()

    # Top-level keys must be exactly the documented set.
    assert set(body.keys()) == {"type", "total", "limit", "offset", "sort", "items"}


# ---------------------------------------------------------------------------
# AC2 — item shape (no english/meaning)
# ---------------------------------------------------------------------------


def test_vault_list_items_have_no_english_or_meaning(client_with_vault):
    """AC2: each item has exactly id, name, snippet — no english/meaning."""
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=sentence")
    assert response.status_code == 200
    body = response.json()

    for item in body["items"]:
        assert set(item.keys()) == {"id", "name", "snippet"}, (
            f"item {item!r} has unexpected keys; want exactly id/name/snippet"
        )
        # english and meaning must not appear at the top level of any item
        assert "english" not in item
        assert "meaning" not in item


# ---------------------------------------------------------------------------
# AC3 — type filtering by id prefix
# ---------------------------------------------------------------------------


def test_vault_list_type_word_filters_by_w_prefix(client_with_vault):
    """AC3: type=word returns only W{n} units (not C{n} compounds)."""
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=word")
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]

    # Only W-prefixed ids
    assert all(id.startswith("W") for id in ids), f"got non-W ids: {ids}"
    # No C-prefixed ids
    assert not any(id.startswith("C") for id in ids), f"got C ids: {ids}"
    # Exactly our 3 words
    assert set(ids) == {"W1", "W2", "W3"}


def test_vault_list_type_compound_filters_by_c_prefix(client_with_vault):
    """AC3: type=compound returns only C{n} units (not W{n} words)."""
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=compound")
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]

    # Only C-prefixed ids
    assert all(id.startswith("C") for id in ids), f"got non-C ids: {ids}"
    # No W-prefixed ids
    assert not any(id.startswith("W") for id in ids), f"got W ids: {ids}"
    # Exactly our 3 compounds
    assert set(ids) == {"C1", "C2", "C3"}


def test_vault_list_type_sentence(client_with_vault):
    """AC3: type=sentence returns 200 with S-prefixed units."""
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=sentence")
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]

    assert all(id.startswith("S") for id in ids)
    assert set(ids) == {"S1", "S2", "S3"}


# ---------------------------------------------------------------------------
# AC4 — pagination
# ---------------------------------------------------------------------------


def test_vault_list_pagination_slice(client_with_vault):
    """AC4: limit=10&offset=0 and offset=1 return correct slices."""
    client, vault = client_with_vault
    _seed_vault(vault)

    first_page = client.get("/api/vault/list?type=sentence&limit=2&offset=0")
    assert first_page.status_code == 200
    body = first_page.json()
    assert body["total"] == 3
    assert body["offset"] == 0
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert [item["id"] for item in body["items"]] == ["S1", "S2"]

    second_page = client.get("/api/vault/list?type=sentence&limit=2&offset=1")
    assert second_page.status_code == 200
    body2 = second_page.json()
    assert body2["offset"] == 1
    assert len(body2["items"]) == 2
    assert [item["id"] for item in body2["items"]] == ["S2", "S3"]


# ---------------------------------------------------------------------------
# AC5 — sort by pinyin
# ---------------------------------------------------------------------------


def test_vault_list_sort_by_pinyin(client_with_vault):
    """AC5: sort=pinyin returns items in pinyin A→Z order.

    Compounds C1(māo), C2(bāozi), C3(zōnghé) sorted alphabetically by
    pinyin should be: bāozi, māo, zōnghé (i.e. C2, C1, C3).
    """
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=compound&sort=pinyin")
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]

    assert ids == ["C2", "C1", "C3"], (
        f"pinyin sort wrong: got {ids}; want [C2, C1, C3] "
        "(bāozi < māo < zōnghé)"
    )


def test_vault_list_sort_by_id_default(client_with_vault):
    """Default sort (no sort param) is id ascending, matching list_units_by_type."""
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=sentence")
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]

    assert ids == ["S1", "S2", "S3"], (
        f"default sort (id) wrong: got {ids}; want [S1, S2, S3]"
    )


# ---------------------------------------------------------------------------
# AC6 — unknown type → 422
# ---------------------------------------------------------------------------


def test_vault_list_unknown_type_returns_422(client_with_vault):
    """AC6: an unknown type value returns HTTP 422."""
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=paragraph")
    assert response.status_code == 422, (
        f"expected 422 for unknown type, got {response.status_code}"
    )


def test_vault_list_limit_validation(client_with_vault):
    """limit outside [1, 200] returns 422."""
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=sentence&limit=0")
    assert response.status_code == 422

    response = client.get("/api/vault/list?type=sentence&limit=201")
    assert response.status_code == 422


def test_vault_list_offset_validation(client_with_vault):
    """offset < 0 returns 422."""
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=sentence&offset=-1")
    assert response.status_code == 422


def test_vault_list_sort_validation(client_with_vault):
    """Unknown sort value returns 422."""
    client, vault = client_with_vault
    _seed_vault(vault)

    response = client.get("/api/vault/list?type=sentence&sort=created")
    assert response.status_code == 422
