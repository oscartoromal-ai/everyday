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
from app.dates import duration_label, human_date, short_date, upper_first, week_label
from app.models import (
    Block,
    BlockState,
    GarminDay,
    Project,
    ProjectStatus,
    Task,
    TaskOwner,
    TaskStatus,
    Workstream,
    WorkstreamStatus,
)
from app.services import blocks as blocks_svc
from app.services import events as events_svc
from app.services import garmin as garmin_svc
from app.services import habits as habits_svc
from app.services import health as health_svc
from app.services import notebook as notebook_svc
from app.services import projects as projects_svc
from app.services import recurrence as recurrence_svc
from app.services import tasks as tasks_svc
from app.ui.calendar_view import DAY_END_HOUR, DAY_START_HOUR, link_host

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
templates.env.filters["duration"] = duration_label
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


def focus_ctx(db: Session, now: datetime) -> dict[str, Any] | None:
    """Today's focus: the planned block running now, and how long is left in
    it; else the next one today, and how long until it; None for neither."""
    day_end = datetime.combine(now.date(), time.max)
    planned = db.scalars(
        select(Block)
        .where(Block.state == BlockState.planned, Block.end > now, Block.start <= day_end)
        .order_by(Block.start)
    ).all()
    if not planned:
        return None
    block = planned[0]

    def span(delta: timedelta) -> str:
        return duration_label(max(1, round(delta.total_seconds() / 60)))

    if block.start <= now:
        return {"block": block, "now": True, "left": span(block.end - now)}
    return {"block": block, "now": False, "until": span(block.start - now)}


def focus_card_ctx(db: Session, now: datetime) -> dict[str, Any]:
    """The focus card's context (partials/focus_card.html): the focus, and
    while a block runs, its task's sub-tasks as a block's menu has them."""
    focus = focus_ctx(db, now)
    row = row_ctx(focus["block"].task, now) if focus and focus["now"] else None
    return {"focus": focus, "row": row}


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


def next_slot_in(
    db: Session, duration: timedelta, first_day: date, day_count: int, now: datetime
) -> datetime | None:
    """The next free stretch this long in the usual hours of the days from
    `first_day`, the earliest first and none in the past; None when they have
    no room left."""
    for i in range(day_count):
        day = first_day + timedelta(days=i)
        start = datetime.combine(day, time(DAY_START_HOUR))
        until = datetime.combine(day, time(DAY_END_HOUR))
        if until <= now:
            continue
        slot = blocks_svc.next_free_slot(db, duration=duration, after=max(now, start), until=until)
        if slot is not None:
            return slot
    return None


def replan_slot(task: Task, now: datetime) -> datetime | None:
    """Where a missed task's time would go if replanned now: the next free
    stretch of today's calendar as long as its last missed block, or None when
    today has no room left (the row then offers tomorrow instead)."""
    missed_block = last_missed_block(task)
    db = object_session(task)
    if missed_block is None or db is None:
        return None
    return next_slot_today(db, missed_block.end - missed_block.start, now)


def project_choices(
    db: Session, project_id: int | None = None, workstream_id: int | None = None
) -> list[dict[str, Any]]:
    """The projects a task can be filed into, as the sheet's project menu
    lists them: open ones with their open workstreams, plus the task's own
    project and workstream if those have closed."""
    return [
        {
            "id": p.id,
            "name": p.name,
            "color": p.color,
            "workstreams": [
                {"id": m.id, "name": m.name}
                for m in p.workstreams
                if m.status == WorkstreamStatus.open or m.id == workstream_id
            ],
        }
        for p in projects_svc.list_projects(db)
        if p.status != ProjectStatus.done or p.id == project_id
    ]


def sheet_ctx(db: Session, task: Task, today: date) -> dict[str, Any]:
    """The task sheet in edit mode (partials/task_sheet.html): the task's
    fields as form values, their labels, and the projects it could file into
    (open ones, plus its own if that has closed)."""
    template = task.recurrence_template
    repeat = recurrence_svc.preset_of(template) if template and template.active else "none"
    projects = project_choices(db, task.project_id, task.workstream_id)
    block = blocks_svc.day_block(task, task.planned_for) if task.planned_for else None
    project_label = ""
    if task.project:
        project_label = task.project.name
        if task.workstream:
            project_label += f" › {task.workstream.name}"
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
        "workstream_id": task.workstream_id or "",
        "planned_label": short_date(task.planned_for, today) if task.planned_for else "",
        "due_label": short_date(task.due, today) if task.due else "",
        # Its time on its do-date, as the sheet's time field writes it.
        "time": f"{block.start:%H:%M}-{block.end:%H:%M}" if block else "",
        "time_label": f"{block.start:%H:%M}–{block.end:%H:%M}" if block else "",
        # How long it is thought to take, in minutes, as the sheet's field holds it.
        "estimate": task.estimate_minutes or "",
        "estimate_label": duration_label(task.estimate_minutes) if task.estimate_minutes else "",
        "project_label": project_label,
        "project_color": task.project.color if task.project else None,
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
        # Its estimate, while it has no time to say how long it takes.
        "estimate_label": (
            duration_label(task.estimate_minutes) if task.estimate_minutes and not block else None
        ),
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
        "project": task.project,
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


def workstream_ctx(db: Session, workstream: Workstream) -> dict[str, Any]:
    return {
        "workstream": workstream,
        "done": workstream.status == WorkstreamStatus.done,
        "progress": projects_svc.workstream_progress(db, workstream.id),
    }


def _plan_order(task: Task) -> tuple:
    """Soonest first: do-date, then deadline, then oldest undated."""
    return (task.planned_for or date.max, task.due or date.max, task.created_at)


def project_card_ctx(
    db: Session, project: Project, now: datetime, *, planning: bool = False
) -> dict[str, Any]:
    """A project card: its workstreams, each with its open tasks, then the rest."""
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
            "m": workstream_ctx(db, m),
            "rows": [
                row_ctx(t, now, planning=planning) for t in open_tasks if t.workstream_id == m.id
            ],
        }
        for m in project.workstreams
    ]
    return {
        "project": project,
        "groups": groups,
        "loose_rows": [
            row_ctx(t, now, planning=planning) for t in open_tasks if t.workstream_id is None
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
# What starts a habit's row: "/habit name" when done, "/habit [ ] name" when
# its box is unticked (the notepad saves it as a habit block).
HABIT = "/habit"
# A task's fields as the sheet posts them (fragments.save_task).
TASK_FIELDS = (
    "planned_for", "time", "due", "repeat", "project_id", "workstream_id", "status", "owner",
    "estimate",
)


def notepad_ctx(db: Session, day: date) -> dict[str, Any]:
    """A day's notepad as the page shows it: the text, each task row's box
    ("- [ ] " or "- [x] ") as its task stands now, wherever it was ticked;
    the task rows ([{row, done, id, fields}], id and fields when the row made
    a task); the projects its controls offer; and the page's version. A page
    written when it still held task boxes reads back with them as task
    rows."""
    lines: list[str] = []
    links: dict[int, int] = {}
    folded: set[int] = set()  # task rows shown folded to their title
    for block in notebook_svc.blocks_of(db, day):
        if block["kind"] == "task":
            task = block["task"]
            title = task.title if task else block["last_known"].get("title", "")
            if title:
                if task:
                    links[len(lines)] = task.id
                lines.append(f"- [ ] {title}")
            continue
        if block["kind"] in ("reflection", "stay"):
            # Written as it was: its "/reflection" (or "/stay") row, its other
            # rows tabbed in.
            first, *rest = block["text"].split("\n")
            lines.append(f"/{block['kind']} {first}".rstrip(" "))
            lines.extend(f"\t{line}" for line in rest)
            continue
        if block["kind"] == "habit":
            # Its row, its box as written, its name, then its note.
            first, *rest = block["text"].split("\n")
            box = "" if block["done"] else "[ ] "
            lines.append(f"{HABIT} {box}{block['slug']} {first}".rstrip(" "))
            lines.extend(f"\t{line}" for line in rest)
            continue
        start = len(lines)
        lines.extend(block["text"].split("\n"))
        for row, task_id in (block.get("links") or {}).items():
            links[start + int(row)] = task_id
        folded |= {start + int(row) for row in block.get("folded") or []}
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
        fields = None
        if task:
            # The fields its title row's controls show and set (the sheet's own).
            sheet = sheet_ctx(db, task, day)
            fields = {k: sheet[k] for k in TASK_FIELDS}
        task_rows.append({
            "row": row, "done": done, "id": task.id if task else None, "fields": fields,
            "folded": row in folded,
        })
        lines[row] = f"- [{'x' if done else ' '}] " + line[mark.end():]
    return {
        "text": "\n".join(lines),
        "task_rows": task_rows,
        "projects": project_choices(db),
        # Every habit and its days: for the strip of those not yet written,
        # and the names offered after "/habit ".
        "habits": [{"slug": h.slug, "days": h.days} for h in habits_svc.list_habits(db)],
        # What a stay written here starts with: the last stay's items.
        "stay_items": notebook_svc.last_stay_items(db, day),
        "version": notebook_svc.version_of(db, day),
    }


def day_tasks_ctx(db: Session, day: date, today: date) -> dict[str, Any]:
    """What a day's notepad offers to write in it (tasks.for_day): the tasks
    planned for the day or due on it, overdue ones on today's, and on today's
    also those still open from the last page before it (notebook.still_open);
    each with its words, its fields as they will stand once brought (do-date
    this day, and so no time yet unless it had one on it), and its due."""
    tasks = tasks_svc.for_day(db, day, today)
    if day == today:
        _, still_open = notebook_svc.still_open(db, day)
        tasks += [t for t in still_open if t not in tasks]
    out = []
    for task in tasks:
        sheet = sheet_ctx(db, task, day)
        fields = {k: sheet[k] for k in TASK_FIELDS}
        moves = task.planned_for != day
        if moves:
            fields |= {"planned_for": day.isoformat(), "time": ""}
        out.append({
            "id": task.id, "title": task.title, "notes": task.notes or "",
            "fields": fields, "moves": moves,
            "due": f"due {short_date(task.due, today)}" if task.due else "",
        })
    return {"label": f"For {short_date(day, today)}", "tasks": out}


# Garmin's readiness levels that ask for a light day.
LIGHT_READINESS = ("POOR", "LOW")


def _figure(label: str, value: str, detail: str = "", over: bool = False) -> dict[str, Any]:
    return {"label": label, "value": value, "detail": detail, "over": over}


def _body_figures(measured: GarminDay) -> list[dict[str, Any]]:
    """How Oscar came into a day, as his watch measured it."""
    out = []
    if measured.readiness is not None:
        level = (measured.readiness_level or "").lower()
        # Garmin's low readiness asks for a light day, and says so.
        light = measured.readiness_level in LIGHT_READINESS
        detail = f"{level}, keep the day light" if light else level
        out.append(_figure("Readiness", str(measured.readiness), detail, over=light))
    if measured.sleep_seconds:
        score = measured.sleep_score
        detail = f"score {score}" if score is not None else ""
        out.append(_figure("Sleep", duration_label(measured.sleep_seconds // 60), detail))
    if measured.body_battery_high is not None:
        out.append(_figure("Body battery", str(measured.body_battery_high)))
    return out


def _calendar_entry(start: datetime, end: datetime, title: str, location: str, now: datetime,
                    *, on_now: bool) -> dict[str, Any]:
    """An event on the glance: on now (till its end), or next (in how
    long), with its meeting link to join."""
    link = location if location.startswith(("http://", "https://")) else ""
    wait = max(1, int((start - now).total_seconds() // 60))
    return {
        "title": title, "now": on_now, "span": f"{start:%H:%M}–{end:%H:%M}",
        "when": f"till {end:%H:%M}" if on_now else f"in {duration_label(wait)}",
        "link": link, "link_host": link_host(link),
    }


def day_glance_ctx(db: Session, day: date, now: datetime) -> dict[str, Any]:
    """A day's glance, under its date: on today's, the events on now and
    next; and how Oscar came into the day (his watch's readiness,
    sleep and body battery). Whether the day's plan fits it is the
    timeline's to say (calendar_view.day_load)."""
    measured = garmin_svc.day(db, day)
    ctx: dict[str, Any] = {
        "live": day == now.date(),
        "body": _body_figures(measured) if measured else [],
        "on": [],
    }
    if not ctx["live"]:
        return ctx

    # The day's timed events, a cancelled one passed over; the task blocks
    # are the focus card's, over the timeline.
    midnight = datetime.combine(day, time.min)
    events, _ = events_svc.calendar_range(db, midnight, midnight + timedelta(days=1))
    items = sorted(
        (e.start, e.end, e.shown_title, e.location.strip())
        for e in events if not e.all_day and not e.cancelled
    )

    current = [i for i in items if i[0] <= now < i[1]]
    upcoming = [i for i in items if now < i[0] and i[0].date() == day]
    if current:  # the one begun last
        ctx["on"].append(_calendar_entry(*current[-1], now, on_now=True))
    if upcoming:
        ctx["on"].append(_calendar_entry(*upcoming[0], now, on_now=False))
    return ctx


def day_page_ctx(db: Session, day: date, now: datetime) -> dict[str, Any]:
    """A day's page: its notepad beside its timeline, under a glance at the
    day, and the day's tasks, offered to write in the notes."""
    is_today = day == now.date()
    return {
        "day": day,
        "is_today": is_today,
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
        "notepad": notepad_ctx(db, day),
        "day_tasks": day_tasks_ctx(db, day, now.date()),
        "glance": day_glance_ctx(db, day, now),
        # Drawn with the page, so the timeline is laid out at its height from the start.
        "focus_card": focus_card_ctx(db, now) if is_today else None,
    }


HISTORY_FIELDS = {
    "title": "Title",
    "notes": "Description",
    "status": "Status",
    "owner": "Owner",
    "project_id": "Project",
    "workstream_id": "Workstream",
    "planned_for": "Do date",
    "due": "Due",
    "starts_on": "Start week",
    "estimate_minutes": "Estimate",
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
    if field == "starts_on":
        start = date.fromisoformat(value)
        return f"{short_date(start, today)} ({week_label(start, today)})"
    if field == "estimate_minutes":
        return duration_label(int(value))
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
        when = f"{upper_first(short_date(at.date(), today))} {at:%H:%M}"
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


SEX_WORDS = {"female": "Female", "male": "Male"}
ACTIVITY_WORDS = {
    "sedentary": "Sedentary: little or no exercise",
    "light": "Light: exercise 1 to 3 days a week",
    "moderate": "Moderate: exercise 3 to 5 days a week",
    "active": "Active: exercise 6 to 7 days a week",
    "very_active": "Very active: hard exercise daily, or a physical job",
}
GOAL_WORDS = {"lose": "Lose weight", "maintain": "Keep my weight", "gain": "Gain weight"}


def me_ctx(db: Session, today: date) -> dict[str, Any]:
    """Health > Me: the profile (health.context) with its choices in words,
    and what the daily energy estimate still needs, in words."""
    me = health_svc.context(db, today)
    needs = [
        word for word, have in (
            ("your weight", me["weight_kg"]), ("height", me["height_cm"]),
            ("birth date", me["birth_date"]), ("sex", me["sex"]), ("activity", me["activity"]),
        ) if not have
    ]
    return {
        "me": me,
        "energy_needs": needs,
        "sex_words": SEX_WORDS,
        "activity_words": ACTIVITY_WORDS,
        "goal_words": GOAL_WORDS,
        "today": today,
    }
