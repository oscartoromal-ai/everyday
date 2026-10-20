"""Search across the planner for the command menu (Ctrl+K): tasks, projects,
events and the days' notes whose words hold what was typed, and the files
of projects, tasks and habits whose words do (the everyday files'
full-text index, app.services.documents)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.dates import short_date, upper_first
from app.models import Event, Habit, NotebookPage, Project, Task, TaskOwner, TaskStatus
from app.services import documents

TASK_LIMIT = 8
PROJECT_LIMIT = 4
EVENT_LIMIT = 5
NOTE_LIMIT = 5
FILE_LIMIT = 5
# Events are looked for this far either side of today.
EVENT_WINDOW = timedelta(days=120)
# A snippet starts a few words before the match, so the match shows even
# where the line is cut short, and runs on after it.
SNIPPET_BEFORE = 20
SNIPPET_AFTER = 60
# A task's box and a command at a line's start are how a line is written, not
# what it says.
MARKS = re.compile(r"^\s*(?:[-*] \[[ xX]\] |[-*] |/\w+ ?)", re.MULTILINE)


def _like(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _snippet(text: str, query: str) -> str:
    """The words around the first match, on one line, its lines' marks gone."""
    flat = " ".join(MARKS.sub("", text).split())
    at = flat.lower().find(query.lower())
    if at < 0:
        return flat[: SNIPPET_BEFORE + SNIPPET_AFTER]
    start = max(0, at - SNIPPET_BEFORE)
    if start:
        # From the start of a word.
        space = flat.find(" ", start, at)
        start = space + 1 if space >= 0 else start
    end = min(len(flat), at + len(query) + SNIPPET_AFTER)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


def _task_place(task: Task) -> dict[str, Any]:
    """Where a task found opens: the list it is planned in, the cursor on
    it (its project's Tasks; Plan, for Oscar's in no project and without a
    day), while it is open; else its own page."""
    if task.status not in (TaskStatus.done, TaskStatus.cancelled):
        if task.project_id is not None:
            return {"href": f"/projects/{task.project_id}/tasks", "cursor": True}
        if task.owner == TaskOwner.oscar and task.planned_for is None:
            return {"href": "/plan", "cursor": True}
    return {"href": f"/tasks/{task.id}", "cursor": False}


def _task_meta(task: Task, today: date) -> str:
    if task.status == TaskStatus.done:
        return "done"
    parts = []
    if task.priority:
        parts.append(task.priority.value)
    if task.planned_for:
        parts.append(short_date(task.planned_for, today))
    if task.due:
        parts.append(f"due {short_date(task.due, today)}")
    return " · ".join(parts)


def search(db: Session, query: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    query = " ".join(query.split())
    if len(query) < 2:
        return {"tasks": [], "projects": [], "events": [], "notes": [], "files": []}
    like = _like(query)
    today = now.date()

    # A task whose task.md holds the words (its acceptance criteria or
    # outcome among them), found by the files' index.
    in_files = {
        int(f["owner"].partition(":")[2])
        for f in documents.search(db, query, limit=TASK_LIMIT * 4, owners=("task:",))
        if f["name"] == documents.TASK_FILE
    }
    tasks = db.scalars(
        select(Task)
        .where(
            Task.status != TaskStatus.cancelled,
            or_(
                Task.title.ilike(like, escape="\\"),
                Task.notes.ilike(like, escape="\\"),
                Task.id.in_(in_files),
            ),
        )
        # Open work first, then what was done, the latest first.
        .order_by((Task.status == TaskStatus.done).asc(), Task.status_changed_at.desc())
        .limit(TASK_LIMIT)
    ).all()

    projects = db.scalars(
        select(Project).where(Project.name.ilike(like, escape="\\")).order_by(Project.name)
        .limit(PROJECT_LIMIT)
    ).all()

    # A series' meetings share a title: each title once, its occurrence
    # nearest to now (the next one before the last one).
    found = db.scalars(
        select(Event).where(
            Event.title.ilike(like, escape="\\"),
            Event.start >= now - EVENT_WINDOW,
            Event.start <= now + EVENT_WINDOW,
        )
    ).all()
    nearest: dict[str, Event] = {}
    for event in sorted(found, key=lambda e: (e.end < now, abs(e.start - now))):
        nearest.setdefault(event.shown_title.lower(), event)
    events = list(nearest.values())[:EVENT_LIMIT]

    notes = []
    for page in db.scalars(select(NotebookPage).order_by(NotebookPage.day.desc())):
        text = "\n".join(
            b.get("text", "") for b in page.blocks or [] if isinstance(b.get("text"), str)
        )
        if query.lower() in text.lower():
            notes.append({"day": page.day, "snippet": _snippet(text, query)})
            if len(notes) == NOTE_LIMIT:
                break

    return {
        "files": _files(db, query),
        "tasks": [
            {"id": t.id, "title": t.title, "meta": _task_meta(t, today),
             "done": t.status == TaskStatus.done, **_task_place(t)}
            for t in tasks
        ],
        "projects": [
            {"id": p.id, "name": p.name, "color": p.color, "status": p.status.value}
            for p in projects
        ],
        "events": [
            {
                "id": e.id,
                "title": e.shown_title,
                "day": e.start.date().isoformat(),
                "when": (
                    upper_first(short_date(e.start.date(), today))
                    + ("" if e.all_day else f", {e.start:%H:%M}")
                ),
                "cancelled": e.cancelled,
            }
            for e in events
        ],
        "notes": [
            {
                "day": n["day"].isoformat(),
                "label": upper_first(short_date(n["day"], today)),
                "snippet": n["snippet"],
            }
            for n in notes
        ],
    }


def _files(db: Session, query: str) -> list[dict[str, Any]]:
    """Projects' documents, tasks' files and habits' whose words hold the
    query's, each with where it opens: a task's task.md is the task, found
    above."""
    out = []
    owners = ("task:", "project:", "habit:")
    for found in documents.search(db, query, limit=FILE_LIMIT * 2, owners=owners):
        kind, _, key = found["owner"].partition(":")
        name = found["name"]
        if kind == "habit":
            habit = db.get(Habit, int(key))
            if habit is None:
                continue
            href, whose = f"/habits/{quote(habit.slug)}", "Habits"
        elif kind == "task":
            task = db.get(Task, int(key))
            if task is None or name == documents.TASK_FILE:
                continue
            href, whose = f"/tasks/{task.id}/files/{quote(name)}", task.title
        else:
            project = db.get(Project, int(key))
            if project is None:
                continue
            whose = project.name
            href = (
                f"/projects/{project.id}" if name == documents.PROJECT_FILE
                else f"/projects/{project.id}/docs/{quote(name)}"
            )
        out.append({
            "title": found["title"], "where": f"{whose} · {name}", "href": href,
            "snippet": found["snippet"],
        })
        if len(out) == FILE_LIMIT:
            break
    return out
