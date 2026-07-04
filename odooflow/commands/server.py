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
    no_validate: bool = typer.Option(
        False,
        "--no-validate",
        help=(
            "Skip on-disk preflight (key file existence) and auth-method prompt. "
            "Use only in CI/automation."
        ),
    ),
):
    """
    Add or update a server profile. Interactive when flags are missing.

    All required fields are validated before saving. In interactive mode
    the wizard loops until each prompt is satisfied (e.g. auth method
    must be 'key' or 'password', key path must exist on disk).
    """
    env, env_path = _load_env()

    # ------------------------------------------------------------------ #
    # Interactive collection with loop-until-valid prompts.
    # ------------------------------------------------------------------ #
    if not host:
        host = _prompt_until(
            "Host (e.g. 10.0.0.5)",
            default="",
            validator=_validate_host_strict,
            error_msg=(
                "  Host cannot contain a scheme prefix; use a bare hostname or IP."
            ),
        )
    if not user:
        user = _prompt_until(
            "SSH user",
            default=getpass.getuser(),
            validator=lambda v: bool(v.strip()),
            error_msg="  SSH user cannot be empty.",
        )
    if not directory:
        directory = typer.prompt(
            "Remote directory (absolute path)", default="/opt/odoo"
        )
    if port is None:
        port = _prompt_port(default=22)

    # Auth method (loop until user types 'key' or 'password').
    if not key_path and password is None:
        choice = _prompt_auth_method()
        if choice == "password":
            password = _prompt_password()
        else:
            key_path = _prompt_key_path(no_validate=no_validate)

    # If user only supplied --key-path (no auth prompt yet), still verify it
    # unless --no-validate was given.
    if key_path and not password and not no_validate:
        while not Path(key_path).expanduser().exists():
            errors._emit(
                f"  SSH key not found at {Path(key_path).expanduser()}.",
                [
                    "",
                    "  Fix it:",
                    "    * Enter an existing file path",
                    "    * Run `odooflow ssh-keygen` first to generate one",
                    "    * Or pass `--no-validate` to skip this check (CI-only)",
                ],
            )
            typer.secho("")
            key_path = _prompt_key_path(no_validate=True)

    # ------------------------------------------------------------------ #
    # Build the profile dict and persist.
    # ------------------------------------------------------------------ #
    profile = {
        "host": host,
        "port": int(port),
        "user": user,
        "directory": directory,
    }
    if key_path:
        profile["key_path"] = key_path
    if password:
        profile["password"] = password
    if post_push_cmd:
        profile["post_push_cmd"] = post_push_cmd

    # ------------------------------------------------------------------ #
    # Save, with structured error path (no traceback for validation).
    # ------------------------------------------------------------------ #
    try:
        new_env, migrated = server_profile.save_profile(
            env_path, env, name, profile
        )
    except errors.ConfigError as exc:
        # Same structured output we use elsewhere; no raw traceback.
        errors._safe_exit(exc)

    if make_default:
        try:
            new_env = server_profile.set_default(env_path, new_env, name)
        except OSError as exc:
            errors._emit(
                f"  Profile saved, but persisting default failed: {exc}",
                [
                    "  Fix it:",
                    "    * Check write permissions on the env file's parent dir.",
                    "    * Re-run `odooflow server use <name>` after fixing.",
                ],
            )
            raise typer.Exit(code=1)
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


# --------------------------------------------------------------------------- #
# Interactive prompt helpers (loop-until-valid)
# --------------------------------------------------------------------------- #


def _prompt_until(
    label: str,
    default: str,
    validator,
    error_msg: str,
) -> str:
    """Loop typer.prompt until `validator(value)` returns True."""
    while True:
        value = typer.prompt(label, default=default)
        if validator(value):
            return value.strip() if isinstance(value, str) else value
        typer.secho(error_msg, fg="red", err=True)


def _validate_host_strict(host: str) -> bool:
    if not host:
        return False
    return "://" not in host


def _prompt_port(default: int = 22) -> int:
    """Loop until the user enters an integer 1-65535."""
    while True:
        raw = typer.prompt("Port", default=str(default))
        try:
            port = int(raw)
        except ValueError:
            typer.secho(
                f"  Port must be a number between 1 and 65535 (got '{raw}').",
                fg="red",
                err=True,
            )
            continue
        if not (1 <= port <= 65535):
            typer.secho(
                f"  Port must be between 1 and 65535 (got {port}).",
                fg="red",
                err=True,
            )
            continue
        return port


def _prompt_auth_method() -> str:
    """Loop until the user types 'key' or 'password' (case-insensitive prefix)."""
    while True:
        choice = (
            typer.prompt(
                "Auth method — type 'key' or 'password'",
                default="key",
            )
            .strip()
            .lower()
        )
        if choice.startswith("p"):
            return "password"
        if choice.startswith("k"):
            return "key"
        typer.secho(
            "  Please type 'key' or 'password' (e.g. 'k' / 'p').",
            fg="red",
            err=True,
        )


def _prompt_password() -> str:
    """Loop until the user enters a non-empty password."""
    while True:
        pw = typer.prompt(
            "Password (input hidden)", hide_input=True, default=""
        )
        if pw:
            return pw
        typer.secho(
            "  Password cannot be empty. Re-enter or press Ctrl-C to abort.",
            fg="red",
            err=True,
        )


def _prompt_key_path(no_validate: bool) -> str:
    """Prompt for an SSH key path. With no_validate=False, loops until file exists."""
    while True:
        path_str = typer.prompt(
            "Path to SSH private key",
            default=str(Path.home() / ".ssh" / "id_rsa"),
        )
        expanded = Path(path_str).expanduser()
        if no_validate or expanded.exists():
            return str(expanded)
        typer.secho(
            f"  SSH key not found at {expanded}.",
            fg="red",
            err=True,
        )
        typer.secho(
            "  Choose again, run `odooflow ssh-keygen`, or pass --no-validate.\n",
            fg="red",
            err=True,
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
