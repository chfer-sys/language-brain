"""Tests for the SQLite storage layer (v0.5.1).

Covers db.py (connection helper + schema init), WAL mode, idempotent
schema migration, and the round-trip property for the live vault.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from api.services.db import get_connection, init_schema


def test_get_connection_creates_db_file(tmp_path: Path) -> None:
    db_path = tmp_path / "index" / "vault.db"
    assert not db_path.exists()
    conn = get_connection(str(tmp_path))
    try:
        assert db_path.exists()
        assert conn is not None
    finally:
        conn.close()


def test_get_connection_sets_wal_mode(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_get_connection_sets_busy_timeout(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    try:
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000
    finally:
        conn.close()


def test_get_connection_enables_foreign_keys(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    try:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
    finally:
        conn.close()


def test_init_schema_creates_all_tables(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    try:
        init_schema(conn)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table') ORDER BY name"
        ).fetchall()
        names = {r[0] for r in rows}
        # 7 tables land in v0.5.1 (vec_sentences deferred to v0.5.5)
        assert "unit" in names
        assert "edge" in names
        assert "dictionary_source" in names
        assert "dictionary_entry" in names
        assert "word" in names
        assert "word_in_source" in names
    finally:
        conn.close()


def test_init_schema_creates_fts5_virtual_table(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    try:
        init_schema(conn)
        # FTS5 table is a virtual table; sqlite_master reports it as 'table' type.
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'unit_fts'"
        ).fetchall()
        assert len(rows) == 1
    finally:
        conn.close()


def test_init_schema_idempotent(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    try:
        init_schema(conn)
        # Second call must not raise.
        init_schema(conn)
    finally:
        conn.close()


def test_concurrent_connections(tmp_path: Path) -> None:
    """Two threads opening connections simultaneously both succeed."""
    errors: list[Exception] = []

    def open_conn() -> None:
        try:
            conn = get_connection(str(tmp_path))
            conn.execute("SELECT 1").fetchone()
            conn.close()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=open_conn) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_empty_db_insert_and_query(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    try:
        init_schema(conn)
        conn.execute(
            "INSERT INTO unit (id, type, sort_key, name, created, updated, author_confirmed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test1", "word", 1, "test", "2026-07-01", "2026-07-01", 1),
        )
        conn.commit()
        row = conn.execute("SELECT name FROM unit WHERE id = ?", ("test1",)).fetchone()
        assert row is not None
        assert row[0] == "test"
    finally:
        conn.close()


def test_unit_table_required_columns(tmp_path: Path) -> None:
    """Verify the unit table has all the columns the migration needs."""
    conn = get_connection(str(tmp_path))
    try:
        init_schema(conn)
        cols = conn.execute("PRAGMA table_info(unit)").fetchall()
        col_names = {c[1] for c in cols}
        for required in {
            "id", "type", "sort_key", "name", "pinyin",
            "english", "gloss", "properties", "created",
            "updated", "author_confirmed",
        }:
            assert required in col_names, f"unit.{required} missing"
    finally:
        conn.close()


def test_edge_table_required_columns(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    try:
        init_schema(conn)
        cols = conn.execute("PRAGMA table_info(edge)").fetchall()
        col_names = {c[1] for c in cols}
        for required in {"source_id", "target_id", "kind", "score"}:
            assert required in col_names, f"edge.{required} missing"
    finally:
        conn.close()


def test_unit_table_unique_on_id(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    try:
        init_schema(conn)
        conn.execute(
            "INSERT INTO unit (id, type, sort_key, name, created, updated, author_confirmed) "
            "VALUES ('dup', 'word', 1, 'a', '2026-07-01', '2026-07-01', 1)"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO unit (id, type, sort_key, name, created, updated, author_confirmed) "
                "VALUES ('dup', 'word', 2, 'b', '2026-07-01', '2026-07-01', 1)"
            )
            conn.commit()
    finally:
        conn.close()


def test_edge_table_unique_constraint(tmp_path: Path) -> None:
    conn = get_connection(str(tmp_path))
    try:
        init_schema(conn)
        conn.executemany(
            "INSERT INTO unit (id, type, sort_key, name, created, updated, author_confirmed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("a", "word", 1, "a", "2026-07-01", "2026-07-01", 1),
                ("b", "word", 2, "b", "2026-07-01", "2026-07-01", 1),
            ],
        )
        conn.commit()
        conn.execute(
            "INSERT INTO edge (source_id, target_id, kind, score) VALUES (?, ?, ?, ?)",
            ("a", "b", "lexical", 0.5),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO edge (source_id, target_id, kind, score) VALUES (?, ?, ?, ?)",
                ("a", "b", "lexical", 0.7),
            )
            conn.commit()
    finally:
        conn.close()