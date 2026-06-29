"""One-shot backfill: derive ``properties.english`` for every word
unit that has it empty, using the ``english`` fields of the
sentences that contain the word.

Background (v0.4.1 T2)
----------------------
After T2 lands, new sentences propagate english to their word units
automatically. But the 15 word units committed before T2 still have
empty ``english`` fields. The user flagged this in
``.specs/My-Reveiew.md``: typing English "i want to eat" returns no
result because 吃.english is empty.

What this script does
---------------------
For every word unit whose ``properties.english`` is empty or
whitespace:

1. Find every sentence that lists this word's pinyin id in its
   ``properties.word_refs[]``.
2. Collect those sentences' ``properties.english`` values into a
   list.
3. Pick a representative gloss:
     - If any sentence has a non-empty english, take the shortest
       one (it's usually the cleanest single-word gloss).
     - Otherwise, leave the word's english untouched.
4. Write the word unit back with ``updated`` bumped.

Idempotent — running twice is a no-op (the second run sees all
``english`` slots already filled and finds no candidates).

Parked particles (``了 的 吗 呢 吧 啊 嘛 啦``) are NOT touched —
same policy as the orphan-cleanup script (Note 2 of v0.4-backlog).

Usage
-----
::

    python scripts/backfill_word_english.py [--dry-run] [--vault PATH]

Flags:
  --dry-run      print what would change but make no modifications
  --vault PATH   override vault root (default: $LANGUAGE_BRAIN_VAULT or ./vault)

Exit code: 0 on success (incl. no-op), 1 on I/O error.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

# Allow running this script from anywhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from api.config import get_settings, settings  # noqa: E402
from api.services.unit_writer import (  # noqa: E402
    read_unit,
    unit_path,
    write_unit,
)
from api.services.word_registry import list_all_words  # noqa: E402


log = logging.getLogger("backfill_english")


# Same parked-particle set as the orphan-cleanup script (Note 2 of
# v0.4-backlog). We never touch these even when they're empty —
# they're intentionally noisy reminders of polysemy.
PARKED_HANZI: frozenset[str] = frozenset({
    "了", "的", "吗", "呢", "吧", "啊", "嘛", "啦",
})


def _today_iso() -> str:
    return date.today().isoformat()


def _collect_sentence_englishes(vault_root: str, word_pinyin: str) -> list[str]:
    """Walk every sentence unit; return the english fields of the
    ones that list ``word_pinyin`` in their ``word_refs[]``.
    """
    sentences_dir = Path(vault_root) / "units" / "sentences"
    out: list[str] = []
    if not sentences_dir.is_dir():
        return out
    for f in sentences_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        props = data.get("properties") or {}
        if not isinstance(props, dict):
            continue
        refs = props.get("word_refs") or []
        if not isinstance(refs, list) or word_pinyin not in refs:
            continue
        e = props.get("english")
        if isinstance(e, str) and e.strip():
            out.append(e.strip())
    return out


def _pick_representative(englishes: list[str]) -> str | None:
    """Pick the shortest non-empty english as the cleanest gloss.

    Ties broken by first-seen order (insertion order from the
    sentences directory glob sort).
    """
    cleaned = [e for e in englishes if isinstance(e, str) and e.strip()]
    if not cleaned:
        return None
    return min(cleaned, key=len)


def run_backfill(vault_root: str, dry_run: bool) -> int:
    """Execute the backfill. Returns 0 on success, 1 on I/O error."""
    today = _today_iso()
    filled = 0
    skipped_parked = 0
    skipped_no_context = 0
    errors = 0

    for word in list_all_words(vault_root):
        wid = word.get("id")
        if not isinstance(wid, str) or not wid.strip():
            continue
        props = word.get("properties") or {}
        if not isinstance(props, dict):
            continue
        hanzi = props.get("hanzi") if isinstance(props.get("hanzi"), str) else ""
        current_english = props.get("english")
        if isinstance(current_english, str) and current_english.strip():
            # Already populated — never overwrite.
            continue

        if hanzi in PARKED_HANZI:
            log.info("keeping parked particle: %s (%s)", wid, hanzi)
            skipped_parked += 1
            continue

        englishes = _collect_sentence_englishes(vault_root, wid)
        chosen = _pick_representative(englishes)
        if chosen is None:
            log.info("no sentence context for %s (%s); leaving empty", wid, hanzi)
            skipped_no_context += 1
            continue

        log.info("backfill %s (%s) english=%r", wid, hanzi, chosen)

        if dry_run:
            continue

        # Read the current unit, update, write back. We don't pass
        # through ensure_word_unit because that would no-op on
        # collision; we need a write that updates the field.
        try:
            current = read_unit(vault_root, "word", wid)
        except (OSError, ValueError) as exc:
            log.error("read failed for %s: %s", wid, exc)
            errors += 1
            continue
        cur_props = current.get("properties")
        if not isinstance(cur_props, dict):
            cur_props = {}
        cur_props["english"] = chosen
        current["properties"] = cur_props
        current["updated"] = today
        try:
            write_unit(vault_root, current)
        except OSError as exc:
            log.error("write failed for %s: %s", wid, exc)
            errors += 1
            continue
        filled += 1

    log.info(
        "Backfilled %d word unit(s); skipped %d parked, %d no-context, %d errors",
        filled,
        skipped_parked,
        skipped_no_context,
        errors,
    )
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change but make no modifications.",
    )
    parser.add_argument(
        "--vault",
        default=None,
        help="Override the vault root (default: LANGUAGE_BRAIN_VAULT or ./vault).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.vault is not None:
        get_settings.cache_clear()
        settings.vault = args.vault
    vault_root = settings.vault

    log.info(
        "backfill_word_english: vault=%s dry_run=%s", vault_root, args.dry_run
    )
    return run_backfill(vault_root, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())