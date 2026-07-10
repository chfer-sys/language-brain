"""ID counter for typed variable-width unit ids (v0.5.2).

Each unit type (W=word, C=compound, S=sentence, G=group) has a
monotonic integer counter stored in ``vault/_meta/id_counters.json``.
The id is ``f"{letter}{n}"`` with no padding — variable width.

Counters are concurrent-safe via ``fcntl.flock`` and restart-safe
because the file is written atomically with ``os.replace``.

ponytail: W and C counters are vestigial for word/compound creation since
v0.5.3 Bite 3a — dict ids (from the word table) are used via
``ensure_word_unit_from_dict`` instead of the counter. The counters are
still needed for S (sentence) and G (group) ids.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

_COUNTERS_FILE = "id_counters.json"

_TYPE_LETTERS: dict[str, str] = {
    "word": "W",
    "compound": "C",
    "sentence": "S",
    "group": "G",
}


def _counters_path(vault_root: str) -> Path:
    return Path(vault_root) / "_meta" / _COUNTERS_FILE


def _read_counters(vault_root: str) -> dict[str, int]:
    path = _counters_path(vault_root)
    if not path.is_file():
        return {letter: 0 for letter in _TYPE_LETTERS.values()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: int(v) for k, v in data.items() if k in _TYPE_LETTERS.values()}
    except (OSError, ValueError, TypeError):
        pass
    return {letter: 0 for letter in _TYPE_LETTERS.values()}


def _write_counters(vault_root: str, counters: dict[str, int]) -> None:
    path = _counters_path(vault_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(counters, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def next_id(vault_root: str, unit_type: str) -> str:
    """Atomically allocate and return the next id for ``unit_type``.

    ``unit_type`` is one of ``"word"``, ``"compound"``, ``"sentence"``,
    ``"group"``. Returns ``"W1"``, ``"C1"``, ``"S1"``, ``"G1"`` etc.
    """
    letter = _TYPE_LETTERS.get(unit_type)
    if letter is None:
        raise ValueError(f"unknown unit_type {unit_type!r}; expected one of {sorted(_TYPE_LETTERS)}")

    path = _counters_path(vault_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Open for read+write, create if missing.
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        # Re-read under lock.
        os.lseek(fd, 0, os.SEEK_SET)
        raw = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            raw += chunk
        counters = {letter: 0 for letter in _TYPE_LETTERS.values()}
        if raw.strip():
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    for k, v in loaded.items():
                        if k in counters:
                            counters[k] = int(v)
            except (ValueError, TypeError):
                pass
        counters[letter] += 1
        new_id = f"{letter}{counters[letter]}"
        # Write back.
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps(counters, indent=2).encode("utf-8"))
        os.fsync(fd)
        return new_id
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def init_counters(vault_root: str, overrides: dict[str, int] | None = None) -> dict[str, int]:
    """Ensure the counters file exists. Returns the current counters.

    If ``overrides`` is given, merge them (taking the max per key) and
    write. Used by the migration script to set initial counters after
    bulk-assigning ids to existing units.
    """
    counters = _read_counters(vault_root)
    if overrides:
        for letter, val in overrides.items():
            if letter in counters:
                counters[letter] = max(counters[letter], val)
    # Only write if file missing or overrides changed something.
    _write_counters(vault_root, counters)
    return counters
