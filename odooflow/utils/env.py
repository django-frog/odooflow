import ast
import json
import typer
from pathlib import Path
from pprint import pformat
from rich import print

from odooflow.config_manager import load_config

config = load_config()
ENV_FILENAME = config["env_file"]
MANIFEST_FILENAME = config["manifest_file"]

def read_manifest(path: Path):
    try:
        return ast.literal_eval(path.read_text())
    except (SyntaxError, ValueError) as e:
        typer.secho(f"❌ Error parsing manifest {path}: {e}", fg="red", bold=True)
        raise typer.Exit(1)

def update_manifest(path: Path, updates: dict):
    manifest = read_manifest(path)
    manifest.update(updates)

    formatted_manifest = pformat(manifest, indent=4, width=100)
    content = f"# Automatically updated by odooflow\n{formatted_manifest}"

    path.write_text(content)
    print(f"[green]Updated {MANIFEST_FILENAME}[/green]")


def write_env_file(env_path: Path, values: dict):
    env_path.write_text(json.dumps(values, indent=4))
    print(f"[green]Created {ENV_FILENAME}[/green]")

def read_env_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}
