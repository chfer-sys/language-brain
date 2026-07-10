"""Comprehensive vault integrity checker (v0.5.3).

Checks for:
1. DANGLING_REFS     — References to non-existent files
2. MISSING_UNITS     — Word/compound referenced but no unit file
3. DUPLICATE_UNITS   — Same (hanzi, pinyin) in multiple files
4. ID_FILENAME_MISMATCH — Unit id doesn't match filename
5. TYPE_ID_MISMATCH  — Unit type doesn't match id prefix
6. DICT_MISALIGNMENT — Unit id doesn't match dict word-table id
7. ANTONYM_ASYMMETRY — One-directional antonym references
8. LEXICAL_EDGE_GAP  — Sentence references a word but no lexical edge
9. COUNTER_CONSISTENCY — id_counters.json vs actual max ids

Usage:
    python scripts/vault_check.py [--vault-root ./vault] [--fix] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# Ensure api package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.db import get_connection
from api.services.lexical import add_lexical_edge_to_word
from api.services.word_registry import ensure_word_unit_from_dict


# ---------------------------------------------------------------------------
# ID pattern helpers
# ---------------------------------------------------------------------------

_ID_PATTERN = re.compile(r"^[WCSG]\d+$")


def is_id_ref(value: str) -> bool:
    """Return True if ``value`` looks like a unit id (not a hanzi string)."""
    return bool(_ID_PATTERN.match(value))


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _today_iso() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# Vault traversal helpers
# ---------------------------------------------------------------------------

def _all_unit_files(vault_root: Path) -> dict[str, Path]:
    """Return {id: path} for all JSON unit files under vault/units/."""
    result: dict[str, Path] = {}
    units_dir = vault_root / "units"
    for subdir in ("words", "sentences", "groups"):
        for path in (units_dir / subdir).glob("*.json"):
            # For groups, id is the stem (e.g. "G1", "social-interaction")
            result[path.stem] = path
    return result


def _load_all_units(vault_root: Path) -> dict[str, dict]:
    """Load all unit files, returning {id: unit_dict}."""
    units: dict[str, dict] = {}
    for unit_id, path in _all_unit_files(vault_root).items():
        try:
            units[unit_id] = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
    return units


def _dict_lookup(vault_root: Path, hanzi: str, pinyin: str) -> Optional[str]:
    """Look up (hanzi, pinyin) in dict word table. Returns dict id or None."""
    conn = get_connection(str(vault_root))
    try:
        row = conn.execute(
            "SELECT id FROM word WHERE hanzi=? AND pinyin=?",
            (hanzi, pinyin),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def check_dangling_refs(vault_root: Path) -> list[dict]:
    """Check for references to non-existent files."""
    issues: list[dict] = []
    units = _load_all_units(vault_root)
    existing_ids = set(units.keys())

    for unit_id, unit in units.items():
        props = unit.get("properties", {})

        # word_refs
        for ref in props.get("word_refs", []):
            if is_id_ref(ref) and ref not in existing_ids:
                issues.append({
                    "file": unit_id,
                    "kind": "word_refs",
                    "target": ref,
                    "message": f"{unit_id}: word_refs → {ref} (file not found)",
                })

        # antonyms
        for ant in props.get("antonyms", []):
            if is_id_ref(ant) and ant not in existing_ids:
                issues.append({
                    "file": unit_id,
                    "kind": "antonyms",
                    "target": ant,
                    "message": f"{unit_id}: antonyms → {ant} (file not found)",
                })

        # members (groups)
        for ref in props.get("members", []):
            if is_id_ref(ref) and ref not in existing_ids:
                issues.append({
                    "file": unit_id,
                    "kind": "members",
                    "target": ref,
                    "message": f"{unit_id}: members → {ref} (file not found)",
                })

        # connections[].to
        for conn in unit.get("connections", []):
            to_ref = conn.get("to", "")
            if is_id_ref(to_ref) and to_ref not in existing_ids:
                issues.append({
                    "file": unit_id,
                    "kind": "connections",
                    "target": to_ref,
                    "message": f"{unit_id}: connections → {to_ref} (file not found)",
                })

    return issues


def check_missing_units(vault_root: Path) -> list[dict]:
    """Word/compound referenced by sentences but no unit file exists.

    Subset of DANGLING_REFS reported separately.
    """
    issues: list[dict] = []
    units = _load_all_units(vault_root)
    existing_ids = set(units.keys())

    for unit_id, unit in units.items():
        if unit.get("type") != "sentence":
            continue
        props = unit.get("properties", {})
        for ref in props.get("word_refs", []):
            if is_id_ref(ref) and ref not in existing_ids:
                issues.append({
                    "file": unit_id,
                    "target": ref,
                    "message": f"{unit_id}: word_refs → {ref} (unit file missing)",
                })
    return issues


def check_duplicate_units(vault_root: Path) -> list[dict]:
    """Same (hanzi, pinyin) in multiple word/compound files."""
    issues: list[dict] = []
    seen: dict[tuple[str, str], list[str]] = {}  # (hanzi, pinyin) → [unit_ids]
    units_dir = vault_root / "units" / "words"

    for path in units_dir.glob("*.json"):
        try:
            unit = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        props = unit.get("properties", {})
        key = (props.get("hanzi", ""), props.get("pinyin", ""))
        if key[0]:  # non-empty hanzi
            seen.setdefault(key, []).append(unit.get("id", path.stem))

    for (hanzi, pinyin), unit_ids in seen.items():
        if len(unit_ids) > 1:
            issues.append({
                "hanzi": hanzi,
                "pinyin": pinyin,
                "files": unit_ids,
                "message": f"Duplicate: {hanzi}/{pinyin} appears in {unit_ids}",
            })
    return issues


def check_id_filename_mismatch(vault_root: Path) -> list[dict]:
    """Unit's internal id field doesn't match its filename."""
    issues: list[dict] = []
    for unit_id, path in _all_unit_files(vault_root).items():
        try:
            unit = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        file_id = path.stem
        unit_id_inner = unit.get("id", "")
        if unit_id_inner != file_id:
            issues.append({
                "file": file_id,
                "expected": unit_id_inner,
                "message": f"{file_id}.json has id={unit_id_inner!r}",
            })
    return issues


def check_type_id_mismatch(vault_root: Path) -> list[dict]:
    """Unit type doesn't match id prefix."""
    issues: list[dict] = []
    for unit_id, path in _all_unit_files(vault_root).items():
        try:
            unit = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        unit_type = unit.get("type", "")
        # G* groups can have slug ids (e.g. "social-interaction")
        if unit_type == "group":
            continue
        expected_prefix = {"word": "W", "compound": "C", "sentence": "S", "group": "G"}.get(unit_type, "?")
        if unit_id.startswith(expected_prefix):
            continue
        issues.append({
            "file": unit_id,
            "type": unit_type,
            "id_prefix": unit_id[0] if unit_id else "?",
            "expected_prefix": expected_prefix,
            "message": f"{unit_id} has type={unit_type} but prefix={unit_id[0]}",
        })
    return issues


def check_dict_misalignment(vault_root: Path) -> list[dict]:
    """Unit id doesn't match dict word-table id.

    ponytail: informational only — user coinages (not in dict) are NOT errors.
    """
    issues: list[dict] = []
    conn = get_connection(str(vault_root))
    try:
        # Check if word table exists
        try:
            conn.execute("SELECT 1 FROM word LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            # word table doesn't exist yet (fresh vault, no dict imported)
            return [{"status": "NOT_IN_DICT", "message": "dict word table not initialized"}]

        for unit_id, path in _all_unit_files(vault_root).items():
            try:
                unit = _load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            unit_type = unit.get("type", "")
            if unit_type not in ("word", "compound"):
                continue
            props = unit.get("properties", {})
            hanzi = props.get("hanzi", "")
            pinyin = props.get("pinyin", "")
            if not hanzi:
                continue
            row = conn.execute(
                "SELECT id FROM word WHERE hanzi=? AND pinyin=?",
                (hanzi, pinyin),
            ).fetchone()
            if row is None:
                issues.append({
                    "file": unit_id,
                    "hanzi": hanzi,
                    "pinyin": pinyin,
                    "status": "NOT_IN_DICT",
                    "message": f"{unit_id} ({hanzi}/{pinyin}): not in dict (user coinage)",
                })
            elif row[0] != unit_id:
                issues.append({
                    "file": unit_id,
                    "hanzi": hanzi,
                    "pinyin": pinyin,
                    "dict_id": row[0],
                    "status": "MISALIGNED",
                    "message": f"{unit_id} ({hanzi}/{pinyin}): unit id={unit_id} but dict id={row[0]}",
                })
            else:
                issues.append({
                    "file": unit_id,
                    "hanzi": hanzi,
                    "pinyin": pinyin,
                    "status": "OK",
                    "message": f"{unit_id} ({hanzi}/{pinyin}): matches dict ✓",
                })
    finally:
        conn.close()
    return issues


def check_antonym_asymmetry(vault_root: Path) -> list[dict]:
    """One-directional antonym references."""
    issues: list[dict] = []
    units = _load_all_units(vault_root)

    # Build bidirectional map: unit_id → set of antonym ids
    antonym_map: dict[str, set[str]] = {}
    for unit_id, unit in units.items():
        antonyms = unit.get("properties", {}).get("antonyms", [])
        antonym_map[unit_id] = {a for a in antonyms if is_id_ref(a)}

    for unit_id, antonyms in antonym_map.items():
        for ant in antonyms:
            if ant in antonym_map:
                if unit_id not in antonym_map[ant]:
                    issues.append({
                        "file": unit_id,
                        "target": ant,
                        "message": f"{unit_id} → antonym {ant} but {ant} does not reference {unit_id}",
                    })
    return issues


def check_lexical_edge_gap(vault_root: Path) -> list[dict]:
    """Sentence references a word but no lexical edge exists."""
    issues: list[dict] = []
    units = _load_all_units(vault_root)

    for unit_id, unit in units.items():
        if unit.get("type") != "sentence":
            continue
        props = unit.get("properties", {})
        word_refs = {r for r in props.get("word_refs", []) if is_id_ref(r)}
        if not word_refs:
            continue

        # Get lexical connections from the word units
        lexical_targets: set[str] = set()
        for ref in word_refs:
            if ref in units:
                word_unit = units[ref]
                for conn in word_unit.get("connections", []):
                    if conn.get("kind") == "lexical" and conn.get("to") == unit_id:
                        lexical_targets.add(ref)

        missing = word_refs - lexical_targets
        for ref in missing:
            issues.append({
                "file": unit_id,
                "word_ref": ref,
                "message": f"{unit_id}: word_refs includes {ref} but no lexical edge {ref}→{unit_id}",
            })
    return issues


def check_counter_consistency(vault_root: Path) -> list[dict]:
    """id_counters.json vs actual max ids."""
    issues: list[dict] = []
    counters_path = vault_root / "_meta" / "id_counters.json"
    if not counters_path.is_file():
        return [{"message": "id_counters.json not found"}]

    try:
        counters = json.loads(counters_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [{"message": "id_counters.json unreadable"}]

    for letter in ("W", "C", "S", "G"):
        counter_val = counters.get(letter, 0)
        actual_max = 0
        for unit_id in _all_unit_files(vault_root).keys():
            if unit_id.startswith(letter) and unit_id[len(letter):].isdigit():
                actual_max = max(actual_max, int(unit_id[len(letter):]))
        if counter_val < actual_max:
            issues.append({
                "type": letter,
                "counter": counter_val,
                "max_actual": actual_max,
                "message": f"{letter} counter={counter_val} but max actual {letter} id={actual_max}",
            })
    return issues


# ---------------------------------------------------------------------------
# Fix implementations
# ---------------------------------------------------------------------------

def fix_missing_unit(vault_root: Path, sentence_id: str, word_id: str) -> bool:
    """Create a missing word/compound unit from dict lookup.

    Returns True if a file was created, False if skipped/already-exists.
    """
    units = _load_all_units(vault_root)
    if word_id in units:
        return False

    # Look up in dict
    conn = get_connection(str(vault_root))
    try:
        row = conn.execute(
            "SELECT hanzi, pinyin, english FROM word WHERE id=?",
            (word_id,),
        ).fetchone()
        if not row:
            return False
        hanzi, pinyin, english = row
    finally:
        conn.close()

    ensure_word_unit_from_dict(str(vault_root), word_id, hanzi, pinyin, english or "")
    return True


def fix_lexical_edge_gap(vault_root: Path, sentence_id: str, word_id: str) -> bool:
    """Add a missing lexical edge from word to sentence.

    Returns True if an edge was added, False if skipped.
    """
    units = _load_all_units(vault_root)
    if word_id not in units:
        return False
    if sentence_id not in units:
        return False

    try:
        add_lexical_edge_to_word(str(vault_root), word_id, sentence_id, score=1.0)
        return True
    except (OSError, ValueError):
        return False


def fix_antonym_asymmetry(vault_root: Path, unit_id: str, missing_ant: str) -> bool:
    """Add the missing reciprocal antonym entry.

    Returns True if a reciprocal entry was added.
    """
    path = vault_root / "units" / "words" / f"{unit_id}.json"
    if not path.is_file():
        return False
    unit = _load_json(path)
    antonyms = unit.get("properties", {}).get("antonyms", [])
    if not isinstance(antonyms, list):
        antonyms = []
        unit["properties"]["antonyms"] = antonyms

    if missing_ant not in antonyms:
        antonyms.append(missing_ant)
        unit["updated"] = _today_iso()
        _save_json(path, unit)
        return True
    return False


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

_CHECK_NAMES = [
    "DANGLING_REFS",
    "MISSING_UNITS",
    "DUPLICATE_UNITS",
    "ID_FILENAME_MISMATCH",
    "TYPE_ID_MISMATCH",
    "DICT_MISALIGNMENT",
    "ANTONYM_ASYMMETRY",
    "LEXICAL_EDGE_GAP",
    "COUNTER_CONSISTENCY",
]

_CHECK_FUNCTIONS = [
    check_dangling_refs,
    check_missing_units,
    check_duplicate_units,
    check_id_filename_mismatch,
    check_type_id_mismatch,
    check_dict_misalignment,
    check_antonym_asymmetry,
    check_lexical_edge_gap,
    check_counter_consistency,
]


def _format_human(results: dict[str, list[dict]], vault_root: str) -> str:
    lines = [f"Vault Integrity Check — {vault_root}", "═" * 50]

    error_count = 0
    warning_count = 0

    for name, issues in zip(_CHECK_NAMES, results.values()):
        count = len(issues)
        if count == 0:
            status = "✓"
            lines.append(f"{name:<26} 0 issues {status}")
        else:
            # Determine if error or warning based on check type
            # DICT_MISALIGNMENT "not in dict" is informational (not an error)
            # ANTONYM_ASYMMETRY etc. are errors
            has_real_error = any(
                i.get("status") == "MISALIGNED" for i in issues
            )
            has_warning = any(
                i.get("status") == "NOT_IN_DICT" for i in issues
            )
            if has_real_error:
                status = "✗"
                error_count += count
            elif name == "DICT_MISALIGNMENT":
                status = "⚠"
                warning_count += count
            else:
                status = "✗"
                error_count += count

            lines.append(f"{name:<26} {count} issue{'s' if count > 1 else ''} {status}")

            for issue in issues[:5]:  # Show first 5
                lines.append(f"  {issue.get('message', str(issue))}")
            if len(issues) > 5:
                lines.append(f"  ... and {len(issues) - 5} more")

    lines.append("═" * 50)
    if error_count == 0 and warning_count == 0:
        lines.append("Result: clean ✓")
    else:
        parts = []
        if error_count:
            parts.append(f"{error_count} error{'s' if error_count > 1 else ''}")
        if warning_count:
            parts.append(f"{warning_count} warning{'s' if warning_count > 1 else ''}")
        lines.append("Result: " + ", ".join(parts))

    return "\n".join(lines)


def _format_json(results: dict[str, list[dict]], vault_root: str) -> str:
    checks = {}
    error_count = 0
    warning_count = 0

    for name, issues in zip(_CHECK_NAMES, results.values()):
        count = len(issues)
        has_error = any(i.get("status") == "MISALIGNED" for i in issues)
        has_warning = any(i.get("status") == "NOT_IN_DICT" for i in issues)

        if has_error:
            status = "fail"
            error_count += count
        elif has_warning:
            status = "warn"
            warning_count += count
        elif count > 0:
            status = "fail"
            error_count += count
        else:
            status = "pass"

        checks[name] = {"status": status, "count": count, "issues": issues}

    output = {
        "vault_root": vault_root,
        "checks": checks,
        "summary": {
            "errors": error_count,
            "warnings": warning_count,
            "total_checks": len(_CHECK_NAMES),
        },
    }
    return json.dumps(output, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main checker
# ---------------------------------------------------------------------------

class VaultChecker:
    def __init__(self, vault_root: str, fix: bool = False):
        self.vault_root = Path(vault_root).resolve()
        self.fix = fix
        self.fixed: list[str] = []

    def run_all(self) -> dict[str, list[dict]]:
        results: dict[str, list[dict]] = {}
        for name, fn in zip(_CHECK_NAMES, _CHECK_FUNCTIONS):
            results[name] = fn(self.vault_root)
        return results

    def apply_fixes(self, results: dict[str, list[dict]]) -> dict[str, list[dict]]:
        if not self.fix:
            return results

        # MISSING_UNITS: create from dict
        for issue in results["MISSING_UNITS"]:
            word_id = issue.get("target", "")
            sentence_id = issue.get("file", "")
            if word_id and sentence_id:
                if fix_missing_unit(self.vault_root, sentence_id, word_id):
                    self.fixed.append(f"Created {word_id} from dict")

        # LEXICAL_EDGE_GAP: add missing edges
        for issue in results["LEXICAL_EDGE_GAP"]:
            word_id = issue.get("word_ref", "")
            sentence_id = issue.get("file", "")
            if word_id and sentence_id:
                if fix_lexical_edge_gap(self.vault_root, sentence_id, word_id):
                    self.fixed.append(f"Added lexical edge {word_id}→{sentence_id}")

        # ANTONYM_ASYMMETRY: add missing reciprocal
        for issue in results["ANTONYM_ASYMMETRY"]:
            unit_id = issue.get("file", "")
            missing_ant = issue.get("target", "")
            if unit_id and missing_ant:
                if fix_antonym_asymmetry(self.vault_root, unit_id, missing_ant):
                    self.fixed.append(f"Added reciprocal antonym {unit_id}↔{missing_ant}")

        # Re-run to confirm
        return self.run_all()


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--vault-root",
        default="./vault",
        help="path to vault root (default: ./vault)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="attempt to auto-fix safe issues",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output as JSON instead of human-readable text",
    )
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root).resolve()
    if not vault_root.exists():
        print(f"ERROR: Vault root does not exist: {vault_root}", file=sys.stderr)
        return 1

    checker = VaultChecker(str(vault_root), fix=args.fix)
    results = checker.run_all()

    if args.fix and any(results.values()):
        print("Auto-fixing issues...", file=sys.stderr)
        results = checker.apply_fixes(results)
        if checker.fixed:
            print(f"Fixed: {', '.join(checker.fixed)}", file=sys.stderr)

    if args.json:
        print(_format_json(results, str(vault_root)))
    else:
        print(_format_human(results, str(vault_root)))

    # Exit code: 0 if clean, 1 if actual errors
    # NOT_IN_DICT is informational (user coinage), not an error
    has_real_issues = any(
        issues
        for name, issues in results.items()
        if name != "DICT_MISALIGNMENT"
    ) or any(
        i for i in results.get("DICT_MISALIGNMENT", [])
        if i.get("status") == "MISALIGNED"
    )
    return 1 if has_real_issues else 0


main = _main

if __name__ == "__main__":
    raise SystemExit(_main())
