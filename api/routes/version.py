"""GET /api/version — identify what version/branch/commit is running."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

router = APIRouter()


def _git_cmd(cmd: list[str], fallback: str = "unknown") -> str:
    """Run a git command, returning fallback on any error (e.g. git not installed, or
    not a git repo — common in production containers)."""
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return fallback


# ponytail: computed once at module import (process lifetime cache).
# Fallback chain: git → env var → "unknown".
_VERSION: dict[str, str] = {
    "version": os.environ.get("LANGUAGE_BRAIN_VERSION") or "0.9.0",
    "git_commit": _git_cmd(["git", "rev-parse", "--short", "HEAD"]),
    "git_branch": _git_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
}


def get_version_info() -> dict[str, Any]:
    """Return version, git_commit, and git_branch for this process.

    Fallback chain for git_commit/git_branch:
      1. ``git rev-parse`` at startup  (works in dev / git-cloned containers)
      2. ``LANGUAGE_BRAIN_GIT_COMMIT`` / ``LANGUAGE_BRAIN_GIT_BRANCH`` env vars
         (allows production containers to override without git installed)
      3. "unknown" if neither is available
    """
    return {
        "version": _VERSION["version"],
        "git_commit": os.environ.get("LANGUAGE_BRAIN_GIT_COMMIT") or _VERSION["git_commit"],
        "git_branch": os.environ.get("LANGUAGE_BRAIN_GIT_BRANCH") or _VERSION["git_branch"],
    }


@router.get("/api/version")
def version_endpoint() -> dict[str, Any]:
    """Return version metadata including git info and a build timestamp."""
    info = get_version_info()
    info["python_version"] = __import__("sys").version.split()[0]
    info["timestamp"] = datetime.now(timezone.utc).isoformat()
    return info
