"""Search latency benchmark for the language-brain vault.

Measures p50/p95/p99 latency for:
- lexical_search (hanzi query)
- lexical_search (english query)
- semantic_search (semantic query)
- suggest_units (prefix suggest)

Then generates synthetic vaults at target scales and benchmarks those.

Usage:
    python scripts/benchmark_search.py --vault ./vault
    python scripts/benchmark_search.py --vault ./vault --scales 100,1000,10000
    python scripts/benchmark_search.py --vault ./vault --scales 100,1000 --json
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Ensure api package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.embedder import HashingEmbedder
from api.services.indexer import Index
from api.services.search import lexical_search, semantic_search, suggest_units
from api.services.unit_writer import list_units_by_type

# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------


def _time_call(func, *args, **kwargs) -> tuple[Any, int]:
    """Call func(*args, **kwargs) and return (result, elapsed_ns)."""
    start = time.perf_counter_ns()
    result = func(*args, **kwargs)
    elapsed = time.perf_counter_ns() - start
    return result, elapsed


def _percentiles(values: list[int], pcts: list[float]) -> dict[str, float]:
    """Return {f"p{p}": value_in_ns_converted_to_ms} for requested percentiles."""
    sorted_vals = sorted(values)
    out = {}
    for p in pcts:
        idx = int(len(sorted_vals) * p / 100)
        if idx >= len(sorted_vals):
            idx = len(sorted_vals) - 1
        out[f"p{int(p)}"] = round(sorted_vals[idx] / 1_000_000, 2)
    return out


# ---------------------------------------------------------------------------
# Vault stats
# ---------------------------------------------------------------------------


def _vault_stats(vault_root: str) -> dict[str, int]:
    """Count sentences, words, and groups in the vault."""
    sentences = len(list_units_by_type(vault_root, "sentence"))
    words = len(list_units_by_type(vault_root, "word"))
    groups = len(list_units_by_type(vault_root, "group"))
    return {"sentences": sentences, "words": words, "groups": groups}


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


def _benchmark_search(
    vault_root: str,
    warm_up: int = 5,
    measured: int = 100,
) -> dict[str, dict[str, float]]:
    """Run all four search benchmarks.

    Returns a dict keyed by benchmark name, each containing p50/p95/p99 in ms.
    """
    embedder = HashingEmbedder()

    # ---- Warm up -----------------------------------------------------------
    for _ in range(warm_up):
        lexical_search(vault_root, query="吃")
        lexical_search(vault_root, query="eat")
        semantic_search(vault_root, query="eating food", embedder=embedder)
        suggest_units(vault_root, prefix="我", limit=5)

    # ---- Measure -----------------------------------------------------------
    def _run(name: str, func, *args, **kwargs) -> dict[str, float]:
        times: list[int] = []
        for _ in range(measured):
            _, ns = _time_call(func, *args, **kwargs)
            times.append(ns)
        return _percentiles(times, [50, 95, 99])

    return {
        "lexical_hanzi": _run(
            "lexical_hanzi",
            lexical_search,
            vault_root,
            query="吃",
        ),
        "lexical_english": _run(
            "lexical_english",
            lexical_search,
            vault_root,
            query="eat",
        ),
        "semantic": _run(
            "semantic",
            semantic_search,
            vault_root,
            query="eating food",
            embedder=embedder,
        ),
        "suggest": _run(
            "suggest",
            suggest_units,
            vault_root,
            prefix="我",
            limit=5,
        ),
    }


# ---------------------------------------------------------------------------
# Synthetic vault generation
# ---------------------------------------------------------------------------


def _sample_hanzi_from_dict(vault_root: str, n: int) -> list[str]:
    """Sample n hanzi characters from the dict word table.

    Uses the real vault's vault.db word table. Falls back to a hardcoded
    pool if the table is empty or inaccessible.
    """
    db_path = Path(vault_root) / "index" / "vault.db"
    pool: list[str] = []

    # ponytail: if dict isn't imported yet, use a compact fallback pool.
    # These are common single-character hanzi from SUBTLEX-CH top frequency.
    fallback = list(
        "的一是了我不人在有他这为之大来以个中上们"
        "到说国和做过热也天自能而对面子得着过发"
        "后去行你很最重并先现在所发现只么还心此"
        "老将没每于起与小型更更更更更更更更更更"
    )

    try:
        if db_path.is_file():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT hanzi FROM word WHERE length(hanzi)=1 ORDER BY frequency DESC LIMIT ?",
                (n * 3,),
            ).fetchall()
            conn.close()
            pool = [r["hanzi"] for r in rows if isinstance(r["hanzi"], str) and r["hanzi"]]
    except Exception:
        pass

    if len(pool) < n:
        pool = list("的一是了我不人在有他这为之大来以个中上们到说国和做过热也天自能而对面子得着过后去行你很最重并先现在所发现只么还心此老将没每于起与小更与")

    # Deterministic shuffle using a fixed seed so repeated runs produce
    # the same vault (useful for debugging).
    rng = random.Random(42)
    result = rng.sample(pool * ((n // len(pool)) + 1), n)
    return result


def _build_synthetic_vault(
    vault_root: str,
    n_sentences: int,
    n_words: int,
    n_groups: int,
) -> None:
    """Generate a synthetic vault with approximately n_sentences/n_words/n_groups units.

    Sentences: 2-6 hanzi drawn from the dict word table.
    Words: single characters extracted from sentence content.
    Groups: simple numbered groups.
    """
    rng = random.Random(42)

    # Sample hanzi pool
    all_hanzi = _sample_hanzi_from_dict(vault_root, n_sentences * 4)

    units_dir = Path(vault_root) / "units"
    words_dir = units_dir / "words"
    sentences_dir = units_dir / "sentences"
    groups_dir = units_dir / "groups"
    index_dir = Path(vault_root) / "index"
    meta_dir = Path(vault_root) / "_meta"

    for d in (words_dir, sentences_dir, groups_dir, index_dir, meta_dir):
        d.mkdir(parents=True, exist_ok=True)

    # --- Write sentences ---
    sentence_hanzi: list[str] = []
    word_ids_used: set[str] = set()

    for i in range(1, n_sentences + 1):
        # 2-6 hanzi
        length = rng.randint(2, 6)
        hanzi = "".join(rng.sample(all_hanzi, length))
        sentence_hanzi.append(hanzi)
        sid = f"S{i}"
        meaning = f"Meaning of {hanzi}"
        # Extract unique characters as word refs
        unique_chars = sorted(set(hanzi))
        word_refs = []
        for ch in unique_chars:
            # Find or assign a word id for this character
            ch_idx = ord(ch) % n_words
            wid = f"W{ch_idx + 1}"
            if wid not in word_ids_used and len(word_ids_used) < n_words:
                word_ids_used.add(wid)
            word_refs.append(wid)

        unit = {
            "id": sid,
            "type": "sentence",
            "name": hanzi,
            "properties": {
                "hanzi": hanzi,
                "pinyin": " ".join(list(hanzi)),
                "english": meaning,
                "meaning": meaning,
                "words": list(hanzi),
                "word_refs": word_refs,
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-07-10",
            "updated": "2026-07-10",
            "author_confirmed": True,
        }
        path = sentences_dir / f"{sid}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(unit, f, ensure_ascii=False, indent=2)
            f.write("\n")

    # --- Write words ---
    for i in range(1, n_words + 1):
        wid = f"W{i}"
        char_idx = (i - 1) % len(all_hanzi)
        hanzi = all_hanzi[char_idx]
        unit = {
            "id": wid,
            "type": "word",
            "name": hanzi,
            "properties": {
                "hanzi": hanzi,
                "pinyin": "p",
                "english": "",
                "meaning": "",
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-07-10",
            "updated": "2026-07-10",
            "author_confirmed": True,
        }
        path = words_dir / f"{wid}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(unit, f, ensure_ascii=False, indent=2)
            f.write("\n")

    # --- Write groups ---
    for i in range(1, n_groups + 1):
        gid = f"G{i}"
        unit = {
            "id": gid,
            "type": "group",
            "name": gid,
            "properties": {
                "display_name": f"Group {i}",
                "description": "",
                "members": [],
            },
            "connections": [],
            "created": "2026-07-10",
            "updated": "2026-07-10",
            "author_confirmed": True,
        }
        path = groups_dir / f"{gid}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(unit, f, ensure_ascii=False, indent=2)
            f.write("\n")

    # --- Write id_counters.json ---
    counters = {
        "W": n_words,
        "C": 0,
        "S": n_sentences,
        "G": n_groups,
    }
    (meta_dir / "id_counters.json").write_text(
        json.dumps(counters, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- Build FAISS index (HashingEmbedder, no model download) ---
    embedder = HashingEmbedder()
    sentences = list_units_by_type(vault_root, "sentence")
    index = Index()
    indexed = 0
    for sent in sentences:
        meaning = sent.get("properties", {}).get("meaning", "")
        sid = sent.get("id")
        if not sid or not isinstance(meaning, str) or not meaning.strip():
            continue
        vec = embedder.embed(meaning)
        index.add(sid, vec)
        indexed += 1

    index.save(vault_root)

    # last_reindex.json
    (index_dir / "last_reindex.json").write_text(
        json.dumps(
            {"scanned": len(sentences), "indexed": indexed, "skipped": len(sentences) - indexed},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _format_human(
    vault_path: str,
    stats: dict[str, int],
    current_results: dict[str, dict[str, float]] | None,
    scale_results: dict[str, Any] | None,
    thresholds: tuple[float, float] = (20.0, 50.0),
) -> str:
    """Format benchmark results as human-readable text."""
    p50_target, p95_target = thresholds
    lines = []
    n_sent, n_word, n_group = stats["sentences"], stats["words"], stats["groups"]
    lines.append(f"Search Benchmark — {vault_path} ({n_sent} sentences, {n_word} words)")
    lines.append("═" * 60)

    def _row(label: str, res: dict[str, float]) -> str:
        p50 = res.get("p50", 0)
        p95 = res.get("p95", 0)
        p99 = res.get("p99", 0)
        return f"  {label:<30} p50={p50:>7.1f}ms  p95={p95:>7.1f}ms  p99={p99:>7.1f}ms"

    if current_results:
        lines.append("\nCurrent vault:")
        lines.append(_row('lexical (hanzi "吃"):', current_results["lexical_hanzi"]))
        lines.append(_row('lexical (english "eat"):', current_results["lexical_english"]))
        lines.append(_row('semantic ("eating food"):', current_results["semantic"]))
        lines.append(_row('suggest ("我"):', current_results["suggest"]))

    if scale_results:
        for scale_str, res in scale_results.items():
            s_stats = res["stats"]
            lines.append(
                f"\nSynthetic {scale_str} units "
                f"({s_stats['sentences']} sentences, "
                f"{s_stats['words']} words):"
            )
            lines.append(_row("lexical (hanzi):", res["lexical_hanzi"]))
            lines.append(_row("lexical (english):", res["lexical_english"]))
            lines.append(_row("semantic:", res["semantic"]))
            lines.append(_row("suggest:", res["suggest"]))

    # Threshold analysis
    lines.append("\nThreshold lines:")
    if scale_results:
        for scale_str, res in scale_results.items():
            p50 = res["lexical_hanzi"].get("p50", 0)
            p95 = res["lexical_hanzi"].get("p95", 0)
            p50_ok = "MET" if p50 < p50_target else "NOT MET"
            p95_ok = "MET" if p95 < p95_target else "NOT MET"
            lines.append(
                f"  p50 < {p50_target}ms / p95 < {p95_target}ms: "
                f"p50={p50_ok}, p95={p95_ok} at {scale_str}"
            )

    return "\n".join(lines)


def _format_json(
    vault_path: str,
    stats: dict[str, int],
    current_results: dict[str, dict[str, float]] | None,
    scale_results: dict[str, Any] | None,
) -> str:
    """Format benchmark results as JSON."""
    out: dict[str, Any] = {
        "vault_path": str(vault_path),
        "vault_stats": stats,
        "current_vault": current_results,
        "synthetic": {},
    }
    if scale_results:
        for scale_str, res in scale_results.items():
            out["synthetic"][scale_str] = {
                "stats": res["stats"],
                "benchmarks": {
                    "lexical_hanzi": res["lexical_hanzi"],
                    "lexical_english": res["lexical_english"],
                    "semantic": res["semantic"],
                    "suggest": res["suggest"],
                },
            }
    return json.dumps(out, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark search latency over the language-brain vault.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--vault",
        default="./vault",
        help="Path to vault root (default: ./vault)",
    )
    parser.add_argument(
        "--scales",
        default="",
        help="Comma-separated target scales for synthetic vaults "
        "(e.g. 100,1000,10000). If omitted, only benchmarks the real vault.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--warm-up",
        type=int,
        default=5,
        help="Number of warm-up calls before measured runs (default: 5).",
    )
    parser.add_argument(
        "--measured",
        type=int,
        default=100,
        help="Number of measured calls per benchmark (default: 100).",
    )
    parser.add_argument(
        "--thresholds",
        default="20,50",
        help="Comma-separated p50/p95 threshold in ms (default: 20,50).",
    )
    args = parser.parse_args(argv)

    vault_root = str(Path(args.vault).resolve())
    if not Path(vault_root).exists():
        print(f"ERROR: Vault root does not exist: {vault_root}", file=sys.stderr)
        return 1

    # Parse thresholds
    try:
        p50_thresh, p95_thresh = (float(x) for x in args.thresholds.split(","))
    except ValueError:
        print(
            f"ERROR: --thresholds must be two comma-separated floats, got {args.thresholds!r}",
            file=sys.stderr,
        )
        return 1

    # Parse scales
    scales: list[int] = []
    if args.scales:
        for s in args.scales.split(","):
            s = s.strip()
            if s:
                try:
                    scales.append(int(s))
                except ValueError:
                    print(f"ERROR: {s!r} is not a valid integer scale", file=sys.stderr)
                    return 1

    # Collect results
    stats = _vault_stats(vault_root)

    # Current vault benchmark
    current_results = _benchmark_search(
        vault_root,
        warm_up=args.warm_up,
        measured=args.measured,
    )

    # Synthetic vault benchmarks
    scale_results: dict[str, Any] = {}
    for scale in scales:
        n_sentences = scale
        n_words = max(1, scale // 3)
        n_groups = max(1, scale // 10)

        # ponytail: for 10k, reduce to 5k if generation + indexing takes too long.
        # The point is to find the knee in the curve.
        if scale >= 10_000:
            n_sentences = 5_000
            n_words = max(1, 5_000 // 3)
            n_groups = max(1, 5_000 // 10)
            scale_label = "10000"
        else:
            scale_label = str(scale)

        tmp = tempfile.mkdtemp(prefix="benchmark_vault_")
        try:
            _build_synthetic_vault(tmp, n_sentences, n_words, n_groups)
            synth_stats = _vault_stats(tmp)
            synth_results = _benchmark_search(
                tmp,
                warm_up=args.warm_up,
                measured=args.measured,
            )
            scale_results[scale_label] = {
                "stats": synth_stats,
                "lexical_hanzi": synth_results["lexical_hanzi"],
                "lexical_english": synth_results["lexical_english"],
                "semantic": synth_results["semantic"],
                "suggest": synth_results["suggest"],
            }
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # Output
    if args.json:
        print(
            _format_json(vault_root, stats, current_results, scale_results),
        )
    else:
        print(
            _format_human(
                vault_root,
                stats,
                current_results,
                scale_results,
                thresholds=(p50_thresh, p95_thresh),
            ),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
