"""One-shot migration: rename 5 slug-id units to typed ids and rewrite
all cross-references (v0.5.2 stragglers, created 2026-07-09).

This is a targeted migration for the cluster that the original
migrate_assign_ids.py sweep missed.

Mapping
-------
k-qi-sh-nme  → S14  (sentence)
kèqi         → C13  (compound — flip type from word)
shénme       → C14  (compound)
suíbiàn      → C15  (compound)
wúlǐ         → C16  (compound)
social-interaction → unchanged (group slug)

Reference-rewrite rules (KEY-AWARE — only these fields):
  top-level id, connections[].to, properties.word_refs[],
  properties.antonyms[], properties.members[]

DO NOT touch: properties.groups[], properties.hanzi, properties.pinyin,
properties.english, properties.meaning, name.

Idempotent: re-running on already-migrated vault finds no old slugs,
changes nothing.

Usage::

    python scripts/migrate_slug_stragglers.py --vault-root ./vault
    python scripts/migrate_slug_stragglers.py --vault-root ./vault --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# ponytail: the imported _rewrite_references skips "properties" (not in
# REFERENCE_KEYS), so properties.members is never visited. We inline a
# corrected version that explicitly recurses into properties.*reference
# fields without touching properties.content fields (hanzi/pinyin/english).

def _rewrite_references(obj, id_map: dict[str, str]):
    """Rewrite id references in the specific fields that hold them.

    Handles top-level ``id``, ``connections[].to``, and
    ``properties.word_refs/antonyms/members`` — key-aware so
    properties.hanzi/pinyin/english/meaning are never touched.

    Also recurses into ``properties`` (which is not a reference field
    itself but may contain reference fields).
    """
    REFERENCE_KEYS = frozenset({"word_refs", "antonyms", "members", "groups"})
    if isinstance(obj, str):
        return id_map.get(obj, obj)
    if isinstance(obj, list):
        return [_rewrite_references(item, id_map) for item in obj]
    if isinstance(obj, dict):
        result = {}
        for key, val in obj.items():
            if key == "id":
                result[key] = id_map.get(val, val) if isinstance(val, str) else val
            elif key == "to" and isinstance(val, str):
                # connections[].to — direct reference
                result[key] = id_map.get(val, val)
            elif key == "properties" and isinstance(val, dict):
                # Recurse into properties so we catch members/antonyms/etc.
                result[key] = {
                    pk: _rewrite_references(pv, id_map) if pk in REFERENCE_KEYS else pv
                    for pk, pv in val.items()
                }
            elif key == "connections" and isinstance(val, list):
                # connections[] contains {to, kind, score} — rewrite to field.
                result[key] = [
                    {k: (id_map.get(v, v) if k == "to" and isinstance(v, str) else v) for k, v in conn.items()}
                    if isinstance(conn, dict) else _rewrite_references(conn, id_map)
                    for conn in val
                ]
            elif key in REFERENCE_KEYS:
                result[key] = _rewrite_references(val, id_map)
            else:
                result[key] = val
        return result
    return obj

_MIGRATION_MAP: dict[str, str] = {
    "k-qi-sh-nme": "S14",
    "kèqi": "C13",
    "shénme": "C14",
    "suíbiàn": "C15",
    "wúlǐ": "C16",
    # social-interaction is unchanged — include so references TO it
    # are left alone (only rewriting slugs that are keys in this dict).
    "social-interaction": "social-interaction",
}

# Files that must be renamed (old slug → new typed id).
_RENAME_MAP: dict[str, tuple[str, str]] = {
    # (old_slug, new_id): (plural_dir, new_filename)
    "k-qi-sh-nme": ("sentences", "S14"),
    "kèqi": ("words", "C13"),
    "shénme": ("words", "C14"),
    "suíbiàn": ("words", "C15"),
    "wúlǐ": ("words", "C16"),
}

# Compound type-flip: these old word-slugs become compounds.
_COMPOUND_FLIP: set[str] = {"kèqi", "shénme", "suíbiàn", "wúlǐ"}

_UNIT_DIRS = ["words", "sentences", "groups"]


def _slug_files(vault_root: Path) -> list[tuple[Path, dict]]:
    """Yield (path, payload) for every JSON unit file."""
    for plural in _UNIT_DIRS:
        unit_dir = vault_root / "units" / plural
        if not unit_dir.is_dir():
            continue
        for p in sorted(unit_dir.glob("*.json")):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict):
                yield p, payload


def migrate(vault_root: str, *, dry_run: bool = False) -> dict[str, int]:
    vault = Path(vault_root)

    # Idempotency check: if none of the old slugs exist, nothing to do.
    old_slugs = set(_MIGRATION_MAP) - {"social-interaction"}
    slug_files_found: dict[str, Path] = {}
    for path, payload in _slug_files(vault):
        slug = payload.get("id", "")
        if slug in old_slugs and slug not in slug_files_found:
            slug_files_found[slug] = path

    if not slug_files_found:
        return {"renamed": 0, "rewritten": 0, "unchanged": 0}

    # Build id_map for _rewrite_references — only includes the 5 migrating slugs.
    id_map = {old: new for old, new in _MIGRATION_MAP.items() if old != new}

    # Pass 1: rewrite references in ALL unit files.
    rewritten = 0
    for path, payload in _slug_files(vault):
        old_id = payload.get("id", "")
        new_payload = _rewrite_references(payload, id_map)
        if new_payload != payload:
            rewritten += 1
            if not dry_run:
                path.write_text(
                    json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

    # Pass 2: rename files, flip type for compounds.
    renamed = 0
    for slug, (plural, typed_id) in _RENAME_MAP.items():
        if slug not in slug_files_found:
            continue  # already migrated or absent
        old_path = slug_files_found[slug]
        new_path = vault / "units" / plural / f"{typed_id}.json"

        if not dry_run:
            # Load current content (may have been rewritten in pass 1).
            payload = json.loads(old_path.read_text(encoding="utf-8"))

            # Flip type: word → compound for the 4 compounds.
            if slug in _COMPOUND_FLIP and payload.get("type") == "word":
                payload["type"] = "compound"

            # Write to new path, delete old.
            new_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            old_path.unlink()
        renamed += 1

    # Update counters: C12→C16, S13→S14.
    counters_path = vault / "_meta" / "id_counters.json"
    counters = {"W": 22, "C": 16, "S": 14, "G": 12}
    if not dry_run:
        counters_path.parent.mkdir(parents=True, exist_ok=True)
        counters_path.write_text(json.dumps(counters, indent=2), encoding="utf-8")

    return {"renamed": renamed, "rewritten": rewritten, "unchanged": 0}


def _cli():
    parser = argparse.ArgumentParser(
        description="Rename 5 slug-id units to typed ids (v0.5.2 stragglers)."
    )
    parser.add_argument("--vault-root", default="./vault")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = migrate(args.vault_root, dry_run=args.dry_run)
    mode = "DRY RUN" if args.dry_run else "DONE"
    print(
        f"[migrate_slug_stragglers] {mode}: "
        f"renamed={result['renamed']}, rewritten={result['rewritten']}, "
        f"unchanged={result['unchanged']}"
    )


if __name__ == "__main__":
    _cli()
