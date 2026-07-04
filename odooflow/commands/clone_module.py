import ast
import typer
import requests
import threading

from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from urllib.parse import urlparse, urlunparse
from git import Repo, GitCommandError
from pathlib import Path

from odooflow import errors
from odooflow.commands.gitlab import get_default_branch
from odooflow.config_manager import (
    get_access_token,
    get_core_modules_from_config,
    load_config,
)


def get_project_url_from_gitlab(module_name: str, base_url: Optional[str] = None) -> Optional[str]:
    """Search GitLab for a project by name and return its HTTPS URL."""
    if base_url is None:
        config = load_config(strict=False)
        base_url = config.get("gitlab_url", "https://gitlab.ebtech-solution.com")

    api_url = f"{base_url}/api/v4/projects"
    headers = {"Accept": "application/json"}

    try:
        token = get_access_token()
    except errors.AccessTokenMissingError:
        errors.access_token_missing_rc_fallback()
        return None

    params = {"search": module_name, "simple": "true", "per_page": 100, "access_token": token}

    try:
        typer.secho(f"  🔍 Looking up '{module_name}' in GitLab…", fg="cyan")
        response = requests.get(api_url, headers=headers, params=params, timeout=15)
        response.raise_for_status()

        for project in response.json():
            if project.get("name") == module_name or project.get("path") == module_name:
                typer.secho(f"  ✓ Resolved '{module_name}'", fg="green")
                return project["http_url_to_repo"]

        errors.dependency_unresolved(module_name)
        return None

    except requests.RequestException as e:
        errors.gitlab_unreachable(base_url, str(e))
        return None


def inject_token_into_url(url: str, token: str) -> str:
    """Embed a GitLab PAT into a clone URL as `oauth2:<token>@host`."""
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
    except (SyntaxError, ValueError) as e:
        errors._emit(
            "Manifest could not be parsed.",
            [
                f"  Python error: {e}",
                "",
                "  Treat the module as having no dependencies; fix the manifest",
                "  in the cloned copy before re-running with --depth > 1.",
            ],
        )
        return {}


def get_access_token_safe() -> bool:
    try:
        get_access_token()
        return True
    except errors.AccessTokenMissingError:
        return False


def _resolve_branch(repo_url: str, requested: Optional[str]) -> Optional[str]:
    """
    Decide which branch to pass to `git clone -b <branch>`.

    Resolution order:
      1. Caller-supplied branch (CLI `--branch` or per-dependency value) wins.
      2. GitLab API `default_branch` for the project's URL.
      3. None — caller passes no `-b` flag and git uses its own default.
    """
    if requested:
        return requested
    try:
        default = get_default_branch(repo_url)
    except Exception:
        default = None
    return default or None


def clone_repo(url: str, target_dir: Path, branch: str = None) -> bool:
    """
    Clone `url` into `target_dir`.

    `branch` precedence (handled by `_resolve_branch`):
        CLI `--branch X`  >  GitLab `default_branch`  >  git's own default.
    """
    if target_dir.exists():
        typer.secho(f"  ⚠  '{target_dir.name}' already exists, skipping.", fg="yellow")
        return True
    try:
        access_token = get_access_token()
        url_with_token = inject_token_into_url(url, access_token)
        chosen = _resolve_branch(url, branch)
        branch_display = f"branch '{chosen}'" if chosen else "default branch"
        typer.secho(f"  ⇣ Cloning '{target_dir.name}' ({branch_display})…", fg="cyan")
        if chosen:
            Repo.clone_from(url_with_token, target_dir, branch=chosen)
        else:
            Repo.clone_from(url_with_token, target_dir)
        typer.secho(f"  ✓ Cloned '{target_dir.name}'", fg="green")
        return True
    except GitCommandError as e:
        stderr = (getattr(e, "stderr", "") or "").strip()
        reason = f"Git error: {e}"
        # Heuristic: if git complained the branch isn't upstream, surface the real cause
        if "Remote branch" in stderr and "not found" in stderr:
            reason = (
                f"The default branch for this repo is not 'main'. "
                f"git said: {stderr.splitlines()[-1]}"
            )
        errors.clone_failed(target_dir.name, reason)
        return False
    except errors.AccessTokenMissingError:
        errors.access_token_missing_rc_fallback()
        return False
    except Exception as e:
        errors.clone_failed(target_dir.name, f"Unexpected error: {e}")
        return False


def clone_module_command(
    url: str = typer.Option(..., "--url", help="Full HTTP URL of the module repo."),
    branch: Optional[str] = None,
    depth: int = typer.Option(1, "--depth", "-d", help="Max dependency depth to clone. 1 clones only the target module, 2 clones target + immediate dependencies, etc."),
    workers: int = typer.Option(4, "--workers", "-w", help="Max concurrent clones (1-8)."),
):
    """Clone a module and (optionally) its dependencies into the current directory."""
    try:
        core_modules = get_core_modules_from_config()
    except errors.ConfigError as e:
        errors._safe_exit(e)

    if not get_access_token_safe():
        typer.secho("")
        typer.secho("┌─ odooflow setup needed", fg="cyan", bold=True)
        typer.secho(
            "│  No GitLab access token found. Run `odooflow setup` to create one",
            fg="cyan",
        )
        typer.secho(
            "│  interactively, or set ODOOFLOW_ACCESS_TOKEN in your shell.",
            fg="cyan",
        )
        typer.secho("")
        typer.secho(
            "  Example:\n"
            "    export ODOOFLOW_ACCESS_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx",
            fg="cyan",
        )
        typer.secho("")
        raise typer.Exit(code=1)

    typer.secho("")
    typer.secho("┌─ odooflow clone", fg="cyan", bold=True)
    typer.secho(
        f"│  Depth: {depth}   Workers: {max(1, min(workers, 8))}",
        fg="cyan",
    )
    typer.secho("")

    visited = set()
    fail_count = 0
    lock = threading.Lock()

    def clone_recursive(module_url: str, current_branch: Optional[str], current_depth: int):
        nonlocal fail_count
        module_name = extract_module_name_from_url(module_url)

        with lock:
            if module_name in visited:
                typer.secho(f"  ↻ Already processed '{module_name}'.", fg="yellow")
                return False
            visited.add(module_name)

        target_path = Path.cwd() / module_name

        if not clone_repo(module_url, target_path, current_branch):
            typer.secho(f"  ✗ Skipping dependencies of '{module_name}'.", fg="red")
            with lock:
                fail_count += 1
            return False

        if current_depth <= 0:
            return True

        manifest_path = target_path / "__manifest__.py"
        if not manifest_path.exists():
            typer.secho(f"  · No manifest in '{module_name}'.", fg="yellow")
            return True

        manifest_data = safe_eval_manifest(manifest_path.read_text())
        dependencies = manifest_data.get("depends", [])

        if not dependencies:
            typer.secho(f"  · '{module_name}' has no dependencies.", fg="cyan")
            return True

        candidate_deps = [dep for dep in dependencies if dep not in core_modules]
        if not candidate_deps:
            return True

        next_depth = current_depth - 1

        def _resolve_and_run(dep_name: str):
            nonlocal fail_count
            dep_url = get_project_url_from_gitlab(module_name=dep_name)
            if not dep_url:
                with lock:
                    fail_count += 1
                return
            clone_recursive(dep_url, current_branch, next_depth)

        typer.secho(
            f"  ⇢ Resolving {len(candidate_deps)} dependency(ies) of '{module_name}' in parallel…",
            fg="cyan",
        )
        pool_size = max(1, min(workers, 8))
        with ThreadPoolExecutor(max_workers=pool_size) as executor:
            futures = [executor.submit(_resolve_and_run, dep) for dep in candidate_deps]
            for f in futures:
                f.result()

        return True

    clone_recursive(url, branch, depth)

    typer.secho("")
    typer.secho("└─ odooflow clone finished", fg="cyan", bold=True)
    if fail_count > 0:
        typer.secho(
            f"   ✗ {fail_count} module(s) failed to clone. See messages above.",
            fg="red",
            bold=True,
        )
        raise typer.Exit(code=1)
    typer.secho(
        f"   ✓ All {len(visited)} module(s) processed without errors.",
        fg="green",
        bold=True,
    )
    typer.secho("")
