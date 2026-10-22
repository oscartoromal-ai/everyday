"""View-model for the work seen in herdr (app/services/work_log.py): Today's
Work pane (partials/work_pane.html), what is going on in herdr now (today's
page only) and the day's work, a line for each thing worked on; and a task's
Work pane on its page's sidebar (partials/task_work.html), its sessions."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dates import duration_label, short_date, upper_first
from app.models import WorkSession
from app.services import everyday, work_log
from app.sources.herdr import Herdr, HerdrError, NotRunning

# An agent's status in herdr in words, its chip's look (app.css, .chip), and
# its place in the list: waiting on Oscar first, then working, then at rest.
LIVE_STATES = {
    "blocked": ("Waiting on you", "needs_review", 0),
    "working": ("Working", "running", 1),
    "done": ("Done", "queued", 2),
    "idle": ("Idle", "queued", 2),
    "unknown": ("Starting", "queued", 2),
}


def herdr() -> Herdr:
    """The herdr the app works with ([herdr]); a stand-in under test."""
    config = get_settings().herdr
    return Herdr.local(config.session, config.socket, config.cli)


def hm(seconds: float) -> str:
    """A length of time as it is written: '45m', '1h 5m'; under a minute, '<1m'."""
    minutes = round(seconds / 60)
    return duration_label(minutes) if minutes else "<1m"


def totals_words(totals: work_log.Totals) -> str:
    """You 1h 5m · agents 2h · waited on you 5m: what of it there was."""
    said = []
    if totals.you >= work_log.SAID_SECONDS:
        said.append(f"You {hm(totals.you)}")
    if totals.working >= work_log.SAID_SECONDS:
        said.append(f"agents {hm(totals.working)}")
    if totals.blocked >= work_log.SAID_SECONDS:
        said.append(f"waited on you {hm(totals.blocked)}")
    return upper_first(" · ".join(said))


def place(cwd: str) -> str:
    """A folder as it is short to read: from the everyday files' folder, or
    from home (~\\code\\app); its name alone when it is neither."""
    if not cwd:
        return "A terminal"
    path = Path(cwd)
    for base, mark in ((everyday.root(), ""), (Path.home(), "~")):
        try:
            rest = path.relative_to(base)
        except ValueError:
            continue
        return str(Path(mark, rest)) if mark else str(rest)
    return str(path)


def _task(task) -> dict[str, Any] | None:  # noqa: ANN001
    if task is None:
        return None
    return {
        "id": task.id,
        "title": task.title,
        "project": task.project,
    }


def live_ctx(db: Session, source: Herdr) -> dict[str, Any]:
    """The agents in herdr now, each with the task its terminal is filed
    under: waiting on Oscar first. running is False when herdr is not
    running, None when it could not be read."""
    try:
        terminals = work_log.seen(source.snapshot(timeout=work_log.LOOK_TIMEOUT))
    except NotRunning:
        return {"running": False, "agents": []}
    except HerdrError as exc:
        return {"running": None, "agents": [], "error": str(exc)}
    with_agents = [t for t in terminals if t.agent]
    sessions = {
        s.terminal_id: s
        for s in db.scalars(
            select(WorkSession).where(
                WorkSession.terminal_id.in_([t.terminal_id for t in with_agents])
            )
        )
    }
    agents = []
    for t in with_agents:
        words, chip, order = LIVE_STATES.get(t.status, LIVE_STATES["unknown"])
        session = sessions.get(t.terminal_id)
        agents.append(
            {
                "terminal": t.terminal_id,
                "state": words,
                "chip": chip,
                "order": order,
                "agent": t.agent,
                "title": t.title,
                "task": _task(session.task if session else None),
                "project": session.project if session and not session.task_id else None,
                "place": t.workspace or place(t.cwd),
                "where": t.cwd,
            }
        )
    agents.sort(key=lambda a: a["order"])
    return {"running": True, "agents": agents}


def _line(line: work_log.Line) -> dict[str, Any]:
    session = line.session
    return {
        "kind": line.key[0],
        "task": _task(line.task),
        "project": line.project,
        "session_id": session.id if session else None,
        "place": (session.workspace or place(session.cwd)) if session else "",
        "where": session.cwd if session else "",
        "totals": totals_words(line.totals),
        "count": len(line.sessions),
    }


def pane_ctx(db: Session, day: date, today: date, source: Herdr | None = None) -> dict[str, Any]:
    """Today's Work pane: what is going on now, then the day's work."""
    lines = [_line(line) for line in work_log.day(db, day)]
    unfiled = any(line["kind"] == "session" for line in lines)
    return {
        "day": day,
        "is_today": day == today,
        "live": live_ctx(db, source or herdr()) if day == today else None,
        "lines": lines,
        # The tasks a terminal may be filed under, offered as it is written.
        "tasks": work_log.open_tasks(db) if unfiled else [],
    }


def _when(at: datetime, today: date) -> str:
    return f"{upper_first(short_date(at.date(), today))} {at:%H:%M}"


def task_ctx(db: Session, task_id: int, today: date) -> dict[str, Any]:
    """A task's Work pane: its time all told, then each of its sessions."""
    total = work_log.Totals()
    sessions = []
    for session, totals in work_log.of_task(db, task_id):
        for kind in work_log.KINDS:
            total.add(kind, getattr(totals, kind))
        sessions.append(
            {
                "agent": session.agent,
                "title": session.title,
                "when": _when(session.started_at, today),
                "live": session.ended_at is None,
                "place": session.workspace or place(session.cwd),
                "where": session.cwd,
                "terminal": session.terminal_id,
                "filed": work_log.FILED_BY.get(session.filed_by, ""),
                "totals": totals_words(totals),
            }
        )
    return {"total": totals_words(total), "sessions": sessions, "task_id": task_id}
