"""One-shot cleanup script: re-segment every sentence in the vault
with the current user-curated segmenter, delete orphan word units, and
create compound word units that the new segmentation references.

Background
----------
Pre-T34 sentences were committed with jieba's default greedy
segmentation, which split compounds like ``口水`` into ``["口", "水"]``.
Each token became its own word unit (``口.json``, ``水.json``, ``了.json``,
``流.json``, ``我.json``), all with `id == hanzi` (not valid pinyin).
These are "orphan" word units: single-char tokens that should have been
parts of a compound.

T34 introduced the user-curated segmenter (`api.services.segmenter`).
Going forward, new sentences are segmented correctly. This script
retroactively applies the same fix to every existing sentence.

What it does
------------
For every sentence unit under ``<vault>/units/sentences/``:

1. Re-segment ``properties.hanzi`` with
   :func:`api.services.segmenter.lcut`.
2. Derive new ``word_refs`` via :func:`pypinyin.lazy_pinyin` (TONE
   style). The T34 commit handler uses this fallback when the AI's
   ``word_refs`` doesn't match jieba's segmentation; we mirror it
   here so the cleaned-up sentences match what new saves will produce.
3. Ensure every newly-referenced word unit exists (idempotent via
   :func:`api.services.word_registry.ensure_word_unit`).
4. Write the sentence back with ``words`` and ``word_refs`` replaced.
   ``updated`` is bumped to today; ``created`` is preserved.

After all sentences are re-segmented:

5. Walk every word unit under ``<vault>/units/words/``. If its id is
   NOT in any sentence's ``word_refs[]`` AND its hanzi is not a
   "parked" particle (see :data:`PARKED_HANZI` below), delete the
   file.

The ``PARKED_HANZI`` set comes from Note 2 of
``.specs/v0.4-backlog.md``: the user explicitly accepts the noise of
having a ``了`` (or ``的``, ``吗``, ``呢``, ``吧``, ``啊``, ``嘛``, ``啦``)
word unit even though it's a single character. We never delete a file
for one of these — it stays as a "noisy but harmless" reminder of the
polysemy the segmenter has to handle context-by-context.

Usage
-----

::

    python scripts/cleanup_orphan_words.py [--dry-run] [--vault PATH]

Flags:

* ``--dry-run`` — print what would change but make no modifications.
* ``--vault PATH`` — override the vault root. Default is whatever
  ``LANGUAGE_BRAIN_VAULT`` resolves to (typically ``./vault``).

Exit code is 0 on success (including the no-op case) and 1 if any
I/O error occurred (logged to stderr).

Idempotency
-----------
Running this script twice is safe. The first run re-segments and
deletes orphans; the second run sees the sentence files already use
the new segmentation, walks the word files, finds no orphans, and
exits as a no-op. The connector is also run once at the end of the
script so the connections reflect the new word ids.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

# Allow running this script from anywhere: add the repo root to sys.path
# so ``import api.*`` works without an install step.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from api.config import get_settings, settings  # noqa: E402
from api.services.connector import compute_connections  # noqa: E402
from api.services.embedder import get_embedder  # noqa: E402
from api.services.segmenter import lcut as segmenter_lcut  # noqa: E402
from api.services.unit_writer import (  # noqa: E402
    read_unit,
    unit_path,
    write_unit,
)
from api.services.word_registry import ensure_word_unit, list_all_words  # noqa: E402


log = logging.getLogger("cleanup")


# Hanzi the user has explicitly accepted as word-unit noise per Note 2
# of .specs/v0.4-backlog.md. Files for these are NEVER deleted by the
# cleanup, even if they end up unreferenced after re-segmentation.
PARKED_HANZI: frozenset[str] = frozenset({
    "了", "的", "吗", "呢", "吧", "啊", "嘛", "啦",
})


def _today_iso() -> str:
    return date.today().isoformat()


def _derive_pinyin_for(token: str) -> str:
    """Return the TONE-style pinyin for a single hanzi token.

    For single characters and compounds alike we concatenate
    :func:`pypinyin.lazy_pinyin` output (no separator). Falls back to
    the hanzi verbatim if pypinyin can't decode (very rare).
    """
    from pypinyin import Style, lazy_pinyin  # type: ignore[import-untyped]

    parts = lazy_pinyin(token, style=Style.TONE)
    out = "".join(parts).strip()
    return out or token


def _resegment_sentence(sentence: dict) -> tuple[list[str], list[str]] | None:
    """Return (new_words, new_word_refs) for a sentence, or None if
    the sentence's hanzi doesn't need re-segmentation.

    "Needs re-segmentation" means the current ``properties.words[]``
    does not match what the current segmenter produces from
    ``properties.hanzi``. The result is what :func:`commit_sentence`
    would produce today (with no AI assist).
    """
    props = sentence.get("properties")
    if not isinstance(props, dict):
        return None
    hanzi = props.get("hanzi")
    if not isinstance(hanzi, str) or not hanzi.strip():
        return None
    existing_words = props.get("words") or []
    if not isinstance(existing_words, list):
        existing_words = []

    new_words = segmenter_lcut(hanzi)
    if list(existing_words) == new_words:
        return None
    new_refs = [_derive_pinyin_for(w) for w in new_words]
    return new_words, new_refs


def _ensure_word_units(vault_root: str, words: list[str], refs: list[str]) -> None:
    """Make sure each (word, ref) pair has a word unit file. Idempotent."""
    for w, r in zip(words, refs):
        if not isinstance(w, str) or not w.strip():
            continue
        if not isinstance(r, str) or not r.strip():
            continue
        ensure_word_unit(
            vault_root,
            hanzi=w,
            pinyin=r,
            english="",
            meaning="",
        )


def _all_sentence_word_refs(vault_root: str) -> set[str]:
    """Return the union of ``word_refs[]`` across every sentence unit."""
    sentences_dir = Path(vault_root) / "units" / "sentences"
    out: set[str] = set()
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
        if not isinstance(refs, list):
            continue
        for r in refs:
            if isinstance(r, str) and r.strip():
                out.add(r)
    return out


def _maybe_delete_orphan(
    vault_root: str,
    word_unit: dict,
    referenced_ids: set[str],
    dry_run: bool,
) -> bool:
    """Delete an orphan word unit file unless its hanzi is parked.

    An "orphan" is a word unit whose ``id`` is not in
    ``referenced_ids``. Parked hanzi (``了``, ``的``, etc.) are kept
    even when orphaned — that's the user's explicit policy from
    Note 2 of the v0.4 backlog.

    Returns True when a delete happened (or would happen in dry-run).
    """
    wid = word_unit.get("id")
    if not isinstance(wid, str) or not wid.strip():
        return False
    if wid in referenced_ids:
        return False
    props = word_unit.get("properties") or {}
    hanzi = props.get("hanzi") if isinstance(props, dict) else None
    if isinstance(hanzi, str) and hanzi in PARKED_HANZI:
        log.info("  keeping parked particle word unit: %s", wid)
        return False
    path = unit_path(vault_root, "word", wid)
    if not path.is_file():
        return False
    if dry_run:
        log.info("  [dry-run] would delete orphan word unit: %s", path)
    else:
        path.unlink()
        log.info("  deleted orphan word unit: %s", path)
    return True


def run_cleanup(vault_root: str, dry_run: bool) -> int:
    """Execute the cleanup. Returns 0 on success, 1 on I/O error."""
    today = _today_iso()

    # Phase 1 — re-segment every sentence.
    sentences_dir = Path(vault_root) / "units" / "sentences"
    if not sentences_dir.is_dir():
        log.error("Sentences directory not found: %s", sentences_dir)
        return 1

    re_seg_count = 0
    error_count = 0
    # Track every (sentence_id, word_ref) pair in their **post-re-
    # segmentation** state. We need this so phase 2 sees the new
    # references even in dry-run mode where the sentence files on
    # disk haven't been written yet. Mapping by sentence_id lets us
    # REPLACE (not add) refs when a sentence is re-segmented.
    live_refs_by_sentence: dict[str, set[str]] = {}

    for f in sorted(sentences_dir.glob("*.json")):
        try:
            sentence = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.error("failed to read %s: %s", f, exc)
            error_count += 1
            continue
        if not isinstance(sentence, dict):
            continue
        sid = sentence.get("id") or f.stem

        # Record the current on-disk refs under this sentence's id so
        # sentences that DON'T need re-segmentation still contribute
        # their references to phase 2.
        props = sentence.get("properties") or {}
        existing_refs: set[str] = set()
        if isinstance(props, dict):
            for r in (props.get("word_refs") or []):
                if isinstance(r, str) and r.strip():
                    existing_refs.add(r)
        live_refs_by_sentence[sid] = existing_refs

        result = _resegment_sentence(sentence)
        if result is None:
            continue
        new_words, new_refs = result
        log.info(
            "re-segment sentence id=%s: %s -> words=%s refs=%s",
            sid,
            (sentence.get("properties") or {}).get("words"),
            new_words,
            new_refs,
        )

        # Ensure every referenced word unit exists on disk.
        try:
            _ensure_word_units(vault_root, new_words, new_refs)
        except Exception as exc:  # pragma: no cover - defensive
            log.error("ensure_word_unit failed for sentence %s: %s", sid, exc)
            error_count += 1
            continue

        # Update the sentence file (preserving created; bumping updated).
        props["words"] = new_words
        props["word_refs"] = new_refs
        sentence["properties"] = props
        sentence["updated"] = today
        if not sentence.get("created"):
            sentence["created"] = today

        # Replace this sentence's refs with the post-re-segment set.
        live_refs_by_sentence[sid] = {r for r in new_refs if isinstance(r, str) and r.strip()}

        if not dry_run:
            try:
                write_unit(vault_root, sentence)
            except Exception as exc:
                log.error("write_unit failed for sentence %s: %s", sid, exc)
                error_count += 1
                continue
        re_seg_count += 1

    # Flatten per-sentence refs into a single set for phase 2.
    live_refs: set[str] = set()
    for refs in live_refs_by_sentence.values():
        live_refs |= refs

    log.info("Phase 1: re-segmented %d sentence(s)", re_seg_count)

    # Phase 2 — delete orphan word units.
    delete_count = 0
    for w in list_all_words(vault_root):
        if _maybe_delete_orphan(vault_root, w, live_refs, dry_run):
            delete_count += 1
    log.info("Phase 2: deleted %d orphan word unit(s)", delete_count)

    # Phase 3 — re-run the connector so lexical/semantic/group/opposite
    # edges reflect the new word ids. Skip in dry-run (no I/O).
    if not dry_run:
        try:
            summary = compute_connections(vault_root, embedder=get_embedder())
            log.info("Phase 3: connector summary=%s", summary)
        except Exception as exc:
            log.error("connector failed during cleanup: %s", exc)
            error_count += 1

    if error_count:
        log.error("cleanup finished with %d error(s)", error_count)
        return 1
    return 0


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
        vault_root = args.vault
        # Override the settings singleton so downstream imports (embedder,
        # connector) read the right root.
        get_settings.cache_clear()
        settings.vault = args.vault
    else:
        vault_root = settings.vault

    log.info("cleanup_orphan_words: vault=%s dry_run=%s", vault_root, args.dry_run)
    return run_cleanup(vault_root, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
