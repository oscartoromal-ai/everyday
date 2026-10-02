"""Task domain logic: lifecycle and list queries."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import checklist
from app.dates import monday
from app.models import (
    Task,
    TaskOwner,
    TaskStatus,
    Workstream,
)
from app.services import DomainError

OPEN_STATUSES = (
    TaskStatus.todo,
    TaskStatus.in_progress,
    TaskStatus.blocked,
    TaskStatus.needs_review,
)


def _validate_workstream(db: Session, project_id: int | None, workstream_id: int | None) -> None:
    if workstream_id is None:
        return
    workstream = db.get(Workstream, workstream_id)
    if workstream is None:
        raise DomainError(f"Workstream {workstream_id} does not exist")
    if project_id is None or workstream.project_id != project_id:
        raise DomainError("A task's workstream must belong to the task's own project")


def create_task(
    db: Session,
    *,
    title: str,
    notes: str = "",
    owner: TaskOwner = TaskOwner.oscar,
    status: TaskStatus = TaskStatus.todo,
    project_id: int | None = None,
    workstream_id: int | None = None,
    planned_for: date | None = None,
    due: date | None = None,
    starts_on: date | None = None,
    written_on: date | None = None,
    estimate_minutes: int | None = None,
) -> Task:
    if not title.strip():
        raise DomainError("Task title must not be empty")
    _validate_estimate(estimate_minutes)
    _validate_workstream(db, project_id, workstream_id)
    task = Task(
        title=title.strip(),
        notes=checklist.normalize(notes),
        owner=owner,
        status=status,
        project_id=project_id,
        workstream_id=workstream_id,
        planned_for=planned_for,
        due=due,
        starts_on=starts_on,
        written_on=written_on,
        estimate_minutes=estimate_minutes,
    )
    _keep_span(task, {"starts_on"} if starts_on else set())
    db.add(task)
    db.flush()
    return task


# The longest a task's estimate may be: a day.
MAX_ESTIMATE_MINUTES = 24 * 60


def _validate_estimate(minutes: int | None) -> None:
    if minutes is not None and not 0 < minutes <= MAX_ESTIMATE_MINUTES:
        raise DomainError("A task's estimate must be between a minute and a day")


# A span with no end given runs to the Friday of its week.
SPAN_END_WEEKDAY = 4


def _keep_span(task: Task, given: set[str]) -> None:
    """A task's span on its project's Gantt stays whole: it starts on a day
    and ends on its due, never before. A start given alone ends that week's
    Friday (or on itself, at a weekend); a due cleared takes the start with
    it (a bar needs its end); and a due moved before the start pulls the
    start back to its week's Monday, unless the start was given in the same
    change, which is then refused."""
    if task.starts_on is None:
        return
    if task.due is None:
        if "starts_on" in given:
            friday = monday(task.starts_on) + timedelta(days=SPAN_END_WEEKDAY)
            task.due = max(friday, task.starts_on)
        else:
            task.starts_on = None
    elif task.due < task.starts_on:
        if "starts_on" in given:
            raise DomainError("A task's start must not be after its due")
        task.starts_on = monday(task.due)


def update_task(db: Session, task_id: int, **fields: Any) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise DomainError(f"Task {task_id} does not exist")
    project_id = fields.get("project_id", task.project_id)
    workstream_id = fields.get("workstream_id", task.workstream_id)
    # Moving a task off its project drops a workstream that no longer applies.
    if "project_id" in fields and "workstream_id" not in fields and workstream_id is not None:
        fields["workstream_id"] = None
        workstream_id = None
    _validate_workstream(db, project_id, workstream_id)
    if "estimate_minutes" in fields:
        _validate_estimate(fields["estimate_minutes"])
    if "status" in fields:
        set_status(db, task_id, fields.pop("status"))
    if fields.get("notes") is not None:
        fields["notes"] = checklist.normalize(fields["notes"])
    for key, value in fields.items():
        if not hasattr(task, key):
            raise DomainError(f"Unknown task field: {key}")
        setattr(task, key, value)
    if "title" in fields and not task.title.strip():
        raise DomainError("Task title must not be empty")
    _keep_span(task, set(fields))
    db.flush()
    return task


def set_status(db: Session, task_id: int, status: TaskStatus) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise DomainError(f"Task {task_id} does not exist")
    if status != task.status:
        task.status = status
        task.status_changed_at = datetime.now()
    db.flush()
    return task


def toggle_subtask(db: Session, task_id: int, index: int, expected_text: str) -> bool:
    """Tick or untick one sub-task in the description; False when the
    description changed under the caller and that sub-task is no longer there."""
    task = get_task(db, task_id)
    updated = checklist.toggle(task.notes, index, expected_text)
    if updated is None:
        return False
    task.notes = updated
    db.flush()
    return True


def daily_list(db: Session, day: date) -> list[Task]:
    """Tasks Oscar intends to work on `day`, driven by planned_for."""
    stmt = select(Task).where(Task.planned_for == day).order_by(Task.status_changed_at)
    return list(db.scalars(stmt))


def backlog(db: Session) -> list[Task]:
    """Open tasks with neither a do-date nor a deadline."""
    stmt = (
        select(Task)
        .where(
            Task.planned_for.is_(None),
            Task.due.is_(None),
            Task.status.in_(OPEN_STATUSES),
        )
        .order_by(Task.created_at.desc())
    )
    return list(db.scalars(stmt))


def one_per_series(tasks: list[Task], today: date) -> list[Task]:
    """A repeating series shows one occurrence: its next from today on, or,
    if none is open, its latest overdue one. The rest are already dated and
    would only bury the tasks that still need attention."""
    out: list[Task] = []
    series: dict[int, Task] = {}

    def rank(task: Task) -> tuple[int, int]:
        day = task.planned_for
        return (0, day.toordinal()) if day >= today else (1, -day.toordinal())

    for task in tasks:
        # An occurrence moved off its date stands on its own.
        if task.recurrence_template_id is None or task.planned_for is None:
            out.append(task)
            continue
        current = series.get(task.recurrence_template_id)
        if current is None or rank(task) < rank(current):
            series[task.recurrence_template_id] = task
    return out + list(series.values())


def planning_list(db: Session, today: date) -> list[Task]:
    """Oscar's open tasks, for the Tasks page where he gives them days."""
    stmt = select(Task).where(Task.owner == TaskOwner.oscar, Task.status.in_(OPEN_STATUSES))
    return one_per_series(list(db.scalars(stmt)), today)


def for_day(db: Session, day: date, today: date) -> list[Task]:
    """Oscar's open tasks for a day's page: those planned for it or due on
    it, and on today's also those whose do-date or due has passed; deadlines
    first, then by do-date. A past day has none: its work was its own."""
    if day < today:
        return []

    def on(task: Task) -> bool:
        if day == today:
            return any(d is not None and d <= day for d in (task.planned_for, task.due))
        return day in (task.planned_for, task.due)

    return sorted(
        (t for t in planning_list(db, day) if on(t)),
        key=lambda t: (t.due or date.max, t.planned_for or date.max, t.id),
    )


def recently_done(db: Session, since: datetime) -> list[Task]:
    """Oscar's tasks finished since `since`, latest first: the Done fold."""
    stmt = (
        select(Task)
        .where(
            Task.owner == TaskOwner.oscar,
            Task.status == TaskStatus.done,
            Task.status_changed_at >= since,
        )
        .order_by(Task.status_changed_at.desc())
    )
    return list(db.scalars(stmt))


def delegated(db: Session) -> list[Task]:
    """The Delegated-to-Claude section: open Claude-owned tasks."""
    stmt = (
        select(Task)
        .where(Task.owner == TaskOwner.claude, Task.status.in_(OPEN_STATUSES))
        .order_by(Task.status_changed_at.desc())
    )
    return list(db.scalars(stmt))


def next_days(db: Session, start: date, days: int = 7) -> dict[date, dict[str, list]]:
    """The next-days view: per day, tasks planned or due."""
    end = start + timedelta(days=days - 1)
    tasks = list(
        db.scalars(
            select(Task).where(
                Task.status.in_(OPEN_STATUSES),
                (Task.planned_for.between(start, end)) | (Task.due.between(start, end)),
            )
        )
    )
    out: dict[date, dict[str, list]] = {
        start + timedelta(days=i): {"planned": [], "due": []}
        for i in range(days)
    }
    for task in tasks:
        if task.planned_for is not None and start <= task.planned_for <= end:
            out[task.planned_for]["planned"].append(task)
        if task.due is not None and start <= task.due <= end:
            out[task.due]["due"].append(task)
    return out


def list_tasks(
    db: Session,
    *,
    project_id: int | None = None,
    status: TaskStatus | None = None,
    owner: TaskOwner | None = None,
    planned_from: date | None = None,
    planned_to: date | None = None,
) -> list[Task]:
    stmt = select(Task).order_by(Task.created_at)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if owner is not None:
        stmt = stmt.where(Task.owner == owner)
    if planned_from is not None:
        stmt = stmt.where(Task.planned_for >= planned_from)
    if planned_to is not None:
        stmt = stmt.where(Task.planned_for <= planned_to)
    return list(db.scalars(stmt))


def delete_task(db: Session, task_id: int) -> None:
    task = db.get(Task, task_id)
    if task is None:
        raise DomainError(f"Task {task_id} does not exist")
    db.delete(task)
    db.flush()


def get_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise DomainError(f"Task {task_id} does not exist")
    return task
