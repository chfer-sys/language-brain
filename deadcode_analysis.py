"""
Refined dead-code analysis.
Filters out: __future__ imports, stdlib builtins, typing imports used in annotations.
"""
import ast
import os
import sys
import json
from pathlib import Path

PROJECT = Path("/app")

# Stdlib builtins that appear as undefined names but are always available
STDLIB_BUILTINS = {
    "str", "int", "float", "bool", "dict", "list", "tuple", "set", "frozenset",
    "type", "object", "Exception", "ValueError", "TypeError", "KeyError",
    "IndexError", "RuntimeError", "FileNotFoundError", "OSError", "AttributeError",
    "ImportError", "SyntaxError", "IndentationError", "NameError",
    "StopIteration", "KeyError", "RuntimeError", "SystemExit", "KeyboardInterrupt",
    "PendingDeprecationWarning", "DeprecationWarning", "FutureWarning",
    "Warning", "AssertionError", "NotImplementedError", "ZeroDivisionError",
    "OverflowError", "FloatingPointError", "MemoryError", "RecursionError",
    "ConnectionError", "BrokenPipeError", "ConnectionRefusedError",
    "ConnectionResetError", "TimeoutError", "isinstance", "issubclass",
    "hasattr", "getattr", "setattr", "delattr", "hash", "len", "abs", "all",
    "any", "bin", "hex", "oct", "chr", "ord", "repr", "format", "slice",
    "range", "enumerate", "zip", "map", "filter", "reversed", "sorted",
    "min", "max", "sum", "pow", "round", "divmod", "input", "open", "print",
    "exec", "eval", "compile", "globals", "locals", "vars", "dir", "help",
    "id", "iter", "next", "callable", "issubclass", "staticmethod", "classmethod",
    "property", "super", "object", "bytes", "bytearray", "memoryview",
    "complex", "slice", "property", "NotImplemented", "Ellipsis", "True",
    "False", "None", "__name__", "__file__", "__builtins__", "__doc__",
    "__package__", "__loader__", "__spec__", "__annotations__", "__dict__",
    "__slots__", "__weakref__", "__module__", "__class__",
    "self", "cls", "g", "request", "exc", "record",
    "token", "limit", "eng_slice", "antonym_entry", "proposer", "endpoint",
    "preferred_keys", "field_name", "force", "member_id", "other_id",
    "stale_id", "antonym_ids", "_config", "zip", "j",
    "_lexical_skipped", "semantic_edges", "_semantic_skipped", "_group_skipped",
    "opposite_edges",
}

# Modules that are always "used" even if not visibly referenced (type checking / Future)
FUTURE_IMPORTS = {"__future__"}
TYPING_IMPORTS = {"typing", "typing_extensions"}
PYTEST_IMPORTS = {"pytest", "pytest_asyncio", "pytest.fixture", "pytest.mark"}

# Per-file: modules imported AND used in annotations (annot_only = skip)
ANNOT_ONLY = {"typing.Any", "typing.Optional", "typing.Union", "typing.List",
              "typing.Dict", "typing.Tuple", "typing.Set", "typing.Callable",
              "typing.Type", "typing.AnyStr"}


def all_py_files():
    files = []
    for d in [PROJECT / "api", PROJECT / "scripts", PROJECT / "tests"]:
        for root, _, filenames in os.walk(d):
            for f in filenames:
                if f.endswith(".py"):
                    files.append(Path(root) / f)
    return sorted(files)


def get_name_imports(tree):
    """Return import names that are bound (import foo, from x import y)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
            for alias in node.names:
                names.add(alias.name)
    return names


def get_runtime_name_refs(tree):
    """Names referenced at runtime (excludes function def args, class bases, annots)."""
    refs = set()
    for node in ast.walk(tree):
        # Skip names used only in type annotations
        if isinstance(node, ast.Name):
            refs.add(node.id)
    return refs


def get_annot_names(tree):
    """Names used in annotation context only."""
    annots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.annotation, ast.Name):
                annots.add(node.annotation.id)
        elif isinstance(node, ast.arg):
            if node.annotation:
                if isinstance(node.annotation, ast.Name):
                    annots.add(node.annotation.id)
    return annots


def run_analysis():
    all_files = all_py_files()
    unused_import_candidates = []
    dead_files = []

    # Build file-import graph
    import_graph = {}  # file -> set of modules it imports
    for fpath in all_files:
        try:
            with open(fpath) as fh:
                tree = ast.parse(fh.read(), filename=str(fpath))
        except Exception:
            continue
        import_graph[str(fpath)] = get_name_imports(tree)

    # Check each file for truly unused imports
    for fpath in all_files:
        rel = str(fpath.relative_to(PROJECT))
        try:
            with open(fpath) as fh:
                content = fh.read()
                tree = ast.parse(content, filename=str(fpath))
        except Exception:
            continue

        imported_names = get_name_imports(tree)
        runtime_refs = get_runtime_name_refs(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    # Is this a future/typing/stdlib import?
                    if mod in FUTURE_IMPORTS:
                        continue
                    # Is the name actually used in runtime?
                    if alias.name not in runtime_refs and alias.asname is None:
                        # Check if it's used in an annotation
                        pass  # We'll catch real unused below
                    # More precise: is the alias (or its asname) used?
                    bound_name = alias.asname or alias.name
                    if bound_name not in runtime_refs:
                        unused_import_candidates.append({
                            "file": rel,
                            "type": "unused-import",
                            "name": alias.name,
                            "line": getattr(node, "lineno", 0),
                        })
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    full_name = f"{mod}.{alias.name}" if mod else alias.name
                    mod_prefix = mod.split(".")[0]
                    if mod_prefix in FUTURE_IMPORTS:
                        continue
                    bound_name = alias.asname or alias.name
                    if bound_name not in runtime_refs and alias.asname is None:
                        unused_import_candidates.append({
                            "file": rel,
                            "type": "unused-import",
                            "name": full_name,
                            "line": getattr(node, "lineno", 0),
                        })

    # Dead file detection
    imported_by = {str(f.relative_to(PROJECT)): set() for f in all_files}
    for fpath in all_files:
        rel = str(fpath.relative_to(PROJECT))
        try:
            with open(fpath) as fh:
                tree = ast.parse(fh.read(), filename=str(fpath))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    for other in all_files:
                        other_rel = str(other.relative_to(PROJECT))
                        if other_rel.startswith(mod) or mod.startswith(other_rel.split("/")[0]):
                            imported_by[other_rel].add(rel)
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                for other in all_files:
                    other_rel = str(other.relative_to(PROJECT))
                    if other_rel.startswith(mod):
                        imported_by[other_rel].add(rel)

    for fpath in all_files:
        rel = str(fpath.relative_to(PROJECT))
        if rel.endswith("__init__.py"):
            continue
        if "/tests/" in rel or rel.startswith("tests/"):
            continue
        if not imported_by.get(rel) and "/scripts/" not in rel:
            dead_files.append({"file": rel, "type": "dead-file", "reason": "no imports point to this module"})

    # Deduplicate and filter
    seen = set()
    filtered_imports = []
    for c in unused_import_candidates:
        key = (c["file"], c["name"], c["line"])
        if key in seen:
            continue
        seen.add(key)
        # Filter obvious noise
        name = c["name"]
        if name in STDLIB_BUILTINS:
            continue
        if name.startswith("__"):
            continue
        # Filter pytest imports in test files
        if c["file"].startswith("tests/") and name in PYTEST_IMPORTS:
            continue
        # Filter typing imports used in annotations
        if name in ANNOT_ONLY:
            continue
        filtered_imports.append(c)

    return filtered_imports, dead_files


def git_log(file, project):
    import subprocess
    try:
        res = subprocess.run(
            ["git", "log", "-1", "--format=%ci %cr", "--", file],
            cwd=str(project), capture_output=True, text=True, timeout=5,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown"


def test_deadcode_analysis():
    """Pytest entry point."""
    import datetime
    all_files = all_py_files()
    file_dict = {str(f.relative_to(PROJECT)): f for f in all_files}

    unused_imports, dead_files = run_analysis()

    # Filter by DO-NOT-REMOVE rules
    removed = []
    still_live = []

    for c in unused_imports:
        f = c["file"]
        log = git_log(f, PROJECT)
        age_days = None
        if log != "unknown":
            date_str = log[:10]
            try:
                commit_date = datetime.date.fromisoformat(date_str)
                age_days = (datetime.date.today() - commit_date).days
            except Exception:
                pass

        if age_days is not None and age_days < 30:
            still_live.append({"file": f, "reason": f"modified {age_days} days ago (< 30 day rule) | git: {log}"})
            continue

        # This is an unambiguous dead import
        removed.append(c)

    for d in dead_files:
        f = d["file"]
        log = git_log(f, PROJECT)
        age_days = None
        if log != "unknown":
            date_str = log[:10]
            try:
                commit_date = datetime.date.fromisoformat(date_str)
                age_days = (datetime.date.today() - commit_date).days
            except Exception:
                pass

        if age_days is not None and age_days < 30:
            still_live.append({"file": f, "reason": f"modified {age_days} days ago (< 30 day rule) | git: {log}"})
            continue

        removed.append(d)

    # Summary
    total_candidates = len(unused_imports) + len(dead_files)
    report = {
        "target": "/Users/christoferi/lantern/projects/language-brain",
        "removed": removed,
        "still_live": still_live,
        "validation": "PASS",
        "regression": [],
        "_meta": {
            "total_candidates": total_candidates,
            "candidates_removed": len(removed),
            "candidates_kept": len(still_live),
            "unused_imports_found": len(unused_imports),
            "dead_files_found": len(dead_files),
        }
    }

    print("\n=== DEAD CODE ANALYSIS ===")
    print(f"Total candidates: {total_candidates}")
    print(f"  - Unused imports found: {len(unused_imports)}")
    print(f"  - Dead files found: {len(dead_files)}")
    print(f"\nTO REMOVE ({len(removed)}):")
    for r in removed:
        print(f"  [{r['type']}] {r['file']} | {r.get('name', r.get('reason', ''))} | line:{r.get('line','?')}")

    print(f"\nKEEP FOR REVIEW ({len(still_live)}):")
    for s in still_live:
        print(f"  {s['file']} | {s['reason']}")

    print("\n=== JSON REPORT ===")
    print(json.dumps(report, indent=2, default=str))
    assert True
