import ast
import json
from pathlib import Path
from pprint import pformat
from rich import print

from odooflow import config_manager, errors


def _config():
    """Load the latest config inside the function, never at import time."""
    return config_manager.load_config(strict=False)


def read_manifest(path: Path):
    """
    Read an Odoo manifest (__manifest__.py) and return its dict.

    Raises odooflow.errors.ConfigError on malformed input so the caller can
    decide whether to abort (e.g. the CLI) or recover (e.g. a non-CLI tool).
    """
    try:
        return ast.literal_eval(path.read_text())
    except (SyntaxError, ValueError) as e:
        errors._emit(
            f"Manifest file could not be parsed: {path}",
            [
                f"  Python error: {e}",
                "",
                "  Common causes:",
                "    * A trailing comma or unclosed bracket in the manifest.",
                "    * Mixed tabs and spaces causing an IndentationError.",
                "    * A typo in a key name.",
                "",
                "  Fix it:",
                f"    1. Open {path} in your editor.",
                "    2. Run `python -c \"import ast; ast.parse(open('<file>').read())\"`",
                "       to see the precise line of the syntax error.",
            ],
        )
        raise errors.ConfigError(f"Invalid manifest: {path}") from e


def update_manifest(path: Path, updates: dict):
    manifest = read_manifest(path)
    manifest.update(updates)

    formatted_manifest = pformat(manifest, indent=4, width=100)
    content = f"# Automatically updated by odooflow\n{formatted_manifest}"

    path.write_text(content)
    cfg = _config()
    print(f"[green]Updated {cfg.get('manifest_file', '__manifest__.py')}[/green]")


def write_env_file(env_path: Path, values: dict):
    env_path.write_text(json.dumps(values, indent=4))
    cfg = _config()
    print(f"[green]Created {cfg.get('env_file', '.odooflow.env.json')}[/green]")


def read_env_file(path: Path) -> dict:
    """Return the env file as a dict, or {} if the file is missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        errors._emit(
            f"Environment file could not be read: {path}",
            [
                f"  Reason:    {e}",
                "  Falling back to {} so the calling command can decide how to recover.",
                "",
                "  Fix it:",
                f"    * Open {path} and confirm it contains valid JSON, or",
                "      delete the file and run `odooflow init` to recreate it.",
            ],
        )
        return {}
