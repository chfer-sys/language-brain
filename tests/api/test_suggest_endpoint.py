"""Tests for ``GET /api/search/suggest`` — SPEC §5.3, §6 AC27b (T26).

T26 wires up the autocomplete endpoint that returns up to N
unit names whose display string starts with the prefix, sorted
alphabetically. The endpoint is the input layer of the SPEC's
``/api/search/suggest?q=...&limit=N`` row; the response payload
must never carry ``english`` or ``meaning`` keys (AC20 / AC27b).

Setup
-----
Uses FastAPI's :class:`TestClient`. Each test isolates its vault
under ``tmp_path`` and monkey-patches :func:`api.config.settings.
vault`, mirroring the pattern used throughout the search tests.

Seeding strategy
----------------
We bypass the ``/api/sentences/commit`` route and write unit
files directly via :func:`api.services.unit_writer.write_unit`.
The commit route does too much (it also runs the connector and
the FAISS index) and would couple each test to that behavior;
direct writes are clearer and faster.

Test coverage
-------------
The cases listed in the T26 task spec are exercised 1:1 below.
Where the SPEC text was ambiguous (e.g. what "case-insensitive
on display_name" means precisely), the test pins the chosen
behavior so a future change is intentional.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import config as config_module
from api.main import app
from api.services.search import (
    has_english_or_meaning_key,
    suggest_units,
)
from api.services.unit_writer import write_unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """A TestClient bound to a fresh ``LANGUAGE_BRAIN_VAULT=tmp_path``.

    Mirrors the pattern from ``test_search.py``: clear the
    ``get_settings`` lru_cache, set the env var, and patch the
    module-level singleton so the route module (which imports
    ``settings`` directly) reads from ``tmp_path``.
    """
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        config_module.get_settings.cache_clear()


def _make_sentence(
    unit_id: str,
    hanzi: str,
    pinyin: str = "",
    english: str = "",
    meaning: str = "",
) -> dict[str, Any]:
    """Build a minimal sentence unit dict ready for :func:`write_unit`.

    The unit's ``name`` is the hanzi (matching SPEC §2.1 and the
    T19 commit route). ``english``/``meaning`` are populated so
    AC20's leak check has something to leak if a regression
    introduced one — the route must still scrub them.
    """
    return {
        "id": unit_id,
        "type": "sentence",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin or unit_id,
            "english": english,
            "meaning": meaning,
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
    english: str = "",
    meaning: str = "",
) -> dict[str, Any]:
    """Build a minimal word unit dict ready for :func:`write_unit`."""
    return {
        "id": unit_id,
        "type": "word",
        "name": hanzi,
        "properties": {
            "hanzi": hanzi,
            "pinyin": pinyin or unit_id,
            "english": english,
            "meaning": meaning,
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

    Group shape follows SPEC §2.3 and the locked OQ5 contract:
    ``id`` and ``name`` are the slug, ``properties.display_name``
    holds the human-readable form, ``properties.members`` is an
    empty list (group-membership edges are owned by a separate
    task and not exercised here).
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
# 1. Empty / missing query
# ---------------------------------------------------------------------------


def test_suggest_missing_q_returns_422(client: TestClient) -> None:
    """A request with no ``q`` parameter is rejected at the route."""
    resp = client.get("/api/search/suggest")
    assert resp.status_code == 422


def test_suggest_empty_q_returns_422(client: TestClient) -> None:
    """A request with ``q=""`` is rejected by FastAPI's min_length=1."""
    resp = client.get("/api/search/suggest", params={"q": ""})
    assert resp.status_code == 422


def test_suggest_whitespace_only_q_returns_422(
    client: TestClient, tmp_path: Path
) -> None:
    """A whitespace-only ``q`` is rejected explicitly by the route.

    ``Query(min_length=1)`` accepts any string of length >= 1, so
    a single space passes Pydantic but is meaningless to the
    suggester. The route strips and raises 422.
    """
    _seed(
        [_make_sentence("s1", "我喜欢吃")],
        tmp_path,
    )
    resp = client.get("/api/search/suggest", params={"q": "   "})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 2. Limit clamping
# ---------------------------------------------------------------------------


def test_suggest_default_limit_is_five(
    client: TestClient, tmp_path: Path
) -> None:
    """With no ``limit`` param, the response is capped at 5 entries.

    Seed seven sentence units whose hanzi all start with ``"我"``;
    a request with ``q=我`` must return exactly 5 of them, in
    alphabetical order.
    """
    _seed(
        [
            _make_sentence(f"s{i}", f"我{i}")
            for i in "ABCDEFG"
        ],
        tmp_path,
    )
    resp = client.get("/api/search/suggest", params={"q": "我"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["suggestions"]) == 5


def test_suggest_respects_explicit_limit(
    client: TestClient, tmp_path: Path
) -> None:
    """``limit=2`` returns exactly 2 entries even when more match."""
    _seed(
        [_make_sentence(f"s{i}", f"我{i}") for i in "ABCDEFG"],
        tmp_path,
    )
    resp = client.get(
        "/api/search/suggest", params={"q": "我", "limit": 2}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["suggestions"]) == 2


def test_suggest_limit_zero_returns_422(client: TestClient) -> None:
    """``limit=0`` is rejected by Pydantic's ``ge=1``."""
    resp = client.get(
        "/api/search/suggest", params={"q": "吃", "limit": 0}
    )
    assert resp.status_code == 422


def test_suggest_limit_twentyone_returns_422(client: TestClient) -> None:
    """``limit=21`` is rejected by Pydantic's ``le=20``."""
    resp = client.get(
        "/api/search/suggest", params={"q": "吃", "limit": 21}
    )
    assert resp.status_code == 422


def test_suggest_limit_boundary_values_accepted(
    client: TestClient, tmp_path: Path
) -> None:
    """``limit=1`` and ``limit=20`` both pass Pydantic."""
    _seed([_make_sentence("s1", "我喜欢吃")], tmp_path)
    lower = client.get(
        "/api/search/suggest", params={"q": "我", "limit": 1}
    )
    assert lower.status_code == 200, lower.text
    upper = client.get(
        "/api/search/suggest", params={"q": "我", "limit": 20}
    )
    assert upper.status_code == 200, upper.text


# ---------------------------------------------------------------------------
# 3. Alphabetical sort order
# ---------------------------------------------------------------------------


def test_suggest_returns_alphabetical_order(
    client: TestClient, tmp_path: Path
) -> None:
    """Suggestions are sorted alphabetically by ``name``.

    We seed five sentences whose hanzi start with ``"我"`` but
    have varying second characters, so alphabetical order is
    observable. Insertion order is the reverse of alphabetical
    order so the test catches a no-op sort.
    """
    _seed(
        [
            _make_sentence("s_e", "我e"),
            _make_sentence("s_d", "我d"),
            _make_sentence("s_c", "我c"),
            _make_sentence("s_b", "我b"),
            _make_sentence("s_a", "我a"),
        ],
        tmp_path,
    )
    resp = client.get("/api/search/suggest", params={"q": "我"})
    assert resp.status_code == 200, resp.text
    names = [item["name"] for item in resp.json()["suggestions"]]
    assert names == ["我a", "我b", "我c", "我d", "我e"]


# ---------------------------------------------------------------------------
# 4. Match by name prefix — sentence hanzi
# ---------------------------------------------------------------------------


def test_suggest_matches_sentence_hanzi_prefix(
    client: TestClient, tmp_path: Path
) -> None:
    """A prefix that matches a sentence's ``properties.hanzi``
    produces a hit for that sentence.

    We seed three sentences, only one of which starts with the
    prefix ``"你好"``.
    """
    _seed(
        [
            _make_sentence("s_match", "你好世界"),
            _make_sentence("s_other1", "我喜欢吃"),
            _make_sentence("s_other2", "她走了"),
        ],
        tmp_path,
    )
    resp = client.get("/api/search/suggest", params={"q": "你好"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["prefix"] == "你好"
    assert len(body["suggestions"]) == 1
    item = body["suggestions"][0]
    assert item["id"] == "s_match"
    assert item["type"] == "sentence"
    assert item["name"] == "你好世界"


# ---------------------------------------------------------------------------
# 5. Match by name prefix — word hanzi
# ---------------------------------------------------------------------------


def test_suggest_matches_word_hanzi_prefix(
    client: TestClient, tmp_path: Path
) -> None:
    """A prefix that matches a word's ``properties.hanzi``
    produces a hit for that word (with ``type='word'``)."""
    _seed(
        [
            _make_word("chī", "吃"),
            _make_word("chī_fàn", "吃饭"),
            _make_word("hé", "喝"),
        ],
        tmp_path,
    )
    resp = client.get("/api/search/suggest", params={"q": "吃"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["suggestions"]) == 2
    types = {item["type"] for item in body["suggestions"]}
    assert types == {"word"}
    names = {item["name"] for item in body["suggestions"]}
    assert names == {"吃", "吃饭"}


# ---------------------------------------------------------------------------
# 6. Group display_name prefix — and fallback to slug
# ---------------------------------------------------------------------------


def test_suggest_matches_group_display_name_prefix(
    client: TestClient, tmp_path: Path
) -> None:
    """A prefix that matches a group's ``properties.display_name``
    produces a hit with ``type='group'`` and ``name=display_name``."""
    _seed(
        [
            _make_group("basic-verbs", display_name="Basic Verbs"),
            _make_group("foods", display_name="Common Foods"),
        ],
        tmp_path,
    )
    resp = client.get("/api/search/suggest", params={"q": "Basic"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["suggestions"]) == 1
    item = body["suggestions"][0]
    assert item["id"] == "basic-verbs"
    assert item["type"] == "group"
    assert item["name"] == "Basic Verbs"


def test_suggest_falls_back_to_slug_id_when_display_name_empty(
    client: TestClient, tmp_path: Path
) -> None:
    """When ``properties.display_name`` is empty, the suggester
    matches against the slug ``id`` and returns that as ``name``."""
    _seed(
        [
            _make_group("basic-verbs", display_name=""),
            _make_group("basic-food", display_name=""),
        ],
        tmp_path,
    )
    resp = client.get("/api/search/suggest", params={"q": "basic"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["suggestions"]) == 2
    by_id = {item["id"]: item for item in body["suggestions"]}
    # Name is the slug because display_name was empty.
    assert by_id["basic-verbs"]["name"] == "basic-verbs"
    assert by_id["basic-verbs"]["type"] == "group"
    assert by_id["basic-food"]["name"] == "basic-food"


# ---------------------------------------------------------------------------
# 7. Payload hygiene — no english / meaning keys
# ---------------------------------------------------------------------------


def test_suggest_response_never_contains_english_or_meaning_keys(
    client: TestClient, tmp_path: Path
) -> None:
    """The suggest payload has no ``english`` or ``meaning`` keys
    at any level (AC20 / AC27b)."""
    _seed(
        [
            _make_sentence(
                "s1", "我喜欢吃", english="I like to eat",
                meaning="expressing enjoyment",
            ),
            _make_word("chī", "吃", english="to eat", meaning="consume"),
            _make_group(
                "basic-verbs",
                display_name="Basic Verbs",
                description="common verbs",
            ),
        ],
        tmp_path,
    )
    resp = client.get("/api/search/suggest", params={"q": "我"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert has_english_or_meaning_key(payload) is False, (
        f"AC20/AC27b violated: suggest payload leaked a forbidden "
        f"key: {payload!r}"
    )
    # Top-level schema lockdown.
    assert set(payload.keys()) == {"prefix", "suggestions"}
    for item in payload["suggestions"]:
        assert set(item.keys()) == {"id", "type", "name"}


# ---------------------------------------------------------------------------
# 8. Empty vault
# ---------------------------------------------------------------------------


def test_suggest_on_empty_vault_returns_empty_list(
    client: TestClient, tmp_path: Path
) -> None:
    """A vault with no units returns ``suggestions=[]``."""
    # tmp_path is empty by default; no seeding required.
    resp = client.get("/api/search/suggest", params={"q": "any"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"prefix": "any", "suggestions": []}


def test_suggest_with_no_matching_units_returns_empty_list(
    client: TestClient, tmp_path: Path
) -> None:
    """A vault with units but no prefix matches returns ``[]``."""
    _seed(
        [
            _make_sentence("s1", "我喜欢吃"),
            _make_word("chī", "吃"),
        ],
        tmp_path,
    )
    resp = client.get(
        "/api/search/suggest", params={"q": "ZZNoMatchPrefix"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"prefix": "ZZNoMatchPrefix", "suggestions": []}


# ---------------------------------------------------------------------------
# 9. Case-insensitive matching on display_name
# ---------------------------------------------------------------------------


def test_suggest_case_insensitive_on_display_name(
    client: TestClient, tmp_path: Path
) -> None:
    """Matching is case-insensitive on group ``display_name``.

    A query of ``"basic"`` (lowercase) must match a group whose
    ``display_name`` is ``"Basic Verbs"`` (capitalized).
    Conversely, ``"BASIC"`` also matches.
    """
    _seed(
        [_make_group("basic-verbs", display_name="Basic Verbs")],
        tmp_path,
    )

    lower = client.get("/api/search/suggest", params={"q": "basic"})
    assert lower.status_code == 200, lower.text
    assert len(lower.json()["suggestions"]) == 1

    upper = client.get("/api/search/suggest", params={"q": "BASIC"})
    assert upper.status_code == 200, upper.text
    assert len(upper.json()["suggestions"]) == 1

    mixed = client.get("/api/search/suggest", params={"q": "BaSiC"})
    assert mixed.status_code == 200, mixed.text
    assert len(mixed.json()["suggestions"]) == 1


def test_suggest_does_not_match_substring_on_group_id(
    client: TestClient, tmp_path: Path
) -> None:
    """Prefix matching against the slug id is *prefix*, not substring.

    Querying ``"verbs"`` against a group whose id is
    ``"basic-verbs"`` (and display_name empty) must NOT match —
    ``"verbs"`` is a substring of ``"basic-verbs"`` but not a
    prefix. This pins the choice: prefix matching, not substring.
    """
    _seed(
        [_make_group("basic-verbs", display_name="")],
        tmp_path,
    )
    resp = client.get("/api/search/suggest", params={"q": "verbs"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggestions"] == []


# ---------------------------------------------------------------------------
# 10. ``types`` filter
# ---------------------------------------------------------------------------


def test_suggest_types_sentence_filter(
    client: TestClient, tmp_path: Path
) -> None:
    """``?types=sentence`` returns only sentence units, even when
    word and group units also match the prefix."""
    _seed(
        [
            _make_sentence("s1", "吃苹果"),
            _make_word("chī", "吃"),
            _make_group("chi-group", display_name="吃 Group"),
        ],
        tmp_path,
    )
    resp = client.get(
        "/api/search/suggest", params={"q": "吃", "types": "sentence"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0]["type"] == "sentence"
    assert body["suggestions"][0]["name"] == "吃苹果"


def test_suggest_types_group_filter(
    client: TestClient, tmp_path: Path
) -> None:
    """``?types=group`` returns only groups."""
    _seed(
        [
            _make_sentence("s1", "吃苹果"),
            _make_word("chī", "吃"),
            _make_group("chi-group", display_name="吃 Group"),
        ],
        tmp_path,
    )
    resp = client.get(
        "/api/search/suggest", params={"q": "吃", "types": "group"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0]["type"] == "group"
    assert body["suggestions"][0]["id"] == "chi-group"


def test_suggest_types_combined_filter(
    client: TestClient, tmp_path: Path
) -> None:
    """``?types=sentence,word`` returns sentences and words but no groups."""
    _seed(
        [
            _make_sentence("s1", "吃苹果"),
            _make_word("chī", "吃"),
            _make_group("chi-group", display_name="吃 Group"),
        ],
        tmp_path,
    )
    resp = client.get(
        "/api/search/suggest",
        params={"q": "吃", "types": "sentence,word"},
    )
    assert resp.status_code == 200, resp.text
    types = {item["type"] for item in resp.json()["suggestions"]}
    assert types == {"sentence", "word"}


def test_suggest_types_unknown_returns_422(client: TestClient) -> None:
    """An unknown ``types`` value is rejected with 422, matching
    the main search route's behavior."""
    resp = client.get(
        "/api/search/suggest",
        params={"q": "吃", "types": "bogus"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 11. Prefix stripping
# ---------------------------------------------------------------------------


def test_suggest_strips_leading_and_trailing_whitespace(
    client: TestClient, tmp_path: Path
) -> None:
    """Leading / trailing whitespace on ``q`` is stripped before
    matching, and the *stripped* prefix is echoed back in the
    response."""
    _seed(
        [_make_sentence("s1", "我喜欢吃")],
        tmp_path,
    )
    resp = client.get(
        "/api/search/suggest", params={"q": "  我  "}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Stripped prefix echoed back.
    assert body["prefix"] == "我"
    assert len(body["suggestions"]) == 1


# ---------------------------------------------------------------------------
# 12. Service-layer direct call
# ---------------------------------------------------------------------------


def test_suggest_units_pure_function_call(tmp_path: Path) -> None:
    """``suggest_units`` works when called directly without HTTP."""
    _seed(
        [
            _make_sentence("s1", "吃苹果"),
            _make_sentence("s2", "吃饭"),
            _make_word("chī", "吃"),
            _make_group("chi-group", display_name="吃 Group"),
        ],
        tmp_path,
    )
    out = suggest_units(str(tmp_path), prefix="吃", limit=10)
    assert isinstance(out, list)
    assert all(set(item.keys()) == {"id", "type", "name"} for item in out)
    # All four units match; the order is alphabetical by name.
    names = [item["name"] for item in out]
    assert names == sorted(names)
    assert len(out) == 4


def test_suggest_units_empty_prefix_returns_empty(tmp_path: Path) -> None:
    """Calling ``suggest_units`` with an empty / whitespace prefix
    returns ``[]`` without reading the vault."""
    _seed([_make_sentence("s1", "吃苹果")], tmp_path)
    assert suggest_units(str(tmp_path), prefix="") == []
    assert suggest_units(str(tmp_path), prefix="   ") == []
    # Non-string input also returns [] (defensive).
    assert suggest_units(str(tmp_path), prefix=None) == []  # type: ignore[arg-type]


def test_suggest_units_limit_clamps_to_one(
    tmp_path: Path,
) -> None:
    """``limit < 1`` is silently clamped to 1 (matches the SPEC's
    fail-open posture on out-of-range ints)."""
    _seed(
        [_make_sentence("s1", "吃苹果"), _make_sentence("s2", "吃饭")],
        tmp_path,
    )
    out = suggest_units(str(tmp_path), prefix="吃", limit=0)
    assert len(out) == 1


def test_suggest_units_limit_clamps_to_twenty(
    tmp_path: Path,
) -> None:
    """``limit > 20`` is silently clamped to 20."""
    _seed(
        [_make_sentence(f"s{i}", f"吃{i}") for i in range(25)],
        tmp_path,
    )
    out = suggest_units(str(tmp_path), prefix="吃", limit=999)
    assert len(out) == 20