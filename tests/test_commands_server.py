import json
import os

import pytest
from typer.testing import CliRunner
from unittest.mock import patch

from odooflow.cli import app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_env_dir(tmp_path):
    """Project dir with an empty .odooflow.env.json."""
    env_path = tmp_path / ".odooflow.env.json"
    env_path.write_text(json.dumps({"remotes": {}}))
    return tmp_path


@pytest.fixture
def fake_key(tmp_path):
    p = tmp_path / "id_rsa"
    p.write_text("fake")
    p.chmod(0o600)
    return str(p)


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


class TestServerList:
    def test_no_profiles_warns(self, runner, tmp_env_dir):
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "list"])
        # CliRunner surfaces stdout; may exit 1 on purpose when empty.
        assert "No server profiles configured" in result.stdout

    def test_lists_named_profiles(self, runner, tmp_env_dir, fake_key):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {
                    "staging": {"host": "s.example", "user": "deploy", "directory": "/srv", "key_path": fake_key},
                    "prod": {"host": "p.example", "user": "deploy", "directory": "/srv", "key_path": fake_key},
                },
                "default_server": "staging",
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "list"])
        assert result.exit_code == 0
        assert "staging" in result.stdout
        assert "prod" in result.stdout
        # Default marker on staging column.
        assert "*" in result.stdout

    def test_json_output_does_not_leak_password(self, runner, tmp_env_dir):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {
                    "pw": {"host": "x", "user": "u", "directory": "/", "password": "supersecret"},
                }
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "list", "--json"])
        assert "supersecret" not in result.stdout


# --------------------------------------------------------------------------- #
# add (flags only — no interactive prompts)
# --------------------------------------------------------------------------- #


class TestServerAdd:
    def _add_kwargs(self, name, key):
        return [
            "server", "add", name,
            "--host", "10.0.0.5",
            "--port", "22",
            "--user", "deploy",
            "--directory", "/srv",
            "--key-path", key,
            "--no-default",
        ]

    def test_add_saves_profile(self, runner, tmp_env_dir, fake_key):
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, self._add_kwargs("staging", fake_key))
        assert result.exit_code == 0, result.stdout
        env = json.loads((tmp_env_dir / ".odooflow.env.json").read_text())
        assert env["remotes"]["servers"]["staging"]["host"] == "10.0.0.5"
        assert env["remotes"]["servers"]["staging"]["user"] == "deploy"

    def test_add_makes_default_when_requested(
        self, runner, tmp_env_dir, fake_key
    ):
        kwargs = self._add_kwargs("staging", fake_key)
        kwargs[-1] = "--default"  # flip the flag
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            runner.invoke(app, kwargs)
        env = json.loads((tmp_env_dir / ".odooflow.env.json").read_text())
        assert env["remotes"]["default_server"] == "staging"

    def test_add_migrates_legacy_when_present(
        self, runner, tmp_env_dir, fake_key
    ):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {"server": {"host": "h", "user": "u", "directory": "/"}}
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, self._add_kwargs("staging", fake_key))
        assert result.exit_code == 0, result.stdout
        env = json.loads(env_path.read_text())
        # Legacy removed, both old (as 'default') and new 'staging' coexist.
        assert "server" not in env["remotes"]
        assert env["remotes"]["servers"]["default"]["host"] == "h"
        assert env["remotes"]["servers"]["staging"]["host"] == "10.0.0.5"

    def test_add_rejects_missing_key_file(self, runner, tmp_env_dir):
        kwargs = self._add_kwargs("staging", "/nonexistent/key")
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, kwargs)
        assert result.exit_code != 0


# --------------------------------------------------------------------------- #
# show
# --------------------------------------------------------------------------- #


class TestServerShow:
    def test_show_default_profile(
        self, runner, tmp_env_dir, fake_key
    ):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {"staging": {"host": "h", "user": "u", "directory": "/", "key_path": fake_key}},
                "default_server": "staging",
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "show"])
        assert result.exit_code == 0
        assert "staging (default)" in result.stdout
        assert "h" in result.stdout

    def test_show_named_profile(self, runner, tmp_env_dir, fake_key):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {
                    "a": {"host": "ha", "user": "ua", "directory": "/", "key_path": fake_key},
                    "b": {"host": "hb", "user": "ub", "directory": "/", "key_path": fake_key},
                },
                "default_server": "a",
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "show", "b"])
        assert result.exit_code == 0
        assert "Server profile: b" in result.stdout
        assert "hb" in result.stdout

    def test_password_hidden_by_default(self, runner, tmp_env_dir):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {
                    "pw": {"host": "h", "user": "u", "directory": "/", "password": "abc12345"},
                },
                "default_server": "pw",
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "show"])
        assert "abc12345" not in result.stdout

    def test_password_revealed_when_requested(self, runner, tmp_env_dir):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {
                    "pw": {"host": "h", "user": "u", "directory": "/", "password": "abc12345"},
                },
                "default_server": "pw",
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "show", "--reveal-password"])
        assert "abc12345" in result.stdout


# --------------------------------------------------------------------------- #
# use / remove
# --------------------------------------------------------------------------- #


class TestServerUseRemove:
    def test_use_changes_default(self, runner, tmp_env_dir, fake_key):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {
                    "a": {"host": "ha", "user": "u", "directory": "/", "key_path": fake_key},
                    "b": {"host": "hb", "user": "u", "directory": "/", "key_path": fake_key},
                },
                "default_server": "a",
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            runner.invoke(app, ["server", "use", "b"])
        env = json.loads(env_path.read_text())
        assert env["remotes"]["default_server"] == "b"

    def test_use_unknown_exits_nonzero(self, runner, tmp_env_dir, fake_key):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {"servers": {"a": {"host": "h"}}}
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "use", "ghost"])
        assert result.exit_code != 0

    def test_remove(self, runner, tmp_env_dir, fake_key):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {
                    "a": {"host": "ha", "user": "u", "directory": "/", "key_path": fake_key},
                    "b": {"host": "hb", "user": "u", "directory": "/", "key_path": fake_key},
                },
                "default_server": "a",
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "remove", "b"])
        assert result.exit_code == 0
        env = json.loads(env_path.read_text())
        assert "b" not in env["remotes"]["servers"]

    def test_remove_default_picks_remaining(self, runner, tmp_env_dir, fake_key):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {
                    "a": {"host": "ha", "user": "u", "directory": "/", "key_path": fake_key},
                    "b": {"host": "hb", "user": "u", "directory": "/", "key_path": fake_key},
                },
                "default_server": "a",
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            runner.invoke(app, ["server", "remove", "a"])
        env = json.loads(env_path.read_text())
        assert env["remotes"]["default_server"] == "b"


# --------------------------------------------------------------------------- #
# test
# --------------------------------------------------------------------------- #


class TestServerTest:
    def test_no_profile_exits(self, runner, tmp_env_dir):
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "test"])
        assert result.exit_code != 0

    def test_tcp_failure_reports_clearly(
        self, runner, tmp_env_dir
    ):
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {
                    "bad": {
                        "host": "127.0.0.255",
                        "port": 1,  # closed port
                        "user": "nobody",
                        "directory": "/",
                    }
                },
                "default_server": "bad",
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "test"])
        assert result.exit_code != 0
        assert "[tcp]" in result.stdout
