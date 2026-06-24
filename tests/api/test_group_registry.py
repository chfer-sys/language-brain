"""Tests for :mod:`api.services.group_registry` (SPEC §6 AC4).

Each test uses pytest's ``tmp_path`` fixture for full filesystem
isolation — we never read or set ``LANGUAGE_BRAIN_VAULT`` here; the
tmp path is passed straight through as ``vault_root``.

These tests cover AC4 ("Saving a sentence to a proposed group adds the
sentence's id to that group's ``members`` array") and the related
``ensure_group_unit`` helper that AC5 ("A proposed group name that does
not exist creates a new group unit file with that name as id") will
build on. Group shape follows SPEC §2.3 and locked OQ5: ``id`` is the
slug, ``name`` is the slug, ``properties.display_name`` is the human
form, ``properties.members`` is a ``list[str]`` of unit ids.

This module deliberately only tests the AC4 helpers (ensure/add).
Group-to-group ``connections`` edges are owned by a separate task.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services.group_registry import (
    add_member_to_group,
    ensure_group_unit,
)
from api.services.unit_writer import read_unit, write_unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _groups_dir(vault_root: str | Path) -> Path:
    return Path(vault_root) / "units" / "groups"


# ---------------------------------------------------------------------------
# ensure_group_unit: file layout and shape
# ---------------------------------------------------------------------------


def test_ensure_group_creates_when_absent(tmp_path: Path) -> None:
    """A fresh slug produces a file at
    ``<vault>/units/groups/basic-verbs.json`` with the SPEC §2.3 shape:
    id and name are the slug, type is "group", properties.members is
    an empty list, and display_name is present (defaults to "")."""
    vault = str(tmp_path)
    result = ensure_group_unit(vault, group_id="basic-verbs")

    group_path = _groups_dir(vault) / "basic-verbs.json"
    assert group_path.is_file(), f"expected group file at {group_path}"

    assert result["id"] == "basic-verbs"
    assert result["name"] == "basic-verbs"
    assert result["type"] == "group"
    # display_name is present even when defaulted.
    assert "display_name" in result["properties"]
    assert result["properties"]["display_name"] == ""
    assert result["properties"]["members"] == []
    # description defaults to empty string.
    assert result["properties"]["description"] == ""


def test_ensure_group_idempotent(tmp_path: Path) -> None:
    """Calling ``ensure_group_unit`` twice with the same id is a no-op
    on the second call. The file is not re-written; the existing dict
    is returned."""
    vault = str(tmp_path)
    first = ensure_group_unit(vault, group_id="basic-verbs")
    group_path = _groups_dir(vault) / "basic-verbs.json"
    mtime_after_first = group_path.stat().st_mtime_ns
    content_after_first = group_path.read_bytes()

    second = ensure_group_unit(vault, group_id="basic-verbs")

    # File is byte-equal (not re-written).
    assert group_path.read_bytes() == content_after_first
    # mtime is unchanged (or, on coarse-resolution filesystems, equal).
    assert group_path.stat().st_mtime_ns == mtime_after_first
    # Returned dicts are equal.
    assert first == second


def test_ensure_group_with_display_name_and_description(tmp_path: Path) -> None:
    """Passing ``display_name`` and ``description`` stores them verbatim
    on the new group unit."""
    vault = str(tmp_path)
    result = ensure_group_unit(
        vault,
        group_id="basic-verbs",
        display_name="Basic Verbs",
        description="Common everyday actions",
    )

    assert result["id"] == "basic-verbs"
    assert result["name"] == "basic-verbs"
    assert result["type"] == "group"
    assert result["properties"]["display_name"] == "Basic Verbs"
    assert result["properties"]["description"] == "Common everyday actions"
    assert result["properties"]["members"] == []


def test_ensure_group_display_name_defaults_to_empty(tmp_path: Path) -> None:
    """When ``display_name`` is not passed, ``properties.display_name``
    is the empty string ``""`` (per the behavior contract), NOT the
    slug. The slug already lives in ``id``/``name``; the display_name
    field is for the human-readable form and must be set by the caller
    when they have one."""
    vault = str(tmp_path)
    result = ensure_group_unit(vault, group_id="basic-verbs")

    assert result["properties"]["display_name"] == ""
    # Confirm we did NOT silently fall back to the slug here.
    assert result["properties"]["display_name"] != "basic-verbs"


def test_ensure_group_with_initial_members(tmp_path: Path) -> None:
    """Passing ``members=["chi", "he"]`` seeds the group's
    ``properties.members`` with that exact list (order preserved)."""
    vault = str(tmp_path)
    result = ensure_group_unit(
        vault,
        group_id="basic-verbs",
        members=["chi", "he"],
    )

    assert result["properties"]["members"] == ["chi", "he"]


# ---------------------------------------------------------------------------
# ensure_group_unit: structural invariants from SPEC §2.3
# ---------------------------------------------------------------------------


def test_ensure_group_fresh_has_required_fields(tmp_path: Path) -> None:
    """A freshly-created group has every field required by SPEC §2.3:
    id, type, name, properties.{display_name,description,members},
    connections (empty per the AC4 contract), created, updated,
    author_confirmed=True."""
    vault = str(tmp_path)
    result = ensure_group_unit(vault, group_id="basic-verbs")

    assert result["id"] == "basic-verbs"
    assert result["type"] == "group"
    assert result["name"] == "basic-verbs"
    # All three property keys are present.
    assert set(result["properties"].keys()) >= {
        "display_name",
        "description",
        "members",
    }
    # connections is empty per the AC4 contract — group connections are
    # added by a separate task.
    assert result["connections"] == []
    assert result["author_confirmed"] is True
    # created/updated are present and ISO-date-shaped (YYYY-MM-DD).
    assert isinstance(result["created"], str) and len(result["created"]) == 10
    assert isinstance(result["updated"], str) and len(result["updated"]) == 10


def test_ensure_group_persisted_file_is_valid_json(tmp_path: Path) -> None:
    """The on-disk file is valid JSON and matches the returned dict."""
    vault = str(tmp_path)
    ensure_group_unit(
        vault,
        group_id="basic-verbs",
        display_name="Basic Verbs",
        description="Common everyday actions",
        members=["chi", "he"],
    )

    raw = (_groups_dir(vault) / "basic-verbs.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["id"] == "basic-verbs"
    assert parsed["type"] == "group"
    assert parsed["name"] == "basic-verbs"
    assert parsed["properties"]["display_name"] == "Basic Verbs"
    assert parsed["properties"]["description"] == "Common everyday actions"
    assert parsed["properties"]["members"] == ["chi", "he"]
    assert parsed["connections"] == []


# ---------------------------------------------------------------------------
# add_member_to_group
# ---------------------------------------------------------------------------


def test_add_member_appends(tmp_path: Path) -> None:
    """Adding a member to an existing group grows ``properties.members``
    by exactly one."""
    vault = str(tmp_path)
    ensure_group_unit(vault, group_id="basic-verbs")

    updated = add_member_to_group(vault, group_id="basic-verbs", member_id="chi")

    assert updated["properties"]["members"] == ["chi"]
    # And the file on disk reflects the change.
    on_disk = read_unit(vault, "group", "basic-verbs")
    assert on_disk["properties"]["members"] == ["chi"]


def test_add_member_idempotent(tmp_path: Path) -> None:
    """Adding the same member twice yields exactly one entry."""
    vault = str(tmp_path)
    ensure_group_unit(vault, group_id="basic-verbs")

    add_member_to_group(vault, group_id="basic-verbs", member_id="chi")
    updated = add_member_to_group(vault, group_id="basic-verbs", member_id="chi")

    assert updated["properties"]["members"] == ["chi"]


def test_add_member_preserves_order(tmp_path: Path) -> None:
    """Adding members in the order ``["c", "a", "b"]`` yields exactly
    that order in the stored list."""
    vault = str(tmp_path)
    ensure_group_unit(vault, group_id="basic-verbs")

    add_member_to_group(vault, group_id="basic-verbs", member_id="c")
    add_member_to_group(vault, group_id="basic-verbs", member_id="a")
    add_member_to_group(vault, group_id="basic-verbs", member_id="b")

    updated = add_member_to_group(vault, group_id="basic-verbs", member_id="b")
    # b was already there, so the list is unchanged at the end.
    assert updated["properties"]["members"] == ["c", "a", "b"]


def test_add_member_to_nonexistent_group_raises(tmp_path: Path) -> None:
    """If the group unit file does not exist, ``FileNotFoundError`` is
    raised — the caller is expected to have created the group first
    (typically via ``ensure_group_unit``)."""
    vault = str(tmp_path)
    with pytest.raises(FileNotFoundError):
        add_member_to_group(vault, group_id="does-not-exist", member_id="chi")


def test_add_member_does_not_touch_connections(tmp_path: Path) -> None:
    """Group-membership is a property of the group, NOT a connection
    kind. ``add_member_to_group`` must not modify the ``connections``
    list of the group unit (group-to-group edges are owned by a
    separate task)."""
    vault = str(tmp_path)
    ensure_group_unit(vault, group_id="basic-verbs")

    # Seed a connection on the group via the unit_writer (mimicking the
    # separate group-connection task). The add_member call must not
    # disturb this.
    group = read_unit(vault, "group", "basic-verbs")
    seeded_connection = {"to": "food", "kind": "group", "score": 0.6}
    group["connections"] = [seeded_connection]
    write_unit(vault, group)

    updated = add_member_to_group(vault, group_id="basic-verbs", member_id="chi")

    # The member was added.
    assert updated["properties"]["members"] == ["chi"]
    # The seeded connection is unchanged (same dict, same position).
    assert updated["connections"] == [seeded_connection]


def test_add_member_works_with_word_ids(tmp_path: Path) -> None:
    """A member id that is shaped like a word id (``"chī"``,
    tone-marked pinyin) is accepted verbatim. The function does not
    validate that the id refers to a real word unit — that's the
    caller's responsibility."""
    vault = str(tmp_path)
    ensure_group_unit(vault, group_id="basic-verbs")

    updated = add_member_to_group(vault, group_id="basic-verbs", member_id="chī")

    assert updated["properties"]["members"] == ["chī"]


def test_add_member_works_with_sentence_ids(tmp_path: Path) -> None:
    """A member id that is shaped like a sentence id (``"2026-06-24-001"``)
    is accepted verbatim, with no validation against the actual vault
    state. The caller is responsible for handing in ids that resolve."""
    vault = str(tmp_path)
    ensure_group_unit(vault, group_id="basic-verbs")

    updated = add_member_to_group(
        vault, group_id="basic-verbs", member_id="2026-06-24-001"
    )

    assert updated["properties"]["members"] == ["2026-06-24-001"]


def test_add_member_multiple_distinct_words(tmp_path: Path) -> None:
    """Adding several distinct members accumulates them in the list."""
    vault = str(tmp_path)
    ensure_group_unit(vault, group_id="basic-verbs", members=["chi"])

    add_member_to_group(vault, group_id="basic-verbs", member_id="he")
    add_member_to_group(vault, group_id="basic-verbs", member_id="shui")
    final = add_member_to_group(
        vault, group_id="basic-verbs", member_id="2026-06-24-001"
    )

    assert final["properties"]["members"] == [
        "chi",
        "he",
        "shui",
        "2026-06-24-001",
    ]


def test_group_file_persistence(tmp_path: Path) -> None:
    """After ``add_member_to_group``, the member is persisted to disk:
    a direct re-read of the JSON file sees the new member."""
    vault = str(tmp_path)
    ensure_group_unit(vault, group_id="basic-verbs")

    add_member_to_group(vault, group_id="basic-verbs", member_id="chi")

    # Bypass the registry helpers; read the file directly.
    on_disk_path = _groups_dir(vault) / "basic-verbs.json"
    assert on_disk_path.is_file(), f"expected group file at {on_disk_path}"
    with open(on_disk_path, encoding="utf-8") as fh:
        raw = json.load(fh)

    assert raw["type"] == "group"
    assert raw["id"] == "basic-verbs"
    assert raw["properties"]["members"] == ["chi"]


def test_add_member_updates_timestamp(tmp_path: Path) -> None:
    """``add_member_to_group`` refreshes the ``updated`` field to
    today's ISO date so the on-disk timestamp reflects the mutation."""
    vault = str(tmp_path)
    ensure_group_unit(vault, group_id="basic-verbs")

    updated = add_member_to_group(vault, group_id="basic-verbs", member_id="chi")

    import re

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", updated["updated"])


def test_add_member_rejects_empty_ids(tmp_path: Path) -> None:
    """Empty / non-string ids are rejected before any disk I/O."""
    vault = str(tmp_path)
    ensure_group_unit(vault, group_id="basic-verbs")

    with pytest.raises(ValueError):
        add_member_to_group(vault, group_id="basic-verbs", member_id="")
    with pytest.raises(ValueError):
        add_member_to_group(vault, group_id="", member_id="chi")


def test_add_member_rejects_empty_group_id(tmp_path: Path) -> None:
    """An empty ``group_id`` is rejected even when the group doesn't
    exist — no disk I/O is attempted."""
    vault = str(tmp_path)
    with pytest.raises(ValueError):
        add_member_to_group(vault, group_id="", member_id="chi")


def test_ensure_group_rejects_empty_id(tmp_path: Path) -> None:
    """``ensure_group_unit`` rejects an empty ``group_id``."""
    vault = str(tmp_path)
    with pytest.raises(ValueError):
        ensure_group_unit(vault, group_id="")