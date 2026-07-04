import typer
from rich import print
from typing import Optional

from odooflow import config_manager, errors


def config(
    env_file: str = typer.Option(None),
    manifest_file: str = typer.Option(None),
    access_token: str = typer.Option(None),
    add_core_module: Optional[str] = typer.Option(None),
    sync_keys: Optional[str] = typer.Option(None),
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
):
    """
    View or patch fields in ~/.odooflowrc. For first-time configuration use
    `odooflow setup` instead — it walks you through every value interactively
    and stores the access token with the correct file permissions.
    """
    try:
        current_config = config_manager.load_config(strict=False)
    except errors.ConfigError as e:
        errors._safe_exit(e)

    updated = False

    if show:
        typer.secho("📦 Current Configuration:", fg="cyan", bold=True)
        print(current_config)
        typer.secho(
            "\n  Tip: run `odooflow setup` to reconfigure interactively.",
            fg="cyan",
        )
        raise typer.Exit()

    has_any = any(
        [env_file, manifest_file, access_token, add_core_module, sync_keys]
    )
    if not has_any:
        typer.secho(
            "No changes provided. Use --help to see options, "
            "or run `odooflow setup` for the guided wizard.",
            fg="yellow",
        )
        return

    if env_file:
        current_config["env_file"] = env_file
        updated = True

    if manifest_file:
        current_config["manifest_file"] = manifest_file
        updated = True

    if access_token:
        current_config["access_token"] = access_token
        updated = True
        typer.secho(
            "  ✓ access_token saved. "
            "Consider `chmod 600 ~/.odooflowrc` for safety.",
            fg="cyan",
        )

    if add_core_module:
        modules = [m.strip() for m in add_core_module.split(",") if m.strip()]
        if modules:
            existing_modules = set(current_config.get(
                "core_modules",
                config_manager.DEFAULT_CONFIG.get("core_modules", []),
            ))
            new_modules = set(modules)
            combined_modules = sorted(existing_modules.union(new_modules))
            current_config["core_modules"] = combined_modules
            updated = True
            typer.secho(f"  ✓ Added core module(s): {', '.join(new_modules)}", fg="green")

    if sync_keys:
        new_keys = [k.strip() for k in sync_keys.split(",") if k.strip()]
        existing_keys = set(current_config.get(
            "sync_keys",
            config_manager.DEFAULT_CONFIG["sync_keys"],
        ))
        combined_keys = sorted(existing_keys.union(new_keys))
        current_config["sync_keys"] = combined_keys
        updated = True
        typer.secho(f"  ✓ Updated sync keys: {', '.join(new_keys)}", fg="cyan")

    if updated:
        config_manager.save_config(current_config)
        typer.secho("💾 Configuration updated.", fg="green", bold=True)
