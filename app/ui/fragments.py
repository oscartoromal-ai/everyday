"""HTMX fragment endpoints: rows, editors, quick-add."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.db import DbSession
from app.models import MilestoneStatus, ProjectStatus, RecurrenceKind, TaskOwner, TaskStatus
from app.services import events as events_svc
from app.services import projects as projects_svc
from app.services import recurrence as recurrence_svc
from app.services import tasks as tasks_svc
from app.ui.views import row_ctx, short_date, templates

router = APIRouter(prefix="/ui", include_in_schema=False)


def _row_response(request: Request, db, task_id: int) -> HTMLResponse:  # noqa: ANN001
    task = tasks_svc.get_task(db, task_id)
    context = {"request": request, "row": row_ctx(task, datetime.now())}
    return templates.TemplateResponse(request, "partials/task_row.html", context)


@router.post("/tasks/quick-add")
def quick_add(
    request: Request,
    db: DbSession,
    title: Annotated[str, Form()],
    planned_for: Annotated[date | None, Form()] = None,
):
    title = title.strip()
    if not title:
        return HTMLResponse("")
    task = tasks_svc.create_task(db, title=title, planned_for=planned_for)
    db.commit()
    return _row_response(request, db, task.id)


@router.post("/tasks/{task_id}/toggle")
def toggle_task(request: Request, db: DbSession, task_id: int):
    task = tasks_svc.get_task(db, task_id)
    new_status = TaskStatus.todo if task.status == TaskStatus.done else TaskStatus.done
    tasks_svc.set_status(db, task_id, new_status)
    db.commit()
    return _row_response(request, db, task_id)


@router.get("/tasks/{task_id}/edit")
def edit_task(request: Request, db: DbSession, task_id: int):
    task = tasks_svc.get_task(db, task_id)
    projects = projects_svc.list_projects(db)
    template = task.recurrence_template
    repeat = (
        recurrence_svc.preset_of(template) if template is not None and template.active else "none"
    )
    return templates.TemplateResponse(
        request,
        "partials/task_editor.html",
        {"request": request, "task": task, "projects": projects, "repeat": repeat},
    )


@router.get("/tasks/{task_id}/row")
def task_row(request: Request, db: DbSession, task_id: int):
    return _row_response(request, db, task_id)


@router.post("/tasks/{task_id}")
def save_task(
    request: Request,
    db: DbSession,
    task_id: int,
    title: Annotated[str, Form()],
    status: Annotated[TaskStatus, Form()],
    owner: Annotated[TaskOwner, Form()],
    notes: Annotated[str, Form()] = "",
    project_id: Annotated[str, Form()] = "",
    milestone_id: Annotated[str, Form()] = "",
    planned_for: Annotated[str, Form()] = "",
    due: Annotated[str, Form()] = "",
    repeat: Annotated[str, Form()] = "none",
):
    task = tasks_svc.update_task(
        db,
        task_id,
        title=title,
        notes=notes,
        status=status,
        owner=owner,
        project_id=int(project_id) if project_id else None,
        milestone_id=int(milestone_id) if milestone_id else None,
        planned_for=date.fromisoformat(planned_for) if planned_for else None,
        due=date.fromisoformat(due) if due else None,
    )
    _apply_task_repeat(db, task, repeat)
    db.commit()
    return _row_response(request, db, task_id)


def _apply_task_repeat(db, task, repeat: str) -> None:  # noqa: ANN001
    current = task.recurrence_template
    current_preset = (
        recurrence_svc.preset_of(current) if current is not None and current.active else "none"
    )
    if repeat == current_preset:
        return
    today = date.today()
    if current is not None and current.active:
        # Detach this row first so stopping the series never deletes it.
        task.recurrence_template = None
        task.occurrence_date = None
        db.flush()
        recurrence_svc.stop_template(db, current.id, from_date=today)
    if repeat != "none":
        start = task.planned_for or today
        template = recurrence_svc.create_template(
            db,
            kind=RecurrenceKind.task,
            repeat=repeat,
            start_date=start,
            title=task.title,
            notes=task.notes,
            project_id=task.project_id,
        )
        # Assign the relationship, not the FK: a lazy-loaded None would
        # otherwise stay cached on the instance for later requests.
        task.recurrence_template = template
        task.occurrence_date = start
        db.flush()
        recurrence_svc.materialize_template(db, template, today)


@router.post("/tasks/{task_id}/delete")
def delete_task(db: DbSession, task_id: int):
    tasks_svc.delete_task(db, task_id)
    db.commit()
    return HTMLResponse("")


@router.post("/events")
def add_event(
    db: DbSession,
    title: Annotated[str, Form()],
    day: Annotated[date, Form()],
    start_time: Annotated[str, Form()] = "",
    end_time: Annotated[str, Form()] = "",
    all_day: Annotated[bool, Form()] = False,
    repeat: Annotated[str, Form()] = "none",
):
    from datetime import datetime, time, timedelta

    if repeat != "none":
        template = recurrence_svc.create_template(
            db,
            kind=RecurrenceKind.event,
            repeat=repeat,
            start_date=day,
            title=title,
            start_time=start_time or None,
            end_time=end_time or None,
            all_day=all_day,
        )
        recurrence_svc.materialize_template(db, template, date.today())
    elif all_day or not start_time or not end_time:
        start = datetime.combine(day, time.min)
        event = events_svc.create_event(
            db, title=title, start=start, end=start + timedelta(days=1), all_day=True
        )
        event.all_day = True
    else:
        events_svc.create_event(
            db,
            title=title,
            start=datetime.combine(day, time.fromisoformat(start_time)),
            end=datetime.combine(day, time.fromisoformat(end_time)),
        )
    db.commit()
    response = HTMLResponse("")
    response.headers["HX-Trigger"] = "calendar:refresh"
    return response


@router.post("/nudges/{nudge_id}/dismiss")
def dismiss_nudge(db: DbSession, nudge_id: int):
    from app.services import nudges as nudges_svc

    nudges_svc.dismiss(db, nudge_id)
    db.commit()
    return HTMLResponse("")


@router.post("/work-sync")
def work_sync(db: DbSession):
    from app.config import get_settings
    from app.services import work_calendar as work_calendar_svc
    from app.sources.ics import IcsWorkCalendarSource

    url = get_settings().ics_url
    if not url:
        return HTMLResponse('<span class="sync-note">No work-calendar feed configured.</span>')
    try:
        stats = work_calendar_svc.sync(db, IcsWorkCalendarSource(url))
    except Exception:
        return HTMLResponse('<span class="sync-note error">Work-calendar sync failed.</span>')
    db.commit()
    response = HTMLResponse(
        '<span class="sync-note">Synced: '
        f"{stats['created']} new, {stats['updated']} changed, {stats['deleted']} removed.</span>"
    )
    response.headers["HX-Trigger"] = "calendar:refresh"
    return response


@router.post("/projects")
def create_project(request: Request, db: DbSession, name: str = Form(...)):
    project = projects_svc.create_project(db, name=name)
    db.commit()
    return templates.TemplateResponse(
        request,
        "partials/project_card.html",
        {
            "request": request,
            "card": {"project": project, "milestones": [], "open_count": 0},
        },
    )


@router.post("/projects/{project_id}/status")
def set_project_status(
    request: Request, db: DbSession, project_id: int, status: Annotated[ProjectStatus, Form()]
):
    projects_svc.update_project(db, project_id, status=status)
    db.commit()
    return HTMLResponse("")


@router.post("/projects/{project_id}/milestones")
def add_milestone(
    request: Request,
    db: DbSession,
    project_id: int,
    name: str = Form(...),
    target_date: str = Form(""),
):
    milestone = projects_svc.create_milestone(
        db,
        project_id=project_id,
        name=name,
        target_date=date.fromisoformat(target_date) if target_date else None,
    )
    db.commit()
    return templates.TemplateResponse(
        request,
        "partials/milestone_row.html",
        {
            "request": request,
            "m": {
                "milestone": milestone,
                "progress": (0, 0),
                "target_label": short_date(milestone.target_date)
                if milestone.target_date
                else None,
                "target_soon": False,
            },
        },
    )


@router.post("/milestones/{milestone_id}/toggle")
def toggle_milestone(request: Request, db: DbSession, milestone_id: int):
    from app.models import Milestone

    milestone = db.get(Milestone, milestone_id)
    new_status = (
        MilestoneStatus.open
        if milestone.status == MilestoneStatus.reached
        else MilestoneStatus.reached
    )
    projects_svc.update_milestone(db, milestone_id, status=new_status)
    db.commit()
    done, total = projects_svc.milestone_progress(db, milestone_id)
    return templates.TemplateResponse(
        request,
        "partials/milestone_row.html",
        {
            "request": request,
            "m": {
                "milestone": milestone,
                "progress": (done, total),
                "target_label": short_date(milestone.target_date)
                if milestone.target_date
                else None,
                "target_soon": False,
            },
        },
    )
