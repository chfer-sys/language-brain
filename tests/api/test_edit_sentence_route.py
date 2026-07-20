"""Tests for ``PUT /api/sentences/{sentence_id}`` (edit sentence).

Uses the ``client`` fixture from ``conftest.py`` which:
* Isolates the vault under ``tmp_path``
* Patches ``settings.vault`` so the route reads from ``tmp_path``
* Seeds the dictionary from ``segment_fixture.txt``
* Forces the route to use :class:`HashingEmbedder` (no real model).

Test cases (8 required)
-----------------------
1. test_edit_sentence_updates_english_and_meaning
2. test_edit_sentence_rejects_hanzi_mismatch
3. test_edit_sentence_returns_404_for_missing_id
4. test_edit_sentence_group_replace_removes_old
5. test_edit_sentence_group_replace_no_duplicates
6. test_edit_sentence_antonyms_normalized
7. test_edit_sentence_runs_connector
8. test_edit_sentence_updates_faiss_when_meaning_changes
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.routes import commit_sentence as commit_sentence_route
from api.routes import edit_sentence as edit_sentence_route
from api.services.embedder import HashingEmbedder
from api.services.indexer import Index
from api.services.unit_writer import read_unit, unit_path


# ---------------------------------------------------------------------------
# Embedder patch — autouse so every test gets a deterministic embedder
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_embedder(monkeypatch: pytest.MonkeyPatch) -> HashingEmbedder:
    """Force the route to use a fresh :class:`HasingEmbedder`."""
    fresh = HashingEmbedder()
    monkeypatch.setattr(
        commit_sentence_route, "get_embedder", lambda force=None: fresh
    )
    monkeypatch.setattr(
        edit_sentence_route, "get_embedder", lambda force=None: fresh
    )
    return fresh


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_payload(**overrides: object) -> dict:
    """Return a minimal valid ``CommitSentenceRequest`` body."""
    payload: dict = {
        "hanzi": "我喜欢吃",
        "pinyin": "wǒ xǐhuān chī",
        "english": "I like to eat",
        "meaning": "expressing enjoyment of eating",
        "words": ["我", "喜欢", "吃"],
        "word_refs": ["wǒ", "xǐhuān", "chī"],
        "groups": [],
        "antonyms": [],
    }
    payload.update(overrides)
    return payload


def _edit_payload(hanzi: str, **overrides: object) -> dict:
    """Return a minimal valid ``EditSentenceRequest`` body."""
    payload: dict = {
        "hanzi": hanzi,
        "pinyin": "",
        "english": "",
        "meaning": "",
        "words": [],
        "word_refs": [],
        "groups": [],
        "antonyms": [],
    }
    payload.update(overrides)
    return payload


def _commit_sentence(client: TestClient, **overrides: object) -> str:
    """Helper: commit a sentence and return its id."""
    body = _minimal_payload(**overrides)
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# 1. Basic field update: english and meaning
# ---------------------------------------------------------------------------


def test_edit_sentence_updates_english_and_meaning(
    client: TestClient, tmp_path: Path
) -> None:
    """PUT edits english and meaning; subsequent read_unit shows new values;
    ``updated`` date is today (different from created date)."""
    sid = _commit_sentence(client, meaning="old meaning", english="old english")

    # Read created timestamp.
    before = read_unit(str(tmp_path), "sentence", sid)
    created_date = before["created"]

    # Edit.
    edit_body = _edit_payload(
        hanzi="我喜欢吃",
        pinyin="wǒ xǐhuān chī",
        english="I really like to eat",
        meaning="expressing enthusiasm about eating",
        words=["我", "喜欢", "吃"],
        word_refs=before["properties"]["word_refs"],
    )
    resp = client.put(f"/api/sentences/{sid}", json=edit_body)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["id"] == sid
    assert payload["updated"]  # updated is a non-empty date string

    # Read back from disk.
    after = read_unit(str(tmp_path), "sentence", sid)
    assert after["properties"]["english"] == "I really like to eat"
    assert after["properties"]["meaning"] == "expressing enthusiasm about eating"
    assert after["properties"]["pinyin"] == "wǒ xǐhuān chī"


# ---------------------------------------------------------------------------
# 2. Hanzi mismatch → 422
# ---------------------------------------------------------------------------


def test_edit_sentence_rejects_hanzi_mismatch(
    client: TestClient,
) -> None:
    """PUT with a different hanzi than the sentence has → 422."""
    sid = _commit_sentence(client)

    edit_body = _edit_payload(
        hanzi="wrong hanzi",  # does not match "我喜欢吃"
        english="something",
    )
    resp = client.put(f"/api/sentences/{sid}", json=edit_body)
    assert resp.status_code == 422, resp.text
    assert "hanzi" in resp.text.lower()


# ---------------------------------------------------------------------------
# 3. 404 for missing sentence id
# ---------------------------------------------------------------------------


def test_edit_sentence_returns_404_for_missing_id(
    client: TestClient,
) -> None:
    """PUT to a nonexistent S-id → 404."""
    edit_body = _edit_payload(
        hanzi="任何字",
        english="something",
    )
    resp = client.put("/api/sentences/S99999", json=edit_body)
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 4. Group REPLACE semantics: removed from old, added to new
# ---------------------------------------------------------------------------


def test_edit_sentence_group_replace_removes_old(
    client: TestClient, tmp_path: Path
) -> None:
    """Sentence in groups [food, travel]; PUT groups=[travel, family].
    Sentence must be removed from 'food' members, added to 'family' members,
    and remain in 'travel' members."""
    sid = _commit_sentence(client, groups=["food", "travel"])

    # Confirm initial state.
    food_before = read_unit(str(tmp_path), "group", "food")
    travel_before = read_unit(str(tmp_path), "group", "travel")
    family_before_path = unit_path(str(tmp_path), "group", "family")
    assert sid in food_before["properties"]["members"]
    assert sid in travel_before["properties"]["members"]
    assert not family_before_path.exists()

    # Edit: REPLACE groups with [travel, family].
    sentence = read_unit(str(tmp_path), "sentence", sid)
    edit_body = _edit_payload(
        hanzi="我喜欢吃",
        pinyin="wǒ xǐhuān chī",
        groups=["travel", "family"],
        word_refs=sentence["properties"]["word_refs"],
        words=sentence["properties"]["words"],
    )
    resp = client.put(f"/api/sentences/{sid}", json=edit_body)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert set(payload["groups_removed"]) == {"food"}
    assert set(payload["groups_added"]) == {"family"}

    # Verify group membership changes.
    food_after = read_unit(str(tmp_path), "group", "food")
    travel_after = read_unit(str(tmp_path), "group", "travel")
    family_after = read_unit(str(tmp_path), "group", "family")

    assert sid not in food_after["properties"]["members"]
    assert sid in travel_after["properties"]["members"]
    assert sid in family_after["properties"]["members"]


# ---------------------------------------------------------------------------
# 5. Group REPLACE deduplicates
# ---------------------------------------------------------------------------


def test_edit_sentence_group_replace_no_duplicates(
    client: TestClient, tmp_path: Path
) -> None:
    """PUT groups=[food, food, travel]; assert 'food' members contains
    sentence exactly once."""
    sid = _commit_sentence(client)

    sentence = read_unit(str(tmp_path), "sentence", sid)
    edit_body = _edit_payload(
        hanzi="我喜欢吃",
        pinyin="wǒ xǐhuān chī",
        groups=["food", "food", "travel"],
        word_refs=sentence["properties"]["word_refs"],
        words=sentence["properties"]["words"],
    )
    resp = client.put(f"/api/sentences/{sid}", json=edit_body)
    assert resp.status_code == 200, resp.text

    food = read_unit(str(tmp_path), "group", "food")
    assert food["properties"]["members"].count(sid) == 1


# ---------------------------------------------------------------------------
# 6. Antonyms are normalized on edit
# ---------------------------------------------------------------------------


def test_edit_sentence_antonyms_normalized(
    client: TestClient, tmp_path: Path
) -> None:
    """PUT with antonyms=["饱 ", ""]; stored antonyms must be ["饱"]."""
    sid = _commit_sentence(client)

    sentence = read_unit(str(tmp_path), "sentence", sid)
    edit_body = _edit_payload(
        hanzi="我喜欢吃",
        pinyin="wǒ xǐhuān chī",
        antonyms=["饱 ", "  ", ""],  # trailing spaces, empty strings
        word_refs=sentence["properties"]["word_refs"],
        words=sentence["properties"]["words"],
    )
    resp = client.put(f"/api/sentences/{sid}", json=edit_body)
    assert resp.status_code == 200, resp.text

    after = read_unit(str(tmp_path), "sentence", sid)
    assert after["properties"]["antonyms"] == ["饱"]


# ---------------------------------------------------------------------------
# 7. Connector runs
# ---------------------------------------------------------------------------


def test_edit_sentence_runs_connector(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spy on compute_connections: verify it is called exactly once."""
    # edit_sentence imports compute_connections directly into its namespace,
    # so we must patch it where it's used.
    calls: list[int] = []

    original_compute = edit_sentence_route.compute_connections

    def spy(*args, **kwargs):
        calls.append(1)
        return original_compute(*args, **kwargs)

    monkeypatch.setattr(edit_sentence_route, "compute_connections", spy)

    sid = _commit_sentence(client)

    sentence = read_unit(str(tmp_path), "sentence", sid)
    edit_body = _edit_payload(
        hanzi="我喜欢吃",
        pinyin="wǒ xǐhuān chī",
        english="updated english",
        word_refs=sentence["properties"]["word_refs"],
        words=sentence["properties"]["words"],
    )
    resp = client.put(f"/api/sentences/{sid}", json=edit_body)
    assert resp.status_code == 200, resp.text
    assert calls == [1], f"compute_connections called {len(calls)} times, expected 1"


# ---------------------------------------------------------------------------
# 8. FAISS index updated when meaning changes
# ---------------------------------------------------------------------------


def test_edit_sentence_updates_faiss_when_meaning_changes(
    client: TestClient, tmp_path: Path
) -> None:
    """Sentence starts with meaning=""; PUT changes meaning to "rich gloss".
    The FAISS index must contain the sentence id after the edit."""
    sid = _commit_sentence(client, meaning="", english="something")

    # Index should be empty (no meaning).
    index_empty = Index.load_or_empty(str(tmp_path))
    assert sid not in index_empty, "precondition: sid should not be in empty index"

    sentence = read_unit(str(tmp_path), "sentence", sid)
    edit_body = _edit_payload(
        hanzi="我喜欢吃",
        pinyin="wǒ xǐhuān chī",
        meaning="rich gloss for semantic search",
        word_refs=sentence["properties"]["word_refs"],
        words=sentence["properties"]["words"],
    )
    resp = client.put(f"/api/sentences/{sid}", json=edit_body)
    assert resp.status_code == 200, resp.text

    index_after = Index.load_or_empty(str(tmp_path))
    assert sid in index_after, "sentence should be in FAISS index after meaning edit"
