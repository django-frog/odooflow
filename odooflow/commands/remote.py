import typer
import json

from pathlib import Path
from rich import print
from typing import Optional, List
from git import Repo, InvalidGitRepositoryError

from odooflow import config_manager, errors
from odooflow.utils.env import write_env_file, read_env_file


ALLOWED_SERVER_KEYS = {
    "host",
    "port",
    "user",
    "password",
    "key_path",
    "directory",
}


def parse_kv_pairs(pairs: List[str]) -> dict:
    parsed = {}
    for pair in pairs:
        if "=" not in pair:
            print(f"[red]Invalid format: {pair}. Use key=value.[/red]")
            continue
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()

        if key not in ALLOWED_SERVER_KEYS:
            print(
                f"[yellow]⚠️ Ignoring unknown key: '{key}'. "
                f"Allowed keys are: {', '.join(ALLOWED_SERVER_KEYS)}[/yellow]"
            )
            continue

        parsed[key] = value
    return parsed


def get_current_branch() -> Optional[str]:
    try:
        repo = Repo(".")
        if repo.head.is_detached:
            errors._emit(
                "Git HEAD is in a detached state.",
                [
                    "  Cannot determine the active branch.",
                    "",
                    "  Fix it:",
                    "    * Check out a real branch (e.g. `git checkout main`).",
                    "    * Or pass `--branch <name>` explicitly.",
                ],
            )
            return None
        return repo.active_branch.name
    except InvalidGitRepositoryError:
        errors._emit(
            "Not inside a Git repository.",
            [
                "  `odooflow remote` needs to inspect the current branch.",
                "",
                "  Fix it:",
                "    * Run this command from inside the directory that contains",
                "      the .git folder (your project root).",
            ],
        )
        return None


def remote(
    add_repo: Optional[str] = typer.Option(None),
    branch: Optional[str] = typer.Option(None),
    server_json: Optional[str] = typer.Option(None),
):
    cfg = config_manager.load_config(strict=False)
    env_filename = cfg.get("env_file", ".odooflow.env.json")
    env_path = Path.cwd() / env_filename

    if not env_path.exists():
        errors._emit(
            "Environment file not found.",
            [
                f"  Expected:  {env_path}",
                "",
                "  Fix it:",
                "    * Run `odooflow init` first to create it from __manifest__.py.",
                "    * Or run `odooflow sync-env` after a valid manifest is in place.",
            ],
        )
        raise typer.Exit(code=1)

    env = read_env_file(env_path)
    if env == {} and not env_path.exists():
        return

    if not env and env_path.exists():
        errors._emit(
            "Environment file exists but is empty or unreadable.",
            [
                f"  File:   {env_path}",
                "",
                "  Fix it:",
                "    * Open the file and confirm it contains valid JSON, or",
                "    * Delete the file and run `odooflow init` to recreate it.",
            ],
        )
        raise typer.Exit(code=1)

    updated = False

    if add_repo:
        current_branch = branch or get_current_branch()
        if not current_branch:
            errors._emit(
                "Cannot determine the current Git branch.",
                [
                    "  Fix it:",
                    "    * Pass it explicitly:  `--branch 17.0` (or whatever your branch is).",
                ],
            )
            raise typer.Exit(code=1)

        env.setdefault("remotes", {})
        if "repo" in env["remotes"]:
            typer.secho("⚠️  Remote repo already configured.", fg="yellow")
            if typer.confirm("Overwrite the existing Git remote info?"):
                env["remotes"]["repo"] = {"url": add_repo, "branch": current_branch}
                updated = True
        else:
            env["remotes"]["repo"] = {"url": add_repo, "branch": current_branch}
            updated = True
        typer.secho(f"🔗 Git remote set to {add_repo} (branch: {current_branch})", fg="green")

    if server_json:
        try:
            server_config = json.loads(server_json)
        except json.JSONDecodeError as e:
            errors._emit(
                "Server config JSON is invalid.",
                [
                    f"  Reason: {e}",
                    "",
                    "  Fix it:",
                    "    * Wrap the JSON in single quotes at the shell, e.g.",
                    "      `odooflow remote --server-json '{\"host\":\"...\",\"port\":22,...}'`.",
                ],
            )
            raise typer.Exit(code=1)

        if not isinstance(server_config, dict):
            errors._emit(
                "Server config must be a JSON object.",
                [
                    "  Expected:  `{ \"host\": \"...\", ... }`",
                    f"  Got:       {type(server_config).__name__}",
                ],
            )
            raise typer.Exit(code=1)

        invalid_keys = [key for key in server_config if key not in ALLOWED_SERVER_KEYS]
        if invalid_keys:
            typer.secho(
                f"⚠️  Ignoring unknown keys: {', '.join(invalid_keys)}",
                fg="yellow",
            )
            for key in invalid_keys:
                server_config.pop(key)

        env.setdefault("remotes", {})
        if "server" in env["remotes"]:
            typer.secho("⚠️  Remote server already configured.", fg="yellow")
            if typer.confirm("Overwrite the existing server connection info?"):
                env["remotes"]["server"] = server_config
                updated = True
        else:
            env["remotes"]["server"] = server_config
            updated = True

        typer.secho("🌐 Server connection info saved.", fg="green")

    if updated:
        write_env_file(env_path, env)
        typer.secho("💾 Remote configuration updated.", fg="green")
    elif not (add_repo or server_json):
        typer.secho(
            "ℹ️  No options provided. Run `odooflow remote --help` to see flags.",
            fg="yellow",
        )
