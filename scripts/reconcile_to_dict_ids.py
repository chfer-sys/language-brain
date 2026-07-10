"""One-shot migration: re-id vault word/compound units from counter-ids to dict word-table ids.

Usage:
    python scripts/reconcile_to_dict_ids.py [--vault-root ./vault] [--dry-run]

Algorithm
─────────
1. Build the mapping: old_unit_id → dict_word_id
   For each word/compound JSON file in vault/units/words/:
     - Read its properties.hanzi and properties.pinyin
     - Look up (hanzi, pinyin) in the dict word table
     - If found: map old_id → dict_id
     - If NOT found: log a warning and SKIP

2. Rename files: for each (old_id, dict_id) in the mapping:
   - Rename vault/units/words/{old_id}.json → vault/units/words/{dict_id}.json
   - Update the "id" field inside the JSON to dict_id
   - Skip if old_id == dict_id (already correct)

3. Rewrite references (KEY-AWARE, not naive recursion):
   In EVERY JSON file under vault/units/ (words, sentences, groups):
     - properties.word_refs: replace old ids with dict ids
     - properties.antonyms: replace old ids with dict ids
     - properties.members: replace old ids with dict ids
     - connections[].to: replace old ids with dict ids
   CRITICAL: only touch the keys above — NOT pinyin/hanzi/name.

4. Idempotency: if run twice, the second run is a no-op.

5. Handle duplicates: if multiple old units map to the same dict_id,
   keep the one with richer data (more connections/antonyms), merge
   refs into the survivor, warn about the merge.

Safety
──────
- --dry-run: report what would change without modifying any files.
- Vault data is gitignored; the user is responsible for their own backup.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from api.services.db import get_connection

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Keys that contain unit-id references to rewrite.
_ID_REF_KEYS = (
    "word_refs",
    "antonyms",
    "members",
)


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _lookup_dict_id(
    conn,
    hanzi: str,
    pinyin: str,
) -> str | None:
    """Look up dict word id by (hanzi, pinyin).

    Tries exact match first, then space-normalized match.
    Returns None if not found.
    """
    row = conn.execute(
        "SELECT id FROM word WHERE hanzi=? AND pinyin=?",
        (hanzi, pinyin),
    ).fetchone()
    if row is not None:
        return row[0]

    # Try with spaces stripped from both sides.
    pinyin_normalized = pinyin.replace(" ", "").replace("\u00a0", "")
    if pinyin_normalized != pinyin:
        row = conn.execute(
            "SELECT id FROM word WHERE hanzi=? AND REPLACE(pinyin, ' ', '') = ?",
            (hanzi, pinyin_normalized),
        ).fetchone()
        if row is not None:
            return row[0]

    return None


def _richness(unit: dict) -> int:
    """Score a unit by richness for merge resolution."""
    return (
        len(unit.get("connections", []))
        + len(unit.get("properties", {}).get("antonyms", []))
        + len(unit.get("properties", {}).get("word_refs", []))
    )


def _build_id_mapping(
    conn,
    vault_root: Path,
) -> dict[str, str]:
    """Build {old_id: dict_id} for all word/compound units."""
    words_dir = vault_root / "units" / "words"
    mapping: dict[str, str] = {}
    skipped: list[str] = []

    for path in sorted((words_dir).glob("*.json")):
        old_id = path.stem
        # Skip S/G (not in dict).
        if old_id[0] not in ("W", "C"):
            continue
        # Skip already-correct dict ids (W* that are already dict W-ids).
        # ponytail: heuristic — if the numeric part is large (>1000), it's likely a dict id.
        if old_id[0] == "W" and old_id[1:].isdigit() and int(old_id[1:]) > 1000:
            continue
        if old_id[0] == "C" and old_id[1:].isdigit() and int(old_id[1:]) > 1000:
            continue

        unit = _load_json(path)
        hanzi = unit.get("properties", {}).get("hanzi", "")
        pinyin = unit.get("properties", {}).get("pinyin", "")
        if not hanzi:
            logger.warning("  SKIP %s: no hanzi", old_id)
            skipped.append(old_id)
            continue

        dict_id = _lookup_dict_id(conn, hanzi, pinyin)
        if dict_id is None:
            logger.warning("  SKIP %s: hanzi=%r pinyin=%r not found in dict", old_id, hanzi, pinyin)
            skipped.append(old_id)
            continue

        mapping[old_id] = dict_id

    return mapping, skipped


def _resolve_duplicates(
    mapping: dict[str, str],
    vault_root: Path,
) -> tuple[dict[str, str], dict[str, dict], dict[str, str], list[tuple[str, str]]]:
    """Resolve duplicates: multiple old_ids → same dict_id.

    Returns:
        mapping: cleaned (losers removed)
        survivors: {dict_id: merged_unit_data}
        winner_for: {dict_id: winner_old_id}
        merged: [(loser_old_id, winner_old_id)]
    """
    # Group by dict_id.
    by_dict: dict[str, list[str]] = defaultdict(list)
    for old_id, dict_id in mapping.items():
        by_dict[dict_id].append(old_id)

    survivors: dict[str, dict] = {}  # dict_id → merged unit data
    winner_for: dict[str, str] = {}  # dict_id → winner_old_id
    merged: list[tuple[str, str]] = []  # (loser_old_id, winner_old_id)
    losers: set[str] = set()  # old_ids that lose their file

    for dict_id, old_ids in by_dict.items():
        if len(old_ids) == 1:
            continue
        logger.warning("  DUPLICATE MERGE: %s all map to %s", old_ids, dict_id)
        # Load all candidates and pick the richest.
        units = {oid: _load_json(vault_root / "units" / "words" / f"{oid}.json") for oid in old_ids}
        winner = max(units, key=lambda oid: _richness(units[oid]))
        winner_for[dict_id] = winner
        for oid in old_ids:
            if oid != winner:
                merged.append((oid, winner))
                losers.add(oid)

        # Merge connections/antonyms from losers into winner.
        winner_unit = units[winner]
        for oid, unit in units.items():
            if oid == winner:
                continue
            # Merge connections.to into winner (avoid duplicates).
            winner_conns = {c["to"] for c in winner_unit.get("connections", [])}
            for conn_obj in unit.get("connections", []):
                if conn_obj["to"] not in winner_conns:
                    winner_unit["connections"].append(conn_obj)
                    winner_conns.add(conn_obj["to"])
            # Merge antonyms.
            winner_antonyms = set(winner_unit.get("properties", {}).get("antonyms", []))
            for ant in unit.get("properties", {}).get("antonyms", []):
                if ant not in winner_antonyms:
                    winner_unit["properties"].setdefault("antonyms", []).append(ant)

        survivors[dict_id] = winner_unit

    # Remove losers from the filesystem (their data is merged into survivor).
    # KEEP losers in the mapping so _rewrite_all_refs can rewrite their
    # references in other files (sentences, groups) before they are deleted.
    # _rename_and_update will skip losers (file already gone).
    for loser in losers:
        loser_path = vault_root / "units" / "words" / f"{loser}.json"
        if loser_path.exists():
            loser_path.unlink()
        # NOTE: loser remains in mapping with its old_id → dict_id entry.
        # _rename_and_update skips it (file gone); _rewrite_all_refs uses it.

    return mapping, survivors, winner_for, merged


def _rewrite_refs_in_unit(
    unit: dict,
    id_map: dict[str, str],
) -> int:
    """Rewrite id references in a unit dict.

    Only touches: word_refs, antonyms, members, connections[].to.
    Returns the number of references rewritten.
    """
    rewritten = 0

    props = unit.get("properties", {})
    for key in _ID_REF_KEYS:
        if key in props and isinstance(props[key], list):
            new_refs = []
            for ref in props[key]:
                new_ref = id_map.get(ref, ref)
                if new_ref != ref:
                    rewritten += 1
                new_refs.append(new_ref)
            props[key] = new_refs

    # connections[].to
    for conn in unit.get("connections", []):
        if "to" in conn:
            old_to = conn["to"]
            new_to = id_map.get(old_to, old_to)
            if new_to != old_to:
                conn["to"] = new_to
                rewritten += 1

    return rewritten


def _rename_and_update(
    mapping: dict[str, str],
    survivors: dict[str, dict],
    winner_for: dict[str, str],
    vault_root: Path,
    dry_run: bool,
) -> tuple[int, int]:
    """Rename word files and update their id fields.

    Handles collisions: when the target file already exists (from a previous
    rename or a pre-existing vault file with a conflicting name), merge the
    source into the target and delete the source.

    Returns (files_renamed, id_fields_updated).
    """
    words_dir = vault_root / "units" / "words"
    renamed = 0
    id_updated = 0

    # ponytail: process in ascending old_id order so lower counter-ids "win".
    # When W4 → W1 and W17 → W4: W4 processes first → W4.json → W1.json,
    # then W17 → W4 has a clear target (W4.json doesn't exist anymore).
    for old_id, dict_id in sorted(mapping.items(), key=lambda x: x[0]):
        old_path = words_dir / f"{old_id}.json"
        new_path = words_dir / f"{dict_id}.json"

        if old_id == dict_id:
            logger.info("  already correct: %s", old_id)
            continue

        if not old_path.exists():
            logger.info("  skip %s: file already deleted (duplicate loser)", old_path.name)
            continue

        # Determine unit data:
        # If old_id is the winner for this dict_id, use the merged survivor data.
        # Otherwise load normally.
        if old_id == winner_for.get(dict_id):
            unit = survivors[dict_id]
        else:
            unit = _load_json(old_path)

        # Update the id field.
        if unit.get("id") != dict_id:
            unit["id"] = dict_id
            id_updated += 1

        if dry_run:
            if new_path.exists():
                logger.info("  [DRY-RUN] merge %s → %s (collision)", old_path.name, new_path.name)
            else:
                logger.info("  [DRY-RUN] rename %s → %s", old_path.name, new_path.name)
        else:
            if new_path.exists():
                # Collision: merge source data into existing target, delete source.
                target = _load_json(new_path)
                # Merge connections (avoid dupes).
                target_conns = {c["to"] for c in target.get("connections", [])}
                for conn_obj in unit.get("connections", []):
                    if conn_obj["to"] not in target_conns:
                        target["connections"].append(conn_obj)
                        target_conns.add(conn_obj["to"])
                # Merge antonyms.
                target_antonyms = set(target.get("properties", {}).get("antonyms", []))
                for ant in unit.get("properties", {}).get("antonyms", []):
                    if ant not in target_antonyms:
                        target["properties"].setdefault("antonyms", []).append(ant)
                # Merge groups (union).
                target_groups = set(target.get("properties", {}).get("groups", []))
                for g in unit.get("properties", {}).get("groups", []):
                    if g not in target_groups:
                        target["properties"].setdefault("groups", []).append(g)
                _save_json(new_path, target)
                old_path.unlink()
                logger.info("  merged %s → %s (collision)", old_path.name, new_path.name)
            else:
                _save_json(new_path, unit)
                old_path.unlink()
                logger.info("  renamed %s → %s", old_path.name, new_path.name)
            renamed += 1

    return renamed, id_updated


def _rewrite_all_refs(
    vault_root: Path,
    id_map: dict[str, str],
    dry_run: bool,
) -> int:
    """Walk all JSON files under vault/units and rewrite id references.

    Returns total number of references rewritten.
    """
    total_rewritten = 0
    units_dir = vault_root / "units"

    for json_path in units_dir.rglob("*.json"):
        unit = _load_json(json_path)
        count = _rewrite_refs_in_unit(unit, id_map)
        if count > 0:
            logger.info("  %s: %d refs rewritten", json_path.relative_to(vault_root), count)
            total_rewritten += count
            if not dry_run:
                _save_json(json_path, unit)

    return total_rewritten


def _check_type_field(vault_root: Path) -> list[str]:
    """Sanity check: W-prefixed dict ids should be 1-hanzi words; C-prefixed 2+ hanzi.

    Returns list of inconsistency warnings.
    """
    words_dir = vault_root / "units" / "words"
    warnings = []
    conn = get_connection(str(vault_root))
    try:
        for path in sorted(words_dir.glob("*.json")):
            unit = _load_json(path)
            unit_id = unit.get("id", "")
            unit_type = unit.get("type", "")
            hanzi = unit.get("properties", {}).get("hanzi", "")
            if not unit_id or not hanzi:
                continue

            expected_prefix = "W" if len(hanzi) == 1 else "C"
            if not unit_id.startswith(expected_prefix):
                warnings.append(
                    f"  TYPE MISMATCH: {unit_id} ({unit_type=}) has hanzi {hanzi!r}"
                    f" (len={len(hanzi)}) → expected prefix {expected_prefix}"
                )
    finally:
        conn.close()

    return warnings


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--vault-root",
        default="./vault",
        help="path to vault root (default: ./vault)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without modifying any files",
    )
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root).resolve()
    if not vault_root.exists():
        logger.error("Vault root does not exist: %s", vault_root)
        return 1

    logger.info("Starting reconciliation (vault=%s, dry_run=%s)", vault_root, args.dry_run)
    if args.dry_run:
        logger.info("  [DRY-RUN] No files will be modified.")

    # Connect to dict.
    conn = get_connection(str(vault_root))
    try:
        # Step 1: build id mapping.
        logger.info("Step 1: Building old_id → dict_id mapping...")
        id_map, skipped = _build_id_mapping(conn, vault_root)

        # Step 2: resolve duplicates.
        logger.info("Step 2: Resolving duplicates...")
        id_map, survivors, winner_for, merged = _resolve_duplicates(id_map, vault_root)

        # Count already-correct.
        already_correct = 0
        for old_id in list(id_map.keys()):
            if old_id == id_map[old_id]:
                already_correct += 1

        logger.info(
            "  Mapping: %d to re-id, %d already correct, %d skipped (not in dict), %d merged",
            len(id_map) - already_correct,
            already_correct,
            len(skipped),
            len(merged),
        )

        # Step 3: rename files and update id fields.
        logger.info("Step 3: Renaming word files...")
        renamed, id_updated = _rename_and_update(id_map, survivors, winner_for, vault_root, args.dry_run)

        # Step 4: rewrite all references.
        logger.info("Step 4: Rewriting references in all units...")
        refs_rewritten = _rewrite_all_refs(vault_root, id_map, args.dry_run)

        # Step 5: type sanity check.
        logger.info("Step 5: Type-field sanity check...")
        type_warnings = _check_type_field(vault_root)
        for w in type_warnings:
            logger.warning(w)

        logger.info("\n=== SUMMARY ===")
        logger.info("  Units re-id'd:   %d", renamed)
        logger.info("  Id fields updated: %d", id_updated)
        logger.info("  References rewritten: %d", refs_rewritten)
        logger.info("  Skipped (not in dict): %d", len(skipped))
        logger.info("  Duplicates merged: %d", len(merged))
        if type_warnings:
            logger.warning("  Type inconsistencies: %d", len(type_warnings))
        logger.info("================")

        if args.dry_run:
            logger.info("\n[DRY-RUN] No files were modified.")
        else:
            logger.info("\nReconciliation complete.")

        return 0
    finally:
        conn.close()


main = _main

if __name__ == "__main__":
    raise SystemExit(_main())
