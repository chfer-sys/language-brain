"""Tests for ``scripts/fix_compound_types.py``."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.fix_compound_types import run_fix  # noqa: E402


def _make_word_unit(vault_root: Path, unit_id: str, unit_type: str) -> None:
    """Write a minimal word unit file for testing (bypasses write_unit validation)."""
    unit = {
        "id": unit_id,
        "type": unit_type,
        "name": "测试",
        "properties": {
            "hanzi": "测试",
            "pinyin": "cèsì",
            "english": "test",
            "meaning": "",
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-28",
        "updated": "2026-06-28",
        "author_confirmed": True,
    }
    words_dir = vault_root / "units" / "words"
    words_dir.mkdir(parents=True, exist_ok=True)
    fpath = words_dir / f"{unit_id}.json"
    fpath.write_text(json.dumps(unit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_c1_flipped_word_to_compound(tmp_path: Path) -> None:
    """C1 with type:word is corrected to type:compound."""
    _make_word_unit(tmp_path, "C1", "word")
    corrected, already = run_fix(str(tmp_path))
    assert corrected == 1
    assert already == 0

    c1 = json.loads((tmp_path / "units" / "words" / "C1.json").read_text(encoding="utf-8"))
    assert c1["type"] == "compound"


def test_c2_already_compound_untouched(tmp_path: Path) -> None:
    """C2 already with type:compound is not modified."""
    _make_word_unit(tmp_path, "C2", "compound")
    corrected, already = run_fix(str(tmp_path))
    assert corrected == 0
    assert already == 1

    c2 = json.loads((tmp_path / "units" / "words" / "C2.json").read_text(encoding="utf-8"))
    assert c2["type"] == "compound"


def test_w1_word_untouched(tmp_path: Path) -> None:
    """W1 (a single-hanzi word) keeps type:word and is not touched."""
    _make_word_unit(tmp_path, "W1", "word")
    corrected, already = run_fix(str(tmp_path))
    assert corrected == 0
    assert already == 0  # W1 doesn't match the C-pattern

    w1 = json.loads((tmp_path / "units" / "words" / "W1.json").read_text(encoding="utf-8"))
    assert w1["type"] == "word"
    assert w1["id"] == "W1"


def test_idempotent_second_run_reports_zero_changes(tmp_path: Path) -> None:
    """Running the fix twice: first run corrects, second reports zero changes."""
    _make_word_unit(tmp_path, "C1", "word")

    # First run: corrects the type
    corrected1, already1 = run_fix(str(tmp_path))
    assert corrected1 == 1

    # Second run: nothing to do
    corrected2, already2 = run_fix(str(tmp_path))
    assert corrected2 == 0
    assert already2 == 1  # C1 is now already correct
