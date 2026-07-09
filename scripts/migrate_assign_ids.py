"""One-shot migration: assign W/C/S/G ids to all existing units (v0.5.2).

Walks ``vault/units/{words,sentences,groups}/*.json``, assigns typed
variable-width ids (W1, C1, S1, G1), renames files, and rewrites all
internal references.

Idempotent: if all files already have ^[WCSG]\\d+$ ids, no changes.

Usage::

    python scripts/migrate_assign_ids.py --vault ./vault
    python scripts/migrate_assign_ids.py --vault ./vault --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from api.services.id_counter import init_counters

_TYPED_ID_RE = re.compile(r"^[WCSG]\d+$")

_UNIT_DIRS: list[tuple[str, str]] = [
    ("word", "words"),
    ("sentence", "sentences"),
    ("group", "groups"),
]


def _is_migrated(unit_id: str) -> bool:
    return bool(_TYPED_ID_RE.match(unit_id))


def _detect_type(payload: dict) -> str:
    """Return 'word' or 'compound' based on hanzi length."""
    props = payload.get("properties", {})
    hanzi = props.get("hanzi", "")
    if isinstance(hanzi, str) and len(hanzi) >= 2:
        return "compound"
    return "word"


def _build_id_map(vault_root: str) -> dict[str, str]:
    """Walk all unit files in lex order and assign typed ids.

    Returns ``{old_id: new_id}``.
    """
    id_map: dict[str, str] = {}
    counters: dict[str, int] = {"W": 0, "C": 0, "S": 0, "G": 0}

    for unit_type, plural in _UNIT_DIRS:
        unit_dir = Path(vault_root) / "units" / plural
        if not unit_dir.is_dir():
            continue
        for path in sorted(unit_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            old_id = payload.get("id", "")
            if not isinstance(old_id, str) or not old_id:
                continue
            if _is_migrated(old_id):
                # Already has a typed id — record it so references resolve.
                id_map[old_id] = old_id
                # Track the counter so init_counters doesn't go below.
                letter = old_id[0]
                num = int(old_id[1:])
                if letter in counters and num > counters[letter]:
                    counters[letter] = num
                continue

            # Assign new id based on type.
            if unit_type == "word":
                detected = _detect_type(payload)
                letter = "C" if detected == "compound" else "W"
            elif unit_type == "sentence":
                letter = "S"
            else:
                letter = "G"

            counters[letter] += 1
            new_id = f"{letter}{counters[letter]}"
            id_map[old_id] = new_id

    return id_map


def _rewrite_references(obj, id_map: dict[str, str]):
    """Recursively rewrite all string values that match an old id."""
    if isinstance(obj, str):
        return id_map.get(obj, obj)
    if isinstance(obj, list):
        return [_rewrite_references(item, id_map) for item in obj]
    if isinstance(obj, dict):
        result = {}
        for key, val in obj.items():
            if key == "id":
                result[key] = id_map.get(val, val) if isinstance(val, str) else val
            else:
                result[key] = _rewrite_references(val, id_map)
        return result
    return obj


def migrate(vault_root: str, *, dry_run: bool = False) -> dict[str, int]:
    """Run the migration. Returns counts of renamed/unchanged files."""
    id_map = _build_id_map(vault_root)

    # Filter out self-mappings (already migrated).
    changes = {old: new for old, new in id_map.items() if old != new}
    if not changes:
        return {"renamed": 0, "unchanged": len(id_map)}

    if dry_run:
        return {"renamed": len(changes), "unchanged": len(id_map) - len(changes)}

    # Pass 1: rewrite references in all files, write to new paths.
    renamed = 0
    for unit_type, plural in _UNIT_DIRS:
        unit_dir = Path(vault_root) / "units" / plural
        if not unit_dir.is_dir():
            continue
        for path in sorted(unit_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue

            old_id = payload.get("id", "")
            new_id = id_map.get(old_id, old_id)
            if new_id == old_id and _is_migrated(old_id):
                # Already migrated — still rewrite references in case
                # some point at old ids.
                pass

            rewritten = _rewrite_references(payload, id_map)

            new_path = path.parent / f"{rewritten['id']}.json"
            if new_path != path:
                # Write new file, delete old.
                new_path.write_text(
                    json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                path.unlink()
                renamed += 1
            else:
                # Same filename but references changed — overwrite.
                path.write_text(
                    json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

    # Set counters so future allocations don't collide.
    counter_overrides: dict[str, int] = {}
    for old, new in id_map.items():
        if old == new:
            continue
        letter = new[0]
        num = int(new[1:])
        if letter not in counter_overrides or num > counter_overrides[letter]:
            counter_overrides[letter] = num
    # Also include already-migrated ids.
    for old, new in id_map.items():
        if old != new:
            continue
        letter = new[0]
        num = int(new[1:])
        if letter not in counter_overrides or num > counter_overrides[letter]:
            counter_overrides[letter] = num
    init_counters(vault_root, counter_overrides)

    return {"renamed": renamed, "unchanged": len(id_map) - len(changes)}


def _cli():
    parser = argparse.ArgumentParser(description="Assign W/C/S/G ids to all units.")
    parser.add_argument("--vault", default="./vault")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = migrate(args.vault, dry_run=args.dry_run)
    mode = "DRY RUN" if args.dry_run else "DONE"
    print(f"[migrate_assign_ids] {mode}: renamed={result['renamed']}, unchanged={result['unchanged']}")


if __name__ == "__main__":
    _cli()
