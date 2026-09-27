"""Shared template setup and view-model helpers for the server-rendered UI."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from sqlalchemy import select
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


TASK_ROW = re.compile(r"^- \[[ xX]\] ")


def notepad_ctx(db: Session, day: date) -> dict[str, Any]:
    """A day's notepad as the page shows it: the text with each task row's
    "- [ ] " made a tab (the page draws its checkbox in the gap, outside
    the text; the task's other rows are tabbed in the same way),
    the task rows ([{row, done, id}], id when the row made a task, done as
    that task stands now, wherever it was ticked), and the page's version.
    A page written when it still held task boxes reads back with them as
    task rows."""
    lines: list[str] = []
    links: dict[int, int] = {}
    for block in notebook_svc.blocks_of(db, day):
        if block["kind"] == "task":
            task = block["task"]
            title = task.title if task else block["last_known"].get("title", "")
            if title:
                if task:
                    links[len(lines)] = task.id
                lines.append(f"- [ ] {title}")
            continue
        start = len(lines)
        lines.extend(block["text"].split("\n"))
        for row, task_id in (block.get("links") or {}).items():
            links[start + int(row)] = task_id
    tasks = {t.id: t for t in db.scalars(select(Task).where(Task.id.in_(links.values())))}
    for row, task_id in list(links.items()):
        task = tasks.get(task_id)
        if task is None or not TASK_ROW.match(lines[row]):
            del links[row]
            continue
    task_rows = []
    for row, line in enumerate(lines):
        mark = TASK_ROW.match(line)
        if not mark:
            continue
        task = tasks.get(links.get(row))
        done = task.status == TaskStatus.done if task else mark[0][3] in "xX"
        task_rows.append({"row": row, "done": done, "id": task.id if task else None})
        lines[row] = "\t" + line[mark.end():]
    return {
        "text": "\n".join(lines),
        "task_rows": task_rows,
        "version": notebook_svc.version_of(db, day),
    }


def day_page_ctx(db: Session, day: date, now: datetime) -> dict[str, Any]:
    """A day's page: its notepad beside its timeline."""
    return {
        "day": day,
        "is_today": day == now.date(),
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
        "notepad": notepad_ctx(db, day),
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
