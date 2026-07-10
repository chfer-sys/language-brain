"""Tests for scripts/benchmark_search.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure api package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.benchmark_search import (
    _build_synthetic_vault,
    _format_json,
    _format_human,
    _vault_stats,
)


# ---------------------------------------------------------------------------
# Vault fixture helpers
# ---------------------------------------------------------------------------

def _write_unit(vault_root: Path, type_dir: str, unit: dict) -> None:
    """Write a unit JSON file to the vault."""
    unit_dir = vault_root / "units" / type_dir
    unit_dir.mkdir(parents=True, exist_ok=True)
    path = unit_dir / f"{unit['id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(unit, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _write_minimal_vault(vault_root: Path) -> None:
    """Write a minimal vault structure for testing vault_stats."""
    vault_root.mkdir(parents=True, exist_ok=True)
    units_dir = vault_root / "units"
    units_dir.mkdir(exist_ok=True)
    (units_dir / "words").mkdir(exist_ok=True)
    (units_dir / "sentences").mkdir(exist_ok=True)
    (units_dir / "groups").mkdir(exist_ok=True)

    # Write 2 words
    _write_unit(vault_root, "words", {
        "id": "W1", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "I",
                       "meaning": "I", "groups": [], "antonyms": []},
        "connections": [], "created": "2026-07-10", "updated": "2026-07-10",
        "author_confirmed": True,
    })
    _write_unit(vault_root, "words", {
        "id": "W2", "type": "word", "name": "吃",
        "properties": {"hanzi": "吃", "pinyin": "chi1", "english": "eat",
                       "meaning": "eat", "groups": [], "antonyms": []},
        "connections": [], "created": "2026-07-10", "updated": "2026-07-10",
        "author_confirmed": True,
    })

    # Write 3 sentences
    _write_unit(vault_root, "sentences", {
        "id": "S1", "type": "sentence", "name": "我吃",
        "properties": {"hanzi": "我吃", "pinyin": "wo3 chi1",
                       "english": "I eat", "meaning": "I eat",
                       "words": ["我", "吃"], "word_refs": ["W1", "W2"],
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-07-10", "updated": "2026-07-10",
        "author_confirmed": True,
    })
    _write_unit(vault_root, "sentences", {
        "id": "S2", "type": "sentence", "name": "你好",
        "properties": {"hanzi": "你好", "pinyin": "ni3 hao3",
                       "english": "hello", "meaning": "hello",
                       "words": ["你", "好"], "word_refs": [],
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-07-10", "updated": "2026-07-10",
        "author_confirmed": True,
    })
    _write_unit(vault_root, "sentences", {
        "id": "S3", "type": "sentence", "name": "吃我",
        "properties": {"hanzi": "吃我", "pinyin": "chi1 wo3",
                       "english": "eat me", "meaning": "eat me",
                       "words": ["吃", "我"], "word_refs": ["W2", "W1"],
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-07-10", "updated": "2026-07-10",
        "author_confirmed": True,
    })

    # Write 1 group
    _write_unit(vault_root, "groups", {
        "id": "G1", "type": "group", "name": "G1",
        "properties": {"display_name": "Test Group", "description": "",
                       "members": ["S1"]},
        "connections": [], "created": "2026-07-10", "updated": "2026-07-10",
        "author_confirmed": True,
    })


# ---------------------------------------------------------------------------
# test_vault_stats
# ---------------------------------------------------------------------------

def test_vault_stats_counts_units(tmp_path: Path):
    """_vault_stats returns correct counts for a minimal vault."""
    _write_minimal_vault(tmp_path)
    stats = _vault_stats(str(tmp_path))
    assert stats["sentences"] == 3
    assert stats["words"] == 2
    assert stats["groups"] == 1


# ---------------------------------------------------------------------------
# test_synthetic_generation
# ---------------------------------------------------------------------------

def test_synthetic_generation(tmp_path: Path):
    """_build_synthetic_vault creates valid JSON unit files."""
    _build_synthetic_vault(str(tmp_path), n_sentences=10, n_words=3, n_groups=1)

    # Check sentence files
    sentences_dir = tmp_path / "units" / "sentences"
    sentence_files = list(sentences_dir.glob("S*.json"))
    assert len(sentence_files) == 10
    for f in sentence_files:
        with open(f, encoding="utf-8") as fh:
            unit = json.load(fh)
        assert isinstance(unit, dict)
        assert "id" in unit
        assert unit["type"] == "sentence"
        assert "meaning" in unit["properties"]

    # Check word files
    words_dir = tmp_path / "units" / "words"
    word_files = list(words_dir.glob("W*.json"))
    assert len(word_files) == 3
    for f in word_files:
        with open(f, encoding="utf-8") as fh:
            unit = json.load(fh)
        assert isinstance(unit, dict)
        assert unit["type"] in ("word", "compound")

    # Check group files
    groups_dir = tmp_path / "units" / "groups"
    group_files = list(groups_dir.glob("G*.json"))
    assert len(group_files) == 1
    for f in group_files:
        with open(f, encoding="utf-8") as fh:
            unit = json.load(fh)
        assert unit["type"] == "group"

    # Check FAISS index exists
    index_dir = tmp_path / "index"
    assert (index_dir / "faiss.index").is_file()
    assert (index_dir / "embeddings.npy").is_file()
    assert (index_dir / "unit_index.json").is_file()

    # Check id_counters.json
    counters = json.loads((tmp_path / "_meta" / "id_counters.json").read_text(encoding="utf-8"))
    assert counters["S"] == 10
    assert counters["W"] == 3
    assert counters["G"] == 1


# ---------------------------------------------------------------------------
# test_benchmark_runs_on_current_vault
# ---------------------------------------------------------------------------

def test_benchmark_runs_on_current_vault():
    """Benchmark script runs without error against ./vault and produces output."""
    result = subprocess.run(
        [sys.executable, "scripts/benchmark_search.py", "--vault", "./vault"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    output = result.stdout
    assert "Search Benchmark" in output
    assert "lexical" in output.lower()
    assert "semantic" in output.lower()
    assert "suggest" in output.lower()


# ---------------------------------------------------------------------------
# test_json_output
# ---------------------------------------------------------------------------

def test_json_output():
    """--json flag produces valid JSON with expected keys."""
    result = subprocess.run(
        [
            sys.executable, "scripts/benchmark_search.py",
            "--vault", "./vault",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "vault_path" in data
    assert "vault_stats" in data
    assert "current_vault" in data
    cv = data["current_vault"]
    assert "lexical_hanzi" in cv
    assert "lexical_english" in cv
    assert "semantic" in cv
    assert "suggest" in cv
    # Each benchmark has p50, p95, p99
    for key in ("lexical_hanzi", "lexical_english", "semantic", "suggest"):
        for pct in ("p50", "p95", "p99"):
            assert pct in cv[key], f"{key} missing {pct}"


# ---------------------------------------------------------------------------
# test_format_functions
# ---------------------------------------------------------------------------

def test_format_human_does_not_raise():
    """_format_human produces readable output without raising."""
    fake_results = {
        "lexical_hanzi": {"p50": 0.3, "p95": 0.5, "p99": 0.8},
        "lexical_english": {"p50": 0.4, "p95": 0.7, "p99": 1.1},
        "semantic": {"p50": 5.2, "p95": 8.1, "p99": 12.3},
        "suggest": {"p50": 0.2, "p95": 0.3, "p99": 0.5},
    }
    fake_scale = {
        "100": {
            "stats": {"sentences": 100, "words": 33, "groups": 10},
            "lexical_hanzi": {"p50": 1.2, "p95": 2.1, "p99": 3.5},
            "lexical_english": {"p50": 1.5, "p95": 2.8, "p99": 4.2},
            "semantic": {"p50": 8.3, "p95": 12.1, "p99": 18.5},
            "suggest": {"p50": 0.8, "p95": 1.2, "p99": 2.1},
        },
    }
    output = _format_human(
        "/fake/vault",
        {"sentences": 14, "words": 38, "groups": 12},
        fake_results,
        fake_scale,
        thresholds=(20.0, 50.0),
    )
    assert "Search Benchmark" in output
    assert "p50" in output


def test_format_json_does_not_raise():
    """_format_json produces valid JSON without raising."""
    fake_results = {
        "lexical_hanzi": {"p50": 0.3, "p95": 0.5, "p99": 0.8},
        "lexical_english": {"p50": 0.4, "p95": 0.7, "p99": 1.1},
        "semantic": {"p50": 5.2, "p95": 8.1, "p99": 12.3},
        "suggest": {"p50": 0.2, "p95": 0.3, "p99": 0.5},
    }
    output = _format_json(
        "/fake/vault",
        {"sentences": 14, "words": 38, "groups": 12},
        fake_results,
        None,
    )
    data = json.loads(output)
    assert data["vault_path"] == "/fake/vault"
    assert "p50" in data["current_vault"]["lexical_hanzi"]
