"""SQLite storage layer (v0.5.1).

Single-file SQLite database at ``<vault>/index/vault.db`` used as a
parallel store alongside the existing JSON-on-disk vault. Future
versions will route reads through SQLite; v0.5.1 is additive and
does not change any existing read path.

Schema covers 7 tables (vec_sentences is deferred to v0.5.5 — see
SPEC §10 risk 1: sqlite-vec is pre-v1, dependency churn avoided
for now). ponytail: skip the dep until we need it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ponytail: vec_sentences (sqlite-vec) deferred to v0.5.5.
# SPEC §10 risk 1: "sqlite-vec is pre-v1, expect breaking changes."
# Adding the dep now means migrations later. Skip until search parity
# actually needs vector search.

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS unit (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    sort_key        INTEGER NOT NULL,
    name            TEXT NOT NULL,
    pinyin          TEXT,
    english         TEXT,
    gloss           TEXT,
    properties      TEXT,
    created         TEXT NOT NULL,
    updated         TEXT NOT NULL,
    author_confirmed INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_unit_type     ON unit(type);
CREATE INDEX IF NOT EXISTS idx_unit_sort_key ON unit(type, sort_key);

CREATE TABLE IF NOT EXISTS edge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    score       REAL,
    FOREIGN KEY (source_id) REFERENCES unit(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES unit(id) ON DELETE CASCADE,
    UNIQUE(source_id, target_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_edge_source ON edge(source_id, kind);
CREATE INDEX IF NOT EXISTS idx_edge_target ON edge(target_id, kind);

CREATE TABLE IF NOT EXISTS dictionary_source (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    version       TEXT NOT NULL,
    license       TEXT NOT NULL,
    attribution   TEXT NOT NULL,
    priority      INTEGER NOT NULL DEFAULT 100,
    entry_count   INTEGER NOT NULL,
    imported_at   TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    UNIQUE(id, version)
);

CREATE TABLE IF NOT EXISTS dictionary_entry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT NOT NULL REFERENCES dictionary_source(id),
    hanzi           TEXT NOT NULL,
    pinyin          TEXT NOT NULL,
    english         TEXT,
    frequency       REAL,
    part_of_speech  TEXT,
    extra           TEXT,
    UNIQUE(source_id, hanzi, pinyin)
);
CREATE INDEX IF NOT EXISTS idx_dict_entry_hanzi  ON dictionary_entry(hanzi);
CREATE INDEX IF NOT EXISTS idx_dict_entry_pinyin ON dictionary_entry(pinyin);

CREATE TABLE IF NOT EXISTS word (
    id              TEXT PRIMARY KEY,
    hanzi           TEXT NOT NULL,
    pinyin          TEXT NOT NULL,
    english         TEXT,
    frequency       REAL,
    first_seen_at   TEXT NOT NULL,
    sort_key        INTEGER NOT NULL,
    UNIQUE(hanzi, pinyin)
);
CREATE INDEX IF NOT EXISTS idx_word_sort_key ON word(sort_key);

CREATE TABLE IF NOT EXISTS word_in_source (
    word_id     TEXT NOT NULL REFERENCES word(id),
    source_id   TEXT NOT NULL REFERENCES dictionary_source(id),
    entry_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (word_id, source_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS unit_fts USING fts5(
    id UNINDEXED,
    type UNINDEXED,
    name,
    english,
    gloss,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def get_connection(vault_root: str) -> sqlite3.Connection:
    """Open (and lazily create) the SQLite database for ``vault_root``.

    Sets WAL mode, foreign keys, and a 5s busy timeout. Does not
    initialise the schema — call :func:`init_schema` separately so
    callers can run their own migrations inside the same transaction
    if they want.
    """
    index_dir = Path(vault_root) / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    db_path = index_dir / "vault.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # ponytail: 30s busy timeout. WAL mode allows concurrent readers but a
    # checkpoint still needs exclusive write access. When multiple threads
    # open/close connections simultaneously the checkpoint can race with new
    # connection opens. 5s was insufficient under load; 30s covers worst-case
    # system load without masking a real bug. Production is single-threaded at
    # startup so this has no runtime cost.
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables, indexes, and the FTS5 virtual table.

    Idempotent: every statement is ``CREATE ... IF NOT EXISTS``.
    Safe to call on every connection open.
    """
    conn.executescript(_SCHEMA_DDL)
    conn.commit()