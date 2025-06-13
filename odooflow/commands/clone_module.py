import ast
import typer
import requests

from typing import Optional

from urllib.parse import urlparse, urlunparse
from git import Repo, GitCommandError
from pathlib import Path

from odooflow.config_manager import get_access_token, get_core_modules_from_config


def get_project_url_from_gitlab(module_name: str, base_url: str = "https://gitlab.ebtech-solution.com") -> Optional[str]:
    """
    Search GitLab for a project by name and return its HTTPS URL.
    """
    api_url = f"{base_url}/api/v4/projects"
    params = {"search": module_name, "simple": "true", "per_page": 100, "access_token": get_access_token()}
    headers = {"Accept": "application/json"}

    try:
        typer.secho(f"🔍 Searching GitLab for module: {module_name}", fg="cyan")
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()

        for project in response.json():
            if project["name"] == module_name or project["path"] == module_name:
                typer.secho(f"✅ Found module '{module_name}'", fg="green")
                return project["http_url_to_repo"]

        typer.secho(f"❌ Module '{module_name}' not found in GitLab.", fg="yellow")
        return None

    except requests.RequestException as e:
        typer.secho(f"❌ GitLab API error: {e}", fg="red")
        return None


def inject_token_into_url(url: str, token: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")
    netloc = f"oauth2:{token}@{parsed.netloc}"
    return urlunparse(parsed._replace(netloc=netloc, scheme="https"))


def extract_module_name_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1].removesuffix(".git")


def safe_eval_manifest(content: str) -> dict:
    try:
        return ast.literal_eval(content)
    except Exception as e:
        typer.secho(f"❌ Failed to evaluate manifest: {e}", fg="red")
        return {}


def clone_repo(url: str, target_dir: Path, branch: str = "main") -> bool:
    if target_dir.exists():
        typer.secho(f"⚠️  Skipping '{target_dir.name}': already exists.", fg="yellow")
        return True
    try:
        access_token = get_access_token()
        url_with_token = inject_token_into_url(url, access_token)
        typer.secho(f"📥 Cloning into '{target_dir}'...", fg="cyan")
        Repo.clone_from(url_with_token, target_dir, branch=branch)
        typer.secho(f"✅ Successfully cloned '{url}'", fg="green")
        return True
    except GitCommandError as e:
        typer.secho(f"❌ Git error: Failed to clone '{url}'\n{e}", fg="red")
        return False
    except Exception as e:
        typer.secho(f"❌ Unexpected error: {e}", fg="red")
        return False


def clone_module_command(
    url: str = typer.Option(..., "--url", help="Full HTTP URL of the module repo."),
    branch: Optional[str] = None,
    deep: bool = typer.Option(False, "--deep")
):
    """
    Clone a module and its dependencies into the current directory.
    """
    typer.secho("🚀 Starting module cloning process...", fg="cyan", bold=True)
    core_modules = get_core_modules_from_config()
    visited = set()
    fail_count = {"count": 0}  # ✅ Use a dict to allow mutation inside nested function

    def clone_recursive(module_url: str, current_branch: Optional[str]):
        module_name = extract_module_name_from_url(module_url)
        if module_name in visited:
            typer.secho(f"🔁 Already processed '{module_name}', skipping.", fg="yellow")
            return

        visited.add(module_name)
        target_path = Path.cwd() / module_name

        if not clone_repo(module_url, target_path, current_branch or "main"):
            typer.secho(f"❌ Failed to clone '{module_name}'. Skipping its dependencies.", fg="red")
            fail_count["count"] += 1  # ✅ Safely mutate the count
            return

        manifest_path = target_path / "__manifest__.py"
        if not manifest_path.exists():
            typer.secho(f"📦 No manifest found in '{module_name}', skipping dependencies.", fg="yellow")
            return

        manifest_data = safe_eval_manifest(manifest_path.read_text())
        dependencies = manifest_data.get("depends", [])

        if not dependencies:
            typer.secho(f"ℹ️  No dependencies for '{module_name}'.", fg="blue")
            return

        for dep in dependencies:
            if dep in core_modules:
                typer.secho(f"🔒 Skipping core module: '{dep}'", fg="magenta")
                continue
            if dep in visited:
                typer.secho(f"🔁 Already processed dependency '{dep}'", fg="yellow")
                continue

            dep_url = get_project_url_from_gitlab(module_name=dep)
            if not dep_url:
                typer.secho(f"❗ Could not resolve dependency: '{dep}'", fg="red")
                fail_count["count"] += 1
                continue

            clone_recursive(dep_url, current_branch)

    if deep:
        clone_recursive(url, branch)
    else:
        # Shallow mode
        module_name = extract_module_name_from_url(url)
        target_path = Path.cwd() / module_name

        if not clone_repo(url, target_path, branch or "main"):
            typer.secho("❌ Failed to clone main module. Exiting.", fg="red", bold=True)
            raise typer.Exit(code=1)

        manifest_path = target_path / "__manifest__.py"
        if not manifest_path.exists():
            typer.secho("❌ Manifest file not found! Cannot resolve dependencies.", fg="red")
            raise typer.Exit(code=1)

        manifest_data = safe_eval_manifest(manifest_path.read_text())
        dependencies = manifest_data.get("depends", [])

        if not dependencies:
            typer.secho("ℹ️  No dependencies found in manifest.", fg="blue")

        for dep in dependencies:
            if dep in core_modules:
                typer.secho(f"🔒 Skipping core dependency: {dep}", fg="magenta")
                continue

            dep_url = get_project_url_from_gitlab(module_name=dep)
            dep_path = Path.cwd() / dep

            if dep_url:
                if not clone_repo(dep_url, dep_path):
                    fail_count["count"] += 1
            else:
                typer.secho(f"❗ Failed to resolve dependency: '{dep}'", fg="yellow")
                fail_count["count"] += 1

    if fail_count["count"] > 0:
        typer.secho(f"⚠️  Finished with {fail_count['count']} failed clones.", fg="yellow", bold=True)
    else:
        typer.secho("✅ All done without errors!", fg="green", bold=True)
