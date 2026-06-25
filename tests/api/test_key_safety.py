"""Tests for SPEC §6 AC8 — every AI call goes through
``api.services.ai_client``; the AI key never appears in source,
tests, or logs.

Coverage:

* Source-tree grep: no module outside ``api/services/ai_client.py``
  imports ``requests`` (which is the only HTTP client we use to talk
  to the AI provider) or constructs the AI HTTP path
  ``/chat/completions``. This locks down the single-chokepoint
  invariant: anything that wants the LLM must go through
  ``ai_client.py``.

* Pre-commit guard: ``scripts/check_no_secrets.sh`` runs clean on
  the current tree. (We invoke it via subprocess so the test fails
  loudly if a regression leaks a key.)

* The AI client module is the only place the API key is referenced.
  A test scans the source for the literal ``LANGUAGE_BRAIN_AI_KEY``
  or ``sk-`` tokens, with the AI client module whitelisted.

* Logging safety: a test that imports the AI client and exercises
  the error path (no key set) confirms the resulting RuntimeError
  message does not contain the key, the endpoint, or any URL
  fragment.

The grep tests are deliberately aggressive. If you intentionally
add another HTTP client somewhere, the test will fail and you'll
have to update it (and justify the change in the SPEC). That's
the point.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from api.services import ai_client as ai_client_module


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _python_sources() -> list[Path]:
    """All .py files under api/ and tests/, excluding __pycache__."""
    paths: list[Path] = []
    for sub in ("api", "tests"):
        for p in (REPO_ROOT / sub).rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            paths.append(p)
    return paths


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Source-tree chokepoint: only ai_client.py uses the HTTP layer
# ---------------------------------------------------------------------------


def test_only_ai_client_imports_requests() -> None:
    """No module outside ``api/services/ai_client.py`` imports
    ``requests`` or any other HTTP client library. The LLM network
    call lives in exactly one place."""
    offenders: list[str] = []
    for p in _python_sources():
        rel = p.relative_to(REPO_ROOT)
        if rel == Path("api/services/ai_client.py"):
            continue
        text = _read(p)
        # Look for "import requests" or "from requests" anywhere.
        if re.search(r"^\s*(import\s+requests|from\s+requests\s+import)",
                     text, re.MULTILINE):
            offenders.append(str(rel))
    assert offenders == [], (
        f"AC8 violated: only api/services/ai_client.py may import the "
        f"HTTP client. Offenders: {offenders}"
    )


def test_only_ai_client_references_chat_completions() -> None:
    """The OpenAI-compatible chat-completions path string must appear
    only in ``ai_client.py``. If another module constructs the URL,
    it's making its own AI call."""
    offenders: list[str] = []
    whitelist = {Path("api/services/ai_client.py"), Path("tests/api/test_key_safety.py")}
    for p in _python_sources():
        rel = p.relative_to(REPO_ROOT)
        if rel in whitelist:
            continue
        text = _read(p)
        if "/chat/completions" in text or "chat/completions" in text:
            offenders.append(str(rel))
    assert offenders == [], (
        f"AC8 violated: chat-completions URL found outside "
        f"api/services/ai_client.py. Offenders: {offenders}"
    )


def test_only_ai_client_imports_os_environ_for_key() -> None:
    """A weaker check: the literal token ``LANGUAGE_BRAIN_AI_KEY``
    should appear only in config.py (the reading-from-env module) and
    ai_client.py (the consumer). No other module should reference
    the key by name."""
    whitelist = {
        Path("api/config.py"),
        Path("api/services/ai_client.py"),
        Path("tests/api/test_ai_client.py"),
        Path("tests/api/test_vault_env_var.py"),
        Path("tests/api/test_config.py"),
        Path("tests/api/test_add_sentence_route.py"),
        Path("tests/api/test_key_safety.py"),  # this file
        Path("tests/api/test_ac30_key_safety.py"),  # AC30 test, by design
    }
    offenders: list[str] = []
    for p in _python_sources():
        rel = p.relative_to(REPO_ROOT)
        if rel in whitelist:
            continue
        text = _read(p)
        # Reference, not just any occurrence: only the env-var name
        # in a string literal. Avoid flagging the name in a comment
        # that explains the policy.
        if re.search(r"[\"']LANGUAGE_BRAIN_AI_KEY[\"']", text):
            offenders.append(str(rel))
    assert offenders == [], (
        f"AC8 violated: LANGUAGE_BRAIN_AI_KEY referenced outside the "
        f"whitelist. Offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# Pre-commit guard runs clean
# ---------------------------------------------------------------------------


def test_check_no_secrets_script_runs_clean() -> None:
    """The pre-commit secret guard exits 0 on the current tree."""
    script = REPO_ROOT / "scripts" / "check_no_secrets.sh"
    assert script.is_file(), f"missing {script}"
    result = subprocess.run(
        ["bash", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"check_no_secrets.sh failed:\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


def test_no_sk_tokens_in_tracked_source() -> None:
    """No ``sk-`` followed by 16+ alnum chars anywhere in tracked files."""
    pattern = re.compile(r"sk-[A-Za-z0-9]{16,}")
    for p in _python_sources():
        text = _read(p)
        # Allow the guard script to mention the pattern in a comment.
        rel = p.relative_to(REPO_ROOT)
        if rel == Path("scripts/check_no_secrets.sh"):
            continue
        m = pattern.search(text)
        assert not m, f"sk- token in {rel}: {m.group(0)!r}"


# ---------------------------------------------------------------------------
# Error-path safety: a RuntimeError from the AI client must not leak
# the key, the endpoint, or the URL into its message.
# ---------------------------------------------------------------------------


def test_runtime_error_does_not_leak_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling the AI client without a key raises RuntimeError. The
    message must not contain the key VALUE (no ``sk-...`` token, no
    key-like alphanumeric run). Mentioning the env var NAME in an
    operator hint is acceptable — the AC8 contract is about key
    values, not env var names."""
    from api.services.ai_client import HttpAIClient

    monkeypatch.delenv("LANGUAGE_BRAIN_AI_KEY", raising=False)
    ai_client_module.get_settings.cache_clear()
    client = HttpAIClient()
    try:
        client.propose_labels("x")
    except RuntimeError as exc:
        msg = str(exc)
        # No key VALUE leaked.
        assert "sk-" not in msg
        # No endpoint URL leaked.
        assert "https://" not in msg
        assert "http://" not in msg
        # Generic diagnostic should be present.
        assert "no AI key configured" in msg
    else:
        pytest.fail("HttpAIClient.propose_labels should have raised")


def test_runtime_error_does_not_leak_endpoint() -> None:
    """A network error (mocked) must not embed the endpoint URL or
    any response body that might echo the prompt back."""
    from unittest.mock import patch

    from api.services import ai_client as ai_client_module
    from api.services.ai_client import HttpAIClient

    class _FakeResp:
        status_code = 500
        text = "echoed prompt with sk-test"

    class _FakeRequestException(Exception):
        def __init__(self) -> None:
            self.response = _FakeResp()

    class _FakeRequests:
        RequestException = _FakeRequestException

        @staticmethod
        def post(*args: object, **kwargs: object) -> _FakeResp:
            raise _FakeRequestException()

    # Inject key + endpoint, then patch requests.
    ai_client_module.get_settings.cache_clear()
    with patch.object(ai_client_module, "get_settings") as mock_get:
        from pydantic import SecretStr

        from api.config import Settings

        s = Settings(
            vault="./vault/",
            ai_key=SecretStr("sk-supersecret-1234567890"),
            ai_endpoint="https://api.example.com/v1",
            ai_model="M2.7",
        )
        mock_get.return_value = s

        with patch.dict("sys.modules", {"requests": _FakeRequests}):
            client = HttpAIClient()
            try:
                client.propose_labels("你好")
            except RuntimeError as exc:
                msg = str(exc)
                assert "sk-supersecret" not in msg
                assert "https://api.example.com" not in msg
                assert "echoed prompt" not in msg
                # Status code is OK to surface.
                assert "500" in msg
            else:
                pytest.fail("expected RuntimeError")
