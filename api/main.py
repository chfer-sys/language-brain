"""FastAPI entry point — minimal stub for T0.

The full app, routes, and middleware are added in later tasks. This
file exists so that ``uvicorn api.main:app`` and the
``language-brain-api`` console script have a working target during
scaffolding.
"""

from __future__ import annotations

# MUST come first: loads .env before api.config.settings is
# constructed (otherwise the Settings lru_cache captures an empty
# environment and the AI key is never seen).
import api.bootstrap  # noqa: F401, E402

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import configure_root_logger, settings
from api.routes import add_sentence as add_sentence_route
from api.routes import commit_sentence as commit_sentence_route
from api.routes import pinyin as pinyin_route
from api.routes import search as search_route
from api.routes import units as units_route

configure_root_logger()

app = FastAPI(
    title="Language Brain API",
    version="0.1.0",
    description=(
        "Local-first knowledge graph of Chinese language units. "
        "See .specs/language-brain.md for the full design."
    ),
)

# CORS for the SvelteKit dev server (B6 — UI brick). The frontend
# runs on http://localhost:5173 (vite default) during development;
# in production the frontend is served from the same origin as the
# API, so this middleware is a no-op. We allow a small set of local
# dev origins explicitly — ``allow_origins=["*"]`` is intentionally
# not used so the production posture is not accidentally widened.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",  # vite preview
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# T7: register the propose-labels route. T19 adds the commit-sentence
# route on the same prefix; T20 adds the search route on its own
# ``/api`` prefix so the full path is ``/api/search``.
app.include_router(add_sentence_route.router)
app.include_router(commit_sentence_route.router)
app.include_router(search_route.router)
app.include_router(units_route.router)
app.include_router(pinyin_route.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe — returns the configured vault path (no secrets)."""
    return {
        "status": "ok",
        "vault": settings.vault,
        "ai_model": settings.ai_model,
        "mock_mode": "true" if settings.ai_key is None else "false",
    }


def run() -> None:
    """Console-script entry point: ``language-brain-api``."""
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
