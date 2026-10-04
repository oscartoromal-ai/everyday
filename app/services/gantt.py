"""A project's Gantt: its tasks as bars over the weeks, in lanes
by workstream, and the edits its sheet makes (SPEC.md, Gantt).

A bar is a task's span: from its start day (Task.starts_on) to its due, so
the end of a bar is the task's deadline and Today and the nudges
see it as one. The sheet is seen in weeks or drilled down to days: in weeks
a bar moves and stretches by whole weeks, its days kept (a due keeps its
weekday; a new bar ends on the Friday), in days by days.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.dates import monday
from app.models import Project, Task, TaskStatus, Workstream, WorkstreamStatus
from app.services import DomainError
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.services.tasks import SPAN_END_WEEKDAY

WEEK = timedelta(days=7)
# The longest bar, and the furthest a week number is read from today.
MAX_WEEKS = 260

MONTHS = {
    m: i + 1
    for i, names in enumerate(
        ("jan january", "feb february", "mar march", "apr april", "may", "jun june",
         "jul july", "aug august", "sep sept september", "oct october", "nov november",
         "dec december")
    )
    for m in names.split()
}
WEEKDAYS = {
    d: i
    for i, names in enumerate(
        ("mon monday", "tue tues tuesday", "wed wednesday", "thu thur thurs thursday",
         "fri friday", "sat saturday", "sun sunday")
    )
    for d in names.split()
}


# ---- reading what is typed in a cell ----


def _nearest_year(today: date, make) -> date:  # noqa: ANN001
    """The date `make(year)` gives nearest today, over last year, this and next."""
    found = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            found.append(make(year))
        except ValueError:
            continue
    if not found:
        raise ValueError
    return min(found, key=lambda d: abs((d - today).days))


def _week(text: str, today: date) -> date | None:
    """A week as written: "40", "W40", "2026-W40", "this week", "next week";
    the Monday it starts, or None when the words are not a week."""
    if text in ("this week", "this", "now"):
        return monday(today)
    if text in ("next week", "next"):
        return monday(today) + WEEK
    if m := re.fullmatch(r"(\d{4})-?w(\d{1,2})", text):
        return date.fromisocalendar(int(m[1]), int(m[2]), 1)
    if m := re.fullmatch(r"w?\s*(\d{1,2})", text):
        week = int(m[1])
        return _nearest_year(today, lambda y: date.fromisocalendar(y, week, 1))
    return None


def _day(text: str, today: date) -> date | None:
    """A day as written: "2026-10-16", "16/10", "16/10/26", "16 Oct", "Oct 16",
    "fri", "today", "tomorrow"; None when the words are not a day. A date
    without a year is the one nearest today, a weekday the next from today."""
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if text in WEEKDAYS:
        return today + timedelta(days=(WEEKDAYS[text] - today.weekday()) % 7)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?", text):
        day, month = int(m[1]), int(m[2])
        if m[3]:
            year = int(m[3])
            return date(year + 2000 if year < 100 else year, month, day)
        return _nearest_year(today, lambda y: date(y, month, day))
    words = text.replace(",", " ").split()
    if len(words) in (2, 3) and words[0] in WEEKDAYS:
        words = words[1:]  # "fri 16 oct": the weekday only repeats the date
    if len(words) in (2, 3):
        if words[0].isdigit() and words[1] in MONTHS:
            day, month = int(words[0]), MONTHS[words[1]]
        elif words[1].isdigit() and words[0] in MONTHS:
            day, month = int(words[1]), MONTHS[words[0]]
        else:
            return None
        if len(words) == 3:
            if not words[2].isdigit():
                return None
            year = int(words[2])
            return date(year + 2000 if year < 100 else year, month, day)
        return _nearest_year(today, lambda y: date(y, month, day))
    return None


def _read(text: str, today: date, what: str) -> tuple[date | None, date | None]:
    """(week, day) of what was typed: one of them, else a refusal naming `what`."""
    text = " ".join(text.lower().split())
    try:
        week, day = _week(text, today), _day(text, today)
    except ValueError as exc:
        raise DomainError(f"There is no such {what}: {text}") from exc
    if week is None and day is None:
        raise DomainError(f"Not a {what}: {text}. Try W42, 12 Oct or next week")
    return week, day


def parse_start(text: str, today: date) -> tuple[date, bool]:
    """The start written in a Start cell, and whether it was a week: a week
    is its Monday ("W42", "next week"), a day itself ("14 Oct", "wed")."""
    week, day = _read(text, today, "week")
    return (week, True) if week else (day, False)


def parse_due(text: str, today: date) -> date:
    """The day written in a Due cell; a week given for it is its Friday."""
    week, day = _read(text, today, "date")
    return day or week + timedelta(days=SPAN_END_WEEKDAY)


UNITS = {"week": 7, "day": 1}
SUFFIXES = (("weeks", "week"), ("week", "week"), ("w", "week"),
            ("days", "day"), ("day", "day"), ("d", "day"))


def parse_length(text: str, unit: str) -> tuple[int, str]:
    """A bar's length written in its length cell: a whole number of the
    view's unit, or of the one it names ("3w", "10d")."""
    value = text.strip().lower()
    for suffix, named in SUFFIXES:
        if value.endswith(suffix) and value[: -len(suffix)].strip().isdigit():
            value, unit = value[: -len(suffix)].strip(), named
            break
    limit = MAX_WEEKS * 7 // UNITS[unit]
    if not value.isdigit() or not 1 <= int(value) <= limit:
        raise DomainError(f"A bar is 1 to {limit} {unit}s: {text.strip()}")
    return int(value), unit


# ---- a bar: whole days, from its start to its due ----


def length_of(task: Task, unit: str) -> int | None:
    """How long a task's bar is: the days it covers, or the weeks they fall in."""
    if task.starts_on is None or task.due is None:
        return None
    if unit == "day":
        return (task.due - task.starts_on).days + 1
    return (monday(task.due) - monday(task.starts_on)).days // 7 + 1


def _week_end(week: date, due: date | None, start: date) -> date:
    """The due of a bar ending in the week of `week`: the old due's weekday
    there, or the Friday for a bar that had none; never before its start."""
    end = monday(week) + timedelta(days=due.weekday() if due else SPAN_END_WEEKDAY)
    return max(end, start)


def _step(op: dict[str, Any]) -> timedelta:
    """The unit an edit moves by: a week, or a day in the Days view."""
    return timedelta(days=UNITS[op.get("unit", "week")])


# ---- the rows ----


@dataclass
class Group:
    """A workstream and its tasks, or (workstream None) the project's other tasks."""

    workstream: Workstream | None
    tasks: list[Task] = field(default_factory=list)


def _order(task: Task) -> tuple:
    return (task.position is None, task.position or 0, task.created_at, task.id)


def groups(db: Session, project: Project, today: date) -> list[Group]:
    """The Gantt's rows: each workstream with its tasks, then the tasks in
    none. Open tasks show one occurrence per
    series, as everywhere; done ones stay on the plan, except a series'
    finished occurrences; cancelled ones leave it."""
    tasks = [
        t for t in tasks_svc.list_tasks(db, project_id=project.id)
        if t.status != TaskStatus.cancelled
    ]
    open_tasks = tasks_svc.one_per_series(
        [t for t in tasks if t.status in tasks_svc.OPEN_STATUSES], today
    )
    done = [t for t in tasks if t.status == TaskStatus.done and t.recurrence_template_id is None]
    shown = sorted(open_tasks + done, key=_order)
    out = [Group(m, [t for t in shown if t.workstream_id == m.id]) for m in project.workstreams]
    out.append(Group(None, [t for t in shown if t.workstream_id is None]))
    return out


# ---- the sheet's edits ----


def _task(db: Session, project: Project, task_id: Any) -> Task:
    task = tasks_svc.get_task(db, int(task_id))
    if task.project_id != project.id:
        raise DomainError(f"Task {task_id} is not in {project.name}")
    return task


def _workstream(db: Session, project: Project, workstream_id: Any) -> Workstream:
    workstream = db.get(Workstream, int(workstream_id))
    if workstream is None or workstream.project_id != project.id:
        raise DomainError(f"Workstream {workstream_id} is not in {project.name}")
    return workstream


def _iso(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


def _set_span(db: Session, task: Task, start: date | None, due: date | None) -> None:
    tasks_svc.update_task(db, task.id, starts_on=start, due=due)


def _start(db: Session, task: Task, text: str, today: date) -> None:
    """A start written in. A bar keeps its length as its start moves; a
    week written for it keeps the weekday it started on. Without a bar, a
    due on or after the start ends it, else the start's week's Friday."""
    if not text.strip():
        _set_span(db, task, None, task.due)
        return
    start, is_week = parse_start(text, today)
    if task.starts_on is not None and task.due is not None:
        if is_week:
            start += timedelta(days=task.starts_on.weekday())
        _set_span(db, task, start, task.due + (start - task.starts_on))
    elif task.due is not None and task.due >= start:
        _set_span(db, task, start, task.due)
    else:
        _set_span(db, task, start, _week_end(start, None, start))


def _length(db: Session, task: Task, text: str, unit: str, today: date) -> None:
    """A length written in: from its start (else back from its due, else
    from today) for that many days, or into that many weeks, its due keeping
    its weekday."""
    if not text.strip():
        _set_span(db, task, None, task.due)
        return
    count, unit = parse_length(text, unit)
    step = timedelta(days=UNITS[unit])
    if task.starts_on is not None:
        start = task.starts_on
    elif task.due is not None:
        start = task.due - step * (count - 1)
        start = monday(start) if unit == "week" else start
    else:
        start = monday(today) if unit == "week" else today
    if unit == "day":
        _set_span(db, task, start, start + step * (count - 1))
    else:
        _set_span(db, task, start, _week_end(start + step * (count - 1), task.due, start))


def edit_task(db: Session, task: Task, op: dict[str, Any], today: date) -> None:
    """One task's cells, as the sheet writes them. Each key is one edit, and
    `unit` ("week", or "day" in the Days view) the unit of those that move:
    title; start, length or due as typed; span, the columns a bar was drawn
    over ([first, last]: Mondays, or days); shift, the bar moved; grow, its
    end moved; move_start, its start moved; clear, its span or its due;
    status, as its box or its menu gives it; priority, as typed or chosen
    ("high", "h", "2", "p2"; empty for none); and set, every field as it
    was (undo)."""
    unit = op.get("unit", "week")
    step = _step(op)
    if "title" in op:
        tasks_svc.update_task(db, task.id, title=op["title"])
    if "priority" in op:
        tasks_svc.update_task(db, task.id, priority=tasks_svc.parse_priority(op["priority"]))
    if "start" in op:
        _start(db, task, op["start"], today)
    if "length" in op:
        _length(db, task, op["length"], unit, today)
    if "due" in op:
        tasks_svc.update_task(
            db, task.id, due=parse_due(op["due"], today) if op["due"].strip() else None
        )
    if "span" in op:
        first, last = sorted(date.fromisoformat(v) for v in op["span"])
        if unit == "day":
            _set_span(db, task, first, last)
        else:
            _set_span(db, task, monday(first), _week_end(last, task.due, monday(first)))
    if "shift" in op and task.due is not None:
        by = step * int(op["shift"])
        start = task.starts_on + by if task.starts_on else None
        _set_span(db, task, start, task.due + by)
    if "grow" in op and task.starts_on is not None:
        due = task.due + step * int(op["grow"])
        # A bar is never shorter than its start's day.
        if due >= task.starts_on:
            _set_span(db, task, task.starts_on, due)
    if "move_start" in op and task.starts_on is not None:
        start = task.starts_on + step * int(op["move_start"])
        if start <= task.due:
            _set_span(db, task, start, task.due)
    if op.get("clear") == "span":
        _set_span(db, task, None, task.due)
    elif op.get("clear") == "due":
        _set_span(db, task, None, None)
    if "status" in op:
        try:
            status = TaskStatus(str(op["status"]))
        except ValueError as exc:
            raise DomainError(f"Not a status: {op['status']!r}") from exc
        tasks_svc.set_status(db, task.id, status)
    if "set" in op:
        was = op["set"]
        tasks_svc.update_task(
            db, task.id, title=was["title"], starts_on=_iso(was["starts_on"]),
            due=_iso(was["due"]), priority=tasks_svc.parse_priority(was.get("priority", "")),
        )
        tasks_svc.set_status(db, task.id, TaskStatus(was["status"]))


def edit_workstream(db: Session, workstream: Workstream, op: dict[str, Any]) -> None:
    """A workstream's cells: its name; done; and set, as it was (undo). It
    has no dates of its own: its span is its tasks'."""
    if "name" in op:
        projects_svc.update_workstream(db, workstream.id, name=op["name"])
    if "done" in op:
        projects_svc.update_workstream(
            db, workstream.id,
            status=WorkstreamStatus.done if op["done"] else WorkstreamStatus.open,
        )
    if "set" in op:
        was = op["set"]
        projects_svc.update_workstream(
            db, workstream.id, name=was["name"], status=WorkstreamStatus(was["status"])
        )


def move_task(db: Session, project: Project, task: Task, step: int, today: date) -> None:
    """A row one place up (step -1) or down (+1). Past its group's first or
    last row it goes into the group above or below: that workstream, or none."""
    rows = groups(db, project, today)
    at = next(i for i, g in enumerate(rows) if task in g.tasks)
    group = rows[at]
    index = group.tasks.index(task)
    target = index + step
    if 0 <= target < len(group.tasks):
        group.tasks[index], group.tasks[target] = group.tasks[target], group.tasks[index]
        order = group.tasks
    elif 0 <= at + step < len(rows):
        into = rows[at + step]
        workstream_id = into.workstream.id if into.workstream else None
        tasks_svc.update_task(db, task.id, workstream_id=workstream_id)
        order = [task, *into.tasks] if step > 0 else [*into.tasks, task]
    else:
        return
    for position, row in enumerate(order):
        row.position = position
    db.flush()


def place_task(
    db: Session, project: Project, task: Task, workstream_id: Any, before_id: Any, today: date
) -> None:
    """A row dropped somewhere: into a workstream's group (or the other
    tasks', workstream_id empty), before another of its tasks, or at its end
    (before_id empty)."""
    workstream = _workstream(db, project, workstream_id) if workstream_id else None
    rows = groups(db, project, today)
    into = next(g for g in rows if g.workstream is workstream)
    order = [t for t in into.tasks if t.id != task.id]
    before = next((t for t in order if before_id and t.id == int(before_id)), None)
    order.insert(order.index(before) if before else len(order), task)
    if task.workstream_id != (workstream.id if workstream else None):
        tasks_svc.update_task(db, task.id, workstream_id=workstream.id if workstream else None)
    for position, row in enumerate(order):
        row.position = position
    db.flush()


def apply(db: Session, project: Project, ops: list[dict[str, Any]], today: date) -> list[int]:
    """The sheet's edits, in order and all or none; the ids of the tasks
    and workstreams it made, in order. An op is {"op": ...} with:

    task (id, and edit_task's keys), workstream (id, and edit_workstream's),
    create (a task: workstream_id, title, and priority, start, length or due
    as typed),
    delete (id), move (id, step), place (id, workstream_id, before: a task's
    id or none), workstream_create (name), workstream_delete (id: its tasks
    stay, in none), workstream_place (id, before: another workstream's id,
    or none for last)."""
    made: list[int] = []
    for op in ops:
        kind = op.get("op")
        if kind == "task":
            edit_task(db, _task(db, project, op["id"]), op, today)
        elif kind == "workstream":
            edit_workstream(db, _workstream(db, project, op["id"]), op)
        elif kind == "create":
            workstream_id = op.get("workstream_id")
            if workstream_id:
                _workstream(db, project, workstream_id)
            task = tasks_svc.create_task(
                db, title=op.get("title", ""), project_id=project.id,
                workstream_id=int(workstream_id) if workstream_id else None,
            )
            cells = {
                k: op[k]
                for k in ("priority", "start", "length", "due")
                if (op.get(k) or "").strip()
            }
            if cells:
                edit_task(db, task, {**cells, "unit": op.get("unit", "week")}, today)
            made.append(task.id)
        elif kind == "delete":
            tasks_svc.delete_task(db, _task(db, project, op["id"]).id)
        elif kind == "move":
            move_task(db, project, _task(db, project, op["id"]), int(op["step"]), today)
        elif kind == "place":
            place_task(
                db, project, _task(db, project, op["id"]), op.get("workstream_id"),
                op.get("before"), today,
            )
        elif kind == "workstream_create":
            workstream = projects_svc.create_workstream(
                db, project_id=project.id, name=op.get("name", "")
            )
            made.append(workstream.id)
        elif kind == "workstream_delete":
            projects_svc.delete_workstream(db, _workstream(db, project, op["id"]).id)
        elif kind == "workstream_place":
            before = op.get("before")
            projects_svc.place_workstream(
                db, _workstream(db, project, op["id"]).id, int(before) if before else None
            )
        else:
            raise DomainError(f"Unknown edit: {kind}")
    db.flush()
    return made
