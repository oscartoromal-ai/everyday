"""Full-page routes for the server-rendered UI."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.db import DbSession
from app.ui.calendar_view import grid_ctx, tray_tasks, week_monday
from app.ui.views import (
    TASKS_VIEWS,
    day_page_ctx,
    projects_list_ctx,
    tasks_page_ctx,
    templates,
)
from app.ui.weeks_view import LAYOUTS, weeks_ctx

router = APIRouter(include_in_schema=False)


def _base(request: Request, active: str) -> dict:
    return {"request": request, "active": active, "today": date.today()}


TASKS_VIEW_COOKIE = "tasks_view"


@router.get("/")
def tasks_page(request: Request, db: DbSession, view: str | None = None):
    # The app opens here: planning (giving tasks days) comes before doing.
    chosen = view or request.cookies.get(TASKS_VIEW_COOKIE)
    view = chosen if chosen in TASKS_VIEWS else TASKS_VIEWS[0]
    response = templates.TemplateResponse(
        request,
        "tasks.html",
        {**_base(request, "tasks"), **tasks_page_ctx(db, datetime.now(), view)},
    )
    response.set_cookie(TASKS_VIEW_COOKIE, view, max_age=60 * 60 * 24 * 365, samesite="strict")
    return response


@router.get("/today")
def today_page(request: Request, db: DbSession):
    return _day_page(request, db, date.today())


@router.get("/day/{day}")
def day_page(request: Request, db: DbSession, day: date):
    if day == date.today():
        return RedirectResponse("/today", status_code=303)
    return _day_page(request, db, day)


def _day_page(request: Request, db: DbSession, day: date):
    """A day's page: its notebook beside its timeline. Today's is /today."""
    from app.services import nudges as nudges_svc

    now = datetime.now()
    return templates.TemplateResponse(
        request,
        "today.html",
        {
            **_base(request, "today"),
            **day_page_ctx(db, day, now),
            "nudges": nudges_svc.active_nudges(db, now) if day == now.date() else [],
            "grid": grid_ctx(db, day, now, day_count=1),
        },
    )


@router.get("/next")
def next_days_page():
    # The multi-week planner's rows layout supersedes the old seven-day list.
    return RedirectResponse("/weeks?layout=rows", status_code=301)


LAYOUT_COOKIE = "weeks_layout"


def _weeks_layout(request: Request, layout: str | None) -> str:
    chosen = layout or request.cookies.get(LAYOUT_COOKIE)
    return chosen if chosen in LAYOUTS else LAYOUTS[0]


@router.get("/weeks")
def weeks_page(
    request: Request, db: DbSession, start: date | None = None, layout: str | None = None
):
    layout = _weeks_layout(request, layout)
    response = templates.TemplateResponse(
        request,
        "weeks.html",
        {
            **_base(request, "weeks"),
            "plan": weeks_ctx(db, start or date.today(), date.today()),
            "layout": layout,
        },
    )
    response.set_cookie(LAYOUT_COOKIE, layout, max_age=60 * 60 * 24 * 365, samesite="strict")
    return response


@router.get("/weeks/board")
def weeks_board(
    request: Request, db: DbSession, start: date | None = None, layout: str | None = None
):
    return templates.TemplateResponse(
        request,
        "partials/weeks_board.html",
        {
            "request": request,
            "today": date.today(),
            "plan": weeks_ctx(db, start or date.today(), date.today()),
            "layout": _weeks_layout(request, layout),
        },
    )


@router.get("/backlog")
def backlog_page():
    # Tasks' No date group is the backlog, beside everything already dated.
    return RedirectResponse("/", status_code=301)


@router.get("/calendar")
def calendar_page(request: Request, db: DbSession, week: date | None = None):
    now = datetime.now()
    week_start = week_monday(week or date.today())
    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            **_base(request, "calendar"),
            "grid": grid_ctx(db, week_start, now),
            "tray": tray_tasks(db, week_start, now),
        },
    )


@router.get("/calendar/grid")
def calendar_grid(
    request: Request,
    db: DbSession,
    start: date | None = None,
    days: Annotated[int, Query(ge=1, le=7)] = 7,
):
    now = datetime.now()
    start = start or date.today()
    if days == 7:
        start = week_monday(start)
    return templates.TemplateResponse(
        request,
        "partials/calendar_grid.html",
        {"request": request, "grid": grid_ctx(db, start, now, day_count=days)},
    )


@router.get("/projects")
def projects_page(request: Request, db: DbSession):
    return templates.TemplateResponse(
        request,
        "projects.html",
        {**_base(request, "projects"), **projects_list_ctx(db, datetime.now())},
    )
