import typer

from pathlib import Path
from typing import Optional

from odooflow import config_manager
from odooflow.utils.env import read_manifest, write_env_file, read_env_file


def sync_env(keys: Optional[str] = typer.Option(None)):
    """
    Sync selected keys from __manifest__.py into the .env file.
    Uses default keys from .odooflowrc unless overridden by --keys option.
    """
    cwd = Path.cwd()
    config = config_manager.load_config()
    manifest_path = cwd / config.get("manifest_file", "__manifest__.py")
    env_path = cwd / config.get("env_file", ".odooflow.env.json")
    keys_to_sync = [k.strip() for k in keys.split(",") if k.strip()] if keys else config.get("sync_keys", ["name", "author", "license", "version", "depends"])

    if not manifest_path.exists():
        typer.secho(f"❌ {manifest_path.name} not found in the current directory.", fg="red")
        raise typer.Exit(code=1)

    manifest = read_manifest(manifest_path)
    env = read_env_file(env_path)

    updated = {}
    for key in keys_to_sync:
        if key in manifest:
            env[key] = manifest[key]
            updated[key] = manifest[key]

    if updated:
        write_env_file(env_path, env)
        typer.secho(f"✅ Synced keys: {', '.join(updated.keys())}", fg="cyan")
    else:
        typer.secho("⚠️  No matching keys found to sync.", fg="yellow")
