"""Generate vault/index/vault.dump.sql from vault/index/vault.db.

The dump is the git-tracked mirror — line-oriented SQL that's diffable
in code review. The binary ``.db`` is gitignored. Restore via:

    cat vault/index/vault.dump.sql | sqlite3 vault/index/vault.db

ponytail: one subprocess call. No new deps.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def dump(vault_root: str) -> Path:
    """Run ``sqlite3 vault.db .dump`` into ``vault/index/vault.dump.sql``.

    Returns the dump path. Requires the ``sqlite3`` CLI on PATH.
    """
    if shutil.which("sqlite3") is None:
        raise RuntimeError("sqlite3 CLI not found on PATH")
    db_path = Path(vault_root) / "index" / "vault.db"
    dump_path = Path(vault_root) / "index" / "vault.dump.sql"
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} does not exist; run migrate first")
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    with dump_path.open("w", encoding="utf-8") as f:
        subprocess.run(
            ["sqlite3", str(db_path), ".dump"],
            check=True,
            stdout=f,
        )
    return dump_path


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--vault", default="./vault", help="vault root (default: ./vault)")
    args = parser.parse_args()
    path = dump(args.vault)
    print(f"[dump_vault_sqlite] wrote {path}")


if __name__ == "__main__":
    _cli()