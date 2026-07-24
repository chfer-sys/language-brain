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
import logging
import os
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

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

    # Dual-write: upsert into SQLite so subsequent reads via SQLite
    # see the new data. Wrapped in try/except so a SQLite failure
    # doesn't corrupt the JSON write (JSON remains source of truth).
    # ponytail: ceiling — opens a new connection per write; upgrade
    # path is connection pooling if write throughput becomes a bottleneck.
    try:
        from api.services.db import get_connection, init_schema

        conn = get_connection(vault_root)
        try:
            init_schema(conn)
            # Disable FK constraints for the dual-write. The live vault may
            # have dangling references (e.g. a connection pointing at a unit
            # that hasn't been written yet). The migration script does the
            # same. ponytail: bulk-write relaxation is the standard pattern;
            # the FK is back ON at connection level for reads.
            conn.execute("PRAGMA foreign_keys = OFF")
            _upsert_unit(conn, unit)
            # If the unit has connections, also upsert edges.
            connections = unit.get("connections") or []
            if connections:
                _upsert_edges(conn, unit_id, connections)
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        # SQLite write failed; log but don't raise. JSON is source of truth.
        log.warning("dual-write to SQLite failed for unit %r: %s", unit_id, exc)

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


# ---------------------------------------------------------------------------
# Dual-write helpers (v0.10) — upsert into SQLite after JSON write
# ---------------------------------------------------------------------------


def _upsert_unit(conn, unit: dict) -> None:
    """Upsert a unit into the SQLite ``unit`` table.

    Mirrors the migration script's ``_insert_unit`` but uses INSERT OR REPLACE
    so re-writes update the row. The ``sort_key`` is set to 0 (matching the
    migration script's default). The ``name`` column is populated from
    ``properties.hanzi`` or ``properties.display_name`` (falling back to the
    unit's top-level ``name`` field if present).
    """
    import sqlite3

    props = unit.get("properties", {}) or {}
    # ponytail: name resolution prefers hanzi (sentences/words/compounds) then
    # display_name (groups). The migration script uses payload.get("name", "")
    # which is usually empty; we do better here so the browse endpoint can
    # use the name column directly if needed.
    name = props.get("hanzi") or props.get("display_name") or unit.get("name", "")
    row = (
        unit["id"],
        unit["type"],
        0,  # sort_key — matching migration script default
        name,
        props.get("pinyin"),
        props.get("english"),
        props.get("meaning") or None,
        json.dumps(props, ensure_ascii=False),
        unit.get("created", ""),
        unit.get("updated", ""),
        1 if unit.get("author_confirmed") else 0,
    )
    conn.execute(
        "INSERT OR REPLACE INTO unit "
        "(id, type, sort_key, name, pinyin, english, gloss, properties, created, updated, author_confirmed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    # Also upsert into FTS5 for search.
    conn.execute(
        "INSERT OR REPLACE INTO unit_fts (id, type, name, english, gloss) VALUES (?, ?, ?, ?, ?)",
        (
            unit["id"],
            unit["type"],
            name,
            props.get("english") or "",
            props.get("meaning") or "",
        ),
    )


def _upsert_edges(conn, unit_id: str, connections: list[dict]) -> None:
    """Upsert edges for a unit into the SQLite ``edge`` table.

    Deletes all existing edges where this unit is the source, then inserts
    the new edges from the ``connections`` array. This is simpler than diffing
    old vs new edges and ensures the edge table stays in sync with the JSON.
    """
    # Delete existing edges for this source.
    conn.execute("DELETE FROM edge WHERE source_id = ?", (unit_id,))
    # Insert new edges.
    for conn_dict in connections:
        target_id = conn_dict.get("to")
        kind = conn_dict.get("kind")
        score = conn_dict.get("score")
        if not target_id or not kind:
            continue
        conn.execute(
            "INSERT INTO edge (source_id, target_id, kind, score) VALUES (?, ?, ?, ?)",
            (unit_id, target_id, kind, score),
        )
