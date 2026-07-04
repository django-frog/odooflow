"""
First-run / reconfiguration wizard. Pure CLI: no external IO beyond the rc.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from odooflow import config_manager, errors


def _ask(label: str, default: str, hide: bool = False, required: bool = True) -> str:
    """
    Ask for one value. If `hide=True`, input is masked (used for tokens).
    Returns the entered value (or the default on EOF / non-TTY).
    """
    prompt_kwargs = {"default": default} if default else {}
    if hide:
        value = typer.prompt(label, hide_input=True, **prompt_kwargs)
    else:
        value = typer.prompt(label, **prompt_kwargs)
    value = (value or "").strip()
    if required and not value:
        typer.secho("  (value left empty; using default)", fg="yellow")
        value = default
    return value


def setup():
    """
    Interactive setup wizard. Writes a clean ~/.odooflowrc.

    Resolution order for values, so the user never has to type the same thing
    twice:
      1. Existing ODOOFLOW_ACCESS_TOKEN env var.
      2. Existing access_token in ~/.odooflowrc.
      3. Interactive prompt.
    """
    rc_path = config_manager.get_global_config_path()
    typer.secho("")
    typer.secho("┌─ odooflow first-run setup", fg="cyan", bold=True)
    typer.secho("│  I'll write ~/.odooflowrc so future commands just work.", fg="cyan")
    typer.secho("")

    try:
        existing = config_manager.load_config(strict=True)
    except errors.ConfigError:
        existing = config_manager.DEFAULT_CONFIG.copy()
    except Exception:
        existing = config_manager.DEFAULT_CONFIG.copy()

    existing_token = os.getenv("ODOOFLOW_ACCESS_TOKEN") or existing.get("access_token", "")
    existing_gitlab = existing.get("gitlab_url", config_manager.DEFAULT_CONFIG["gitlab_url"])

    typer.secho(
        "Step 1/3 — GitLab access token.",
        fg="cyan",
    )
    if existing_token:
        typer.secho(
            f"  Detected an existing token ({'*' * min(len(existing_token), 8)}…). "
            "Press Enter to keep it.",
            fg="green",
        )
    typer.secho(
        "  Create one at:  GitLab → Preferences → Access Tokens\n"
        "  Required scopes:  api, read_api, write_repository.\n",
        fg="cyan",
    )
    token_default = existing_token or ""
    access_token = _ask("Access token", token_default, hide=True, required=False)

    typer.secho("")
    typer.secho("Step 2/3 — GitLab URL.", fg="cyan")
    typer.secho(
        "  Press Enter to accept the default; type the URL of your self-hosted\n"
        "  GitLab if you are not using gitlab.com.\n",
        fg="cyan",
    )
    gitlab_url = _ask("GitLab URL", existing_gitlab, required=True)

    typer.secho("")
    typer.secho("Step 3/3 — Core modules (skipped during deep clones).", fg="cyan")
    typer.secho(
        "  Comma-separated, e.g.  base,web,mail,sale,account\n",
        fg="cyan",
    )
    default_core = ",".join(
        existing.get("core_modules", config_manager.DEFAULT_CONFIG["core_modules"])
    )
    core_modules_raw = _ask("Core modules", default_core, required=False)
    core_modules = [m.strip() for m in core_modules_raw.split(",") if m.strip()]

    new_config = {
        **existing,
        "gitlab_url": gitlab_url,
        "core_modules": core_modules or config_manager.DEFAULT_CONFIG["core_modules"],
    }
    if access_token:
        new_config["access_token"] = access_token

    config_manager.save_config(new_config)
    os.chmod(rc_path, 0o600)

    typer.secho("")
    typer.secho(f"✓ Wrote {rc_path}", fg="green", bold=True)
    typer.secho(
        f"  Token stored:       {'yes' if access_token else 'no (set ODOOFLOW_ACCESS_TOKEN instead)'}",
        fg="green",
    )
    typer.secho(f"  GitLab URL:         {gitlab_url}", fg="green")
    typer.secho(
        f"  Core modules:       {', '.join(new_config['core_modules'])}",
        fg="green",
    )
    typer.secho("")
    typer.secho(
        "Next: try  `odooflow clone --url <your gitlab module url>` from inside your",
        fg="cyan",
    )
    typer.secho(
        "project. Run  `odooflow --help`  any time for the full command list.",
        fg="cyan",
    )
    typer.secho("")


__all__ = ["setup"]
