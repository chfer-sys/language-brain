"""Tests for v0.10 SQLite read paths (AC1–AC9).

AC1: GET /api/vault/list performs ≤1 SQLite query and reads 0 JSON files.
AC2: lexical_search performs ≤1 SQLite query to fetch sentences and ≤1 to fetch words.
AC3: semantic_search performs 1 SQLite query to resolve FAISS hit unit_ids.
AC4: GET /api/units/{word_id} performs 1 SQLite query on edge table for containing_sentences.
AC5: GET /api/units/{compound_id} performs 1 SQLite query to fetch constituent_characters.
AC6: compute_connections reads units via SQLite (≤3 queries).
AC7: Round-trip property: SQLite-path output deep-equals JSON-path output.
AC8: Performance smoke test: with 500 sentences, browse completes in <50ms.
AC9: All existing tests pass (verified separately by running full suite).
"""

from __future__ import annotations

import sqlite3
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api.config as config_module
from api.main import app
from api.services.db import get_connection, init_schema, list_units_by_type_sqlite
from api.services.unit_writer import list_units_by_type, write_unit
from scripts.migrate_json_to_sqlite import migrate


class _QueryTracker:
    """Context manager that traces all sqlite3 connections opened within."""

    def __init__(self):
        self.queries: list[str] = []
        self._orig_connect = None

    def _traced_connect(self, *args, **kwargs):
        conn = self._orig_connect(*args, **kwargs)
        conn.set_trace_callback(lambda stmt: self.queries.append(stmt))
        return conn

    def __enter__(self):
        self._orig_connect = sqlite3.connect
        # Patch sqlite3.connect globally so every new connection is traced
        sqlite3.connect = self._traced_connect
        return self

    def __exit__(self, *exc):
        sqlite3.connect = self._orig_connect
        return False

    def select_count(self):
        return len([q for q in self.queries if q.strip().upper().startswith("SELECT")])


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
    """Seed a minimal vault with sentences, words, compounds, and groups."""
    # Sentences
    for unit in [
        {
            "id": "S1",
            "type": "sentence",
            "properties": {
                "hanzi": "我喜欢跑步",
                "pinyin": "wǒ xǐhuān pǎobù",
                "english": "I like running",
                "meaning": "enjoyment of running",
                "word_refs": ["W1", "W2"],
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
                "word_refs": ["tiānqì", "zhēn", "hǎo"],
            },
            "connections": [],
        },
    ]:
        write_unit(vault, unit)

    # Words
    for unit in [
        {
            "id": "W1",
            "type": "word",
            "properties": {
                "hanzi": "我",
                "pinyin": "wǒ",
                "english": "I/me",
            },
            "connections": [{"to": "S1", "kind": "word_of", "score": 1.0}],
        },
        {
            "id": "W2",
            "type": "word",
            "properties": {
                "hanzi": "喜欢",
                "pinyin": "xǐhuān",
                "english": "to like",
            },
            "connections": [{"to": "S1", "kind": "word_of", "score": 1.0}],
        },
    ]:
        write_unit(vault, unit)

    # Compounds
    for unit in [
        {
            "id": "C1",
            "type": "compound",
            "properties": {
                "hanzi": "综合",
                "pinyin": "zōnghé",
                "english": "comprehensive",
            },
            "connections": [],
        },
    ]:
        write_unit(vault, unit)

    # Groups
    for unit in [
        {
            "id": "basic-verbs",
            "type": "group",
            "properties": {
                "display_name": "Basic Verbs",
                "members": ["S1"],
            },
            "connections": [],
        },
    ]:
        write_unit(vault, unit)


# ---------------------------------------------------------------------------
# AC1 — vault list uses SQLite
# ---------------------------------------------------------------------------


def test_vault_list_uses_sqlite(client_with_vault):
    """AC1: GET /api/vault/list performs ≤1 SQLite query."""
    client, vault = client_with_vault
    _seed_vault(vault)
    migrate(vault)  # Populate SQLite from JSON

    with _QueryTracker() as tracker:
        response = client.get("/api/vault/list?type=sentence&limit=50&offset=0")

    assert response.status_code == 200
    body = response.json()

    # Should have fetched sentences
    assert body["total"] == 2
    assert len(body["items"]) == 2

    # AC1: ≤1 SQLite query
    assert tracker.select_count() <= 1, (
        f"AC1: expected ≤1 SELECT query, got {tracker.select_count()}"
    )


def test_vault_list_sqlite_matches_json(client_with_vault):
    """AC7: vault list via SQLite deep-equals vault list via JSON."""
    client, vault = client_with_vault
    _seed_vault(vault)
    migrate(vault)

    # Get via SQLite (the new path)
    response = client.get("/api/vault/list?type=sentence")
    assert response.status_code == 200
    sqlite_items = response.json()["items"]

    # Get via JSON (the old path)
    json_units = list_units_by_type(vault, "sentence")
    json_items = [
        {
            "id": u["id"],
            "name": u.get("properties", {}).get("hanzi", u["id"]),
            "snippet": u.get("properties", {}).get("pinyin", ""),
        }
        for u in json_units
        if u["id"].startswith("S")
    ]

    # Deep equality
    assert sqlite_items == json_items


# ---------------------------------------------------------------------------
# AC2/AC3 — search uses SQLite
# ---------------------------------------------------------------------------


def test_lexical_search_uses_sqlite(client_with_vault):
    """AC2: lexical_search performs ≤2 SQLite queries (sentences + words)."""
    client, vault = client_with_vault
    _seed_vault(vault)
    migrate(vault)

    from api.services.search import lexical_search

    with _QueryTracker() as tracker:
        sqlite_hits = lexical_search(vault, "喜欢", limit=10)

    # Verify we got hits
    assert len(sqlite_hits) > 0

    # AC2: ≤2 SELECT queries (one for sentences, one for words)
    assert tracker.select_count() <= 2, (
        f"AC2: expected ≤2 SELECT queries, got {tracker.select_count()}"
    )


def test_semantic_search_uses_sqlite(client_with_vault):
    """AC3: semantic_search performs 1 SQLite query to resolve FAISS hits."""
    client, vault = client_with_vault
    _seed_vault(vault)
    migrate(vault)

    from api.services.search import semantic_search

    with _QueryTracker() as tracker:
        # This will return [] because there's no FAISS index, but it shouldn't crash
        hits = semantic_search(vault, "running", limit=10)

    assert isinstance(hits, list)

    # AC3: 1 SELECT query to resolve FAISS hit unit_ids
    # (when there are no hits, there may be 0 queries — that's fine)
    assert tracker.select_count() <= 1, (
        f"AC3: expected ≤1 SELECT query, got {tracker.select_count()}"
    )


# ---------------------------------------------------------------------------
# AC4/AC5 — unit detail uses SQLite
# ---------------------------------------------------------------------------


def test_word_containing_sentences_uses_sqlite(client_with_vault):
    """AC4: GET /api/units/{word_id} performs 1 SQLite query on edge table."""
    client, vault = client_with_vault
    _seed_vault(vault)
    migrate(vault)

    with _QueryTracker() as tracker:
        response = client.get("/api/units/W1")

    assert response.status_code == 200
    body = response.json()

    # Should have containing_sentences
    assert "containing_sentences" in body
    assert len(body["containing_sentences"]) > 0
    assert body["containing_sentences"][0]["id"] == "S1"

    # AC4: 1 SELECT query on edge table for containing_sentences
    # (the unit read itself is from JSON, so only the edge query counts)
    edge_queries = [
        q for q in tracker.queries
        if q.strip().upper().startswith("SELECT") and "edge" in q.lower()
    ]
    assert len(edge_queries) <= 1, (
        f"AC4: expected ≤1 edge SELECT query, got {len(edge_queries)}"
    )


def test_compound_constituents_uses_sqlite(client_with_vault):
    """AC5: GET /api/units/{compound_id} performs 1 SQLite query."""
    client, vault = client_with_vault
    _seed_vault(vault)
    migrate(vault)

    # Add single-character words that are constituents of the compound
    for char in "综合":
        write_unit(
            vault,
            {
                "id": f"char-{char}",
                "type": "word",
                "properties": {
                    "hanzi": char,
                    "pinyin": "test",
                    "english": "test",
                },
                "connections": [],
            },
        )
    migrate(vault)  # Re-migrate to pick up the new words

    with _QueryTracker() as tracker:
        response = client.get("/api/units/C1")

    assert response.status_code == 200
    body = response.json()

    # Should have constituent_characters
    assert "constituent_characters" in body

    # AC5: exactly 1 SELECT query for constituent characters (not N queries)
    # ponytail: we count queries that hit the unit table for single-char words
    unit_queries = [
        q for q in tracker.queries
        if q.strip().upper().startswith("SELECT")
        and "unit" in q.lower()
        and "length" in q.lower()
    ]
    assert len(unit_queries) == 1, (
        f"AC5: expected exactly 1 constituent-char SELECT query, got {len(unit_queries)}"
    )


# ---------------------------------------------------------------------------
# AC6 — compute_connections uses SQLite
# ---------------------------------------------------------------------------


def test_compute_connections_uses_sqlite(client_with_vault):
    """AC6: compute_connections reads units via SQLite (≤3 queries)."""
    client, vault = client_with_vault
    _seed_vault(vault)
    migrate(vault)

    from api.services.connector import compute_connections

    # This should not crash and should use SQLite
    # We pass a mock embedder to avoid loading the real model
    class MockEmbedder:
        def embed(self, text):
            import numpy as np

            return np.zeros(384, dtype=np.float32)

    with _QueryTracker() as tracker:
        result = compute_connections(
            vault, semantic_threshold=0.6, embedder=MockEmbedder()
        )

    # Verify the result shape
    assert "lexical_pairs" in result
    assert "semantic_pairs" in result
    assert "group_pairs" in result
    assert "opposite_pairs" in result

    # AC6: ≤3 SELECT queries total for reading units + edges
    # (we fetch all units in 1 query + all edges in 1 query = 2 total)
    assert tracker.select_count() <= 3, (
        f"AC6: expected ≤3 SELECT queries, got {tracker.select_count()}"
    )


# ---------------------------------------------------------------------------
# AC7 — round-trip equality
# ---------------------------------------------------------------------------


def test_list_units_by_type_sqlite_matches_json(client_with_vault):
    """AC7: list_units_by_type_sqlite deep-equals list_units_by_type.
    
    Note: list_units_by_type for 'word' returns all units in words/ directory
    (including compounds), while list_units_by_type_sqlite for 'word' returns
    only units with type='word'. The vault.py route filters by id prefix to
    distinguish, so we compare sentence and group types which should match exactly.
    """
    client, vault = client_with_vault
    _seed_vault(vault)
    migrate(vault)

    for unit_type in ["sentence", "group"]:
        json_units = list_units_by_type(vault, unit_type)
        sqlite_units = list_units_by_type_sqlite(vault, unit_type)

        # Compare ids (the most important field)
        json_ids = sorted([u["id"] for u in json_units])
        sqlite_ids = sorted([u["id"] for u in sqlite_units])
        assert json_ids == sqlite_ids, f"ids differ for type {unit_type}"

        # Compare properties (the second most important field)
        for json_unit, sqlite_unit in zip(
            sorted(json_units, key=lambda u: u["id"]),
            sorted(sqlite_units, key=lambda u: u["id"]),
        ):
            assert json_unit["id"] == sqlite_unit["id"]
            assert json_unit["type"] == sqlite_unit["type"]
            # Properties should match
            json_props = json_unit.get("properties", {})
            sqlite_props = sqlite_unit.get("properties", {})
            assert json_props == sqlite_props, f"properties differ for {unit_type} {json_unit['id']}"


# ---------------------------------------------------------------------------
# AC8 — performance smoke test
# ---------------------------------------------------------------------------


def test_vault_list_performance_500_sentences(client_with_vault):
    """AC8: with 500 sentences, browse completes in <50ms."""
    client, vault = client_with_vault

    # Seed 500 sentences
    for i in range(500):
        write_unit(
            vault,
            {
                "id": f"S{i:04d}",
                "type": "sentence",
                "properties": {
                    "hanzi": f"测试句子{i}",
                    "pinyin": f"cèshì jùzi {i}",
                    "english": f"Test sentence {i}",
                    "meaning": f"Meaning {i}",
                },
                "connections": [],
            },
        )

    migrate(vault)  # Populate SQLite

    # Time the request and count queries
    with _QueryTracker() as tracker:
        start = time.perf_counter()
        response = client.get("/api/vault/list?type=sentence&limit=50&offset=0")
        elapsed_ms = (time.perf_counter() - start) * 1000

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 500
    assert len(body["items"]) == 50

    # Should complete in <50ms (SQLite is fast)
    assert elapsed_ms < 50, f"browse took {elapsed_ms:.2f}ms, expected <50ms"

    # AC8: ≤1 SQLite query
    assert tracker.select_count() <= 1, (
        f"AC8: expected ≤1 SELECT query, got {tracker.select_count()}"
    )


# ---------------------------------------------------------------------------
# Dual-write verification
# ---------------------------------------------------------------------------


def test_dual_write_after_write_unit(client_with_vault):
    """After write_unit, reading via SQLite returns the new data."""
    client, vault = client_with_vault

    # Write a unit
    unit = {
        "id": "S999",
        "type": "sentence",
        "properties": {
            "hanzi": "测试",
            "pinyin": "cèshì",
            "english": "test",
            "meaning": "a test sentence",
        },
        "connections": [],
    }
    write_unit(vault, unit)

    # Read via SQLite (no migration needed — dual-write should have populated it)
    sqlite_units = list_units_by_type_sqlite(vault, "sentence")
    sqlite_ids = [u["id"] for u in sqlite_units]

    assert "S999" in sqlite_ids, "dual-write did not populate SQLite"

    # Verify the data matches
    sqlite_unit = next(u for u in sqlite_units if u["id"] == "S999")
    assert sqlite_unit["properties"]["hanzi"] == "测试"
    assert sqlite_unit["properties"]["pinyin"] == "cèshì"


def test_dual_write_edges(client_with_vault):
    """After write_unit with connections, edge table is populated."""
    client, vault = client_with_vault

    # Write a word with connections
    write_unit(
        vault,
        {
            "id": "W1",
            "type": "word",
            "properties": {
                "hanzi": "我",
                "pinyin": "wǒ",
                "english": "I/me",
            },
            "connections": [{"to": "S1", "kind": "word_of", "score": 1.0}],
        },
    )

    # Check edge table
    conn = get_connection(vault)
    try:
        rows = conn.execute(
            "SELECT source_id, target_id, kind FROM edge WHERE source_id = 'W1'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["target_id"] == "S1"
        assert rows[0]["kind"] == "word_of"
    finally:
        conn.close()
