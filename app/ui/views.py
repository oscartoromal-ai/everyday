"""Shared template setup and view-model helpers for the server-rendered UI."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import changelog, checklist
from app.config import get_settings
from app.dates import duration_label, human_date, monday, short_date, upper_first, week_label
from app.db import DbSession
from app.markdown import render_note
from app.models import (
    GarminDay,
    Project,
    ProjectStatus,
    Task,
    TaskOwner,
    TaskPriority,
    TaskStatus,
    Workstream,
    WorkstreamStatus,
)
from app.services import events as events_svc
from app.services import garmin as garmin_svc
from app.services import habits as habits_svc
from app.services import health as health_svc
from app.services import keys as keys_svc
from app.services import notebook as notebook_svc
from app.services import projects as projects_svc
from app.services import rail as rail_svc
from app.services import recurrence as recurrence_svc
from app.services import tasks as tasks_svc
from app.ui.agent_window_view import window_ctx
from app.ui.calendar_view import link_host

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

CHIPS = {
    TaskStatus.todo: ("Queued", "queued"),
    TaskStatus.in_progress: ("Running", "running"),
    TaskStatus.needs_review: ("Needs review", "needs_review"),
    TaskStatus.blocked: ("Blocked", "blocked"),
}


STATIC_DIR = TEMPLATES_DIR.parent / "static"


def asset(path: str) -> str:
    """Static URL carrying the file's mtime, so a browser never pairs fresh
    templates with a stale cached stylesheet or script."""
    return f"/static/{path}?v={int((STATIC_DIR / path).stat().st_mtime)}"


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["human_date"] = human_date
templates.env.filters["short_date"] = short_date
templates.env.filters["duration"] = duration_label
templates.env.filters["upper_first"] = upper_first
# A line of a task's description, or a sub-task's words, as Markdown.
templates.env.filters["note"] = lambda text: Markup(render_note(text))
templates.env.globals["asset"] = asset


def design_system() -> dict[str, Any]:
    """The design system installed in static/design by the design-language
    tool: its name, mode names and fonts to preload (design-language.json).
    Read per render, so switching systems needs no restart."""
    return json.loads((STATIC_DIR / "design" / "design-language.json").read_text(encoding="utf-8"))


templates.env.globals["design"] = design_system
# The installed app's Update button (app/desktop/update.py), which sets its
# own; a run from the repo has nothing to update.
templates.env.globals["app_update"] = lambda: None
# Whether Settings offers Check for updates: only the installed app updates.
templates.env.globals["app_updatable"] = lambda: False
# The app's version, in Settings (app/changelog.py).
templates.env.globals["app_version"] = lambda: changelog.running()


def keep_db(request: Request, db: DbSession) -> None:
    """The UI's routes keep their request's session where every page's
    sidebar finds it (rail_projects); the route shares the same session."""
    request.state.db = db


def rail_projects(request: Request) -> list[Project]:
    """The active projects, in Projects' order, listed under Projects in
    the sidebar. None for a page rendered outside a UI route."""
    db = getattr(request.state, "db", None)
    return [] if db is None else projects_svc.list_projects(db, status=ProjectStatus.active)


templates.env.globals["rail_projects"] = rail_projects


def capture_projects(request: Request) -> list[dict[str, Any]]:
    """The projects a task written in the New task window can be filed
    into, with their workstreams (the sheet's project menu). None for a page
    rendered outside a UI route."""
    db = getattr(request.state, "db", None)
    return [] if db is None else project_choices(db)


templates.env.globals["capture_projects"] = capture_projects


def rail_layout(request: Request) -> list[rail_svc.PlacedSection]:
    """The sidebar's sections and modules, as Oscar laid them out."""
    return rail_svc.layout(getattr(request.state, "db", None))


templates.env.globals["rail_layout"] = rail_layout


def llm_summary(request: Request) -> list[dict[str, str]]:
    """Each model provider in a word, for Settings (app/ui/models_view.py)."""
    from app.ui.models_view import summary

    return summary(getattr(request.state, "db", None))


templates.env.globals["llm_summary"] = llm_summary


def agent_window(request: Request) -> dict[str, Any] | None:
    """The agent window beside every page (agent_window_view). None for a
    page rendered outside a UI route."""
    db = getattr(request.state, "db", None)
    return None if db is None else window_ctx(db)


templates.env.globals["agent_window"] = agent_window
# The modules this machine has, for what a page shows of the optional ones.
templates.env.globals["installed"] = lambda module: get_settings().installed(module)
templates.env.globals["not_installed"] = rail_svc.not_installed
# The keys in use (app/services/keys.py): their key caps and titles in the
# pages, the keys dialog (?), and every action's keys for keys.js.
templates.env.globals["keys"] = keys_svc.current
templates.env.globals["keys_scopes"] = keys_svc.SCOPES
templates.env.globals["keys_client"] = lambda: keys_svc.client_map(keys_svc.load())
templates.env.filters["key_caps"] = keys_svc.fixed_keys
templates.env.filters["with_caps"] = keys_svc.with_caps
templates.env.filters["key_cap"] = keys_svc.caps
templates.env.filters["key_text"] = keys_svc.text


_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def description_blocks(notes: str) -> list[dict[str, Any]]:
    """The description as the row renders it: runs of context lines become
    paragraphs, runs of sub-tasks become checklists, blank lines separate.
    An indented line right under a sub-task is that sub-task's note, hung
    under its words rather than starting a paragraph of its own. A fenced
    block ("```" to "```") is code, its lines as written."""
    blocks: list[dict[str, Any]] = []
    fence: str | None = None  # the open fence's marks, while in a fenced block
    for raw, line in zip(notes.split("\n"), checklist.parse(notes), strict=True):
        last = blocks[-1] if blocks else None
        if fence is not None:
            if re.fullmatch(rf"[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", raw):
                fence = None
            else:
                last["lines"].append(raw)
        elif opens := _FENCE.match(raw):
            fence = opens[1]
            blocks.append({"kind": "code", "lines": []})
        elif line.kind == "blank":
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
        # How long it is thought to take, in minutes, as the sheet's field holds it.
        "estimate": task.estimate_minutes or "",
        "estimate_label": duration_label(task.estimate_minutes) if task.estimate_minutes else "",
        "priority": task.priority.value if task.priority else "",
        "priority_label": task.priority.label if task.priority else "",
        "project_label": project_label,
        "project_color": task.project.color if task.project else None,
        "projects": projects,
    }


def row_ctx(task: Task, now: datetime) -> dict[str, Any]:
    """Everything the task-row partial needs, precomputed. A row always
    names its do-date, today included, and carries the quick do-date
    buttons: giving tasks days is what a project's Tasks and Plan are for."""
    today = now.date()
    subtasks_done, subtasks_total = checklist.progress(task.notes)
    return {
        "description": description_blocks(task.notes),
        "subtasks_done": subtasks_done,
        "subtasks_total": subtasks_total,
        "estimate_label": (
            duration_label(task.estimate_minutes) if task.estimate_minutes else None
        ),
        "priority": task.priority.value if task.priority else None,
        "priority_label": task.priority.label if task.priority else None,
        "planned_label": short_date(task.planned_for, today) if task.planned_for else None,
        "task": task,
        "done": task.status == TaskStatus.done,
        # The quick do-date buttons.
        "plan_today": today,
        "plan_tomorrow": today + timedelta(days=1),
        "chip": (
            CHIPS[task.status][0]
            if task.owner == TaskOwner.claude and task.status in CHIPS
            else None
        ),
        "chip_class": CHIPS[task.status][1] if task.status in CHIPS else "",
        "due_label": f"due {short_date(task.due, today)}" if task.due else None,
        "due_soon": bool(
            task.due and task.due <= today + timedelta(days=tasks_svc.DUE_SOON_DAYS)
        ),
        "project": task.project,
    }


DONE_DAYS = 14
TIMELINE_WEEKS = 16


def projects_page_ctx(db: Session, now: datetime) -> dict[str, Any]:
    """Projects, an overview: what needs attention, then the active projects
    over the weeks they share, the paused and done ones after. Their tasks
    are planned on each project's Tasks tab, and those without a day on
    Plan."""
    today = now.date()
    planning = tasks_svc.planning_list(db, today)
    projects = projects_svc.list_projects(db)
    active = [p for p in projects if p.status == ProjectStatus.active]
    return {
        "active_count": len(active),
        "open_count": len(planning),
        "undated_count": sum(1 for t in planning if t.planned_for is None),
        "attention": attention_rows(db, today),
        "timeline": projects_timeline(db, active, today),
        "paused": [p for p in projects if p.status == ProjectStatus.paused],
        "done_projects": [p for p in projects if p.status == ProjectStatus.done],
    }


def attention_rows(db: Session, today: date) -> list[dict[str, Any]]:
    """What needs attention: open tasks overdue or due soon, the soonest
    first, then Claude's work waiting for review; none of a project paused
    or done."""
    open_tasks = [
        t
        for t in tasks_svc.one_per_series(
            [t for t in tasks_svc.list_tasks(db) if t.status in tasks_svc.OPEN_STATUSES], today
        )
        if t.project is None or t.project.status == ProjectStatus.active
    ]
    soon = today + timedelta(days=tasks_svc.DUE_SOON_DAYS)
    due = sorted(
        (t for t in open_tasks if t.due and t.due <= soon),
        key=lambda t: (t.due, tasks_svc.priority_rank(t), t.id),
    )
    rows = [
        {
            "task": t,
            "chip": ("Overdue", "err") if t.due < today else ("Due soon", "warn"),
            "day": upper_first(short_date(t.due, today)),
        }
        for t in due
    ]
    rows += [
        {"task": t, "chip": ("Needs review", "needs_review"), "day": ""}
        for t in open_tasks
        if t.owner == TaskOwner.claude and t.status == TaskStatus.needs_review and t not in due
    ]
    return rows


def projects_timeline(db: Session, projects: list[Project], today: date) -> dict[str, Any] | None:
    """The projects over the weeks they share, from last week's Monday on:
    each one's span (its tasks' first start to their last due) with what
    is done of it, its open tasks' deadlines, and under it its workstreams
    with work still open, each its own span. None with no project."""
    if not projects:
        return None
    start = monday(today) - timedelta(weeks=1)
    end = start + timedelta(weeks=TIMELINE_WEEKS)
    length = (end - start).days

    def at(day: date) -> float:
        """A day's place in the weeks, in percent of their width, kept in them."""
        return round(100 * min(max((day - start).days, 0), length) / length, 3)

    def bar(first: date | None, last: date | None) -> dict[str, float] | None:
        if not first or not last or last < start or first >= end:
            return None
        left = at(first)
        return {"left": left, "width": round(at(last + timedelta(days=1)) - left, 3)}

    rows = []
    for project in projects:
        glance = project_glance(db, project, today)
        streams, finished = [], 0
        for workstream in project.workstreams:
            done, total = projects_svc.workstream_progress(db, workstream.id)
            if workstream.status == WorkstreamStatus.done or (total and done == total):
                finished += 1
                continue
            days = [
                d
                for t in workstream.tasks
                if t.status != TaskStatus.cancelled
                for d in (t.starts_on, t.due)
                if d
            ]
            first, last = (min(days), max(days)) if days else (None, None)
            streams.append({
                "workstream": workstream,
                "done": done,
                "total": total,
                "percent": round(100 * done / total) if total else 0,
                "bar": bar(first, last),
                "span_label": human_span(first, last, today) if days else "No dates yet",
            })
        marks = [
            {
                "left": at(t.due),
                "label": f"{t.title}, due {short_date(t.due, today)}",
                "overdue": t.due < today,
            }
            for t in glance["deadlines"]
            if start <= t.due < end
        ]
        rows.append({
            **glance,
            "bar": bar(glance["first"], glance["last"]),
            "streams": streams,
            "finished": finished,
            "marks": marks,
        })
    weeks = []
    for i in range(TIMELINE_WEEKS):
        day = start + timedelta(weeks=i)
        # A month is named on its first week, and on the first column.
        month = day.strftime("%b") if i == 0 or day.day <= 7 else ""
        weeks.append({"left": round(100 * i / TIMELINE_WEEKS, 3), "day": day.day, "month": month})
    return {
        "rows": rows,
        "weeks": weeks,
        "count": TIMELINE_WEEKS,
        "now": round(100 * ((today - start).days + 0.5) / length, 3),
    }


def project_glance(db: Session, project: Project, today: date) -> dict[str, Any]:
    """A project at a glance: its health (what its deadlines say), its
    progress, its deadlines, the next first, and its span, its tasks'
    first start to their last due. Projects' timeline and its own page
    show it."""
    tasks = [
        t for t in tasks_svc.list_tasks(db, project_id=project.id)
        if t.status != TaskStatus.cancelled
    ]
    open_tasks = tasks_svc.one_per_series(
        [t for t in tasks if t.status in tasks_svc.OPEN_STATUSES], today
    )
    done = sum(1 for t in tasks if t.status == TaskStatus.done)
    total = done + len(open_tasks)
    deadlines = sorted((t for t in open_tasks if t.due), key=lambda t: t.due)
    overdue = sum(1 for t in deadlines if t.due < today)
    upcoming = deadlines[0] if deadlines else None
    if project.status == ProjectStatus.paused:
        health = ("Paused", "neutral")
    elif project.status == ProjectStatus.done:
        health = ("Done", "neutral")
    elif overdue:
        health = (f"{overdue} overdue", "err")
    elif upcoming and upcoming.due <= today + timedelta(days=tasks_svc.DUE_SOON_DAYS):
        health = ("Due soon", "warn")
    elif not open_tasks:
        health = ("Nothing open", "neutral")
    elif not upcoming:
        health = ("No deadline", "neutral")
    else:
        health = ("On track", "ok")
    days = [d for t in tasks for d in (t.starts_on, t.due) if d]
    first, last = (min(days), max(days)) if days else (None, None)
    return {
        "project": project,
        "health": health[0],
        "health_class": health[1],
        "done": done,
        "open": len(open_tasks),
        "total": total,
        "percent": round(100 * done / total) if total else 0,
        "deadlines": deadlines,
        "next": upcoming,
        "next_label": upper_first(short_date(upcoming.due, today)) if upcoming else None,
        "first": first,
        "last": last,
        "span_label": human_span(first, last, today) if first and last else "No dates yet",
    }


def human_span(first: date, last: date, today: date) -> str:
    """A span as its two days ('28 Sep to 22 Nov'), the year written when
    it is not this one."""

    def day(value: date) -> str:
        text = f"{value.day} {value.strftime('%b')}"
        return text if value.year == today.year else f"{text} {value.year}"

    return day(first) if first == last else f"{day(first)} to {day(last)}"


def workstream_ctx(db: Session, workstream: Workstream) -> dict[str, Any]:
    return {
        "workstream": workstream,
        "done": workstream.status == WorkstreamStatus.done,
        "progress": projects_svc.workstream_progress(db, workstream.id),
    }


def _plan_order(task: Task) -> tuple:
    """Soonest first: do-date, then deadline, then priority, then oldest."""
    return (
        task.planned_for or date.max, task.due or date.max, tasks_svc.priority_rank(task),
        task.created_at,
    )


def project_tasks_ctx(db: Session, project: Project, now: datetime) -> dict[str, Any]:
    """A project's Tasks tab, where its tasks are planned: each workstream
    with its open tasks, then the tasks in none, the finished workstreams on
    a line, and the last two weeks' finished work folded away."""
    today = now.date()
    tasks = tasks_svc.list_tasks(db, project_id=project.id)
    open_tasks = sorted(
        tasks_svc.one_per_series([t for t in tasks if t.status in tasks_svc.OPEN_STATUSES], today),
        key=_plan_order,
    )
    groups, finished = [], []
    for workstream in project.workstreams:
        m = workstream_ctx(db, workstream)
        rows = [row_ctx(t, now) for t in open_tasks if t.workstream_id == workstream.id]
        # A finished workstream (marked done, or all its tasks done) folds to
        # its row, unless work was left open in it.
        done, total = m["progress"]
        if not rows and (m["done"] or (total and done == total)):
            finished.append(m)
        else:
            groups.append({"m": m, "rows": rows})
    since = now - timedelta(days=DONE_DAYS)
    done = sorted(
        (t for t in tasks if t.status == TaskStatus.done and t.status_changed_at >= since),
        key=lambda t: t.status_changed_at,
        reverse=True,
    )
    return {
        "groups": groups,
        "finished": finished,
        "loose_rows": [row_ctx(t, now) for t in open_tasks if t.workstream_id is None],
        "open_count": len(open_tasks),
        "done_rows": [row_ctx(t, now) for t in done],
        "done_days": DONE_DAYS,
    }


def plan_page_ctx(db: Session, now: datetime) -> dict[str, Any]:
    """Plan: Oscar's open tasks without a day, for giving them days. Those
    in no project first, then each project's, in Projects' order."""
    today = now.date()
    undated = sorted(
        (t for t in tasks_svc.planning_list(db, today) if t.planned_for is None), key=_plan_order
    )
    groups = []
    for project in projects_svc.list_projects(db):
        rows = [row_ctx(t, now) for t in undated if t.project_id == project.id]
        if rows:
            groups.append({"project": project, "rows": rows})
    return {
        "undated_count": len(undated),
        "loose_rows": [row_ctx(t, now) for t in undated if t.project_id is None],
        "groups": groups,
    }


TASK_ROW = re.compile(r"^- \[[ xX]\] ")
# What starts a habit's row: "/habit name" when done, "/habit [ ] name" when
# its box is unticked (the notepad saves it as a habit block).
HABIT = "/habit"
# A task's fields as the sheet posts them (fragments.save_task).
TASK_FIELDS = (
    "planned_for", "due", "repeat", "project_id", "workstream_id", "status", "owner", "estimate",
    "priority",
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
    this day), and its due."""
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
            fields["planned_for"] = day.isoformat()
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
    timeline's to say (calendar_view.day_load). The watch's figures are
    Health's: a machine installed without it has none."""
    measured = garmin_svc.day(db, day) if get_settings().installed("health") else None
    ctx: dict[str, Any] = {
        "live": day == now.date(),
        "body": _body_figures(measured) if measured else [],
        "on": [],
    }
    if not ctx["live"]:
        return ctx

    # The day's timed events, a cancelled one passed over.
    midnight = datetime.combine(day, time.min)
    events = events_svc.calendar_range(db, midnight, midnight + timedelta(days=1))
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
    "priority": "Priority",
    "acceptance": "Acceptance criteria",
    "outcome": "Outcome",
}
STATUS_WORDS = {
    "todo": "To do",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "needs_review": "Needs review",
    "done": "Done",
    "cancelled": "Cancelled",
}
ACTOR_WORDS = {"oscar": "Oscar", "claude": "Claude", "agent": "An agent", "system": "The planner"}


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
    if field == "priority":
        return TaskPriority(value).label
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
                elif f["field"] in ("acceptance", "outcome"):
                    lines.append(f"{name} {'written' if not f['from'] else 'edited'}")
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


# The app's pages a task's page can be opened from (the command menu opens
# one from anywhere), by their path's first part: the sidebar's, by its
# names, then Plan and those Settings opens.
_PAGE_NAMES = {
    **{module.href.strip("/"): module.label for s in rail_svc.SECTIONS for module in s.modules},
    "plan": "Plan",
    "models": "Models",
    "changelog": "Changelog",
}


def back_link(url: str, today: date | None = None) -> dict[str, str]:
    """Where a task's page goes back to: the page it was opened from (its
    path, never another site), named; Projects when that is not one of
    the app's pages, or is another task's (two tasks' pages would only lead
    back to each other)."""
    from urllib.parse import urlsplit

    parts = urlsplit(url or "")
    path = parts.path
    href = path + (f"?{parts.query}" if parts.query else "")
    segments = path.strip("/").split("/")
    label = None
    if path in ("/", "/today"):
        label = "Today"
    elif segments[0] == "projects" and segments[1:2] and segments[1].isdigit():
        # A project's page, its Tasks, its Gantt, or one of its documents.
        rest = tuple(segments[2:])
        label = {(): "Project", ("tasks",): "Tasks", ("gantt",): "Gantt"}.get(rest)
        if len(rest) == 2 and rest[0] == "docs":
            label = "Document"
    elif segments[0] in _PAGE_NAMES and (len(segments) == 1 or segments[0] != "projects"):
        # One of the app's pages, or a day or month of it (Garmin's, Spending's).
        label = _PAGE_NAMES[segments[0]]
    elif segments[0] == "day" and len(segments) == 2:
        try:
            label = upper_first(short_date(date.fromisoformat(segments[1]), today or date.today()))
        except ValueError:
            label = None
    if label is None:
        return {"href": "/projects", "label": "Projects"}
    return {"href": href, "label": label}


def task_page_ctx(db: Session, task: Task, today: date, back: str) -> dict[str, Any]:
    """A task's own page: its sheet in full, for a task too long for a row."""
    return {"sheet": sheet_ctx(db, task, today), "back": back_link(back, today)}
