import io
import json
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from odooflow.cli import app
from odooflow.commands.connect import (
    InteractiveShell,
    _preflight,
    _resolve_profile,
    _open_client,
)
from odooflow.commands.connect import connect as server_connect


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


@pytest.fixture
def fake_key(tmp_path):
    p = tmp_path / "id_rsa"
    p.write_text("x")
    p.chmod(0o600)
    return str(p)


@pytest.fixture
def tmp_env_dir(tmp_path):
    """Project dir with an empty .odooflow.env.json."""
    env_path = tmp_path / ".odooflow.env.json"
    env_path.write_text(json.dumps({"remotes": {}}))
    return tmp_path


# --------------------------------------------------------------------------- #
# Unit tests: preflight
# --------------------------------------------------------------------------- #


class TestPreflight:
    def test_missing_required(self):
        with pytest.raises(typer.Exit):
            _preflight("qa", {"host": "h"})

    def test_host_with_scheme_rejected(self):
        with pytest.raises(typer.Exit):
            _preflight(
                "qa",
                {"host": "https://x", "user": "u", "directory": "/"},
            )

    def test_minimal_ok(self):
        pre = _preflight(
            "qa",
            {"host": "h", "user": "u", "directory": "/d"},
        )
        assert pre == {
            "host": "h",
            "port": 22,
            "user": "u",
            "directory": "/d",
            "key_path": None,
            "password": None,
        }

    def test_port_coerced(self):
        pre = _preflight(
            "qa",
            {"host": "h", "user": "u", "directory": "/d", "port": "2222"},
        )
        assert pre["port"] == 2222

    def test_auth_choice(self):
        pre = _preflight(
            "qa",
            {
                "host": "h",
                "user": "u",
                "directory": "/d",
                "key_path": "/key",
            },
        )
        assert pre["key_path"] == "/key"
        assert pre["password"] is None


# --------------------------------------------------------------------------- #
# Unit tests: _resolve_profile
# --------------------------------------------------------------------------- #


class TestResolveProfile:
    def test_no_profile_exits(self, tmp_env_dir):
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            with pytest.raises(typer.Exit):
                _resolve_profile(None)

    def test_resolves_default(self, tmp_env_dir, fake_key):
        env = {
            "remotes": {
                "servers": {
                    "staging": {
                        "host": "h",
                        "user": "u",
                        "directory": "/",
                        "key_path": fake_key,
                    }
                },
                "default_server": "staging",
            }
        }
        (tmp_env_dir / ".odooflow.env.json").write_text(json.dumps(env))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            name, profile = _resolve_profile(None)
        assert name == "staging"
        assert profile["host"] == "h"

    def test_resolves_named(self, tmp_env_dir, fake_key):
        env = {
            "remotes": {
                "servers": {
                    "a": {"host": "ha", "user": "u", "directory": "/", "key_path": fake_key},
                    "b": {"host": "hb", "user": "u", "directory": "/", "key_path": fake_key},
                },
                "default_server": "a",
            }
        }
        (tmp_env_dir / ".odooflow.env.json").write_text(json.dumps(env))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            name, profile = _resolve_profile("b")
        assert name == "b"
        assert profile["host"] == "hb"

    def test_unknown_profile_exits(self, tmp_env_dir, fake_key):
        env = {
            "remotes": {
                "servers": {"a": {"host": "h", "user": "u", "directory": "/", "key_path": fake_key}}
            }
        }
        (tmp_env_dir / ".odooflow.env.json").write_text(json.dumps(env))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            with pytest.raises(typer.Exit):
                _resolve_profile("ghost")


# --------------------------------------------------------------------------- #
# Unit tests: _open_client
# --------------------------------------------------------------------------- #


class TestOpenClient:
    def test_key_auth_calls_connect(self, monkeypatch, fake_key):
        captured = {}
        fake_pkey = MagicMock(name="RSAKey")

        class FakeClient:
            def set_missing_host_key_policy(self, policy):
                pass

            def connect(self, host, port, username, pkey, **kw):
                captured["host"] = host
                captured["user"] = username
                captured["pkey"] = pkey
                captured["kw"] = kw

            def close(self):
                pass

        monkeypatch.setattr(
            "odooflow.commands.connect.paramiko.SSHClient",
            lambda: FakeClient(),
        )
        monkeypatch.setattr(
            "odooflow.commands.connect.paramiko.RSAKey.from_private_key_file",
            lambda filename, password=None: fake_pkey,
        )

        pre = {"host": "h", "port": 22, "user": "u", "key_path": fake_key, "password": None}
        _open_client(pre)
        assert captured["host"] == "h"
        assert captured["user"] == "u"
        assert captured["pkey"] is fake_pkey
        assert captured["kw"]["allow_agent"] is False
        assert captured["kw"]["look_for_keys"] is False

    def test_password_auth_calls_connect(self, monkeypatch):
        captured = {}

        class FakeClient:
            def set_missing_host_key_policy(self, policy):
                pass

            def connect(self, host, port, username, password, **kw):
                captured["password"] = password

            def close(self):
                pass

        monkeypatch.setattr(
            "odooflow.commands.connect.paramiko.SSHClient",
            lambda: FakeClient(),
        )

        pre = {"host": "h", "port": 22, "user": "u", "key_path": None, "password": "pw"}
        _open_client(pre)
        assert captured["password"] == "pw"


# --------------------------------------------------------------------------- #
# InteractiveShell — minimal fake transport
# --------------------------------------------------------------------------- #


def make_fake_channel(stdout_text: str = "", stderr_text: str = "", exit_status: int = 0):
    """Build a paramiko.Channel-like object with exit status."""
    channel = MagicMock()
    channel.recv_exit_status.return_value = exit_status
    return channel


def make_fake_client(exec_outputs):
    """
    exec_outputs is a list of (stdout_text, stderr_text, exit_status) tuples,
    one per exec_command call. Returns a fake SSHClient whose exec_command
    pops from the list.
    """
    client = MagicMock()
    iter_outputs = list(exec_outputs)

    def exec_command(*args, **kw):
        if not iter_outputs:
            stdout, stderr, status = "", "", 0
        else:
            stdout, stderr, status = iter_outputs.pop(0)
        s = MagicMock()
        s.read.return_value = stdout.encode()
        s.channel.recv_exit_status.return_value = status
        e = MagicMock(); e.read.return_value = stderr.encode()
        return (MagicMock(), s, e)

    client.exec_command.side_effect = exec_command
    client.close = MagicMock()
    return client


# --------------------------------------------------------------------------- #
# Interactive shell behaviour (no real TTY — uses _read_line_simple)
# --------------------------------------------------------------------------- #


class TestInteractiveShell:
    def _build(self, outputs, stdin_text: str, *, cwd=None):
        pre = {
            "host": "h",
            "port": 22,
            "user": "u",
            "directory": cwd or "/srv",
            "key_path": None,
            "password": "pw",
        }
        client = make_fake_client(outputs)
        console = MagicMock()
        from odooflow.commands.connect import InteractiveShell

        shell = InteractiveShell(
            client_factory=lambda: client,
            pre=pre,
            console=console,
        )
        # Force plain input mode.
        shell._setup_tty = lambda: None  # type: ignore[assignment]
        shell._restore_tty = lambda: None  # type: ignore[assignment]
        shell._stdin = io.StringIO(stdin_text)
        return shell, console

    def test_runs_command_and_streams_output(self):
        shell, _ = self._build(
            outputs=[("hello world\n", "", 0)],
            stdin_text="echo hello\nexit\n",
        )
        rc = shell.run()
        assert rc == 0
        assert any(
            kind == "out" and "hello world" in text
            for kind, text in shell.scrollback
        )

    def test_records_exit_code_in_scrollback(self):
        shell, _ = self._build(
            outputs=[("", "boom\n", 2)],
            stdin_text="false\nexit\n",
        )
        rc = shell.run()
        assert rc == 0
        assert any(c == ("exit", "exit 2") for c in shell.scrollback)

    def test_help_builtin_does_not_exec(self):
        captured = {}
        shell, _ = self._build(outputs=[], stdin_text="help\nexit\n")
        # Replace factory so we capture the client reference.
        original_factory = shell._client_factory

        def factory():
            c = original_factory()
            captured["client"] = c
            return c

        shell._client_factory = factory
        rc = shell.run()
        assert rc == 0
        captured["client"].exec_command.assert_not_called()

    def test_built_in_cd_updates_local_directory(self):
        shell, _ = self._build(outputs=[], stdin_text="cd /tmp\nexit\n")
        rc = shell.run()
        assert rc == 0
        assert shell._pre["directory"] == "/tmp"

    def test_quit_exit_builtin(self):
        shell, _ = self._build(outputs=[], stdin_text="quit\n")
        rc = shell.run()
        assert rc == 0

    def test_reconnect_after_session_drop(self):
        """When exec_command raises an SSHException, the user accepts reconnect."""
        # We patch exec_command to raise on the first call, succeed on the second.
        client = MagicMock()
        call_count = {"n": 0}

        def exec_command(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise EOFError("Connection reset")
            chan = MagicMock()
            chan.recv_exit_status.return_value = 0
            s = MagicMock(); s.read.return_value = b"after reconnect"
            e = MagicMock(); e.read.return_value = b""
            return (MagicMock(), s, e)

        client.exec_command.side_effect = exec_command
        client.close = MagicMock()

        pre = {
            "host": "h", "port": 22, "user": "u", "directory": "/",
            "key_path": None, "password": "pw",
        }
        from odooflow.commands.connect import InteractiveShell
        console = MagicMock()
        shell = InteractiveShell(
            client_factory=lambda: client,
            pre=pre,
            console=console,
        )
        shell._setup_tty = lambda: None  # type: ignore[assignment]
        shell._restore_tty = lambda: None  # type: ignore[assignment]
        # Feed two commands. The second call triggers EOF; reconnect confirms.
        shell._stdin = io.StringIO("ls\npwd\nexit\n")

        # typer.confirm is mocked to return True without reading stdin.
        with patch("odooflow.commands.connect.typer.confirm", return_value=True):
            rc = shell.run()
        assert rc == 0
        # First call (ls) raises; second call (pwd) succeeds.
        assert call_count["n"] == 2
        # Scrollback replayed.
        kinds = [k for k, _ in shell.scrollback]
        assert "cmd" in kinds and "out" in kinds

    def test_reconnect_declined_exits_cleanly(self):
        client = MagicMock()

        def exec_command(*a, **kw):
            raise EOFError("gone")

        client.exec_command.side_effect = exec_command
        client.close = MagicMock()

        pre = {
            "host": "h", "port": 22, "user": "u", "directory": "/",
            "key_path": None, "password": "pw",
        }
        from odooflow.commands.connect import InteractiveShell
        console = MagicMock()
        shell = InteractiveShell(
            client_factory=lambda: client,
            pre=pre,
            console=console,
        )
        shell._setup_tty = lambda: None  # type: ignore[assignment]
        shell._restore_tty = lambda: None  # type: ignore[assignment]
        shell._stdin = io.StringIO("ls\nn\n")

        with patch("odooflow.commands.connect.typer.confirm", return_value=False):
            rc = shell.run()
        assert rc == 0  # declines -> 0
        # Only one client instance; no reconnect happened.
        assert client.exec_command.call_count == 1

    def test_initial_connect_failure_returns_one(self):
        pre = {
            "host": "h", "port": 22, "user": "u", "directory": "/",
            "key_path": None, "password": "pw",
        }
        from odooflow.commands.connect import InteractiveShell
        console = MagicMock()

        def boom():
            raise OSError("connection refused")

        shell = InteractiveShell(
            client_factory=boom,
            pre=pre,
            console=console,
        )
        shell._setup_tty = lambda: None  # type: ignore[assignment]
        shell._restore_tty = lambda: None  # type: ignore[assignment]
        rc = shell.run()
        assert rc == 1


# --------------------------------------------------------------------------- #
# CLI-level smoke: ensure the command is registered and --help works
# --------------------------------------------------------------------------- #


class TestConnectCLISurface:
    def test_help_lists_options(self, runner):
        result = runner.invoke(app, ["server", "connect", "--help"])
        assert result.exit_code == 0
        assert "--cd" in result.stdout
        assert "--raw-input" in result.stdout

    def test_unknown_profile_exits_nonzero(self, runner, tmp_env_dir, fake_key):
        env = {
            "remotes": {
                "servers": {
                    "a": {"host": "h", "user": "u", "directory": "/", "key_path": fake_key}
                }
            }
        }
        (tmp_env_dir / ".odooflow.env.json").write_text(json.dumps(env))
        with patch("pathlib.Path.cwd", return_value=tmp_env_dir):
            result = runner.invoke(app, ["server", "connect", "ghost"])
        assert result.exit_code != 0

    def test_no_env_file_exits(self, runner, tmp_path):
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["server", "connect"])
        assert result.exit_code != 0


# --------------------------------------------------------------------------- #
# Regression tests for the "every character adds a new line" bug.
# Root cause was a cooked-mode readline() fallback that fired whenever
# termios.tcsetattr or tty.setraw silently failed. The fix is to read
# bytes via os.read(fd, 1), which bypasses canonicalization regardless
# of whether the terminal is in raw or cooked mode.
# --------------------------------------------------------------------------- #


class TestLineEditorReadsChars:
    """
    Drive `_read_line` with a StringIO under the new os.read path
    (which falls back to .read(1) when stdin_fd is None). Each test
    confirms that a multi-character line assembled correctly, with
    proper handling of backspace, arrow keys, and Ctrl-C / Ctrl-D.
    """

    def _build_shell(self, stdin_text: str, history: list[str] | None = None):
        pre = {
            "host": "h",
            "port": 22,
            "user": "u",
            "directory": "/srv",
            "key_path": None,
            "password": "pw",
        }
        client = MagicMock()
        client.exec_command.side_effect = lambda *a, **kw: (
            MagicMock(),
            MagicMock(read=lambda: b"", channel=MagicMock(recv_exit_status=lambda: 0)),
            MagicMock(read=lambda: b""),
        )
        client.close = MagicMock()
        from odooflow.commands.connect import InteractiveShell

        shell = InteractiveShell(
            client_factory=lambda: client,
            pre=pre,
            console=MagicMock(),
        )
        # Force the non-TTY path (the regression was triggered when
        # the shell mistakenly used the cooked-mode fallback on a
        # broken/raw TTY).
        shell._is_tty = False
        shell._stdin_fd = None
        shell._setup_tty()
        shell._stdin = io.StringIO(stdin_text)
        if history:
            shell.history.extend(history)
        # Capture the client reference so we can assert on it after
        # run() disconnects in its `finally` clause.
        shell._test_client = client
        return shell

    def test_reads_full_line_without_waiting_for_newline(self):
        """The user's report: every character adds a new line. The
        fix is that we read one char at a time, so even keystrokes
        typed without Enter are buffered. A complete line is only
        finalised on Enter or Ctrl-D."""
        shell = self._build_shell("ls\nexit\n")
        rc = shell.run()
        assert rc == 0
        # 'ls' was executed (not 'l' + 's' on separate lines).
        assert shell._test_client.exec_command.call_count == 1

    def test_backspace_edits_inline(self):
        """\"hel\\x7flo\" should produce 'helo' (DEL/BS removes one char)."""
        shell = self._build_shell("hel\x7flo\nexit\n")
        rc = shell.run()
        assert rc == 0
        # The history record reflects the edited buffer, not the raw input.
        assert list(shell.history) == ["helo"]

    def test_arrow_keys_cycle_history(self):
        # Up arrow on a fresh prompt lands on the most recent entry;
        # two ups walk back one further; Enter commits that line into
        # the history as the newest entry.
        shell = self._build_shell(
            "\x1b[A\x1b[A\nexit\n",
            history=["first", "second", "third"],
        )
        rc = shell.run()
        assert rc == 0
        # History starts as ["first","second","third"], and the typed
        # line "second" (recalled via two ups) is appended at the end.
        assert list(shell.history) == ["first", "second", "third", "second"]

    def test_ctrl_c_breaks_line_returns_none(self):
        shell = self._build_shell("ls\x03exit\n")
        # The Ctrl-C cancels the current line. _read_line returns None,
        # which the run() loop interprets as session-end.
        rc = shell.run()
        assert rc == 0
        # The 'ls' command was NOT executed.
        assert shell._test_client.exec_command.call_count == 0

    def test_ctrl_d_on_empty_line_exits_cleanly(self):
        shell = self._build_shell("\x04")
        rc = shell.run()
        assert rc == 0

    def test_unicode_input_passes_through(self):
        """Multibyte chars (UTF-8) are read as one chunk by os.read,
        but our StringIO test path uses .read(1) on a StringIO which
        already splits on code points; we just verify nothing crashes."""
        shell = self._build_shell("echo café\nexit\n")
        rc = shell.run()
        assert rc == 0
        assert list(shell.history)[-1] == "echo café"