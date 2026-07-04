"""
Server profile storage and resolution.

Schema (in .odooflow.env.json under `remotes`):

    "servers": {
      "staging": {
        "host": "...", "port": 22, "user": "...",
        "directory": "...", "key_path": "...", "password": "...",
        "post_push_cmd": "..."
      }
    },
    "default_server": "staging",

Legacy (still supported, written by 0.1/0.2 code, read by 0.3):

    "server": {"host": "...", ...}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from odooflow import errors


ALLOWED_KEYS = frozenset(
    {
        "host",
        "port",
        "user",
        "password",
        "key_path",
        "directory",
        "post_push_cmd",
        # Runtime metadata, written silently by `server test` and `push`:
        "last_used",
        "last_test_ok",
    }
)

REQUIRED_KEYS = ("host", "user", "directory")

LEGACY_KEY = "server"
NEW_KEY = "servers"
DEFAULT_KEY = "default_server"
DEFAULT_PROFILE_NAME = "default"


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #


def load_remotes(env: dict) -> dict:
    """Return `env['remotes']` as a dict, defaulting to {}."""
    remotes = env.get("remotes")
    if remotes is None:
        return {}
    if not isinstance(remotes, dict):
        return {}
    return remotes


def load_servers(env: dict) -> Dict[str, dict]:
    """Return the named-profiles dict, migrating from legacy if needed."""
    remotes = load_remotes(env)
    if isinstance(remotes.get(NEW_KEY), dict):
        servers = {k: v for k, v in remotes[NEW_KEY].items() if isinstance(v, dict)}
    else:
        servers = {}

    legacy = remotes.get(LEGACY_KEY)
    if isinstance(legacy, dict) and servers == {} and DEFAULT_PROFILE_NAME not in servers:
        servers[DEFAULT_PROFILE_NAME] = dict(legacy)

    return servers


def load_default_name(env: dict) -> Optional[str]:
    """Return the explicit default_server name, or None if unset."""
    remotes = load_remotes(env)
    name = remotes.get(DEFAULT_KEY)
    return name if isinstance(name, str) and name else None


def resolve_default_name(env: dict) -> Optional[str]:
    """
    Resolve which profile name should be considered the default.
    Order:
      1. explicit `default_server` in remotes.
      2. only one profile exists -> its name.
      3. legacy `server` -> "default".
      4. None.
    """
    servers = load_servers(env)
    explicit = load_default_name(env)
    if explicit and explicit in servers:
        return explicit
    if len(servers) == 1:
        return next(iter(servers))
    legacy = load_remotes(env).get(LEGACY_KEY)
    if isinstance(legacy, dict):
        return DEFAULT_PROFILE_NAME
    return None


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def validate_profile(profile: dict) -> List[str]:
    """Return a list of human-readable errors. Empty list => valid."""
    errors_list: List[str] = []

    if not isinstance(profile, dict):
        return ["profile must be a JSON object"]

    for key in profile:
        if key not in ALLOWED_KEYS:
            errors_list.append(
                f"unknown key '{key}' (allowed: {', '.join(sorted(ALLOWED_KEYS))})"
            )

    for required in REQUIRED_KEYS:
        value = profile.get(required)
        if not value or not isinstance(value, str):
            errors_list.append(f"missing required string field '{required}'")

    port = profile.get("port")
    if port is not None:
        if not isinstance(port, int) or isinstance(port, bool):
            errors_list.append("'port' must be an integer")
        elif not (1 <= port <= 65535):
            errors_list.append("'port' must be between 1 and 65535")

    host = profile.get("host")
    if isinstance(host, str) and "://" in host:
        errors_list.append(
            f"'host' must not include a scheme (got '{host}'); use bare hostname"
        )

    key_path = profile.get("key_path")
    if isinstance(key_path, str) and key_path:
        expanded = Path(key_path).expanduser()
        if not expanded.exists():
            errors_list.append(f"'key_path' does not exist on disk: {expanded}")

    password = profile.get("password")
    if password is not None and not isinstance(password, str):
        errors_list.append("'password' must be a string")

    return errors_list


def sanitise_profile(profile: dict) -> dict:
    """Drop unknown keys and coerce port to int if possible. Return a new dict."""
    cleaned: dict = {}
    for key, value in profile.items():
        if key not in ALLOWED_KEYS:
            continue
        if key == "port" and isinstance(value, str) and value.isdigit():
            cleaned[key] = int(value)
        elif key == "key_path" and isinstance(value, str):
            cleaned[key] = str(Path(value).expanduser())
        else:
            cleaned[key] = value
    return cleaned


# --------------------------------------------------------------------------- #
# Resolve a profile for `odooflow push`
# --------------------------------------------------------------------------- #


def select_profile(
    env: dict,
    requested_name: Optional[str] = None,
) -> Tuple[Optional[str], Optional[dict]]:
    """
    Resolve which profile to use.

    Order:
      1. requested_name (CLI flag)
      2. explicit default_server
      3. only profile in `servers`
      4. legacy `server` (-> profile name "default")

    Returns (name, profile_dict) or (None, None) if nothing matches.
    """
    servers = load_servers(env)

    if requested_name:
        if requested_name in servers:
            return requested_name, servers[requested_name]
        return None, None

    explicit = load_default_name(env)
    if explicit and explicit in servers:
        return explicit, servers[explicit]

    if len(servers) == 1:
        name = next(iter(servers))
        return name, servers[name]

    legacy = load_remotes(env).get(LEGACY_KEY)
    if isinstance(legacy, dict):
        return DEFAULT_PROFILE_NAME, legacy

    return None, None


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def save_profile(env_path: Path, env: dict, profile_name: str, profile: dict) -> Tuple[dict, bool]:
    """
    Insert or replace a named profile in `env` and write back to disk.

    Returns (new_env_dict, migrated_from_legacy). The caller can detect
    `migrated_from_legacy=True` to surface a one-time deprecation hint.

    The path is *overwritten*, not appended to — callers should pass the
    full current env dict (as they read it via `read_env_file`).
    """
    errors_list = validate_profile(profile)
    if errors_list:
        msgs = "\n    ".join(errors_list)
        raise errors.ConfigError(
            f"Server profile '{profile_name}' is invalid:\n    {msgs}"
        )

    env = dict(env)  # shallow copy
    env["remotes"] = dict(env.get("remotes", {}))

    migrated = False
    # First-time migration from legacy single-server form.
    if LEGACY_KEY in env["remotes"] and NEW_KEY not in env["remotes"]:
        legacy = env["remotes"][LEGACY_KEY]
        if isinstance(legacy, dict):
            env["remotes"][NEW_KEY] = {
                DEFAULT_PROFILE_NAME: sanitise_profile(legacy),
            }
            migrated = True
            # Promote legacy "default" to "default_server".
            if DEFAULT_KEY not in env["remotes"]:
                env["remotes"][DEFAULT_KEY] = DEFAULT_PROFILE_NAME
        del env["remotes"][LEGACY_KEY]
    else:
        env["remotes"].setdefault(NEW_KEY, {})

    servers = env["remotes"][NEW_KEY]
    servers[profile_name] = sanitise_profile(profile)

    env_path.write_text(json.dumps(env, indent=4))
    try:
        env_path.chmod(0o600)
    except OSError:
        pass

    return env, migrated


def remove_profile(env_path: Path, env: dict, profile_name: str) -> bool:
    """Remove a profile; return True if removed."""
    env = dict(env)
    env["remotes"] = dict(env.get("remotes", {}))
    servers = env["remotes"].get(NEW_KEY)
    if not isinstance(servers, dict) or profile_name not in servers:
        return False
    del servers[profile_name]
    if env["remotes"].get(DEFAULT_KEY) == profile_name:
        env["remotes"][DEFAULT_KEY] = (
            next(iter(servers), None) if servers else None
        )
    env_path.write_text(json.dumps(env, indent=4))
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    return True


def set_default(env_path: Path, env: dict, profile_name: str) -> dict:
    """Persist `default_server = profile_name`. Returns the updated env dict."""
    env = dict(env)
    env["remotes"] = dict(env.get("remotes", {}))
    env["remotes"][DEFAULT_KEY] = profile_name
    env_path.write_text(json.dumps(env, indent=4))
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    return env


__all__ = [
    "ALLOWED_KEYS",
    "REQUIRED_KEYS",
    "LEGACY_KEY",
    "NEW_KEY",
    "DEFAULT_KEY",
    "DEFAULT_PROFILE_NAME",
    "load_remotes",
    "load_servers",
    "load_default_name",
    "resolve_default_name",
    "validate_profile",
    "sanitise_profile",
    "select_profile",
    "save_profile",
    "remove_profile",
    "set_default",
]
