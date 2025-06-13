import typer
from rich import print
from typing import Optional

from odooflow import config_manager

def config(
    env_file: str = typer.Option(None),
    manifest_file: str = typer.Option(None),
    access_token: str = typer.Option(None),
    add_core_module: Optional[str] = typer.Option(None),
    sync_keys: Optional[str] = typer.Option(None),
    show: bool = typer.Option(False, "--show", help="Display current configuration")
):
    current_config = config_manager.load_config()
    updated = False

    if show:
        typer.secho("📦 Current Configuration:", fg="cyan", bold=True)
        print(current_config)
        raise typer.Exit()

    if env_file:
        current_config["env_file"] = env_file
        updated = True

    if manifest_file:
        current_config["manifest_file"] = manifest_file
        updated = True

    if access_token:
        current_config["access_token"] = access_token
        updated = True

    if add_core_module:
        modules = [m.strip() for m in add_core_module.split(",") if m.strip()]
        if modules:
            clone_config = current_config.setdefault("clone", {})
            existing_modules = set(clone_config.get(
                "core_modules",
                config_manager.DEFAULT_CONFIG.get("core_modules", [])
            ))
            new_modules = set(modules)
            combined_modules = sorted(existing_modules.union(new_modules))
            clone_config["core_modules"] = combined_modules
            updated = True
            typer.secho(f"✅ Added core module(s): {', '.join(new_modules)}", fg="green")

    if sync_keys:
        new_keys = [k.strip() for k in sync_keys.split(",") if k.strip()]
        existing_keys = set(current_config.get(
            "sync_keys",
            config_manager.DEFAULT_CONFIG['sync_keys'] 
        ))
        combined_keys = sorted(existing_keys.union(new_keys))
        current_config["sync_keys"] = combined_keys
        updated = True
        typer.secho(f"🔑 Updated sync keys: {', '.join(new_keys)}", fg="cyan")

    if updated:
        config_manager.save_config(current_config)
        typer.secho("💾 Configuration updated successfully.", fg="green")
    else:
        typer.secho("⚠️  No changes provided. Use --help to see available options.", fg="yellow")
