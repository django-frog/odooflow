import os
import json
import typer
from pathlib import Path
from typing import Dict

DEFAULT_CONFIG = {
    "env_file": ".odooflow.env.json",
    "manifest_file": "__manifest__.py",
    "core_modules" : ["base", "web", "mail", "sale", "account"],
    "sync_keys" : ["name", "author", "license", "version", "depends"],
}

CONFIG_FILENAME = ".odooflowrc"

def get_global_config_path() -> Path:
    return Path.home() / ".odooflowrc"

def load_config() -> Dict:
    path = get_global_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(config: Dict):
    path = get_global_config_path()
    with open(path, "w") as f:
        json.dump(config, f, indent=4)

def get_access_token():
    token = os.getenv("ODOOFLOW_ACCESS_TOKEN")
    if token:
        return token

    config = load_config()
    token = config.get("access_token")
    if token:
        return token

    typer.secho("❌ Access token not found. Please set the 'ODOOFLOW_ACCESS_TOKEN' "
                "environment variable or configure it via `.odooflowrc`.", fg="red", bold=True)
    raise typer.Exit(code=1)

def get_core_modules_from_config() -> set:
    config = load_config()
    return set(config.get("clone", {}).get("core_modules", []))