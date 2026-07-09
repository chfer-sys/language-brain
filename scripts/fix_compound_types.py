"""One-shot: flip ``type`` from "word" to "compound" for C-prefixed word units.

Background: the v0.5.2 id-migration gave 2-hanzi units C-ids but never
updated their ``type`` field.  The authoritative rule is
``api/services/word_registry.py:86``:
  ``unit_type = "compound" if len(hanzi) >= 2 else "word"``
C13-C16 were fixed by a prior bite; C1-C12 still have ``"type": "word"``.
This breaks UI type filters AC22/AC23.

Note: ``api/services/unit_writer.py`` only accepts unit types
{sentence, word, group} — it does not know about "compound".
We write directly using ``path.write_text`` (same pattern as
``scripts/migrate_assign_ids.py``) to bypass that restriction.

Usage::

    python scripts/fix_compound_types.py --vault-root PATH
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_C_PATTERN = re.compile(r"^C\d+$")


def run_fix(vault_root: str) -> tuple[int, int]:
    """Fix compound types. Returns (corrected_count, already_correct_count)."""
    words_dir = Path(vault_root) / "units" / "words"
    corrected = 0
    already_correct = 0

    for fpath in sorted(words_dir.glob("*.json")):
        try:
            unit = json.loads(fpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(unit, dict):
            continue

        unit_id = unit.get("id", "")
        if not _C_PATTERN.match(unit_id):
            continue  # not a C-id, leave untouched

        if unit.get("type") == "compound":
            already_correct += 1
            continue

        unit["type"] = "compound"
        # Write directly — bypasses unit_writer's VALID_UNIT_TYPES check.
        fpath.write_text(
            json.dumps(unit, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        corrected += 1

    return corrected, already_correct


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--vault-root",
        required=True,
        help="Path to the vault root (must contain vault/units/words/).",
    )
    args = parser.parse_args(argv)

    corrected, already = run_fix(args.vault_root)
    print(f"fix_compound_types: corrected={corrected} already_correct={already}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
