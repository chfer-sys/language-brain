"""FastAPI entry point — minimal stub for T0.

The full app, routes, and middleware are added in later tasks. This
file exists so that ``uvicorn api.main:app`` and the
``language-brain-api`` console script have a working target during
scaffolding.
"""

from __future__ import annotations

from fastapi import FastAPI

from api.config import configure_root_logger, settings
from api.routes import add_sentence as add_sentence_route
from api.routes import commit_sentence as commit_sentence_route

configure_root_logger()

app = FastAPI(
    title="Language Brain API",
    version="0.1.0",
    description=(
        "Local-first knowledge graph of Chinese language units. "
        "See .specs/language-brain.md for the full design."
    ),
)

# T7: register the propose-labels route. T19 adds the commit-sentence
# route on the same prefix; the search routes (T20+) are added in later
# tasks. Both routers share the ``/api/sentences`` prefix, so the commit
# endpoint is reachable at ``/api/sentences/commit``.
app.include_router(add_sentence_route.router)
app.include_router(commit_sentence_route.router)


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
