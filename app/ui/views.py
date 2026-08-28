"""Shared template setup and view-model helpers for the server-rendered UI."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.dates import human_date, short_date
from app.models import Block, BlockState, Task, TaskOwner, TaskStatus
from app.services import tasks as tasks_svc

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

CHIPS = {
    TaskStatus.todo: ("Queued", "queued"),
    TaskStatus.in_progress: ("Running", "running"),
    TaskStatus.needs_review: ("Needs review", "needs_review"),
    TaskStatus.blocked: ("Blocked", "blocked"),
}

DUE_SOON_DAYS = 3


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["human_date"] = human_date
templates.env.filters["short_date"] = short_date


def last_missed_block(task: Task) -> Block | None:
    missed = [b for b in task.blocks if b.state == BlockState.missed]
    return max(missed, key=lambda b: b.start) if missed else None


def row_ctx(task: Task, now: datetime) -> dict[str, Any]:
    """Everything the task-row partial needs, precomputed."""
    missed = tasks_svc.has_missed_marker(task, now)
    missed_block = last_missed_block(task) if missed else None
    today = now.date()
    return {
        "task": task,
        "done": task.status == TaskStatus.done,
        "missed": missed,
        "missed_label": (
            f"missed {short_date(missed_block.start.date(), today)}" if missed_block else None
        ),
        "chip": (
            CHIPS[task.status][0]
            if task.owner == TaskOwner.claude and task.status in CHIPS
            else None
        ),
        "chip_class": CHIPS[task.status][1] if task.status in CHIPS else "",
        "due_label": f"due {short_date(task.due, today)}" if task.due else None,
        "due_soon": bool(task.due and task.due <= today + timedelta(days=DUE_SOON_DAYS)),
        "project_name": task.project.name if task.project else None,
    }


def today_page_tasks(db: Session, now: datetime) -> tuple[list[Task], list[Task]]:
    """(oscar_rows, delegated_rows) for the Today page.

    Oscar's list: tasks planned for today plus fallen-back missed tasks from
    other days. Delegated: open Claude-owned tasks, own section.
    """
    today = now.date()
    planned = tasks_svc.daily_list(db, today)
    fallback = [
        t
        for t in tasks_svc.list_tasks(db)
        if tasks_svc.has_missed_marker(t, now) and t.planned_for != today
    ]
    combined = planned + sorted(fallback, key=lambda t: t.status_changed_at)
    oscar_rows = [t for t in combined if t.owner == TaskOwner.oscar]
    delegated_rows = tasks_svc.delegated(db)
    return oscar_rows, delegated_rows
