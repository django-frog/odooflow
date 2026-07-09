import typer
from typing import List, Optional

from odooflow.commands.init_module_env import init_module_env
from odooflow.commands.sync_env import sync_env as sync_env_command
from odooflow.commands.config import config as config_command
from odooflow.commands.clone_module import clone_module_command
from odooflow.commands.remote import remote as remote_command
from odooflow.commands.keygen import generate_ssh_key as keygen_command
from odooflow.commands.push import push_command
from odooflow.commands.setup import setup as setup_command
from odooflow.commands.server import app as server_app
from odooflow.commands.connect import connect as server_connect

app = typer.Typer(help="OdooFlow CLI — streamline your Odoo development workflow.")
app.add_typer(server_app, name="server")
server_app.command("connect")(server_connect)

@app.command(name="setup")
def setup_cmd():
    """Interactive wizard: write ~/.odooflowrc with token, GitLab URL, core modules."""
    setup_command()

@app.command(name="init")
def init_manifest(
    author: Optional[str] = typer.Option(None, help="Author name"),
    website : Optional[str] = typer.Option(None, help="Website"),
    odoo_version: Optional[str] = typer.Option(None, help="Odoo version"),
    license_name: Optional[str] = typer.Option(None, help="License"),
):
    """
    Initialize the Odoo module environment file and sync metadata with manifest.
    """
    init_module_env(author=author, odoo_version=odoo_version, license_name=license_name, website=website)

@app.command(name="sync-env")
def sync_env(
    keys: Optional[str] = typer.Option(None, "--keys", help="Comma-separated keys to sync from manifest to env file.")
):
    """
    Sync the environment file (.odooflow.env.json) from manifest.
    """
    sync_env_command(keys)

@app.command("config", help="Update configuration")
def config(
    env_file: Optional[str] = typer.Option(None, help="Set custom env file name"),
    manifest_file: Optional[str] = typer.Option(None, help="Set custom manifest file name"),
    access_token : Optional[str] = typer.Option(None, help="Set Git access token"),
    add_core_module: Optional[str] = typer.Option(None, "--add-core-module", help="Comma-separated list of core modules to add"),
    sync_keys: Optional[str] = typer.Option(None, help="Set default keys to sync from manifest to .env (comma-separated)"),
    show: Optional[bool] = typer.Option(False, "--show", help="Show current config")
):
    """
    Update or show OdooFlow CLI configuration (.odooflowrc)
    """
    config_command(env_file, manifest_file, access_token, add_core_module, sync_keys,show)


@app.command("clone")
def clone_command(
    repo_url: str = typer.Argument(..., help="HTTP URL of the module repository."),
    branch: Optional[str] = typer.Option(None, "--branch", '-b', help="Branch to clone"),
    depth: int = typer.Option(1, "--depth", "-d", help="Max dependency depth to clone. 1 = target only, 2 = target + immediate deps, etc."),
    workers: int = typer.Option(4, "--workers", "-w", help="Max concurrent clones (1-8)."),
):
    """
    Clone a module and (optionally) its dependencies from a Git repository.

    Run `odooflow setup` first if you have not configured an access token yet.
    """
    clone_module_command(repo_url, branch, depth, workers)


@app.command()
def remote(
    add_repo: Optional[str] = typer.Option(None, help="Add Git remote URL"),
    branch: Optional[str] = typer.Option(None, help="Target Git branch (defaults to current)"),
    server_json: Optional[str] = typer.Option(None, help="Server config as JSON: '{\"host\": \"127.0.0.1\", \"port\": 22}'")
):
    """
    Manage remote connections for Git and deployment server.
    """
    remote_command(
        add_repo=add_repo,
        server_json=server_json, 
        branch=branch
    )

@app.command("ssh-keygen")
def generate_ssh_key(
    key_name: str = typer.Option("odooflow_rsa", help="Name of the SSH key file to generate (without extension)."),
    output_dir: Optional[str] = typer.Option(None, help="Directory to save the SSH key. Defaults to ~/.ssh"),
    overwrite: bool = typer.Option(False, help="Overwrite existing key files if they exist."),
):
    """
    Generate a secure SSH key pair.
    """
    keygen_command(key_name=key_name, output_dir=output_dir, overwrite=overwrite)


@app.command()
def push(
    server: Optional[str] = typer.Option(None, "--server", "-s", help="Named server profile from `odooflow server list`."),
    remote_only: bool = typer.Option(False, "--remote-only", help="Skip Git push and only upload to server"),
    exec_cmd: Optional[str] = typer.Option(None, "--exec", help="Custom shell command to execute on the server after pushing"),
):
    """
    Push the current Git branch and upload the project to the test server.
    """
    push_command(server_name=server, remote_only=remote_only, exec_cmd=exec_cmd)



def main():
    app()

if __name__ == "__main__":
    main()
