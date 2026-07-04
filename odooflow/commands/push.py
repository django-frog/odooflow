import typer
from pathlib import Path
from typing import Optional
from git import Repo, GitCommandError
import getpass

from odooflow import config_manager
from odooflow.utils.env import read_env_file
from odooflow.utils.ssh import upload_directory_via_ssh


EXCLUDED_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".pytest_cache", ".env", ".odooflowrc", ".odooflow.env.json"}

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



def push_command(
    server_name: Optional[str] = None,
    remote_only: bool = False,
    exec_cmd: Optional[str] = None,
):
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
        repo_config = remote_config.get("repo", {})
        if not repo_config:
            typer.secho(f"❌ No repo config provided", fg="red")
            raise typer.Exit(1)
        repo_url = remote_config.get("repo")
        branch = remote_config.get("branch")

        try:
            repo = Repo(cwd)
            if repo.head.is_detached:
                typer.secho("❌ Git repository is in a detached HEAD state. Cannot push.", fg="red")
                raise typer.Exit(1)
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

    # Resolve the active server profile (named or legacy single).
    from odooflow.utils import server_profile as _sp
    active_name, server = _sp.select_profile(env, requested_name=server_name)
    if active_name:
        typer.secho(f"📡 Using server profile '{active_name}'.", fg="cyan")

    if not server:
        typer.secho("⚠️  No server config found for this module. Skipping upload.", fg="yellow")
        raise typer.Exit(0)

    required_keys = ["host", "user", "directory"]
    if not all(k in server for k in required_keys):
        typer.secho(
            f"❌ Incomplete server config. Required keys: {', '.join(required_keys)}",
            fg="red",
        )
        typer.secho(
            "  Tip: run `odooflow server show"
            + (f' {active_name}' if active_name else '')
            + "` or `odooflow server add <name>` to fix it.",
            fg="cyan",
        )
        raise typer.Exit(1)

    key_path = server.get("key") or server.get("key_path")
    password = server.get("password")
    if not key_path and not password:
        password = getpass.getpass("🔑 Enter SSH password: ")

    final_exec_cmd = exec_cmd or server.get("post_push_cmd")

    def _report_post_exec(stdout_text: str, stderr_text: str, exit_status: int):
        if stdout_text:
            typer.secho(stdout_text, fg="cyan")
        if exit_status != 0:
            typer.secho(
                f"❌ Post-upload command failed (exit {exit_status}): {stderr_text.strip() or '(no stderr)'}",
                fg="red",
                bold=True,
            )
            raise typer.Exit(1)

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
            exclude_dirs=excluded_dirs,
            post_exec_cmd=final_exec_cmd,
            on_post_exec=_report_post_exec if final_exec_cmd else None,
        )
        typer.secho("✅ Project uploaded successfully.", fg="green")
    except Exception as e:
        typer.secho(f"❌ Upload failed: {e}", fg="red")
        raise typer.Exit(1)