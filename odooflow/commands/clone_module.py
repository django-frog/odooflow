import ast
import typer
import requests
import threading

from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from urllib.parse import urlparse, urlunparse
from git import Repo, GitCommandError
from pathlib import Path

from odooflow.config_manager import get_access_token, get_core_modules_from_config, load_config


def get_project_url_from_gitlab(module_name: str, base_url: Optional[str] = None) -> Optional[str]:
    """
    Search GitLab for a project by name and return its HTTPS URL.
    """
    if base_url is None:
        config = load_config()
        base_url = config.get("gitlab_url", "https://gitlab.ebtech-solution.com")

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
    depth: int = typer.Option(1, "--depth", "-d", help="Max dependency depth to clone. 1 clones only the target module, 2 clones target + immediate dependencies, etc."),
):
    """
    Clone a module and its dependencies into the current directory.
    """
    typer.secho("🚀 Starting module cloning process...", fg="cyan", bold=True)
    core_modules = get_core_modules_from_config()
    visited = set()
    fail_count = 0
    lock = threading.Lock()

    def clone_recursive(module_url: str, current_branch: Optional[str], current_depth: int):
        nonlocal fail_count
        module_name = extract_module_name_from_url(module_url)

        with lock:
            if module_name in visited:
                typer.secho(f"🔁 Already processed '{module_name}', skipping.", fg="yellow")
                return False
            visited.add(module_name)

        target_path = Path.cwd() / module_name

        if not clone_repo(module_url, target_path, current_branch or "main"):
            typer.secho(f"❌ Failed to clone '{module_name}'. Skipping its dependencies.", fg="red")
            with lock:
                fail_count += 1
            return False

        if current_depth <= 0:
            return False

        manifest_path = target_path / "__manifest__.py"
        if not manifest_path.exists():
            typer.secho(f"📦 No manifest found in '{module_name}', skipping dependencies.", fg="yellow")
            return True

        manifest_data = safe_eval_manifest(manifest_path.read_text())
        dependencies = manifest_data.get("depends", [])

        if not dependencies:
            typer.secho(f"ℹ️  No dependencies for '{module_name}'.", fg="blue")
            return True

        candidate_deps = [dep for dep in dependencies if dep not in core_modules]
        if not candidate_deps:
            return True

        next_depth = current_depth - 1

        def _resolve_and_run(dep_name: str):
            dep_url = get_project_url_from_gitlab(module_name=dep_name)
            if not dep_url:
                typer.secho(f"❗ Could not resolve dependency: '{dep_name}'", fg="red")
                nonlocal_assign = True
                with lock:
                    fail_count += 1
                return
            clone_recursive(dep_url, current_branch, next_depth)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_resolve_and_run, dep) for dep in candidate_deps]
            for f in futures:
                f.result()

        return True

    clone_recursive(url, branch, depth)

    if fail_count > 0:
        typer.secho(f"⚠️  Finished with {fail_count} failed clones.", fg="yellow", bold=True)
    else:
        typer.secho("✅ All done without errors!", fg="green", bold=True)
