import typer
from pathlib import Path
from git import Repo, GitCommandError
import getpass

from odooflow import config_manager
from odooflow.utils.env import read_env_file
from odooflow.utils.ssh import upload_directory_via_ssh


EXCLUDED_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".pytest_cache"}

def get_gitignore_exclusions(base_path: Path):
    gitignore_path = base_path / ".gitignore"
    exclusions = set()

    if not gitignore_path.exists():
        return exclusions

    with gitignore_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "/" in line or "*" in line:
                continue  # Skip wildcards and nested ignores for now

            exclusions.add(line.strip("/"))

    return exclusions



def push_command(remote_only: bool = False):
    cwd = Path.cwd()

    # Load config and env
    config = config_manager.load_config()
    env_path = cwd / config.get("env_file", ".env")
    env = read_env_file(env_path)

    excluded_dirs = EXCLUDED_DIRS.union(get_gitignore_exclusions(cwd))

    module_name = env.get("name")
    if not module_name:
        typer.secho("❌ Module name not found in environment file.", fg="red")
        raise typer.Exit(1)

    remote_config = env.get("remotes", {})
    if not remote_config:
        typer.secho(f"❌ No remote config found for module: {module_name}", fg="red")
        raise typer.Exit(1)

    # Git Push (if not remote only)
    if not remote_only:
        repo = remote_config.get("repo", {})
        if not repo:
            typer.secho(f"❌ No repo config provided", fg="red")
            raise typer.Exit(1)
        repo_url = remote_config.get("repo")
        branch = remote_config.get("branch")

        try:
            repo = Repo(cwd)
            active_branch = repo.active_branch.name
            branch_to_push = branch or active_branch

            typer.secho(f"🚀 Pushing branch '{branch_to_push}' to remote...", fg="cyan")
            origin = repo.remote(name="origin")
            origin.push(refspec=f"{branch_to_push}:{branch_to_push}")
            typer.secho("✅ Git push successful.", fg="green")
        except GitCommandError as e:
            typer.secho(f"❌ Git error: {e}", fg="red")
            raise typer.Exit(1)
        except Exception as e:
            typer.secho(f"❌ Unexpected Git error: {e}", fg="red")
            raise typer.Exit(1)
    else:
        typer.secho("📦 Skipping Git push (remote only mode).", fg="yellow")

    # Upload to server
    server = remote_config.get("server")
    if not server:
        typer.secho("⚠️  No server config found for this module. Skipping upload.", fg="yellow")
        raise typer.Exit(0)

    required_keys = ["host", "user", "directory"]
    if not all(k in server for k in required_keys):
        typer.secho(f"❌ Incomplete server config. Required keys: {', '.join(required_keys)}", fg="red")
        raise typer.Exit(1)

    key_path = server.get("key")
    password = None
    if not key_path:
        password = getpass.getpass("🔑 Enter SSH password: ")

    try:
        typer.secho("📤 Uploading project to the test server...", fg="cyan")
        upload_directory_via_ssh(
            local_path=cwd,
            remote_user=server["user"],
            remote_host=server["host"],
            remote_path=server["directory"],
            port=int(server.get("port", 22)),
            key_path=key_path,
            password=password,
            exclude_dirs=excluded_dirs
        )
        typer.secho("✅ Project uploaded successfully.", fg="green")
    except Exception as e:
        typer.secho(f"❌ Upload failed: {e}", fg="red")
        raise typer.Exit(1)