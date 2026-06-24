"""Tests for :mod:`api.services.group_helpers` (SPEC §6 AC5).

These tests cover the batch wrappers around
``ensure_group_unit`` that the sentence-commit endpoint will use to
turn the AI client's proposed group list into actual group unit files.

The unit under test (``api.services.group_helpers``) does no disk I/O
of its own — it delegates to ``ensure_group_unit``. All tests use
pytest's ``tmp_path`` fixture for full filesystem isolation and never
read or set ``LANGUAGE_BRAIN_VAULT``.

Contract under test (per SPEC §6 AC5):
    "A proposed group name that does not exist creates a new group
    unit file with that name as id."

The helpers add:
    - Batch handling: take a list, return a list, in input order.
    - Empty / None handling: returns ``[]`` without raising.
    - Dedupe: a caller that lists the same group twice does not
      create a double-entry.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.group_helpers import (
    ensure_groups,
    ensure_groups_from_proposed,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _groups_dir(vault_root: str | Path) -> Path:
    return Path(vault_root) / "units" / "groups"


def _read_group_file(vault_root: str | Path, group_id: str) -> dict:
    """Read a group unit file directly off disk (bypassing the
    registry) for persistence assertions."""
    path = _groups_dir(vault_root) / f"{group_id}.json"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# ensure_groups: edge cases and shape
# ---------------------------------------------------------------------------


def test_ensure_groups_empty_input_returns_empty(tmp_path: Path) -> None:
    """An empty list yields an empty list — no disk I/O, no error."""
    vault = str(tmp_path)
    assert ensure_groups(vault, []) == []
    # And no group directory was created.
    assert not _groups_dir(vault).exists()


def test_ensure_groups_creates_each_unknown(tmp_path: Path) -> None:
    """Passing ``["a", "b", "c"]`` produces three group files with the
    right ids and the SPEC §2.3 shape."""
    vault = str(tmp_path)
    result = ensure_groups(vault, ["a", "b", "c"])

    assert [g["id"] for g in result] == ["a", "b", "c"]
    for gid in ("a", "b", "c"):
        path = _groups_dir(vault) / f"{gid}.json"
        assert path.is_file(), f"expected group file at {path}"
        on_disk = _read_group_file(vault, gid)
        assert on_disk["id"] == gid
        assert on_disk["type"] == "group"
        assert on_disk["name"] == gid
        # Display name defaults to empty string (per behavior contract).
        assert on_disk["properties"]["display_name"] == ""
        assert on_disk["properties"]["description"] == ""
        assert on_disk["properties"]["members"] == []


def test_ensure_groups_idempotent(tmp_path: Path) -> None:
    """Calling ``ensure_groups`` twice with the same ids returns the
    same dicts on the second call AND does not re-write the files."""
    vault = str(tmp_path)
    first = ensure_groups(vault, ["x", "y", "z"])

    # Capture mtime + bytes of every file before the second call.
    snapshots: dict[str, tuple[int, bytes]] = {}
    for gid in ("x", "y", "z"):
        p = _groups_dir(vault) / f"{gid}.json"
        snapshots[gid] = (p.stat().st_mtime_ns, p.read_bytes())

    second = ensure_groups(vault, ["x", "y", "z"])

    # Same dicts returned.
    assert first == second
    # Files were not rewritten.
    for gid, (mtime, content) in snapshots.items():
        p = _groups_dir(vault) / f"{gid}.json"
        assert p.read_bytes() == content
        assert p.stat().st_mtime_ns == mtime


def test_ensure_groups_dedupes_input(tmp_path: Path) -> None:
    """Duplicates in the input are deduped, preserving first-occurrence
    order. A caller that lists ``"a"`` twice gets one group, not two."""
    vault = str(tmp_path)
    result = ensure_groups(vault, ["a", "b", "a", "c", "b"])

    assert [g["id"] for g in result] == ["a", "b", "c"]
    # And exactly three files on disk.
    on_disk_ids = sorted(
        p.stem for p in _groups_dir(vault).glob("*.json")
    )
    assert on_disk_ids == ["a", "b", "c"]


def test_ensure_groups_preserves_input_order(tmp_path: Path) -> None:
    """The output order matches the (deduped) input order, regardless
    of alphabetical order."""
    vault = str(tmp_path)
    result = ensure_groups(vault, ["c", "a", "b"])

    assert [g["id"] for g in result] == ["c", "a", "b"]
    # Confirm against on-disk mtime ordering too — first-written
    # should be "c".
    mt = {
        p.stem: p.stat().st_mtime_ns
        for p in _groups_dir(vault).glob("*.json")
    }
    assert mt["c"] <= mt["a"] <= mt["b"]


# ---------------------------------------------------------------------------
# ensure_groups: disk persistence
# ---------------------------------------------------------------------------


def test_ensure_groups_via_helper_persists_to_disk(tmp_path: Path) -> None:
    """A group ensured via the helper is actually on disk at the
    canonical path ``<vault>/units/groups/<id>.json``. We read the
    file directly (bypassing the registry) to confirm."""
    vault = str(tmp_path)
    result = ensure_groups(vault, ["basic-verbs"])
    assert len(result) == 1

    expected_path = _groups_dir(vault) / "basic-verbs.json"
    assert expected_path.is_file(), f"expected group file at {expected_path}"

    on_disk = _read_group_file(vault, "basic-verbs")
    # Returned dict matches the file contents.
    assert result[0] == on_disk
    # And the file has the SPEC §2.3 shape.
    assert on_disk["id"] == "basic-verbs"
    assert on_disk["type"] == "group"
    assert on_disk["name"] == "basic-verbs"
    assert on_disk["properties"]["members"] == []


# ---------------------------------------------------------------------------
# ensure_groups_from_proposed: shape handling
# ---------------------------------------------------------------------------


def test_ensure_groups_from_proposed_bare_slugs(tmp_path: Path) -> None:
    """Bare string slugs default display_name and description to empty
    strings (per SPEC §2.3 / behavior contract)."""
    vault = str(tmp_path)
    result = ensure_groups_from_proposed(vault, ["food", "travel"])

    assert [g["id"] for g in result] == ["food", "travel"]
    for gid in ("food", "travel"):
        on_disk = _read_group_file(vault, gid)
        assert on_disk["properties"]["display_name"] == ""
        assert on_disk["properties"]["description"] == ""


def test_ensure_groups_from_proposed_with_display_name(tmp_path: Path) -> None:
    """A dict entry's ``display_name`` and ``description`` are stored
    verbatim on the resulting group unit."""
    vault = str(tmp_path)
    result = ensure_groups_from_proposed(
        vault,
        [
            {
                "id": "food",
                "display_name": "Food",
                "description": "things you eat",
            }
        ],
    )

    assert len(result) == 1
    assert result[0]["id"] == "food"
    assert result[0]["properties"]["display_name"] == "Food"
    assert result[0]["properties"]["description"] == "things you eat"

    # And the file on disk reflects the same values.
    on_disk = _read_group_file(vault, "food")
    assert on_disk["properties"]["display_name"] == "Food"
    assert on_disk["properties"]["description"] == "things you eat"


def test_ensure_groups_from_proposed_none_returns_empty(tmp_path: Path) -> None:
    """``None`` input returns ``[]`` without raising and without
    touching the filesystem."""
    vault = str(tmp_path)
    assert ensure_groups_from_proposed(vault, None) == []
    assert not _groups_dir(vault).exists()


def test_ensure_groups_from_proposed_mixed(tmp_path: Path) -> None:
    """A list mixing bare slugs and dicts is handled — bare slugs get
    default fields, dicts use their explicit values."""
    vault = str(tmp_path)
    result = ensure_groups_from_proposed(
        vault,
        [
            "food",
            {"id": "travel", "display_name": "Travel"},
        ],
    )

    assert [g["id"] for g in result] == ["food", "travel"]
    by_id = {g["id"]: g for g in result}
    # "food" came in as a bare slug — defaults.
    assert by_id["food"]["properties"]["display_name"] == ""
    assert by_id["food"]["properties"]["description"] == ""
    # "travel" came in as a dict — display_name applied, description
    # defaulted.
    assert by_id["travel"]["properties"]["display_name"] == "Travel"
    assert by_id["travel"]["properties"]["description"] == ""

    # Confirm both files exist on disk.
    assert (_groups_dir(vault) / "food.json").is_file()
    assert (_groups_dir(vault) / "travel.json").is_file()


def test_ensure_groups_from_proposed_dedupes(tmp_path: Path) -> None:
    """Duplicate ids in the proposed list (whether bare slugs or
    dicts) collapse to a single group unit, in first-occurrence
    position."""
    vault = str(tmp_path)
    result = ensure_groups_from_proposed(vault, ["food", "food"])

    assert len(result) == 1
    assert result[0]["id"] == "food"
    # Only one file on disk.
    on_disk_ids = sorted(
        p.stem for p in _groups_dir(vault).glob("*.json")
    )
    assert on_disk_ids == ["food"]


def test_ensure_groups_from_proposed_empty_list_returns_empty(
    tmp_path: Path,
) -> None:
    """An explicit empty list returns ``[]`` (mirrors the ``None``
    case for symmetry)."""
    vault = str(tmp_path)
    assert ensure_groups_from_proposed(vault, []) == []
    assert not _groups_dir(vault).exists()
