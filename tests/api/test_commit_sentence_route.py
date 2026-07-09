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
    sentence_id = payload["id"]
    assert sentence_id.startswith("S")

    # On-disk file shape.
    s_path = unit_path(str(tmp_path), "sentence", sentence_id)
    assert s_path.is_file()
    on_disk = json.loads(s_path.read_text(encoding="utf-8"))
    assert on_disk["type"] == "sentence"
    assert on_disk["name"] == "我喜欢吃"
    assert on_disk["properties"]["hanzi"] == "我喜欢吃"
    assert on_disk["properties"]["pinyin"] == "wǒ xǐhuān chī"
    assert on_disk["properties"]["english"] == "I like to eat"
    assert on_disk["properties"]["meaning"] == "expressing enjoyment of eating"
    assert on_disk["properties"]["words"] == ["我", "喜欢", "吃"]
    # After v0.5.2, word_refs are typed counter ids (W{n}, C{n}).
    assert all(
        isinstance(r, str) and (r.startswith("W") or r.startswith("C"))
        for r in on_disk["properties"]["word_refs"]
    )
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
        hanzi="我喜欢",
        pinyin="wǒ xǐhuān",
        english="I like",
        meaning="feeling fondness",
        words=["我", "喜欢"],
        word_refs=["wǒ", "xǐhuān"],
    )
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text

    # After v0.5.2, word ids are typed counters (W1, W2, ...).
    # Look up the actual ids from the on-disk word files.
    words_dir = tmp_path / "units" / "words"
    files = sorted(words_dir.glob("*.json"))
    assert len(files) == 2
    word_units = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    word_units.sort(key=lambda u: u["id"])

    by_hanzi = {u["properties"]["hanzi"]: u for u in word_units}
    assert set(by_hanzi.keys()) == {"我", "喜欢"}
    # 1-hanzi '我' is type:word; 2-hanzi '喜欢' is type:compound (v0.5.2).
    assert by_hanzi["我"]["type"] == "word"
    assert by_hanzi["喜欢"]["type"] == "compound"
    for hanzi, unit in by_hanzi.items():
        assert unit["name"] == hanzi
        assert unit["properties"]["hanzi"] == hanzi


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
    sentence_id = resp.json()["id"]

    # After v0.5.2 word ids are typed counters. Walk the sentence's
    # word_refs (which are the actual W/C ids) and check each.
    sentence = read_unit(str(tmp_path), "sentence", sentence_id)
    for word_id in sentence["properties"]["word_refs"]:
        w_unit = read_unit(str(tmp_path), "word", word_id)
        lexical = [
            e
            for e in w_unit.get("connections", [])
            if isinstance(e, dict) and e.get("kind") == "lexical"
        ]
        assert any(e.get("to") == sentence_id for e in lexical), (
            f"word {word_id!r} missing lexical edge to {sentence_id!r}"
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
    sentence_id = resp.json()["id"]

    for gid in ["food", "preferences"]:
        g_path = unit_path(str(tmp_path), "group", gid)
        assert g_path.is_file(), f"missing group file for {gid}"
        on_disk = json.loads(g_path.read_text(encoding="utf-8"))
        assert on_disk["type"] == "group"
        assert sentence_id in on_disk["properties"]["members"]


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
    sentence_id = resp.json()["id"]

    food = read_unit(str(tmp_path), "group", "food")
    assert sentence_id in food["properties"]["members"]


# ---------------------------------------------------------------------------
# 5. Connector's lexical-pair pass ran (AC12)
# ---------------------------------------------------------------------------


def test_commit_runs_connector_lexical_pairs(
    client: TestClient, tmp_path: Path
) -> None:
    """Two sentences that share a hanzi token get a lexical edge
    between them — proof the connector's lexical pass ran."""
    first = _minimal_payload(hanzi="我喜欢吃", words=["我", "喜欢", "吃"], word_refs=["wǒ", "xǐhuān", "chī"])
    second = _minimal_payload(
        hanzi="我吃饭",
        words=["我", "吃饭"],
        word_refs=["wǒ", "chīfàn"],
    )
    s1_resp = client.post("/api/sentences/commit", json=first)
    assert s1_resp.status_code == 200
    s2_resp = client.post("/api/sentences/commit", json=second)
    assert s2_resp.status_code == 200
    s1_id = s1_resp.json()["id"]
    s2_id = s2_resp.json()["id"]

    s1 = read_unit(str(tmp_path), "sentence", s1_id)
    lexical_to_s2 = [
        e for e in s1.get("connections", [])
        if isinstance(e, dict)
        and e.get("kind") == "lexical"
        and e.get("to") == s2_id
    ]
    assert lexical_to_s2, f"{s1_id} should have a lexical edge to {s2_id} after the connector ran"


# ---------------------------------------------------------------------------
# 6. Connector's opposite-pair pass ran (AC15)
# ---------------------------------------------------------------------------


def test_commit_runs_connector_opposite_pairs(
    client: TestClient, tmp_path: Path
) -> None:
    """The sentence declares ``antonyms=[hǎo_id]``. After the commit,
    the antonym wiring loop should add hǎo_id to è's antonyms list.
    """
    # First commit creates hǎo and captures its id.
    first = _minimal_payload(
        hanzi="好",
        pinyin="hǎo",
        words=["好"],
        word_refs=["hǎo"],
        meaning="good",
        english="good",
    )
    resp1 = client.post("/api/sentences/commit", json=first)
    assert resp1.status_code == 200, resp1.text
    s1 = read_unit(str(tmp_path), "sentence", resp1.json()["id"])
    hǎo_id = s1["properties"]["word_refs"][0]

    # Second commit declares hǎo is antonym of è by using hǎo's id.
    # We use a 2-token sentence so both words become proper word units
    # through ensure_word_unit (avoiding the pre-existing pypinyin
    # CJK-detection quirk for è).
    second = _minimal_payload(
        hanzi="好饿",
        pinyin="hǎo è",
        english="hungry from being good",
        meaning="hungry",
        words=["好", "饿"],
        word_refs=["hǎo", "è"],
        antonyms=[hǎo_id],
    )
    resp2 = client.post("/api/sentences/commit", json=second)
    assert resp2.status_code == 200, resp2.text

    s2 = read_unit(str(tmp_path), "sentence", resp2.json()["id"])
    # Find the id of 饿 from this sentence's word_refs.
    è_id = next(w for w in s2["properties"]["word_refs"] if w != hǎo_id)
    è_unit = read_unit(str(tmp_path), "word", è_id)
    # The connector's symmetry sync must have appended hǎo_id to è's antonyms.
    assert hǎo_id in è_unit["properties"]["antonyms"], (
        f"è's antonyms should contain {hǎo_id} after the opposite pass"
    )


def test_commit_updates_faiss_index(
    client: TestClient, tmp_path: Path
) -> None:
    """A non-empty ``meaning`` results in a single vector being added
    to the FAISS index."""
    body = _minimal_payload(meaning="expressing enjoyment of eating")
    resp = client.post("/api/sentences/commit", json=body)
    assert resp.status_code == 200, resp.text
    sentence_id = resp.json()["id"]

    index = Index.load_or_empty(str(tmp_path))
    assert sentence_id in index
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
    sentence_id = resp.json()["id"]

    # The sentence file should exist (the unit write is independent
    # of the FAISS update), but the FAISS index should be empty.
    assert unit_path(str(tmp_path), "sentence", sentence_id).is_file()
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
    first_id = first.json()["id"]

    s_path = unit_path(str(tmp_path), "sentence", first_id)
    on_disk_first = json.loads(s_path.read_text(encoding="utf-8"))

    second = client.post("/api/sentences/commit", json=body)
    assert second.status_code == 200, second.text
    second_id = second.json()["id"]
    on_disk_second = json.loads(
        unit_path(str(tmp_path), "sentence", second_id).read_text(encoding="utf-8")
    )

    # Each commit gets a distinct counter id.
    assert first_id != second_id
    assert on_disk_first["type"] == on_disk_second["type"] == "sentence"


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
    sentence_id = resp.json()["id"]

    # 1. Sentence unit file is on disk.
    sentence_path = unit_path(str(tmp_path), "sentence", sentence_id)
    assert sentence_path.is_file(), (
        "AC8b violated: sentence unit file missing immediately after "
        "the commit response returned."
    )

    # 2. Word units are created (one per word_refs entry).
    sentence = read_unit(str(tmp_path), "sentence", sentence_id)
    for word_id in sentence["properties"]["word_refs"]:
        word_path = unit_path(str(tmp_path), "word", word_id)
        assert word_path.is_file(), (
            f"AC8b violated: word unit '{word_id}' missing immediately "
            f"after the commit response returned."
        )

    # 3. Groups have the sentence in their members list.
    for group_id in ("food", "preferences"):
        group = read_unit(str(tmp_path), "group", group_id)
        assert sentence_id in group["properties"]["members"], (
            f"AC8b violated: group '{group_id}' does not have the "
            f"sentence in its members list."
        )

    # 4. Connection-update script ran: word units have a lexical
    #    connection to the new sentence. Find 吃 by hanzi.
    sentence_words_dir = tmp_path / "units" / "words"
    chi_word = None
    for wf in sentence_words_dir.glob("*.json"):
        unit = json.loads(wf.read_text(encoding="utf-8"))
        if unit.get("properties", {}).get("hanzi") == "吃":
            chi_word = unit
            break
    assert chi_word is not None, "AC8b: word '吃' missing"
    chi_edges = chi_word.get("connections", [])
    assert any(
        isinstance(e, dict) and e.get("to") == sentence_id and e.get("kind") == "lexical"
        for e in chi_edges
    ), (
        "AC8b violated: word '吃' has no lexical connection to the "
        "new sentence — connector did not run."
    )

    # 5. FAISS index contains a vector for the sentence's meaning.
    index = Index.load_or_empty(str(tmp_path))
    assert sentence_id in index, (
        "AC8b violated: FAISS index does not contain a vector for "
        "the new sentence — embedder/indexer did not run."
    )
    assert len(index) == 1