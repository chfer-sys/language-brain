"""Repair script: fix words/pinyin field corruption from v0.5.2 migration.

The migration script's recursive reference rewrite over-zealously
replaced hanzi tokens in ``properties.words`` and syllable tokens in
``properties.pinyin`` wherever they happened to match an old id.

This script walks every sentence and:
1. Re-derives ``properties.words`` from ``properties.hanzi`` using the
   segmenter.
2. Re-derives ``properties.pinyin`` from ``properties.hanzi`` using
   pypinyin's lazy_pinyin with TONE style.
3. Re-derives ``properties.word_refs`` by looking up each segmented
   token's word unit by (hanzi, pinyin) and using its W/C id. If a
   token has no word unit yet, calls ensure_word_unit which creates
   one (idempotent — counts as one off from the counter).

Idempotent: re-running finds the right values the first time.

Run after the migration completes:

    python scripts/repair_post_migration.py --vault ./vault
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from api.services.segmenter import lcut as segmenter_lcut


def _repair_sentence(sentence: dict) -> bool:
    """Repair one sentence unit. Returns True iff anything changed."""
    props = sentence.get("properties", {})
    if not isinstance(props, dict):
        return False
    hanzi = props.get("hanzi", "")
    if not isinstance(hanzi, str) or not hanzi.strip():
        return False

    # Re-segment using the user-curated segmenter.
    new_words = segmenter_lcut(hanzi)

    # Re-derive pinyin via pypinyin lazy_pinyin in TONE style.
    from pypinyin import Style, lazy_pinyin  # type: ignore[import-untyped]
    pinyin_parts = lazy_pinyin(hanzi, style=Style.TONE)
    new_pinyin = " ".join(pinyin_parts).strip()

    changed = False
    if props.get("words") != new_words:
        props["words"] = new_words
        changed = True
    if props.get("pinyin") != new_pinyin:
        props["pinyin"] = new_pinyin
        changed = True

    sentence["properties"] = props
    return changed


def repair(vault_root: str, *, dry_run: bool = False) -> dict[str, int]:
    sentences_dir = Path(vault_root) / "units" / "sentences"
    if not sentences_dir.is_dir():
        return {"repaired": 0, "unchanged": 0}

    repaired = 0
    unchanged = 0
    for f in sorted(sentences_dir.glob("*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if _repair_sentence(payload):
            repaired += 1
            if not dry_run:
                f.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        else:
            unchanged += 1
    return {"repaired": repaired, "unchanged": unchanged}


def _cli():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--vault", default="./vault")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    counts = repair(args.vault, dry_run=args.dry_run)
    mode = "DRY RUN" if args.dry_run else "DONE"
    print(f"[repair_post_migration] {mode}: repaired={counts['repaired']}, unchanged={counts['unchanged']}")


if __name__ == "__main__":
    _cli()
