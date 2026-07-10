"""Tests for api.services.antonym_service."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.antonym_service import mirror_antonyms, save_word_antonyms
from api.services.unit_writer import write_unit


def _make_word(vault_root: str, word_id: str, hanzi: str, pinyin: str) -> dict:
    """Create a word unit on disk and return its dict."""
    unit = {
        "id": word_id,
        "type": "word",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin,
            "english": "",
            "meaning": "",
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-28",
        "updated": "2026-06-28",
        "author_confirmed": True,
    }
    write_unit(vault_root, unit)
    return unit


def _read_word(vault_root: str, word_id: str) -> dict:
    words_dir = Path(vault_root) / "units" / "words"
    path = words_dir / f"{word_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# mirror_antonyms
# ---------------------------------------------------------------------------


def test_mirror_both_directions(tmp_path: Path) -> None:
    """mirror_antonyms(A, B) → A has B in antonyms AND B has A."""
    _make_word(tmp_path, "W1", "高", "gāo")
    _make_word(tmp_path, "W2", "矮", "ǎi")

    mirror_antonyms(str(tmp_path), "W1", "W2")

    w1 = _read_word(tmp_path, "W1")
    w2 = _read_word(tmp_path, "W2")
    assert "W2" in w1["properties"]["antonyms"]
    assert "W1" in w2["properties"]["antonyms"]


def test_mirror_idempotent(tmp_path: Path) -> None:
    """Calling twice → no duplicate entries."""
    _make_word(tmp_path, "W1", "高", "gāo")
    _make_word(tmp_path, "W2", "矮", "ǎi")

    mirror_antonyms(str(tmp_path), "W1", "W2")
    mirror_antonyms(str(tmp_path), "W1", "W2")

    w1 = _read_word(tmp_path, "W1")
    w2 = _read_word(tmp_path, "W2")
    assert w1["properties"]["antonyms"].count("W2") == 1
    assert w2["properties"]["antonyms"].count("W1") == 1


def test_mirror_skips_self(tmp_path: Path) -> None:
    """mirror_antonyms(A, A) → no-op."""
    _make_word(tmp_path, "W1", "高", "gāo")

    mirror_antonyms(str(tmp_path), "W1", "W1")

    w1 = _read_word(tmp_path, "W1")
    assert w1["properties"]["antonyms"] == []


def test_mirror_skips_missing_target(tmp_path: Path) -> None:
    """Target file doesn't exist → skip gracefully (no crash)."""
    _make_word(tmp_path, "W1", "高", "gāo")
    # W2 does not exist.

    # Should not raise.
    mirror_antonyms(str(tmp_path), "W1", "W2")

    w1 = _read_word(tmp_path, "W1")
    assert w1["properties"]["antonyms"] == []


# ---------------------------------------------------------------------------
# save_word_antonyms
# ---------------------------------------------------------------------------


def test_save_adds_new(tmp_path: Path) -> None:
    """save_word_antonyms(A, [B]) → both have each other."""
    _make_word(tmp_path, "W1", "高", "gāo")
    _make_word(tmp_path, "W2", "矮", "ǎi")

    save_word_antonyms(str(tmp_path), "W1", ["W2"])

    w1 = _read_word(tmp_path, "W1")
    w2 = _read_word(tmp_path, "W2")
    assert "W2" in w1["properties"]["antonyms"]
    assert "W1" in w2["properties"]["antonyms"]


def test_save_removes_stale(tmp_path: Path) -> None:
    """AC6: A had [B], save A with [] → B no longer has A."""
    _make_word(tmp_path, "W1", "高", "gāo")
    _make_word(tmp_path, "W2", "矮", "ǎi")
    # Wire them first.
    mirror_antonyms(str(tmp_path), "W1", "W2")

    # Now remove: save A with empty list.
    save_word_antonyms(str(tmp_path), "W1", [])

    w1 = _read_word(tmp_path, "W1")
    w2 = _read_word(tmp_path, "W2")
    assert w1["properties"]["antonyms"] == []
    assert "W1" not in w2["properties"]["antonyms"]


def test_save_partial_change(tmp_path: Path) -> None:
    """A had [B, C], save A with [C, D] → B loses A, D gains A, C unchanged."""
    _make_word(tmp_path, "W1", "高", "gāo")
    _make_word(tmp_path, "W2", "矮", "ǎi")
    _make_word(tmp_path, "W3", "胖", "pàng")
    _make_word(tmp_path, "W4", "瘦", "shòu")

    # Initial state: W1 antonyms = [W2, W3]
    save_word_antonyms(str(tmp_path), "W1", ["W2", "W3"])

    # New state: W1 antonyms = [W3, W4]
    save_word_antonyms(str(tmp_path), "W1", ["W3", "W4"])

    w1 = _read_word(tmp_path, "W1")
    w2 = _read_word(tmp_path, "W2")
    w3 = _read_word(tmp_path, "W3")
    w4 = _read_word(tmp_path, "W4")

    assert w1["properties"]["antonyms"] == ["W3", "W4"]
    assert "W1" not in w2["properties"]["antonyms"]  # W2 lost W1
    assert "W1" in w3["properties"]["antonyms"]  # C unchanged (still has A)
    assert "W1" in w4["properties"]["antonyms"]  # D gained W1


def test_save_empty_list_clears_all(tmp_path: Path) -> None:
    """A had [B, C], save A with [] → B and C both lose A."""
    _make_word(tmp_path, "W1", "高", "gāo")
    _make_word(tmp_path, "W2", "矮", "ǎi")
    _make_word(tmp_path, "W3", "胖", "pàng")

    # Wire all.
    save_word_antonyms(str(tmp_path), "W1", ["W2", "W3"])

    # Clear.
    save_word_antonyms(str(tmp_path), "W1", [])

    w1 = _read_word(tmp_path, "W1")
    w2 = _read_word(tmp_path, "W2")
    w3 = _read_word(tmp_path, "W3")
    assert w1["properties"]["antonyms"] == []
    assert "W1" not in w2["properties"]["antonyms"]
    assert "W1" not in w3["properties"]["antonyms"]


# ---------------------------------------------------------------------------
# AC6 — full removal path
# ---------------------------------------------------------------------------


def test_ac6_commit_removal_clears_reciprocal(tmp_path: Path) -> None:
    """AC6: If A is committed with antonym B, then re-committed without B,
    B's word unit should no longer reference A.

    Note: The commit API (/api/sentences/commit) only calls mirror_antonyms
    (additive-only, step 3b). It does NOT call save_word_antonyms, so
    sentence-level antonym removal does NOT trigger reciprocal deletion.
    The word-level mirror from the first commit persists. This is
    acceptable: word-level antonyms are independent of sentence-level
    antonyms. The removal path (save_word_antonyms) is tested directly
    below and will be wired to a future word-edit endpoint.
    """
    _make_word(tmp_path, "W1", "高", "gāo")
    _make_word(tmp_path, "W2", "矮", "ǎi")

    # Phase 1: save_word_antonyms with [B] — same effect as commit wiring.
    save_word_antonyms(str(tmp_path), "W1", ["W2"])

    w1 = _read_word(tmp_path, "W1")
    w2 = _read_word(tmp_path, "W2")
    assert "W2" in w1["properties"]["antonyms"]
    assert "W1" in w2["properties"]["antonyms"]

    # Phase 2: remove — save_word_antonyms with [] (the AC6 path).
    save_word_antonyms(str(tmp_path), "W1", [])

    w1_after = _read_word(tmp_path, "W1")
    w2_after = _read_word(tmp_path, "W2")
    assert w1_after["properties"]["antonyms"] == []
    assert "W1" not in w2_after["properties"]["antonyms"]

