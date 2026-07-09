"""Hermetic tests for ``scripts/migrate_slug_stragglers.py``.

Builds a minimal tmp vault that mirrors the real slug-cluster shape:
  - 2 word-slug compounds cross-referencing via antonyms + connections.to
  - 1 sentence-slug referencing both word slugs via word_refs
  - 1 group whose members[] contains the sentence slug
  - A hanzi-only antonyms[] entry (the "trap guard")
  - A groups[] containing the group slug (must NOT be rewritten)

Then runs the migration and verifies:
  1. Files renamed to typed ids; type flipped to "compound".
  2. All references rewritten; no old slug anywhere in the tmp vault.
  3. Hanzi and groups values untouched (the naive-recursion trap guard).
  4. Counter file updated.
  5. Idempotency: second run changes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.migrate_slug_stragglers import migrate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(parent: Path, stem: str, data: dict) -> Path:
    path = parent / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_minimal_vault(root: Path) -> dict[str, Path]:
    """Write the 4-unit cluster and return {slug: path} for the 3 slugs."""
    units = {
        "words": {
            "kèqi": {
                "id": "kèqi",
                "type": "word",
                "name": "客气",
                "properties": {
                    "hanzi": "客气",
                    "pinyin": "kèqi",
                    "english": "",
                    "meaning": "",
                    "groups": [],
                    "antonyms": ["suíbiàn", "随便"],  # one is slug, one is bare hanzi
                },
                "connections": [
                    {"to": "k-qi-sh-nme", "kind": "lexical", "score": 1.0},
                    {"to": "suíbiàn", "kind": "opposite", "score": 1.0},
                ],
                "created": "2026-07-09",
                "updated": "2026-07-09",
                "author_confirmed": True,
            },
            "suíbiàn": {
                "id": "suíbiàn",
                "type": "word",
                "name": "随便",
                "properties": {
                    "hanzi": "随便",
                    "pinyin": "suíbiàn",
                    "english": "",
                    "meaning": "",
                    "groups": [],
                    "antonyms": ["kèqi"],
                },
                "connections": [
                    {"to": "kèqi", "kind": "opposite", "score": 1.0},
                ],
                "created": "2026-07-09",
                "updated": "2026-07-09",
                "author_confirmed": True,
            },
        },
        "sentences": {
            "k-qi-sh-nme": {
                "id": "k-qi-sh-nme",
                "type": "sentence",
                "name": "客气什么",
                "properties": {
                    "hanzi": "客气什么",
                    "pinyin": "kèqi shénme",
                    "english": "What, so polite?",
                    "meaning": "",
                    "words": ["客气", "什么"],
                    "word_refs": ["kèqi", "shénme"],
                    "groups": ["social-interaction"],
                    "antonyms": ["随便", "无礼"],  # bare hanzi only — must NOT be rewritten
                },
                "connections": [],
                "created": "2026-07-09",
                "updated": "2026-07-09",
                "author_confirmed": True,
            },
        },
        "groups": {
            "social-interaction": {
                "id": "social-interaction",
                "type": "group",
                "name": "social-interaction",
                "properties": {
                    "display_name": "Social Interaction",
                    "description": "",
                    "members": ["k-qi-sh-nme"],
                },
                "connections": [],
                "created": "2026-07-09",
                "updated": "2026-07-09",
                "author_confirmed": True,
            },
        },
    }

    paths = {}
    for plural, unit_dict in units.items():
        for slug, data in unit_dict.items():
            p = _write_json(root / "units" / plural, slug, data)
            paths[slug] = p

    # Write initial counters.
    _write_json(
        root / "_meta",
        "id_counters",
        {"W": 22, "C": 12, "S": 13, "G": 12},
    )

    return paths


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_migration_renames_files_and_flips_type(tmp_path: Path) -> None:
    """Files are renamed to typed ids; compound words flip type from word→compound."""
    _build_minimal_vault(tmp_path)

    result = migrate(str(tmp_path), dry_run=False)
    assert result["renamed"] == 3

    words_dir = tmp_path / "units" / "words"
    sentences_dir = tmp_path / "units" / "sentences"

    # Compounds renamed.
    for slug, new_id in [("kèqi", "C13"), ("suíbiàn", "C15")]:
        new_path = words_dir / f"{new_id}.json"
        assert new_path.exists(), f"{new_id} should exist"
        assert not (words_dir / f"{slug}.json").exists(), f"old {slug} should be gone"

    # Sentence renamed.
    assert (sentences_dir / "S14.json").exists()
    assert not (sentences_dir / "k-qi-sh-nme.json").exists()

    # Type flipped for compounds.
    c13 = _read_json(words_dir / "C13.json")
    assert c13["type"] == "compound", "kèqi → C13 must be compound"
    c15 = _read_json(words_dir / "C15.json")
    assert c15["type"] == "compound", "suíbiàn → C15 must be compound"


def test_references_rewritten_no_old_slugs_remain(tmp_path: Path) -> None:
    """All old slug strings are replaced in reference fields.

    Note: old slugs may still appear in content fields like pinyin
    (e.g. "kèqi" in pinyin: "kèqi shénme") — those are NOT references
    and must NOT be rewritten (the naive-recursion trap).
    """
    _build_minimal_vault(tmp_path)
    migrate(str(tmp_path), dry_run=False)

    # Check that id fields no longer contain old slugs.
    for json_path in tmp_path.rglob("*.json"):
        data = _read_json(json_path)
        assert data.get("id") not in {"k-qi-sh-nme", "kèqi", "suíbiàn"}, (
            f"old slug still in id field of {json_path}"
        )

    # Spot-check: C15 (suíbiàn) antonyms now references C13, not the raw slug.
    c15 = _read_json(tmp_path / "units" / "words" / "C15.json")
    assert "kèqi" not in c15["properties"]["antonyms"]
    assert "C13" in c15["properties"]["antonyms"]

    # C13 (kèqi) connections.to updated.
    c13 = _read_json(tmp_path / "units" / "words" / "C13.json")
    to_targets = {conn["to"] for conn in c13["connections"]}
    assert "S14" in to_targets
    assert "k-qi-sh-nme" not in to_targets


def test_hanzi_and_groups_fields_untouched(tmp_path: Path) -> None:
    """Hanzi values and groups[] are NOT rewritten — the naive-recursion trap guard."""
    _build_minimal_vault(tmp_path)
    migrate(str(tmp_path), dry_run=False)

    # Sentence: antonyms[] are bare hanzi — must still be ["随便", "无礼"]
    s14 = _read_json(tmp_path / "units" / "sentences" / "S14.json")
    assert s14["properties"]["antonyms"] == ["随便", "无礼"], (
        "bare hanzi antonyms must not be rewritten"
    )

    # Sentence: groups[] still ["social-interaction"]
    assert s14["properties"]["groups"] == ["social-interaction"], (
        "groups[] must not be rewritten"
    )

    # Sentence: hanzi/pinyin untouched
    assert s14["properties"]["hanzi"] == "客气什么"
    assert s14["properties"]["pinyin"] == "kèqi shénme"

    # Compound: hanzi untouched
    c13 = _read_json(tmp_path / "units" / "words" / "C13.json")
    assert c13["properties"]["hanzi"] == "客气"


def test_counter_file_updated(tmp_path: Path) -> None:
    """id_counters.json reflects the new max assigned ids."""
    _build_minimal_vault(tmp_path)
    migrate(str(tmp_path), dry_run=False)

    counters = _read_json(tmp_path / "_meta" / "id_counters.json")
    assert counters["C"] == 16, "C counter should be 16"
    assert counters["S"] == 14, "S counter should be 14"
    assert counters["W"] == 22, "W counter unchanged"
    assert counters["G"] == 12, "G counter unchanged"


def test_idempotency_second_run_is_noop(tmp_path: Path) -> None:
    """Running the migration twice: second run changes nothing."""
    _build_minimal_vault(tmp_path)
    r1 = migrate(str(tmp_path), dry_run=False)
    assert r1["renamed"] == 3

    # Capture state after first run.
    c13_path = tmp_path / "units" / "words" / "C13.json"
    s14_path = tmp_path / "units" / "sentences" / "S14.json"
    counters_after = _read_json(tmp_path / "_meta" / "id_counters.json")

    c13_mtime = c13_path.stat().st_mtime
    s14_mtime = s14_path.stat().st_mtime
    counters_mtime = (tmp_path / "_meta" / "id_counters.json").stat().st_mtime

    # Second run.
    r2 = migrate(str(tmp_path), dry_run=False)
    assert r2["renamed"] == 0
    assert r2["rewritten"] == 0

    # No files changed.
    assert c13_path.stat().st_mtime == c13_mtime
    assert s14_path.stat().st_mtime == s14_mtime
    assert (tmp_path / "_meta" / "id_counters.json").stat().st_mtime == counters_mtime

    # State unchanged.
    assert _read_json(c13_path)["id"] == "C13"
    assert _read_json(s14_path)["id"] == "S14"
    assert _read_json(tmp_path / "_meta" / "id_counters.json") == counters_after


def test_social_interaction_members_updated(tmp_path: Path) -> None:
    """The group's members[] is rewritten from k-qi-sh-nme → S14."""
    _build_minimal_vault(tmp_path)
    migrate(str(tmp_path), dry_run=False)

    group = _read_json(tmp_path / "units" / "groups" / "social-interaction.json")
    assert group["properties"]["members"] == ["S14"], (
        "group members[] should reference S14, not the old slug"
    )


def test_dry_run_does_not_modify_vault(tmp_path: Path) -> None:
    """--dry-run returns expected counts but leaves vault untouched."""
    _build_minimal_vault(tmp_path)

    result = migrate(str(tmp_path), dry_run=True)
    assert result["renamed"] == 3

    # Files still have old slugs.
    assert (tmp_path / "units" / "sentences" / "k-qi-sh-nme.json").exists()
    assert (tmp_path / "units" / "words" / "kèqi.json").exists()

    # Counters not updated.
    counters = _read_json(tmp_path / "_meta" / "id_counters.json")
    assert counters["C"] == 12
    assert counters["S"] == 13
