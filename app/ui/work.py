"""The work seen in herdr, on Today's Work pane (partials/work_pane.html) and
a task's Work pane (partials/task_work.html): drawn, a terminal filed under a
task by Oscar, and an agent's pane shown in herdr."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response

from app.config import get_settings
from app.db import DbSession
from app.services import DomainError, work_log
from app.sources import attention
from app.sources.herdr import HerdrError
from app.ui import work_view
from app.ui.views import templates

router = APIRouter(include_in_schema=False)

# A task as written to file a terminal under it: "#12 Fix the build", or 12.
_TASK = re.compile(r"^\s*#?(\d+)\b")


def _pane(request: Request, db: DbSession, day: date) -> Response:
    return templates.TemplateResponse(
        request,
        "partials/work_pane.html",
        {"request": request, "work": work_view.pane_ctx(db, day, date.today())},
    )


@router.get("/ui/work/{day}")
def work_pane(request: Request, db: DbSession, day: date):
    """The day's Work pane, drawn again (every few seconds, on today's page)."""
    return _pane(request, db, day)


@router.post("/ui/work/sessions/{session_id}/file")
def file_session(
    request: Request,
    db: DbSession,
    session_id: int,
    day: Annotated[date, Form()],
    task: Annotated[str, Form()] = "",
):
    """A terminal filed under a task, written as #12 or chosen from those
    offered; under none, written as nothing."""
    found = _TASK.match(task)
    if task.strip() and not found:
        raise DomainError("Write the task as its number, #12, or choose one offered")
    work_log.file(db, session_id, int(found[1]) if found else None)
    db.commit()
    return _pane(request, db, day)


@router.post("/ui/work/show", status_code=204)
def show_in_herdr(terminal: Annotated[str, Form()]) -> None:
    """An agent's pane brought to the front of herdr, and herdr's screen (its
    terminal, WezTerm) to the front of the desktop."""
    try:
        if not work_view.herdr().focus(terminal):
            raise DomainError("It is not in herdr anymore")
    except HerdrError as exc:
        raise DomainError(f"herdr could not show it: {exc}") from exc
    attention.bring_forward(get_settings().herdr.terminals)


@router.get("/ui/tasks/{task_id}/work")
def task_work(request: Request, db: DbSession, task_id: int):
    """A task's Work pane: its time all told, and each of its sessions."""
    return templates.TemplateResponse(
        request,
        "partials/task_work.html",
        {"request": request, "work": work_view.task_ctx(db, task_id, date.today())},
    )
