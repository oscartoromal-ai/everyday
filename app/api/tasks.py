from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from app.api.schemas import ReportIn, TaskIn, TaskOut, TaskPatch
from app.db import DbSession
from app.models import Task, TaskOwner, TaskStatus
from app.services import task_runs
from app.services import tasks as tasks_svc

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def task_out(task: Task) -> TaskOut:
    return TaskOut.model_validate(task)


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
    return [task_out(t) for t in tasks]


@router.post("", status_code=201)
def create_task(body: TaskIn, db: DbSession) -> TaskOut:
    return task_out(tasks_svc.create_task(db, **body.model_dump()))


@router.get("/{task_id}")
def get_task(task_id: int, db: DbSession) -> TaskOut:
    return task_out(tasks_svc.get_task(db, task_id))


@router.patch("/{task_id}")
def update_task(task_id: int, body: TaskPatch, db: DbSession) -> TaskOut:
    fields = body.model_dump(exclude_unset=True)
    repos = fields.pop("repos", None)
    task = tasks_svc.update_task(db, task_id, **fields)
    if repos is not None:
        task = task_runs.set_repos(db, task_id, repos)
    return task_out(task)


@router.post("/{task_id}/report")
def report(task_id: int, body: ReportIn, db: DbSession) -> TaskOut:
    """An agent's word on the task's work (SPEC.md, Agent runs), one call:
    how far it got (in_progress, blocked or needs_review; never done), a
    note, what came of it, and its pull requests. Answers the task."""
    db.info["actor"] = "agent"
    prs = [body.pull_requests] if isinstance(body.pull_requests, str) else body.pull_requests
    return task_out(
        task_runs.report(
            db, task_id, actor="agent", status=body.status, note=body.note,
            outcome=body.outcome, pull_requests=prs,
        )
    )


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, db: DbSession) -> None:
    tasks_svc.delete_task(db, task_id)
