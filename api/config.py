"""Application configuration for the Language Brain API.

Loads settings from environment variables (or a local ``.env`` file via
``pydantic-settings``). The AI key is treated as a secret: it is **never**
logged, printed, or included in ``repr()``. Debug logging masks it as
``"***"``.

The env-var name ``LANGUAGE_BRAIN_AI_KEY`` must never appear in
``Settings.model_dump_json()`` or any structured log output.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Runtime configuration for the API.

    All fields are populated from environment variables prefixed with
    ``LANGUAGE_BRAIN_`` (case-insensitive). Defaults are tuned for a
    local mock-mode development run.
    """

    model_config = SettingsConfigDict(
        env_prefix="LANGUAGE_BRAIN_",
        env_file=None,  # .env loaded by python-dotenv at the process level
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    vault: str = Field(
        default="./vault/",
        description="Filesystem path to the vault root.",
    )

    ai_key: SecretStr | None = Field(
        default=None,
        description=(
            "API key for the AI provider. When unset, the API runs in "
            "mock mode. Never logged or printed in cleartext."
        ),
    )

    ai_endpoint: str = Field(
        default="https://api.MiniMax.chat/v1",
        description="Base URL of the AI provider API.",
    )

    ai_model: str = Field(
        default="M2.7",
        description="Default model identifier passed to the AI provider.",
    )

    semantic_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description=(
            "Cosine-similarity cutoff for semantic search (SPEC §6 AC17). "
            "Tunable per instance via the LANGUAGE_BRAIN_SEMANTIC_THRESHOLD "
            "env var. The default 0.6 matches the SPEC; lower it (e.g. 0.4) "
            "for vaults with thin meaning fields where English queries "
            "cluster around 0.3–0.5 similarity. The route also accepts a "
            "?threshold= query param for one-off overrides."
        ),
    )

    def debug_summary(self) -> dict[str, Any]:
        """Return a log-safe summary of the settings.

        The AI key is always masked. Safe to emit at DEBUG level.
        """
        key_status = "set" if self.ai_key is not None else "unset"
        return {
            "vault": self.vault,
            "ai_key": key_status,  # never the value
            "ai_key_masked": "***" if self.ai_key is not None else None,
            "ai_endpoint": self.ai_endpoint,
            "ai_model": self.ai_model,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide singleton ``Settings`` instance."""
    return Settings()


def configure_root_logger() -> None:
    """Install a small formatter that scrubs the AI key from log records.

    Idempotent. Call once at process start.
    """
    if getattr(configure_root_logger, "_installed", False):
        return
    configure_root_logger._installed = True  # type: ignore[attr-defined]

    settings = get_settings()
    raw_key = (
        settings.ai_key.get_secret_value() if settings.ai_key is not None else None
    )

    class _KeyScrubbingFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
            try:
                msg = record.getMessage()
            except Exception:  # pragma: no cover - defensive
                return True
            if raw_key and raw_key in msg:
                record.msg = str(record.msg).replace(raw_key, "***")
                record.args = ()
            return True

    handler = logging.StreamHandler()
    handler.addFilter(_KeyScrubbingFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    # Replace any existing handlers so the scrubber always runs.
    root.handlers = [handler]
    root.setLevel(os.environ.get("LANGUAGE_BRAIN_LOG_LEVEL", "INFO"))


# Re-export for convenience.
settings = get_settings()
