"""Bootstrap module — loaded first to set up process-wide config.

The trick is import order: ``api.main`` does
``from api.config import settings``, and ``api.config.settings``
calls ``get_settings()`` (which is lru_cached) at import time. If
we don't load .env BEFORE that import runs, ``Settings()`` is
constructed from an empty environment and the result is cached.

So we ``import api.bootstrap`` at the very top of ``api.main``,
which:
  1. loads .env from the project root
  2. clears the Settings lru_cache so the next access constructs
     a fresh Settings() with the now-populated environment
  3. pre-warms settings so all subsequent imports see the right values
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOTENV_PATH = _PROJECT_ROOT / ".env"

# Load .env. ``override=False`` means real process env vars (set
# via `export`, `docker run -e`, etc.) win over .env values. This
# matches the standard 12-factor pattern.
load_dotenv(dotenv_path=_DOTENV_PATH, override=False)

# Now that the env is populated, clear the cached Settings() (if it
# was constructed during api.config import) and pre-warm it.
import api.config as _config  # noqa: E402

_config.get_settings.cache_clear()
_settings = _config.get_settings()