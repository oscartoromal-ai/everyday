"""Domain models per SPEC.md section 4.

All datetimes are naive local wall time. Dates (planned_for, due, target_date,
occurrence_date) are calendar dates.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ProjectStatus(enum.StrEnum):
    active = "active"
    paused = "paused"
    done = "done"


class MilestoneStatus(enum.StrEnum):
    open = "open"
    reached = "reached"
    dropped = "dropped"


class TaskStatus(enum.StrEnum):
    todo = "todo"
    in_progress = "in_progress"
    blocked = "blocked"
    needs_review = "needs_review"
    done = "done"
    cancelled = "cancelled"


class TaskOwner(enum.StrEnum):
    oscar = "oscar"
    claude = "claude"


class BlockState(enum.StrEnum):
    planned = "planned"
    completed = "completed"
    missed = "missed"


class EventSource(enum.StrEnum):
    local = "local"
    work = "work"


class RecurrenceKind(enum.StrEnum):
    task = "task"
    event = "event"


class RecurrenceFrequency(enum.StrEnum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


def _enum(e: type[enum.StrEnum]) -> Enum:
    return Enum(e, native_enum=False, values_callable=lambda x: [m.value for m in x])


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[ProjectStatus] = mapped_column(
        _enum(ProjectStatus), default=ProjectStatus.active
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    milestones: Mapped[list[Milestone]] = relationship(back_populates="project")
    tasks: Mapped[list[Task]] = relationship(back_populates="project")


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(200))
    target_date: Mapped[date | None] = mapped_column(Date, default=None)
    status: Mapped[MilestoneStatus] = mapped_column(
        _enum(MilestoneStatus), default=MilestoneStatus.open
    )

    project: Mapped[Project] = relationship(back_populates="milestones")
    tasks: Mapped[list[Task]] = relationship(back_populates="milestone")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("recurrence_template_id", "occurrence_date"),
        Index("ix_tasks_planned_for", "planned_for"),
        Index("ix_tasks_due", "due"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_written_on", "written_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TaskStatus] = mapped_column(_enum(TaskStatus), default=TaskStatus.todo)
    owner: Mapped[TaskOwner] = mapped_column(_enum(TaskOwner), default=TaskOwner.oscar)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), default=None)
    milestone_id: Mapped[int | None] = mapped_column(ForeignKey("milestones.id"), default=None)
    planned_for: Mapped[date | None] = mapped_column(Date, default=None)
    due: Mapped[date | None] = mapped_column(Date, default=None)
    recurrence_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurrence_templates.id"), default=None
    )
    occurrence_date: Mapped[date | None] = mapped_column(Date, default=None)
    # The day whose notebook page it was written on, if it was written in one.
    written_on: Mapped[date | None] = mapped_column(Date, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # When the current status was entered; drives the needs_review-age nudge.
    status_changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    project: Mapped[Project | None] = relationship(back_populates="tasks")
    milestone: Mapped[Milestone | None] = relationship(back_populates="tasks")
    blocks: Mapped[list[Block]] = relationship(back_populates="task", cascade="all, delete-orphan")
    # A nudge is about its task; deleting the task retires its nudges with it.
    nudges: Mapped[list[Nudge]] = relationship(back_populates="task", cascade="all, delete-orphan")
    recurrence_template: Mapped[RecurrenceTemplate | None] = relationship()


class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (
        Index("ix_blocks_start", "start"),
        Index("ix_blocks_state", "state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    state: Mapped[BlockState] = mapped_column(_enum(BlockState), default=BlockState.planned)

    task: Mapped[Task] = relationship(back_populates="blocks")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        UniqueConstraint("recurrence_template_id", "occurrence_date"),
        Index("ix_events_start", "start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    location: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[EventSource] = mapped_column(_enum(EventSource), default=EventSource.local)
    read_only: Mapped[bool] = mapped_column(Boolean, default=False)
    external_id: Mapped[str | None] = mapped_column(String(500), default=None)
    recurrence_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurrence_templates.id"), default=None
    )
    occurrence_date: Mapped[date | None] = mapped_column(Date, default=None)

    recurrence_template: Mapped[RecurrenceTemplate | None] = relationship()


class NudgeType(enum.StrEnum):
    missed_block = "missed_block"
    due_soon = "due_soon"
    milestone_soon = "milestone_soon"
    needs_review = "needs_review"


class Nudge(Base):
    __tablename__ = "nudges"
    __table_args__ = (UniqueConstraint("dedup_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[NudgeType] = mapped_column(_enum(NudgeType))
    # One nudge per underlying fact: an evaluation never re-raises a dedup key,
    # dismissed or not.
    dedup_key: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(String(500))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    task: Mapped[Task | None] = relationship(back_populates="nudges")


class RecurrenceTemplate(Base):
    __tablename__ = "recurrence_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[RecurrenceKind] = mapped_column(_enum(RecurrenceKind))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Rule
    frequency: Mapped[RecurrenceFrequency] = mapped_column(_enum(RecurrenceFrequency))
    interval: Mapped[int] = mapped_column(Integer, default=1)
    # Weekly only: comma-separated ISO weekday numbers, "1"=Monday .. "7"=Sunday.
    weekdays: Mapped[str] = mapped_column(String(20), default="")
    start_date: Mapped[date] = mapped_column(Date)
    until: Mapped[date | None] = mapped_column(Date, default=None)

    # Prototype fields copied onto each materialized occurrence.
    title: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str] = mapped_column(Text, default="")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), default=None)
    # Event templates only: time of day for the occurrence, or all-day.
    start_time: Mapped[str | None] = mapped_column(String(5), default=None)  # "HH:MM"
    end_time: Mapped[str | None] = mapped_column(String(5), default=None)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskRevision(Base):
    """One step in a task's history: the task as it stood after a change, and
    who made it. app.services.history writes one on every flush that creates,
    changes or deletes a task, whichever path made the change (the UI, REST,
    MCP, a job), and keeps them after the task itself is deleted."""

    __tablename__ = "task_revisions"
    __table_args__ = (Index("ix_task_revisions_task", "task_id", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Not a foreign key: the history outlives the task.
    task_id: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime)
    change: Mapped[str] = mapped_column(String(20))  # created / updated / deleted / baseline
    actor: Mapped[str] = mapped_column(String(20))  # oscar / claude / system
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)


class NotebookPage(Base):
    """A day's notebook page: what Oscar wrote on that day, in order. Prose
    stays as written, tasks are referenced by id and render as they stand
    now, and reflections are free text (block shapes: app.services.notebook)."""

    __tablename__ = "notebook_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True)
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Bumped by every save; a save made from an older copy is refused.
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
