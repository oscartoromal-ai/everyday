"""A stand-in for herdr's server, answering its API on a real named pipe at a
socket path of the test's own, so the app's client (sources/herdr.py) runs
its requests against it as it would against herdr: newline-delimited JSON,
a request answered by its result or an error."""

from __future__ import annotations

import itertools
import json
import threading
from multiprocessing.connection import Listener
from pathlib import Path
from typing import Any

from app.sources.herdr import Herdr


class FakeHerdr:
    """herdr's server with its workspaces, panes and agents as a test sets
    them; what it was asked is kept in `asked`."""

    def __init__(self, socket: Path) -> None:
        self.herdr = Herdr(socket)
        self.workspaces: list[dict[str, Any]] = []
        self.panes: list[dict[str, Any]] = []
        self.agents: list[dict[str, Any]] = []
        self.focused: str | None = None
        self.asked: list[tuple[str, dict[str, Any]]] = []
        # A method answered with this error code instead.
        self.refuse: dict[str, str] = {}
        self._ids = itertools.count(1)
        self._listener = Listener("\\\\.\\pipe\\" + str(socket), family="AF_PIPE")
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    # ---- as a test sets it ----

    def workspace(self, label: str, cwd: str, agent: str = "", status: str = "") -> dict:
        """A workspace with one pane in `cwd`, an agent in it when given."""
        n = next(self._ids)
        workspace = {"workspace_id": f"w{n}", "label": label}
        pane = {
            "pane_id": f"w{n}:p1",
            "terminal_id": f"term_{n}",
            "workspace_id": f"w{n}",
            "cwd": cwd,
        }
        self.workspaces.append(workspace)
        self.panes.append(pane)
        if agent:
            self.agents.append(
                {
                    "terminal_id": pane["terminal_id"],
                    "pane_id": pane["pane_id"],
                    "name": f"agent-{n}",
                    "agent": agent,
                    "agent_status": status or "working",
                    "agent_session": {"kind": "id", "value": f"session-{n}"},
                    "terminal_title_stripped": f"Working on {n}",
                    "cwd": cwd,
                }
            )
        return pane

    def status(self, terminal_id: str, status: str) -> None:
        for agent in self.agents:
            if agent["terminal_id"] == terminal_id:
                agent["agent_status"] = status

    def close(self, terminal_id: str) -> None:
        self.panes = [p for p in self.panes if p["terminal_id"] != terminal_id]
        self.agents = [a for a in self.agents if a["terminal_id"] != terminal_id]

    def stop(self) -> None:
        self._listener.close()

    # ---- as herdr answers ----

    def _answer(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "ping":
            return {"type": "pong"}
        if method == "session.snapshot":
            return {
                "type": "session_snapshot",
                "snapshot": {
                    "focused_pane_id": self.focused,
                    "workspaces": self.workspaces,
                    "panes": self.panes,
                    "agents": self.agents,
                },
            }
        if method == "agent.list":
            return {"type": "agent_list", "agents": self.agents}
        if method == "workspace.create":
            pane = self.workspace(params.get("label") or "", params.get("cwd") or "")
            return {"type": "workspace_created", "root_pane": pane}
        if method == "agent.start":
            pane = next(p for p in self.panes if p["pane_id"] == params["pane_id"])
            self.agents.append(
                {
                    "terminal_id": pane["terminal_id"],
                    "pane_id": pane["pane_id"],
                    "name": params["name"],
                    "agent": params["kind"],
                    "agent_status": "unknown",
                    "cwd": pane["cwd"],
                }
            )
            return {"type": "agent_started"}
        if method == "pane.focus":
            self.focused = params["pane_id"]
            return {"type": "ok"}
        raise KeyError(method)

    def _serve(self) -> None:
        while True:
            try:
                connection = self._listener.accept()
            except OSError:
                return
            # One request a connection, as herdr answers, then closed.
            with connection:
                try:
                    line = connection.recv_bytes()
                except (EOFError, OSError):
                    continue
                request = json.loads(line)
                method, params = request["method"], request.get("params") or {}
                self.asked.append((method, params))
                if method in self.refuse:
                    answer = {
                        "id": request["id"],
                        "error": {"code": self.refuse[method], "message": "refused"},
                    }
                else:
                    answer = {"id": request["id"], "result": self._answer(method, params)}
                connection.send_bytes(json.dumps(answer).encode() + b"\n")
