"""A project's Gantt: its tasks as bars over weeks, its milestones as
diamonds, and the edits its sheet makes (SPEC.md, Gantt).

A bar is a task's span: from the Monday of its start week (Task.starts_on)
to its due, so the end of a bar is the task's deadline and the Tasks page,
nudges and Weeks see it as one. Everything here works in whole weeks; a due
keeps its weekday as its bar moves or stretches (a new one is the Friday).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.dates import monday
from app.models import Milestone, MilestoneStatus, Project, Task, TaskStatus
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


def parse_start(text: str, today: date) -> date:
    """The Monday of the start week written in a Start cell: a week, or any
    day of it."""
    week, day = _read(text, today, "week")
    return week or monday(day)


def parse_due(text: str, today: date) -> date:
    """The day written in a Due cell; a week given for it is its Friday."""
    week, day = _read(text, today, "date")
    return day or week + timedelta(days=SPAN_END_WEEKDAY)


def parse_weeks(text: str) -> int:
    """A bar's length written in a Wks cell: a whole number of weeks."""
    value = text.strip().lower().removesuffix("w").removesuffix("weeks").strip()
    if not value.isdigit() or not 1 <= int(value) <= MAX_WEEKS:
        raise DomainError(f"A bar is 1 to {MAX_WEEKS} weeks: {text.strip()}")
    return int(value)


# ---- a bar in weeks ----


def weeks_of(task: Task) -> int | None:
    """How many weeks a task's bar covers, its start's to its due's."""
    if task.starts_on is None or task.due is None:
        return None
    return (monday(task.due) - task.starts_on).days // 7 + 1


def _end(last_week: date, due: date | None) -> date:
    """The due of a bar ending in `last_week`: the old due's weekday there,
    or the Friday for a bar that had none."""
    return last_week + timedelta(days=due.weekday() if due else SPAN_END_WEEKDAY)


# ---- the rows ----


@dataclass
class Group:
    """A milestone and its tasks, or (milestone None) the project's other tasks."""

    milestone: Milestone | None
    tasks: list[Task] = field(default_factory=list)


def _order(task: Task) -> tuple:
    return (task.position is None, task.position or 0, task.created_at, task.id)


def groups(db: Session, project: Project, today: date) -> list[Group]:
    """The Gantt's rows: each milestone not dropped with its tasks, then the
    tasks in none (or in a dropped one). Open tasks show one occurrence per
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
    milestones = sorted(
        (m for m in project.milestones if m.status != MilestoneStatus.dropped),
        key=lambda m: m.id,
    )
    out = [Group(m, [t for t in shown if t.milestone_id == m.id]) for m in milestones]
    grouped = {m.id for m in milestones}
    out.append(Group(None, [t for t in shown if t.milestone_id not in grouped]))
    return out


# ---- the sheet's edits ----


def _task(db: Session, project: Project, task_id: Any) -> Task:
    task = tasks_svc.get_task(db, int(task_id))
    if task.project_id != project.id:
        raise DomainError(f"Task {task_id} is not in {project.name}")
    return task


def _milestone(db: Session, project: Project, milestone_id: Any) -> Milestone:
    milestone = db.get(Milestone, int(milestone_id))
    if milestone is None or milestone.project_id != project.id:
        raise DomainError(f"Milestone {milestone_id} is not in {project.name}")
    return milestone


def _iso(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


def _set_span(db: Session, task: Task, start: date | None, due: date | None) -> None:
    tasks_svc.update_task(db, task.id, starts_on=start, due=due)


def edit_task(db: Session, task: Task, op: dict[str, Any], today: date) -> None:
    """One task's cells, as the sheet writes them. Each key is one edit:
    title; start, weeks or due as typed; span, the weeks a bar was drawn
    over ([first Monday, last Monday]); shift, a bar moved by whole weeks;
    grow, its end moved by whole weeks; clear, its span or its due; done;
    and set, every field as it was (undo)."""
    if "title" in op:
        tasks_svc.update_task(db, task.id, title=op["title"])
    if "start" in op:
        if not op["start"].strip():
            _set_span(db, task, None, task.due)
        else:
            start = parse_start(op["start"], today)
            weeks = weeks_of(task)
            if weeks is not None:
                # A bar keeps its length as its start moves.
                due = _end(start + WEEK * (weeks - 1), task.due)
            elif task.due is not None and task.due >= start:
                due = task.due
            else:
                due = _end(start, None)
            _set_span(db, task, start, due)
    if "weeks" in op:
        if not op["weeks"].strip():
            _set_span(db, task, None, task.due)
        else:
            weeks = parse_weeks(op["weeks"])
            if task.starts_on is not None:
                start = task.starts_on
            elif task.due is not None:
                # A task due already: its bar reaches back from its due's week.
                start = monday(task.due) - WEEK * (weeks - 1)
            else:
                start = monday(today)
            _set_span(db, task, start, _end(start + WEEK * (weeks - 1), task.due))
    if "due" in op:
        tasks_svc.update_task(
            db, task.id, due=parse_due(op["due"], today) if op["due"].strip() else None
        )
    if "span" in op:
        first, last = sorted(date.fromisoformat(v) for v in op["span"])
        _set_span(db, task, monday(first), _end(monday(last), task.due))
    if "shift" in op and task.due is not None:
        by = WEEK * int(op["shift"])
        start = task.starts_on + by if task.starts_on else None
        _set_span(db, task, start, task.due + by)
    if "grow" in op and task.starts_on is not None:
        due = task.due + WEEK * int(op["grow"])
        # A bar is never shorter than a week.
        if monday(due) >= task.starts_on:
            _set_span(db, task, task.starts_on, due)
    if op.get("clear") == "span":
        _set_span(db, task, None, task.due)
    elif op.get("clear") == "due":
        _set_span(db, task, None, None)
    if "done" in op:
        tasks_svc.set_status(db, task.id, TaskStatus.done if op["done"] else TaskStatus.todo)
    if "set" in op:
        was = op["set"]
        tasks_svc.update_task(
            db, task.id, title=was["title"], starts_on=_iso(was["starts_on"]),
            due=_iso(was["due"]),
        )
        tasks_svc.set_status(db, task.id, TaskStatus(was["status"]))


def edit_milestone(db: Session, milestone: Milestone, op: dict[str, Any], today: date) -> None:
    """A milestone's cells: name; target as typed (its Due cell); shift, its
    diamond moved by whole weeks; reached; and set, as it was (undo)."""
    if "name" in op:
        projects_svc.update_milestone(db, milestone.id, name=op["name"])
    if "target" in op:
        text = op["target"].strip()
        projects_svc.update_milestone(
            db, milestone.id, target_date=parse_due(text, today) if text else None,
            clear_target_date=not text,
        )
    if "shift" in op and milestone.target_date is not None:
        projects_svc.update_milestone(
            db, milestone.id, target_date=milestone.target_date + WEEK * int(op["shift"])
        )
    if "reached" in op:
        projects_svc.update_milestone(
            db, milestone.id,
            status=MilestoneStatus.reached if op["reached"] else MilestoneStatus.open,
        )
    if "set" in op:
        was = op["set"]
        target = _iso(was["target"])
        projects_svc.update_milestone(
            db, milestone.id, name=was["name"], target_date=target,
            clear_target_date=target is None, status=MilestoneStatus(was["status"]),
        )


def move_task(db: Session, project: Project, task: Task, step: int, today: date) -> None:
    """A row one place up (step -1) or down (+1). Past its group's first or
    last row it goes into the group above or below: that milestone, or none."""
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
        milestone_id = into.milestone.id if into.milestone else None
        tasks_svc.update_task(db, task.id, milestone_id=milestone_id)
        order = [task, *into.tasks] if step > 0 else [*into.tasks, task]
    else:
        return
    for position, row in enumerate(order):
        row.position = position
    db.flush()


def apply(db: Session, project: Project, ops: list[dict[str, Any]], today: date) -> list[int]:
    """The sheet's edits, in order and all or none; the ids of the tasks
    and milestones it made, in order. An op is {"op": ...} with:

    task (id, and edit_task's keys), milestone (id, and edit_milestone's),
    create (a task: milestone_id, title, and start, weeks or due as typed),
    delete (id), move (id, step), milestone_create (name, and target)."""
    made: list[int] = []
    for op in ops:
        kind = op.get("op")
        if kind == "task":
            edit_task(db, _task(db, project, op["id"]), op, today)
        elif kind == "milestone":
            edit_milestone(db, _milestone(db, project, op["id"]), op, today)
        elif kind == "create":
            milestone_id = op.get("milestone_id")
            if milestone_id:
                _milestone(db, project, milestone_id)
            task = tasks_svc.create_task(
                db, title=op.get("title", ""), project_id=project.id,
                milestone_id=int(milestone_id) if milestone_id else None,
            )
            cells = {k: op[k] for k in ("start", "weeks", "due") if (op.get(k) or "").strip()}
            if cells:
                edit_task(db, task, cells, today)
            made.append(task.id)
        elif kind == "delete":
            tasks_svc.delete_task(db, _task(db, project, op["id"]).id)
        elif kind == "move":
            move_task(db, project, _task(db, project, op["id"]), int(op["step"]), today)
        elif kind == "milestone_create":
            text = (op.get("target") or "").strip()
            milestone = projects_svc.create_milestone(
                db, project_id=project.id, name=op.get("name", ""),
                target_date=parse_due(text, today) if text else None,
            )
            made.append(milestone.id)
        else:
            raise DomainError(f"Unknown edit: {kind}")
    db.flush()
    return made
