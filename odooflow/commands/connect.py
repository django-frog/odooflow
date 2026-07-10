"""
`odooflow server connect` — open an interactive SSH session against a
named server profile.

UX goals:
  * Friendly, color-coded preflight (resolved profile, auth method,
    directory).
  * Live stdout streaming, stderr highlighted in red, exit codes
    highlighted when non-zero.
  * In-memory command history (arrow keys on a real TTY).
  * Detect session-closed / EOF / reset and offer to reconnect,
    restoring scrollback.
  * Plain Ctrl-C / Ctrl-D exit cleanly.
"""

from __future__ import annotations

import collections
import os
import socket
import sys
import termios
from pathlib import Path
from typing import Callable, Optional

import paramiko
import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from odooflow import errors
from odooflow.utils import server_profile
from odooflow.utils.env import read_env_file
from odooflow.config_manager import load_config


# Public entry-point: cli.py imports `connect` and registers it on the
# existing `server` sub-app via `app.command("connect")`.


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #


def _resolve_profile(name: Optional[str]) -> tuple[str, dict]:
    """Return (profile_name, profile_dict) or raise ConfigError."""
    cfg = load_config(strict=False)
    env_path = Path.cwd() / cfg.get("env_file", ".odooflow.env.json")
    if not env_path.exists():
        errors._emit(
            "Environment file not found.",
            [
                f"  Expected:  {env_path}",
                "",
                "  Fix it:",
                "    * Run `odooflow init` first.",
                "    * Or run `odooflow sync-env` after a valid manifest.",
            ],
        )
        raise typer.Exit(code=1)
    env = read_env_file(env_path)
    profile_name, profile = server_profile.select_profile(
        env, requested_name=name
    )
    if profile is None:
        errors._emit(
            f"No server profile{' '+repr(name) if name else ''} found.",
            [
                "  Fix it:",
                "    * Run `odooflow server list` to see what's available.",
                "    * Run `odooflow server add <name>` to create one.",
            ],
        )
        raise typer.Exit(code=1)
    return profile_name, profile


def _preflight(profile_name: str, profile: dict) -> dict:
    """
    Normalise the profile dict and return `{host, port, user, key_path|password, directory}`.
    Raises ConfigError / typer.Exit on missing required fields.
    """
    required = ("host", "user", "directory")
    missing = [k for k in required if not profile.get(k)]
    if missing:
        errors._emit(
            f"Server profile '{profile_name}' is incomplete.",
            [
                f"  Missing keys: {', '.join(missing)}",
                "",
                "  Fix it:",
                f"    * `odooflow server show {profile_name}`",
                f"    * `odooflow server add {profile_name}` (to overwrite)",
            ],
        )
        raise typer.Exit(code=1)

    host = profile["host"]
    if "://" in host:
        errors._emit(
            f"Server profile '{profile_name}' has a malformed host.",
            [
                f"  Host: {host}",
                "  Must be a bare hostname or IP, no scheme.",
            ],
        )
        raise typer.Exit(code=1)

    try:
        port = int(profile.get("port", 22))
    except (TypeError, ValueError):
        port = 22

    return {
        "host": host,
        "port": port,
        "user": profile["user"],
        "directory": profile["directory"],
        "key_path": profile.get("key_path"),
        "password": profile.get("password"),
    }


def _open_client(pre: dict, *, timeout: int = 10) -> paramiko.SSHClient:
    """Open and authenticate a paramiko.SSHClient. Caller closes."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        if pre["key_path"]:
            pkey = paramiko.RSAKey.from_private_key_file(
                os.path.expanduser(pre["key_path"])
            )
            client.connect(
                pre["host"],
                port=pre["port"],
                username=pre["user"],
                pkey=pkey,
                timeout=timeout,
                auth_timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        else:
            client.connect(
                pre["host"],
                port=pre["port"],
                username=pre["user"],
                password=pre["password"],
                timeout=timeout,
                auth_timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
            )
    except (paramiko.SSHException, socket.error, OSError):
        client.close()
        raise
    return client


# --------------------------------------------------------------------------- #
# Interactive shell
# --------------------------------------------------------------------------- #


class InteractiveShell:
    """
    Read commands from stdin, run them over an open SSHClient.

    The session maintains:
      * scrollback: list of (kind, text) entries, replayed on reconnect.
      * history:   deque of past commands for arrow-key recall.
    """

    def __init__(
        self,
        client_factory: Callable[[], paramiko.SSHClient],
        pre: dict,
        console: Console,
        *,
        prompt_color: str = "cyan",
    ) -> None:
        self._client_factory = client_factory
        self._pre = pre
        self._console = console
        self._prompt_color = prompt_color

        self.scrollback: list[tuple[str, str]] = []  # ('cmd', text) or ('out', text)
        self.history: collections.deque[str] = collections.deque(maxlen=200)

        self._client: Optional[paramiko.SSHClient] = None
        self._is_tty: bool = bool(getattr(sys.stdin, "isatty", lambda: False)())
        self._old_term_attrs = None
        self._stdin_fd: Optional[int] = None
        self._stdin = sys.stdin

    # ---------- lifecycle ---------- #

    def _connect(self) -> bool:
        try:
            self._client = self._client_factory()
        except Exception as exc:  # noqa: BLE001
            self._console.print(
                f"[red]✗ Connection failed:[/red] {exc}"
            )
            return False
        banner = (
            f"[green]✓ Connected to[/green] "
            f"[bold]{self._pre['user']}@{self._pre['host']}:{self._pre['port']}[/bold]"
        )
        self._console.print(banner)
        return True

    def _disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    # ---------- terminal setup ---------- #

    def _setup_tty(self) -> None:
        """
        Disable echo on the controlling terminal so our hand-drawn prompt
        does not double up with the kernel's echo. We deliberately do
        NOT use `tty.setraw`: we read bytes via `os.read(fd, 1)`, which
        bypasses canonicalisation regardless of whether the terminal is
        in cooked or raw mode. That way a single code path works on
        every environment, including ones where `tty.setraw` would
        silently fail (no controlling terminal, odd TERM, etc.).
        """
        if not self._is_tty:
            self._stdin_fd = None
            return
        try:
            fd = self._stdin.fileno()
            self._stdin_fd = fd
            attrs = termios.tcgetattr(fd)
            self._old_term_attrs = attrs
            # Disable echo and canonical-mode line editing; leave signals
            # (ISIG) on so Ctrl-C still works as expected.
            new_attrs = list(attrs)
            new_attrs[3] = (new_attrs[3] & ~termios.ECHO) & ~termios.ICANON
            # VMIN=0 + VTIME=1: read with a small timeout so a stalled
            # remote does not freeze the shell.
            new_attrs[6][termios.VMIN] = 0
            new_attrs[6][termios.VTIME] = 1
            termios.tcsetattr(fd, termios.TCSANOW, new_attrs)
        except (termios.error, OSError, ValueError, AttributeError):
            self._stdin_fd = None
            self._old_term_attrs = None

    def _restore_tty(self) -> None:
        if self._stdin_fd is None or self._old_term_attrs is None:
            return
        try:
            termios.tcsetattr(
                self._stdin_fd, termios.TCSAFLUSH, self._old_term_attrs
            )
        except (termios.error, OSError, ValueError, AttributeError):
            pass
        self._old_term_attrs = None
        self._stdin_fd = None

    # ---------- prompt drawing ---------- #

    def _draw_prompt(self) -> None:
        prompt = Text()
        prompt.append(self._pre["user"], style="bold")
        prompt.append("@", style="dim")
        prompt.append(self._pre["host"], style="bold")
        prompt.append(":", style="dim")
        prompt.append(str(self._pre["port"]), style="dim")
        prompt.append(" ", style="dim")
        prompt.append("$ ", style=self._prompt_color)
        self._console.print(prompt, end="")

    # ---------- input ---------- #

    # ---------- line editor ---------- #

    def _render(self, buf: list[str], cursor: int) -> None:
        """Re-render the current line under the prompt."""
        self._draw_prompt()
        if buf:
            self._console.print("".join(buf), end="", highlight=False)
        back = len(buf) - cursor
        if back > 0:
            self._console.print("\b" * back, end="", highlight=False)

    def _read_byte(self) -> Optional[str]:
        """
        Read one byte from stdin. Returns None on EOF.

        On a real terminal: bypasses canonical mode by reading directly
        from the file descriptor with `os.read(fd, 1)`. The terminal
        is still in cooked mode for everything else (other processes,
        shell signals), but our line editor receives characters as they
        are typed — no buffering, no per-line waits.
        """
        if self._stdin_fd is not None:
            try:
                chunk = os.read(self._stdin_fd, 1)
            except (OSError, ValueError):
                chunk = self._stdin.read(1)  # type: ignore[assignment]
            return chunk or None
        # Non-TTY fallback: read one char via the high-level API.
        try:
            ch = self._stdin.read(1)
        except (EOFError, KeyboardInterrupt):
            return None
        return ch or None

    def _read_line(self) -> Optional[str]:
        """
        Read a line of input, with arrow-key history, backspace, and
        Ctrl-A/E/C/D. Returns None on EOF / Ctrl-C / Ctrl-D on empty
        buffer.
        """
        buf: list[str] = []
        cursor = 0
        history_index: Optional[int] = None  # None means 'on the live line'

        self._render(buf, cursor)
        while True:
            ch = self._read_byte()
            if ch is None:
                return None
            code = ord(ch)

            # Enter
            if ch in ("\r", "\n"):
                self._console.print()
                return "".join(buf)

            # Backspace / DEL
            if code in (0x7F, 0x08):
                if cursor > 0:
                    del buf[cursor - 1]
                    cursor -= 1
                    self._render(buf, cursor)
                continue

            # Escape sequences (arrow keys, etc.)
            if code == 0x1B:
                seq1 = self._read_byte() or ""
                seq2 = self._read_byte() or ""
                if seq1 == "[" and seq2 == "A":  # Up
                    if not self.history:
                        continue
                    if history_index is None:
                        history_index = len(self.history) - 1
                    elif history_index > 0:
                        history_index -= 1
                    buf = list(self.history[history_index])
                    cursor = len(buf)
                    self._render(buf, cursor)
                elif seq1 == "[" and seq2 == "B":  # Down
                    if history_index is None:
                        continue
                    if history_index < len(self.history) - 1:
                        history_index += 1
                        buf = list(self.history[history_index])
                    else:
                        history_index = None
                        buf = []
                    cursor = len(buf)
                    self._render(buf, cursor)
                # Ignore unknown escape sequences (F1-F12, etc.)
                continue

            # Ctrl-C
            if code == 0x03:
                self._console.print("^C")
                return None

            # Ctrl-D on empty line => exit
            if code == 0x04 and not buf:
                return None

            # Ctrl-A / Ctrl-E
            if code == 0x01:
                cursor = 0
                self._render(buf, cursor)
                continue
            if code == 0x05:
                cursor = len(buf)
                self._render(buf, cursor)
                continue

            # Anything else: insert
            buf.insert(cursor, ch)
            cursor += 1
            self._render(buf, cursor)

    # ---------- execution ---------- #

    def _exec(self, command: str) -> Optional[str]:
        """Run a command. Returns 'open' / 'closed' / None (fatal)."""
        assert self._client is not None
        try:
            stdin, stdout, stderr = self._client.exec_command(command, timeout=30)
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            code = stdout.channel.recv_exit_status()
        except (paramiko.SSHException, socket.error, EOFError, OSError) as exc:
            self._console.print(f"[red]✗ Session error:[/red] {exc}")
            return "closed"

        if out:
            self._console.print(out, highlight=False)
            self.scrollback.append(("out", out))
        if err:
            self._console.print(err, style="red", highlight=False)
            self.scrollback.append(("err", err))
        if code != 0:
            self._console.print(f"[yellow]↳ exit {code}[/yellow]")
            self.scrollback.append(("exit", f"exit {code}"))
        return None

    # ---------- main loop ---------- #

    def run(self) -> int:
        if not self._connect():
            return 1

        self._setup_tty()
        try:
            cd_path = self._pre["directory"]
            self._console.print(
                f"[dim]cwd:[/dim] [bold]{cd_path}[/bold]"
            )

            while True:
                # Read a command.
                self._render([], 0)
                line = self._read_line()

                if line is None:
                    self._console.print(
                        "[dim]session ended (Ctrl-D / EOF).[/dim]"
                    )
                    return 0

                stripped = line.strip()
                if not stripped:
                    continue
                if stripped in ("exit", "logout", "quit"):
                    self._console.print("[dim]bye.[/dim]")
                    return 0
                if stripped == "help":
                    self._console.print(
                        Panel(
                            "Built-ins: [bold]help[/bold], [bold]cd <path>[/bold], "
                            "[bold]exit[/bold]/[bold]logout[/bold]/[bold]quit[/bold].",
                            title="odooflow server connect",
                            border_style="cyan",
                        )
                    )
                    continue
                if stripped.startswith("cd "):
                    new_path = stripped[3:].strip()
                    if new_path:
                        cd_path = new_path
                        self._pre["directory"] = new_path
                    self._console.print(f"[dim]cwd:[/dim] {cd_path}")
                    continue

                self.history.append(stripped)
                self.scrollback.append(("cmd", stripped))
                result = self._exec(stripped)
                if result == "closed":
                    if typer.confirm(
                        "The SSH session dropped. Reconnect?", default=True
                    ):
                        self._disconnect()
                        # Replay scrollback after reconnect for context.
                        if not self._connect():
                            return 1
                        self._console.print("[dim]— replayed scrollback —[/dim]")
                        for kind, text in self.scrollback:
                            if kind == "cmd":
                                self._console.print(
                                    f"[bold cyan]> {text}[/bold cyan]"
                                )
                            elif kind == "out":
                                self._console.print(text, highlight=False)
                            elif kind == "err":
                                self._console.print(
                                    text, style="red", highlight=False
                                )
                            elif kind == "exit":
                                self._console.print(
                                    f"[yellow]↳ {text}[/yellow]"
                                )
                        continue
                    return 0
        finally:
            self._restore_tty()
            self._disconnect()


# --------------------------------------------------------------------------- #
# Typer command
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Typer command
# --------------------------------------------------------------------------- #


def connect(
    name: Optional[str] = typer.Argument(
        None, help="Profile name (defaults to current default)."
    ),
    cd: Optional[str] = typer.Option(
        None, "--cd", help="Override the directory configured in the profile."
    ),
    raw_input: bool = typer.Option(
        False,
        "--raw-input",
        help="Skip raw TTY mode; use plain line input (use for tests/CI).",
    ),
):
    """Open an interactive SSH session against a server profile."""
    profile_name, profile = _resolve_profile(name)
    pre = _preflight(profile_name, profile)
    if cd:
        pre["directory"] = cd

    console = Console()

    def factory() -> paramiko.SSHClient:
        return _open_client(pre)

    shell = InteractiveShell(
        client_factory=factory,
        pre=pre,
        console=console,
    )
    if raw_input:
        # Force non-interactive mode even when stdin is a TTY (useful
        # for `odooflow server connect < input.txt` style invocations).
        shell._is_tty = False
        shell._stdin_fd = None
    raise typer.Exit(code=shell.run())


__all__ = ["connect"]