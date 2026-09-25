"""Task domain logic: lifecycle, list queries, the missed marker."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import checklist
from app.models import (
    BlockState,
    Milestone,
    MilestoneStatus,
    Task,
    TaskOwner,
    TaskStatus,
)
from app.services import DomainError

OPEN_STATUSES = (
    TaskStatus.todo,
    TaskStatus.in_progress,
    TaskStatus.blocked,
    TaskStatus.needs_review,
)


def _validate_milestone(db: Session, project_id: int | None, milestone_id: int | None) -> None:
    if milestone_id is None:
        return
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise DomainError(f"Milestone {milestone_id} does not exist")
    if project_id is None or milestone.project_id != project_id:
        raise DomainError("A task's milestone must belong to the task's own project")


def create_task(
    db: Session,
    *,
    title: str,
    notes: str = "",
    owner: TaskOwner = TaskOwner.oscar,
    status: TaskStatus = TaskStatus.todo,
    project_id: int | None = None,
    milestone_id: int | None = None,
    planned_for: date | None = None,
    due: date | None = None,
) -> Task:
    if not title.strip():
        raise DomainError("Task title must not be empty")
    _validate_milestone(db, project_id, milestone_id)
    task = Task(
        title=title.strip(),
        notes=checklist.normalize(notes),
        owner=owner,
        status=status,
        project_id=project_id,
        milestone_id=milestone_id,
        planned_for=planned_for,
        due=due,
    )
    db.add(task)
    db.flush()
    return task


def update_task(db: Session, task_id: int, **fields: Any) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise DomainError(f"Task {task_id} does not exist")
    project_id = fields.get("project_id", task.project_id)
    milestone_id = fields.get("milestone_id", task.milestone_id)
    # Moving a task off its project drops a milestone that no longer applies.
    if "project_id" in fields and "milestone_id" not in fields and milestone_id is not None:
        fields["milestone_id"] = None
        milestone_id = None
    _validate_milestone(db, project_id, milestone_id)
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


def has_missed_marker(task: Task, now: datetime) -> bool:
    """Missed marker: a block was missed and the task is neither replanned nor closed.

    Derived from block state per the spec; missed is never a task status.
    """
    if task.status in (TaskStatus.done, TaskStatus.cancelled):
        return False
    has_missed = any(b.state == BlockState.missed for b in task.blocks)
    if not has_missed:
        return False
    replanned = any(b.state == BlockState.planned and b.start >= now for b in task.blocks)
    return not replanned


def _with_blocks(stmt):  # noqa: ANN001, ANN202
    return stmt.options(selectinload(Task.blocks))


def daily_list(db: Session, day: date) -> list[Task]:
    """Tasks Oscar intends to work on `day`, driven by planned_for."""
    stmt = _with_blocks(
        select(Task).where(Task.planned_for == day).order_by(Task.status_changed_at)
    )
    return list(db.scalars(stmt))


def backlog(db: Session) -> list[Task]:
    """Open tasks with neither a do-date nor a deadline."""
    stmt = _with_blocks(
        select(Task)
        .where(
            Task.planned_for.is_(None),
            Task.due.is_(None),
            Task.status.in_(OPEN_STATUSES),
        )
        .order_by(Task.created_at.desc())
    )
    return list(db.scalars(stmt))


def delegated(db: Session) -> list[Task]:
    """The Delegated-to-Claude section: open Claude-owned tasks."""
    stmt = _with_blocks(
        select(Task)
        .where(Task.owner == TaskOwner.claude, Task.status.in_(OPEN_STATUSES))
        .order_by(Task.status_changed_at.desc())
    )
    return list(db.scalars(stmt))


def next_days(db: Session, start: date, days: int = 7) -> dict[date, dict[str, list]]:
    """The next-days view: per day, tasks planned or due and milestones targeting it."""
    end = start + timedelta(days=days - 1)
    tasks = list(
        db.scalars(
            _with_blocks(
                select(Task).where(
                    Task.status.in_(OPEN_STATUSES),
                    (Task.planned_for.between(start, end)) | (Task.due.between(start, end)),
                )
            )
        )
    )
    milestones = list(
        db.scalars(
            select(Milestone).where(
                Milestone.status == MilestoneStatus.open,
                Milestone.target_date.between(start, end),
            )
        )
    )
    out: dict[date, dict[str, list]] = {
        start + timedelta(days=i): {"planned": [], "due": [], "milestones": []}
        for i in range(days)
    }
    for task in tasks:
        if task.planned_for is not None and start <= task.planned_for <= end:
            out[task.planned_for]["planned"].append(task)
        if task.due is not None and start <= task.due <= end:
            out[task.due]["due"].append(task)
    for milestone in milestones:
        out[milestone.target_date]["milestones"].append(milestone)
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
    stmt = _with_blocks(select(Task).order_by(Task.created_at))
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
