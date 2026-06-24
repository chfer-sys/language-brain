"""Tests for AC28: the ``LANGUAGE_BRAIN_VAULT`` env var must control the
vault root for unit writes.

SPEC §6 AC28: ``LANGUAGE_BRAIN_VAULT`` env var changes the vault root.
Test by running with two different values and asserting files are created
in the right place.

The settings layer (``api.config.get_settings``) reads ``LANGUAGE_BRAIN_VAULT``
via pydantic-settings and caches the result behind an ``lru_cache``. These
tests therefore exercise the integration end-to-end:

    LANGUAGE_BRAIN_VAULT=<path>  →  get_settings().vault == <path>
                              →  write_unit(get_settings().vault, ...) lands at <path>

Every test:

* clears ``get_settings.cache_clear()`` so the lru_cache doesn't return a
  stale ``Settings`` instance from a prior test;
* clears any ``LANGUAGE_BRAIN_*`` env vars in the autouse fixture (the
  same pattern used by ``tests/api/test_config.py``);
* uses ``monkeypatch.setenv`` (never reads the real ``.env``);
* uses ``tmp_path`` for the vault roots so the test never touches the
  on-disk vault.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api import config as config_module
from api.config import get_settings
from api.services.unit_writer import write_unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch: pytest.MonkeyPatch):
    """Each test gets a fresh ``get_settings`` cache and a clean
    ``LANGUAGE_BRAIN_*`` env prefix.

    We mirror the pattern in ``tests/api/test_config.py`` so these tests
    are robust to whatever the real ``.env`` file happens to contain in
    CI or locally — we never read it.
    """
    config_module.get_settings.cache_clear()
    for k in [
        "LANGUAGE_BRAIN_VAULT",
        "LANGUAGE_BRAIN_AI_KEY",
        "LANGUAGE_BRAIN_AI_ENDPOINT",
        "LANGUAGE_BRAIN_AI_MODEL",
    ]:
        monkeypatch.delenv(k, raising=False)
    yield
    config_module.get_settings.cache_clear()


@pytest.fixture
def example_sentence_unit() -> dict:
    """A minimal sentence unit per SPEC §2.1 — just enough to satisfy
    ``write_unit``'s shape contract (``id`` and ``type`` required)."""
    return {
        "id": "2026-06-24-001",
        "type": "sentence",
        "name": "我流口水了",
        "properties": {
            "hanzi": "我流口水了",
            "pinyin": "wǒ liú kǒu shuǐ le",
            "english": "I'm drooling",
            "meaning": "I see food and my mouth waters",
            "words": ["我", "流", "口水", "了"],
            "word_refs": ["wǒ", "liú", "kǒushuǐ", "le"],
            "groups": ["reactions", "food"],
            "antonyms": [],
        },
        "connections": [
            {"to": "看起来很好吃", "kind": "semantic", "score": 0.81},
            {"to": "reactions", "kind": "group", "score": 1.0},
        ],
        "created": "2026-06-24",
        "updated": "2026-06-24",
        "author_confirmed": True,
    }


@pytest.fixture
def another_sentence_unit() -> dict:
    """A second, distinct sentence unit. Used in the two-paths test to
    confirm there's no cross-contamination between vault roots."""
    return {
        "id": "2026-06-24-002",
        "type": "sentence",
        "name": "看起来很好吃",
        "properties": {
            "hanzi": "看起来很好吃",
            "pinyin": "kàn qǐ lái hěn hǎo chī",
            "english": "It looks delicious",
            "meaning": "visual assessment of food",
            "words": ["看", "起来", "很", "好吃"],
            "word_refs": ["kàn", "qǐlái", "hěn", "hǎochī"],
            "groups": ["reactions", "food"],
            "antonyms": [],
        },
        "connections": [],
        "created": "2026-06-24",
        "updated": "2026-06-24",
        "author_confirmed": True,
    }


# ---------------------------------------------------------------------------
# AC28 — env var drives settings.vault
# ---------------------------------------------------------------------------


def test_get_settings_reads_vault_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With ``LANGUAGE_BRAIN_VAULT`` set, ``get_settings().vault`` must
    return that exact value (not the default ``./vault/``)."""
    target = str(tmp_path / "custom_root")
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", target)

    settings = get_settings()

    assert settings.vault == target


def test_get_settings_default_when_unset() -> None:
    """With no env var present, ``get_settings().vault`` must fall back
    to the configured default of ``./vault/`` (see ``api/config.py``)."""
    # Autouse fixture has cleared LANGUAGE_BRAIN_VAULT, so the default
    # branch in pydantic-settings should fire.
    settings = get_settings()

    assert settings.vault == "./vault/"


def test_env_var_overrides_dotenv_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``Settings`` is configured with ``env_file=None`` (see
    ``api/config.py``) — pydantic-settings must read the OS env directly.
    Setting the var at runtime must therefore reach ``get_settings()``
    even when no ``.env`` file is in play."""
    target = str(tmp_path / "runtime_only")
    # Sanity: the var is genuinely absent at the start of the test.
    import os
    assert "LANGUAGE_BRAIN_VAULT" not in os.environ
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", target)

    settings = get_settings()

    assert settings.vault == target
    # And the var must not have leaked into the env under a different name.
    assert os.environ.get("LANGUAGE_BRAIN_VAULT") == target


# ---------------------------------------------------------------------------
# AC28 — env var drives where files land on disk
# ---------------------------------------------------------------------------


def test_write_unit_respects_vault_env_var(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    example_sentence_unit: dict,
) -> None:
    """When ``LANGUAGE_BRAIN_VAULT`` points at a non-default path, a
    written unit must land under that path's ``units/sentences/`` tree —
    and NOT under the default ``./vault/``."""
    custom_root = tmp_path / "vault_a"
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(custom_root))

    settings = get_settings()
    assert settings.vault == str(custom_root)

    path = write_unit(settings.vault, example_sentence_unit)

    expected = custom_root / "units" / "sentences" / "2026-06-24-001.json"
    assert path == expected
    assert path.exists()
    # The file should be parseable JSON with the expected id.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["id"] == "2026-06-24-001"
    # No cross-contamination with the default vault location.
    assert not (Path("./vault") / "units" / "sentences" / "2026-06-24-001.json").exists()


def test_two_different_env_values_yield_different_locations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    example_sentence_unit: dict,
    another_sentence_unit: dict,
) -> None:
    """The exact AC28 scenario: run with two different env values, write
    a unit under each, and confirm the files end up in the right places
    without cross-contamination.

    Path A gets unit #1; path B gets unit #2. Both files must exist at
    their respective paths; path A must not contain unit #2, and path B
    must not contain unit #1."""
    path_a = tmp_path / "vault_alpha"
    path_b = tmp_path / "vault_beta"

    # --- First run: env=A, write unit #1 -------------------------------
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(path_a))
    settings_a = get_settings()
    assert settings_a.vault == str(path_a)
    written_a = write_unit(settings_a.vault, example_sentence_unit)
    assert written_a == path_a / "units" / "sentences" / "2026-06-24-001.json"
    assert written_a.exists()

    # --- Second run: env=B, write unit #2 ------------------------------
    # We must clear the lru_cache between runs so get_settings() rebuilds
    # Settings from the new env. The autouse fixture clears it after the
    # test, but here we clear it mid-test for the same reason.
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(path_b))
    settings_b = get_settings()
    assert settings_b.vault == str(path_b)
    written_b = write_unit(settings_b.vault, another_sentence_unit)
    assert written_b == path_b / "units" / "sentences" / "2026-06-24-002.json"
    assert written_b.exists()

    # --- Cross-contamination checks ------------------------------------
    # Path A still has only unit #1.
    a_files = sorted(p.relative_to(path_a) for p in path_a.rglob("*.json"))
    assert a_files == [
        Path("units/sentences/2026-06-24-001.json"),
    ]
    # Path B has only unit #2.
    b_files = sorted(p.relative_to(path_b) for p in path_b.rglob("*.json"))
    assert b_files == [
        Path("units/sentences/2026-06-24-002.json"),
    ]
    # Neither vault contains the other vault's unit id.
    assert not (path_a / "units" / "sentences" / "2026-06-24-002.json").exists()
    assert not (path_b / "units" / "sentences" / "2026-06-24-001.json").exists()
