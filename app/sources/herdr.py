"""herdr, the terminal multiplexer for coding agents Oscar works in (inside
WezTerm): its workspaces, panes and agents read, and agents started in it.

herdr runs as a server of its own, which keeps the terminals going while
clients (WezTerm showing its screen, or this app) come and go. Its API is
newline-delimited JSON on a local socket: on Windows a named pipe named after
the socket's path (%APPDATA%\\herdr\\herdr.sock, or a named session's
sessions\\<name>\\herdr.sock). A connection takes one request, {"id",
"method", "params"}, answered by {"id", "result"} or {"id", "error":
{"code", "message"}}, and herdr closes it.

What is asked of herdr (its protocol 22, herdr 0.9):

- session.snapshot: every workspace, tab, pane (its terminal, its folder) and
  agent (its kind, its status: idle, working, blocked, done or unknown, and
  the agent's own session id), and the pane focused;
- workspace.create, then agent.start in its first pane: an agent launched in a
  workspace of its own, with its opening prompt as an argument;
- agent.focus: a pane brought to the front of herdr's screen.

Only I/O lives here: app/services/agent_runs.py launches runs through it,
app/services/work_log.py records the work seen in it.
"""

from __future__ import annotations

import json
import os
import shutil
import socket as socket_mod
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TIMEOUT = 10.0
START_TIMEOUT = 15.0
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

# What the app's own process carries that a terminal herdr opens must not:
# the frozen app's (PyInstaller's), and an agent's that ran the app from
# source (Claude Code's own markers, which turn a child's transcripts off),
# and a herdr pane's (the app run from one).
_NOT_PASSED_ON = ("_PYI", "_MEI", "CLAUDECODE", "CLAUDE_CODE_", "HERDR_")


class HerdrError(Exception):
    """herdr could not be reached, or refused what was asked."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class NotRunning(HerdrError):
    """No herdr server is running for the session."""


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def socket_path(session: str = "") -> Path:
    """Where herdr's server for `session` (its default, when "") listens."""
    base = _appdata() / "herdr"
    return base / "sessions" / session / "herdr.sock" if session else base / "herdr.sock"


class _Pipe:
    """A Windows named pipe, read and written with a timeout (overlapped)."""

    def __init__(self, name: str, timeout: float) -> None:
        import _winapi

        self._w = _winapi
        self.timeout = timeout
        flags = _winapi.FILE_FLAG_OVERLAPPED
        access = _winapi.GENERIC_READ | _winapi.GENERIC_WRITE
        for _ in range(3):
            try:
                self.handle = _winapi.CreateFile(
                    name, access, 0, _winapi.NULL, _winapi.OPEN_EXISTING, flags, _winapi.NULL
                )
                return
            except FileNotFoundError as exc:
                raise NotRunning("herdr is not running", "server_not_running") from exc
            except OSError as exc:
                if getattr(exc, "winerror", None) != _winapi.ERROR_PIPE_BUSY:
                    raise HerdrError(f"herdr's socket would not open: {exc}") from exc
                _winapi.WaitNamedPipe(name, int(timeout * 1000))
        raise HerdrError("herdr's socket stayed busy")

    def _wait(self, ov) -> None:  # noqa: ANN001
        w = self._w
        done = w.WaitForMultipleObjects([ov.event], False, int(self.timeout * 1000))
        if done == w.WAIT_TIMEOUT:
            ov.cancel()
            raise HerdrError("herdr did not answer in time")

    def send(self, data: bytes) -> None:
        w = self._w
        try:
            ov, err = w.WriteFile(self.handle, data, overlapped=True)
            if err == w.ERROR_IO_PENDING:
                self._wait(ov)
            ov.GetOverlappedResult(True)
        except OSError as exc:
            raise HerdrError(f"herdr's socket closed: {exc}") from exc

    def receive(self) -> bytes:
        """What came, b"" once the pipe is closed (a part of a longer
        message, ERROR_MORE_DATA, is returned as it is: the rest is next)."""
        w = self._w
        try:
            ov, err = w.ReadFile(self.handle, 65536, overlapped=True)
            if err == w.ERROR_IO_PENDING:
                self._wait(ov)
            ov.GetOverlappedResult(True)
            return bytes(ov.getbuffer())
        except OSError as exc:
            raise HerdrError(f"herdr's socket closed: {exc}") from exc

    def close(self) -> None:
        self._w.CloseHandle(self.handle)


class _Unix:
    """A Unix socket, elsewhere than Windows."""

    def __init__(self, path: str, timeout: float) -> None:
        self.sock = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)  # type: ignore[attr-defined]
        self.sock.settimeout(timeout)
        try:
            self.sock.connect(path)
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise NotRunning("herdr is not running", "server_not_running") from exc
        except OSError as exc:
            raise HerdrError(f"herdr's socket would not open: {exc}") from exc

    def send(self, data: bytes) -> None:
        try:
            self.sock.sendall(data)
        except OSError as exc:
            raise HerdrError(f"herdr's socket closed: {exc}") from exc

    def receive(self) -> bytes:
        try:
            return self.sock.recv(65536)
        except TimeoutError as exc:
            raise HerdrError("herdr did not answer in time") from exc
        except OSError as exc:
            raise HerdrError(f"herdr's socket closed: {exc}") from exc

    def close(self) -> None:
        self.sock.close()


def _request(path: Path, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    """One request on a connection of its own (herdr answers one a
    connection, then closes it): its result, or HerdrError with herdr's code
    when refused."""
    name = "\\\\.\\pipe\\" + str(path)
    io: _Pipe | _Unix = _Pipe(name, timeout) if os.name == "nt" else _Unix(str(path), timeout)
    try:
        request = {"id": "pc", "method": method, "params": params}
        io.send(json.dumps(request).encode() + b"\n")
        buffer = b""
        while b"\n" not in buffer:
            chunk = io.receive()
            if not chunk:
                raise HerdrError("herdr closed the connection")
            buffer += chunk
    finally:
        io.close()
    answer = json.loads(buffer.partition(b"\n")[0])
    if "error" in answer:
        error = answer["error"] or {}
        raise HerdrError(error.get("message") or "herdr refused it", error.get("code", ""))
    return answer.get("result") or {}


@dataclass(frozen=True)
class Herdr:
    """The herdr server of one session on this machine."""

    socket: Path
    # The session's name, "" for herdr's default one.
    session: str = ""
    # herdr's command line, to start the server when it is not running.
    cli: str = ""

    @classmethod
    def local(cls, session: str = "", socket: str = "", cli: str = "") -> Herdr:
        return cls(Path(socket) if socket else socket_path(session), session, cli)

    def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = TIMEOUT
    ) -> dict[str, Any]:
        """A request's result; HerdrError with herdr's code when refused,
        NotRunning when no server is there."""
        return _request(self.socket, method, params or {}, timeout)

    def snapshot(self, timeout: float = TIMEOUT) -> dict[str, Any]:
        """The session as it stands: workspaces, tabs, panes and agents."""
        return self.call("session.snapshot", timeout=timeout).get("snapshot") or {}

    def focus(self, terminal_id: str) -> bool:
        """The pane holding a terminal brought to the front of herdr's
        screen; whether it is still there to be."""
        panes = self.snapshot().get("panes", [])
        pane = next((p for p in panes if p.get("terminal_id") == terminal_id), None)
        if pane is None:
            return False
        self.call("pane.focus", {"pane_id": pane["pane_id"]})
        return True

    def running(self) -> bool:
        try:
            self.call("ping", timeout=3)
        except HerdrError:
            return False
        return True

    def find_cli(self) -> str | None:
        if self.cli:
            return self.cli if Path(self.cli).exists() or shutil.which(self.cli) else None
        found = shutil.which("herdr")
        if found:
            return found
        installed = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Herdr" / "bin"
        exe = installed / "herdr.exe"
        return str(exe) if exe.exists() else None

    def start(self) -> None:
        """The server started, on its own (it outlives the app, as it would
        started from WezTerm), once it is not running; back once it answers."""
        if self.running():
            return
        cli = self.find_cli()
        if cli is None:
            raise HerdrError("herdr is not installed: get it from herdr.dev")
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(_NOT_PASSED_ON)}
        args = [cli, *(["--session", self.session] if self.session else []), "server"]
        detached = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        flags = detached if os.name == "nt" else 0
        subprocess.Popen(  # noqa: S603
            args,
            env=env,
            cwd=str(Path.home()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if self.running():
                return
            time.sleep(0.25)
        raise HerdrError("herdr's server did not start")
