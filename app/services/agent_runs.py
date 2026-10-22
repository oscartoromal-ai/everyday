"""Agent runs: a brief handed to an agent, working in a workspace of its own.

A run is the same whichever agent system takes it: a brief (what to do),
launched by a runner into a git worktree on a branch of its own, then looked
at until it is done. Its state is read from the runner, never reported by
the agent: the runner knows whether its thread is working, waiting on Oscar,
finished or failed. What a run made (its pull request) is found from its
branch, the one thing it is given that it cannot change.

herdr (app/sources/herdr.py), where Oscar works in his terminal, and T3
Code (app/sources/t3.py) are the runners; another agent system is another
Runner.
"""

from __future__ import annotations

import enum
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.sources.herdr import Herdr, HerdrError, NotRunning
from app.sources.t3 import T3, T3Error

GIT_TIMEOUT = 300


class RunState(enum.StrEnum):
    working = "working"
    # Waiting on Oscar: an approval, or an answer to a question.
    waiting = "waiting"
    finished = "finished"
    failed = "failed"
    # Not there anymore: archived or deleted.
    gone = "gone"


@dataclass(frozen=True)
class Brief:
    title: str
    text: str
    # The folder the work is on, the runner's project: a repo, its worktree
    # and branch made by prepare_worktree; or, with no worktree, a folder
    # worked in as it is (a task's workspace holding a worktree of each of
    # its repos, each on the branch).
    repo: Path
    worktree: Path | None
    branch: str


@dataclass(frozen=True)
class Run:
    runner: str
    id: str


class RunError(Exception):
    """A run could not be launched or looked at."""


class Runner(Protocol):
    name: str

    def launch(self, brief: Brief) -> Run: ...

    def states(self, runs: list[Run]) -> dict[str, RunState]: ...


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
        stdin=subprocess.DEVNULL,
    )
    if out.returncode:
        raise RunError(f"git {' '.join(args[:2])}: {out.stderr.strip()[-500:]}")
    return out.stdout


def prepare_worktree(repo: Path, worktree: Path, branch: str, base: str = "origin/master") -> None:
    """A worktree of `repo` at `worktree`, on a new `branch` from `base` as
    fetched now."""
    remote, _, name = base.partition("/")
    _git("fetch", "--quiet", remote, name, cwd=repo)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "-b", branch, str(worktree), base, cwd=repo)


def remove_worktree(repo: Path, worktree: Path) -> bool:
    """The worktree removed, when it is there and has nothing uncommitted;
    whether it was. Its branch stays (its pull request needs it)."""
    if not worktree.exists():
        return False
    if _git("status", "--porcelain", cwd=worktree).strip():
        return False
    _git("worktree", "remove", str(worktree), cwd=repo)
    return True


def _same_path(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(str(b)))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class T3Runner:
    """Runs as T3 Code threads, on the T3 project whose workspace is the repo,
    with full access: no one is there to approve each step."""

    name = "t3"

    def __init__(self, t3: T3 | None = None, model: str = "claude-opus-5-5") -> None:
        self._t3 = t3
        self.model = model

    @property
    def t3(self) -> T3:
        if self._t3 is None:
            self._t3 = T3.local()
        return self._t3

    def launch(self, brief: Brief) -> Run:
        selection = {"instanceId": "claudeAgent", "model": self.model}
        thread_id = str(uuid4())
        modes = {"runtimeMode": "full-access", "interactionMode": "default"}
        try:
            with self.t3.connect("personal-calendar-runs") as t3:
                projects = t3.snapshot()["projects"]
                project = next(
                    (p for p in projects if _same_path(p.get("workspaceRoot", ""), brief.repo)),
                    None,
                )
                if project is None:
                    # One made for it, as T3's own Add project would.
                    project = {"id": str(uuid4())}
                    t3.dispatch(
                        {
                            "type": "project.create",
                            "commandId": str(uuid4()),
                            "projectId": project["id"],
                            "title": brief.repo.name,
                            "workspaceRoot": str(brief.repo),
                            "createdAt": _now(),
                        }
                    )
                t3.dispatch(
                    {
                        "type": "thread.create",
                        "commandId": str(uuid4()),
                        "threadId": thread_id,
                        "projectId": project["id"],
                        "title": brief.title,
                        "modelSelection": selection,
                        **modes,
                        "branch": brief.branch if brief.worktree else None,
                        "worktreePath": str(brief.worktree) if brief.worktree else None,
                        "createdAt": _now(),
                    }
                )
                t3.dispatch(
                    {
                        "type": "thread.turn.start",
                        "commandId": str(uuid4()),
                        "threadId": thread_id,
                        "message": {
                            "messageId": str(uuid4()),
                            "role": "user",
                            "text": brief.text,
                            "attachments": [],
                        },
                        "modelSelection": selection,
                        **modes,
                        "createdAt": _now(),
                    }
                )
        except T3Error as exc:
            raise RunError(str(exc)) from exc
        return Run(self.name, thread_id)

    def states(self, runs: list[Run]) -> dict[str, RunState]:
        try:
            with self.t3.connect("personal-calendar-runs") as t3:
                threads = {t["id"]: t for t in t3.snapshot()["threads"]}
        except T3Error as exc:
            raise RunError(str(exc)) from exc
        return {run.id: thread_state(threads.get(run.id)) for run in runs}


def thread_state(thread: dict | None) -> RunState:
    """A T3 thread's state, as a run's."""
    if thread is None or thread.get("archivedAt"):
        return RunState.gone
    if thread.get("hasPendingApprovals") or thread.get("hasPendingUserInput"):
        return RunState.waiting
    turn = (thread.get("latestTurn") or {}).get("state")
    session = (thread.get("session") or {}).get("status")
    if turn == "running" or session in ("starting", "running"):
        return RunState.working
    if turn == "completed":
        return RunState.finished
    if turn in ("interrupted", "error") or session == "error":
        return RunState.failed
    # Made, its first message not yet taken up.
    return RunState.working


# A herdr agent's name: a letter, then letters, digits, - and _ (32 at most).
_AGENT_NAME = re.compile(r"[^a-z0-9_-]+")
_TASK_BRANCH = re.compile(r"^task/(\d+)-")


def brief_path(folder: Path) -> Path:
    """Where a run's brief is written, for the agent to read first: beside
    the folder it works in (never in it, a repository's worktree), in
    .briefs/."""
    return folder.parent / ".briefs" / f"{folder.name}.md"


class HerdrRunner:
    """Runs as agents in herdr (app/sources/herdr.py), each in a workspace of
    its own named after its task, where Oscar watches them and answers them
    in his terminal. The brief is a file beside the folder worked in and the
    agent's opening prompt says to read it: the agent's first screens (a
    folder to trust) are Oscar's to answer, and its prompt waits for them.
    herdr's server is started when it is not running. A run's id is its
    terminal's, which stays the same as its pane is moved about."""

    name = "herdr"

    def __init__(
        self,
        herdr: Herdr | None = None,
        model: str = "claude-opus-5-5",
        agent: str | None = None,
        args: list[str] | None = None,
    ) -> None:
        self._herdr = herdr
        self.model = model
        self._agent = agent
        self._args = args

    @property
    def herdr(self) -> Herdr:
        if self._herdr is None:
            from app.config import get_settings

            config = get_settings().herdr
            self._herdr = Herdr.local(config.session, config.socket, config.cli)
        return self._herdr

    def _config(self) -> tuple[str, list[str]]:
        from app.config import get_settings

        config = get_settings().herdr
        agent = self._agent if self._agent is not None else config.agent
        args = self._args if self._args is not None else list(config.agent_args)
        return agent, args

    @staticmethod
    def _label(brief: Brief) -> str:
        task = _TASK_BRANCH.match(brief.branch)
        return f"#{task[1]} {brief.title}" if task else brief.title

    @staticmethod
    def _agent_name(brief: Brief, taken: set[str]) -> str:
        """A name of its own among the agents live: task-12, else task-12-2."""
        task = _TASK_BRANCH.match(brief.branch)
        folder = brief.worktree or brief.repo
        base = f"task-{task[1]}" if task else _AGENT_NAME.sub("-", folder.name.lower()).strip("-")
        if not base or not base[0].isalpha():
            base = f"run-{base}".rstrip("-")
        base = base[:28]
        name, n = base, 1
        while name in taken:
            n += 1
            name = f"{base}-{n}"
        return name

    def launch(self, brief: Brief) -> Run:
        folder = brief.worktree or brief.repo
        path = brief_path(folder)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(brief.text, encoding="utf-8")
        agent, args = self._config()
        if agent == "claude" and self.model and "--model" not in args:
            args = [*args, "--model", self.model]
        opening = f"Your brief is in {path}: read it first, then do what it says."
        try:
            herdr = self.herdr
            herdr.start()
            agents = herdr.call("agent.list").get("agents", [])
            taken = {a.get("name") for a in agents if a.get("name")}
            made = herdr.call(
                "workspace.create",
                {"cwd": str(folder), "label": self._label(brief), "focus": False},
            )
            pane = made["root_pane"]
            start = {
                "name": self._agent_name(brief, taken),
                "kind": agent,
                "pane_id": pane["pane_id"],
                "args": [*args, opening],
                "timeout_ms": 60000,
            }
            try:
                # Answered once the agent is up, or waiting at its first screen.
                herdr.call("agent.start", start, timeout=90)
            except HerdrError as exc:
                # Started, and waiting on Oscar at its first screen.
                if exc.code != "agent_not_ready":
                    raise
        except (HerdrError, KeyError, OSError) as exc:
            raise RunError(str(exc)) from exc
        return Run(self.name, pane["terminal_id"])

    def states(self, runs: list[Run]) -> dict[str, RunState]:
        try:
            snapshot = self.herdr.snapshot()
        except NotRunning:
            # Its server stopped, and every terminal with it.
            snapshot = {}
        except HerdrError as exc:
            raise RunError(str(exc)) from exc
        panes = {p.get("terminal_id"): p for p in snapshot.get("panes", [])}
        agents = {a.get("terminal_id"): a for a in snapshot.get("agents", [])}
        return {run.id: herdr_state(panes.get(run.id), agents.get(run.id)) for run in runs}


def herdr_state(pane: dict | None, agent: dict | None) -> RunState:
    """A herdr terminal's state, as a run's: gone with its pane, finished
    once its agent is at rest (idle, done) in a session of its own, or has
    left the terminal. At rest before its session began, it is starting
    (herdr says done for a moment as its first screen is answered)."""
    if pane is None:
        return RunState.gone
    if agent is None:
        return RunState.finished
    status = agent.get("agent_status")
    if status == "blocked":
        return RunState.waiting
    if status in ("idle", "done") and (agent.get("agent_session") or {}).get("value"):
        return RunState.finished
    # Working, or starting and not yet told apart.
    return RunState.working


RUNNERS = {"herdr": HerdrRunner, "t3": T3Runner}
