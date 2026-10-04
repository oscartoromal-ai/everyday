"""Full-page routes for the server-rendered UI."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.db import DbSession
from app.models import Task
from app.ui import changelog_view
from app.ui.calendar_view import (
    VIEWS,
    calendar_nav,
    grid_ctx,
    home_anchor,
    range_label,
    view_start,
)
from app.ui.day_sheet_view import day_sheet_ctx
from app.ui.views import (
    day_glance_ctx,
    day_page_ctx,
    projects_page_ctx,
    task_page_ctx,
    templates,
)

router = APIRouter(include_in_schema=False)


def _base(request: Request, active: str) -> dict:
    return {"request": request, "active": active, "today": date.today()}


@router.get("/")
def home():
    # The app opens on the day: what is on, and the notes to write it in.
    return RedirectResponse("/today", status_code=303)


@router.get("/today")
def today_page(request: Request, db: DbSession):
    return _day_page(request, db, date.today())


@router.get("/today/glance")
def today_glance(request: Request, db: DbSession):
    # Today's glance, redrawn each minute and as the calendar changes.
    now = datetime.now()
    return templates.TemplateResponse(
        request,
        "partials/day_glance.html",
        {"request": request, "glance": day_glance_ctx(db, now.date(), now)},
    )


@router.get("/day/{day}")
def day_page(request: Request, db: DbSession, day: date):
    if day == date.today():
        return RedirectResponse("/today", status_code=303)
    return _day_page(request, db, day)


def _day_page(request: Request, db: DbSession, day: date):
    """A day's page: its notepad beside its timeline. Today's is /today,
    and opens with the nudge center."""
    from app.services import nudges as nudges_svc

    now = datetime.now()
    return templates.TemplateResponse(
        request,
        "today.html",
        {
            **_base(request, "today"),
            **day_page_ctx(db, day, now),
            "grid": grid_ctx(db, day, now, day_count=1),
            "nudges": [
                {"id": n.id, "type": n.type.value, "task_id": n.task_id,
                 "message": nudges_svc.wording(db, n, day)}
                for n in (nudges_svc.active_nudges(db) if day == now.date() else [])
            ],
        },
    )


@router.get("/backlog")
def backlog_page():
    # The backlog is Projects' tasks without a day.
    return RedirectResponse("/projects", status_code=301)


@router.get("/changelog")
def changelog_page(request: Request):
    # Every version and what it changed, from Settings.
    ctx = changelog_view.page_ctx(date.today())
    return templates.TemplateResponse(
        request, "changelog.html", {**_base(request, "changelog"), **ctx}
    )


CALENDAR_VIEW_COOKIE = "calendar_view"


def _calendar_view(request: Request, view: str | None) -> str:
    """The view asked for, else the one last chosen on this device, else a
    week, or three days on a phone, where seven columns cannot be read."""
    chosen = view or request.cookies.get(CALENDAR_VIEW_COOKIE)
    if chosen == "sheet" and not view and "new" in request.query_params:
        # A new event is written on the time grid: the sheet stays the choice.
        chosen = "week"
    if chosen in VIEWS:
        return chosen
    return "3days" if "Mobi" in request.headers.get("user-agent", "") else "week"


@router.get("/calendar")
def calendar_page(
    request: Request,
    db: DbSession,
    start: date | None = None,
    week: date | None = None,  # the week view's earlier links
    view: str | None = None,
):
    now = datetime.now()
    view = _calendar_view(request, view)
    first_day = view_start(view, start or week or home_anchor(view, now.date()))
    days = VIEWS[view]
    ctx = {**_base(request, "calendar"), "nav": calendar_nav(view, first_day, now.date())}
    if view == "sheet":
        ctx["sheet"] = day_sheet_ctx(db, first_day, now.date(), days)
    else:
        # Each day headed, a single one too: its head carries its load.
        ctx["grid"] = grid_ctx(db, first_day, now, days, head=True)
    ctx["label"] = range_label(first_day, days)
    response = templates.TemplateResponse(request, "calendar.html", ctx)
    if view in (request.query_params.get("view"), request.cookies.get(CALENDAR_VIEW_COOKIE)):
        # Remembered once chosen; a phone's own default stays a default.
        response.set_cookie(
            CALENDAR_VIEW_COOKIE, view, max_age=60 * 60 * 24 * 365, samesite="strict"
        )
    return response


@router.get("/calendar/grid")
def calendar_grid(
    request: Request,
    db: DbSession,
    start: date | None = None,
    days: Annotated[int, Query(ge=1, le=7)] = 7,
    head: bool | None = None,
):
    now = datetime.now()
    start = start or date.today()
    if days == VIEWS["week"]:
        start = view_start("week", start)
    return templates.TemplateResponse(
        request,
        "partials/calendar_grid.html",
        {"request": request, "grid": grid_ctx(db, start, now, day_count=days, head=head)},
    )


@router.get("/calendar/sheet")
def calendar_sheet(request: Request, db: DbSession, start: date | None = None):
    # The sheet drawn again: notes written elsewhere since (day_sheet.js).
    today = date.today()
    first_day = view_start("sheet", start or home_anchor("sheet", today))
    return templates.TemplateResponse(
        request,
        "partials/day_sheet.html",
        {"request": request, "sheet": day_sheet_ctx(db, first_day, today)},
    )


@router.get("/projects")
def projects_page(request: Request, db: DbSession):
    # Every open task, filed under its project, for giving tasks days.
    return templates.TemplateResponse(
        request,
        "projects.html",
        {**_base(request, "projects"), **projects_page_ctx(db, datetime.now())},
    )


@router.get("/tasks/{task_id}")
def task_page(request: Request, db: DbSession, task_id: int, back: str = ""):
    """A task on its own page, for one too long for its row: its title, its
    fields and its description written at length. It goes back to the page
    it was opened from."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "No such task: it may have been deleted")
    ctx = task_page_ctx(db, task, date.today(), back or request.headers.get("referer", ""))
    return templates.TemplateResponse(request, "task.html", {**_base(request, "task"), **ctx})
