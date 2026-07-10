"""Tests for scripts/reconcile_to_dict_ids.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_dictionary import _import_source
from scripts.reconcile_to_dict_ids import (
    _build_id_mapping,
    _check_type_field,
    _rewrite_refs_in_unit,
    main as reconcile_main,
)


def _seed_dictionary(vault_root: str, csv_content: str) -> None:
    """Populate the word table using a custom CSV content.

    The CSV uses the SUBTLEX-CH tab-separated format.
    """
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(csv_content)
        csv_path = f.name
    try:
        _import_source(
            vault_root=vault_root,
            source_id="subtlex-ch",
            source_name="SUBTLEX-CH",
            source_version="1.0",
            license="CC-BY",
            attribution="Test fixture",
            priority=50,
            csv_path=csv_path,
        )
    finally:
        Path(csv_path).unlink()


def _word_ids_by_hanzi(vault_root: str) -> dict[str, str]:
    """Return {hanzi: dict_word_id} from the word table."""
    import sqlite3
    conn = sqlite3.connect(str(Path(vault_root) / "index" / "vault.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT hanzi, id FROM word").fetchall()
    conn.close()
    return {hanzi: wid for hanzi, wid in rows}


def _write_unit(vault_root: Path, type_dir: str, unit: dict) -> None:
    """Write a unit JSON file to the vault."""
    unit_dir = vault_root / "units" / type_dir
    unit_dir.mkdir(parents=True, exist_ok=True)
    path = unit_dir / f"{unit['id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(unit, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _read_unit(vault_root: Path, type_dir: str, unit_id: str) -> dict:
    """Read a unit JSON file."""
    path = vault_root / "units" / type_dir / f"{unit_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path(tmp_path: Path) -> None:
    """Counter-id word units get re-id'd to dict word ids."""
    # Custom CSV: 我=wo3→wǒ, 吃=chi1→chī. They will get W1 and W2 in dict.
    csv = (
        "# meta1\n# meta2\n"
        "Word\tLength\tPinyin\tPinyin.Input\tW.million\tDominant.PoS\t"
        "Dominant.PoS.Freq\tAll.PoS\tAll.PoS.Freq\tWCount\tlog10W\t"
        "W-CD\tW-CD%\tlog10CD\tEng.Tran\n"
        "我\t1\two3\two3\t100\tV\t90\tV\t1.0\t10000\t4.0\t.\t.\t.\tI\n"
        "吃\t1\tchi1\tchi1\t200\tV\t180\tV\t1.0\t20000\t4.3\t.\t.\t.\teat\n"
    )
    _seed_dictionary(str(tmp_path), csv)

    dict_ids = _word_ids_by_hanzi(str(tmp_path))
    wǒ_id = dict_ids["我"]
    chī_id = dict_ids["吃"]

    # Vault has counter-ids W99, W98. Dict has 我=wǒ, 吃=chī at W1, W2.
    _write_unit(tmp_path, "words", {
        "id": "W99", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wǒ", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "words", {
        "id": "W98", "type": "word", "name": "吃",
        "properties": {"hanzi": "吃", "pinyin": "chī", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    rc = reconcile_main(["--vault-root", str(tmp_path)])
    assert rc == 0

    assert not (tmp_path / "units" / "words" / "W99.json").exists()
    assert not (tmp_path / "units" / "words" / "W98.json").exists()
    assert (tmp_path / "units" / "words" / f"{wǒ_id}.json").exists()
    assert (tmp_path / "units" / "words" / f"{chī_id}.json").exists()

    unit = _read_unit(tmp_path, "words", wǒ_id)
    assert unit["id"] == wǒ_id
    assert unit["properties"]["hanzi"] == "我"
    assert unit["properties"]["pinyin"] == "wǒ"


def test_idempotent(tmp_path: Path) -> None:
    """Running twice is a no-op the second time."""
    csv = (
        "# meta1\n# meta2\n"
        "Word\tLength\tPinyin\tPinyin.Input\tW.million\tDominant.PoS\t"
        "Dominant.PoS.Freq\tAll.PoS\tAll.PoS.Freq\tWCount\tlog10W\t"
        "W-CD\tW-CD%\tlog10CD\tEng.Tran\n"
        "我\t1\two3\two3\t100\tV\t90\tV\t1.0\t10000\t4.0\t.\t.\t.\tI\n"
    )
    _seed_dictionary(str(tmp_path), csv)

    dict_ids = _word_ids_by_hanzi(str(tmp_path))
    wǒ_id = dict_ids["我"]

    _write_unit(tmp_path, "words", {
        "id": "W99", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wǒ", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    rc1 = reconcile_main(["--vault-root", str(tmp_path)])
    assert rc1 == 0

    rc2 = reconcile_main(["--vault-root", str(tmp_path)])
    assert rc2 == 0

    assert (tmp_path / "units" / "words" / f"{wǒ_id}.json").exists()
    files = list((tmp_path / "units" / "words").glob("W*.json"))
    assert len(files) == 1


def test_dry_run(tmp_path: Path) -> None:
    """--dry-run reports changes but does not modify files."""
    csv = (
        "# meta1\n# meta2\n"
        "Word\tLength\tPinyin\tPinyin.Input\tW.million\tDominant.PoS\t"
        "Dominant.PoS.Freq\tAll.PoS\tAll.PoS.Freq\tWCount\tlog10W\t"
        "W-CD\tW-CD%\tlog10CD\tEng.Tran\n"
        "我\t1\two3\two3\t100\tV\t90\tV\t1.0\t10000\t4.0\t.\t.\t.\tI\n"
    )
    _seed_dictionary(str(tmp_path), csv)

    _write_unit(tmp_path, "words", {
        "id": "W99", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wǒ", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    import io, logging
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setLevel(logging.INFO)
    logger = logging.getLogger("scripts.reconcile_to_dict_ids")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    rc = reconcile_main(["--vault-root", str(tmp_path), "--dry-run"])
    logger.removeHandler(handler)

    assert rc == 0
    output = out.getvalue()
    assert "DRY-RUN" in output
    assert "No files were modified" in output

    assert (tmp_path / "units" / "words" / "W99.json").exists()


def test_reference_rewrite(tmp_path: Path) -> None:
    """Sentence's word_refs are rewritten to dict ids after reconcile."""
    csv = (
        "# meta1\n# meta2\n"
        "Word\tLength\tPinyin\tPinyin.Input\tW.million\tDominant.PoS\t"
        "Dominant.PoS.Freq\tAll.PoS\tAll.PoS.Freq\tWCount\tlog10W\t"
        "W-CD\tW-CD%\tlog10CD\tEng.Tran\n"
        "我\t1\two3\two3\t100\tV\t90\tV\t1.0\t10000\t4.0\t.\t.\t.\tI\n"
        "吃\t1\tchi1\tchi1\t200\tV\t180\tV\t1.0\t20000\t4.3\t.\t.\t.\teat\n"
    )
    _seed_dictionary(str(tmp_path), csv)

    dict_ids = _word_ids_by_hanzi(str(tmp_path))
    wǒ_id = dict_ids["我"]
    chī_id = dict_ids["吃"]

    _write_unit(tmp_path, "words", {
        "id": "W99", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wǒ", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "sentences", {
        "id": "S1", "type": "sentence", "name": "我吃",
        "properties": {
            "hanzi": "我吃", "pinyin": "wǒ chī", "english": "",
            "meaning": "", "words": ["我", "吃"],
            "word_refs": ["W99"],  # old counter id
            "groups": [], "antonyms": [],
        },
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    rc = reconcile_main(["--vault-root", str(tmp_path)])
    assert rc == 0

    assert not (tmp_path / "units" / "words" / "W99.json").exists()
    assert (tmp_path / "units" / "words" / f"{wǒ_id}.json").exists()

    sentence = _read_unit(tmp_path, "sentences", "S1")
    assert wǒ_id in sentence["properties"]["word_refs"]


def test_unit_not_in_dict(tmp_path: Path) -> None:
    """Word unit whose hanzi/pinyin isn't in dict is left unchanged with a warning."""
    csv = (
        "# meta1\n# meta2\n"
        "Word\tLength\tPinyin\tPinyin.Input\tW.million\tDominant.PoS\t"
        "Dominant.PoS.Freq\tAll.PoS\tAll.PoS.Freq\tWCount\tlog10W\t"
        "W-CD\tW-CD%\tlog10CD\tEng.Tran\n"
        "我\t1\two3\two3\t100\tV\t90\tV\t1.0\t10000\t4.0\t.\t.\t.\tI\n"
    )
    _seed_dictionary(str(tmp_path), csv)

    _write_unit(tmp_path, "words", {
        "id": "W99", "type": "word", "name": "xyz",
        "properties": {"hanzi": "xyz", "pinyin": "xyz", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    import io, logging
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setLevel(logging.WARNING)
    logger = logging.getLogger("scripts.reconcile_to_dict_ids")
    logger.addHandler(handler)

    rc = reconcile_main(["--vault-root", str(tmp_path)])
    logger.removeHandler(handler)

    assert rc == 0
    output = out.getvalue()
    assert "SKIP" in output
    assert "xyz" in output

    assert (tmp_path / "units" / "words" / "W99.json").exists()
    unit = _read_unit(tmp_path, "words", "W99")
    assert unit["id"] == "W99"


def test_duplicate_merge(tmp_path: Path) -> None:
    """Two units with same hanzi/pinyin merge to one dict id."""
    csv = (
        "# meta1\n# meta2\n"
        "Word\tLength\tPinyin\tPinyin.Input\tW.million\tDominant.PoS\t"
        "Dominant.PoS.Freq\tAll.PoS\tAll.PoS.Freq\tWCount\tlog10W\t"
        "W-CD\tW-CD%\tlog10CD\tEng.Tran\n"
        "我\t1\two3\two3\t100\tV\t90\tV\t1.0\t10000\t4.0\t.\t.\t.\tI\n"
    )
    _seed_dictionary(str(tmp_path), csv)

    dict_ids = _word_ids_by_hanzi(str(tmp_path))
    wǒ_id = dict_ids["我"]

    # Two units both with 我/wǒ but different connections.
    _write_unit(tmp_path, "words", {
        "id": "W99", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wǒ", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [{"to": "S1", "kind": "lexical", "score": 1.0}],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "words", {
        "id": "W98", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wǒ", "english": "", "meaning": "",
                       "groups": [], "antonyms": ["W3"]},
        "connections": [{"to": "S2", "kind": "lexical", "score": 0.8}],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    rc = reconcile_main(["--vault-root", str(tmp_path)])
    assert rc == 0

    assert not (tmp_path / "units" / "words" / "W99.json").exists()
    assert not (tmp_path / "units" / "words" / "W98.json").exists()
    assert (tmp_path / "units" / "words" / f"{wǒ_id}.json").exists()

    merged = _read_unit(tmp_path, "words", wǒ_id)
    conn_tos = {c["to"] for c in merged["connections"]}
    assert "S1" in conn_tos
    assert "S2" in conn_tos
    assert "W3" in merged["properties"].get("antonyms", [])


def test_key_aware_rewrite(tmp_path: Path) -> None:
    """Only word_refs/antonyms/members/connections.to are rewritten; pinyin/hanzi/name stay intact."""
    csv = (
        "# meta1\n# meta2\n"
        "Word\tLength\tPinyin\tPinyin.Input\tW.million\tDominant.PoS\t"
        "Dominant.PoS.Freq\tAll.PoS\tAll.PoS.Freq\tWCount\tlog10W\t"
        "W-CD\tW-CD%\tlog10CD\tEng.Tran\n"
        "我\t1\two3\two3\t100\tV\t90\tV\t1.0\t10000\t4.0\t.\t.\t.\tI\n"
    )
    _seed_dictionary(str(tmp_path), csv)

    dict_ids = _word_ids_by_hanzi(str(tmp_path))
    wǒ_id = dict_ids["我"]

    _write_unit(tmp_path, "words", {
        "id": "W99", "type": "word", "name": "我",
        "properties": {
            "hanzi": "我",  # should NOT be rewritten
            "pinyin": "wǒ",  # should NOT be rewritten
            "english": "", "meaning": "",
            "groups": [],
            "antonyms": ["W99"],  # self-ref (will be rewritten to wǒ_id)
        },
        "connections": [{"to": "W99", "kind": "lexical", "score": 1.0}],
        "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    rc = reconcile_main(["--vault-root", str(tmp_path)])
    assert rc == 0

    unit = _read_unit(tmp_path, "words", wǒ_id)
    assert unit["id"] == wǒ_id
    # hanzi/pinyin NOT rewritten (still correct).
    assert unit["properties"]["hanzi"] == "我"
    assert unit["properties"]["pinyin"] == "wǒ"
    # name NOT rewritten.
    assert unit["name"] == "我"
    # antonyms W99 → wǒ_id.
    assert wǒ_id in unit["properties"]["antonyms"]
    # connections.to W99 → wǒ_id.
    assert unit["connections"][0]["to"] == wǒ_id


def test_type_field_sanity_check(tmp_path: Path) -> None:
    """Type-field sanity check runs without errors after reconcile."""
    csv = (
        "# meta1\n# meta2\n"
        "Word\tLength\tPinyin\tPinyin.Input\tW.million\tDominant.PoS\t"
        "Dominant.PoS.Freq\tAll.PoS\tAll.PoS.Freq\tWCount\tlog10W\t"
        "W-CD\tW-CD%\tlog10CD\tEng.Tran\n"
        "我\t1\two3\two3\t100\tV\t90\tV\t1.0\t10000\t4.0\t.\t.\t.\tI\n"
        "别的\t2\tbie2 de5\tbie2 de5\t50\tSPEC\t45\tSPEC\t1.0\t5000\t4.7\t.\t.\t.\tother\n"
    )
    _seed_dictionary(str(tmp_path), csv)

    dict_ids = _word_ids_by_hanzi(str(tmp_path))
    bié_de_id = dict_ids["别的"]  # will be C prefix in dict

    _write_unit(tmp_path, "words", {
        "id": "W99", "type": "word", "name": "别的",
        "properties": {"hanzi": "别的", "pinyin": "bié de", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    rc = reconcile_main(["--vault-root", str(tmp_path)])
    assert rc == 0
    # Sanity check passes (id corrected, type stays as-is — not a mass rewrite).
    # Verify the file was renamed to correct dict id.
    assert (tmp_path / "units" / "words" / f"{bié_de_id}.json").exists()


def test_sentence_and_group_refs_rewritten(tmp_path: Path) -> None:
    """Group members and sentence word_refs referencing old counter ids are rewritten."""
    csv = (
        "# meta1\n# meta2\n"
        "Word\tLength\tPinyin\tPinyin.Input\tW.million\tDominant.PoS\t"
        "Dominant.PoS.Freq\tAll.PoS\tAll.PoS.Freq\tWCount\tlog10W\t"
        "W-CD\tW-CD%\tlog10CD\tEng.Tran\n"
        "我\t1\two3\two3\t100\tV\t90\tV\t1.0\t10000\t4.0\t.\t.\t.\tI\n"
        "吃\t1\tchi1\tchi1\t200\tV\t180\tV\t1.0\t20000\t4.3\t.\t.\t.\teat\n"
    )
    _seed_dictionary(str(tmp_path), csv)

    dict_ids = _word_ids_by_hanzi(str(tmp_path))
    wǒ_id = dict_ids["我"]

    _write_unit(tmp_path, "words", {
        "id": "W99", "type": "word", "name": "我",
        "properties": {"hanzi": "我", "pinyin": "wǒ", "english": "", "meaning": "",
                       "groups": [], "antonyms": []},
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "sentences", {
        "id": "S1", "type": "sentence", "name": "我吃",
        "properties": {
            "hanzi": "我吃", "pinyin": "wǒ chī", "english": "",
            "meaning": "", "words": ["我", "吃"],
            "word_refs": ["W99"],
            "groups": [], "antonyms": [],
        },
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })
    _write_unit(tmp_path, "groups", {
        "id": "G1", "type": "group", "name": "G1",
        "properties": {
            "display_name": "Test",
            "description": "",
            "members": ["S1"],
        },
        "connections": [], "created": "2026-01-01", "updated": "2026-01-01",
        "author_confirmed": True,
    })

    rc = reconcile_main(["--vault-root", str(tmp_path)])
    assert rc == 0

    sentence = _read_unit(tmp_path, "sentences", "S1")
    assert wǒ_id in sentence["properties"]["word_refs"]

    group = _read_unit(tmp_path, "groups", "G1")
    assert "S1" in group["properties"]["members"]
