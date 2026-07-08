"""Tests for scripts/migrate_json_to_sqlite.py."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.migrate_json_to_sqlite import migrate


def _write_unit(
    vault_root: Path,
    unit_type: str,
    unit_id: str,
    *,
    extra_properties: dict | None = None,
    word_refs: list[str] | None = None,
    members: list[str] | None = None,
    antonyms: list[str] | None = None,
    connections: list[dict] | None = None,
) -> None:
    """Helper: write a JSON unit file with the schema the live vault uses."""
    plural = {"word": "words", "sentence": "sentences", "group": "groups"}[unit_type]
    d = vault_root / "units" / plural
    d.mkdir(parents=True, exist_ok=True)
    props = {
        "hanzi": unit_id,
        "pinyin": unit_id,
        "english": f"english for {unit_id}",
        "meaning": "",
        "groups": [],
        "antonyms": antonyms or [],
    }
    if unit_type == "sentence":
        props["words"] = list(word_refs or [])
        props["word_refs"] = list(word_refs or [])
    if unit_type == "group":
        props["display_name"] = ""
        props["description"] = ""
        props["members"] = list(members or [])
    if extra_properties:
        props.update(extra_properties)
    payload = {
        "id": unit_id,
        "type": unit_type,
        "name": unit_id,
        "properties": props,
        "connections": connections or [],
        "created": "2026-07-01",
        "updated": "2026-07-01",
        "author_confirmed": True,
    }
    (d / f"{unit_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def test_migrate_empty_vault(tmp_path: Path) -> None:
    """Empty vault: migration runs without error, zero rows inserted."""
    (tmp_path / "units").mkdir()
    counts = migrate(str(tmp_path))
    assert counts == {"unit": 0, "edge": 0}


def test_migrate_single_word(tmp_path: Path) -> None:
    (tmp_path / "units").mkdir()
    _write_unit(tmp_path, "word", "w1")
    counts = migrate(str(tmp_path))
    assert counts["unit"] == 1
    conn = sqlite3.connect(str(tmp_path / "index" / "vault.db"))
    try:
        row = conn.execute("SELECT id, type, name, english FROM unit").fetchone()
        assert row[0] == "w1"
        assert row[1] == "word"
        assert row[2] == "w1"
        assert row[3] == "english for w1"
    finally:
        conn.close()


def test_migrate_three_unit_types(tmp_path: Path) -> None:
    (tmp_path / "units").mkdir()
    _write_unit(tmp_path, "word", "w1")
    _write_unit(tmp_path, "sentence", "s1", word_refs=["w1"])
    _write_unit(tmp_path, "group", "g1", members=["s1"])
    counts = migrate(str(tmp_path))
    assert counts["unit"] == 3
    conn = sqlite3.connect(str(tmp_path / "index" / "vault.db"))
    try:
        types = {r[0] for r in conn.execute("SELECT DISTINCT type FROM unit").fetchall()}
        assert types == {"word", "sentence", "group"}
    finally:
        conn.close()


def test_migrate_word_refs_become_edges(tmp_path: Path) -> None:
    (tmp_path / "units").mkdir()
    _write_unit(tmp_path, "word", "w1")
    _write_unit(tmp_path, "word", "w2")
    _write_unit(tmp_path, "sentence", "s1", word_refs=["w1", "w2"])
    migrate(str(tmp_path))
    conn = sqlite3.connect(str(tmp_path / "index" / "vault.db"))
    try:
        edges = conn.execute(
            "SELECT source_id, target_id, kind FROM edge WHERE source_id='s1' AND kind='word_of'"
        ).fetchall()
        targets = {e[1] for e in edges}
        assert targets == {"w1", "w2"}
    finally:
        conn.close()


def test_migrate_members_become_edges(tmp_path: Path) -> None:
    (tmp_path / "units").mkdir()
    _write_unit(tmp_path, "sentence", "s1")
    _write_unit(tmp_path, "sentence", "s2")
    _write_unit(tmp_path, "group", "g1", members=["s1", "s2"])
    migrate(str(tmp_path))
    conn = sqlite3.connect(str(tmp_path / "index" / "vault.db"))
    try:
        edges = conn.execute(
            "SELECT target_id FROM edge WHERE source_id='g1' AND kind='group_member'"
        ).fetchall()
        targets = {e[0] for e in edges}
        assert targets == {"s1", "s2"}
    finally:
        conn.close()


def test_migrate_antonyms_become_edges(tmp_path: Path) -> None:
    (tmp_path / "units").mkdir()
    _write_unit(tmp_path, "word", "w1", antonyms=["w2"])
    _write_unit(tmp_path, "word", "w2")
    migrate(str(tmp_path))
    conn = sqlite3.connect(str(tmp_path / "index" / "vault.db"))
    try:
        edges = conn.execute(
            "SELECT target_id FROM edge WHERE source_id='w1' AND kind='antonym'"
        ).fetchall()
        assert len(edges) == 1
        assert edges[0][0] == "w2"
    finally:
        conn.close()


def test_migrate_connections_become_edges(tmp_path: Path) -> None:
    (tmp_path / "units").mkdir()
    _write_unit(tmp_path, "sentence", "s1")
    _write_unit(tmp_path, "sentence", "s2")
    _write_unit(
        tmp_path,
        "sentence",
        "s1",
        connections=[{"to": "s2", "kind": "lexical", "score": 0.5}],
    )
    migrate(str(tmp_path))
    conn = sqlite3.connect(str(tmp_path / "index" / "vault.db"))
    try:
        row = conn.execute(
            "SELECT target_id, kind, score FROM edge WHERE source_id='s1' AND kind='lexical'"
        ).fetchone()
        assert row[0] == "s2"
        assert row[1] == "lexical"
        assert abs(row[2] - 0.5) < 1e-9
    finally:
        conn.close()


def test_migrate_idempotent(tmp_path: Path) -> None:
    (tmp_path / "units").mkdir()
    _write_unit(tmp_path, "word", "w1")
    _write_unit(tmp_path, "sentence", "s1", word_refs=["w1"])
    first = migrate(str(tmp_path))
    second = migrate(str(tmp_path))
    assert first == second


def test_migrate_dry_run_makes_no_writes(tmp_path: Path) -> None:
    (tmp_path / "units").mkdir()
    _write_unit(tmp_path, "word", "w1")
    _write_unit(tmp_path, "sentence", "s1", word_refs=["w1"])
    migrate(str(tmp_path), dry_run=True)
    db_path = tmp_path / "index" / "vault.db"
    assert not db_path.exists()


def test_migrate_indexes_fts(tmp_path: Path) -> None:
    (tmp_path / "units").mkdir()
    _write_unit(tmp_path, "sentence", "s1", extra_properties={"english": "I want to eat"})
    migrate(str(tmp_path))
    conn = sqlite3.connect(str(tmp_path / "index" / "vault.db"))
    try:
        rows = conn.execute(
            "SELECT id FROM unit_fts WHERE unit_fts MATCH 'want'"
        ).fetchall()
        assert any(r[0] == "s1" for r in rows)
    finally:
        conn.close()


def test_migrate_round_trip_against_live_vault(tmp_path_with_live_vault: Path) -> None:
    """The migration of a copy of the real vault produces the right row counts."""
    counts = migrate(str(tmp_path_with_live_vault))
    # The live vault has 12 sentences, 32 words, 10 groups (~54 total).
    assert counts["unit"] >= 50
    assert counts["unit"] <= 70


@pytest.fixture
def tmp_path_with_live_vault(tmp_path: Path) -> Path:
    """Copy the live vault into tmp_path for migration tests.

    Resolves the live vault relative to the repo root. Works both on
    the host (``/Users/christoferi/.../vault/units``) and inside the
    docker test container (``/work/vault/units``).
    """
    import shutil

    # tests/scripts/ is two levels below the repo root.
    repo_root = Path(__file__).resolve().parents[2]
    src = repo_root / "vault" / "units"
    if not src.exists():
        pytest.skip(f"live vault not present at {src}")
    dst = tmp_path / "units"
    shutil.copytree(src, dst)
    return tmp_path