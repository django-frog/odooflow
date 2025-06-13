import typer

from pathlib import Path
from typing import Optional

from odooflow import config_manager
from odooflow.utils.env import read_manifest, write_env_file, read_env_file

config = config_manager.load_config()
ENV_FILENAME = config["env_file"]
MANIFEST_FILENAME = config["manifest_file"]
DEFAULT_KEYS = config['sync_keys']


def sync_env(keys: Optional[str] = typer.Option(None)):
    """
    Sync selected keys from __manifest__.py into the .env file.
    Uses default keys from .odooflowrc unless overridden by --keys option.
    """
    cwd = Path.cwd()
    manifest_path = cwd / MANIFEST_FILENAME
    env_path = cwd / ENV_FILENAME

    if not manifest_path.exists():
        typer.secho(f"❌ {MANIFEST_FILENAME} not found in the current directory.", fg="red")
        raise typer.Exit(code=1)

    manifest = read_manifest(manifest_path)
    env = read_env_file(env_path)

    if keys:
        keys_to_sync = [k.strip() for k in keys.split(",") if k.strip()]
    else:
        config = config_manager.load_config()
        keys_to_sync = config.get("sync_keys", DEFAULT_KEYS)

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