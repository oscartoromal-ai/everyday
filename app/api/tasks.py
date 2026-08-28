from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter

from app.api.schemas import TaskIn, TaskOut, TaskPatch
from app.db import DbSession
from app.models import Task, TaskOwner, TaskStatus
from app.services import tasks as tasks_svc

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def task_out(task: Task, now: datetime | None = None) -> TaskOut:
    out = TaskOut.model_validate(task)
    out.missed = tasks_svc.has_missed_marker(task, now or datetime.now())
    return out


@router.get("")
def list_tasks(
    db: DbSession,
    project_id: int | None = None,
    status: TaskStatus | None = None,
    owner: TaskOwner | None = None,
    planned_from: date | None = None,
    planned_to: date | None = None,
) -> list[TaskOut]:
    tasks = tasks_svc.list_tasks(
        db,
        project_id=project_id,
        status=status,
        owner=owner,
        planned_from=planned_from,
        planned_to=planned_to,
    )
    now = datetime.now()
    return [task_out(t, now) for t in tasks]


@router.post("", status_code=201)
def create_task(body: TaskIn, db: DbSession) -> TaskOut:
    return task_out(tasks_svc.create_task(db, **body.model_dump()))


@router.get("/{task_id}")
def get_task(task_id: int, db: DbSession) -> TaskOut:
    return task_out(tasks_svc.get_task(db, task_id))


@router.patch("/{task_id}")
def update_task(task_id: int, body: TaskPatch, db: DbSession) -> TaskOut:
    return task_out(tasks_svc.update_task(db, task_id, **body.model_dump(exclude_unset=True)))


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, db: DbSession) -> None:
    tasks_svc.delete_task(db, task_id)
