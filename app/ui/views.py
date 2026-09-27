"""Shared template setup and view-model helpers for the server-rendered UI."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, object_session

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
from app.services import blocks as blocks_svc
from app.services import notebook as notebook_svc
from app.services import projects as projects_svc
from app.services import recurrence as recurrence_svc
from app.services import tasks as tasks_svc
from app.ui.calendar_view import DAY_END_HOUR, DAY_START_HOUR

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


def design_system() -> dict[str, Any]:
    """The design system installed in static/design by the design-language
    tool: its name, mode names and fonts to preload (design-language.json).
    Read per render, so switching systems needs no restart."""
    return json.loads((STATIC_DIR / "design" / "design-language.json").read_text(encoding="utf-8"))


templates.env.globals["design"] = design_system


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


def next_slot_today(db: Session, duration: timedelta, now: datetime) -> datetime | None:
    """The next free stretch of today's calendar this long, from now (or the
    grid's first hour) to the grid's last; None when today has no room left."""
    today = now.date()
    return blocks_svc.next_free_slot(
        db,
        duration=duration,
        after=max(now, datetime.combine(today, time(DAY_START_HOUR))),
        until=datetime.combine(today, time(DAY_END_HOUR)),
    )


def replan_slot(task: Task, now: datetime) -> datetime | None:
    """Where a missed task's time would go if replanned now: the next free
    stretch of today's calendar as long as its last missed block, or None when
    today has no room left (the row then offers tomorrow instead)."""
    missed_block = last_missed_block(task)
    db = object_session(task)
    if missed_block is None or db is None:
        return None
    return next_slot_today(db, missed_block.end - missed_block.start, now)


def sheet_ctx(db: Session, task: Task, today: date) -> dict[str, Any]:
    """The task sheet in edit mode (partials/task_sheet.html): the task's
    fields as form values, their labels, and the projects it could file into
    (open ones, plus its own if that has closed)."""
    template = task.recurrence_template
    repeat = recurrence_svc.preset_of(template) if template and template.active else "none"
    projects = [
        {
            "id": p.id,
            "name": p.name,
            "milestones": [
                {"id": m.id, "name": m.name}
                for m in p.milestones
                if m.status == MilestoneStatus.open or m.id == task.milestone_id
            ],
        }
        for p in projects_svc.list_projects(db)
        if p.status != ProjectStatus.done or p.id == task.project_id
    ]
    block = blocks_svc.day_block(task, task.planned_for) if task.planned_for else None
    project_label = ""
    if task.project:
        project_label = task.project.name
        if task.milestone:
            project_label += f" › {task.milestone.name}"
    return {
        "id": task.id,
        "title": task.title,
        "notes": task.notes,
        "status": task.status.value,
        "owner": task.owner.value,
        "repeat": repeat,
        "planned_for": task.planned_for.isoformat() if task.planned_for else "",
        "due": task.due.isoformat() if task.due else "",
        "project_id": task.project_id or "",
        "milestone_id": task.milestone_id or "",
        "planned_label": short_date(task.planned_for, today) if task.planned_for else "",
        "due_label": short_date(task.due, today) if task.due else "",
        # Its time on its do-date, as the sheet's time field writes it.
        "time": f"{block.start:%H:%M}-{block.end:%H:%M}" if block else "",
        "time_label": f"{block.start:%H:%M}–{block.end:%H:%M}" if block else "",
        "project_label": project_label,
        "projects": projects,
    }


def row_ctx(
    task: Task, now: datetime, *, planning: bool = False, day: date | None = None
) -> dict[str, Any]:
    """Everything the task-row partial needs, precomputed.

    `planning` rows (the Tasks page) always name their do-date, today
    included, and carry the quick do-date buttons. `day` is the day the row
    is shown under (a day page's), today by default: a do-date of that day
    goes without saying, and the time shown is the task's time then."""
    missed = tasks_svc.has_missed_marker(task, now)
    missed_block = last_missed_block(task) if missed else None
    replan = replan_slot(task, now) if missed else None
    today = now.date()
    day = day or today
    # Its time on the day it is shown under, else on its own do-date.
    block = todays_block(task, day) or (
        todays_block(task, task.planned_for) if task.planned_for else None
    )
    subtasks_done, subtasks_total = checklist.progress(task.notes)
    return {
        # The row's number in the database, as a day page's RECORD column shows it.
        "record_no": f"{task.id:03d}",
        "description": description_blocks(task.notes),
        "subtasks_done": subtasks_done,
        "subtasks_total": subtasks_total,
        "block_label": f"{block.start:%H:%M}–{block.end:%H:%M}" if block else None,
        # A day's list is that day by definition; while planning, the day always matters.
        "planned_label": (
            short_date(task.planned_for, today)
            if task.planned_for and (planning or task.planned_for != day)
            else None
        ),
        "plan_controls": planning,
        "task": task,
        "done": task.status == TaskStatus.done,
        # The Tasks page's quick do-date buttons.
        "plan_today": today,
        "plan_tomorrow": today + timedelta(days=1),
        "missed": missed,
        # One step back onto the plan: the next free slot today, else tomorrow.
        "replan_at": f"{replan:%H:%M}" if replan else None,
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
        # Written on another day's page: where to read what was written around it.
        "written_on": task.written_on if task.written_on and task.written_on != day else None,
        "written_label": (
            f"from {short_date(task.written_on, today)}"
            if task.written_on and task.written_on != day
            else None
        ),
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


DONE_DAYS = 14
TASKS_VIEWS = ("date", "project")


def tasks_page_ctx(db: Session, now: datetime, view: str) -> dict[str, Any]:
    """The Tasks page: Oscar's open tasks, for giving them days, either by
    do-date or by project, with the last two weeks' finished work folded
    away underneath."""
    today = now.date()
    planning = tasks_svc.planning_list(db, today)
    ctx: dict[str, Any] = {
        "view": view,
        "open_count": len(planning),
        "undated_count": sum(1 for t in planning if t.planned_for is None),
        "done_rows": [
            row_ctx(t, now, planning=True)
            for t in tasks_svc.recently_done(db, now - timedelta(days=DONE_DAYS))
        ],
        "done_days": DONE_DAYS,
    }
    if view == "project":
        ctx.update(_tasks_by_project(db, planning, now))
    else:
        ctx["groups"] = _tasks_by_date(planning, now)
    return ctx


def _tasks_by_date(planning: list[Task], now: datetime) -> list[dict[str, Any]]:
    """No date is always shown, since that is where triage happens; the
    other groups only when they hold something."""
    today = now.date()
    grouped: dict[str, list[Task]] = {key: [] for key, _ in PLAN_GROUPS}
    for task in planning:
        grouped[plan_group(task.planned_for, today)].append(task)
    # Undated: deadlines first, soonest first, then the newest captures.
    grouped["nodate"].sort(key=lambda t: (t.due or date.max, -t.created_at.timestamp()))
    for key, tasks in grouped.items():
        if key != "nodate":
            tasks.sort(key=lambda t: (t.planned_for, t.created_at))
    return [
        {"key": key, "label": label, "rows": [row_ctx(t, now, planning=True) for t in grouped[key]]}
        for key, label in PLAN_GROUPS
        if grouped[key] or key == "nodate"
    ]


def _tasks_by_project(db: Session, planning: list[Task], now: datetime) -> dict[str, Any]:
    """The project cards, as on Projects, for every active project and any
    parked one that still holds open work; then the tasks with no project."""
    with_open = {t.project_id for t in planning}
    projects = [
        p
        for p in projects_svc.list_projects(db)
        if p.status == ProjectStatus.active or p.id in with_open
    ]
    projects.sort(key=lambda p: p.status != ProjectStatus.active)  # stable: keeps creation order
    loose = sorted((t for t in planning if t.project_id is None), key=_plan_order)
    return {
        "project_cards": [project_card_ctx(db, p, now, planning=True) for p in projects],
        "loose_rows": [row_ctx(t, now, planning=True) for t in loose],
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


def project_card_ctx(
    db: Session, project: Project, now: datetime, *, planning: bool = False
) -> dict[str, Any]:
    """A project card: its milestones, each with its open tasks, then the rest."""
    today = now.date()
    open_tasks = sorted(
        tasks_svc.one_per_series(
            [
                t
                for t in tasks_svc.list_tasks(db, project_id=project.id)
                if t.status in tasks_svc.OPEN_STATUSES
            ],
            today,
        ),
        key=_plan_order,
    )
    groups = [
        {
            "m": milestone_ctx(db, m, today),
            "rows": [
                row_ctx(t, now, planning=planning) for t in open_tasks if t.milestone_id == m.id
            ],
        }
        for m in project.milestones
        if m.status != MilestoneStatus.dropped
    ]
    return {
        "project": project,
        "groups": groups,
        "loose_rows": [
            row_ctx(t, now, planning=planning) for t in open_tasks if t.milestone_id is None
        ],
        "open_count": len(open_tasks),
        "planning": planning,
    }


def projects_list_ctx(db: Session, now: datetime) -> dict[str, Any]:
    """Project cards split by status: active up front, paused and done shelved."""
    cards: dict[str, list[dict[str, Any]]] = {s.value: [] for s in ProjectStatus}
    for project in projects_svc.list_projects(db):
        cards[project.status.value].append(project_card_ctx(db, project, now))
    return cards


def notebook_ctx(db: Session, day: date, now: datetime) -> dict[str, Any]:
    """A day's notebook page as it renders: its blocks with every task as a
    row, and a line to write on around every box, so there is always
    somewhere to put the caret before, between and after them."""
    rendered: list[dict[str, Any]] = []
    for block in notebook_svc.blocks_of(db, day):
        if block["kind"] == "task":
            task = block["task"]
            rendered.append(
                {
                    "kind": "task",
                    "id": block["id"],
                    "row": row_ctx(task, now, day=day) if task else None,
                    "gone_title": None if task else block["last_known"].get("title", "A task"),
                }
            )
        else:
            rendered.append(block)
    spaced: list[dict[str, Any]] = []
    for block in rendered:
        if block["kind"] != "text" and (not spaced or spaced[-1]["kind"] != "text"):
            spaced.append({"kind": "text", "text": ""})
        spaced.append(block)
    if not spaced or spaced[-1]["kind"] != "text":
        spaced.append({"kind": "text", "text": ""})
    return {
        "day": day,
        "version": notebook_svc.version_of(db, day),
        "blocks": spaced,
        # A storyboard's cuts: every block but the empty lines kept around boxes.
        "cuts": sum(1 for b in spaced if b["kind"] != "text" or b["text"]),
    }


def day_page_ctx(db: Session, day: date, now: datetime) -> dict[str, Any]:
    """A day's page: its notebook, then what else is on for the day (tasks
    planned for it that were written elsewhere), and on today's, what is
    overdue and Claude's work.

    Overdue: open tasks planned before today, and tasks whose time passed
    unworked on another day (the missed marker) and are not replanned onto
    today. What the notebook holds is never listed again under it."""
    today = now.date()
    notebook = notebook_ctx(db, day, now)
    on_page = {b["id"] for b in notebook["blocks"] if b["kind"] == "task"}

    def mine(tasks: list[Task]) -> list[Task]:
        return [t for t in tasks if t.owner == TaskOwner.oscar and t.id not in on_page]

    also = mine(tasks_svc.daily_list(db, day))
    overdue: list[Task] = []
    delegated: list[Task] = []
    if day == today:
        overdue = mine(
            [
                t
                for t in tasks_svc.list_tasks(db)
                if t.status in tasks_svc.OPEN_STATUSES
                and t.planned_for != today
                and (
                    (t.planned_for is not None and t.planned_for < today)
                    or tasks_svc.has_missed_marker(t, now)
                )
            ]
        )
        overdue.sort(key=lambda t: (t.planned_for or today, t.created_at))
        delegated = tasks_svc.delegated(db)
    also_rows = [row_ctx(t, now, day=day) for t in also]
    page_tasks = [b["row"] for b in notebook["blocks"] if b["kind"] == "task" and b["row"]]
    open_count = sum(1 for r in page_tasks + also_rows if not r["done"])
    return {
        "day": day,
        "is_today": day == today,
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
        "notebook": notebook,
        # Finished work folds away under the list instead of lingering in it.
        "rows": [r for r in also_rows if not r["done"]],
        "done_rows": [r for r in also_rows if r["done"]],
        "overdue": [row_ctx(t, now, day=day) for t in overdue],
        "delegated": [row_ctx(t, now, day=day) for t in delegated],
        "open_count": open_count,
    }


HISTORY_FIELDS = {
    "title": "Title",
    "notes": "Description",
    "status": "Status",
    "owner": "Owner",
    "project_id": "Project",
    "milestone_id": "Milestone",
    "planned_for": "Do date",
    "due": "Due",
}
STATUS_WORDS = {
    "todo": "To do",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "needs_review": "Needs review",
    "done": "Done",
    "cancelled": "Cancelled",
}
ACTOR_WORDS = {"oscar": "Oscar", "claude": "Claude", "system": "The planner"}


def _ticks(before: str, after: str) -> list[str] | None:
    """When a description changed only by ticking sub-tasks, what was ticked
    ("Ticked “x”", "Unticked “y”"); None for any other edit."""
    old, new = checklist.parse(before or ""), checklist.parse(after or "")
    if len(old) != len(new):
        return None
    out = []
    for a, b in zip(old, new, strict=True):
        if (a.kind, a.text, a.depth) != (b.kind, b.text, b.depth):
            return None
        if a.checked != b.checked:
            out.append(f"{'Ticked' if b.checked else 'Unticked'} “{b.text}”")
    return out


def _history_value(field: str, value: Any, today: date) -> str:
    if value is None or value == "":
        return "none"
    if field in ("planned_for", "due"):
        return short_date(date.fromisoformat(value), today)
    if field == "status":
        return STATUS_WORDS.get(value, value)
    if field == "owner":
        return ACTOR_WORDS.get(value, value)
    return str(value)


def history_ctx(changes: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """A task's history (app.services.history.changes) in words: when, who,
    and one line per thing that changed."""
    steps = []
    for change in changes:
        at: datetime = change["at"]
        when = f"{short_date(at.date(), today).capitalize()} {at:%H:%M}"
        if change["change"] == "created":
            lines = ["Written"]
        elif change["change"] == "deleted":
            lines = ["Deleted"]
        else:
            lines = []
            for f in change["fields"]:
                name = HISTORY_FIELDS[f["field"]]
                if f["field"] == "notes":
                    ticks = _ticks(f["from"], f["to"])
                    lines += ticks if ticks else ["Description edited"]
                elif f["field"] == "title":
                    lines.append(f"Title: “{f['from']}” → “{f['to']}”")
                else:
                    lines.append(
                        f"{name}: {_history_value(f['field'], f['from'], today)}"
                        f" → {_history_value(f['field'], f['to'], today)}"
                    )
        steps.append({"when": when, "who": ACTOR_WORDS.get(change["actor"], change["actor"]),
                      "lines": lines})
    return steps
