"""Tests for scripts/vault_check.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure api package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.build_dictionary import _import_source
from scripts.vault_check import (
    check_antonym_asymmetry,
    check_counter_consistency,
    check_dict_misalignment,
    check_dangling_refs,
    check_duplicate_units,
    check_id_filename_mismatch,
    check_lexical_edge_gap,
    check_missing_units,
    check_type_id_mismatch,
    fix_antonym_asymmetry,
    fix_lexical_edge_gap,
    fix_missing_unit,
    is_id_ref,
    main as vault_check_main,
)


# ---------------------------------------------------------------------------
# Seed helper (same as tests/api/conftest.py)
# ---------------------------------------------------------------------------

SEGMENT_FIXTURE = Path(__file__).parent.parent / "fixtures" / "segment_fixture.txt"


def _seed_dictionary(vault_root: str) -> None:
    """Populate the word table using the segment_fixture."""
    _import_source(
        vault_root=vault_root,
        source_id="segment-fixture",
        source_name="Segment Fixture",
        source_version="1.0",
        license="CC-BY",
        attribution="Test fixture",
        priority=50,
        csv_path=str(SEGMENT_FIXTURE),
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


def _read_unit(vault_root: Path, type_dir: str, unit_id: str) -> dict | None:
    """Read a unit JSON file."""
    path = vault_root / "units" / type_dir / f"{unit_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_counters(vault_root: Path, counters: dict) -> None:
    """Write id_counters.json."""
    meta_dir = vault_root / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    path = meta_dir / "id_counters.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(counters, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# is_id_ref tests
# ---------------------------------------------------------------------------

def test_is_id_ref():
    assert is_id_ref("W1") is True
    assert is_id_ref("C99") is True
    assert is_id_ref("S123") is True
    assert is_id_ref("G5") is True
    assert is_id_ref("闹") is False  # hanzi, not id
    assert is_id_ref("随便") is False  # hanzi, not id
    assert is_id_ref("W") is False  # no number
    assert is_id_ref("WABC") is False  # not numeric


# ---------------------------------------------------------------------------
# test_clean_vault
# ---------------------------------------------------------------------------

def test_clean_vault(tmp_path: Path):
    """All checks pass on a correct vault."""
    _seed_dictionary(str(tmp_path))

    # Write a minimal clean vault
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "I", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "sentences", {
        "id": "S1", "type": "sentence", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "I",
                       "meaning": "", "words": ["我"], "word_refs": ["W1"],
                       "groups": [], "antonyms": []},
        "connections": [{"to": "S1", "kind": "lexical", "score": 1.0}],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "I", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [{"to": "S1", "kind": "lexical", "score": 1.0}],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_counters(tmp_path, {"W": 1, "C": 0, "S": 1, "G": 0})

    assert check_dangling_refs(tmp_path) == []
    assert check_missing_units(tmp_path) == []
    assert check_duplicate_units(tmp_path) == []
    assert check_id_filename_mismatch(tmp_path) == []
    assert check_type_id_mismatch(tmp_path) == []
    # Dict misalignment: not_in_dict since our fixture has different ids
    assert all(i.get("status") != "MISALIGNED" for i in check_dict_misalignment(tmp_path))
    assert check_antonym_asymmetry(tmp_path) == []
    assert check_lexical_edge_gap(tmp_path) == []
    assert check_counter_consistency(tmp_path) == []


# ---------------------------------------------------------------------------
# test_dangling_ref_detected
# ---------------------------------------------------------------------------

def test_dangling_ref_detected(tmp_path: Path):
    """Sentence references W999 (no file) → DANGLING_REFS flags it."""
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "sentences", {
        "id": "S1", "type": "sentence", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "",
                       "meaning": "", "words": ["我"], "word_refs": ["W1", "W999"],
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    issues = check_dangling_refs(tmp_path)
    assert len(issues) == 1
    assert issues[0]["target"] == "W999"
    assert issues[0]["kind"] == "word_refs"


# ---------------------------------------------------------------------------
# test_missing_unit_detected
# ---------------------------------------------------------------------------

def test_missing_unit_detected(tmp_path: Path):
    """Word_ref with no unit file → MISSING_UNITS flags it."""
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "sentences", {
        "id": "S1", "type": "sentence", "name": "我吃",
        "properties": {"hanzi": "我吃", "pinyin": "wo3 chi1", "english": "",
                       "meaning": "", "words": ["我", "吃"], "word_refs": ["W1", "W888"],
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    issues = check_missing_units(tmp_path)
    assert len(issues) == 1
    assert issues[0]["target"] == "W888"


# ---------------------------------------------------------------------------
# test_duplicate_detected
# ---------------------------------------------------------------------------

def test_duplicate_detected(tmp_path: Path):
    """Two files with same (hanzi, pinyin) → DUPLICATE_UNITS flags it."""
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "words", {
        "id": "W2", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    issues = check_duplicate_units(tmp_path)
    assert len(issues) == 1
    assert set(issues[0]["files"]) == {"W1", "W2"}
    assert issues[0]["hanzi"] == "我"
    assert issues[0]["pinyin"] == "wo3"


# ---------------------------------------------------------------------------
# test_id_filename_mismatch_detected
# ---------------------------------------------------------------------------

def test_id_filename_mismatch_detected(tmp_path: Path):
    """File W4.json with id="W5" → ID_FILENAME_MISMATCH."""
    _write_unit(tmp_path, "words", {
        "id": "W5", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    # Rename to wrong filename
    (tmp_path / "units" / "words" / "W5.json").rename(
        tmp_path / "units" / "words" / "W4.json"
    )

    issues = check_id_filename_mismatch(tmp_path)
    assert len(issues) == 1
    assert issues[0]["file"] == "W4"
    assert issues[0]["expected"] == "W5"


# ---------------------------------------------------------------------------
# test_type_id_mismatch_detected
# ---------------------------------------------------------------------------

def test_type_id_mismatch_detected(tmp_path: Path):
    """W-prefixed file with type=compound → TYPE_ID_MISMATCH."""
    _write_unit(tmp_path, "words", {
        "id": "W99", "type": "compound", "name": "别的",
        "properties": {"hanzi": "别的", "pinyin": "bie2 de5", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    issues = check_type_id_mismatch(tmp_path)
    assert len(issues) == 1
    assert issues[0]["file"] == "W99"
    assert issues[0]["type"] == "compound"


# ---------------------------------------------------------------------------
# test_antonym_asymmetry_detected
# ---------------------------------------------------------------------------

def test_antonym_asymmetry_detected(tmp_path: Path):
    """A→B but B doesn't have A → ANTONYM_ASYMMETRY."""
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "好",
        "properties": {"hanzi": "好", "pinyin": "hao3", "english": "", "meaning": "",
                       "groups": [], "antonyms": ["W2"]},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "words", {
        "id": "W2", "type": "word", "name": "坏",
        "properties": {"hanzi": "坏", "pinyin": "huai4", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    issues = check_antonym_asymmetry(tmp_path)
    assert len(issues) == 1
    assert issues[0]["file"] == "W1"
    assert issues[0]["target"] == "W2"


# ---------------------------------------------------------------------------
# test_fix_creates_missing_unit
# ---------------------------------------------------------------------------

def test_fix_creates_missing_unit(tmp_path: Path):
    """--fix creates a missing unit file from dict lookup."""
    _seed_dictionary(str(tmp_path))

    # Get the dict id for "我"
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "index" / "vault.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id, hanzi, pinyin, english FROM word WHERE hanzi='我'").fetchone()
    conn.close()
    assert row is not None
    dict_id = row["id"]
    dict_hanzi = row["hanzi"]
    dict_pinyin = row["pinyin"]

    # Create sentence referencing the missing word
    _write_unit(tmp_path, "sentences", {
        "id": "S1", "type": "sentence", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "",
                       "meaning": "", "words": ["我"], "word_refs": [dict_id],
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    # Verify the word file is missing
    assert not (tmp_path / "units" / "words" / f"{dict_id}.json").exists()

    # Fix it
    fixed = fix_missing_unit(tmp_path, "S1", dict_id)
    assert fixed is True

    # Verify it was created
    assert (tmp_path / "units" / "words" / f"{dict_id}.json").exists()
    unit = _read_unit(tmp_path, "words", dict_id)
    assert unit["id"] == dict_id
    assert unit["properties"]["hanzi"] == dict_hanzi


# ---------------------------------------------------------------------------
# test_fix_adds_lexical_edge
# ---------------------------------------------------------------------------

def test_fix_adds_lexical_edge(tmp_path: Path):
    """--fix adds a missing lexical edge."""
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],  # No lexical edge to S1
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "sentences", {
        "id": "S1", "type": "sentence", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "",
                       "meaning": "", "words": ["我"], "word_refs": ["W1"],
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    # Verify the edge is missing
    assert check_lexical_edge_gap(tmp_path) != []

    # Fix it
    fixed = fix_lexical_edge_gap(tmp_path, "S1", "W1")
    assert fixed is True

    # Verify edge was added
    unit = _read_unit(tmp_path, "words", "W1")
    lexical_tos = {c["to"] for c in unit.get("connections", []) if c.get("kind") == "lexical"}
    assert "S1" in lexical_tos


# ---------------------------------------------------------------------------
# test_hanzi_antonym_not_flagged
# ---------------------------------------------------------------------------

def test_hanzi_antonym_not_flagged(tmp_path: Path):
    """antonyms=["闹"] (hanzi, not id) → not flagged as dangling."""
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "安静",
        "properties": {"hanzi": "安静", "pinyin": "an1 jing4", "english": "", "meaning": "",
                       "groups": [], "antonyms": ["闹"]},  # hanzi string, not id
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    issues = check_dangling_refs(tmp_path)
    # "闹" is not an id ref (no W/C/S/G prefix + number), so not flagged
    dangling_antons = [i for i in issues if i.get("kind") == "antonyms"]
    assert dangling_antons == []


# ---------------------------------------------------------------------------
# test_antonym_asymmetry_fix
# ---------------------------------------------------------------------------

def test_fix_antonym_asymmetry(tmp_path: Path):
    """--fix adds the missing reciprocal antonym."""
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "好",
        "properties": {"hanzi": "好", "pinyin": "hao3", "english": "", "meaning": "",
                       "groups": [], "antonyms": ["W2"]},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "words", {
        "id": "W2", "type": "word", "name": "坏",
        "properties": {"hanzi": "坏", "pinyin": "huai4", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    fixed = fix_antonym_asymmetry(tmp_path, "W2", "W1")
    assert fixed is True

    # Verify reciprocal was added
    unit = _read_unit(tmp_path, "words", "W2")
    assert "W1" in unit["properties"]["antonyms"]


# ---------------------------------------------------------------------------
# test_exit_code
# ---------------------------------------------------------------------------

def test_exit_code_clean(tmp_path: Path):
    """Clean vault → exit 0."""
    _seed_dictionary(str(tmp_path))
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "I", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_counters(tmp_path, {"W": 1, "C": 0, "S": 0, "G": 0})

    rc = vault_check_main(["--vault-root", str(tmp_path)])
    assert rc == 0


def test_exit_code_with_issues(tmp_path: Path):
    """Issues found → exit 1."""
    # No seed, dangling ref
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "sentences", {
        "id": "S1", "type": "sentence", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "",
                       "meaning": "", "words": ["我"], "word_refs": ["W1", "W999"],
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    rc = vault_check_main(["--vault-root", str(tmp_path)])
    assert rc == 1


# ---------------------------------------------------------------------------
# test_counter_consistency
# ---------------------------------------------------------------------------

def test_counter_consistency_low(tmp_path: Path):
    """Counter lower than actual max → COUNTER_CONSISTENCY flags it."""
    _write_unit(tmp_path, "words", {
        "id": "W1", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wo3", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "words", {
        "id": "W999", "type": "word", "name": "你",
        "properties": {"hanzi": "你", "pinyin": "ni3", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_counters(tmp_path, {"W": 1, "C": 0, "S": 0, "G": 0})  # counter too low

    issues = check_counter_consistency(tmp_path)
    assert len(issues) == 1
    assert issues[0]["type"] == "W"
    assert issues[0]["counter"] == 1
    assert issues[0]["max_actual"] == 999
