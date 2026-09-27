"""HTMX fragment endpoints: rows, editors, quick-add."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.db import DbSession
from app.models import MilestoneStatus, ProjectStatus, RecurrenceKind, TaskOwner, TaskStatus
from app.services import DomainError
from app.services import blocks as blocks_svc
from app.services import events as events_svc
from app.services import projects as projects_svc
from app.services import recurrence as recurrence_svc
from app.services import tasks as tasks_svc
from app.ui.views import (
    last_missed_block,
    milestone_ctx,
    next_slot_today,
    project_card_ctx,
    projects_list_ctx,
    replan_slot,
    row_ctx,
    sheet_ctx,
    templates,
)

router = APIRouter(prefix="/ui", include_in_schema=False)


def _row_context(request: Request) -> str:
    """Where a task is being shown, as its page marks its requests: "plan"
    (the Tasks page), "block" (a calendar block's menu), or "" (a list)."""
    return request.headers.get("X-Row-Context", "")


def _planning(request: Request) -> bool:
    """On the Tasks page, re-rendered rows stay in planning form (do-date
    buttons, dates always shown)."""
    return _row_context(request) == "plan"


def _checklist_response(request: Request, db, task_id: int) -> HTMLResponse:  # noqa: ANN001
    task = tasks_svc.get_task(db, task_id)
    context = {"request": request, "row": row_ctx(task, datetime.now())}
    return templates.TemplateResponse(request, "partials/block_checklist.html", context)


def _row_day(request: Request) -> date | None:
    """The day the row is shown under, as a day page marks its requests."""
    value = request.headers.get("X-Row-Day", "")
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _time_range(value: str) -> tuple[time | None, time | None]:
    """The sheet's time field: "HH:MM", "HH:MM-HH:MM", or empty for none."""
    if not value:
        return None, None
    start, _, end = value.partition("-")
    try:
        return time.fromisoformat(start), time.fromisoformat(end) if end else None
    except ValueError as exc:
        raise DomainError(f"Not a time: {value}") from exc


def _row_response(
    request: Request,
    db,  # noqa: ANN001
    task_id: int,
    *,
    expanded: bool = False,
) -> HTMLResponse:
    task = tasks_svc.get_task(db, task_id)
    row = row_ctx(task, datetime.now(), planning=_planning(request), day=_row_day(request))
    context = {"request": request, "row": row, "expanded": expanded}
    return templates.TemplateResponse(request, "partials/task_row.html", context)


@router.post("/tasks/quick-add")
def quick_add(
    request: Request,
    db: DbSession,
    title: Annotated[str, Form()],
    notes: Annotated[str, Form()] = "",
    planned_for: Annotated[str, Form()] = "",
    time_range: Annotated[str, Form(alias="time")] = "",
    due: Annotated[str, Form()] = "",
    repeat: Annotated[str, Form()] = "none",
    project_id: Annotated[str, Form()] = "",
    list_day: Annotated[str, Form()] = "",
):
    title = title.strip()
    if not title:
        return HTMLResponse("")
    start, end = _time_range(time_range)
    day = date.fromisoformat(planned_for) if planned_for else None
    if start is not None and day is None:
        # A time needs a day: the list's, else today.
        day = date.fromisoformat(list_day) if list_day else date.today()
    task = tasks_svc.create_task(
        db,
        title=title,
        notes=notes,
        planned_for=day,
        due=date.fromisoformat(due) if due else None,
        project_id=int(project_id) if project_id else None,
    )
    _apply_task_repeat(db, task, repeat)
    if start is not None:
        blocks_svc.set_day_time(db, task, day, start, end)
    db.commit()
    triggers = ["calendar:refresh"] if start is not None else []
    if list_day and day != date.fromisoformat(list_day):
        # Dated away from the list it was written in: it does not join that
        # list, and the page regroups; tasks.js carries the composer.
        response = HTMLResponse("")
        response.headers["HX-Trigger"] = ", ".join([*triggers, "tasks:changed"])
        return response
    response = _row_response(request, db, task.id)
    # Only the page's open count follows; a full list refresh would re-render
    # the composer and pull focus out of it mid-entry.
    response.headers["HX-Trigger"] = ", ".join([*triggers, "task:added"])
    return response


@router.post("/tasks/{task_id}/plan")
def plan_task(db: DbSession, task_id: int, planned_for: Annotated[str, Form()] = ""):
    """Give a task its do-date, or clear it with an empty value."""
    tasks_svc.update_task(
        db, task_id, planned_for=date.fromisoformat(planned_for) if planned_for else None
    )
    db.commit()
    response = HTMLResponse("")
    # The Tasks page regroups; the task moves to its new day's group.
    response.headers["HX-Trigger"] = "tasks:changed"
    return response


@router.post("/tasks/{task_id}/subtasks/{index}/toggle")
def toggle_subtask(
    request: Request,
    db: DbSession,
    task_id: int,
    index: int,
    text: Annotated[str, Form()],
):
    # A stale toggle changes nothing; either way the fresh render shows the truth.
    tasks_svc.toggle_subtask(db, task_id, index, text)
    db.commit()
    if _row_context(request) == "block":
        response = _checklist_response(request, db, task_id)
        # The task's row elsewhere on the page (Today's list) shows the new count.
        response.headers["HX-Trigger"] = "tasks:changed"
        return response
    return _row_response(request, db, task_id, expanded=True)


@router.get("/tasks/{task_id}/checklist")
def task_checklist(request: Request, db: DbSession, task_id: int):
    """The sub-tasks alone, for a calendar block's menu."""
    return _checklist_response(request, db, task_id)


@router.post("/tasks/{task_id}/toggle")
def toggle_task(request: Request, db: DbSession, task_id: int):
    task = tasks_svc.get_task(db, task_id)
    new_status = TaskStatus.todo if task.status == TaskStatus.done else TaskStatus.done
    tasks_svc.set_status(db, task_id, new_status)
    db.commit()
    response = _row_response(request, db, task_id)
    response.headers["HX-Trigger"] = "calendar:refresh"  # keeps Today's open count honest
    return response


@router.post("/tasks/{task_id}/replan")
def replan_task(request: Request, db: DbSession, task_id: int):
    """Put a missed task back on the plan in one step: its missed block's
    length in the next free slot today, or tomorrow when today is full."""
    task = tasks_svc.get_task(db, task_id)
    now = datetime.now()
    missed_block = last_missed_block(task)
    slot = replan_slot(task, now) if tasks_svc.has_missed_marker(task, now) else None
    if slot is not None and missed_block is not None:
        blocks_svc.schedule_block(
            db, task_id=task_id, start=slot, end=slot + (missed_block.end - missed_block.start)
        )
        tasks_svc.update_task(db, task_id, planned_for=now.date())
    elif missed_block is not None:
        tasks_svc.update_task(db, task_id, planned_for=now.date() + timedelta(days=1))
    db.commit()
    response = _row_response(request, db, task_id)
    # Today's list and timeline re-render; the Tasks page regroups.
    response.headers["HX-Trigger"] = "calendar:refresh, tasks:changed"
    return response


# A task given time from the keyboard gets what a drop on the timeline gives.
BOOK_LENGTH = blocks_svc.DEFAULT_LENGTH


@router.post("/tasks/{task_id}/book")
def book_task(db: DbSession, task_id: int):
    """Give a task the next free hour today: the keyboard's drop on the
    timeline. Answers the booked time, or 422 when today has no free hour."""
    now = datetime.now()
    start = next_slot_today(db, BOOK_LENGTH, now)
    if start is None:
        raise DomainError("No free hour left today.")
    blocks_svc.schedule_block(db, task_id=task_id, start=start, end=start + BOOK_LENGTH)
    tasks_svc.update_task(db, task_id, planned_for=now.date())
    db.commit()
    return JSONResponse({"start": f"{start:%H:%M}", "end": f"{start + BOOK_LENGTH:%H:%M}"})


@router.get("/tasks/{task_id}/edit")
def edit_task(request: Request, db: DbSession, task_id: int):
    task = tasks_svc.get_task(db, task_id)
    context = {"request": request, "mode": "edit", "sheet": sheet_ctx(db, task, date.today())}
    return templates.TemplateResponse(request, "partials/task_sheet.html", context)


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
    time_range: Annotated[str, Form(alias="time")] = "",
    due: Annotated[str, Form()] = "",
    repeat: Annotated[str, Form()] = "none",
):
    was = tasks_svc.get_task(db, task_id).planned_for
    day = date.fromisoformat(planned_for) if planned_for else None
    start, end = _time_range(time_range)
    if start is not None and day is None:
        day = was or date.today()  # a time needs a day
    task = tasks_svc.update_task(
        db,
        task_id,
        title=title,
        notes=notes,
        status=status,
        owner=owner,
        project_id=int(project_id) if project_id else None,
        milestone_id=int(milestone_id) if milestone_id else None,
        planned_for=day,
        due=date.fromisoformat(due) if due else None,
    )
    _apply_task_repeat(db, task, repeat)
    # Its time rides with its day: moved with it, set, or taken away.
    had = blocks_svc.day_block(task, was) if was else None
    had_time = f"{had.start:%H:%M}-{had.end:%H:%M}" if had else ""
    if time_range != had_time or (had is not None and day != was):
        if day is not None:
            blocks_svc.set_day_time(db, task, day, start, end, was=was)
        elif had is not None:
            blocks_svc.delete_block(db, had.id)
    db.commit()
    response = _row_response(request, db, task_id)
    # Its day or time may have changed: lists grouped or filtered by day, and
    # the time grid, re-render.
    response.headers["HX-Trigger"] = "tasks:changed, calendar:refresh"
    return response


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
    response = HTMLResponse("")
    # Its blocks went with it: the time grid (and on Today, the list and its
    # open count) re-render from the server.
    response.headers["HX-Trigger"] = "calendar:refresh"
    return response


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


def _projects_list(request: Request, db) -> HTMLResponse:  # noqa: ANN001
    context = {"request": request, **projects_list_ctx(db, datetime.now())}
    return templates.TemplateResponse(request, "partials/projects_list.html", context)


def _project_partial(request: Request, db, project_id: int, template: str) -> HTMLResponse:  # noqa: ANN001
    project = projects_svc.get_project(db, project_id)
    card = project_card_ctx(db, project, datetime.now(), planning=_planning(request))
    return templates.TemplateResponse(request, template, {"request": request, "card": card})


@router.post("/projects")
def create_project(request: Request, db: DbSession, name: str = Form(...)):
    projects_svc.create_project(db, name=name)
    db.commit()
    return _projects_list(request, db)


@router.post("/projects/{project_id}/status")
def set_project_status(
    request: Request, db: DbSession, project_id: int, status: Annotated[ProjectStatus, Form()]
):
    projects_svc.update_project(db, project_id, status=status)
    db.commit()
    # Status moves the card between the active list and the shelves.
    return _projects_list(request, db)


@router.get("/projects/{project_id}/edit")
def edit_project(request: Request, db: DbSession, project_id: int):
    return _project_partial(request, db, project_id, "partials/project_editor.html")


@router.get("/projects/{project_id}/card")
def project_card(request: Request, db: DbSession, project_id: int):
    return _project_partial(request, db, project_id, "partials/project_card.html")


@router.post("/projects/{project_id}")
def save_project(
    request: Request,
    db: DbSession,
    project_id: int,
    name: Annotated[str, Form()],
    notes: Annotated[str, Form()] = "",
):
    projects_svc.update_project(db, project_id, name=name, notes=notes.strip())
    db.commit()
    return _project_partial(request, db, project_id, "partials/project_card.html")


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
    group = {"m": milestone_ctx(db, milestone, date.today()), "rows": []}
    return templates.TemplateResponse(
        request, "partials/milestone_group.html", {"request": request, "group": group}
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
    return templates.TemplateResponse(
        request,
        "partials/milestone_row.html",
        {"request": request, "m": milestone_ctx(db, milestone, date.today())},
    )


@router.post("/notebook/{day}")
async def save_notebook(request: Request, db: DbSession, day: date):
    """Save a day's page (notepad.js): {"version": the copy's version,
    "blocks": [...]}. Answers the new version, or 409 with the page's
    current one when it was saved elsewhere since."""
    from app.services import notebook as notebook_svc

    body = await request.json()
    if not isinstance(body, dict):
        raise DomainError("Expected a page")
    try:
        page = notebook_svc.save_page(
            db, day, body.get("blocks"), version=int(body.get("version", -1))
        )
    except notebook_svc.StalePage as exc:
        return JSONResponse(
            {"detail": str(exc), "version": notebook_svc.version_of(db, day)}, status_code=409
        )
    db.commit()
    return JSONResponse({"version": page.version})


@router.get("/notebook/{day}/version")
def notebook_version(db: DbSession, day: date):
    from app.services import notebook as notebook_svc

    return JSONResponse({"version": notebook_svc.version_of(db, day)})


@router.get("/tasks/{task_id}/history")
def task_history(request: Request, db: DbSession, task_id: int):
    """How the task changed, newest first, for its sheet."""
    from app.services import history as history_svc
    from app.ui.views import history_ctx

    steps = history_ctx(history_svc.changes(db, task_id), date.today())
    return templates.TemplateResponse(
        request, "partials/task_history.html", {"request": request, "steps": steps}
    )
