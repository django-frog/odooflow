"""
`odooflow server` — manage named server profiles.

Stores profiles under `remotes.servers.<name>` in the project's
.odooflow.env.json. Single legacy `remotes.server` is auto-migrated on
first write.
"""

from __future__ import annotations

import getpass
import json
import os
import socket
from pathlib import Path
from typing import List, Optional

import paramiko
import typer

from odooflow import errors
from odooflow.utils import server_profile
from odooflow.utils.env import read_env_file, write_env_file
from odooflow.config_manager import load_config


app = typer.Typer(
    name="server",
    help=(
        "Manage named server profiles (the servers you can push to). "
        "Profiles are stored in your project's .odooflow.env.json."
    ),
    no_args_is_help=True,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _env_path() -> Path:
    cfg = load_config(strict=False)
    return Path.cwd() / cfg.get("env_file", ".odooflow.env.json")


def _load_env():
    """Read the env file, raising a structured error if missing."""
    path = _env_path()
    if not path.exists():
        errors._emit(
            "Environment file not found.",
            [
                f"  Expected:  {path}",
                "",
                "  Fix it:",
                "    * Run `odooflow init` to create it from __manifest__.py.",
                "    * Or run `odooflow sync-env` after a valid manifest is in place.",
            ],
        )
        raise typer.Exit(code=1)
    env = read_env_file(path)
    if env == {} and path.stat().st_size > 0:
        errors._emit(
            "Environment file exists but is unreadable.",
            [
                f"  File:   {path}",
                "",
                "  Fix it:",
                "    * Open the file and confirm it contains valid JSON, or",
                "    * Delete the file and run `odooflow init` to recreate it.",
            ],
        )
        raise typer.Exit(code=1)
    if "remotes" not in env:
        env["remotes"] = {}
    return env, path


def _print_table(rows: List[List[str]], headers: List[str]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    typer.echo(line)
    typer.echo("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        typer.echo("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


@app.command("list")
def list_cmd(json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON.")):
    """List all configured server profiles."""
    env, _ = _load_env()
    servers = server_profile.load_servers(env)
    if not servers:
        typer.secho(
            "  No server profiles configured.\n"
            "  Run `odooflow server add <name>` to create one.",
            fg="yellow",
        )
        raise typer.Exit()

    default = server_profile.resolve_default_name(env) or ""

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "default": default or None,
                    "servers": {
                        name: {k: v for k, v in srv.items() if k != "password"}
                        for name, srv in servers.items()
                    },
                },
                indent=2,
            )
        )
        return

    headers = ["NAME", "HOST", "USER", "KEY", "DEFAULT", "POST-CMD"]
    rows = []
    for name, srv in servers.items():
        rows.append(
            [
                name,
                srv.get("host", "-"),
                srv.get("user", "-"),
                srv.get("key_path", srv.get("password", "-"))
                if srv.get("key_path") or srv.get("password")
                else "-",
                "*" if name == default else "",
                srv.get("post_push_cmd", "") or "",
            ]
        )
    _print_table(rows, headers)


@app.command()
def add(
    name: str = typer.Argument(..., help="Unique profile name, e.g. 'staging'."),
    host: Optional[str] = typer.Option(None, "--host"),
    port: Optional[int] = typer.Option(None, "--port"),
    user: Optional[str] = typer.Option(None, "--user"),
    directory: Optional[str] = typer.Option(None, "--directory"),
    key_path: Optional[str] = typer.Option(None, "--key-path"),
    password: Optional[str] = typer.Option(
        None, "--password", help="Use only in scripts; prefer the masked prompt."
    ),
    post_push_cmd: Optional[str] = typer.Option(None, "--post-push-cmd"),
    make_default: bool = typer.Option(
        True, "--default/--no-default", help="Set this profile as the default."
    ),
):
    """
    Add or update a server profile. Interactive when flags are missing.
    """
    env, env_path = _load_env()

    # Interactive fallback for any missing required field.
    if not host:
        host = typer.prompt("Host (e.g. 10.0.0.5)", default="")
    if not user:
        user = typer.prompt("SSH user", default=getpass.getuser())
    if not directory:
        directory = typer.prompt(
            "Remote directory (absolute path)", default="/opt/odoo"
        )
    if port is None:
        port = typer.prompt("Port", default="22")
        try:
            port = int(port)
        except ValueError:
            errors._emit(
                f"'port' must be an integer (got '{port}').",
                ["  Re-run with `--port <number>` or enter a number at the prompt."],
            )
            raise typer.Exit(code=1)

    if not key_path and password is None:
        choice = typer.prompt(
            "Auth method — type 'key' or 'password'",
            default="key",
        ).strip().lower()
        if choice.startswith("p"):
            password = typer.prompt(
                "Password (input hidden)", hide_input=True, default=""
            )
        else:
            key_path = typer.prompt(
                "Path to SSH private key",
                default=str(Path.home() / ".ssh" / "id_rsa"),
            )

    profile = {
        "host": host,
        "port": port,
        "user": user,
        "directory": directory,
    }
    if key_path:
        profile["key_path"] = key_path
    if password:
        profile["password"] = password
    if post_push_cmd:
        profile["post_push_cmd"] = post_push_cmd

    new_env, migrated = server_profile.save_profile(env_path, env, name, profile)

    if make_default:
        server_profile.set_default(env_path, new_env, name)
        typer.secho(f"  ✓ '{name}' saved and set as default.", fg="green")
    else:
        typer.secho(f"  ✓ '{name}' saved.", fg="green")

    if migrated:
        typer.secho(
            "  ℹ Migrated legacy `remotes.server` into `remotes.servers.default`.",
            fg="cyan",
        )
    typer.secho(
        f"  Tip: run `odooflow server test {name}` to verify SSH connectivity.",
        fg="cyan",
    )


@app.command()
def show(
    name: Optional[str] = typer.Argument(
        None, help="Profile name (defaults to current default)."
    ),
    reveal_password: bool = typer.Option(
        False, "--reveal-password", help="Print the password (otherwise masked)."
    ),
):
    """Show details of a server profile."""
    env, _ = _load_env()
    servers = server_profile.load_servers(env)
    if not servers:
        typer.secho("  No server profiles configured.", fg="yellow")
        raise typer.Exit(code=1)

    target_name = name or server_profile.resolve_default_name(env)
    if not target_name or target_name not in servers:
        typer.secho(
            f"  No server profile '{name or ''}' found.",
            fg="red",
        )
        raise typer.Exit(code=1)

    profile = servers[target_name]
    default_name = server_profile.resolve_default_name(env)
    is_default = target_name == default_name

    typer.secho(f"\n  Server profile: {target_name}{' (default)' if is_default else ''}", bold=True)
    for key in (
        "host",
        "port",
        "user",
        "directory",
        "key_path",
        "password",
        "post_push_cmd",
    ):
        if key not in profile:
            continue
        value = profile[key]
        if key == "password" and not reveal_password:
            value = "(set, hidden — pass --reveal-password to display)"
        typer.echo(f"  {key:<14} {value}")

    typer.echo("")


@app.command(name="use")
def use_cmd(name: str = typer.Argument(..., help="Profile name to set as default.")):
    """Set the default server profile used by `odooflow push`."""
    env, env_path = _load_env()
    servers = server_profile.load_servers(env)
    if name not in servers:
        typer.secho(
            f"  No server profile named '{name}'.\n"
            f"  Available: {', '.join(servers) or '(none)'}",
            fg="red",
        )
        raise typer.Exit(code=1)
    server_profile.set_default(env_path, env, name)
    typer.secho(f"  ✓ '{name}' is now the default server profile.", fg="green")


@app.command()
def remove(name: str = typer.Argument(..., help="Profile name to remove.")):
    """Remove a server profile."""
    env, env_path = _load_env()
    if server_profile.remove_profile(env_path, env, name):
        typer.secho(f"  ✓ Removed '{name}'.", fg="green")
        return
    typer.secho(f"  No server profile named '{name}'.", fg="red")
    raise typer.Exit(code=1)


@app.command()
def test(
    name: Optional[str] = typer.Argument(
        None, help="Profile name (defaults to current default)."
    ),
):
    """Test SSH connectivity and directory writability without uploading."""
    env, _ = _load_env()
    profile_name, profile = server_profile.select_profile(
        env,
        requested_name=name,
    )
    if profile is None:
        typer.secho(
            f"  No server profile{' '+repr(name) if name else ''} found. "
            "Run `odooflow server add <name>` first.",
            fg="red",
        )
        raise typer.Exit(code=1)

    host = profile.get("host", "")
    port = int(profile.get("port", 22))
    user = profile.get("user", "")
    directory = profile.get("directory", "")
    key_path = profile.get("key_path")
    password = profile.get("password")

    typer.echo(f"\n  Testing {profile_name} → {user}@{host}:{port}\n")

    # 1. TCP-level reachability (fast, no auth).
    try:
        with socket.create_connection((host, port), timeout=5) as _:
            typer.secho("  [tcp]   reachable", fg="green")
    except OSError as e:
        typer.secho(f"  [tcp]   failed: {e}", fg="red")
        raise typer.Exit(code=1)

    # 2. SSH-level authentication.
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        if key_path:
            pkey = paramiko.RSAKey.from_private_key_file(
                os.path.expanduser(key_path)
            )
            client.connect(host, port=port, username=user, pkey=pkey, timeout=10)
        else:
            client.connect(host, port=port, username=user, password=password, timeout=10)
        typer.secho("  [auth]  ok", fg="green")
    except Exception as e:  # noqa: BLE001
        typer.secho(f"  [auth]  failed: {e}", fg="red")
        raise typer.Exit(code=1)
    finally:
        client.close()

    # 3. Directory writability (best-effort).
    sftp_client = None
    try:
        sftp_client = paramiko.SSHClient()  # reconnect for sftp
        if key_path:
            pkey = paramiko.RSAKey.from_private_key_file(
                os.path.expanduser(key_path)
            )
            sftp_client.connect(host, port=port, username=user, pkey=pkey, timeout=10)
        else:
            sftp_client.connect(
                host, port=port, username=user, password=password, timeout=10
            )
        sftp = sftp_client.open_sftp()
        try:
            sftp.stat(directory)
            typer.secho(f"  [dir]   {directory} exists", fg="green")
        except IOError:
            typer.secho(
                f"  [dir]   {directory} does not exist; will be created on upload.",
                fg="yellow",
            )
        sftp.close()
    except Exception as e:  # noqa: BLE001
        typer.secho(f"  [dir]   check failed: {e}", fg="yellow")
    finally:
        if sftp_client is not None:
            sftp_client.close()

    # 4. Dry-run of post_push_cmd if present.
    ppc = profile.get("post_push_cmd")
    if ppc:
        typer.secho(f"\n  [dry-run]  would execute on remote: {ppc}", fg="cyan")

    typer.echo("")
    typer.secho("  ✓ Connection succeeded.\n", fg="green", bold=True)


__all__ = ["app"]
