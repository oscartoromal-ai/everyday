"""Pydantic request/response shapes for the REST API (and reused by MCP tools)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models import (
    BlockState,
    EventSource,
    MilestoneStatus,
    ProjectStatus,
    TaskOwner,
    TaskStatus,
)


class ProjectIn(BaseModel):
    name: str
    notes: str = ""
    color: int | None = None  # 1 to 8; the least used one when left out


class ProjectPatch(BaseModel):
    name: str | None = None
    status: ProjectStatus | None = None
    notes: str | None = None
    color: int | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: ProjectStatus
    notes: str
    color: int


class MilestoneIn(BaseModel):
    name: str
    target_date: date | None = None


class MilestonePatch(BaseModel):
    name: str | None = None
    target_date: date | None = None
    clear_target_date: bool = False
    status: MilestoneStatus | None = None


class MilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    target_date: date | None
    status: MilestoneStatus


class TaskIn(BaseModel):
    title: str
    notes: str = ""
    owner: TaskOwner = TaskOwner.oscar
    status: TaskStatus = TaskStatus.todo
    project_id: int | None = None
    milestone_id: int | None = None
    planned_for: date | None = None
    due: date | None = None


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    notes: str | None = None
    owner: TaskOwner | None = None
    status: TaskStatus | None = None
    project_id: int | None = None
    milestone_id: int | None = None
    planned_for: date | None = None
    due: date | None = None


class BlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    start: datetime
    end: datetime
    state: BlockState


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    notes: str
    status: TaskStatus
    owner: TaskOwner
    project_id: int | None
    milestone_id: int | None
    planned_for: date | None
    due: date | None
    missed: bool = False
    blocks: list[BlockOut] = []


class BlockIn(BaseModel):
    task_id: int
    start: datetime
    end: datetime


class BlockMove(BaseModel):
    start: datetime
    end: datetime


class EventIn(BaseModel):
    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str = ""


class EventPatch(BaseModel):
    title: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool | None = None
    location: str | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str
    source: EventSource
    read_only: bool


class CalendarBlockOut(BlockOut):
    task_title: str


class CalendarOut(BaseModel):
    events: list[EventOut]
    blocks: list[CalendarBlockOut]
    ghosts: list[CalendarBlockOut]
