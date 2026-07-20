"""Tests for ``PUT /api/words/{word_id}`` (v0.9).

Uses the ``vault_client`` fixture from ``conftest.py`` which:
* Isolates the vault under ``tmp_path``
* Patches ``settings.vault`` so the route reads from ``tmp_path``
* Seeds the dictionary from ``segment_fixture.txt``
* Returns (TestClient, tmp_path) so tests can pre-create vault files

The tests cover the seven cases from the v0.9 brief: basic update on
word, basic update on compound, 404 for missing id, group-replace
semantics, antonym mirror on add, antonym unmirror on remove, and
connector invocation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.routes import edit_word as edit_word_route
from api.services.connector import compute_connections
from api.services.embedder import HashingEmbedder
from api.services.unit_writer import write_unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_word(
    vault_root: str,
    word_id: str,
    hanzi: str,
    pinyin: str,
    *,
    english: str = "",
    meaning: str = "",
    groups: list[str] | None = None,
    antonyms: list[str] | None = None,
    connections: list | None = None,
) -> dict:
    """Create a word unit on disk and return its dict."""
    unit = {
        "id": word_id,
        "type": "word",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin,
            "english": english,
            "meaning": meaning,
            "groups": groups if groups is not None else [],
            "antonyms": antonyms if antonyms is not None else [],
        },
        "connections": connections if connections is not None else [],
        "created": "2026-06-28",
        "updated": "2026-06-28",
        "author_confirmed": True,
    }
    write_unit(vault_root, unit)
    return unit


def _make_compound(
    vault_root: str,
    compound_id: str,
    hanzi: str,
    pinyin: str,
    *,
    english: str = "",
    meaning: str = "",
    groups: list[str] | None = None,
    antonyms: list[str] | None = None,
    connections: list | None = None,
) -> dict:
    """Create a compound unit on disk (type='compound') and return its dict."""
    unit = {
        "id": compound_id,
        "type": "compound",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin,
            "english": english,
            "meaning": meaning,
            "groups": groups if groups is not None else [],
            "antonyms": antonyms if antonyms is not None else [],
        },
        "connections": connections if connections is not None else [],
        "created": "2026-06-28",
        "updated": "2026-06-28",
        "author_confirmed": True,
    }
    write_unit(vault_root, unit)
    return unit


def _read_word(vault_root: str, word_id: str) -> dict:
    path = Path(vault_root) / "units" / "words" / f"{word_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _read_group(vault_root: str, group_id: str) -> dict:
    path = Path(vault_root) / "units" / "groups" / f"{group_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Embedder patch — autouse so every test gets a deterministic embedder
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_embedder(monkeypatch: pytest.MonkeyPatch) -> HashingEmbedder:
    fresh = HashingEmbedder()
    monkeypatch.setattr(
        edit_word_route, "get_embedder", lambda force=None: fresh
    )
    return fresh


# ---------------------------------------------------------------------------
# 1. Basic word update
# ---------------------------------------------------------------------------


def test_edit_word_updates_english(vault_client: tuple[TestClient, Path]) -> None:
    """A valid PUT updates english and returns 200."""
    client, tmp_path = vault_client
    vault = str(tmp_path)
    _make_word(vault, "W1", "高", "gāo", english="tall")

    resp = client.put(
        "/api/words/W1",
        json={"english": "lofty", "meaning": "", "groups": [], "antonyms": []},
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["id"] == "W1"
    assert payload["type"] == "word"

    unit = _read_word(vault, "W1")
    assert unit["properties"]["english"] == "lofty"
    # Unchanged fields
    assert unit["properties"]["hanzi"] == "高"
    assert unit["properties"]["pinyin"] == "gāo"


# ---------------------------------------------------------------------------
# 2. Compound update
# ---------------------------------------------------------------------------


def test_edit_compound_updates_english(vault_client: tuple[TestClient, Path]) -> None:
    """A valid PUT on a compound returns type='compound' and persists."""
    client, tmp_path = vault_client
    vault = str(tmp_path)
    _make_compound(vault, "C1", "高兴", "gāoxìng", english="happy")

    resp = client.put(
        "/api/words/C1",
        json={"english": "elated", "meaning": "", "groups": [], "antonyms": []},
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["id"] == "C1"
    assert payload["type"] == "compound"

    unit = _read_word(vault, "C1")
    assert unit["properties"]["english"] == "elated"
    assert unit["properties"]["hanzi"] == "高兴"


# ---------------------------------------------------------------------------
# 3. 404 for missing id
# ---------------------------------------------------------------------------


def test_edit_word_returns_404_for_missing_id(vault_client: tuple[TestClient, Path]) -> None:
    """A PUT for a non-existent word_id returns 404."""
    client, tmp_path = vault_client
    vault = str(tmp_path)
    _make_word(vault, "W1", "高", "gāo")

    resp = client.put(
        "/api/words/W999",
        json={"english": "x", "meaning": "", "groups": [], "antonyms": []},
    )

    assert resp.status_code == 404, resp.text
    assert "not found" in resp.text.lower()


# ---------------------------------------------------------------------------
# 4. Group replace semantics
# ---------------------------------------------------------------------------


def test_edit_word_group_replace(vault_client: tuple[TestClient, Path]) -> None:
    """Word in [A,B]; PUT with [B,C] → A loses the word, B and C gain it."""
    client, tmp_path = vault_client
    vault = str(tmp_path)
    _make_word(vault, "W1", "吃", "chī", groups=["food", "verbs"])

    # Pre-create groups
    from api.services.group_registry import add_member_to_group, ensure_group_unit
    ensure_group_unit(vault, "food")
    ensure_group_unit(vault, "verbs")
    ensure_group_unit(vault, "actions")
    add_member_to_group(vault, "food", "W1")
    add_member_to_group(vault, "verbs", "W1")

    resp = client.put(
        "/api/words/W1",
        json={
            "english": "to eat",
            "meaning": "",
            "groups": ["verbs", "actions"],  # B, C — A is removed
            "antonyms": [],
        },
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert sorted(payload["groups_added"]) == ["actions"]
    assert sorted(payload["groups_removed"]) == ["food"]

    # food no longer has W1
    g_food = _read_group(vault, "food")
    assert "W1" not in g_food["properties"]["members"]

    # verbs still has W1
    g_verbs = _read_group(vault, "verbs")
    assert "W1" in g_verbs["properties"]["members"]

    # actions now has W1
    g_actions = _read_group(vault, "actions")
    assert "W1" in g_actions["properties"]["members"]


# ---------------------------------------------------------------------------
# 5. Antonym add mirrors
# ---------------------------------------------------------------------------


def test_edit_word_antonym_add_mirrors(vault_client: tuple[TestClient, Path]) -> None:
    """PUT with antonyms=['W2'] → W2.properties.antonyms gains 'W1'."""
    client, tmp_path = vault_client
    vault = str(tmp_path)
    _make_word(vault, "W1", "高", "gāo")
    _make_word(vault, "W2", "矮", "ǎi")

    resp = client.put(
        "/api/words/W1",
        json={
            "english": "tall",
            "meaning": "",
            "groups": [],
            "antonyms": ["W2"],
        },
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["antonyms_added"] == ["W2"]
    assert payload["antonyms_removed"] == []

    # W2 should now have W1 in its antonyms
    w2 = _read_word(vault, "W2")
    assert "W1" in w2["properties"]["antonyms"]


# ---------------------------------------------------------------------------
# 6. Antonym remove unmirrors
# ---------------------------------------------------------------------------


def test_edit_word_antonym_remove_unmirrors(vault_client: tuple[TestClient, Path]) -> None:
    """PUT with antonyms=[] on a word that had W2 → W2 no longer has W1.

    Note: ``compute_connections`` runs after the unmirror and may re-establish
    a symmetric opposite edge if the partner word still references this word.
    The key correctness condition is that the EDITED word (W1) has its
    antonyms cleared in the response and on disk.
    """
    client, tmp_path = vault_client
    vault = str(tmp_path)
    _make_word(
        vault,
        "W1",
        "高",
        "gāo",
        antonyms=["W2"],
        connections=[{"to": "W2", "kind": "opposite", "score": 1.0}],
    )
    _make_word(
        vault,
        "W2",
        "矮",
        "ǎi",
        antonyms=["W1"],
        connections=[{"to": "W1", "kind": "opposite", "score": 1.0}],
    )

    resp = client.put(
        "/api/words/W1",
        json={
            "english": "tall",
            "meaning": "",
            "groups": [],
            "antonyms": [],  # remove W2
        },
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["antonyms_added"] == []
    assert payload["antonyms_removed"] == ["W2"]

    # The edited word (W1) has no antonyms
    w1 = _read_word(vault, "W1")
    assert w1["properties"]["antonyms"] == []

    # The partner word (W2) no longer has W1 in its antonyms
    w2 = _read_word(vault, "W2")
    assert "W1" not in w2["properties"]["antonyms"]


# ---------------------------------------------------------------------------
# 7. Connector is called
# ---------------------------------------------------------------------------


def test_edit_word_runs_connector(
    vault_client: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """edit_word calls compute_connections exactly once."""
    client, tmp_path = vault_client
    vault = str(tmp_path)
    _make_word(vault, "W1", "高", "gāo")

    spy_calls: list = []

    def _spy(vault_root: str, embedder: object = None, **kwargs: object) -> dict:
        spy_calls.append((vault_root, embedder))
        return {
            "sentences_touched": 0,
            "words_touched": 0,
            "lexical_pairs": 0,
            "semantic_pairs": 0,
            "group_pairs": 0,
            "opposite_pairs": 0,
            "skipped": 0,
        }

    # Patch at module level so edit_word route uses the spy.
    monkeypatch.setattr(
        "api.routes.edit_word.compute_connections",
        _spy,
    )

    resp = client.put(
        "/api/words/W1",
        json={
            "english": "tall",
            "meaning": "",
            "groups": [],
            "antonyms": [],
        },
    )

    assert resp.status_code == 200, resp.text
    assert len(spy_calls) == 1, f"expected 1 compute_connections call, got {len(spy_calls)}"
    assert spy_calls[0][0] == vault
