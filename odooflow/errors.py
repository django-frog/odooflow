"""
User-facing error helpers for odooflow.

Every error path produces:
  1. A short headline (single bold line).
  2. A blank line.
  3. A numbered "What this means / What to do" block.
  4. Optional breadcrumbs that name the exact files or env vars involved.

Each helper prints a structured message and then raises a domain-specific
ConfigError so the CLI can exit cleanly with code 1 (no traceback, no
import-time crashes).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Sequence

import typer


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class ConfigError(Exception):
    """Raised for any first-run / configuration problem the user must fix."""

    exit_code = 1

    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.hint = hint


class AccessTokenMissingError(ConfigError):
    """Raised when no access token is available from env or rc."""

    def __init__(self, rc_path: Path):
        super().__init__(
            "No GitLab access token is configured.",
            hint=(
                f"Set the ODOOFLOW_ACCESS_TOKEN environment variable or add "
                f"an `access_token` entry to {rc_path}. "
                f"You can run `odooflow setup` to do this interactively."
            ),
        )
        self.rc_path = rc_path


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _emit(headline: str, lines: Sequence[str], hint: Optional[str] = None) -> None:
    """Pretty-print a structured error block to stderr."""
    out = sys.stderr
    out.write("\n")
    out.write(f"  {headline}\n")
    out.write("\n")
    for line in lines:
        out.write(f"  {line}\n")
    if hint:
        out.write("\n")
        out.write(f"  {hint}\n")
    out.write("\n")
    out.flush()


def _die(message: str, hint: Optional[str] = None, code: int = 1) -> None:
    """Print a structured message and exit the process with a clean code."""
    _emit(message, [], hint)
    raise typer.Exit(code)


def _safe_exit(exc: ConfigError) -> None:
    """Convert a ConfigError into a clean CLI exit."""
    _emit(str(exc), [], exc.hint)
    raise typer.Exit(exc.exit_code)


# --------------------------------------------------------------------------- #
# Specific error reports
# --------------------------------------------------------------------------- #


def config_file_missing(path: Path) -> None:
    """
    No ~/.odooflowrc yet. Not fatal: defaults are used. Print one quiet hint.
    """
    _emit(
        "No configuration file found.",
        [
            f"  Expected:  {path}",
            f"  Using:     built-in defaults",
            "",
            "  Tip: run `odooflow setup` once to create it interactively.",
        ],
    )


def config_unreadable(path: Path, reason: str, backup: Optional[Path]) -> None:
    _emit(
        f"Could not read configuration file: {path}",
        [
            f"  Reason:    {reason}",
            (
                f"  Recovered: defaults (backup at {backup})"
                if backup
                else "  Recovered: defaults (no backup could be created)"
            ),
            "",
            "  Fix it:",
            f"    1. Check permissions on {path}.",
            "    2. Re-run the command; if it keeps failing, delete the file",
            "       and run `odooflow setup` to recreate it.",
        ],
    )


def config_empty(path: Path, backup: Optional[Path]) -> None:
    _emit(
        f"Configuration file is empty: {path}",
        [
            "  The file exists but contains no JSON.",
            (
                f"  Backup:   {backup}"
                if backup
                else "  No backup was made (rename failed)."
            ),
            "",
            "  Fix it (pick one):",
            f"    1. Open {path} in your editor and paste valid JSON.",
            "    2. Run `odooflow setup` to recreate it interactively.",
            "    3. Delete the file; odooflow will use defaults next time.",
        ],
    )


def config_corrupt(path: Path, reason: str, backup: Optional[Path]) -> None:
    _emit(
        f"Configuration file is corrupted: {path}",
        [
            f"  JSON error: {reason}",
            (
                f"  Backup:     {backup}"
                if backup
                else "  Backup:     <rename failed, see above>"
            ),
            "",
            "  odooflow will continue with built-in defaults so you are not",
            "  blocked, but the missing values (GitLab URL, core modules, etc.)",
            "  will fall back to Odoo's defaults.",
            "",
            "  Fix it (pick one):",
            f"    1. Open {path} in your editor, fix the JSON, save the file.",
            f"    2. Restore from {backup} if you have a recent good copy." if backup else "",
            "    3. Delete the file and run `odooflow setup` to recreate it.",
        ],
    )


def config_shape_wrong(path: Path, backup: Optional[Path]) -> None:
    _emit(
        f"Configuration file is not a JSON object: {path}",
        [
            "  The top-level value should be a JSON object ({...}), not a list",
            "  or scalar.",
            (
                f"  Backup:   {backup}"
                if backup
                else "  Backup:   <rename failed, see above>"
            ),
            "",
            "  Fix it:",
            "    1. Edit the file so it starts with `{` and ends with `}`.",
            "    2. Or delete the file and run `odooflow setup`.",
        ],
    )


def config_missing_keys(path: Path, missing: Sequence[str]) -> None:
    """Not fatal in non-strict mode, but we want to point the user at it."""
    keys = ", ".join(missing)
    _emit(
        "Configuration is missing some optional keys.",
        [
            f"  File:   {path}",
            f"  Missing: {keys}",
            "",
            "  odooflow is using built-in defaults for these. Run",
            "  `odooflow setup` to populate them.",
        ],
    )


def access_token_missing_rc_fallback() -> None:
    """
    Non-fatal-ish variant used inside worker threads. Prints guidance and
    returns (does NOT raise) so the worker pool can shut down cleanly.
    """
    typer.secho(
        "\n"
        "  ⚠  No GitLab access token found.\n"
        "  ─────────────────────────────────────────────────────────────────\n"
        "  Set ODOOFLOW_ACCESS_TOKEN in your shell, or add one to\n"
        f"  {Path.home() / '.odooflowrc'}. Run `odooflow setup` for a wizard.\n"
        "  ─────────────────────────────────────────────────────────────────\n"
    )


def access_token_missing(rc_path: Path) -> None:
    """
    Stand-alone helper when no token is found from any source. Use
    AccessTokenMissingError when you also want to abort the current command.
    """
    has_env = bool(os.getenv("ODOOFLOW_ACCESS_TOKEN"))
    _die(
        "GitLab access token not found.",
        "\n".join(
            [
                "  odooflow needs a GitLab access token to clone private modules.",
                "",
                "  Pick one of:",
                "    1. Set the environment variable for this shell session:",
                "",
                "         export ODOOFLOW_ACCESS_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx",
                "",
                "       (Add the same line to ~/.bashrc or ~/.zshrc to persist.)",
                "",
                f"    2. Add an `access_token` entry to {rc_path}.",
                "",
                "    3. Run `odooflow setup` and follow the prompts.",
                "",
                f"  Status:  env var {'set' if has_env else 'not set'}, "
                f"rc file {'present' if rc_path.exists() else 'missing'}.",
            ]
        ),
    )


def gitlab_unreachable(base_url: str, reason: str) -> None:
    _die(
        "Could not reach the GitLab API.",
        "\n".join(
            [
                f"  URL:     {base_url}",
                f"  Reason:  {reason}",
                "",
                "  Fix it:",
                "    1. Check your internet connection.",
                "    2. Confirm the gitlab_url value in your config or env var.",
                "    3. Confirm that the access token has the `api` scope and the",
                "       `read_api` permission.",
            ]
        ),
    )


def clone_failed(module: str, reason: str) -> None:
    _emit(
        f"Could not clone '{module}'.",
        [
            f"  Reason: {reason}",
            "",
            "  Common causes:",
            "    * Wrong or missing access token (run `odooflow setup`).",
            "    * Module is private and your token lacks visibility.",
            "    * Branch name was wrong (default branch is `main`; use --branch).",
            "    * Network interruption (retry).",
        ],
    )


def dependency_unresolved(module: str) -> None:
    _emit(
        f"Could not resolve dependency '{module}'.",
        [
            "  GitLab returned no matching project.",
            "",
            "  Fix it:",
            f"    * Confirm the module '{module}' exists in your GitLab group.",
            "    * Update the gitlab_url in your config if your group moved.",
            "    * Or pin gitlab_url in ~/.odooflowrc explicitly.",
        ],
    )


__all__ = [
    "ConfigError",
    "AccessTokenMissingError",
    "config_file_missing",
    "config_unreadable",
    "config_empty",
    "config_corrupt",
    "config_shape_wrong",
    "config_missing_keys",
    "access_token_missing",
    "access_token_missing_rc_fallback",
    "gitlab_unreachable",
    "clone_failed",
    "dependency_unresolved",
] 
