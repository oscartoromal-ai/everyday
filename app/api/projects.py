from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.schemas import (
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    WorkstreamIn,
    WorkstreamOut,
    WorkstreamPatch,
)
from app.db import DbSession
from app.models import ProjectStatus
from app.services import projects as projects_svc

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def list_projects(
    db: DbSession, status: ProjectStatus | None = None
) -> list[ProjectOut]:
    return [ProjectOut.model_validate(p) for p in projects_svc.list_projects(db, status=status)]


@router.post("", status_code=201)
def create_project(body: ProjectIn, db: DbSession) -> ProjectOut:
    return ProjectOut.model_validate(projects_svc.create_project(db, **body.model_dump()))


@router.patch("/{project_id}")
def update_project(
    project_id: int, body: ProjectPatch, db: DbSession
) -> ProjectOut:
    return ProjectOut.model_validate(
        projects_svc.update_project(db, project_id, **body.model_dump(exclude_unset=True))
    )


@router.get("/{project_id}/context")
def project_context(project_id: int, db: DbSession) -> dict[str, Any]:
    """What an agent working on the project is given: the project, its
    repositories, its folders, and its documents in full, AGENTS.md first,
    each with its path among the folders."""
    return projects_svc.project_context(projects_svc.get_project(db, project_id))


@router.get("/{project_id}/workstreams")
def list_workstreams(project_id: int, db: DbSession) -> list[WorkstreamOut]:
    project = projects_svc.get_project(db, project_id)
    return [WorkstreamOut.model_validate(m) for m in project.workstreams]


@router.post("/{project_id}/workstreams", status_code=201)
def create_workstream(
    project_id: int, body: WorkstreamIn, db: DbSession
) -> WorkstreamOut:
    return WorkstreamOut.model_validate(
        projects_svc.create_workstream(db, project_id=project_id, **body.model_dump())
    )


@router.patch("/workstreams/{workstream_id}")
def update_workstream(
    workstream_id: int, body: WorkstreamPatch, db: DbSession
) -> WorkstreamOut:
    return WorkstreamOut.model_validate(
        projects_svc.update_workstream(db, workstream_id, **body.model_dump(exclude_unset=True))
    )
