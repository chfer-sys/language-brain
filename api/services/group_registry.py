"""Group registry: create and mutate group units on the local vault.

This module implements the AC4 ("sentence added to group's members on
save") helpers for group units. A separate task owns the AC5 ("a
proposed group name that does not exist creates a new group unit
file with that name as id") flow that wraps ``ensure_group_unit`` —
the helper exposed here is the building block, not the caller-facing
commit endpoint.

Shape (from SPEC §2.3 and locked OQ5)
------------------------------------
* ``id`` is the slug (e.g. ``"basic-verbs"``).
* ``name`` is the same slug — id and name are identical strings.
* ``type`` is ``"group"``.
* ``properties`` is ``{display_name, description, members}``:
    - ``display_name`` defaults to ``""`` (the empty string). It is
      the human form (e.g. ``"Basic Verbs"``). Per the behavior
      contract, when not provided we store the empty string rather
      than falling back to the slug — the slug already lives in
      ``id``/``name``.
    - ``description`` defaults to ``""``.
    - ``members`` is a ``list[str]`` of unit ids (sentence or word).
      Group-to-group membership is NOT supported in MVP. Per SPEC
      §2.3, the members array stores unit ids, not group ids.
* ``connections`` is ``[]`` on creation. Group-to-group edges
  (``{"to": <other-group-id>, "kind": "group", ...}``) are owned by a
  separate task and are not touched by this module.

Side effects
------------
All disk I/O goes through :mod:`api.services.unit_writer`, so the
atomic-write guarantee of ``write_unit`` is preserved. ``add_member_to_group``
only mutates the group's own file — it never touches the member
unit's file, and it never adds a ``group`` connection kind anywhere.
Connection edges from member units to the group unit are a separate
task (per the deliverable contract).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from api.services.unit_writer import read_unit, unit_path, write_unit


def _today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return date.today().isoformat()


def ensure_group_unit(
    vault_root: str,
    group_id: str,
    display_name: str = "",
    description: str = "",
    members: list[str] | None = None,
) -> dict:
    """If a group unit with this id does not exist, create one.
    If it does exist, return it unchanged. AC5 is a separate task
    that handles the case where the caller passes a member list —
    AC4 is just about ADDING a member to an existing group.

    The group's id is a slug (e.g. 'basic-verbs'). The group's
    'name' is the slug; 'properties.display_name' is the human form
    (e.g. 'Basic Verbs'). Per SPEC §2.3 and locked OQ5.

    The members array stores unit ids (sentence or word), NOT group ids.
    Group-to-group membership is not supported in MVP.

    Side effect: writes a new group unit file at
    <vault_root>/units/groups/<id>.json if it doesn't already exist.
    """
    if not isinstance(group_id, str) or not group_id:
        raise ValueError("group_id must be a non-empty string")
    if not isinstance(display_name, str):
        raise ValueError("display_name must be a string")
    if not isinstance(description, str):
        raise ValueError("description must be a string")
    if members is not None and not isinstance(members, list):
        raise ValueError("members must be a list when provided")
    if members is not None:
        for idx, m in enumerate(members):
            if not isinstance(m, str):
                raise ValueError(
                    f"members[{idx}] must be a string, got {type(m).__name__}"
                )

    path = unit_path(vault_root, "group", group_id)
    if path.exists():
        # Idempotent re-save: read the existing unit and return it.
        # We deliberately do NOT re-write, so callers can rely on
        # "ensure" being a true no-op on collision. AC5's
        # "create-if-absent" flow uses this as its create half; a
        # separate task may add an "update if different" variant.
        existing = read_unit(vault_root, "group", group_id)
        # Defensive: read_unit would have raised if the file was
        # malformed, so we know we have a dict here.
        return existing

    today = _today_iso()
    group_unit: dict[str, Any] = {
        "id": group_id,
        "type": "group",
        "name": group_id,
        "properties": {
            "display_name": display_name,
            "description": description,
            "members": list(members) if members is not None else [],
        },
        "connections": [],
        "created": today,
        "updated": today,
        "author_confirmed": True,
    }
    write_unit(vault_root, group_unit)
    return group_unit


def add_member_to_group(
    vault_root: str,
    group_id: str,
    member_id: str,
) -> dict:
    """Add ``member_id`` to the group's ``properties.members`` list.
    Idempotent — re-adding is a no-op. If the group does not exist,
    raises FileNotFoundError; the caller is expected to ensure the
    group exists first (typically via ensure_group_unit).

    The unit is read, the member list updated, and the file rewritten
    via write_unit. Connections of any kind are NOT touched by this
    function — group-membership is a property of the group, not a
    connection kind. (A separate task adds 'group' connection edges
    from member units to the group unit.)
    """
    if not isinstance(group_id, str) or not group_id:
        raise ValueError("group_id must be a non-empty string")
    if not isinstance(member_id, str) or not member_id:
        raise ValueError("member_id must be a non-empty string")

    group_unit: dict[str, Any] = read_unit(vault_root, "group", group_id)

    # Defensive: confirm we just read a group unit. If a sentence or
    # word file got mis-routed to this id, fail loudly rather than
    # silently editing the wrong file.
    if group_unit.get("type") != "group":
        raise ValueError(
            f"unit at id {group_id!r} has type "
            f"{group_unit.get('type')!r}, expected 'group'"
        )

    properties = group_unit.get("properties")
    if not isinstance(properties, dict):
        # Malformed file: properties is not a dict. Repair it by
        # replacing with an empty dict so the rest of the function
        # can still update the members field. (A repair tool can flag
        # this separately.)
        properties = {}
        group_unit["properties"] = properties

    members = properties.get("members")
    if not isinstance(members, list):
        # Malformed: members is not a list. Repair it the same way.
        members = []
        properties["members"] = members

    # Idempotent append: only add if not already present. We do NOT
    # reorder; first-occurrence position wins, so re-adding is a
    # no-op and order is preserved across re-runs.
    if member_id not in members:
        members.append(member_id)

    # Refresh the timestamp so the on-disk mtime reflects the
    # mutation. ``created`` is left alone — creation is a one-shot
    # event owned by ``ensure_group_unit``.
    group_unit["updated"] = _today_iso()

    # connections of any kind are NEVER touched here — group-membership
    # is a property of the group, not a connection kind. The
    # ``connections`` key on the group unit (if present from a
    # separate task) is left exactly as-is.
    write_unit(vault_root, group_unit)
    return group_unit


__all__ = [
    "ensure_group_unit",
    "add_member_to_group",
]