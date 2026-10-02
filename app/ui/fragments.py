"""HTMX fragment endpoints: rows, editors, quick-add."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.dates import duration_label
from app.db import DbSession
from app.models import ProjectStatus, RecurrenceKind, TaskOwner, TaskStatus, WorkstreamStatus
from app.services import DomainError
from app.services import blocks as blocks_svc
from app.services import events as events_svc
from app.services import health as health_svc
from app.services import projects as projects_svc
from app.services import recurrence as recurrence_svc
from app.services import tasks as tasks_svc
from app.ui.calendar_view import event_card_ctx
from app.ui.views import (
    last_missed_block,
    me_ctx,
    next_slot_in,
    next_slot_today,
    project_card_ctx,
    projects_list_ctx,
    replan_slot,
    row_ctx,
    sheet_ctx,
    templates,
    workstream_ctx,
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


def _estimate(value: str) -> int | None:
    """The sheet's estimate field: minutes, or empty for none."""
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise DomainError(f"Not an estimate: {value}") from exc


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


def _add_task(
    db,  # noqa: ANN001
    *,
    title: str,
    notes: str = "",
    planned_for: str = "",
    time_range: str = "",
    due: str = "",
    repeat: str = "none",
    project_id: str = "",
    workstream_id: str = "",
    list_day: str = "",
    done: bool = False,
    estimate: str = "",
):
    """A new task as written (quick-add, the task sheet, the notepad's rows),
    its time booked and its repeat set. Returns it, and whether it was given
    a time."""
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
        workstream_id=int(workstream_id) if workstream_id else None,
        status=TaskStatus.done if done else TaskStatus.todo,
        estimate_minutes=_estimate(estimate),
    )
    _apply_task_repeat(db, task, repeat)
    if start is not None:
        blocks_svc.set_day_time(db, task, day, start, end)
    return task, start is not None


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
    estimate: Annotated[str, Form()] = "",
):
    title = title.strip()
    if not title:
        return HTMLResponse("")
    task, timed = _add_task(
        db, title=title, notes=notes, planned_for=planned_for, time_range=time_range,
        due=due, repeat=repeat, project_id=project_id, list_day=list_day, estimate=estimate,
    )
    db.commit()
    triggers = ["calendar:refresh"] if timed else []
    if list_day and task.planned_for != date.fromisoformat(list_day):
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


@router.post("/tasks/{task_id}/book")
def book_task(
    db: DbSession,
    task_id: int,
    start: Annotated[str, Form()] = "",
    days: Annotated[int, Form(ge=1, le=7)] = 1,
):
    """Give a task the next free stretch as long as its estimate (an hour
    without one): today's (B, the keyboard's drop on the timeline), or the
    days shown from `start` (Book, on Calendar's tray). Its do-date becomes
    that day. Answers the time booked, its block and the do-date it had, so
    the booking can be undone; or 422 when there is no room."""
    now = datetime.now()
    task = tasks_svc.get_task(db, task_id)
    had = task.planned_for
    length = blocks_svc.task_length(task)
    if start:
        slot = next_slot_in(db, length, date.fromisoformat(start), days, now)
        where = "today" if days == 1 and start == now.date().isoformat() else (
            "on that day" if days == 1 else "in these days"
        )
    else:
        slot = next_slot_today(db, length, now)
        where = "today"
    if slot is None:
        if length == blocks_svc.DEFAULT_LENGTH:
            raise DomainError(f"No free hour left {where}.")
        raise DomainError(
            f"No {duration_label(length // timedelta(minutes=1))} free left {where}."
        )
    block = blocks_svc.schedule_block(db, task_id=task_id, start=slot, end=slot + length)
    tasks_svc.update_task(db, task_id, planned_for=slot.date())
    db.commit()
    return JSONResponse({
        "start": f"{slot:%H:%M}", "end": f"{slot + length:%H:%M}",
        "day": slot.date().isoformat(), "block_id": block.id,
        "had": had.isoformat() if had else "",
    })


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
    workstream_id: Annotated[str, Form()] = "",
    planned_for: Annotated[str, Form()] = "",
    time_range: Annotated[str, Form(alias="time")] = "",
    due: Annotated[str, Form()] = "",
    repeat: Annotated[str, Form()] = "none",
    estimate: Annotated[str, Form()] = "",
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
        workstream_id=int(workstream_id) if workstream_id else None,
        planned_for=day,
        due=date.fromisoformat(due) if due else None,
        estimate_minutes=_estimate(estimate),
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


@router.get("/search")
def search(db: DbSession, q: str = ""):
    """The command menu's matches for what was typed (app.services.search)."""
    from app.services import search as search_svc

    return JSONResponse(search_svc.search(db, q, datetime.now()))


@router.get("/events/{event_id}/card")
def event_card(request: Request, db: DbSession, event_id: int):
    """An event's card, opened from the grid: what, when and where; one of
    Oscar's own events also changed or deleted there."""
    event = events_svc.get_event(db, event_id)
    return templates.TemplateResponse(
        request, "partials/event_card.html", event_card_ctx(event, date.today())
    )


@router.post("/events/{event_id}")
def edit_event(
    db: DbSession,
    event_id: int,
    title: Annotated[str, Form()],
    day: Annotated[date, Form()],
    start_time: Annotated[str, Form()] = "",
    end_time: Annotated[str, Form()] = "",
):
    """An event's card saved: no times make it all day, as when it is added."""
    if start_time and end_time:
        start = datetime.combine(day, time.fromisoformat(start_time))
        end = datetime.combine(day, time.fromisoformat(end_time))
        all_day = False
    elif start_time or end_time:
        raise DomainError("An event needs both a start and an end, or neither for all day")
    else:
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)
        all_day = True
    events_svc.update_event(
        db, event_id, title=title, start=start, end=end, all_day=all_day
    )
    db.commit()
    response = HTMLResponse("")
    response.headers["HX-Trigger"] = "calendar:refresh"
    return response


@router.post("/events/{event_id}/delete")
def remove_event(db: DbSession, event_id: int, scope: Annotated[str, Form()] = "one"):
    """Delete an event; for one of a series, `scope` "following" also stops
    the series from it on."""
    event = events_svc.get_event(db, event_id)
    if scope == "following" and event.recurrence_template_id and event.occurrence_date:
        recurrence_svc.stop_template(
            db,
            event.recurrence_template_id,
            from_date=event.occurrence_date - timedelta(days=1),
        )
    else:
        events_svc.delete_event(db, event_id)
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


@router.post("/projects/{project_id}/fold", status_code=204)
def fold_project(db: DbSession, project_id: int, folded: Annotated[bool, Form()]) -> None:
    """A card folded to its header, or open again: tasks.js folds it on the
    page at once, and this keeps it so through the lists' next render."""
    projects_svc.update_project(db, project_id, folded=folded)
    db.commit()


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
    color: Annotated[int | None, Form()] = None,
):
    projects_svc.update_project(db, project_id, name=name, notes=notes.strip(), color=color)
    db.commit()
    return _project_partial(request, db, project_id, "partials/project_card.html")


@router.post("/projects/{project_id}/workstreams")
def add_workstream(
    request: Request,
    db: DbSession,
    project_id: int,
    name: str = Form(...),
):
    workstream = projects_svc.create_workstream(db, project_id=project_id, name=name)
    db.commit()
    group = {"m": workstream_ctx(db, workstream), "rows": []}
    return templates.TemplateResponse(
        request, "partials/workstream_group.html", {"request": request, "group": group}
    )


@router.post("/workstreams/{workstream_id}/toggle")
def toggle_workstream(request: Request, db: DbSession, workstream_id: int):
    """A workstream done, or open again."""
    workstream = projects_svc.get_workstream(db, workstream_id)
    done = workstream.status == WorkstreamStatus.done
    projects_svc.update_workstream(
        db, workstream_id, status=WorkstreamStatus.open if done else WorkstreamStatus.done
    )
    db.commit()
    return templates.TemplateResponse(
        request,
        "partials/workstream_row.html",
        {"request": request, "m": workstream_ctx(db, workstream)},
    )


@router.post("/notebook/{day}")
async def save_notebook(request: Request, db: DbSession, day: date):
    """Save a day's page (notepad.js): {"version": the copy's version,
    "blocks": [...]}. A text block's `new`, {row: task as written}, names
    task rows not yet added (the page was being left): each is added here
    and linked to its row, in the same save, since a page being left never
    hears back which task a separate add made. Answers the new version, or
    409 with the page's current one when it was saved elsewhere since (and
    adds nothing)."""
    from app.services import notebook as notebook_svc

    body = await request.json()
    if not isinstance(body, dict):
        raise DomainError("Expected a page")
    version = int(body.get("version", -1))
    blocks = body.get("blocks")
    if version != notebook_svc.version_of(db, day):
        return JSONResponse(
            {"detail": "This page was changed in another window.",
             "version": notebook_svc.version_of(db, day)},
            status_code=409,
        )
    if isinstance(blocks, list):
        blocks = [_add_new_rows(db, b) for b in blocks]
    try:
        page = notebook_svc.save_page(db, day, blocks, version=version)
    except notebook_svc.StalePage as exc:
        return JSONResponse(
            {"detail": str(exc), "version": notebook_svc.version_of(db, day)}, status_code=409
        )
    db.commit()
    return JSONResponse({"version": page.version})


NEW_ROW_FIELDS = (
    "planned_for", "time", "due", "repeat", "project_id", "workstream_id", "estimate",
)


def _add_new_rows(db, block):  # noqa: ANN001, ANN202
    """A text block with its `new` rows added as tasks and put in its links."""
    if not isinstance(block, dict) or "new" not in block:
        return block
    block = dict(block)
    new = block.pop("new")
    if not isinstance(new, dict):
        raise DomainError("A text block's new rows map its rows to tasks")
    links = dict(block.get("links") or {})
    for row, written in new.items():
        if not isinstance(written, dict) or str(row) in {str(r) for r in links}:
            continue
        title = str(written.get("title", "")).strip()
        if not title:
            continue
        fields = {name: str(written.get(name) or "") for name in NEW_ROW_FIELDS}
        task, _ = _add_task(
            db, title=title, notes=str(written.get("notes", "")),
            planned_for=fields["planned_for"], time_range=fields["time"], due=fields["due"],
            repeat=fields["repeat"] or "none", project_id=fields["project_id"],
            workstream_id=fields["workstream_id"], done=written.get("done") is True,
            estimate=fields["estimate"],
        )
        links[str(row)] = task.id
    if links:
        block["links"] = links
    return block


@router.get("/notebook/{day}/version")
def notebook_version(db: DbSession, day: date):
    from app.services import notebook as notebook_svc

    return JSONResponse({"version": notebook_svc.version_of(db, day)})


@router.post("/habits/{slug}")
def set_habit_days(db: DbSession, slug: str, days: Annotated[str, Form()] = ""):
    """A habit's days, from its repeat icon (notepad.js): the weekdays it is
    due, Monday 0 to Sunday 6, or "" for any day. A habit not yet written
    anywhere begins here."""
    from app.services import habits as habits_svc

    habit = habits_svc.set_days(db, slug, days)
    db.commit()
    return JSONResponse({"slug": habit.slug, "days": habit.days})


@router.get("/tasks/{task_id}/history")
def task_history(request: Request, db: DbSession, task_id: int):
    """How the task changed, newest first, for its sheet."""
    from app.services import history as history_svc
    from app.ui.views import history_ctx

    steps = history_ctx(history_svc.changes(db, task_id), date.today())
    return templates.TemplateResponse(
        request, "partials/task_history.html", {"request": request, "steps": steps}
    )


# ---- Health > Me ----


def _number(value: str, what: str) -> float | None:
    value = value.strip().replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise DomainError(f"{what} should be a number") from None


def _me_partial(request: Request, db: DbSession, template: str) -> HTMLResponse:
    ctx = me_ctx(db, date.today())
    return templates.TemplateResponse(request, template, {"request": request, **ctx})


@router.post("/me")
def save_me(
    request: Request,
    db: DbSession,
    height_cm: Annotated[str, Form()] = "",
    birth_date: Annotated[str, Form()] = "",
    sex: Annotated[str, Form()] = "",
    activity: Annotated[str, Form()] = "",
    goal: Annotated[str, Form()] = "",
    target_weight_kg: Annotated[str, Form()] = "",
    diet: Annotated[str, Form()] = "",
    allergies: Annotated[str, Form()] = "",
    avoids: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    """Me's form, saved whole on each change; answers with what follows from it."""
    try:
        born = date.fromisoformat(birth_date) if birth_date else None
    except ValueError:
        raise DomainError("A birth date is a date") from None
    health_svc.update_profile(
        db,
        height_cm=_number(height_cm, "Height (cm)"),
        birth_date=born,
        sex=sex or None,
        activity=activity or None,
        goal=goal or None,
        target_weight_kg=_number(target_weight_kg, "Target weight (kg)"),
        diet=diet, allergies=allergies, avoids=avoids, notes=notes,
    )
    db.commit()
    return _me_partial(request, db, "partials/me_context.html")


@router.get("/me/context")
def me_context(request: Request, db: DbSession):
    return _me_partial(request, db, "partials/me_context.html")


@router.post("/me/weight")
def log_weight(
    request: Request,
    db: DbSession,
    weight_kg: Annotated[str, Form()],
    day: Annotated[str, Form()] = "",
):
    """A weigh-in (today's unless a day is given); the day's last one is kept."""
    weight = _number(weight_kg, "Weight (kg)")
    if weight is None:
        raise DomainError("Write your weight in kg")
    health_svc.log_weight(db, date.fromisoformat(day) if day else date.today(), weight)
    db.commit()
    response = _me_partial(request, db, "partials/me_weights.html")
    response.headers["HX-Trigger"] = "me:changed"
    return response


@router.post("/me/weight/{day}/delete")
def delete_weight(request: Request, db: DbSession, day: date):
    health_svc.delete_weight(db, day)
    db.commit()
    response = _me_partial(request, db, "partials/me_weights.html")
    response.headers["HX-Trigger"] = "me:changed"
    return response
