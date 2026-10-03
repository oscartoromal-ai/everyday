"""A project's Gantt: its page, its sheet drawn again (in weeks, or drilled
down to days), and the sheet's edits (app.services.gantt.apply), each
answered with the sheet as it now stands, in the scale it was seen in."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.db import DbSession
from app.services import gantt as gantt_svc
from app.services import projects as projects_svc
from app.ui.gantt_view import SCALES, gantt_ctx
from app.ui.views import templates

router = APIRouter(include_in_schema=False)

# The scale last chosen, for every project's Gantt.
SCALE_COOKIE = "gantt_scale"


def _scale(request: Request, scale: str | None) -> str:
    chosen = scale or request.cookies.get(SCALE_COOKIE)
    return chosen if chosen in SCALES else SCALES[0]


def _remember(response: Response, scale: str) -> Response:
    response.set_cookie(SCALE_COOKIE, scale, max_age=60 * 60 * 24 * 365, samesite="strict")
    return response


@router.get("/projects/{project_id}")
def gantt_page(request: Request, db: DbSession, project_id: int, scale: str | None = None):
    project = projects_svc.get_project(db, project_id)
    scale = _scale(request, scale)
    response = templates.TemplateResponse(
        request,
        "gantt.html",
        {"request": request, "active": "project", "today": date.today(),
         **gantt_ctx(db, project, date.today(), scale)},
    )
    return _remember(response, scale)


def _sheet(request: Request, db: DbSession, project_id: int, scale: str) -> Response:
    project = projects_svc.get_project(db, project_id)
    ctx = {"request": request, **gantt_ctx(db, project, date.today(), scale)}
    return templates.TemplateResponse(request, "partials/gantt_sheet.html", ctx)


@router.get("/ui/projects/{project_id}/gantt")
def gantt_sheet(request: Request, db: DbSession, project_id: int, scale: str | None = None):
    scale = _scale(request, scale)
    return _remember(_sheet(request, db, project_id, scale), scale)


class Edits(BaseModel):
    ops: list[dict[str, Any]]


@router.post("/ui/projects/{project_id}/gantt")
def gantt_edit(
    request: Request, db: DbSession, project_id: int, body: Edits, scale: str | None = None
):
    project = projects_svc.get_project(db, project_id)
    made = gantt_svc.apply(db, project, body.ops, date.today())
    db.commit()
    response = _sheet(request, db, project_id, _scale(request, scale))
    # What the edits made, so the sheet can put its cursor on them and undo them.
    response.headers["X-Gantt-Made"] = ",".join(map(str, made))
    return response
