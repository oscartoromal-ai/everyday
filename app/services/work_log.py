"""The work seen in herdr, recorded (SPEC.md, Work in herdr): what Oscar and
his agents actually did, filed under the task or project it was for.

herdr is looked at every few seconds (watch(), a thread of the app's own).
Each terminal in it is a session (models.WorkSession): its herdr workspace,
its folder, the agent in it, from when it was first seen to when it went.
Its spans (models.WorkSpan) are the stretches of it:

- "you": Oscar at it, herdr's screen in front (in one of his terminals,
  WezTerm) with the pane focused, and he not away from the keyboard;
- "working": its agent working;
- "blocked": its agent waiting on him (an approval, a question).

A session is filed under a task, told by (FILED_BY) the run launched in it,
its herdr workspace's name ("#12 ..."), its folder (a run's workspace in
work/, a task's folder in the everyday files), or its git branch
(task/12-...); else under a project, by its folder (the project's, or one of
its repositories'); else under nothing, for Oscar to file. Filed by him, it
stays as he filed it. A session's folder or name changing files it again.

What a gap leaves (the machine asleep, herdr or the app not running) is not
counted: what was open ends where it was last seen.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Project, Task, TaskRun, TaskStatus, WorkSession, WorkSpan
from app.services import DomainError, everyday, project_files
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.sources.herdr import Herdr, HerdrError, NotRunning

log = logging.getLogger(__name__)

KINDS = ("you", "working", "blocked")

# How a session was filed, in words.
FILED_BY = {
    "run": "launched from the task's page",
    "label": "found by its herdr workspace's name",
    "workspace": "found by its folder in work/",
    "files": "found by its folder, the task's",
    "branch": "found by its branch",
    "folder": "found by its folder, the project's",
    "oscar": "filed by you",
}

# Time worth saying: what rounds to a minute.
SAID_SECONDS = 30

# Open spans are written as they go on at most this often; a session or span
# starting or ending is written at once.
FLUSH_SECONDS = 30

# A task named in a herdr workspace's name: "#12 Fix the build".
_LABEL_TASK = re.compile(r"#(\d+)\b")
_ID_FOLDER = re.compile(r"^(\d+)-")
_TASK_BRANCH = re.compile(r"^task/(\d+)-")
BRANCH_SECONDS = 60
# herdr answers a look within this, or it is left for the next.
LOOK_TIMEOUT = 3.0


@dataclass(frozen=True)
class Seen:
    """A terminal as herdr shows it now."""

    terminal_id: str
    pane_id: str
    workspace: str
    cwd: str
    agent: str
    agent_session: str
    title: str
    # Its agent's status: idle, working, blocked, done, unknown; "" for none.
    status: str
    focused: bool


def _title(agent: dict[str, Any]) -> str:
    """What an agent calls its work (its terminal's title), "" while that is
    only its own name ("claude", "Claude Code")."""
    title = (agent.get("terminal_title_stripped") or "").strip()
    kind = (agent.get("agent") or "").lower()
    return "" if not title or title.lower() in (kind, f"{kind} code") else title


def seen(snapshot: dict[str, Any]) -> list[Seen]:
    """Every terminal in a herdr snapshot (session.snapshot)."""
    labels = {w.get("workspace_id"): w.get("label") or "" for w in snapshot.get("workspaces", [])}
    agents = {a.get("terminal_id"): a for a in snapshot.get("agents", [])}
    focused = snapshot.get("focused_pane_id")
    found = []
    for pane in snapshot.get("panes", []):
        terminal = pane.get("terminal_id")
        if not terminal:
            continue
        agent = agents.get(terminal) or {}
        found.append(
            Seen(
                terminal_id=terminal,
                pane_id=pane.get("pane_id") or "",
                workspace=labels.get(pane.get("workspace_id"), ""),
                cwd=(pane.get("cwd") or agent.get("cwd") or "").rstrip("\\/"),
                agent=agent.get("agent") or "",
                agent_session=(agent.get("agent_session") or {}).get("value") or "",
                title=_title(agent),
                status=(agent.get("agent_status") or "") if agent else "",
                focused=pane.get("pane_id") == focused,
            )
        )
    return found


# ---- filing ----


def _within(path: Path, folder: Path) -> Path | None:
    """`path` from `folder`, when it is in it."""
    try:
        return Path(os.path.normcase(os.path.normpath(path))).relative_to(
            os.path.normcase(os.path.normpath(folder))
        )
    except ValueError:
        return None


_branches: dict[str, tuple[float, str]] = {}


def branch_of(cwd: str) -> str:
    """The git branch checked out where `cwd` is, "" when none; asked again
    after a minute."""
    kept = _branches.get(cwd)
    if kept and time.monotonic() - kept[0] < BRANCH_SECONDS:
        return kept[1]
    branch = ""
    if cwd and Path(cwd).is_dir():
        try:
            done = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            branch = done.stdout.strip() if done.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            branch = ""
    _branches[cwd] = (time.monotonic(), branch)
    return branch


def _task(db: Session, task_id: int) -> Task | None:
    return db.get(Task, task_id)


def _project_folders(db: Session) -> list[tuple[Path, int]]:
    """Each project's folders: its folder in the everyday files, and its
    repositories' (the folder a location names, or its clone in repos/)."""
    found = []
    for project in db.scalars(select(Project).options(selectinload(Project.repos))):
        folder = project_files.folder_path(project)
        if folder is not None:
            found.append((folder, project.id))
        for repo in project.repos:
            path = Path(repo.location.strip())
            if not path.is_absolute():
                path = everyday.repos_dir() / projects_svc.repo_name(repo.location)
            found.append((path, project.id))
    # The deepest first: a repository inside another's folder is its own.
    return sorted(found, key=lambda f: len(f[0].parts), reverse=True)


def file_under(db: Session, terminal: Seen) -> tuple[Task | None, int | None, str]:
    """The task (or, failing one, the project) a terminal's work is for, and
    how that was told (FILED_BY); (None, None, "") when nothing tells."""
    run = db.scalars(
        select(TaskRun).where(TaskRun.runner == "herdr", TaskRun.run_id == terminal.terminal_id)
    ).first()
    if run is not None and (task := _task(db, run.task_id)):
        return task, task.project_id, "run"
    if (named := _LABEL_TASK.search(terminal.workspace)) and (task := _task(db, int(named[1]))):
        return task, task.project_id, "label"
    cwd = Path(terminal.cwd) if terminal.cwd else None
    if cwd is not None:
        inside = _within(cwd, everyday.work_dir())
        folder = _ID_FOLDER.match(inside.parts[0]) if inside and inside.parts else None
        if folder and (task := _task(db, int(folder[1]))):
            return task, task.project_id, "workspace"
        inside = _within(cwd, everyday.root())
        if inside:
            parts = inside.parts
            for i, part in enumerate(parts[:-1]):
                folder = _ID_FOLDER.match(parts[i + 1]) if part == "tasks" else None
                if folder and (task := _task(db, int(folder[1]))):
                    return task, task.project_id, "files"
        branch = _TASK_BRANCH.match(branch_of(terminal.cwd))
        if branch and (task := _task(db, int(branch[1]))):
            return task, task.project_id, "branch"
        for folder, project_id in _project_folders(db):
            if _within(cwd, folder) is not None:
                return None, project_id, "folder"
    return None, None, ""


def file(db: Session, session_id: int, task_id: int | None) -> WorkSession:
    """A session filed by Oscar under a task (its project with it), or under
    nothing; it stays so."""
    session = db.get(WorkSession, session_id)
    if session is None:
        raise DomainError(f"No work session {session_id}")
    task = tasks_svc.get_task(db, task_id) if task_id is not None else None
    session.task = task
    session.project = task.project if task else None
    session.filed_by = "oscar"
    db.flush()
    return session


# ---- recording ----


@dataclass
class Recorder:
    """What is being recorded, between one look at herdr and the next: each
    live terminal's session, and each span going on."""

    sessions: dict[str, int] = field(default_factory=dict)
    # (terminal, kind) -> the span's id.
    spans: dict[tuple[str, str], int] = field(default_factory=dict)
    # What each live terminal was filed from: its workspace's name and folder.
    filed_from: dict[str, tuple[str, str]] = field(default_factory=dict)
    last: datetime | None = None
    flushed: datetime | None = None
    started: bool = False

    def wanted(self, terminals: list[Seen], at_screen: bool) -> set[tuple[str, str]]:
        spans = set()
        for t in terminals:
            if t.status in ("working", "blocked"):
                spans.add((t.terminal_id, t.status))
            if at_screen and t.focused:
                spans.add((t.terminal_id, "you"))
        return spans

    def _end_all(self, db: Session, at: datetime) -> None:
        """Every span going on ended at `at`, and every session with them."""
        for span_id in self.spans.values():
            if span := db.get(WorkSpan, span_id):
                span.ended_at = max(span.started_at, at)
        for session_id in self.sessions.values():
            if session := db.get(WorkSession, session_id):
                session.seen_at, session.ended_at = at, at
        self.spans.clear()
        self.sessions.clear()
        self.filed_from.clear()

    def _resume(self, db: Session) -> None:
        """On the first look since the app started: the sessions left going
        ended where they were last seen; those still live are taken up
        again as they are seen."""
        for session in db.scalars(select(WorkSession).where(WorkSession.ended_at.is_(None))):
            session.ended_at = session.seen_at
        self.started = True

    def _session(self, db: Session, t: Seen, now: datetime) -> WorkSession:
        session_id = self.sessions.get(t.terminal_id)
        session = db.get(WorkSession, session_id) if session_id else None
        if session is None:
            session = db.scalars(
                select(WorkSession).where(WorkSession.terminal_id == t.terminal_id)
            ).first()
            if session is None:
                session = WorkSession(terminal_id=t.terminal_id, started_at=now, seen_at=now)
                db.add(session)
            session.ended_at = None
            db.flush()
            self.sessions[t.terminal_id] = session.id
        session.workspace = t.workspace[:255]
        session.cwd = t.cwd
        if t.agent:
            session.agent = t.agent[:40]
        if t.agent_session:
            session.agent_session = t.agent_session[:120]
        if t.title:
            session.title = t.title[:255]
        return session

    def _file(self, db: Session, session: WorkSession, t: Seen, flush: bool) -> None:
        """Filed when first seen and when its name or folder changes; while
        under no task, again at each flush (a run's row comes after its
        terminal). Filed by Oscar, it stays."""
        source = (t.workspace, t.cwd)
        changed = self.filed_from.get(t.terminal_id) != source
        self.filed_from[t.terminal_id] = source
        if session.filed_by == "oscar":
            return
        if not changed and not (flush and session.task_id is None):
            return
        task, project_id, by = file_under(db, t)
        session.task = task
        session.project = db.get(Project, project_id) if project_id else None
        session.filed_by = by

    def look(
        self, db: Session, terminals: list[Seen] | None, at_screen: bool, now: datetime, gap: float
    ) -> bool:
        """One look at herdr (`terminals`, None when it is not running)
        recorded. Answers whether anything was written."""
        if not self.started:
            self._resume(db)
        wrote = False
        if self.last is not None and (now - self.last).total_seconds() > gap:
            # Asleep, or unreachable: what was going on ended when last seen.
            self._end_all(db, self.last)
            wrote = True
        live = {t.terminal_id: t for t in terminals or []}
        flush = self.flushed is None or (now - self.flushed).total_seconds() >= FLUSH_SECONDS
        for terminal_id in [tid for tid in self.sessions if tid not in live]:
            if session := db.get(WorkSession, self.sessions.pop(terminal_id)):
                session.seen_at = session.ended_at = now
            self.filed_from.pop(terminal_id, None)
            wrote = True
        for t in live.values():
            new = t.terminal_id not in self.sessions
            session = self._session(db, t, now)
            self._file(db, session, t, flush)
            if new or flush:
                session.seen_at = now
            wrote |= new
        wanted = self.wanted(list(live.values()), at_screen)
        for key in [k for k in self.spans if k not in wanted]:
            if span := db.get(WorkSpan, self.spans.pop(key)):
                span.ended_at = now
            wrote = True
        for key in wanted:
            span_id = self.spans.get(key)
            if span_id is None:
                span = WorkSpan(
                    session_id=self.sessions[key[0]], kind=key[1], started_at=now, ended_at=now
                )
                db.add(span)
                db.flush()
                self.spans[key] = span.id
                wrote = True
            elif flush and (span := db.get(WorkSpan, span_id)):
                span.ended_at = now
        if flush:
            self.flushed = now
            wrote |= bool(self.sessions)
        self.last = now
        return wrote or bool(db.new or db.dirty)


class Watcher:
    """herdr looked at, now and then, and what it shows recorded."""

    def __init__(
        self,
        factory: Callable[[], Session],
        herdr: Herdr,
        at_screen: Callable[[], bool],
        interval: float,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.factory = factory
        self.herdr = herdr
        self.at_screen = at_screen
        self.interval = interval
        self.now = now
        self.recorder = Recorder()

    def look(self) -> None:
        try:
            terminals: list[Seen] | None = seen(self.herdr.snapshot(timeout=LOOK_TIMEOUT))
        except NotRunning:
            terminals = None
        except HerdrError as exc:
            # Busy or stuck: the next look tries again, and a long gap ends
            # what was going on.
            log.info("herdr not read: %s", exc)
            return
        at_screen = bool(terminals) and self.at_screen()
        try:
            with self.factory() as db:
                db.info["actor"] = "system"
                if self.recorder.look(db, terminals, at_screen, self.now(), gap=self.interval * 4):
                    db.commit()
        except Exception:
            # Not written (the database busy): what it held is begun again,
            # from the database, at the next look.
            self.recorder = Recorder()
            raise


# ---- what was done ----


@dataclass
class Totals:
    you: float = 0.0
    working: float = 0.0
    blocked: float = 0.0

    def add(self, kind: str, seconds: float) -> None:
        setattr(self, kind, getattr(self, kind) + seconds)

    @property
    def any(self) -> bool:
        return max(self.you, self.working, self.blocked) >= SAID_SECONDS


def _clipped(span: WorkSpan, start: datetime, end: datetime) -> float:
    return max(0.0, (min(span.ended_at, end) - max(span.started_at, start)).total_seconds())


def spans_between(db: Session, start: datetime, end: datetime) -> list[WorkSpan]:
    return list(
        db.scalars(
            select(WorkSpan)
            .where(WorkSpan.started_at < end, WorkSpan.ended_at > start)
            .options(selectinload(WorkSpan.session))
            .order_by(WorkSpan.started_at)
        )
    )


@dataclass
class Line:
    """What was done on one thing on a day: a task, a project (its work on
    no task of its), or a session filed under nothing."""

    key: tuple[str, int]
    task: Task | None
    project: Project | None
    session: WorkSession | None
    totals: Totals = field(default_factory=Totals)
    sessions: set[int] = field(default_factory=set)
    first: datetime | None = None


def day(db: Session, on: date) -> list[Line]:
    """The day's work, a line for each thing worked on, the most of Oscar's
    time first, then the most of the agents'."""
    start = datetime.combine(on, datetime.min.time())
    end = start + timedelta(days=1)
    lines: dict[tuple[str, int], Line] = {}
    for span in spans_between(db, start, end):
        session = span.session
        if session.task_id:
            key = ("task", session.task_id)
        elif session.project_id:
            key = ("project", session.project_id)
        else:
            key = ("session", session.id)
        line = lines.get(key)
        if line is None:
            line = lines[key] = Line(
                key,
                session.task,
                session.project if not session.task_id else None,
                session if key[0] == "session" else None,
            )
        line.totals.add(span.kind, _clipped(span, start, end))
        line.sessions.add(session.id)
        line.first = min(line.first or span.started_at, span.started_at)
    kept = [line for line in lines.values() if line.totals.any]
    return sorted(kept, key=lambda line: (-line.totals.you, -line.totals.working))


def of_task(db: Session, task_id: int) -> list[tuple[WorkSession, Totals]]:
    """A task's sessions, the newest first, each with its totals."""
    sessions = db.scalars(
        select(WorkSession)
        .where(WorkSession.task_id == task_id)
        .options(selectinload(WorkSession.spans))
        .order_by(WorkSession.started_at.desc())
    ).all()
    found = []
    for session in sessions:
        totals = Totals()
        for span in session.spans:
            totals.add(span.kind, (span.ended_at - span.started_at).total_seconds())
        found.append((session, totals))
    return found


def open_tasks(db: Session) -> list[Task]:
    """The tasks a session may be filed under: those not settled, the most
    recently changed first."""
    return list(
        db.scalars(
            select(Task)
            .where(Task.status.not_in((TaskStatus.done, TaskStatus.cancelled)))
            .order_by(Task.status_changed_at.desc())
            .limit(300)
        )
    )


def watch(stop: threading.Event) -> None:
    """herdr looked at every [herdr] watch_seconds, and what it shows
    recorded, until stop is set: a thread of the app's own, beside the jobs
    (a job run every few seconds would fill the log). A look that fails is
    logged, and the next one tried."""
    from app.config import get_settings
    from app.db import get_session_factory
    from app.sources import attention

    config = get_settings().herdr
    watcher = Watcher(
        get_session_factory(),
        Herdr.local(config.session, config.socket, config.cli),
        lambda: attention.at_terminal(config.terminals, config.away_minutes),
        config.watch_seconds,
    )
    while not stop.wait(config.watch_seconds):
        try:
            watcher.look()
        except Exception:
            log.exception("The work in herdr was not recorded")
