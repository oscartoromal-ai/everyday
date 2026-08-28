from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import (
    MilestoneIn,
    MilestoneOut,
    MilestonePatch,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
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


@router.get("/{project_id}/milestones")
def list_milestones(project_id: int, db: DbSession) -> list[MilestoneOut]:
    project = projects_svc.get_project(db, project_id)
    return [MilestoneOut.model_validate(m) for m in project.milestones]


@router.post("/{project_id}/milestones", status_code=201)
def create_milestone(
    project_id: int, body: MilestoneIn, db: DbSession
) -> MilestoneOut:
    return MilestoneOut.model_validate(
        projects_svc.create_milestone(db, project_id=project_id, **body.model_dump())
    )


@router.patch("/milestones/{milestone_id}")
def update_milestone(
    milestone_id: int, body: MilestonePatch, db: DbSession
) -> MilestoneOut:
    return MilestoneOut.model_validate(
        projects_svc.update_milestone(db, milestone_id, **body.model_dump(exclude_unset=True))
    )
