"""T3 Code, the agent app on this machine: its threads launched and read back.

T3 serves its orchestration on 127.0.0.1, its origin written to
~/.t3/userdata/server-runtime.json while it runs. Each use is a session of
its own: a bearer token issued by T3's own command line (its installed
server, run as Node: `auth session issue`), traded for a WebSocket ticket,
and revoked once done, so no token is ever kept. Over the socket go Effect
RPC messages: a Request, answered by Chunks (each acknowledged) for a
subscription, and an Exit.

What is asked of T3:

- orchestration.subscribeShell: its first chunk is a snapshot of the
  projects (each with its workspaceRoot) and the threads (each with its
  session, latest turn, branch and worktree);
- orchestration.dispatchCommand: thread.create, then thread.turn.start to
  send it its first message.

Only I/O lives here: app/services/agent_runs.py launches runs through it.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as ws_connect

RUNTIME = Path.home() / ".t3" / "userdata" / "server-runtime.json"
INSTALL = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "t3code"
EXE = "T3 Code (Alpha).exe"
SERVER_BIN = Path("resources", "server.asar", "apps", "server", "dist", "bin.mjs")
TIMEOUT = 60
CREATE_NO_WINDOW = 0x08000000


class T3Error(Exception):
    """T3 could not be reached, or refused what was asked."""


@dataclass(frozen=True)
class T3:
    origin: str
    exe: Path

    @classmethod
    def local(cls) -> T3:
        """The T3 running on this machine."""
        try:
            origin = json.loads(RUNTIME.read_text(encoding="utf-8"))["origin"]
        except (OSError, ValueError, KeyError) as exc:
            raise T3Error(f"T3 Code is not running (no {RUNTIME})") from exc
        exe = INSTALL / EXE
        if not exe.exists():
            raise T3Error(f"T3 Code is not installed at {INSTALL}")
        return cls(origin, exe)

    def _cli(self, *args: str) -> str:
        """T3's own command line: its server, run as Node by its executable
        (the path in Windows' form, which it needs)."""
        out = subprocess.run(
            [str(self.exe), str(self.exe.parent / SERVER_BIN), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            env={**os.environ, "ELECTRON_RUN_AS_NODE": "1"},
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if out.returncode:
            raise T3Error(f"t3 {args[0]} {args[1]}: {(out.stderr or out.stdout).strip()[-500:]}")
        return out.stdout

    @contextmanager
    def connect(self, label: str) -> Iterator[Connection]:
        """A connection to T3 on a token of its own, revoked when done."""
        issued = json.loads(
            self._cli("auth", "session", "issue", "--ttl", "15m", "--label", label, "--json")
        )
        try:
            try:
                response = httpx.post(
                    f"{self.origin}/api/auth/websocket-ticket",
                    headers={"Authorization": f"Bearer {issued['token']}"},
                    timeout=TIMEOUT,
                )
                response.raise_for_status()
                body = response.json()
                ticket = (
                    (body.get("ticket") or body.get("wsTicket")) if isinstance(body, dict) else body
                )
                url = self.origin.replace("http", "ws", 1)
                ws = ws_connect(
                    f"{url}/ws?orchestrationProtocol=2&wsTicket={ticket}",
                    max_size=None,
                    open_timeout=TIMEOUT,
                )
            except (OSError, httpx.HTTPError) as exc:
                raise T3Error(f"T3 Code could not be reached: {exc}") from exc
            with ws:
                yield Connection(ws)
        finally:
            self._cli("auth", "session", "revoke", issued["sessionId"])


class Connection:
    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws
        self._ids = itertools.count(1)

    def _send(self, message: dict) -> None:
        self.ws.send(json.dumps(message))

    def request(self, tag: str, payload: dict, *, first_chunk: bool = False) -> Any:
        """A request's answer: its Exit's value, or for a subscription its
        first chunk (the subscription interrupted then)."""
        rid = str(next(self._ids))
        self._send({"_tag": "Request", "id": rid, "tag": tag, "payload": payload, "headers": []})
        while True:
            message = json.loads(self.ws.recv(timeout=TIMEOUT))
            if message.get("_tag") == "Ping":
                self._send({"_tag": "Pong"})
                continue
            if message.get("requestId") != rid:
                continue
            if message["_tag"] == "Chunk":
                self._send({"_tag": "Ack", "requestId": rid})
                if first_chunk and message["values"]:
                    self._send({"_tag": "Interrupt", "requestId": rid})
                    return message["values"][0]
                continue
            exit_ = message.get("exit", {})
            if message["_tag"] != "Exit" or exit_.get("_tag") != "Success":
                raise T3Error(f"{tag} failed: {json.dumps(message)[:800]}")
            return exit_.get("value")

    def snapshot(self) -> dict:
        """The projects and threads as T3 has them now."""
        return self.request("orchestration.subscribeShell", {}, first_chunk=True)["snapshot"]

    def dispatch(self, command: dict) -> Any:
        return self.request("orchestration.dispatchCommand", command)
