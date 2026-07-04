import json

import pytest

from odooflow import errors
from odooflow.utils import server_profile as sp


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


class TestLoadServers:
    def test_empty(self):
        assert sp.load_servers({}) == {}
        assert sp.load_servers({"remotes": None}) == {}
        assert sp.load_servers({"remotes": {}}) == {}

    def test_explicit_servers(self):
        env = {"remotes": {"servers": {"qa": {"host": "q", "user": "u", "directory": "/"}}}}
        assert sp.load_servers(env) == env["remotes"]["servers"]

    def test_filters_non_dict_profiles(self):
        env = {"remotes": {"servers": {"ok": {"host": "a"}, "bad": "string", "listy": [1, 2]}}}
        servers = sp.load_servers(env)
        assert "ok" in servers
        assert "bad" not in servers
        assert "listy" not in servers

    def test_legacy_single_server_migrates(self):
        env = {
            "remotes": {
                "server": {"host": "h", "user": "u", "directory": "/"},
            }
        }
        servers = sp.load_servers(env)
        assert servers == {
            sp.DEFAULT_PROFILE_NAME: {"host": "h", "user": "u", "directory": "/"}
        }

    def test_legacy_does_not_overwrite_existing_named(self):
        env = {
            "remotes": {
                "servers": {"qa": {"host": "q"}},
                "server": {"host": "ignored"},
            }
        }
        # Named profiles win; legacy is left for the explicit save_profile migration
        assert "qa" in sp.load_servers(env)


# --------------------------------------------------------------------------- #
# Default resolution
# --------------------------------------------------------------------------- #


class TestResolveDefault:
    def test_explicit_default_when_present(self):
        env = {"remotes": {"servers": {"a": {}, "b": {}}, "default_server": "b"}}
        assert sp.resolve_default_name(env) == "b"

    def test_single_profile_becomes_default(self):
        env = {"remotes": {"servers": {"only": {}}}}
        assert sp.resolve_default_name(env) == "only"

    def test_default_unset_when_multiple(self):
        env = {"remotes": {"servers": {"a": {}, "b": {}}}}
        assert sp.resolve_default_name(env) is None

    def test_legacy_acts_as_default(self):
        env = {"remotes": {"server": {"host": "h"}}}
        assert sp.resolve_default_name(env) == sp.DEFAULT_PROFILE_NAME

    def test_explicit_default_must_exist(self):
        env = {"remotes": {"servers": {"a": {}}, "default_server": "ghost"}}
        # Falls back to single profile heuristic
        assert sp.resolve_default_name(env) == "a"


# --------------------------------------------------------------------------- #
# select_profile
# --------------------------------------------------------------------------- #


class TestSelectProfile:
    def test_requested_name(self):
        env = {
            "remotes": {
                "servers": {
                    "a": {"host": "a"},
                    "b": {"host": "b"},
                },
                "default_server": "a",
            }
        }
        name, profile = sp.select_profile(env, requested_name="b")
        assert name == "b"
        assert profile == {"host": "b"}

    def test_requested_name_unknown_returns_none_pair(self):
        env = {"remotes": {"servers": {"a": {"host": "a"}}, "default_server": "a"}}
        name, profile = sp.select_profile(env, requested_name="ghost")
        assert name is None
        assert profile is None

    def test_default_resolution(self):
        env = {
            "remotes": {
                "servers": {"a": {"host": "a"}, "b": {"host": "b"}},
                "default_server": "b",
            }
        }
        name, profile = sp.select_profile(env)
        assert (name, profile) == ("b", {"host": "b"})

    def test_legacy_fallback(self):
        env = {
            "remotes": {
                "server": {"host": "h"},
            }
        }
        name, profile = sp.select_profile(env)
        assert name == sp.DEFAULT_PROFILE_NAME
        assert profile == {"host": "h"}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


@pytest.fixture
def tmp_key(tmp_path):
    """A real, 600-perm key path on disk so validation does not flag it."""
    p = tmp_path / "id_rsa"
    p.write_text("fake")
    p.chmod(0o600)
    return str(p)


class TestValidateProfile:
    def test_valid_minimum(self, tmp_key):
        profile = {
            "host": "10.0.0.5",
            "user": "deploy",
            "directory": "/srv",
            "key_path": tmp_key,
        }
        assert sp.validate_profile(profile) == []

    def test_missing_required(self):
        errors_list = sp.validate_profile({"host": "h"})
        joined = " ".join(errors_list)
        assert "user" in joined
        assert "directory" in joined

    def test_non_integer_port_rejected(self):
        profile = {
            "host": "h",
            "user": "u",
            "directory": "/",
            "port": "22",
        }
        errors_list = sp.validate_profile(profile)
        assert any("'port' must be an integer" in e for e in errors_list)

    def test_port_out_of_range_rejected(self):
        profile = {
            "host": "h",
            "user": "u",
            "directory": "/",
            "port": 70000,
        }
        errors_list = sp.validate_profile(profile)
        assert any("between 1 and 65535" in e for e in errors_list)

    def test_host_with_scheme_rejected(self):
        profile = {
            "host": "https://gitlab.com",
            "user": "u",
            "directory": "/",
        }
        errors_list = sp.validate_profile(profile)
        assert any("must not include a scheme" in e for e in errors_list)

    def test_key_path_missing_rejected(self):
        profile = {
            "host": "h",
            "user": "u",
            "directory": "/",
            "key_path": "/nonexistent/of-course",
        }
        errors_list = sp.validate_profile(profile)
        assert any("does not exist on disk" in e for e in errors_list)

    def test_unknown_keys_flagged(self):
        profile = {
            "host": "h",
            "user": "u",
            "directory": "/",
            "made_up": "x",
        }
        errors_list = sp.validate_profile(profile)
        assert any("unknown key 'made_up'" in e for e in errors_list)

    def test_bool_port_rejected(self):
        # In Python `True == 1` so without an explicit bool rejection,
        # `True` would silently pass an integer range check.
        profile = {
            "host": "h",
            "user": "u",
            "directory": "/",
            "port": True,
        }
        errors_list = sp.validate_profile(profile)
        assert any("'port' must be an integer" in e for e in errors_list)


class TestSanitise:
    def test_strips_unknown_keys(self):
        profile = {
            "host": "h",
            "user": "u",
            "directory": "/",
            "made_up": "x",
        }
        cleaned = sp.sanitise_profile(profile)
        assert "made_up" not in cleaned

    def test_coerces_string_port(self):
        cleaned = sp.sanitise_profile({"host": "h", "user": "u", "directory": "/", "port": "22"})
        assert cleaned["port"] == 22
        assert isinstance(cleaned["port"], int)

    def test_expands_user_in_key_path(self):
        cleaned = sp.sanitise_profile(
            {"host": "h", "user": "u", "directory": "/", "key_path": "~/f"}
        )
        assert "~" not in cleaned["key_path"]


# --------------------------------------------------------------------------- #
# save_profile / remove_profile / set_default
# --------------------------------------------------------------------------- #


class TestPersistence:
    def test_save_and_remove_round_trip(self, tmp_path, tmp_key):
        env_path = tmp_path / "env.json"
        env_path.write_text(json.dumps({"remotes": {}}))
        env = json.loads(env_path.read_text())

        new_env, migrated = sp.save_profile(
            env_path,
            env,
            "staging",
            {
                "host": "10.0.0.1",
                "user": "deploy",
                "directory": "/srv",
                "key_path": tmp_key,
            },
        )
        assert migrated is False
        assert new_env["remotes"]["servers"]["staging"]["host"] == "10.0.0.1"

        # File on disk matches.
        on_disk = json.loads(env_path.read_text())
        assert on_disk["remotes"]["servers"]["staging"]["host"] == "10.0.0.1"

        # Remove.
        ok = sp.remove_profile(env_path, new_env, "staging")
        assert ok is True
        after = json.loads(env_path.read_text())
        assert "staging" not in after["remotes"].get("servers", {})

    def test_remove_unknown_returns_false(self, tmp_path):
        env_path = tmp_path / "env.json"
        env_path.write_text(json.dumps({"remotes": {"servers": {"a": {}}}}))
        env = json.loads(env_path.read_text())
        assert sp.remove_profile(env_path, env, "ghost") is False

    def test_save_then_set_default(self, tmp_path, tmp_key):
        env_path = tmp_path / "env.json"
        env_path.write_text(json.dumps({"remotes": {"servers": {}}}))
        env = json.loads(env_path.read_text())
        new_env, _ = sp.save_profile(
            env_path, env, "staging",
            {"host": "h", "user": "u", "directory": "/", "key_path": tmp_key},
        )
        sp.set_default(env_path, new_env, "staging")
        after = json.loads(env_path.read_text())
        assert after["remotes"]["default_server"] == "staging"

    def test_legacy_migration_on_first_save(self, tmp_path, tmp_key):
        env_path = tmp_path / "env.json"
        env_path.write_text(json.dumps(
            {"remotes": {"server": {"host": "h", "user": "u", "directory": "/"}}}
        ))
        env = json.loads(env_path.read_text())
        new_env, migrated = sp.save_profile(
            env_path, env, "qa",
            {"host": "q", "user": "u", "directory": "/", "key_path": tmp_key},
        )
        assert migrated is True
        remotes = new_env["remotes"]
        # Legacy form is gone; both old (under "default") and new "qa" coexist
        assert sp.LEGACY_KEY not in remotes
        assert remotes[sp.NEW_KEY][sp.DEFAULT_PROFILE_NAME]["host"] == "h"
        assert remotes[sp.NEW_KEY]["qa"]["host"] == "q"
        assert remotes[sp.DEFAULT_KEY] == sp.DEFAULT_PROFILE_NAME

    def test_invalid_profile_raises(self, tmp_path):
        env_path = tmp_path / "env.json"
        env_path.write_text(json.dumps({"remotes": {}}))
        with pytest.raises(errors.ConfigError) as exc:
            sp.save_profile(
                env_path,
                {"remotes": {}},
                "broken",
                {"host": "h"},  # missing user & directory
            )
        assert "Server profile 'broken'" in str(exc.value)

    def test_remove_default_picks_remaining(self, tmp_path, tmp_key):
        env_path = tmp_path / "env.json"
        env_path.write_text(json.dumps({"remotes": {"servers": {}, "default_server": "only"}}))
        env = json.loads(env_path.read_text())
        new_env, _ = sp.save_profile(
            env_path, env, "only",
            {"host": "h", "user": "u", "directory": "/", "key_path": tmp_key},
        )
        sp.set_default(env_path, new_env, "only")
        assert sp.remove_profile(env_path, new_env, "only") is True
        after = json.loads(env_path.read_text())
        # No servers remain; default_server is null.
        assert after["remotes"]["servers"] == {}
        assert after["remotes"]["default_server"] is None
