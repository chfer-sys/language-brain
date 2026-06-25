"""Reindex the FAISS index from the canonical vault.

Walks every sentence unit under ``<vault>/units/sentences/``,
embeds the ``meaning`` field, and rebuilds:

* ``<vault>/index/faiss.index``
* ``<vault>/index/embeddings.npy``
* ``<vault>/index/unit_index.json``

Usage:
    python scripts/reindex.py [--vault-root PATH]

If ``--vault-root`` is omitted, the vault root is read from
``get_settings().vault`` (env var ``LANGUAGE_BRAIN_VAULT`` or
default ``./vault/``).

AC10 (idempotency)
-------------------
Two runs on the same vault produce byte-equal ``faiss.index``,
``embeddings.npy``, and ``unit_index.json``. The script must NOT
modify the underlying unit files (no ``updated`` timestamp bump).
This is enforced because the only writes the script makes are to
``<vault>/index/``, never to ``<vault>/units/``.

AC29 (no network)
------------------
The reindex script never makes an outbound network call. The
embedder loads the local sentence-transformers model on first
call and caches it; subsequent runs are fully offline. If the
model fails to load (no network, no torch, etc.), the factory
falls back to ``HashingEmbedder`` and reindex still completes.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from api.config import configure_root_logger
from api.services.embedder import get_embedder, reset_embedder_singleton
from api.services.indexer import Index
from api.services.unit_writer import list_all_sentences

log = logging.getLogger(__name__)


def reindex(vault_root: str, *, force_hashing: bool = False) -> dict[str, int]:
    """Rebuild the FAISS index from the vault's sentence units.

    Returns a small summary ``{"scanned": N, "indexed": M, "skipped": K}``
    where ``skipped`` counts sentence units missing the ``meaning``
    field. The summary is also written to ``<vault>/index/last_reindex.json``
    so tests can inspect what the last run did.
    """
    reset_embedder_singleton()
    embedder = get_embedder(force="hashing" if force_hashing else None)

    sentences = list_all_sentences(vault_root)
    log.info("reindex: found %d sentence units under %s", len(sentences), vault_root)

    index = Index()
    scanned = 0
    indexed = 0
    skipped = 0
    for sentence in sentences:
        scanned += 1
        meaning = sentence.get("properties", {}).get("meaning", "")
        sid = sentence.get("id")
        if not sid or not isinstance(meaning, str) or not meaning.strip():
            skipped += 1
            continue
        vec = embedder.embed(meaning)
        index.add(sid, vec)
        indexed += 1

    index.save(vault_root)

    summary = {"scanned": scanned, "indexed": indexed, "skipped": skipped}
    summary_path = Path(vault_root) / "index" / "last_reindex.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("reindex: %s", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--vault-root",
        default=None,
        help="Path to the vault root. Defaults to LANGUAGE_BRAIN_VAULT or ./vault/.",
    )
    parser.add_argument(
        "--force-hashing",
        action="store_true",
        help="Use the deterministic HashingEmbedder instead of the real model. "
        "Useful for tests and offline runs.",
    )
    args = parser.parse_args(argv)

    configure_root_logger()

    if args.vault_root is None:
        from api.config import get_settings

        vault_root = get_settings().vault
    else:
        vault_root = args.vault_root

    summary = reindex(vault_root, force_hashing=args.force_hashing)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
