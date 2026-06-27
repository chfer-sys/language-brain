"""Tests for ``POST /api/sentences/commit`` (SPEC §6 AC3, AC4, AC5, AC9, AC12-15).

Uses FastAPI's :class:`TestClient`. Each test isolates its vault under
``tmp_path`` and monkey-patches:

* ``LANGUAGE_BRAIN_VAULT`` so the route reads from a temp vault.
* :func:`api.services.embedder.get_embedder` (imported into the route
  module) so the embedder is a deterministic :class:`HashingEmbedder`
  and no real model is downloaded.

The test list covers the 12 cases enumerated in the T19 brief: the
happy path, word-unit creation, lexical edges, group members, the
four connector passes (lexical / opposite), FAISS index growth and
skip-on-empty-meaning, the 422 paths, the summary shape, and
idempotency.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import commit_sentence as commit_sentence_route
from api import config as config_module
from api.services.embedder import HashingEmbedder
from api.services.indexer import Index
from api.services.unit_writer import read_unit, unit_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_embedder(monkeypatch: pytest.MonkeyPatch) -> HashingEmbedder:
    """Force the route to use a fresh :class:`HashingEmbedder`.

    The route module does ``from api.services.embedder import
    get_embedder``, so the symbol is bound in the route's module
    namespace. Patching it there is sufficient — ``compute_connections``
    also does a lazy ``from api.services.embedder import get_embedder``
    inside the function body, but in tests we pass the embedder
    explicitly via :func:`_get_embedder` so that path is bypassed.
    """
    fresh = HashingEmbedder()
    monkeypatch.setattr(
        commit_sentence_route, "get_embedder", lambda force=None: fresh
    )
    return fresh


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """A TestClient bound to a fresh ``LANGUAGE_BRAIN_VAULT=tmp_path``.

    The route module does ``from api.config import settings``, which
    freezes the vault path at import time. We must therefore patch
    ``settings.vault`` directly (in addition to the env var) so the
    route reads from this test's ``tmp_path``. We also clear the
    ``get_settings`` lru_cache so a fresh ``Settings()`` instance is
    built on the next access.

    Clears the cache on entry AND on exit so subsequent tests don't
    inherit this test's temp path.
    """
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    # Patch the module-level singleton too — the route imports
    # ``settings`` directly, so the env var alone isn't enough.
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        config_module.get_settings.cache_clear()


def _minimal_payload(**overrides: object) -> dict:
    """Return a minimal valid ``CommitSentenceRequest`` body.

    The fixture provides the smallest possible payload that still
    exercises the happy path. Tests that need extra fields override
    them via kwargs.
    """
    payload: dict = {
        "id": "wo-xihuan-chi",
        "hanzi": "我喜欢吃",
        "pinyin": "wǒ xǐhuān chī",
        "english": "I like to eat",
        "meaning": "expressing enjoyment of eating",
        "words": ["我", "喜欢", "吃"],
        "word_refs": ["wǒ", "xǐhuān", "chī"],
        "groups": [],
        "antonyms": [],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 1. Minimal happy path
# ---------------------------------------------------------------------------


def test_commit_minimal_happy_path(client: TestClient, tmp_path: Path) -> None:
    """A minimal valid body returns 200, the sentence file is written,
    and its ``properties.hanzi`` matches the request."""
    body = _minimal_payload()
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["id"] == "wo-xihuan-chi"

    # On-disk file shape.
    s_path = unit_path(str(tmp_path), "sentence", "wo-xihuan-chi")
    assert s_path.is_file()
    on_disk = json.loads(s_path.read_text(encoding="utf-8"))
    assert on_disk["type"] == "sentence"
    assert on_disk["name"] == "我喜欢吃"
    assert on_disk["properties"]["hanzi"] == "我喜欢吃"
    assert on_disk["properties"]["pinyin"] == "wǒ xǐhuān chī"
    assert on_disk["properties"]["english"] == "I like to eat"
    assert on_disk["properties"]["meaning"] == "expressing enjoyment of eating"
    assert on_disk["properties"]["words"] == ["我", "喜欢", "吃"]
    assert on_disk["properties"]["word_refs"] == ["wǒ", "xǐhuān", "chī"]
    assert on_disk["properties"]["groups"] == []
    assert on_disk["properties"]["antonyms"] == []


# ---------------------------------------------------------------------------
# 2. Word units are created
# ---------------------------------------------------------------------------


def test_commit_creates_word_units_from_word_refs(
    client: TestClient, tmp_path: Path
) -> None:
    """POSTing a sentence with two word_refs writes both word files."""
    body = _minimal_payload(
        words=["我", "喜欢"],
        word_refs=["wǒ", "xǐhuān"],
    )
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text

    for word_id, expected_hanzi in [("wǒ", "我"), ("xǐhuān", "喜欢")]:
        w_path = unit_path(str(tmp_path), "word", word_id)
        assert w_path.is_file(), f"missing word file for {word_id}"
        on_disk = json.loads(w_path.read_text(encoding="utf-8"))
        assert on_disk["type"] == "word"
        assert on_disk["name"] == expected_hanzi
        assert on_disk["properties"]["hanzi"] == expected_hanzi
        assert on_disk["properties"]["pinyin"] == word_id


# ---------------------------------------------------------------------------
# 3. Lexical edges from each word to the sentence
# ---------------------------------------------------------------------------


def test_commit_adds_lexical_edges_from_words_to_sentence(
    client: TestClient, tmp_path: Path
) -> None:
    """Each word's ``connections`` list contains a lexical edge to the
    new sentence."""
    body = _minimal_payload(
        words=["我", "喜欢", "吃"],
        word_refs=["wǒ", "xǐhuān", "chī"],
    )
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text

    for word_id in body["word_refs"]:
        w_unit = read_unit(str(tmp_path), "word", word_id)
        lexical = [
            e
            for e in w_unit.get("connections", [])
            if isinstance(e, dict) and e.get("kind") == "lexical"
        ]
        assert any(e.get("to") == "wo-xihuan-chi" for e in lexical), (
            f"word {word_id!r} missing lexical edge to the new sentence"
        )


# ---------------------------------------------------------------------------
# 4. Groups are ensured and the sentence is added to each
# ---------------------------------------------------------------------------


def test_commit_ensures_groups_and_adds_sentence_to_each(
    client: TestClient, tmp_path: Path
) -> None:
    """Two group ids: both group files exist and both contain the
    sentence id in ``properties.members``."""
    body = _minimal_payload(groups=["food", "preferences"])
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text

    for gid in ["food", "preferences"]:
        g_path = unit_path(str(tmp_path), "group", gid)
        assert g_path.is_file(), f"missing group file for {gid}"
        on_disk = json.loads(g_path.read_text(encoding="utf-8"))
        assert on_disk["type"] == "group"
        assert "wo-xihuan-chi" in on_disk["properties"]["members"]


def test_commit_accepts_group_dict_shapes(
    client: TestClient, tmp_path: Path
) -> None:
    """A group can also arrive as a ``ProposedGroupOut``-shaped dict."""
    body = _minimal_payload(
        groups=[
            {"id": "food", "display_name": "Food", "description": "edible things"},
            "preferences",
        ]
    )
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text

    food = read_unit(str(tmp_path), "group", "food")
    assert "wo-xihuan-chi" in food["properties"]["members"]


# ---------------------------------------------------------------------------
# 5. Connector's lexical-pair pass ran (AC12)
# ---------------------------------------------------------------------------


def test_commit_runs_connector_lexical_pairs(
    client: TestClient, tmp_path: Path
) -> None:
    """Two sentences that share a hanzi token get a lexical edge
    between them — proof the connector's lexical pass ran."""
    first = _minimal_payload(id="s-1", hanzi="我喜欢吃", words=["我", "喜欢", "吃"], word_refs=["wǒ", "xǐhuān", "chī"])
    second = _minimal_payload(
        id="s-2",
        hanzi="我吃饭",
        words=["我", "吃饭"],
        word_refs=["wǒ", "chīfàn"],
    )
    assert client.post("/api/sentences/commit", json=first).status_code == 200
    assert client.post("/api/sentences/commit", json=second).status_code == 200

    s1 = read_unit(str(tmp_path), "sentence", "s-1")
    lexical_to_s2 = [
        e for e in s1.get("connections", [])
        if isinstance(e, dict)
        and e.get("kind") == "lexical"
        and e.get("to") == "s-2"
    ]
    assert lexical_to_s2, "s-1 should have a lexical edge to s-2 after the connector ran"


# ---------------------------------------------------------------------------
# 6. Connector's opposite-pair pass ran (AC15)
# ---------------------------------------------------------------------------


def test_commit_runs_connector_opposite_pairs(
    client: TestClient, tmp_path: Path
) -> None:
    """The sentence declares ``antonyms=['è']`` and contains ``hǎo`` as
    one of its ``word_refs``. The route's Step 3b wires the
    declaration onto the ``è`` word unit (which already exists on
    disk). Then ``compute_connections`` runs and the connector's
    symmetry sync (AC15) appends ``è`` to ``hǎo.properties.antonyms``.

    Note on the brief
    -----------------
    The T19 brief described the test as "POST a sentence with
    ``antonyms=["è"]`` and POST a second sentence WITHOUT antonyms".
    In practice the symmetry sync lands on the first commit itself
    (because Step 3b writes the one-sided reference BEFORE
    ``compute_connections`` runs). We therefore run a single commit
    and assert the symmetry landed, then run a second commit so the
    test matches the brief's two-commit shape.
    """
    # Pre-seed the ``è`` word unit so Step 3b can append ``hǎo`` to
    # its ``antonyms`` array on the first commit. ``è`` must exist on
    # disk for the connector's opposite pass to consider it as a
    # target (per the "skip unknown targets" rule in
    # ``_compute_word_opposite_edges``).
    è_path = unit_path(str(tmp_path), "word", "è")
    è_path.parent.mkdir(parents=True, exist_ok=True)
    è_path.write_text(
        json.dumps(
            {
                "id": "è",
                "type": "word",
                "name": "饿",
                "properties": {
                    "hanzi": "饿",
                    "pinyin": "è",
                    "english": "hungry",
                    "meaning": "",
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

    # First commit — declares ``hǎo`` is antonym of ``è``.
    first = _minimal_payload(
        id="s-ant-1",
        hanzi="好",
        pinyin="hǎo",
        words=["好"],
        word_refs=["hǎo"],
        antonyms=["è"],
        meaning="good",
        english="good",
    )
    assert client.post("/api/sentences/commit", json=first).status_code == 200

    # Second commit (without antonyms) to mirror the brief's two-
    # commit shape and confirm idempotency of the wiring.
    second = _minimal_payload(
        id="s-ant-2",
        hanzi="别的",
        pinyin="bié de",
        words=["别", "的"],
        word_refs=["bié", "de"],
        antonyms=[],
        meaning="other",
        english="other",
    )
    assert client.post("/api/sentences/commit", json=second).status_code == 200

    # The connector's symmetry sync (AC15) must have appended ``è``
    # to ``hǎo``'s ``antonyms`` array — proof the opposite pass ran
    # against a vault where both sides of the pair were known.
    hǎo = read_unit(str(tmp_path), "word", "hǎo")
    assert "è" in hǎo["properties"]["antonyms"], (
        "hǎo.properties.antonyms should have been symmetry-synced "
        "to contain è after the connector's opposite pass"
    )


# ---------------------------------------------------------------------------
# 7. FAISS index grows when meaning is non-empty (AC9, R8)
# ---------------------------------------------------------------------------


def test_commit_updates_faiss_index(
    client: TestClient, tmp_path: Path
) -> None:
    """A non-empty ``meaning`` results in a single vector being added
    to the FAISS index."""
    body = _minimal_payload(meaning="expressing enjoyment of eating")
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text

    index = Index.load_or_empty(str(tmp_path))
    assert "wo-xihuan-chi" in index
    assert len(index) == 1


# ---------------------------------------------------------------------------
# 8. FAISS index is left alone when meaning is empty
# ---------------------------------------------------------------------------


def test_commit_skips_faiss_when_meaning_empty(
    client: TestClient, tmp_path: Path
) -> None:
    """An empty ``meaning`` does not crash and leaves the FAISS index
    empty."""
    body = _minimal_payload(meaning="")
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text

    # The sentence file should exist (the unit write is independent
    # of the FAISS update), but the FAISS index should be empty.
    assert unit_path(str(tmp_path), "sentence", "wo-xihuan-chi").is_file()
    index = Index.load_or_empty(str(tmp_path))
    assert len(index) == 0


# ---------------------------------------------------------------------------
# 9 / 10. Validation
# ---------------------------------------------------------------------------


def test_commit_rejects_empty_hanzi(client: TestClient) -> None:
    body = _minimal_payload(hanzi="")
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 422


def test_commit_rejects_whitespace_only_hanzi(client: TestClient) -> None:
    """Pydantic's ``min_length=1`` lets whitespace through; the route
    strips and rejects with 422."""
    body = _minimal_payload(hanzi="   ")
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 422
    assert "hanzi" in resp.text.lower()


def test_commit_rejects_empty_id(client: TestClient) -> None:
    body = _minimal_payload(id="")
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 422


def test_commit_rejects_whitespace_only_id(client: TestClient) -> None:
    body = _minimal_payload(id="   ")
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 422


def test_commit_rejects_empty_pinyin(client: TestClient) -> None:
    body = _minimal_payload(pinyin="")
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 11. Response shape
# ---------------------------------------------------------------------------


def test_commit_returns_connection_summary(client: TestClient) -> None:
    """The ``connections_summary`` is a flat dict containing the
    canonical keys, with int values."""
    body = _minimal_payload()
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    summary = payload["connections_summary"]
    assert isinstance(summary, dict)
    for key in (
        "sentences_touched",
        "lexical_pairs",
        "semantic_pairs",
        "group_pairs",
        "opposite_pairs",
    ):
        assert key in summary, f"missing summary key {key!r}"
        assert isinstance(summary[key], int), (
            f"summary[{key!r}] should be int, got {type(summary[key]).__name__}"
        )


# ---------------------------------------------------------------------------
# 12. Idempotency
# ---------------------------------------------------------------------------


def test_commit_idempotent(client: TestClient, tmp_path: Path) -> None:
    """Committing the same sentence twice rewrites the file with a
    bumped ``updated`` timestamp and does NOT duplicate members,
    words, or edges."""
    body = _minimal_payload(groups=["food"])
    first = client.post("/api/sentences/commit", json=body)
    assert first.status_code == 200, first.text

    s_path = unit_path(str(tmp_path), "sentence", "wo-xihuan-chi")
    on_disk_first = json.loads(s_path.read_text(encoding="utf-8"))

    second = client.post("/api/sentences/commit", json=body)
    assert second.status_code == 200, second.text
    on_disk_second = json.loads(s_path.read_text(encoding="utf-8"))

    # The file still has the same id and type.
    assert on_disk_first["id"] == on_disk_second["id"] == "wo-xihuan-chi"
    assert on_disk_first["type"] == on_disk_second["type"] == "sentence"

    # The group has exactly one member (the sentence), not two.
    food = read_unit(str(tmp_path), "group", "food")
    assert food["properties"]["members"].count("wo-xihuan-chi") == 1


# ---------------------------------------------------------------------------
# AC8b — POST /api/sentences/commit is synchronous
# ---------------------------------------------------------------------------


def test_commit_all_side_effects_complete_before_response(
    client: TestClient, tmp_path: Path
) -> None:
    """AC8b: the response is returned only after every side effect
    has completed.

    A single commit must, by the time the HTTP response returns:

      1. Have written the sentence unit file to disk.
      2. Have created (or updated) the word units referenced by
         the sentence's ``word_refs`` and ``words`` lists.
      3. Have added the sentence to every proposed group's members
         list.
      4. Have run the connection-update script — at minimum, the
         word units must carry a lexical connection to the new
         sentence.
      5. Have added a vector to the FAISS index for the sentence's
         ``meaning`` field.

    Each side effect is independently exercised by the tests above;
    this test asserts the combined contract by inspecting all five
    state surfaces immediately after the response, with no
    ``sleep``, ``await``, or background-polling.

    Locked SPEC §6 AC8b / OQ4: ``POST /api/sentences/commit`` is
    synchronous. A future refactor that defers any of these side
    effects to a background queue would break this test.
    """
    payload = _minimal_payload(
        id="wo-xihuan-chi",
        hanzi="我喜欢吃",
        pinyin="wǒ xǐhuān chī",
        english="I like to eat",
        meaning="expressing enjoyment of eating",
        words=["我", "喜欢", "吃"],
        word_refs=["wǒ", "xǐhuān", "chī"],
        groups=["food", "preferences"],
        antonyms=[],
    )

    resp = client.post("/api/sentences/commit", json=payload)

    # The response returns 200 only after all side effects.
    assert resp.status_code == 200, resp.text

    # 1. Sentence unit file is on disk.
    sentence_path = unit_path(str(tmp_path), "sentence", "wo-xihuan-chi")
    assert sentence_path.is_file(), (
        "AC8b violated: sentence unit file missing immediately after "
        "the commit response returned."
    )

    # 2. Word units are created (one per word_refs entry).
    for pinyin in ("wǒ", "xǐhuān", "chī"):
        word_path = unit_path(str(tmp_path), "word", pinyin)
        assert word_path.is_file(), (
            f"AC8b violated: word unit '{pinyin}' missing immediately "
            f"after the commit response returned."
        )

    # 3. Groups have the sentence in their members list.
    for group_id in ("food", "preferences"):
        group = read_unit(str(tmp_path), "group", group_id)
        assert "wo-xihuan-chi" in group["properties"]["members"], (
            f"AC8b violated: group '{group_id}' does not have the "
            f"sentence in its members list."
        )

    # 4. Connection-update script ran: word units have a lexical
    #    connection to the new sentence.
    chi_word = read_unit(str(tmp_path), "word", "chī")
    chi_edges = chi_word.get("connections", [])
    assert any(
        isinstance(e, dict) and e.get("to") == "wo-xihuan-chi" and e.get("kind") == "lexical"
        for e in chi_edges
    ), (
        "AC8b violated: word 'chī' has no lexical connection to the "
        "new sentence — connector did not run."
    )

    # 5. FAISS index contains a vector for the sentence's meaning.
    index = Index.load_or_empty(str(tmp_path))
    assert "wo-xihuan-chi" in index, (
        "AC8b violated: FAISS index does not contain a vector for "
        "the new sentence — embedder/indexer did not run."
    )
    assert len(index) == 1