import typer
import json

from pathlib import Path
from rich import print
from typing import Optional, List
from git import Repo, InvalidGitRepositoryError

from odooflow import config_manager
from odooflow.utils.env import write_env_file, read_env_file

config = config_manager.load_config()
ENV_FILENAME = config["env_file"]


ALLOWED_SERVER_KEYS = {
    "host", 
    "port", 
    "user", 
    "password", # For SSH connection 
    "key_path", # For SSH connection
    "directory"
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
            print(f"[yellow]⚠️ Ignoring unknown key: '{key}'. Allowed keys are: {', '.join(ALLOWED_SERVER_KEYS)}[/yellow]")
            continue

        parsed[key] = value
    return parsed


def get_current_branch() -> Optional[str]:
    try:
        repo = Repo(".")
        if repo.head.is_detached:
            print("[yellow]Warning: HEAD is in a detached state.[/yellow]")
            return None
        return repo.active_branch.name
    except InvalidGitRepositoryError:
        print("[red]Error: Not a Git repository.[/red]")
        return None
    except Exception as e:
        print(f"[red]Error while determining Git branch:[/red] {e}")
        return None


def remote(
    add_repo: Optional[str] = typer.Option(None),
    branch: Optional[str] = typer.Option(None),
    server_json: Optional[str] = typer.Option(None)
):
    updated = False
    env_path = Path.cwd() / ENV_FILENAME

    if not env_path.exists():
        typer.secho(f"❌ environment file ({ENV_FILENAME}) is not found in the current directory.", fg="red")
        raise typer.Exit(code=1)

    env = read_env_file(env_path)

    # Handle Git remote
    if add_repo:
        current_branch = branch or get_current_branch()
        if not current_branch:
            typer.secho("❌ Failed to detect branch. Please specify it with --branch.", fg="red")
            raise typer.Exit()

        env.setdefault("remotes", {})

        if "repo" in env["remotes"]:
            typer.secho("⚠️ Remote repo already configured.", fg="yellow")
            if not typer.confirm("Do you want to overwrite the existing Git remote info?"):
                typer.secho("❌ Skipped updating Git remote.", fg="red")
            else:
                env["remotes"]["repo"] = {
                    "url": add_repo,
                    "branch": current_branch
                }
                updated = True
        else:
            env["remotes"]["repo"] = {
                "url": add_repo,
                "branch": current_branch
            }
            updated = True
        typer.secho(f"🔗 Git remote set to {add_repo} (branch: {current_branch})", fg="green")

    # Handle server connection via JSON
    if server_json:
        try:
            server_config = json.loads(server_json)
        except json.JSONDecodeError:
            typer.secho("❌ Invalid JSON format for server config.", fg="red")
            raise typer.Exit(code=1)

        # Validate allowed keys
        invalid_keys = [key for key in server_config if key not in ALLOWED_SERVER_KEYS]
        if invalid_keys:
            typer.secho(f"⚠️ Ignoring unknown keys: {', '.join(invalid_keys)}", fg="yellow")
            for key in invalid_keys:
                server_config.pop(key)

        env.setdefault("remotes", {})

        if "server" in env["remotes"]:
            typer.secho("⚠️ Remote server already configured.", fg="yellow")
            if not typer.confirm("Do you want to overwrite the existing server connection info?"):
                typer.secho("❌ Skipped updating server connection.", fg="red")
            else:
                env["remotes"]["server"] = server_config
                updated = True
        else:
            env["remotes"]["server"] = server_config
            updated = True

        typer.secho("🌐 Server connection info saved.", fg="green")

    if updated:
        write_env_file(env_path, env)
        typer.secho("💾 Remote configuration updated successfully.", fg="green")
    elif not (add_repo or server_json):
        typer.secho("ℹ️ No options provided. Use --help to see available flags.", fg="yellow")
