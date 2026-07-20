"""FastAPI entry point — minimal stub for T0.

The full app, routes, and middleware are added in later tasks. This
file exists so that ``uvicorn api.main:app`` and the
``language-brain-api`` console script have a working target during
scaffolding.
"""

from __future__ import annotations

import os

# MUST come first: loads .env before api.config.settings is
# constructed (otherwise the Settings lru_cache captures an empty
# environment and the AI key is never seen).
import api.bootstrap  # noqa: F401, E402

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import configure_root_logger, settings


class SPAStaticFiles(StaticFiles):
    """StaticFiles subclass with two responsibilities:

    1. Fall back to index.html for SPA routing — any GET that doesn't
       match an existing file returns ``index.html`` instead of 404,
       so client-side routes (e.g. ``/add``, ``/unit/S7``) work.

    2. Emit ``Cache-Control: no-cache`` on every SPA bundle response so
       browsers always re-validate the bundle with the server. The
       upstream v0.5.x deploy pipeline used heuristic caching
       (Last-Modified + ETag only, no Cache-Control), which let
       browsers hold an OLD JS bundle across deploys. Symptom: a
       fixed SPA appears still-broken to users whose browser had
       cached the pre-fix bundle. Setting ``no-cache`` (vs.
       ``max-age``) means the browser still caches locally but
       always revalidates with If-None-Match, so unchanged chunks
       get a 304 (no body), and changed chunks get the new file.
       Cost: one extra round-trip per page-load on cache misses.
       Benefit: stale bundles can never mask a deploy.
    """

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as ex:
            if ex.status_code == 404:
                # SPA fallback — serve index.html for client-side routes.
                response = await super().get_response("index.html", scope)
            else:
                raise
        # Always revalidate. The heuristic-caching default let browsers
        # hold an OLD bundle from before a deploy and miss the new code.
        # ponytail: ceiling — fine at MVP scale; revisit if/when QPS
        # warrants a `max-age=31536000, immutable` policy on the
        # content-hashed chunks (immutable/[^/]+\\..+\\.js$) and
        # `no-cache` only on index.html + version.json.
        response.headers["cache-control"] = "no-cache"
        return response


from api.routes import add_sentence as add_sentence_route
from api.routes import commit_sentence as commit_sentence_route
from api.routes import edit_sentence as edit_sentence_route
from api.routes import edit_word as edit_word_route
from api.routes import pinyin as pinyin_route
from api.routes import search as search_route
from api.routes import units as units_route
from api.routes import vault as vault_route

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
app.include_router(edit_sentence_route.router)
app.include_router(edit_word_route.router)
app.include_router(search_route.router)
app.include_router(units_route.router)
app.include_router(pinyin_route.router)
app.include_router(vault_route.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe — returns the configured vault path (no secrets)."""
    return {
        "status": "ok",
        "vault": settings.vault,
        "ai_model": settings.ai_model,
        "mock_mode": "true" if settings.ai_key is None else "false",
    }


# Serve the built SvelteKit frontend (SPA mode). Mount LAST so it doesn't
# shadow /api/* or /healthz routes. The directory is created at build time;
# if missing (API-only mode), skip.
_static_dir = os.environ.get("LANGUAGE_BRAIN_STATIC_DIR", "/app/static")
if os.path.isdir(_static_dir):
    app.mount("/", SPAStaticFiles(directory=_static_dir, html=True), name="frontend")


def run() -> None:
    """Console-script entry point: ``language-brain-api``."""
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
