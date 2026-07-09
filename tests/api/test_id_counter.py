"""Tests for api.services.id_counter (SPEC v0.5.2).

Each test uses pytest's ``tmp_path`` fixture for full filesystem
isolation — we never touch the live vault.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.id_counter import next_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _counter_file(vault_root: str) -> Path:
    return Path(vault_root) / "_meta" / "id_counters.json"


def _seeded_vault(tmp_path: Path, counters: dict[str, int]) -> Path:
    """Create _meta/id_counters.json with given counters."""
    meta = tmp_path / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    _counter_file(str(tmp_path)).write_text(json.dumps(counters), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_next_id_returns_incremented_id(tmp_path):
    """next_id must return the next sequential id for the given unit type."""
    vault = _seeded_vault(tmp_path, {"W": 5, "C": 2, "S": 3, "G": 1})
    assert next_id(str(vault), "word") == "W6"
    assert next_id(str(vault), "compound") == "C3"
    assert next_id(str(vault), "sentence") == "S4"
    assert next_id(str(vault), "group") == "G2"


def test_next_id_persists_after_call(tmp_path):
    """next_id must write the updated counter file so subsequent calls are monotonic."""
    vault = _seeded_vault(tmp_path, {"W": 0, "C": 0, "S": 0, "G": 0})

    # First call: W1
    id1 = next_id(str(vault), "word")
    assert id1 == "W1"

    # Counter file must reflect W:1 now.
    counters = json.loads(_counter_file(str(vault)).read_text(encoding="utf-8"))
    assert counters["W"] == 1

    # Second call: W2
    id2 = next_id(str(vault), "word")
    assert id2 == "W2"

    # Third call: W3
    id3 = next_id(str(vault), "word")
    assert id3 == "W3"

    # Final state
    counters = json.loads(_counter_file(str(vault)).read_text(encoding="utf-8"))
    assert counters["W"] == 3


def test_next_id_unknown_type_raises(tmp_path):
    """next_id must reject unknown unit types with ValueError."""
    vault = _seeded_vault(tmp_path, {"W": 1})
    with pytest.raises(ValueError, match="unknown unit_type"):
        next_id(str(vault), "not_a_type")


def test_next_id_mixed_types_are_independent(tmp_path):
    """Each unit type has an independent counter."""
    vault = _seeded_vault(tmp_path, {"W": 1, "C": 1, "S": 1, "G": 1})
    assert next_id(str(vault), "word") == "W2"
    assert next_id(str(vault), "compound") == "C2"
    assert next_id(str(vault), "sentence") == "S2"
    assert next_id(str(vault), "group") == "G2"
    assert next_id(str(vault), "word") == "W3"
