"""
GitLab REST helpers. Kept tiny and side-effect-free so they're easy to mock.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote, urlparse

import requests

from odooflow import errors
from odooflow.config_manager import (
    DEFAULT_CONFIG,
    get_access_token,
    load_config,
)


def extract_project_path_from_url(repo_url: str) -> Optional[str]:
    """
    `https://gitlab.ebtech-solution.com/ebtech/internal/ebt_hr_attendance`
    -> `ebtech/internal/ebt_hr_attendance`

    Strip a trailing `.git` and trailing slash. Return None if no path
    component is found (caller decides what to do).
    """
    parsed = urlparse(repo_url)
    path = parsed.path.lstrip("/").rstrip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    return path or None


def get_default_branch(repo_url: str, *, gitlab_url: Optional[str] = None) -> Optional[str]:
    """
    Return the project's default branch name (whatever it is — main, master,
    16.0, anything). Never raises; on any failure returns None so the caller
    can fall back to "let git figure it out".

    Strategy:
      1. Resolve `<gitlab_url>` from config if not provided.
      2. Pull the access token. If missing, return None (caller will not
         pass --branch and git will use the project's own default).
      3. URL-encode the project path and call /api/v4/projects/:path.
         Reading `default_branch` from the JSON. Empty string is treated
         as None.
    """
    if gitlab_url is None:
        cfg = load_config(strict=False)
        gitlab_url = cfg.get("gitlab_url", DEFAULT_CONFIG["gitlab_url"])

    project_path = extract_project_path_from_url(repo_url)
    if not project_path:
        return None

    try:
        token = get_access_token()
    except errors.AccessTokenMissingError:
        return None

    api_url = f"{gitlab_url.rstrip('/')}/api/v4/projects/{quote(project_path, safe='')}"

    try:
        response = requests.get(
            api_url,
            params={"access_token": token},
            headers={"Accept": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    default = (data or {}).get("default_branch")
    return default or None


__all__ = ["extract_project_path_from_url", "get_default_branch"]
