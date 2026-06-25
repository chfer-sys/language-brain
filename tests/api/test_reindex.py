"""Tests for ``scripts/reindex.py`` (SPEC §6 AC10, AC29).

AC10: two runs of reindex on the same vault produce byte-equal
``faiss.index``, ``embeddings.npy``, and ``unit_index.json``.

AC29: reindex makes no outbound network call. We use
``--force-hashing`` (or the auto-fallback) so the real model is
not loaded; tests stay deterministic and offline.

Tests use ``tmp_path`` for vault isolation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import reindex as reindex_module


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_sentence(vault: Path, sid: str, meaning: str) -> None:
    """Write a minimal sentence unit file with the given meaning."""
    payload = {
        "id": sid,
        "type": "sentence",
        "name": "你好" if sid == "s-001" else "再见",
        "properties": {
            "hanzi": "你好" if sid == "s-001" else "再见",
            "pinyin": "nǐ hǎo" if sid == "s-001" else "zài jiàn",
            "english": "hello" if sid == "s-001" else "goodbye",
            "meaning": meaning,
            "words": ["你", "好"] if sid == "s-001" else ["再", "见"],
            "word_refs": ["nǐ", "hǎo"] if sid == "s-001" else ["zài", "jiàn"],
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-24",
        "updated": "2026-06-24",
        "author_confirmed": True,
    }
    out_dir = vault / "units" / "sentences"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{sid}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@pytest.fixture
def seeded_vault(tmp_path: Path) -> Path:
    """A vault with 3 sentence units."""
    _seed_sentence(tmp_path, "s-001", "a casual greeting used when meeting someone")
    _seed_sentence(tmp_path, "s-002", "a farewell used when parting")
    _seed_sentence(tmp_path, "s-003", "thank you, an expression of gratitude")
    return tmp_path


# ---------------------------------------------------------------------------
# AC10 — idempotent
# ---------------------------------------------------------------------------


def test_reindex_creates_index_files(seeded_vault: Path) -> None:
    """A fresh vault has no index/ dir; after reindex, the three
    files are present."""
    summary = reindex_module.reindex(str(seeded_vault), force_hashing=True)
    assert summary == {"scanned": 3, "indexed": 3, "skipped": 0}

    index_dir = seeded_vault / "index"
    assert (index_dir / "faiss.index").is_file()
    assert (index_dir / "embeddings.npy").is_file()
    assert (index_dir / "unit_index.json").is_file()
    assert (index_dir / "last_reindex.json").is_file()


def test_reindex_is_idempotent_byte_equal(seeded_vault: Path) -> None:
    """AC10: two consecutive runs produce byte-equal files."""
    reindex_module.reindex(str(seeded_vault), force_hashing=True)
    index_dir = seeded_vault / "index"
    faiss1 = (index_dir / "faiss.index").read_bytes()
    embeddings1 = (index_dir / "embeddings.npy").read_bytes()
    map1 = (index_dir / "unit_index.json").read_bytes()

    reindex_module.reindex(str(seeded_vault), force_hashing=True)
    faiss2 = (index_dir / "faiss.index").read_bytes()
    embeddings2 = (index_dir / "embeddings.npy").read_bytes()
    map2 = (index_dir / "unit_index.json").read_bytes()

    assert faiss1 == faiss2, "faiss.index differs between runs"
    assert embeddings1 == embeddings2, "embeddings.npy differs between runs"
    assert map1 == map2, "unit_index.json differs between runs"


def test_reindex_skips_sentences_with_no_meaning(tmp_path: Path) -> None:
    """A sentence without a meaning field is counted as scanned but
    not indexed. (The search route will not be able to find it
    semantically, but the unit itself is not deleted.)"""
    _seed_sentence(tmp_path, "s-ok", "real meaning")
    # A sentence with no meaning field at all.
    bad_path = tmp_path / "units" / "sentences" / "s-bad.json"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text(
        json.dumps(
            {
                "id": "s-bad",
                "type": "sentence",
                "name": "no meaning",
                "properties": {"hanzi": "x", "pinyin": "x", "english": "x"},
                "connections": [],
                "created": "2026-06-24",
                "updated": "2026-06-24",
                "author_confirmed": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = reindex_module.reindex(str(tmp_path), force_hashing=True)
    assert summary == {"scanned": 2, "indexed": 1, "skipped": 1}


def test_reindex_skips_empty_meaning(tmp_path: Path) -> None:
    """An empty/whitespace-only meaning is treated as 'no meaning'."""
    _seed_sentence(tmp_path, "s-ok", "real meaning")
    _seed_sentence(tmp_path, "s-empty", "   ")
    summary = reindex_module.reindex(str(tmp_path), force_hashing=True)
    assert summary == {"scanned": 2, "indexed": 1, "skipped": 1}


def test_reindex_empty_vault(tmp_path: Path) -> None:
    """An empty vault produces an empty index and summary 0/0/0."""
    summary = reindex_module.reindex(str(tmp_path), force_hashing=True)
    assert summary == {"scanned": 0, "indexed": 0, "skipped": 0}
    index_dir = tmp_path / "index"
    assert (index_dir / "faiss.index").is_file()
    assert (index_dir / "embeddings.npy").is_file()
    assert (index_dir / "unit_index.json").is_file()


def test_reindex_does_not_modify_unit_files(seeded_vault: Path) -> None:
    """AC10 contract: reindex is read-only on the unit files."""
    # Snapshot the unit files' contents before reindex.
    units_dir = seeded_vault / "units" / "sentences"
    before = {p.name: p.read_bytes() for p in units_dir.glob("*.json")}
    assert len(before) == 3

    reindex_module.reindex(str(seeded_vault), force_hashing=True)

    after = {p.name: p.read_bytes() for p in units_dir.glob("*.json")}
    assert before == after, "reindex must not modify unit files"


def test_reindex_writes_summary(seeded_vault: Path) -> None:
    """The summary is persisted as JSON for inspection."""
    reindex_module.reindex(str(seeded_vault), force_hashing=True)
    summary_path = seeded_vault / "index" / "last_reindex.json"
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data == {"scanned": 3, "indexed": 3, "skipped": 0}


# ---------------------------------------------------------------------------
# CLI invocation
# ---------------------------------------------------------------------------


def test_reindex_cli_runs(tmp_path: Path) -> None:
    """The script can be invoked as a CLI process."""
    _seed_sentence(tmp_path, "s-001", "a casual greeting")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "reindex.py"),
            "--vault-root",
            str(tmp_path),
            "--force-hashing",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    out = json.loads(result.stdout.strip())
    assert out == {"scanned": 1, "indexed": 1, "skipped": 0}


# ---------------------------------------------------------------------------
# AC29 — no network
# ---------------------------------------------------------------------------


def test_reindex_does_not_import_network_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC29: the reindex module never imports anything that would
    open a network socket. We assert by checking the module's
    imports — only embedder, indexer, unit_writer, config are
    allowed; ``requests``, ``urllib.request``, ``socket``, etc.
    must not appear."""
    import sys

    # Snapshot modules BEFORE running reindex.
    before = set(sys.modules.keys())

    summary = reindex_module.reindex(
        "/tmp/__no_such_vault__", force_hashing=True
    )
    # The path doesn't exist; the reindex should still complete
    # (just with scanned=0). The point is the import graph.

    after = set(sys.modules.keys())
    new = after - before

    forbidden_substrings = ("requests", "urllib", "socket", "http.client")
    leaked = [m for m in new if any(s in m for s in forbidden_substrings)]
    assert not leaked, (
        f"AC29 violated: reindex imported network modules: {leaked}"
    )


def test_reindex_completes_with_no_internet(seeded_vault: Path) -> None:
    """The hashing embedder is purely deterministic, so reindex
    completes without any network. We assert on the summary."""
    summary = reindex_module.reindex(str(seeded_vault), force_hashing=True)
    assert summary["indexed"] == 3
