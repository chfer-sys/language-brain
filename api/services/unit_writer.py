"""Unit writer: read and write unit files to/from the local vault.

The vault is a plain directory of pretty-printed JSON files, one per
unit. There are four unit types: ``sentence``, ``word``, ``compound``,
and ``group``. Each unit's canonical on-disk path is::

    <vault_root>/units/<plural(unit_type)>/<id>.json

where ``plural("sentence") = "sentences"``, ``plural("word") = "words"``,
``plural("compound") = "words"`` (compounds share the words directory),
``plural("group") = "groups"``.

Writes are atomic: the unit is serialized to a ``.tmp`` sibling and then
moved into place with :func:`os.replace`, so a crash mid-write cannot
leave a half-written JSON file at the canonical path.

See SPEC §2 (unit model) and §6 AC1 (round-trip property).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Final

VALID_UNIT_TYPES: Final[frozenset[str]] = frozenset({"sentence", "word", "compound", "group"})

_PLURAL_BY_TYPE: Final[dict[str, str]] = {
    "sentence": "sentences",
    "word": "words",
    "compound": "words",
    "group": "groups",
}


def _validate_unit_type(unit_type: str) -> str:
    """Return ``unit_type`` unchanged or raise :class:`ValueError`."""
    if unit_type not in VALID_UNIT_TYPES:
        raise ValueError(
            f"invalid unit_type {unit_type!r}; "
            f"must be one of {sorted(VALID_UNIT_TYPES)}"
        )
    return unit_type


def unit_path(vault_root: str, unit_type: str, unit_id: str) -> Path:
    """Return the canonical on-disk :class:`Path` for a unit file.

    Parameters
    ----------
    vault_root:
        Filesystem path to the vault root (the directory that contains
        ``units/``). May be relative or absolute.
    unit_type:
        One of ``"sentence"``, ``"word"``, ``"compound"``, ``"group"``. Any other value
        raises :class:`ValueError`.
    unit_id:
        The unit's stable id (slug for groups, ISO-date for sentences,
        tone-marked pinyin for words per SPEC §2.2 / OQ2). The id is
        used verbatim as the filename stem; it is the caller's
        responsibility to pass a filesystem-safe id.

    Returns
    -------
    pathlib.Path
        The path is not guaranteed to exist; use :func:`read_unit` to
        fetch an existing unit, or :func:`write_unit` to create one.
    """
    _validate_unit_type(unit_type)
    if not isinstance(unit_id, str) or not unit_id:
        raise ValueError("unit_id must be a non-empty string")
    root = Path(vault_root)
    return root / "units" / _PLURAL_BY_TYPE[unit_type] / f"{unit_id}.json"


def _coerce_unit(unit: Any, expected_type: str | None = None) -> dict[str, Any]:
    """Validate that ``unit`` is a dict with an ``id`` and (optionally)
    a ``type`` field that matches ``expected_type``. Returns the dict
    unchanged so callers can rely on the original object reference."""
    if not isinstance(unit, dict):
        raise ValueError(f"unit must be a dict, got {type(unit).__name__}")
    unit_id = unit.get("id")
    if not isinstance(unit_id, str) or not unit_id:
        raise ValueError("unit['id'] is required and must be a non-empty string")
    if expected_type is not None:
        actual_type = unit.get("type")
        if actual_type is None:
            raise ValueError(
                f"unit['type'] is required when unit_type={expected_type!r} is passed"
            )
        if actual_type != expected_type:
            raise ValueError(
                f"unit['type']={actual_type!r} does not match "
                f"unit_type={expected_type!r}"
            )
    return unit


def write_unit(vault_root: str, unit: dict) -> Path:
    """Write ``unit`` to its canonical JSON file.

    The unit is written atomically via a ``.tmp`` sibling followed by
    :func:`os.replace`. The parent directory is created if it does not
    exist. The file is pretty-printed (``indent=2``) with
    ``ensure_ascii=False`` so hanzi and pinyin remain human-readable.

    Parameters
    ----------
    vault_root:
        Filesystem path to the vault root.
    unit:
        The unit dict. Must contain an ``id`` field. If it also
        contains a ``type`` field, that field is used to determine the
        destination subdirectory.

    Returns
    -------
    pathlib.Path
        The path the unit was written to.
    """
    unit_type = unit.get("type")
    if unit_type is None:
        raise ValueError("unit['type'] is required for write_unit")
    _validate_unit_type(unit_type)
    unit_id = unit.get("id")
    if not isinstance(unit_id, str) or not unit_id:
        raise ValueError("unit['id'] is required and must be a non-empty string")

    path = unit_path(vault_root, unit_type, unit_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(unit, indent=2, ensure_ascii=False)
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.write("\n")
    os.replace(tmp_path, path)
    return path


def read_unit(vault_root: str, unit_type: str, unit_id: str) -> dict:
    """Read a unit from disk and return it as a dict.

    Parameters
    ----------
    vault_root:
        Filesystem path to the vault root.
    unit_type:
        One of ``"sentence"``, ``"word"``, ``"compound"``, ``"group"``.
    unit_id:
        The unit's stable id.

    Raises
    ------
    FileNotFoundError
        If the unit file does not exist.
    ValueError
        If ``unit_type`` is not one of the valid types.
    """
    path = unit_path(vault_root, unit_type, unit_id)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(
            f"unit file at {path} did not deserialize to a dict "
            f"(got {type(data).__name__})"
        )
    return data


def round_trip(vault_root: str, unit: dict) -> dict:
    """Write ``unit`` then read it back, returning the read result.

    The ``updated`` timestamp is stripped from the input before writing
    and from the output after reading, so the round-trip is symmetric
    under SPEC §6 AC1's "ignoring updated timestamp" contract.
    """
    if not isinstance(unit, dict):
        raise ValueError(f"unit must be a dict, got {type(unit).__name__}")

    # Validate the basic shape so we fail fast on bad input.
    unit_type = unit.get("type")
    if unit_type is None:
        raise ValueError("unit['type'] is required for round_trip")
    _validate_unit_type(unit_type)
    unit_id = unit.get("id")
    if not isinstance(unit_id, str) or not unit_id:
        raise ValueError("unit['id'] is required and must be a non-empty string")

    # Strip "updated" from input so we don't overwrite a fresh timestamp
    # the caller may have set. write_unit may set its own; we strip
    # that on the way out.
    input_payload = {k: v for k, v in unit.items() if k != "updated"}
    write_unit(vault_root, input_payload)
    result = read_unit(vault_root, unit_type, unit_id)
    result.pop("updated", None)
    return result


# ---------------------------------------------------------------------------
# Listing helpers — used by reindex.py and the search route
# ---------------------------------------------------------------------------


def list_units_by_type(vault_root: str, unit_type: str) -> list[dict]:
    """Return all units of ``unit_type`` under the vault, as a list
    of dicts. Skips files that fail to deserialize (logged but not
    raised) so a single corrupt file doesn't kill the whole list.

    The result is sorted by unit id for determinism — important for
    idempotent reindex per AC10.
    """
    _validate_unit_type(unit_type)
    root = Path(vault_root) / "units" / _PLURAL_BY_TYPE[unit_type]
    if not root.is_dir():
        return []
    out: list[dict] = []
    for entry in sorted(root.glob("*.json")):
        try:
            with entry.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                out.append(data)
        except (OSError, json.JSONDecodeError):
            # Skip corrupt files; the reindex script and search route
            # should not crash on a single bad file. A future task
            # can build a repair tool that flags these.
            continue
    return out


def list_all_sentences(vault_root: str) -> list[dict]:
    """Return all sentence units under the vault (sorted by id)."""
    return list_units_by_type(vault_root, "sentence")


def list_sentence_units_sorted(vault_root: str) -> list[dict]:
    """Return all sentence units sorted by id (alias for clarity
    when callers want to make sort order explicit)."""
    return list_all_sentences(vault_root)


def list_all_groups_from_disk(vault_root: str) -> list[dict]:
    """Return all group units under the vault (sorted by id)."""
    return list_units_by_type(vault_root, "group")
