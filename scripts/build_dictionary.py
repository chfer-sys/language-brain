"""CLI for building and managing the dictionary store (v0.5.3).

Usage:
    python scripts/build_dictionary.py --source subtlex-ch --path ./subtlex-ch.csv
    python scripts/build_dictionary.py --list
    python scripts/build_dictionary.py --vault-root /path/to/vault --source ...

Idempotent: re-running ``--source`` with the same file is a no-op
(INSERT OR IGNORE + UNIQUE constraints prevent duplicates).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from api.services.db import get_connection, init_schema
from scripts.parsers import parse as parse_csv

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Default metadata for the SUBTLEX-CH source.
SUBTLEX_CH_META: dict[str, str | int] = {
    "id": "subtlex-ch",
    "name": "SUBTLEX-CH",
    "version": "1.0",
    "license": "CC-BY",
    "attribution": "Cai & Brysbaert, 2010",
    "priority": 50,
}


def _next_word_id(conn, hanzi: str) -> str:
    """Derive next word id for ``hanzi`` (1 char → W, 2+ chars → C).

    ponytail: word table has its OWN id space independent of the unit table's
    id_counter.json. We compute the next id by querying MAX(word.id) per letter
    within the current import transaction. This keeps the import self-contained
    and does not mutate the vault's unit id counters.
    """
    letter = "W" if len(hanzi) == 1 else "C"

    # Get current max id for this letter.
    row = conn.execute(
        f"SELECT id FROM word WHERE id LIKE '{letter}%' ORDER BY CAST(SUBSTR(id, 2) AS INTEGER) DESC LIMIT 1"
    ).fetchone()

    if row is None:
        next_n = 1
    else:
        next_n = int(row[0][1:]) + 1

    return f"{letter}{next_n}"


def _import_source(
    vault_root: str,
    source_id: str,
    source_name: str,
    source_version: str,
    license: str,
    attribution: str,
    priority: int,
    csv_path: str,
) -> dict[str, int]:
    """Parse CSV and consolidate into dictionary tables.

    Returns dict with keys: entries_count, new_entries, new_words, total_words.
    """
    conn = get_connection(vault_root)
    try:
        init_schema(conn)
        conn.execute("PRAGMA foreign_keys = ON")

        entries = parse_csv(csv_path)
        if not entries:
            logger.warning("No entries parsed from %r", csv_path)
            return {"entries_count": 0, "new_entries": 0, "new_words": 0, "total_words": 0}

        imported_at = datetime.now(timezone.utc).isoformat()

        # Seed dictionary_source (INSERT OR IGNORE — idempotent).
        conn.execute(
            """INSERT OR IGNORE INTO dictionary_source
               (id, name, version, license, attribution, priority, entry_count, imported_at, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (source_id, source_name, source_version, license, attribution, priority,
             len(entries), imported_at),
        )

        new_entries = 0
        new_words = 0
        seen_combinations: set[tuple[str, str]] = set()

        # Track next sort_key.
        sort_key_row = conn.execute(
            "SELECT COALESCE(MAX(sort_key), 0) FROM word"
        ).fetchone()
        sort_key = (sort_key_row[0] or 0) + 1

        for entry in entries:
            hanzi = entry["hanzi"]
            pinyin = entry["pinyin"] or ""
            english = entry["english"]
            frequency = entry["frequency"]
            pos = entry["part_of_speech"]

            key = (hanzi, pinyin)
            combo_seen = key in seen_combinations

            # a. INSERT OR IGNORE into dictionary_entry.
            cur = conn.execute(
                """INSERT OR IGNORE INTO dictionary_entry
                   (source_id, hanzi, pinyin, english, frequency, part_of_speech)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (source_id, hanzi, pinyin, english, frequency, pos),
            )
            if cur.rowcount > 0:
                new_entries += 1

            # b. Check if (hanzi, pinyin) already in word table.
            existing = conn.execute(
                "SELECT 1 FROM word WHERE hanzi=? AND pinyin=?",
                (hanzi, pinyin),
            ).fetchone()

            if existing is None:
                # Insert new word row.
                word_id = _next_word_id(conn, hanzi)
                conn.execute(
                    """INSERT INTO word
                       (id, hanzi, pinyin, english, frequency, first_seen_at, sort_key)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (word_id, hanzi, pinyin, english, frequency, imported_at, sort_key),
                )
                sort_key += 1
                new_words += 1
                seen_combinations.add(key)

            # c. INSERT OR IGNORE into word_in_source.
            # Get word_id (either just-created or existing).
            if not combo_seen:
                wid_row = conn.execute(
                    "SELECT id FROM word WHERE hanzi=? AND pinyin=?",
                    (hanzi, pinyin),
                ).fetchone()
                word_id_for_src = wid_row[0]
                conn.execute(
                    """INSERT OR IGNORE INTO word_in_source
                       (word_id, source_id, entry_count)
                       VALUES (?, ?, 1)""",
                    (word_id_for_src, source_id),
                )
                seen_combinations.add(key)

        conn.commit()

        total_words = conn.execute("SELECT COUNT(*) FROM word").fetchone()[0]

        return {
            "entries_count": len(entries),
            "new_entries": new_entries,
            "new_words": new_words,
            "total_words": total_words,
        }
    finally:
        conn.close()


def _list_sources(vault_root: str) -> None:
    """Print all enabled sources with entry counts and priorities."""
    conn = get_connection(vault_root)
    try:
        init_schema(conn)
        rows = conn.execute(
            """SELECT id, name, version, license, attribution, priority,
                      entry_count, imported_at, enabled
               FROM dictionary_source
               ORDER BY priority ASC, id ASC"""
        ).fetchall()
        if not rows:
            print("No dictionary sources registered.")
            return
        print(f"{'ID':<20} {'Name':<15} {'Priority':>8} {'Entries':>8} {'Enabled':>7}  Attribution")
        print("-" * 90)
        for r in rows:
            enabled_str = "yes" if r["enabled"] else "no"
            print(
                f"{r['id']:<20} {r['name']:<15} {r['priority']:>8} "
                f"{r['entry_count']:>8} {enabled_str:>7}  {r['attribution']}"
            )
    finally:
        conn.close()


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--vault-root",
        default="./vault",
        help="path to vault root (default: ./vault)",
    )
    parser.add_argument(
        "--source",
        help="source id to import (e.g. subtlex-ch)",
    )
    parser.add_argument(
        "--path",
        help="path to the source CSV file",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list enabled sources with entry counts and priorities",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="display name for the source (default: SUBTLEX-CH)",
    )
    parser.add_argument(
        "--version",
        default="1.0",
        help="version string for the source",
    )
    parser.add_argument(
        "--license",
        default="CC-BY",
        help="license identifier",
    )
    parser.add_argument(
        "--attribution",
        default="Cai & Brysbaert, 2010",
        help="attribution string",
    )
    parser.add_argument(
        "--priority",
        type=int,
        default=50,
        help="priority (lower = higher, default: 50)",
    )
    args = parser.parse_args(argv)

    if args.list:
        _list_sources(args.vault_root)
        return 0

    if not args.source or not args.path:
        parser.error("--source and --path are required for import")
        return 1

    csv_path = Path(args.path)
    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}", file=sys.stderr)
        return 1

    # Use SUBTLEX-CH defaults for the known subtlex-ch source.
    source_id = args.source
    if source_id == "subtlex-ch":
        name = args.name or SUBTLEX_CH_META["name"]
        version = args.version
        license_str = args.license
        attribution = args.attribution
        priority = args.priority
    else:
        name = args.name or args.source
        version = args.version
        license_str = args.license
        attribution = args.attribution
        priority = args.priority

    print(f"[build_dictionary] Importing {source_id} from {csv_path} ...")
    result = _import_source(
        vault_root=args.vault_root,
        source_id=source_id,
        source_name=name,
        source_version=version,
        license=license_str,
        attribution=attribution,
        priority=priority,
        csv_path=str(csv_path),
    )

    print(
        f"[build_dictionary] Done: {result['new_entries']} new entries, "
        f"{result['new_words']} new words, "
        f"{result['total_words']} total words in word table"
    )
    return 0


main = _cli

if __name__ == "__main__":
    raise SystemExit(_cli())
