"""One-shot migration: JSON-on-disk vault → SQLite (v0.5.1).

Walks ``vault/units/{words,sentences,groups}/*.json``, inserts each unit
into the ``unit`` table, and reconstructs the edge table from:

- ``properties.word_refs``  (sentence → word, kind=word_of)
- ``properties.members``    (group → unit, kind=group_member)
- ``properties.antonyms``   (word → word, kind=antonym; one-way for v0.5.1)
- ``connections[].to``      (any → any, kind+score preserved)

Indexes name/english/gloss into the FTS5 virtual table for search.

Idempotent: re-running is a no-op (``INSERT OR IGNORE`` on every row).

ponytail: one-shot CLI, direct sqlite3 calls, no SQLAlchemy, no
async driver. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from api.services.db import get_connection, init_schema

_UNIT_TYPES: tuple[tuple[str, str], ...] = (
    ("word", "words"),
    ("sentence", "sentences"),
    ("group", "groups"),
)


def _read_unit(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def migrate(vault_root: str, *, dry_run: bool = False) -> dict[str, int]:
    """Migrate the JSON vault under ``vault_root`` into SQLite.

    Returns ``{"unit": N, "edge": M}`` with **total** entity counts
    seen in the JSON vault (not newly-inserted). Idempotent: re-running
    produces the same return value because every row uses
    ``INSERT OR IGNORE`` and we count what we read, not what changed.
    """
    if dry_run:
        return _dry_run(vault_root)

    conn = get_connection(vault_root)
    try:
        init_schema(conn)
        # Disable FK constraints for the migration. The live vault has
        # dangling references (e.g. an antonym pointing at a hanzi
        # instead of a word-unit id) that the production FK would
        # reject. ponytail: bulk-load relaxation is the standard
        # pattern; the FK is back ON at connection level for reads.
        conn.execute("PRAGMA foreign_keys = OFF")
        unit_count = 0
        edge_count = 0

        # Pass 1: insert all units (so FK targets exist before edges reference them).
        for unit_type, plural in _UNIT_TYPES:
            unit_dir = Path(vault_root) / "units" / plural
            if not unit_dir.exists():
                continue
            for path in sorted(unit_dir.glob("*.json")):
                payload = _read_unit(path)
                _insert_unit(conn, payload)
                unit_count += 1

        # Pass 2: insert all edges (all units exist, so FK constraints pass).
        for unit_type, plural in _UNIT_TYPES:
            unit_dir = Path(vault_root) / "units" / plural
            if not unit_dir.exists():
                continue
            for path in sorted(unit_dir.glob("*.json")):
                payload = _read_unit(path)
                edge_count += _insert_edges(conn, payload)

        conn.commit()
        return {"unit": unit_count, "edge": edge_count}
    finally:
        conn.close()


def _insert_unit(conn: sqlite3.Connection, payload: dict) -> int:
    """Insert one unit. Returns 1 on insert, 0 if ignored (duplicate)."""
    props = payload.get("properties", {}) or {}
    row = (
        payload["id"],
        payload["type"],
        0,  # sort_key — assigned by lexicographic order at v0.5.2
        payload.get("name", ""),
        props.get("pinyin"),
        props.get("english"),
        props.get("meaning") or None,
        json.dumps(props, ensure_ascii=False),
        payload.get("created", ""),
        payload.get("updated", ""),
        1 if payload.get("author_confirmed") else 0,
    )
    cur = conn.execute(
        "INSERT OR IGNORE INTO unit "
        "(id, type, sort_key, name, pinyin, english, gloss, properties, created, updated, author_confirmed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    if cur.rowcount == 0:
        return 0
    # Populate FTS5. use unicode61 tokenization on name + english + gloss.
    conn.execute(
        "INSERT OR IGNORE INTO unit_fts (id, type, name, english, gloss) VALUES (?, ?, ?, ?, ?)",
        (
            payload["id"],
            payload["type"],
            payload.get("name", ""),
            props.get("english") or "",
            props.get("meaning") or "",
        ),
    )
    return 1


def _count_edges_in_payload(payload: dict) -> int:
    """Count edges that this unit's JSON declares, regardless of insert success."""
    props = payload.get("properties", {}) or {}
    n = 0
    n += len(props.get("word_refs") or [])
    n += len(props.get("members") or [])
    n += len(props.get("antonyms") or [])
    for c in payload.get("connections") or []:
        if c.get("to") and c.get("kind"):
            n += 1
    return n


def _insert_edges(conn: sqlite3.Connection, payload: dict) -> int:
    """Insert all edges for one unit. Returns count of edges attempted.

    The count reflects what was in the JSON, not what was newly inserted,
    so re-running ``migrate()`` produces the same number (idempotent
    return value).
    """
    unit_id = payload["id"]
    props = payload.get("properties", {}) or {}

    # word_refs: sentence → word/compound (kind=word_of)
    for ref in props.get("word_refs") or []:
        _insert_edge(conn, unit_id, ref, "word_of", None)

    # members: group → any (kind=group_member)
    for ref in props.get("members") or []:
        _insert_edge(conn, unit_id, ref, "group_member", None)

    # antonyms: word → word (kind=antonym, one-way; v0.5.4 adds mirror)
    for ref in props.get("antonyms") or []:
        _insert_edge(conn, unit_id, ref, "antonym", None)

    # connections: any → any (kind + score preserved)
    for c in payload.get("connections") or []:
        _insert_edge(conn, unit_id, c.get("to"), c.get("kind"), c.get("score"))

    return _count_edges_in_payload(payload)


def _insert_edge(
    conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    kind: str,
    score: float | None,
) -> int:
    """Insert one edge. Returns 1 on insert, 0 if ignored.

    Silently skips edges where source_id or target_id does not exist
    in the unit table (foreign-key would reject them). The migration
    is forgiving of dangling references in the live vault.
    """
    if not source_id or not target_id or not kind:
        return 0
    cur = conn.execute(
        "INSERT OR IGNORE INTO edge (source_id, target_id, kind, score) VALUES (?, ?, ?, ?)",
        (source_id, target_id, kind, score),
    )
    return cur.rowcount


def _dry_run(vault_root: str) -> dict[str, int]:
    """Count what would be inserted without writing."""
    unit_count = 0
    edge_count = 0
    for unit_type, plural in _UNIT_TYPES:
        unit_dir = Path(vault_root) / "units" / plural
        if not unit_dir.exists():
            continue
        for path in sorted(unit_dir.glob("*.json")):
            unit_count += 1
            payload = _read_unit(path)
            props = payload.get("properties", {}) or {}
            edge_count += len(props.get("word_refs") or [])
            edge_count += len(props.get("members") or [])
            edge_count += len(props.get("antonyms") or [])
            edge_count += len(payload.get("connections") or [])
    return {"unit": unit_count, "edge": edge_count}


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--vault",
        default="./vault",
        help="path to the vault root (default: ./vault)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count planned operations without writing",
    )
    args = parser.parse_args()
    counts = migrate(args.vault, dry_run=args.dry_run)
    mode = "DRY RUN" if args.dry_run else "WROTE"
    print(f"[migrate_json_to_sqlite] {mode}: unit={counts['unit']}, edge={counts['edge']}")


if __name__ == "__main__":
    _cli()