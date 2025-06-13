from pathlib import Path
from rich import print

from odooflow.config_manager import load_config
from odooflow.utils.env import read_manifest, write_env_file, update_manifest

config = load_config()
ENV_FILENAME = config["env_file"]
MANIFEST_FILENAME = config["manifest_file"]



def init_module_env(author: str, odoo_version: str, license_name: str, website : str):
    cwd = Path.cwd()
    env_path = cwd / ENV_FILENAME
    manifest_path = cwd / MANIFEST_FILENAME

    if not manifest_path.exists():
        print(f"[red]No {MANIFEST_FILENAME} found in this directory[/red]")
        raise SystemExit(1)

    manifest = read_manifest(manifest_path)

    values = {
        "name" : manifest.get("name", ""), 
        "author": author or manifest.get("author", "Unknown"),
        "version": odoo_version or manifest.get("version", "16.0"),
        "license": license_name or manifest.get("license", "LGPL-3"),
        "website" : website or manifest.get("website", 'https://www.yourcompany.com'),
        "depends" : manifest.get("depends" , []),
    }

    write_env_file(env_path, values)
    
    if author or odoo_version or license_name or website:
        update_manifest(manifest_path, values)
