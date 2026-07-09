import json
import os
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner
from unittest.mock import patch

from odooflow.cli import app
from odooflow import errors


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


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

    def test_add_rejects_missing_key_file(self, runner, tmp_env_dir, fake_key):
        """A missing key path triggers a wizard re-prompt until the user
        provides a valid path. We confirm by feeding two invalid inputs
        and then a real key — the CLI must end cleanly with the profile
        saved using the real key.
        """
        # typer.prompt in the wizard reads from this sequence:
        #   1. "Auth method — type 'key' or 'password'"  -> "key"
        #   2. "Path to SSH private key" (1st)            -> "/nonexistent/key"
        #   3. "Path to SSH private key" (2nd)            -> fake_key
        kwargs = self._add_kwargs("staging", "/nonexistent/key")
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(
                app,
                kwargs,
                input="key\n/nonexistent/key\n" + str(fake_key) + "\n",
            )
        assert result.exit_code == 0, result.stdout
        env = json.loads((tmp_env_dir / ".odooflow.env.json").read_text())
        assert env["remotes"]["servers"]["staging"]["key_path"] == fake_key

    def test_add_with_no_validate_bypasses_preflight(
        self, runner, tmp_env_dir, fake_key
    ):
        """CI users can pass --no-validate on a real key path; the wizard's
        pre-prompt check is skipped, and saving succeeds. The persistent
        validator still runs at save time but allows the file to exist."""
        kwargs = self._add_kwargs("staging", fake_key)
        # Drop the trailing --no-default and append --no-validate instead.
        kwargs.pop()
        kwargs.append("--no-validate")
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, kwargs)
        assert result.exit_code == 0, result.stdout
        env = json.loads((tmp_env_dir / ".odooflow.env.json").read_text())
        assert env["remotes"]["servers"]["staging"]["key_path"] == fake_key


# --------------------------------------------------------------------------- #
# Wizard prompt flow (unit-tested at the helper level, not via CliRunner,
# which gets flaky when mocking typer.prompt/typer.confirm).
# --------------------------------------------------------------------------- #


class TestPromptHelpers:
    def test_validate_host_strict_rejects_schemes(self):
        from odooflow.commands.server import _validate_host_strict
        assert _validate_host_strict("10.0.0.1")
        assert _validate_host_strict("example.com")
        assert not _validate_host_strict("https://example.com")
        assert not _validate_host_strict("ssh://user@host")
        assert not _validate_host_strict("")

    def test_prompt_port_loop_returns_int(self, monkeypatch):
        from odooflow.commands.server import _prompt_port

        answers = iter(["abc", "70000", "22"])
        monkeypatch.setattr(
            "odooflow.commands.server.typer.prompt", lambda *a, **kw: next(answers)
        )
        port = _prompt_port(default=22)
        assert port == 22
        # We consumed 3 answers (validation rejected two).
        assert list(answers) == []

    def test_prompt_auth_method_loops(self, monkeypatch):
        from odooflow.commands.server import _prompt_auth_method

        answers = iter(["maybe", "garbage", "k"])
        monkeypatch.setattr(
            "odooflow.commands.server.typer.prompt", lambda *a, **kw: next(answers)
        )
        choice = _prompt_auth_method()
        assert choice == "key"
        assert list(answers) == []

    def test_prompt_auth_method_password(self, monkeypatch):
        from odooflow.commands.server import _prompt_auth_method

        monkeypatch.setattr(
            "odooflow.commands.server.typer.prompt", lambda *a, **kw: "Password"
        )
        assert _prompt_auth_method() == "password"

    def test_prompt_password_rejects_empty(self, monkeypatch):
        from odooflow.commands.server import _prompt_password

        answers = iter(["", "", "realpw"])
        monkeypatch.setattr(
            "odooflow.commands.server.typer.prompt", lambda *a, **kw: next(answers)
        )
        pw = _prompt_password()
        assert pw == "realpw"
        assert list(answers) == []

    def test_prompt_key_path_returns_expanded(self, monkeypatch, tmp_path):
        from odooflow.commands.server import _prompt_key_path

        key = tmp_path / "id_rsa"
        key.write_text("x")
        monkeypatch.setattr(
            "odooflow.commands.server.typer.prompt", lambda *a, **kw: str(key)
        )
        assert _prompt_key_path(no_validate=False) == str(key)

    def test_prompt_key_path_no_validate_accepts_missing(
        self, monkeypatch, tmp_path
    ):
        from odooflow.commands.server import _prompt_key_path

        target = tmp_path / "does-not-exist"
        monkeypatch.setattr(
            "odooflow.commands.server.typer.prompt", lambda *a, **kw: str(target)
        )
        # With no_validate=True we skip the existence check entirely.
        assert _prompt_key_path(no_validate=True) == str(target)


# --------------------------------------------------------------------------- #
# Traceback regression: server add + remote --server-json never traceback.
# --------------------------------------------------------------------------- #


class TestNoTracebackOnValidationFailure:
    def test_server_add_does_not_traceback_on_validation(
        self, runner, tmp_env_dir, fake_key
    ):
        from odooflow.utils import server_profile

        def boom(*a, **kw):
            raise errors.ConfigError(
                "Server profile 'qa' is invalid:\n    missing field"
            )

        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            with patch.object(server_profile, "save_profile", side_effect=boom):
                result = runner.invoke(
                    app,
                    [
                        "server", "add", "qa",
                        "--host", "h",
                        "--user", "u",
                        "--directory", "/",
                        "--key-path", fake_key,
                        "--no-default",
                    ],
                )
        assert result.exit_code == 1
        combined = result.stdout + (result.stderr or "")
        assert "Traceback" not in combined
        assert "Server profile 'qa' is invalid" in combined

    def test_remote_server_json_does_not_traceback_on_validation(
        self, runner, tmp_env_dir
    ):
        from odooflow.utils import server_profile

        def boom(*a, **kw):
            raise errors.ConfigError(
                "Server profile 'default' is invalid:\n    missing field"
            )

        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            with patch.object(server_profile, "save_profile", side_effect=boom):
                result = runner.invoke(
                    app,
                    [
                        "remote",
                        "--server-json",
                        '{"host":"h","port":22,"user":"u","directory":"/"}',
                    ],
                    input="",  # no stdin (typer.confirm is mocked to default-no path)
                )
        assert result.exit_code == 1
        combined = result.stdout + (result.stderr or "")
        assert "Traceback" not in combined
        assert "Server profile 'default' is invalid" in combined

    def test_remote_server_json_existing_profile_skip_message(
        self, runner, tmp_env_dir, fake_key
    ):
        """When a server profile already exists and the user declines overwrite,
        no validation is invoked and we print a clean skip."""
        env_path = tmp_env_dir / ".odooflow.env.json"
        env_path.write_text(json.dumps({
            "remotes": {
                "servers": {
                    "default": {
                        "host": "existing",
                        "user": "u",
                        "directory": "/",
                        "key_path": fake_key,
                    }
                },
                "default_server": "default",
            }
        }))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            with patch("odooflow.commands.remote.typer.confirm", return_value=False):
                result = runner.invoke(
                    app,
                    ["remote", "--server-json", '{"host":"new","port":22}'],
                )
        # Decline path: no exception, exits with the existing profile intact.
        assert result.exit_code == 0
        env = json.loads(env_path.read_text())
        assert env["remotes"]["servers"]["default"]["host"] == "existing"


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
