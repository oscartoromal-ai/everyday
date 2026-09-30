"""A project's Gantt: its page, its sheet drawn again, and the sheet's edits
(app.services.gantt.apply), each answered with the sheet as it now stands."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.db import DbSession
from app.services import gantt as gantt_svc
from app.services import projects as projects_svc
from app.ui.gantt_view import gantt_ctx
from app.ui.views import templates

router = APIRouter(include_in_schema=False)


@router.get("/projects/{project_id}")
def gantt_page(request: Request, db: DbSession, project_id: int):
    project = projects_svc.get_project(db, project_id)
    return templates.TemplateResponse(
        request,
        "gantt.html",
        {"request": request, "active": "projects", "today": date.today(),
         **gantt_ctx(db, project, date.today())},
    )


def _sheet(request: Request, db: DbSession, project_id: int) -> Response:
    project = projects_svc.get_project(db, project_id)
    ctx = {"request": request, **gantt_ctx(db, project, date.today())}
    return templates.TemplateResponse(request, "partials/gantt_sheet.html", ctx)


@router.get("/ui/projects/{project_id}/gantt")
def gantt_sheet(request: Request, db: DbSession, project_id: int):
    return _sheet(request, db, project_id)


class Edits(BaseModel):
    ops: list[dict[str, Any]]


@router.post("/ui/projects/{project_id}/gantt")
def gantt_edit(request: Request, db: DbSession, project_id: int, body: Edits):
    project = projects_svc.get_project(db, project_id)
    made = gantt_svc.apply(db, project, body.ops, date.today())
    db.commit()
    response = _sheet(request, db, project_id)
    # What the edits made, so the sheet can put its cursor on them and undo them.
    response.headers["X-Gantt-Made"] = ",".join(map(str, made))
    return response
