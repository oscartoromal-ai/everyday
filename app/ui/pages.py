"""Full-page routes for the server-rendered UI."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Request

from app.db import DbSession
from app.models import TaskOwner
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.ui.calendar_view import grid_ctx, tray_tasks, week_monday
from app.ui.views import human_date, row_ctx, short_date, templates, today_page_tasks

router = APIRouter(include_in_schema=False)


def _base(request: Request, active: str) -> dict:
    return {"request": request, "active": active, "today": date.today()}


@router.get("/")
def today_page(request: Request, db: DbSession):
    from app.services import nudges as nudges_svc

    now = datetime.now()
    oscar_rows, delegated_rows = today_page_tasks(db, now)
    return templates.TemplateResponse(
        request,
        "today.html",
        {
            **_base(request, "today"),
            "rows": [row_ctx(t, now) for t in oscar_rows],
            "delegated": [row_ctx(t, now) for t in delegated_rows],
            "nudges": nudges_svc.active_nudges(db),
        },
    )


@router.get("/next")
def next_days_page(request: Request, db: DbSession):
    now = datetime.now()
    start = date.today() + timedelta(days=1)
    view = tasks_svc.next_days(db, start, days=7)
    day_groups = []
    for day, entries in view.items():
        seen: set[int] = set()
        rows = []
        for task in entries["planned"] + entries["due"]:
            if task.id not in seen:
                seen.add(task.id)
                rows.append(row_ctx(task, now))
        day_groups.append(
            {
                "day": day,
                "title": human_date(day),
                "relative": short_date(day),
                "rows": rows,
                "milestones": [
                    {"milestone": m, "project": m.project.name} for m in entries["milestones"]
                ],
            }
        )
    return templates.TemplateResponse(
        request, "next.html", {**_base(request, "next"), "day_groups": day_groups}
    )


@router.get("/backlog")
def backlog_page(request: Request, db: DbSession):
    now = datetime.now()
    rows = [row_ctx(t, now) for t in tasks_svc.backlog(db) if t.owner == TaskOwner.oscar]
    return templates.TemplateResponse(
        request, "backlog.html", {**_base(request, "backlog"), "rows": rows}
    )


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
def calendar_grid(request: Request, db: DbSession, week: date | None = None):
    now = datetime.now()
    week_start = week_monday(week or date.today())
    return templates.TemplateResponse(
        request,
        "partials/calendar_grid.html",
        {"request": request, "grid": grid_ctx(db, week_start, now)},
    )


@router.get("/projects")
def projects_page(request: Request, db: DbSession):
    projects = projects_svc.list_projects(db)
    cards = []
    for project in projects:
        milestones = [
            {
                "milestone": m,
                "progress": projects_svc.milestone_progress(db, m.id),
                "target_label": short_date(m.target_date) if m.target_date else None,
                "target_soon": bool(
                    m.target_date and m.target_date <= date.today() + timedelta(days=3)
                ),
            }
            for m in project.milestones
        ]
        open_tasks = [
            t for t in tasks_svc.list_tasks(db, project_id=project.id)
            if t.status in tasks_svc.OPEN_STATUSES
        ]
        cards.append(
            {"project": project, "milestones": milestones, "open_count": len(open_tasks)}
        )
    return templates.TemplateResponse(
        request, "projects.html", {**_base(request, "projects"), "cards": cards}
    )
