"""Agent runs: a brief handed to an agent, working in a workspace of its own.

A run is the same whichever agent system takes it: a brief (what to do),
launched by a runner into a git worktree on a branch of its own, then looked
at until it is done. Its state is read from the runner, never reported by
the agent: the runner knows whether its thread is working, waiting on Oscar,
finished or failed. What a run made (its pull request) is found from its
branch, the one thing it is given that it cannot change.

T3 Code is the first runner (app/sources/t3.py); another agent system is
another Runner.
"""

from __future__ import annotations

import enum
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

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
    # The repo the work is on, its worktree and branch made by prepare_worktree.
    repo: Path
    worktree: Path
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
                    raise RunError(f"T3 Code has no project for {brief.repo}")
                t3.dispatch(
                    {
                        "type": "thread.create",
                        "commandId": str(uuid4()),
                        "threadId": thread_id,
                        "projectId": project["id"],
                        "title": brief.title,
                        "modelSelection": selection,
                        **modes,
                        "branch": brief.branch,
                        "worktreePath": str(brief.worktree),
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


RUNNERS = {"t3": T3Runner}
