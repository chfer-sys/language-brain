"""Tests for SPEC §6 AC30 — API key is read from .env only and
never appears in source, tests, or logs.

T9 already covers:
- source-grep: no module imports ``requests`` outside ai_client.py
- pre-commit guard runs clean on the current tree
- RuntimeError from HttpAIClient does not leak key value

AC30 specifically requires:
- the pre-commit hook is INSTALLED and FIRES on a bad commit
- a real ``.env`` file's key value never enters logs at any level

This test file fills those gaps.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Pre-commit hook is wired and fires
# ---------------------------------------------------------------------------


def test_pre_commit_hook_is_installed() -> None:
    """The hook at ``.git/hooks/pre-commit`` is a symlink to the
    secret guard."""
    hook = REPO_ROOT / ".git" / "hooks" / "pre-commit"
    assert hook.is_file() or hook.is_symlink(), (
        f"pre-commit hook missing at {hook}. AC30 requires the guard "
        f"to run on every commit."
    )
    if hook.is_symlink():
        # It's a symlink to scripts/check_no_secrets.sh.
        target = os.readlink(hook)
        assert target.endswith("scripts/check_no_secrets.sh"), (
            f"pre-commit symlink points to {target!r}, expected "
            f"scripts/check_no_secrets.sh"
        )


def test_pre_commit_hook_rejects_a_leaked_key(tmp_path: Path) -> None:
    """If a tracked file contains a sk- token, the hook exits 1.

    We invoke the hook script directly (not via ``git commit``)
    so the test doesn't depend on a clean git index or staged
    files. The script's behavior is what matters.

    The offending token is constructed at runtime so the test file
    itself doesn't contain a literal that the regex would catch
    when the guard scans tracked files.
    """
    script = REPO_ROOT / "scripts" / "check_no_secrets.sh"
    assert script.is_file()

    # Build the offending token at runtime. The prefix is fixed by
    # the secret-leak convention; the suffix is long enough to
    # exceed the 16-char threshold in the regex.
    offending_prefix = "sk"
    offending_suffix = "-" + "supersecretvalue" + "1234567890" + "abcdef"
    offending_token = offending_prefix + offending_suffix

    # Build a tiny repo with a single offending file. The script
    # only reads ``git ls-files`` (or falls back to find).
    repo = tmp_path / "leaky-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "leaky.py").write_text(
        f'API_KEY = "{offending_token}"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "leaky.py"], cwd=repo, check=True)

    # Run the script against this repo. It uses git ls-files, so
    # the file must be tracked.
    result = subprocess.run(
        ["bash", str(script)],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, (
        "AC30 violated: pre-commit guard did not reject a file "
        "containing an sk- token."
    )
    assert offending_prefix + "-" in result.stdout + result.stderr


def test_pre_commit_hook_accepts_clean_repo(tmp_path: Path) -> None:
    """A repo with no leaked secrets passes the guard."""
    script = REPO_ROOT / "scripts" / "check_no_secrets.sh"
    repo = tmp_path / "clean-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "safe.py").write_text(
        "# Just a normal comment mentioning the env var name\n"
        'KEY = os.environ["LANGUAGE_BRAIN_AI_KEY"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "safe.py"], cwd=repo, check=True)
    result = subprocess.run(
        ["bash", str(script)],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"clean repo rejected by guard:\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Real .env file: the key value never enters logs
# ---------------------------------------------------------------------------


def test_real_env_key_does_not_appear_in_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Set a real-looking AI key in the environment, exercise every
    code path that touches it (configure_root_logger, get_settings,
    HttpAIClient.propose_labels failure path), and assert the key
    value never appears in any log record's formatted text.

    The sentinel key is built at runtime so the test file itself
    doesn't trip the pre-commit guard's regex.
    """
    sentinel_key = "sk" + "-" + "thisistherealkey" + "1234567890" + "abcdef"
    monkeypatch.setenv("LANGUAGE_BRAIN_AI_KEY", sentinel_key)
    # Clear the settings cache so get_settings() picks up the new key.
    from api import config as config_module
    from api.services import ai_client as ai_client_module

    config_module.get_settings.cache_clear()
    ai_client_module.get_settings.cache_clear()

    with caplog.at_level(logging.DEBUG):
        # Exercise the logger configuration.
        config_module.configure_root_logger()
        # Read settings; this also logs a "vault=/..." debug line.
        s = config_module.get_settings()
        assert s.ai_key is not None
        # The debug summary is log-safe.
        log = logging.getLogger("test.no_network.config")
        log.debug("debug summary: %s", s.debug_summary())
        # The factory logs the choice of client.
        ai_client_module.reset_ai_client_singleton()
        _ = ai_client_module.get_ai_client()
        # The HttpAIClient.propose_labels path raises (no key transport
        # because we didn't patch requests) — but with the key set, it
        # proceeds past the key check. Force a transport error by
        # pointing at an invalid endpoint.
        ai_client_module.reset_ai_client_singleton()
        client = ai_client_module.HttpAIClient(endpoint="http://no.such.host.invalid:1")
        try:
            client.propose_labels("你好")
        except (RuntimeError, Exception):  # noqa: BLE001
            pass

    # Now assert: the sentinel key value never appears in any captured
    # log record.
    full_log = caplog.text
    assert sentinel_key not in full_log, (
        f"AC30 violated: the AI key value appeared in logs:\n{full_log}"
    )


def test_real_env_key_unset_does_not_invent_one() -> None:
    """If the env var is unset, the key is None. The system never
    invents a placeholder."""
    from api import config as config_module

    os.environ.pop("LANGUAGE_BRAIN_AI_KEY", None)
    config_module.get_settings.cache_clear()
    s = config_module.get_settings()
    assert s.ai_key is None


# ---------------------------------------------------------------------------
# README documents the .env flow
# ---------------------------------------------------------------------------


def test_readme_documents_env_var() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    # The README must mention the env var by name AND tell the user
    # how to set it.
    assert "LANGUAGE_BRAIN_AI_KEY" in readme
    # And the vault env var.
    assert "LANGUAGE_BRAIN_VAULT" in readme


def test_env_example_provides_template() -> None:
    """A .env.example exists and contains the env var name with a
    placeholder value, not a real key."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "LANGUAGE_BRAIN_AI_KEY" in example
    # The placeholder must not look like a real key. We check the
    # prefix only — the actual examples may use any suffix.
    assert "sk-" not in example.split("=")[1] if "=" in example else True  # noqa
    # And there must be some kind of placeholder pattern.
    assert (
        "sk-replace-me" in example
        or "<your-key>" in example
        or "..." in example
    )


# ---------------------------------------------------------------------------
# .env file in working tree is not committed
# ---------------------------------------------------------------------------


def test_dot_env_file_is_gitignored() -> None:
    """``.env`` is in .gitignore so it cannot be committed by accident."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    # The .gitignore must contain a rule that matches ".env" or "*.env" or ".env.*".
    assert any(
        line.strip() in (".env", "*.env", ".env.*")
        or line.strip().startswith(".env")
        for line in gitignore.splitlines()
    ), (
        "AC30 violated: .gitignore does not contain a rule for .env. "
        "Without this, a real key in .env could be committed by accident."
    )


def test_dot_env_not_in_git_ls_files() -> None:
    """Even if .env exists on disk, it must not be tracked."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = result.stdout.splitlines()
    assert ".env" not in tracked, (
        "AC30 violated: .env is tracked by git. This would expose the "
        "AI key in the repository history."
    )
