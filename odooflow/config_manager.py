import os
import json
import typer
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from odooflow import errors

DEFAULT_CONFIG = {
    "env_file": ".odooflow.env.json",
    "manifest_file": "__manifest__.py",
    "core_modules" : ["base", "web", "mail", "sale", "account"],
    "sync_keys" : ["name", "author", "license", "version", "depends"],
    "gitlab_url": "https://gitlab.ebtech-solution.com",
}

CONFIG_FILENAME = ".odooflowrc"


def get_global_config_path() -> Path:
    return Path.home() / ".odooflowrc"


def _format_missing_keys(current: Dict, required: list) -> list:
    return [k for k in required if k not in current]


def _backup_corrupt_rc(path: Path) -> Optional[Path]:
    """Move a malformed rc to a timestamped backup so we can recover later."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.corrupt.{timestamp}")
        path.rename(backup)
        return backup
    except OSError:
        return None


def _get_printed_notices() -> set[str]:
    """Process-wide set of already-printed notices."""
    if not hasattr(_get_printed_notices, "_store"):
        _get_printed_notices._store = set()
    return _get_printed_notices._store


def reset_printed_notices() -> None:
    """Test hook: forget all notices that were previously printed."""
    _get_printed_notices().clear()


def _print_once(key: str, fn, *args, **kwargs) -> None:
    store = _get_printed_notices()
    if key in store:
        return
    store.add(key)
    fn(*args, **kwargs)


def load_config(strict: bool = False) -> Dict:
    """
    Load ~/.odooflowrc. Returns a fully-populated config dict.

    Behaviour:
      * File missing              -> defaults.
      * File empty                -> warn, back it up, return defaults.
      * File has invalid JSON     -> back it up, return defaults with a clear,
                                     user-actionable message printed once.
      * strict=True and any of the
        above problems happened   -> raise ConfigError (lets callers fail fast
                                     with their own context instead of
                                     silently using defaults).

    A ConfigError is raised instead of typer.Exit so this function can be
    safely called at import time, inside non-CLI helpers, or inside try/except
    blocks that want to translate the error into something domain-specific.
    """
    path = get_global_config_path()

    if not path.exists():
        _print_once("missing", errors.config_file_missing, path)
        return DEFAULT_CONFIG.copy()

    raw = ""
    try:
        raw = path.read_text()
    except OSError as e:
        backup = _backup_corrupt_rc(path)
        _print_once(
            f"unreadable:{path}",
            errors.config_unreadable,
            path, str(e), backup,
        )
        if strict:
            raise errors.ConfigError(str(e)) from e
        return DEFAULT_CONFIG.copy()

    stripped = raw.strip()
    if not stripped:
        backup = _backup_corrupt_rc(path)
        _print_once(
            f"empty:{path}",
            errors.config_empty,
            path, backup,
        )
        if strict:
            raise errors.ConfigError(f"Empty config at {path}")
        return DEFAULT_CONFIG.copy()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as e:
        backup = _backup_corrupt_rc(path)
        _print_once(
            f"corrupt:{path}",
            errors.config_corrupt,
            path, str(e), backup,
        )
        if strict:
            raise errors.ConfigError(f"Invalid JSON at {path}: {e}") from e
        return DEFAULT_CONFIG.copy()

    if not isinstance(parsed, dict):
        backup = _backup_corrupt_rc(path)
        _print_once(
            f"shape:{path}",
            errors.config_shape_wrong,
            path, backup,
        )
        if strict:
            raise errors.ConfigError(f"Config at {path} is not a JSON object")
        return DEFAULT_CONFIG.copy()

    merged = DEFAULT_CONFIG.copy()
    merged.update(parsed)

    missing = _format_missing_keys(
        merged,
        ["env_file", "manifest_file", "gitlab_url"],
    )
    if missing:
        _print_once(
            f"missingkeys:{path}:{','.join(missing)}",
            errors.config_missing_keys,
            path, missing,
        )
        if strict:
            raise errors.ConfigError(f"Config at {path} missing keys: {missing}")

    return merged


def save_config(config: Dict):
    path = get_global_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=4)


def is_configured() -> bool:
    """Cheap check: does the user have a token configured (env or rc)?"""
    if os.getenv("ODOOFLOW_ACCESS_TOKEN"):
        return True
    try:
        cfg = load_config(strict=False)
    except errors.ConfigError:
        return False
    return bool(cfg.get("access_token"))


def get_access_token() -> str:
    """
    Return the GitLab access token. Resolution order:
      1. ODOOFLOW_ACCESS_TOKEN env var.
      2. access_token entry in ~/.odooflowrc.
    Raises ConfigError with a guided 'how to fix' message if neither works.
    """
    token = os.getenv("ODOOFLOW_ACCESS_TOKEN")
    if token:
        return token

    try:
        config = load_config(strict=False)
    except errors.ConfigError as e:
        raise errors.ConfigError(str(e)) from e

    token = config.get("access_token")
    if token:
        return token

    raise errors.AccessTokenMissingError(
        rc_path=get_global_config_path(),
    )


def get_core_modules_from_config() -> set:
    config = load_config(strict=False)
    return set(config.get("core_modules", DEFAULT_CONFIG.get("core_modules", [])))
