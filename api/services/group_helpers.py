"""Group helpers: batch wrappers around ``ensure_group_unit``.

This module implements SPEC §6 AC5 ("a proposed group name that does
not exist creates a new group unit file with that name as id") at the
service layer. The actual disk I/O and unit shape are owned by
:mod:`api.services.group_registry` — this module is a thin batch
wrapper that turns a list of ids (or a list of proposed-name dicts)
into the list of group unit dicts the caller needs to chain into the
rest of the sentence-save pipeline (members, connections, etc.).

Why a wrapper?
--------------
``ensure_group_unit`` is the right building block, but the
sentence-commit endpoint receives a *list* of proposed group names
from the AI client. Calling it in a Python ``for`` loop at every
callsite duplicates logic (dedupe, empty-input handling, dict
unpacking) and is easy to get wrong. These helpers centralize that
contract so the route handler stays short.

Contract
--------
* ``ensure_groups`` accepts a list of slug strings.
* ``ensure_groups_from_proposed`` accepts the richer AI-client
  output: a list that may be a mix of bare slugs (strings) and dicts
  with optional ``display_name`` and ``description`` fields.
* Both helpers:
    - Return ``[]`` for ``None`` or empty input.
    - Dedupe the input (preserving first-occurrence order).
    - Are idempotent: re-ensuring an existing group returns the
      existing unit dict and does NOT re-write its file.
    - Return the group unit dicts in the same order as the deduped
      input (which is the same as the original input minus dupes).
"""
from __future__ import annotations

from typing import Any

from api.services.group_registry import ensure_group_unit


def _dedupe_preserving_order(items: list[str]) -> list[str]:
    """Return ``items`` with duplicates removed, keeping the position
    of each first occurrence. Used to make ``ensure_groups`` safe
    against callers that hand in the same id twice."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        # We only dedupe strings here; the proposed-input helper does
        # its own normalization before calling us.
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def ensure_groups(
    vault_root: str,
    group_ids: list[str],
) -> list[dict]:
    """For each id in ``group_ids``, ensure a group unit exists.

    Idempotent. Returns the list of group unit dicts in the same
    order as the (deduped) input. Uses
    :func:`api.services.group_registry.ensure_group_unit` underneath
    — this is just a batch wrapper that takes a list and returns a
    list.

    An empty input list returns an empty list. Duplicates in the
    input are deduped (preserving first-occurrence order) so a
    caller that lists the same group twice doesn't create a
    double-entry.

    Parameters
    ----------
    vault_root:
        Filesystem path to the vault root.
    group_ids:
        List of group slugs (e.g. ``["food", "travel"]``). Each id
        must be a non-empty string; :func:`ensure_group_unit` raises
        :class:`ValueError` otherwise.

    Returns
    -------
    list[dict]
        One group unit dict per deduped input id, in input order.
    """
    if not group_ids:
        return []
    deduped = _dedupe_preserving_order(group_ids)
    return [
        ensure_group_unit(vault_root, group_id=gid)
        for gid in deduped
    ]


def _coerce_proposed(item: str | dict[str, Any]) -> tuple[str, str, str]:
    """Normalize a single proposed-group entry into ``(id, display_name,
    description)``.

    A bare string is treated as the id with default ``display_name``
    and ``description`` (both empty). A dict must carry ``id``; the
    other fields are optional and default to empty strings so the
    resulting group unit has the SPEC §2.3 shape on disk.

    Raises :class:`ValueError` for any other input shape — we fail
    loudly at the boundary rather than silently dropping a
    malformed AI proposal.
    """
    if isinstance(item, str):
        if not item:
            raise ValueError("proposed group id must be a non-empty string")
        return item, "", ""

    if isinstance(item, dict):
        gid = item.get("id")
        if not isinstance(gid, str) or not gid:
            raise ValueError(
                "proposed group dict must have a non-empty string 'id'"
            )
        display_name = item.get("display_name", "")
        if not isinstance(display_name, str):
            raise ValueError(
                "proposed group 'display_name' must be a string when provided"
            )
        description = item.get("description", "")
        if not isinstance(description, str):
            raise ValueError(
                "proposed group 'description' must be a string when provided"
            )
        return gid, display_name, description

    raise ValueError(
        f"proposed group entry must be a str or dict, got {type(item).__name__}"
    )


def ensure_groups_from_proposed(
    vault_root: str,
    proposed: list[str] | list[dict] | None,
) -> list[dict]:
    """Higher-level helper: accept either bare slug strings, or dicts
    like ``{'id': 'food', 'display_name': 'Food', 'description': '...'}``,
    and ensure each as a group. Returns the list of group unit dicts
    in input order. ``None`` or empty input returns ``[]``.

    The two element shapes can be mixed in the same list (e.g.
    ``["food", {"id": "travel", "display_name": "Travel"}]``). Each
    entry is normalized via :func:`_coerce_proposed` before being
    handed to :func:`ensure_group_unit`.

    Duplicates (by id) are deduped preserving first-occurrence order,
    matching the contract of :func:`ensure_groups`.

    Parameters
    ----------
    vault_root:
        Filesystem path to the vault root.
    proposed:
        List of proposed group entries, or ``None``.

    Returns
    -------
    list[dict]
        One group unit dict per deduped id, in input order. Empty
        list for ``None`` or empty input.
    """
    if proposed is None or len(proposed) == 0:
        return []

    # Normalize first so dedupe sees stable ids regardless of which
    # shape each entry arrived in.
    normalized: list[tuple[str, str, str]] = [
        _coerce_proposed(item) for item in proposed
    ]

    seen: set[str] = set()
    out: list[dict] = []
    for gid, display_name, description in normalized:
        if gid in seen:
            continue
        seen.add(gid)
        out.append(
            ensure_group_unit(
                vault_root,
                group_id=gid,
                display_name=display_name,
                description=description,
            )
        )
    return out


__all__ = [
    "ensure_groups",
    "ensure_groups_from_proposed",
]
