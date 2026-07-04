from pathlib import Path
from rich import print
import typer

from odooflow import config_manager, errors
from odooflow.utils.env import read_manifest, write_env_file, update_manifest


DEFAULTS = {
    "manifest_file": "__manifest__.py",
    "env_file": ".odooflow.env.json",
    "author": "Unknown",
    "version": "16.0",
    "license": "LGPL-3",
    "website": "https://www.yourcompany.com",
}


def _cfg():
    return config_manager.load_config(strict=False)


def init_module_env(
    author: str,
    odoo_version: str,
    license_name: str,
    website: str,
):
    """
    Initialize .odooflow.env.json from the current directory's __manifest__.py.
    Missing manifest values are filled in interactively with the prior
    hardcoded defaults shown as the prompt's default answer.
    """
    cwd = Path.cwd()
    cfg = _cfg()
    manifest_path = cwd / cfg.get("manifest_file", DEFAULTS["manifest_file"])

    if not manifest_path.exists():
        errors._emit(
            "No Odoo manifest found in this directory.",
            [
                f"  Expected:  {manifest_path}",
                "",
                "  Fix it:",
                "    * Run this command inside an Odoo module (a directory",
                "      that contains __manifest__.py).",
                f"    * Or set a custom `manifest_file` value in {config_manager.get_global_config_path()}",
                "      (`odooflow config --manifest-file <name>`).",
            ],
        )
        raise typer.Exit(code=1)

    manifest = read_manifest(manifest_path)

    def _resolve(field: str, cli_value: str, manifest_key: str, fallback: str) -> str:
        """CLI arg wins, then manifest, then interactive prompt with fallback."""
        if cli_value:
            return cli_value
        manifest_value = manifest.get(manifest_key)
        if manifest_value:
            return manifest_value
        return typer.prompt(field, default=fallback)

    values = {
        "name": manifest.get("name", ""),
        "author": _resolve("Author", author, "author", DEFAULTS["author"]),
        "version": _resolve("Odoo version", odoo_version, "version", DEFAULTS["version"]),
        "license": _resolve("License", license_name, "license", DEFAULTS["license"]),
        "website": _resolve("Website", website, "website", DEFAULTS["website"]),
        "depends": manifest.get("depends", []),
    }

    env_filename = cfg.get("env_file", DEFAULTS["env_file"])
    env_path = cwd / env_filename
    write_env_file(env_path, values)

    if author or odoo_version or license_name or website:
        update_manifest(manifest_path, values)

    print(f"[green]✓ Initialized {env_filename} from {manifest_path.name}[/green]")
