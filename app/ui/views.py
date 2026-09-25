"""Shared template setup and view-model helpers for the server-rendered UI."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import checklist
from app.dates import human_date, short_date
from app.models import (
    Block,
    BlockState,
    Milestone,
    MilestoneStatus,
    Project,
    ProjectStatus,
    Task,
    TaskOwner,
    TaskStatus,
)
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

CHIPS = {
    TaskStatus.todo: ("Queued", "queued"),
    TaskStatus.in_progress: ("Running", "running"),
    TaskStatus.needs_review: ("Needs review", "needs_review"),
    TaskStatus.blocked: ("Blocked", "blocked"),
}

DUE_SOON_DAYS = 3


STATIC_DIR = TEMPLATES_DIR.parent / "static"


def asset(path: str) -> str:
    """Static URL carrying the file's mtime, so a browser never pairs fresh
    templates with a stale cached stylesheet or script."""
    return f"/static/{path}?v={int((STATIC_DIR / path).stat().st_mtime)}"


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["human_date"] = human_date
templates.env.filters["short_date"] = short_date
templates.env.globals["asset"] = asset


def last_missed_block(task: Task) -> Block | None:
    missed = [b for b in task.blocks if b.state == BlockState.missed]
    return max(missed, key=lambda b: b.start) if missed else None


def todays_block(task: Task, today: date) -> Block | None:
    """The first of today's non-missed blocks, if the task has time today."""
    todays = [
        b for b in task.blocks if b.start.date() == today and b.state != BlockState.missed
    ]
    return min(todays, key=lambda b: b.start) if todays else None


def description_blocks(notes: str) -> list[dict[str, Any]]:
    """The description as the row renders it: runs of context lines become
    paragraphs, runs of sub-tasks become checklists, blank lines separate.
    An indented line right under a sub-task is that sub-task's note, hung
    under its words rather than starting a paragraph of its own."""
    blocks: list[dict[str, Any]] = []
    for line in checklist.parse(notes):
        last = blocks[-1] if blocks else None
        if line.kind == "blank":
            blocks.append({"kind": "gap"})
        elif line.kind == "item":
            if last is None or last["kind"] != "list":
                last = {"kind": "list", "entries": []}
                blocks.append(last)
            last["entries"].append({"item": line, "notes": []})
        elif last is not None and last["kind"] == "list" and line.text[:1] in (" ", "\t"):
            last["entries"][-1]["notes"].append(line.text.strip())
        else:
            if last is None or last["kind"] != "text":
                last = {"kind": "text", "lines": []}
                blocks.append(last)
            last["lines"].append(line.text)
    # A gap only separates: never lead, trail, or double up.
    return [
        b
        for i, b in enumerate(blocks)
        if b["kind"] != "gap" or (0 < i < len(blocks) - 1 and blocks[i + 1]["kind"] != "gap")
    ]


def row_ctx(task: Task, now: datetime) -> dict[str, Any]:
    """Everything the task-row partial needs, precomputed."""
    missed = tasks_svc.has_missed_marker(task, now)
    missed_block = last_missed_block(task) if missed else None
    today = now.date()
    block = todays_block(task, today)
    subtasks_done, subtasks_total = checklist.progress(task.notes)
    return {
        "description": description_blocks(task.notes),
        "subtasks_done": subtasks_done,
        "subtasks_total": subtasks_total,
        "block_label": f"{block.start:%H:%M}–{block.end:%H:%M}" if block else None,
        # Today's list is today by definition; everywhere else the do-date matters.
        "planned_label": (
            short_date(task.planned_for, today)
            if task.planned_for and task.planned_for != today
            else None
        ),
        "task": task,
        "done": task.status == TaskStatus.done,
        # The Tasks page's quick do-date buttons.
        "plan_today": today,
        "plan_tomorrow": today + timedelta(days=1),
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


PLAN_GROUPS = (
    ("overdue", "Overdue"),
    ("nodate", "No date"),
    ("today", "Today"),
    ("tomorrow", "Tomorrow"),
    ("week", "Later this week"),
    ("nextweek", "Next week"),
    ("later", "Later"),
)


def plan_group(planned_for: date | None, today: date) -> str:
    if planned_for is None:
        return "nodate"
    if planned_for < today:
        return "overdue"
    if planned_for == today:
        return "today"
    if planned_for == today + timedelta(days=1):
        return "tomorrow"
    sunday = today + timedelta(days=6 - today.weekday())
    if planned_for <= sunday:
        return "week"
    if planned_for <= sunday + timedelta(days=7):
        return "nextweek"
    return "later"


def tasks_page_ctx(db: Session, now: datetime) -> dict[str, Any]:
    """The Tasks page: Oscar's open tasks grouped by do-date, for giving
    them days. No date is always shown, since that is where triage happens;
    the other groups only when they hold something."""
    today = now.date()
    grouped: dict[str, list[Task]] = {key: [] for key, _ in PLAN_GROUPS}
    for task in tasks_svc.planning_list(db, today):
        grouped[plan_group(task.planned_for, today)].append(task)
    # Undated: deadlines first, soonest first, then the newest captures.
    grouped["nodate"].sort(
        key=lambda t: (t.due or date.max, -t.created_at.timestamp())
    )
    for key, tasks in grouped.items():
        if key != "nodate":
            tasks.sort(key=lambda t: (t.planned_for, t.created_at))

    groups = []
    for key, label in PLAN_GROUPS:
        if not grouped[key] and key != "nodate":
            continue
        rows = [row_ctx(t, now) for t in grouped[key]]
        if key in ("today", "tomorrow"):
            for row in rows:
                row["planned_label"] = None  # the group already says so
        groups.append({"key": key, "label": label, "rows": rows})
    return {
        "groups": groups,
        "open_count": sum(len(tasks) for tasks in grouped.values()),
        "undated_count": len(grouped["nodate"]),
    }


def milestone_ctx(db: Session, milestone: Milestone, today: date) -> dict[str, Any]:
    return {
        "milestone": milestone,
        "progress": projects_svc.milestone_progress(db, milestone.id),
        "target_label": short_date(milestone.target_date, today) if milestone.target_date else None,
        "target_soon": bool(
            milestone.target_date
            and milestone.status == MilestoneStatus.open
            and milestone.target_date <= today + timedelta(days=DUE_SOON_DAYS)
        ),
    }


def _plan_order(task: Task) -> tuple:
    """Soonest first: do-date, then deadline, then oldest undated."""
    return (task.planned_for or date.max, task.due or date.max, task.created_at)


def project_card_ctx(db: Session, project: Project, now: datetime) -> dict[str, Any]:
    """A project card: its milestones, each with its open tasks, then the rest."""
    today = now.date()
    open_tasks = sorted(
        (
            t
            for t in tasks_svc.list_tasks(db, project_id=project.id)
            if t.status in tasks_svc.OPEN_STATUSES
        ),
        key=_plan_order,
    )
    groups = [
        {
            "m": milestone_ctx(db, m, today),
            "rows": [row_ctx(t, now) for t in open_tasks if t.milestone_id == m.id],
        }
        for m in project.milestones
        if m.status != MilestoneStatus.dropped
    ]
    return {
        "project": project,
        "groups": groups,
        "loose_rows": [row_ctx(t, now) for t in open_tasks if t.milestone_id is None],
        "open_count": len(open_tasks),
    }


def projects_list_ctx(db: Session, now: datetime) -> dict[str, Any]:
    """Project cards split by status: active up front, paused and done shelved."""
    cards: dict[str, list[dict[str, Any]]] = {s.value: [] for s in ProjectStatus}
    for project in projects_svc.list_projects(db):
        cards[project.status.value].append(project_card_ctx(db, project, now))
    return cards


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
