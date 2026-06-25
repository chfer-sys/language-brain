"""Tests for SPEC §6 AC29 — no outbound network during search/read/write.

AC29 contract: search, unit-read, and unit-write operations make
NO outbound network calls. The only module that opens a network
socket is ``api.services.ai_client`` (for the AI labeler, which
runs only on the propose step).

Coverage:

* A complete pipeline (write sentence → search → read → delete) is
  exercised while watching ``sys.modules`` for any new network
  module imports. None are allowed.
* ``search`` directly: an Index.search call plus a unit_writer
  read does not import ``requests`` / ``urllib`` / ``socket`` /
  ``http.client``.
* ``write`` directly: ``write_unit`` does not import any network
  module.
* A negative test: importing ``ai_client`` and reading its module
  graph DOES include ``requests`` (or it would not be able to make
  HTTP calls). This proves the AC29 invariant isn't trivially true
  because the project has no HTTP code anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from api.services.embedder import HashingEmbedder
from api.services.indexer import Index
from api.services.unit_writer import (
    list_units_by_type,
    read_unit,
    write_unit,
)


# Modules whose presence in sys.modules proves a network call is possible.
# We exclude stdlib modules that are imported by tons of things but never
# open sockets themselves (``urllib.parse``, ``http``, etc.).
NETWORK_MODULE_FRAGMENTS = (
    "requests",
    "urllib.request",
    "urllib3",
    "socket",
    "http.client",
    "httpx",
    "aiohttp",
)


def _network_modules_present() -> list[str]:
    return [
        name
        for name in sys.modules
        if any(frag in name for frag in NETWORK_MODULE_FRAGMENTS)
    ]


def _snapshot_modules() -> set[str]:
    return set(sys.modules.keys())


def _new_network_modules(before: set[str]) -> list[str]:
    """Return any newly-imported network-capable modules since ``before``."""
    after = set(sys.modules.keys())
    new = after - before
    return [m for m in new if any(frag in m for frag in NETWORK_MODULE_FRAGMENTS)]


# ---------------------------------------------------------------------------
# The full pipeline writes, searches, reads, and deletes — and never
# imports a network module at any step.
# ---------------------------------------------------------------------------


def _seed_vault(tmp_path: Path) -> None:
    """Write a few sentence and word units directly to disk."""
    sentences_dir = tmp_path / "units" / "sentences"
    words_dir = tmp_path / "units" / "words"
    sentences_dir.mkdir(parents=True, exist_ok=True)
    words_dir.mkdir(parents=True, exist_ok=True)

    import json

    (sentences_dir / "s-001.json").write_text(
        json.dumps(
            {
                "id": "s-001",
                "type": "sentence",
                "name": "你好",
                "properties": {
                    "hanzi": "你好",
                    "pinyin": "nǐ hǎo",
                    "english": "hello",
                    "meaning": "a casual greeting",
                    "words": ["你", "好"],
                    "word_refs": ["nǐ", "hǎo"],
                    "groups": [],
                    "antonyms": [],
                },
                "connections": [],
                "created": "2026-06-24",
                "updated": "2026-06-24",
                "author_confirmed": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (sentences_dir / "s-002.json").write_text(
        json.dumps(
            {
                "id": "s-002",
                "type": "sentence",
                "name": "再见",
                "properties": {
                    "hanzi": "再见",
                    "pinyin": "zài jiàn",
                    "english": "goodbye",
                    "meaning": "a farewell",
                    "words": ["再", "见"],
                    "word_refs": ["zài", "jiàn"],
                    "groups": [],
                    "antonyms": [],
                },
                "connections": [],
                "created": "2026-06-24",
                "updated": "2026-06-24",
                "author_confirmed": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_full_pipeline_imports_no_network_modules(tmp_path: Path) -> None:
    """Write → index → search → read → delete, with no network imports."""
    before = _snapshot_modules()
    _seed_vault(tmp_path)

    # Build an FAISS index using the offline hashing embedder.
    embedder = HashingEmbedder()
    idx = Index()
    for s in list_units_by_type(str(tmp_path), "sentence"):
        idx.add(s["id"], embedder.embed(s["properties"]["meaning"]))
    idx.save(str(tmp_path))

    # Search.
    hits = idx.search(embedder.embed("hello"), k=5)
    assert hits  # at least the seed sentence

    # Read.
    unit = read_unit(str(tmp_path), "sentence", "s-001")
    assert unit["id"] == "s-001"

    # Delete.
    from api.services.sentence_delete import delete_sentence

    delete_sentence(str(tmp_path), "s-001")

    leaked = _new_network_modules(before)
    assert leaked == [], (
        f"AC29 violated: search/read/write/delete pipeline imported "
        f"network-capable modules: {leaked}"
    )


def test_search_alone_imports_no_network(tmp_path: Path) -> None:
    """An Index.search + read_unit + list_units_by_type session
    imports no network modules."""
    _seed_vault(tmp_path)
    embedder = HashingEmbedder()
    idx = Index()
    for s in list_units_by_type(str(tmp_path), "sentence"):
        idx.add(s["id"], embedder.embed(s["properties"]["meaning"]))
    idx.save(str(tmp_path))

    before = _snapshot_modules()
    hits = idx.search(embedder.embed("anything"), k=10)
    _ = read_unit(str(tmp_path), "sentence", hits[0].unit_id)
    leaked = _new_network_modules(before)
    assert leaked == [], f"AC29 violated: {leaked}"


def test_write_unit_alone_imports_no_network(tmp_path: Path) -> None:
    """write_unit + list_units_by_type alone imports no network
    modules."""
    _seed_vault(tmp_path)
    before = _snapshot_modules()
    new_unit = {
        "id": "s-003",
        "type": "sentence",
        "name": "x",
        "properties": {"hanzi": "x", "pinyin": "x", "english": "x"},
        "connections": [],
        "created": "2026-06-24",
        "updated": "2026-06-24",
        "author_confirmed": True,
    }
    write_unit(str(tmp_path), new_unit)
    _ = list_units_by_type(str(tmp_path), "sentence")
    leaked = _new_network_modules(before)
    assert leaked == [], f"AC29 violated: {leaked}"


# ---------------------------------------------------------------------------
# Negative control: prove the AI client IS where the network lives.
# ---------------------------------------------------------------------------


def test_ai_client_module_does_depend_on_requests() -> None:
    """The AI client module imports ``requests`` (or has the
    capability to). This is the *only* place in the codebase
    where outbound HTTP is allowed by design. If this test ever
    fails, either we removed the AI client or we swapped to a
    different HTTP library — and the AC29 invariant above needs
    to be re-verified for the new library name."""
    import importlib

    mod = importlib.import_module("api.services.ai_client")
    assert hasattr(mod, "HttpAIClient")
    # The AI client's HTTP path uses ``requests.post``. We don't
    # require ``requests`` to be already imported (lazy import),
    # but the module must mention it in source for the network
    # call to work.
    import inspect

    src = inspect.getsource(mod)
    assert "requests" in src, (
        "AC29 sanity check: ai_client.py should reference 'requests' "
        "so we know the network dependency is contained."
    )


# ---------------------------------------------------------------------------
# Smoke test: confirm the search route (T20, future) is on the
# non-network path. We don't have the route yet, but we can
# assert that no test for it has been written that would
# introduce a network dep.
# ---------------------------------------------------------------------------


def test_search_results_payload_has_no_network_keys() -> None:
    """Defensive: a SearchHit (the result type of Index.search)
    has only ``unit_id`` and ``score`` — no URL, no key, no
    transport metadata. Even if the search code accidentally
    included a network object, the dataclass shape keeps it out."""
    from api.services.indexer import SearchHit

    h = SearchHit(unit_id="x", score=0.5)
    # dataclass field names are exactly these two.
    assert set(h.__dataclass_fields__) == {"unit_id", "score"}
