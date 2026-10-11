"""A task's work as an agent does it, written on the task's page
(partials/task_run.html): its repositories, acceptance criteria and outcome,
its pull requests (added, taken off, and read again from GitHub)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response

from app.api.tasks import get_runner
from app.db import DbSession
from app.models import TaskOwner, TaskStatus
from app.services import task_launch, task_runs
from app.services import tasks as tasks_svc
from app.sources.github import GitHubAccount, account
from app.ui.task_run_view import run_ctx
from app.ui.views import templates

router = APIRouter(include_in_schema=False)


def get_github() -> GitHubAccount:
    """The app's GitHub sign-ins, or a stand-in under test."""
    return account()


GitHub = Annotated[GitHubAccount, Depends(get_github)]


def _section(request: Request, db: DbSession, task_id: int) -> Response:
    """The section drawn again, after a change to it."""
    task = tasks_svc.get_task(db, task_id)
    db.refresh(task)
    return templates.TemplateResponse(
        request, "partials/task_run.html", {"request": request, "run": run_ctx(task, date.today())}
    )


@router.post("/ui/tasks/{task_id}/run", status_code=204)
def save_text(
    db: DbSession,
    task_id: int,
    acceptance: Annotated[str | None, Form()] = None,
    outcome: Annotated[str | None, Form()] = None,
) -> None:
    """Its acceptance criteria or its outcome, saved as they are written."""
    fields = {k: v.replace("\r\n", "\n") for k, v in
              (("acceptance", acceptance), ("outcome", outcome)) if v is not None}
    tasks_svc.update_task(db, task_id, **fields)


@router.post("/ui/tasks/{task_id}/owner", status_code=204)
def save_owner(db: DbSession, task_id: int, owner: Annotated[TaskOwner, Form()]) -> None:
    """Whose task it is, from its agent work pane where its page shows one
    of its files, not its sheet (Hand to an agent; task-page.js)."""
    tasks_svc.update_task(db, task_id, owner=owner)


@router.post("/ui/tasks/{task_id}/repos")
def toggle_repo(
    request: Request,
    db: DbSession,
    task_id: int,
    location: Annotated[str, Form()],
    on: Annotated[bool, Form()],
):
    task_runs.set_repo(db, task_id, location, on)
    db.commit()
    return _section(request, db, task_id)


@router.post("/ui/tasks/{task_id}/pull-requests")
def add_pull_request(request: Request, db: DbSession, task_id: int, url: Annotated[str, Form()]):
    task_runs.add_pull_request(db, task_id, url)
    db.commit()
    return _section(request, db, task_id)


@router.post("/ui/pull-requests/{pr_id}/delete")
def remove_pull_request(request: Request, db: DbSession, pr_id: int):
    task = task_runs.remove_pull_request(db, pr_id)
    db.commit()
    return _section(request, db, task.id)


@router.post("/ui/tasks/{task_id}/launch")
def launch(db: DbSession, task_id: int):
    """The task handed to an agent: the page drawn again, its status moved."""
    task_launch.launch(db, task_id, get_runner())
    db.commit()
    response = Response(status_code=204)
    response.headers["HX-Refresh"] = "true"
    return response


@router.post("/ui/tasks/{task_id}/pull-requests/check")
def check_pull_requests(request: Request, db: DbSession, github: GitHub, task_id: int):
    """Its pull requests read from GitHub now, rather than at the next check."""
    task_runs.check_pull_requests(db, github, [task_id])
    db.commit()
    response = _section(request, db, task_id)
    # Done by its pull requests merging: the sheet's status shows it.
    if tasks_svc.get_task(db, task_id).status == TaskStatus.done:
        response.headers["HX-Refresh"] = "true"
    return response
