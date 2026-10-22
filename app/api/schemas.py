"""Pydantic request/response shapes for the REST API (and reused by MCP tools)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.models import (
    EventSource,
    ProjectStatus,
    PullRequestState,
    TaskOwner,
    TaskPriority,
    TaskStatus,
    WorkstreamStatus,
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


class WorkstreamIn(BaseModel):
    name: str


class WorkstreamPatch(BaseModel):
    name: str | None = None
    status: WorkstreamStatus | None = None


class WorkstreamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    status: WorkstreamStatus


class TaskIn(BaseModel):
    title: str
    notes: str = ""
    acceptance: str = ""
    owner: TaskOwner = TaskOwner.oscar
    status: TaskStatus = TaskStatus.todo
    project_id: int | None = None
    workstream_id: int | None = None
    planned_for: date | None = None
    due: date | None = None
    starts_on: date | None = None
    estimate_minutes: int | None = None
    priority: TaskPriority | None = None


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    notes: str | None = None
    owner: TaskOwner | None = None
    status: TaskStatus | None = None
    project_id: int | None = None
    workstream_id: int | None = None
    planned_for: date | None = None
    due: date | None = None
    starts_on: date | None = None
    estimate_minutes: int | None = None
    priority: TaskPriority | None = None
    acceptance: str | None = None
    outcome: str | None = None
    # Some of its project's repositories' locations: the ones it is worked in.
    repos: list[str] | None = None


class PullRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    repo: str
    number: int
    title: str
    # unknown (not read from GitHub yet), draft, open, merged or closed.
    state: PullRequestState


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # The agent system it was launched on, and its id there.
    runner: str
    run_id: str
    # working, waiting (on Oscar), finished, failed or gone, as the runner last had it.
    state: str
    branch: str
    workspace: str
    started_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    notes: str
    status: TaskStatus
    owner: TaskOwner
    project_id: int | None
    workstream_id: int | None
    planned_for: date | None
    due: date | None
    starts_on: date | None = None
    estimate_minutes: int | None = None
    priority: TaskPriority | None = None
    acceptance: str = ""
    outcome: str = ""
    repos: list[str] = []
    pull_requests: list[PullRequestOut] = []
    runs: list[RunOut] = []
    # Its folder in the everyday files (app.services.task_files), its
    # task.md there (the task as a file: its words are the file's), and
    # each of its other files' path in the folder.
    files_folder: str = ""
    task_file: str = ""
    files: list[str] = []

    @field_validator("repos", mode="before")
    @classmethod
    def _locations(cls, repos: Any) -> Any:
        return [getattr(r, "location", r) for r in repos or []]


class ReportIn(BaseModel):
    """An agent's word on a task's work (SPEC.md, Agent runs): any of these."""

    model_config = ConfigDict(extra="forbid")

    # How far it got: in_progress, blocked or needs_review (never done).
    status: TaskStatus | None = None
    # A word on the work as it goes, kept in the task's updates.
    note: str | None = None
    # What came of it, in Markdown: written over the outcome it had.
    outcome: str | None = None
    # Its pull requests, each a URL on GitHub (or owner/name#number).
    pull_requests: list[str] | str | None = None


class LaunchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The agent system to hand it to; the configured one ([runs] runner) when left out.
    runner: str | None = None


class WorkLineOut(BaseModel):
    # What it was: a task (with its project), else a project (its work on no
    # task of its), else a terminal filed under nothing (its session).
    task_id: int | None
    project_id: int | None
    session_id: int | None
    # Oscar at it, its agents working, and its agents waiting on him.
    you_seconds: int
    working_seconds: int
    blocked_seconds: int
    # The terminals it was worked in.
    sessions: int


class WorkDayOut(BaseModel):
    day: date
    lines: list[WorkLineOut]


class WorkFileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The task to file it under; null, under none.
    task_id: int | None


class WorkSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    terminal_id: str
    workspace: str
    cwd: str
    agent: str
    agent_session: str
    title: str
    task_id: int | None
    project_id: int | None
    filed_by: str
    started_at: datetime
    seen_at: datetime
    ended_at: datetime | None


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


class CalendarOut(BaseModel):
    events: list[EventOut]
