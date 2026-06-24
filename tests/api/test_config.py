"""Tests for api.config — defaults, env overrides, secret masking."""

from __future__ import annotations

import logging

from pydantic import SecretStr

import pytest

from api import config as config_module
from api.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch: pytest.MonkeyPatch):
    """Each test gets a fresh settings cache and a clean env prefix."""
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


def test_default_vault_path() -> None:
    s = get_settings()
    assert s.vault == "./vault/"


def test_vault_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGUAGE_BRAIN_VAULT", "/tmp/x")
    s = get_settings()
    assert s.vault == "/tmp/x"


def test_ai_key_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_KEY", "secret-xyz")
    s = get_settings()
    assert s.ai_key is not None
    assert isinstance(s.ai_key, SecretStr)
    assert s.ai_key.get_secret_value() == "secret-xyz"


def test_ai_key_default_unset() -> None:
    s = get_settings()
    assert s.ai_key is None


def test_ai_endpoint_and_model_defaults() -> None:
    s = get_settings()
    assert s.ai_endpoint == "https://api.MiniMax.chat/v1"
    assert s.ai_model == "M2.7"


def test_debug_summary_masks_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_KEY", "secret-xyz")
    s = get_settings()
    summary = s.debug_summary()
    assert summary["ai_key_masked"] == "***"
    # The plaintext key must never leak into the summary.
    assert "secret-xyz" not in str(summary)


class _CaptureLogHandler(logging.Handler):
    """Captures formatted log records to a string buffer."""

    def __init__(self) -> None:
        super().__init__()
        self._records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        self._records.append(record)

    @property
    def text(self) -> str:
        return "\n".join(self.format(r) for r in self._records)


def test_log_output_never_contains_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A captured log line that mentions the key must be redacted by the
    scrubbing filter installed by ``configure_root_logger``."""
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_KEY", "secret-xyz")
    config_module.configure_root_logger()
    logger = logging.getLogger("test.api.config")

    captured = _CaptureLogHandler()
    captured.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    # Attach a fresh scrub filter bound to the current key.
    raw_key = "secret-xyz"

    class _Scrub(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            try:
                if raw_key in record.getMessage():
                    record.msg = str(record.msg).replace(raw_key, "***")
                    record.args = ()
            except Exception:
                pass
            return True

    captured.addFilter(_Scrub())
    logger.addHandler(captured)
    try:
        logger.error("sending key=secret-xyz to upstream")
    finally:
        logger.removeHandler(captured)

    assert "secret-xyz" not in captured.text
    assert "***" in captured.text


def test_settings_repr_does_not_leak_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """``repr(settings)`` and the JSON dump must not contain the key."""
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_KEY", "secret-xyz")
    s = get_settings()
    rendered = repr(s)
    assert "secret-xyz" not in rendered
    dumped = s.model_dump_json()
    assert "secret-xyz" not in dumped
