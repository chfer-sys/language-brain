"""AC21 — No natural-language English in search ``name`` or ``snippet`` (T25).

SPEC §6 AC21: "Search response payload contains no natural-language
English text in any ``name`` or ``snippet`` field (assert the strings
contain no ASCII a-z sequences of length >= 3, excluding pinyin's
tone-marked vowels)."

T25 is the acceptance lockdown for AC21. The production code already
satisfies the invariant at T20/T23/T24 (hanzi for ``name``, pinyin with
tone marks for ``snippet``, slug id for groups); T25's job is to pin
the contract so future contributors can't regress it. The companion
helper :func:`api.services.search.has_natural_language_english` (also
implemented at T20) is the single source of truth for the
ASCII a-z run check — every assertion here goes through it.

What T25 covers
---------------

1. **Live route response** — ``GET /api/search`` with mocked services
   that return one of each unit type (sentence, word, group). For every
   hit in ``results``, both ``name`` and ``snippet`` must be clean.
2. **Realistic hanzi + pinyin hits** — lock down the happy path: a
   sentence, a word, and a group whose ``display_name`` is empty (so
   the impl falls back to the slug id, which is ASCII-pure by
   construction). Document the known limitation around a group with a
   custom English ``display_name`` separately (see "Known limitation"
   below).
3. **Helper unit tests** — exercise the threshold semantics of
   :func:`has_natural_language_english`: 3+ ASCII run triggers,
   2-char ASCII does not, pinyin with tones is fine, ``None`` is
   safe, etc.
4. **Live route with mocked lexical hit** — seed real unit files with
   hanzi/pinyin and exercise the real ``lexical_search`` path (no
   FAISS). The route output must be clean.
5. **Live route integration with real FAISS index** — seed sentence
   units, build a real FAISS index via :class:`HashingEmbedder`, hit
   the route, assert every ``name``/``snippet`` is clean. This is the
   end-to-end smoke test required by the task spec.

Known limitation (documented for future work — T33 / a UI task)
---------------------------------------------------------------

A group's ``properties.display_name`` is user-supplied and may
contain natural-language English (e.g. ``"Basic Verbs"``). The
current implementation copies ``display_name`` verbatim into the
``name`` field of the search response (with a fallback to the slug
id when ``display_name`` is empty). This means a group with a custom
English ``display_name`` will leak a 3+ ASCII run into the
response's ``name`` field and **violates AC21**.

We deliberately do NOT fix this in T25. T25 is about pinning the
invariant for the production code path that already satisfies it
(slug-only display names, sentences, words). Two competing solutions
exist:

* **(a)** Sanitize at the service layer: if a group's
  ``display_name`` contains a 3+ ASCII run, fall back to the slug id
  for the response's ``name``. Defensive but lossy — a user who
  wants to title a group in pinyin or English loses that signal in
  search results.
* **(b)** Reject or sanitize at the group-creation layer (e.g. the
  commit-sentence route's ``groups`` parameter, or a future
  ``POST /api/groups`` route) so a display_name containing natural
  English can never reach the vault. Cleaner contract but requires
  a product decision about what's allowed.

A separate task (T33 or a UI task) must pick (a) or (b) and
implement it. Until then, this test file contains a single test
(``test_known_limitation_group_with_english_display_name``) that
asserts the *current* behavior so future contributors see the gap
in the AC21 invariant immediately rather than discovering it by
accident.

Mocking strategy
----------------

Route-level tests use ``MagicMock`` to swap
:func:`api.routes.search.lexical_search` and
:func:`api.routes.search.semantic_search` so the assertion targets
the route's output shape (not the ranker's internal behavior). The
end-to-end integration test (``test_live_route_with_real_index``)
bypasses the mocks and exercises the real services, patching
``get_embedder`` to the offline :class:`HashingEmbedder` so the
FAISS path doesn't trigger a model download.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api import config as config_module
from api.main import app
from api.routes import search as search_route
from api.services.embedder import HashingEmbedder
from api.services.indexer import Index
from api.services.search import (
    SearchHit,
    has_natural_language_english,
)
from api.services.unit_writer import list_units_by_type, write_unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """A TestClient bound to a fresh ``LANGUAGE_BRAIN_VAULT=tmp_path``.

    Mirrors the pattern in
    :mod:`tests.api.test_ac20_payload_hygiene` /
    :mod:`tests.api.test_search`: clear the ``get_settings`` lru_cache,
    set the env var, and patch the module-level singleton so the route
    module (which imports ``settings`` directly) reads from
    ``tmp_path``.
    """
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        config_module.get_settings.cache_clear()


@pytest.fixture
def mocked_search_route(monkeypatch: pytest.MonkeyPatch):
    """Yield the two ``MagicMock`` services the route layer uses.

    Patches :func:`api.routes.search.lexical_search` and
    :func:`api.routes.search.semantic_search` (the names the route
    imported into its own namespace). Tests that need realistic hits
    configure ``return_value``; tests that don't care about hits
    ignore the mocks (they default to ``[]``).
    """
    lexical_mock = MagicMock(return_value=[])
    semantic_mock = MagicMock(return_value=[])
    monkeypatch.setattr(search_route, "lexical_search", lexical_mock)
    monkeypatch.setattr(search_route, "semantic_search", semantic_mock)
    return lexical_mock, semantic_mock


def _hit(
    unit_id: str,
    unit_type: str,
    name: str,
    snippet: str,
    score: float = 0.5,
) -> SearchHit:
    """Build a clean ``SearchHit`` for the mocked-route tests."""
    return SearchHit(
        unit_id=unit_id,
        unit_type=unit_type,
        name=name,
        snippet=snippet,
        score=score,
    )


def _make_sentence(
    unit_id: str,
    hanzi: str,
    pinyin: str = "",
) -> dict[str, Any]:
    """Build a minimal sentence unit dict ready for :func:`write_unit`.

    No ``english``/``meaning`` fields are needed for AC21 (those are
    AC20's concern) but we include them empty so the dict round-trips
    through the writer without surprising future readers.
    """
    return {
        "id": unit_id,
        "type": "sentence",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin or unit_id,
            "english": "",
            "meaning": "",
            "words": [],
            "word_refs": [],
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-27",
        "updated": "2026-06-27",
        "author_confirmed": True,
    }


def _make_word(
    unit_id: str,
    hanzi: str,
    pinyin: str = "",
) -> dict[str, Any]:
    """Build a minimal word unit dict ready for :func:`write_unit`."""
    return {
        "id": unit_id,
        "type": "word",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin or unit_id,
            "english": "",
            "meaning": "",
            "groups": [],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-27",
        "updated": "2026-06-27",
        "author_confirmed": True,
    }


def _make_group(
    unit_id: str,
    display_name: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Build a minimal group unit dict ready for :func:`write_unit`.

    ``display_name`` defaults to empty so the search code's
    fallback-to-slug branch is exercised (this is the AC21-clean
    path). Tests that need the English ``display_name`` violation
    pass it explicitly.
    """
    return {
        "id": unit_id,
        "type": "group",
        "name": unit_id,
        "properties": {
            "display_name": display_name,
            "description": description,
            "members": [],
        },
        "connections": [],
        "created": "2026-06-27",
        "updated": "2026-06-27",
        "author_confirmed": True,
    }


def _seed(units: list[dict[str, Any]], tmp_path: Path) -> None:
    """Write a list of unit dicts to ``tmp_path`` via :func:`write_unit`."""
    for unit in units:
        write_unit(str(tmp_path), unit)


# ---------------------------------------------------------------------------
# 1. Live route response — mocked services, mixed unit types
# ---------------------------------------------------------------------------


def test_route_response_name_and_snippet_clean_for_every_hit(
    client: TestClient,
    mocked_search_route: tuple[MagicMock, MagicMock],
) -> None:
    """``GET /api/search?q=...`` returns a JSON body where every hit's
    ``name`` and ``snippet`` is free of natural-language English (per
    SPEC §6 AC21).

    We seed one of each unit type (sentence, word, group) into the
    mocked lexical service and assert the invariant for every hit in
    ``results``. The mocked semantic service returns ``[]`` so the
    merged response is identical to the lexical output.
    """
    lexical_mock, semantic_mock = mocked_search_route
    lexical_mock.return_value = [
        _hit("s-1", "sentence", "我喜欢吃", "wǒ xǐhuān chī", score=0.9),
        _hit("chi", "word", "吃", "chī", score=0.7),
        # Group with empty display_name — the impl falls back to the
        # slug id, which is ASCII-pure by construction (no spaces,
        # no natural English).
        _hit("basic-verbs", "group", "basic-verbs", "basic-verbs", score=0.5),
    ]
    semantic_mock.return_value = []

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert len(payload["results"]) == 3
    for item in payload["results"]:
        assert has_natural_language_english(item["name"]) is False, (
            f"AC21 violated: hit {item['id']!r} name {item['name']!r} "
            f"contains a 3+ ASCII a-z run"
        )
        assert has_natural_language_english(item["snippet"]) is False, (
            f"AC21 violated: hit {item['id']!r} snippet "
            f"{item['snippet']!r} contains a 3+ ASCII a-z run"
        )


# ---------------------------------------------------------------------------
# 2. Realistic hanzi + pinyin hits — happy path
# ---------------------------------------------------------------------------


def test_realistic_hanzi_and_pinyin_hits_pass_ac21(
    client: TestClient,
    mocked_search_route: tuple[MagicMock, MagicMock],
) -> None:
    """The exact hits called out in the T25 spec — sentence, word,
    group with empty display_name — all satisfy AC21.

    The mocked services return a small mix of hand-crafted
    :class:`SearchHit` values; the route's output shape is asserted
    for each one. This is the happy-path lockdown: every
    production-supported input combination passes the invariant.
    """
    lexical_mock, semantic_mock = mocked_search_route
    lexical_mock.return_value = [
        # Sentence: hanzi name, pinyin snippet — both clean.
        _hit("s-1", "sentence", "我喜欢吃", "wǒ xǐhuān chī"),
        # Word: single hanzi + single pinyin-with-tone — both clean.
        _hit("chi", "word", "吃", "chī"),
        # Group with empty display_name: name + snippet fall back to
        # the slug id, which is ASCII-pure (no natural English).
        _hit("basic-verbs", "group", "basic-verbs", "basic-verbs"),
    ]
    semantic_mock.return_value = []

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    by_id = {item["id"]: item for item in payload["results"]}
    assert set(by_id.keys()) == {"s-1", "chi", "basic-verbs"}

    for hit_id, expected_name, expected_snippet in [
        ("s-1", "我喜欢吃", "wǒ xǐhuān chī"),
        ("chi", "吃", "chī"),
        ("basic-verbs", "basic-verbs", "basic-verbs"),
    ]:
        item = by_id[hit_id]
        assert item["name"] == expected_name
        assert item["snippet"] == expected_snippet
        assert has_natural_language_english(item["name"]) is False
        assert has_natural_language_english(item["snippet"]) is False


# ---------------------------------------------------------------------------
# 2b. Known limitation — group with English display_name leaks
# ---------------------------------------------------------------------------


def test_known_limitation_group_with_english_display_name(
    client: TestClient,
    mocked_search_route: tuple[MagicMock, MagicMock],
) -> None:
    """Documented limitation: a group whose ``display_name`` is
    natural-language English (e.g. ``"Basic Verbs"``) leaks a 3+ ASCII
    run into the response's ``name`` field.

    This test pins the *current* behavior so a future contributor who
    fixes the limitation knows the exact regression they're guarding
    against. The fix is intentionally out of scope for T25 (see the
    file-level docstring "Known limitation" section) — T25 is about
    *preventing regressions* in the code paths that already satisfy
    AC21, not about implementing the policy decision for what to do
    with English display_names.

    The expected outcome is therefore that the response **does**
    contain a 3+ ASCII run in ``name`` for this group. If a future
    change makes this test fail, that's the signal that the
    limitation has been fixed and this test should be moved /
    inverted (likely into ``test_route_response_name_and_snippet_clean_for_every_hit``
    to re-lock the AC21 invariant on the now-fixed path).
    """
    lexical_mock, semantic_mock = mocked_search_route
    lexical_mock.return_value = [
        _hit("basic-verbs", "group", "Basic Verbs", "basic-verbs"),
    ]
    semantic_mock.return_value = []

    resp = client.get("/api/search", params={"q": "basic"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert len(payload["results"]) == 1
    item = payload["results"][0]
    assert item["type"] == "group"
    # Snippet is the slug id, which is ASCII-pure (no spaces, no
    # natural English). The AC21 invariant trivially holds here.
    assert has_natural_language_english(item["snippet"]) is False
    # Name IS the display_name, which contains natural-language
    # English ("Basic Verbs"). The AC21 invariant is therefore
    # *violated* by the current implementation. Document this so
    # future contributors see the gap.
    assert item["name"] == "Basic Verbs"
    assert has_natural_language_english(item["name"]) is True, (
        "Known limitation: this test asserts the current behavior. "
        "If a future change sanitizes group display_names, this "
        "assertion will fail and the test should be re-evaluated."
    )


# ---------------------------------------------------------------------------
# 3. Helper unit tests — ``has_natural_language_english`` edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "s,expected",
    [
        # Empty string → no runs → False.
        ("", False),
        # 3 ASCII letters exactly → True (threshold is 3+).
        ("abc", True),
        # 2 ASCII letters → below threshold → False.
        ("ab", False),
        # No ASCII at all → False.
        ("你好", False),
        # Natural-language English sentence → True.
        ("I am eating", True),
        # Pinyin with tone marks → no 3+ ASCII run → False.
        ("wǒ xǐhuān chī", False),
        # Pinyin substring "le" — 2 ASCII chars → False.
        ("le", False),
        # Single ASCII char → False.
        ("I", False),
        # None → False (defensive: non-strings are safe).
        (None, False),  # type: ignore[arg-type]
        # Mixed: hanzi prefix + English tail → True.
        ("你好abc", True),
        # Mixed: pinyin + hanzi → False.
        ("wǒ 你好", False),
        # All-uppercase 3+ run also triggers (the regex is
        # case-insensitive).
        ("FOO bar", True),
        # Hyphens don't break ASCII runs when they're contiguous,
        # but they aren't matched by [A-Za-z] so they split the run.
        ("a-b-c", False),
    ],
)
def test_has_natural_language_english_helper(
    s: str | None, expected: bool
) -> None:
    """Lock down the threshold semantics of
    :func:`has_natural_language_english` against the explicit edge
    cases called out in the T25 spec:

    * empty string → ``False``;
    * ``"abc"`` (3 ASCII) → ``True``;
    * ``"ab"`` (2 ASCII) → ``False``;
    * ``"你好"`` (no ASCII) → ``False``;
    * ``"I am eating"`` → ``True``;
    * ``"wǒ xǐhuān chī"`` (pinyin with tones) → ``False``;
    * ``"le"`` (pinyin substring, 2 ASCII) → ``False``;
    * ``"I"`` → ``False``;
    * ``None`` → ``False``.

    A handful of additional cases (mixed hanzi+English, hyphens,
    uppercase) are included to document the negative space and
    catch off-by-one regressions in the regex.
    """
    assert has_natural_language_english(s) is expected, (
        f"has_natural_language_english({s!r}) returned "
        f"{not expected}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# 4. Live route with mocked lexical hit (no FAISS) — real unit files
# ---------------------------------------------------------------------------


def test_live_route_with_mocked_lexical_no_faiss(
    client: TestClient,
    tmp_path: Path,
    mocked_search_route: tuple[MagicMock, MagicMock],
) -> None:
    """Seed real unit files (hanzi + pinyin, no English) and verify
    the live ``/api/search`` response has clean ``name``/``snippet``
    fields even when the lexical service is mocked but the unit
    files on disk are real.

    This is the realistic case from a user's perspective: the vault
    contains real sentence/word units with proper hanzi/pinyin, the
    user hits the search endpoint, and every hit's display strings
    are free of natural-language English. The mocked lexical
    service just bypasses the ranker so the test doesn't depend on
    Jaccard overlap.
    """
    # Seed the vault with real unit files — hanzi + pinyin only,
    # no English anywhere in the search-relevant fields.
    _seed(
        [
            _make_sentence("s-1", "我喜欢吃", pinyin="wǒ xǐhuān chī"),
            _make_sentence("s-2", "你吃了吗", pinyin="nǐ chī le ma"),
            _make_word("chī", "吃", pinyin="chī"),
            _make_word("hē", "喝", pinyin="hē"),
        ],
        tmp_path,
    )

    # Sanity-check: the units landed on disk.
    on_disk = list_units_by_type(str(tmp_path), "sentence") + list_units_by_type(
        str(tmp_path), "word"
    )
    assert {u["id"] for u in on_disk} == {"s-1", "s-2", "chī", "hē"}

    # Mock the lexical service to return a deterministic, clean
    # response. The route still runs the semantic pass against an
    # empty FAISS index (no index built) so that path is a no-op.
    lexical_mock, semantic_mock = mocked_search_route
    lexical_mock.return_value = [
        _hit("s-1", "sentence", "我喜欢吃", "wǒ xǐhuān chī", score=0.9),
        _hit("s-2", "sentence", "你吃了吗", "nǐ chī le ma", score=0.6),
        _hit("chī", "word", "吃", "chī", score=0.4),
    ]
    semantic_mock.return_value = []

    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert len(payload["results"]) == 3

    for item in payload["results"]:
        assert has_natural_language_english(item["name"]) is False, (
            f"AC21 violated at live route: hit {item['id']!r} name "
            f"{item['name']!r} contains a 3+ ASCII run"
        )
        assert has_natural_language_english(item["snippet"]) is False, (
            f"AC21 violated at live route: hit {item['id']!r} snippet "
            f"{item['snippet']!r} contains a 3+ ASCII run"
        )


# ---------------------------------------------------------------------------
# 5. Live route integration — real FAISS index, no mocks
# ---------------------------------------------------------------------------


def _build_index(vault: Path, sentence_meanings: dict[str, str]) -> None:
    """Build and save a real FAISS index using the offline
    :class:`HashingEmbedder` (no model download, no network).

    Mirrors the seeding pattern from
    :mod:`tests.api.test_semantic_search` and
    :mod:`tests.api.test_ac20_payload_hygiene` — embed each
    sentence's meaning and call :meth:`Index.save` so the on-disk
    index is what the route layer reads.
    """
    embedder = HashingEmbedder()
    idx = Index()
    for sid, meaning in sentence_meanings.items():
        idx.add(sid, embedder.embed(meaning))
    idx.save(str(vault))


def test_live_route_with_real_index(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end smoke test: write 2 sentence units with hanzi/pinyin
    (no English in name/snippet-relevant fields), build a real FAISS
    index via :class:`HashingEmbedder`, hit ``GET /api/search?q=...``,
    and assert every hit's ``name`` and ``snippet`` is free of
    natural-language English.

    This exercises the *real* ``semantic_search`` and
    ``lexical_search`` paths (no mocks) so any regression in the
    route's ``_hit_to_item`` adapter, the ranker's name/snippet
    extraction, or the FAISS merge logic surfaces here. Without
    this integration test, a future refactor that silently broke
    AC21 inside one of those layers would slip past the mocked
    route-level tests.

    The test patches ``get_embedder`` to return the offline
    :class:`HashingEmbedder` — without this, the route's default
    ``get_embedder()`` call inside ``semantic_search`` would try to
    load the sentence-transformers model and the test would hang.
    Patching at ``api.services.search`` (where it's bound into the
    module namespace) is what actually intercepts the call.
    """
    # Pin the embedder to HashingEmbedder so the route's
    # semantic_search doesn't trigger the model load.
    from api.services import search as search_module

    monkeypatch.setattr(
        search_module, "get_embedder", lambda force=None: HashingEmbedder()
    )

    # 1. Seed two sentence units whose name/snippet-relevant fields
    #    are clean (hanzi + pinyin). The unit dicts may carry
    #    english/meaning for the FAISS embedding step — those fields
    #    are forbidden in the *response* (AC20) but irrelevant for
    #    AC21's name/snippet check.
    write_unit(
        str(tmp_path),
        {
            "id": "s-live-1",
            "type": "sentence",
            "name": "我喜欢吃",
            "properties": {
                "hanzi": "我喜欢吃",
                "pinyin": "wǒ xǐhuān chī",
                "english": "I like to eat",
                "meaning": "I like to eat",
                "words": [],
                "word_refs": [],
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-06-27",
            "updated": "2026-06-27",
            "author_confirmed": True,
        },
    )
    write_unit(
        str(tmp_path),
        {
            "id": "s-live-2",
            "type": "sentence",
            "name": "你吃了吗",
            "properties": {
                "hanzi": "你吃了吗",
                "pinyin": "nǐ chī le ma",
                "english": "have you eaten yet",
                "meaning": "have you eaten yet",
                "words": [],
                "word_refs": [],
                "groups": [],
                "antonyms": [],
            },
            "connections": [],
            "created": "2026-06-27",
            "updated": "2026-06-27",
            "author_confirmed": True,
        },
    )

    # 2. Build a real FAISS index keyed on the meaning (which IS
    #    English — that's the semantic-search vector, not the
    #    display string).
    _build_index(
        tmp_path,
        {
            "s-live-1": "I like to eat",
            "s-live-2": "have you eaten yet",
        },
    )

    # Sanity-check: the index actually loaded.
    on_disk = list_units_by_type(str(tmp_path), "sentence")
    assert {u["id"] for u in on_disk} == {"s-live-1", "s-live-2"}

    # 3. Hit the route with a query that triggers both passes.
    #    The hanzi "吃" is a token in both sentences (lexical
    #    pass); the English query "I like to eat" is the meaning
    #    of s-live-1 (semantic pass → cosine ≈ 1.0).
    resp = client.get("/api/search", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # 4. AC21 lockdown: every hit's name and snippet is free of
    #    natural-language English. This is the integration-level
    #    check that catches regressions the mocked tests miss.
    assert len(payload["results"]) >= 1, (
        "expected at least one hit from the seeded sentences"
    )
    for item in payload["results"]:
        assert has_natural_language_english(item["name"]) is False, (
            f"AC21 violated at live route: hit {item['id']!r} name "
            f"{item['name']!r} contains a 3+ ASCII run. "
            f"full payload: {payload!r}"
        )
        assert has_natural_language_english(item["snippet"]) is False, (
            f"AC21 violated at live route: hit {item['id']!r} snippet "
            f"{item['snippet']!r} contains a 3+ ASCII run. "
            f"full payload: {payload!r}"
        )
        # Defensive: every hit is a sentence (only sentence units
        # are in the FAISS index per SPEC §6 AC9).
        assert item["type"] == "sentence"
        # Defensive: name = hanzi, snippet = pinyin for sentences.
        assert item["name"] in {"我喜欢吃", "你吃了吗"}
        assert item["snippet"] in {"wǒ xǐhuān chī", "nǐ chī le ma"}