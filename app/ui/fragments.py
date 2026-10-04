"""HTMX fragment endpoints: rows, editors, quick-add."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.db import DbSession
from app.models import (
    RecurrenceKind,
    TaskOwner,
    TaskPriority,
    TaskStatus,
    WorkstreamStatus,
)
from app.services import DomainError
from app.services import events as events_svc
from app.services import projects as projects_svc
from app.services import rail as rail_svc
from app.services import recurrence as recurrence_svc
from app.services import tasks as tasks_svc
from app.ui.calendar_view import event_card_ctx
from app.ui.views import (
    back_link,
    row_ctx,
    sheet_ctx,
    templates,
)

router = APIRouter(prefix="/ui", include_in_schema=False)


def _estimate(value: str) -> int | None:
    """The sheet's estimate field: minutes, or empty for none."""
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise DomainError(f"Not an estimate: {value}") from exc


def _priority(value: str) -> TaskPriority | None:
    """The sheet's priority field: its value, or empty for none."""
    return tasks_svc.parse_priority(value)


def _row_response(
    request: Request,
    db,  # noqa: ANN001
    task_id: int,
    *,
    expanded: bool = False,
) -> HTMLResponse:
    task = tasks_svc.get_task(db, task_id)
    context = {"request": request, "row": row_ctx(task, datetime.now()), "expanded": expanded}
    return templates.TemplateResponse(request, "partials/task_row.html", context)


def _add_task(
    db,  # noqa: ANN001
    *,
    title: str,
    notes: str = "",
    planned_for: str = "",
    due: str = "",
    repeat: str = "none",
    project_id: str = "",
    workstream_id: str = "",
    done: bool = False,
    estimate: str = "",
    priority: str = "",
):
    """A new task as written (quick-add, the task sheet, the notepad's rows),
    its repeat set."""
    task = tasks_svc.create_task(
        db,
        title=title,
        notes=notes,
        planned_for=date.fromisoformat(planned_for) if planned_for else None,
        due=date.fromisoformat(due) if due else None,
        project_id=int(project_id) if project_id else None,
        workstream_id=int(workstream_id) if workstream_id else None,
        status=TaskStatus.done if done else TaskStatus.todo,
        estimate_minutes=_estimate(estimate),
        priority=_priority(priority),
    )
    _apply_task_repeat(db, task, repeat)
    return task


@router.post("/tasks/quick-add")
def quick_add(
    request: Request,
    db: DbSession,
    title: Annotated[str, Form()],
    notes: Annotated[str, Form()] = "",
    planned_for: Annotated[str, Form()] = "",
    due: Annotated[str, Form()] = "",
    repeat: Annotated[str, Form()] = "none",
    project_id: Annotated[str, Form()] = "",
    workstream_id: Annotated[str, Form()] = "",
    list_day: Annotated[str, Form()] = "",
    estimate: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "",
):
    title = title.strip()
    if not title:
        return HTMLResponse("")
    task = _add_task(
        db, title=title, notes=notes, planned_for=planned_for, due=due, repeat=repeat,
        project_id=project_id, workstream_id=workstream_id, estimate=estimate, priority=priority,
    )
    db.commit()
    if list_day and task.planned_for != date.fromisoformat(list_day):
        # Dated away from the list it was written in: it does not join that
        # list, and the page regroups; tasks.js carries the composer.
        response = HTMLResponse("")
        response.headers["HX-Trigger"] = "tasks:changed"
        return response
    response = _row_response(request, db, task.id)
    # Only the page's open count follows; a full list refresh would re-render
    # the composer and pull focus out of it mid-entry.
    response.headers["HX-Trigger"] = "task:added"
    return response


@router.post("/tasks/{task_id}/plan")
def plan_task(db: DbSession, task_id: int, planned_for: Annotated[str, Form()] = ""):
    """Give a task its do-date, or clear it with an empty value."""
    tasks_svc.update_task(
        db, task_id, planned_for=date.fromisoformat(planned_for) if planned_for else None
    )
    db.commit()
    response = HTMLResponse("")
    # Projects' list re-renders, the row naming its new day.
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
    return _row_response(request, db, task_id, expanded=True)


@router.post("/tasks/{task_id}/toggle")
def toggle_task(request: Request, db: DbSession, task_id: int):
    task = tasks_svc.get_task(db, task_id)
    new_status = TaskStatus.todo if task.status == TaskStatus.done else TaskStatus.done
    tasks_svc.set_status(db, task_id, new_status)
    db.commit()
    response = _row_response(request, db, task_id)
    response.headers["HX-Trigger"] = "calendar:refresh"  # keeps Today's open count honest
    return response


@router.get("/tasks/{task_id}/edit")
def edit_task(request: Request, db: DbSession, task_id: int):
    task = tasks_svc.get_task(db, task_id)
    context = {"request": request, "mode": "edit", "sheet": sheet_ctx(db, task, date.today())}
    return templates.TemplateResponse(request, "partials/task_sheet.html", context)


@router.get("/tasks/{task_id}/row")
def task_row(request: Request, db: DbSession, task_id: int):
    return _row_response(request, db, task_id)


def _save_task(
    db,  # noqa: ANN001
    task_id: int,
    *,
    title: str,
    status: TaskStatus,
    owner: TaskOwner,
    notes: str,
    project_id: str,
    workstream_id: str,
    planned_for: str,
    due: str,
    repeat: str,
    estimate: str,
    priority: str,
) -> None:
    """A task as its sheet (or its page) holds it."""
    task = tasks_svc.update_task(
        db,
        task_id,
        title=title,
        notes=notes,
        status=status,
        owner=owner,
        project_id=int(project_id) if project_id else None,
        workstream_id=int(workstream_id) if workstream_id else None,
        planned_for=date.fromisoformat(planned_for) if planned_for else None,
        due=date.fromisoformat(due) if due else None,
        estimate_minutes=_estimate(estimate),
        priority=_priority(priority),
    )
    _apply_task_repeat(db, task, repeat)
    db.commit()


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
    due: Annotated[str, Form()] = "",
    repeat: Annotated[str, Form()] = "none",
    estimate: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "",
):
    _save_task(
        db, task_id, title=title, status=status, owner=owner, notes=notes,
        project_id=project_id, workstream_id=workstream_id, planned_for=planned_for,
        due=due, repeat=repeat, estimate=estimate, priority=priority,
    )
    response = _row_response(request, db, task_id)
    # Its day or estimate may have changed: lists grouped or filtered by day,
    # and the days' loads on the time grid, re-render.
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


@router.post("/tasks/{task_id}/page", status_code=204)
def save_task_page(
    db: DbSession,
    task_id: int,
    title: Annotated[str, Form()],
    status: Annotated[TaskStatus, Form()],
    owner: Annotated[TaskOwner, Form()],
    notes: Annotated[str, Form()] = "",
    project_id: Annotated[str, Form()] = "",
    workstream_id: Annotated[str, Form()] = "",
    planned_for: Annotated[str, Form()] = "",
    due: Annotated[str, Form()] = "",
    repeat: Annotated[str, Form()] = "none",
    estimate: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "",
) -> None:
    """A task's page, saved as it is written (task-sheet.js): nothing to draw
    again, the page already shows what it holds."""
    _save_task(
        db, task_id, title=title, status=status, owner=owner, notes=notes,
        project_id=project_id, workstream_id=workstream_id, planned_for=planned_for,
        due=due, repeat=repeat, estimate=estimate, priority=priority,
    )


@router.post("/tasks/{task_id}/delete")
def delete_task(db: DbSession, task_id: int, back: Annotated[str, Form()] = ""):
    tasks_svc.delete_task(db, task_id)
    db.commit()
    response = HTMLResponse("")
    if back:
        # Deleted from its own page: back to where it was opened from.
        response.headers["HX-Redirect"] = back_link(back)["href"]
        return response
    # The days' loads on the time grid (and on Today, the list and its open
    # count) re-render from the server.
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


def _projects_changed() -> HTMLResponse:
    """The lists that show projects draw themselves again from the server:
    Projects' timeline, a project's Tasks, Plan, and the sidebar's projects."""
    response = HTMLResponse("")
    response.headers["HX-Trigger"] = "tasks:changed, projects:changed"
    return response


@router.post("/projects")
def create_project(db: DbSession, name: str = Form(...)):
    projects_svc.create_project(db, name=name)
    db.commit()
    return _projects_changed()


@router.get("/rail/projects")
def rail_projects(request: Request, current: int | None = None):
    """The sidebar's projects, drawn again as one changes (rail_projects.html)."""
    return templates.TemplateResponse(
        request, "partials/rail_projects.html", {"request": request, "current": current}
    )


class RailLayout(BaseModel):
    sections: list[str]
    modules: dict[str, list[str]]
    hidden: list[str]


@router.put("/rail", status_code=204)
def save_rail(db: DbSession, layout: RailLayout) -> None:
    """The sidebar as it now stands, a section or module dragged, hidden or
    brought back: shell.js has it so on the page already, and this keeps it."""
    rail_svc.save_layout(
        db, sections=layout.sections, modules=layout.modules, hidden=layout.hidden
    )
    db.commit()


class ProjectOrder(BaseModel):
    ids: list[int]


@router.put("/projects/order", status_code=204)
def order_projects(db: DbSession, order: ProjectOrder) -> None:
    """The active projects in the order they were dragged to in the sidebar."""
    projects_svc.reorder_projects(db, order.ids)
    db.commit()


@router.post("/projects/{project_id}/fold", status_code=204)
def fold_project(db: DbSession, project_id: int, folded: Annotated[bool, Form()]) -> None:
    """A project on Projects' timeline folded to its row, its workstreams
    out of sight, or open again: tasks.js folds it on the page at once, and
    this keeps it so through the timeline's next render."""
    projects_svc.update_project(db, project_id, folded=folded)
    db.commit()


@router.post("/projects/{project_id}/workstreams")
def add_workstream(db: DbSession, project_id: int, name: str = Form(...)):
    """A workstream added on the project's Tasks: its list, and the
    timeline and Gantt, draw it from the server."""
    projects_svc.create_workstream(db, project_id=project_id, name=name)
    db.commit()
    return _tasks_changed()


@router.post("/workstreams/{workstream_id}/toggle")
def toggle_workstream(db: DbSession, workstream_id: int):
    """A workstream done, folding to the finished ones' line, or open again."""
    workstream = projects_svc.get_workstream(db, workstream_id)
    done = workstream.status == WorkstreamStatus.done
    projects_svc.update_workstream(
        db, workstream_id, status=WorkstreamStatus.open if done else WorkstreamStatus.done
    )
    db.commit()
    return _tasks_changed()


def _tasks_changed() -> HTMLResponse:
    response = HTMLResponse("")
    response.headers["HX-Trigger"] = "tasks:changed"
    return response


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
    "planned_for", "due", "repeat", "project_id", "workstream_id", "estimate", "priority",
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
        task = _add_task(
            db, title=title, notes=str(written.get("notes", "")),
            planned_for=fields["planned_for"], due=fields["due"],
            repeat=fields["repeat"] or "none", project_id=fields["project_id"],
            workstream_id=fields["workstream_id"], done=written.get("done") is True,
            estimate=fields["estimate"], priority=fields["priority"],
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


@router.post("/day-sheet")
async def day_sheet_edit(request: Request, db: DbSession, start: date):
    """Calendar's sheet, written in (day_sheet.js): {"ops": [...]}, each
    one of
        {"op": "habit", "day", "slug", "done"}    a habit done that day, or not
        {"op": "stay", "day", "name", "value"?, "done"?}   an item of its stay
        {"op": "task", "day", "title"}            a task planned for the day
        {"op": "toggle", "task"}                  a task's box clicked: to do, in
                                                  progress, done, then to do again
        {"op": "status", "task", "status"}        a task's status, from its menu
        {"op": "delete", "task"}                  a task deleted
    applied in order, as the day's notes and tasks would have them; answers
    the sheet drawn again, naming the last task written (X-Task-Created) for
    the sheet to open its page."""
    from app.services import notebook as notebook_svc
    from app.ui.day_sheet_view import day_sheet_ctx

    body = await request.json()
    ops = body.get("ops") if isinstance(body, dict) else None
    if not isinstance(ops, list):
        raise DomainError("Expected a list of ops")
    created = None
    for op in ops:
        if not isinstance(op, dict):
            raise DomainError(f"Not an op: {op!r}")
        kind = op.get("op")
        if kind == "toggle":
            task = tasks_svc.get_task(db, int(op["task"]))
            following = {TaskStatus.in_progress: TaskStatus.done, TaskStatus.done: TaskStatus.todo}
            tasks_svc.set_status(db, task.id, following.get(task.status, TaskStatus.in_progress))
            continue
        if kind == "status":
            try:
                status = TaskStatus(str(op.get("status")))
            except ValueError as exc:
                raise DomainError(f"Not a status: {op.get('status')!r}") from exc
            tasks_svc.set_status(db, int(op["task"]), status)
            continue
        if kind == "delete":
            tasks_svc.delete_task(db, int(op["task"]))
            continue
        try:
            day = date.fromisoformat(str(op.get("day")))
        except ValueError as exc:
            raise DomainError(f"Not a day: {op.get('day')!r}") from exc
        if kind == "habit":
            notebook_svc.set_habit(db, day, str(op.get("slug")), op.get("done") is True)
        elif kind == "stay":
            value, done = op.get("value"), op.get("done")
            notebook_svc.set_stay_item(
                db, day, str(op.get("name", "")),
                value=None if value is None else str(value),
                done=None if done is None else done is True,
            )
        elif kind == "task":
            title = str(op.get("title", "")).strip()
            if title:
                created = tasks_svc.create_task(db, title=title, planned_for=day)
        else:
            raise DomainError(f"Unknown op: {kind!r}")
    db.commit()
    response = templates.TemplateResponse(
        request,
        "partials/day_sheet.html",
        {"request": request, "sheet": day_sheet_ctx(db, start, date.today())},
    )
    if created is not None:
        response.headers["X-Task-Created"] = str(created.id)
    return response


@router.get("/tasks/{task_id}/history")
def task_history(request: Request, db: DbSession, task_id: int):
    """How the task changed, newest first, for its sheet."""
    from app.services import history as history_svc
    from app.ui.views import history_ctx

    steps = history_ctx(history_svc.changes(db, task_id), date.today())
    return templates.TemplateResponse(
        request, "partials/task_history.html", {"request": request, "steps": steps}
    )
