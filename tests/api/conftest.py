"""Shared fixtures for ``tests/api/``.

The ``client`` fixture seeds the dictionary (from ``segment_fixture.txt``)
into every test's tmp vault so that commit-path tests can use
``Dictionary.segment()`` instead of jieba.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api import config as config_module
from scripts.build_dictionary import _import_source


# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------

SEGMENT_FIXTURE = Path(__file__).parent.parent / "fixtures" / "segment_fixture.txt"


def _seed_dictionary(vault_root: str) -> None:
    """Populate the word table using the segment_fixture."""
    _import_source(
        vault_root=vault_root,
        source_id="segment-fixture",
        source_name="Segment Fixture",
        source_version="1.0",
        license="CC-BY",
        attribution="Test fixture",
        priority=50,
        csv_path=str(SEGMENT_FIXTURE),
    )


# ---------------------------------------------------------------------------
# Client fixture — seeds the dictionary so commit-path tests work
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A TestClient bound to a fresh ``LANGUAGE_BRAIN_VAULT=tmp_path``.

    The dictionary is seeded from ``segment_fixture.txt`` so that
    ``Dictionary.segment()`` can resolve word units during commit.
    """
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))

    # Seed the dictionary into this test's tmp vault.
    _seed_dictionary(str(tmp_path))

    try:
        yield TestClient(app)
    finally:
        config_module.get_settings.cache_clear()


@pytest.fixture
def vault_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    """A TestClient bound to a fresh vault + the tmp_path.

    Like ``client``, but also returns the vault path as a second value.
    Use this fixture when you need to pre-create vault files before
    making API calls.
    """
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(config_module.settings, "vault", str(tmp_path))
    _seed_dictionary(str(tmp_path))
    try:
        yield TestClient(app), tmp_path
    finally:
        config_module.get_settings.cache_clear()
