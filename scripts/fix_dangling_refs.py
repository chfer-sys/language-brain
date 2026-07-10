#!/usr/bin/env python3
"""Fix dangling references in vault after Bite 3b reconciliation.

This script repairs two classes of dangling-reference bugs introduced by
reconcile_to_dict_ids.py (commit 5da1e75):

1. Missing unit files: W4 (我), W5 (你), W7 (了), C8 (这个) were deleted
   during duplicate-merge but their word_refs in sentences were not rewritten.
   The sentence word_refs point to these ids correctly; the files just
   need to be re-created.

2. Dangling antonym refs: W1029, W733, W344 still reference old W4 (好/hǎo,
   now W14) in their properties.antonyms and connections arrays. The
   reconciliation renamed the file but missed the antonym references in
   these three files because they were not updated before the old W4
   file was deleted as a duplicate loser.

Usage:
    python scripts/fix_dangling_refs.py [--vault-root ./vault] [--dry-run]

Verification (run separately):
    python -c "
    import json, sys
    from pathlib import Path
    vault = Path('vault')

    # Check word_refs all resolve
    sentences = list((vault/'units'/'sentences').glob('*.json'))
    missing_words, missing_conns = [], []
    for s in sentences:
        unit = json.load(open(s))
        for ref in unit.get('properties', {}).get('word_refs', []):
            if not (vault/'units'/'words'/f'{ref}.json').exists():
                missing_words.append(f'{s.stem}: word_refs {ref}')
        for conn in unit.get('connections', []):
            to = conn.get('to', '')
            if to.startswith(('W', 'C')) and not (vault/'units'/'words'/f'{to}.json').exists():
                missing_conns.append(f'{s.stem}: connection to {to}')

    if missing_words: print('MISSING word_refs:', *missing_words)
    if missing_conns: print('MISSING conn refs:', *missing_conns)
    if not missing_words and not missing_conns: print('OK: no dangling refs in sentences')

    # Check word antonym refs
    words = list((vault/'units'/'words').glob('*.json'))
    dangling_antons = []
    for w in words:
        unit = json.load(open(w))
        for ant in unit.get('properties', {}).get('antonyms', []):
            if ant.startswith(('W', 'C')) and not (vault/'units'/'words'/f'{ant}.json').exists():
                dangling_antons.append(f'{w.stem}: antonym {ant}')
    if dangling_antons: print('DANGLING antonyms:', *dangling_antons)
    else: print('OK: no dangling antonym refs')
    "
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Ensure the api package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.word_registry import ensure_word_unit_from_dict
from api.services.lexical import add_lexical_edge_to_word
from api.services.unit_writer import read_unit, write_unit


def _today_iso() -> str:
    return date.today().isoformat()


# ------------------------------------------------------------------
# Step 1: Create missing unit files
# ------------------------------------------------------------------

MISSING_UNITS = [
    # (id, hanzi, pinyin, english)
    ("W4",  "我",   "wǒ",   "I/me/my"),
    ("W5",  "你",   "nǐ",   "you"),
    ("W7",  "了",   "le",   "(modal particle)"),
    ("C8",  "这个", "zhè ge", "this/this one"),
]

# Sentences that reference each missing word (for lexical edge creation)
WORD_TO_SENTENCES: dict[str, list[str]] = {
    "W4":  ["S1", "S2", "S5", "S6", "S9", "S10", "S11", "S12"],
    "W5":  ["S4"],
    "W7":  ["S1", "S4"],
    "C8":  ["S11"],
}


def create_missing_units(vault_root: str, dry_run: bool) -> None:
    for word_id, hanzi, pinyin, english in MISSING_UNITS:
        path = Path(vault_root) / "units" / "words" / f"{word_id}.json"
        if path.exists():
            print(f"  SKIP {word_id}: already exists")
            continue
        if dry_run:
            print(f"  [DRY-RUN] Would create {word_id} ({hanzi})")
            continue
        unit = ensure_word_unit_from_dict(vault_root, word_id, hanzi, pinyin, english)
        print(f"  Created {word_id} ({hanzi})")


# ------------------------------------------------------------------
# Step 2: Fix dangling antonym references
# ------------------------------------------------------------------

# Files with dangling W4 references → replace with W14 (好/hǎo)
DANGLING_ANTONYM_FILES = ["W1029", "W733", "W344"]
OLD_W4 = "W4"
CORRECT_W4 = "W14"  # 好 (hǎo) — old W4 was renamed to W14 during reconciliation


def fix_dangling_antonyms(vault_root: str, dry_run: bool) -> None:
    for word_id in DANGLING_ANTONYM_FILES:
        path = Path(vault_root) / "units" / "words" / f"{word_id}.json"
        if not path.exists():
            print(f"  SKIP {word_id}: file missing (will be fixed by create_missing_units?)")
            continue
        unit = json.loads(path.read_text(encoding="utf-8"))
        changed = False

        # Fix properties.antonyms
        antonyms = unit.get("properties", {}).get("antonyms")
        if isinstance(antonyms, list):
            new_antonyms = []
            for ant in antonyms:
                if ant == OLD_W4:
                    new_antonyms.append(CORRECT_W4)
                    changed = True
                else:
                    new_antonyms.append(ant)
            unit["properties"]["antonyms"] = new_antonyms

        # Fix connections[].to
        for conn in unit.get("connections", []):
            if conn.get("to") == OLD_W4:
                conn["to"] = CORRECT_W4
                changed = True

        if changed:
            if dry_run:
                print(f"  [DRY-RUN] Would fix W4→W14 in {word_id}")
            else:
                unit["updated"] = _today_iso()
                write_unit(vault_root, unit)
                print(f"  Fixed W4→W14 in {word_id}")
        else:
            print(f"  SKIP {word_id}: no W4 reference found")


# ------------------------------------------------------------------
# Step 3: Add lexical edges for newly created units
# ------------------------------------------------------------------

def add_lexical_edges(vault_root: str, dry_run: bool) -> None:
    for word_id, sentences in WORD_TO_SENTENCES.items():
        path = Path(vault_root) / "units" / "words" / f"{word_id}.json"
        if not path.exists():
            print(f"  SKIP lexical edges for {word_id}: file does not exist")
            continue
        for sentence_id in sentences:
            if dry_run:
                print(f"  [DRY-RUN] Would add lexical edge {word_id} → {sentence_id}")
            else:
                try:
                    add_lexical_edge_to_word(vault_root, word_id, sentence_id, score=1.0)
                    print(f"  Added lexical edge {word_id} → {sentence_id}")
                except Exception as e:
                    print(f"  ERROR adding lexical edge {word_id} → {sentence_id}: {e}")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
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

    vault_root = str(Path(args.vault_root).resolve())
    if not Path(vault_root).exists():
        print(f"ERROR: Vault root does not exist: {vault_root}", file=sys.stderr)
        return 1

    print(f"Fixing dangling references (vault={vault_root}, dry_run={args.dry_run})")

    print("\nStep 1: Creating missing unit files...")
    create_missing_units(vault_root, args.dry_run)

    print("\nStep 2: Fixing dangling antonym references (W4 → W14)...")
    fix_dangling_antonyms(vault_root, args.dry_run)

    print("\nStep 3: Adding lexical edges for newly created units...")
    add_lexical_edges(vault_root, args.dry_run)

    if not args.dry_run:
        print("\nStep 4: compute_connections should be run separately to rebuild all edges.")
        print("  From the repo root:")
        print("    python -c \"from api.services.connector import compute_connections; print(compute_connections('./vault'))\"")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
