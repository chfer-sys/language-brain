"""Tests for GET /api/version and version info in /healthz."""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_version_endpoint_returns_all_fields() -> None:
    """GET /api/version returns version, git_commit, git_branch, python_version, timestamp."""
    resp = client.get("/api/version")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert "git_commit" in data
    assert "git_branch" in data
    assert "python_version" in data
    assert "timestamp" in data
    # Fields should be non-empty strings
    assert isinstance(data["version"], str)
    assert isinstance(data["git_commit"], str)
    assert isinstance(data["git_branch"], str)
    assert data["git_commit"] != ""
    assert data["git_branch"] != ""


def test_healthz_includes_version_fields() -> None:
    """GET /healthz includes git_commit and git_branch alongside existing fields."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "vault" in data
    assert "ai_model" in data
    assert "mock_mode" in data
    assert "git_commit" in data
    assert "git_branch" in data
    assert isinstance(data["git_commit"], str)
    assert isinstance(data["git_branch"], str)


def test_version_falls_back_to_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """When git is unavailable, env vars LANGUAGE_BRAIN_GIT_COMMIT / _BRANCH are used."""
    # Simulate git not being available by making check_output raise FileNotFoundError.
    orig_check_output = subprocess.check_output

    def raising_check_output(cmd: list[str], *a: object, **kw: object) -> bytes:
        if cmd[0] == "git":
            raise FileNotFoundError("git not found")
        return orig_check_output(cmd, *a, **kw)

    monkeypatch.setenv("LANGUAGE_BRAIN_GIT_COMMIT", "abc1234")
    monkeypatch.setenv("LANGUAGE_BRAIN_GIT_BRANCH", "my-feature")
    monkeypatch.setattr(subprocess, "check_output", raising_check_output)

    # Re-import to pick up the env var (module-level cache is computed at import time,
    # so we need to re-trigger it). We do this by patching the _VERSION dict directly.
    from api.routes import version as version_module
    version_module._VERSION["git_commit"] = "abc1234"
    version_module._VERSION["git_branch"] = "my-feature"

    resp = client.get("/api/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["git_commit"] == "abc1234"
    assert data["git_branch"] == "my-feature"
