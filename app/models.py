"""Domain models per SPEC.md section 4.

All datetimes are naive local wall time. Dates (planned_for, due, starts_on,
occurrence_date) are calendar dates.
"""

from __future__ import annotations

import enum
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ProjectStatus(enum.StrEnum):
    active = "active"
    paused = "paused"
    done = "done"


class WorkstreamStatus(enum.StrEnum):
    open = "open"
    done = "done"


class TaskStatus(enum.StrEnum):
    todo = "todo"
    in_progress = "in_progress"
    blocked = "blocked"
    needs_review = "needs_review"
    done = "done"
    cancelled = "cancelled"


class TaskPriority(enum.StrEnum):
    """How much a task matters against the others, most first. A task need
    not have one: none is no priority."""

    urgent = "urgent"
    high = "high"
    medium = "medium"
    low = "low"

    @property
    def label(self) -> str:
        """Its word as the app writes it: "High"."""
        return self.value.capitalize()


class TaskOwner(enum.StrEnum):
    oscar = "oscar"
    claude = "claude"


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


# How many colours a project can have: the design's hues, --hue-1 to --hue-8.
PROJECT_COLORS = 8


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[ProjectStatus] = mapped_column(
        _enum(ProjectStatus), default=ProjectStatus.active
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    # Its colour: one of the design's hues, 1 to PROJECT_COLORS (--hue-N).
    color: Mapped[int] = mapped_column(Integer, default=1)
    # Its card folded to its header (Projects, Tasks by project): kept here,
    # so it holds through the lists' re-renders and on every device.
    folded: Mapped[bool] = mapped_column(Boolean, default=False)
    # Its place among the projects (Projects, the sidebar): a new one last,
    # moved by dragging it in the sidebar.
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    workstreams: Mapped[list[Workstream]] = relationship(
        back_populates="project", order_by=lambda: [Workstream.position, Workstream.id]
    )
    tasks: Mapped[list[Task]] = relationship(back_populates="project")
    repos: Mapped[list[ProjectRepo]] = relationship(
        back_populates="project", order_by="ProjectRepo.id", cascade="all, delete-orphan"
    )
    docs: Mapped[list[ProjectDoc]] = relationship(
        back_populates="project", order_by="ProjectDoc.id", cascade="all, delete-orphan"
    )
    doc_folders: Mapped[list[ProjectDocFolder]] = relationship(
        back_populates="project", order_by="ProjectDocFolder.id", cascade="all, delete-orphan"
    )


class ProjectRepo(Base):
    """A repository the project's work lives in: where it is, a local path
    or a URL, as written."""

    __tablename__ = "project_repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    location: Mapped[str] = mapped_column(String(1000))

    project: Mapped[Project] = relationship(back_populates="repos")


# The document every project has, first among its context: what an agent
# working on the project reads before anything else.
AGENTS_DOC = "AGENTS.md"


class ProjectDocFolder(Base):
    """A folder of the project's context, as a folder on disk: its documents
    and its subfolders, named once among what sits beside it."""

    __tablename__ = "project_doc_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    # The folder it is in; none at the context's top.
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_doc_folders.id"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    # Folded on the project's page, its contents hidden: kept here, so it
    # holds through the tree's re-renders and on every device.
    folded: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped[Project] = relationship(back_populates="doc_folders")
    parent: Mapped[ProjectDocFolder | None] = relationship(
        back_populates="children", remote_side=[id]
    )
    children: Mapped[list[ProjectDocFolder]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    docs: Mapped[list[ProjectDoc]] = relationship(back_populates="folder")

    @property
    def path(self) -> str:
        """Where it is in the context, as a path: "decisions/adr"."""
        return f"{self.parent.path}/{self.name}" if self.parent else self.name


class ProjectDoc(Base):
    """A document of the project's context, in Markdown, for Oscar and the
    agents working on it: its AGENTS.md, and any others he writes, at the
    context's top or in a folder."""

    __tablename__ = "project_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_doc_folders.id"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    project: Mapped[Project] = relationship(back_populates="docs")
    folder: Mapped[ProjectDocFolder | None] = relationship(back_populates="docs")

    @property
    def is_agents(self) -> bool:
        return self.name == AGENTS_DOC and self.folder_id is None

    @property
    def path(self) -> str:
        """Where it is in the context, as a path: "decisions/adr/0001.md"."""
        return f"{self.folder.path}/{self.name}" if self.folder else self.name


class Workstream(Base):
    """A stream of a project's work, run beside its others: a lane of its
    tasks, with no date of its own; its span is its tasks'."""

    __tablename__ = "workstreams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[WorkstreamStatus] = mapped_column(
        _enum(WorkstreamStatus), default=WorkstreamStatus.open
    )
    # Its place among its project's workstreams (the Gantt's lanes, the
    # Projects page): a new one last, moved on the Gantt.
    position: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship(back_populates="workstreams")
    tasks: Mapped[list[Task]] = relationship(back_populates="workstream")


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
    workstream_id: Mapped[int | None] = mapped_column(ForeignKey("workstreams.id"), default=None)
    planned_for: Mapped[date | None] = mapped_column(Date, default=None)
    due: Mapped[date | None] = mapped_column(Date, default=None)
    # The day its work starts, on its project's Gantt: its bar runs from that
    # day to its due, so a task with one always has a due.
    starts_on: Mapped[date | None] = mapped_column(Date, default=None)
    # Its place among its workstream's tasks (or its project's other tasks) on
    # the Gantt, lowest first; None for one never moved, after those, oldest first.
    position: Mapped[int | None] = mapped_column(Integer, default=None)
    recurrence_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurrence_templates.id"), default=None
    )
    occurrence_date: Mapped[date | None] = mapped_column(Date, default=None)
    # The day whose notebook page it was written on, if it was written in one.
    written_on: Mapped[date | None] = mapped_column(Date, default=None)
    # How long its work is thought to take, in minutes: its weight in a day's plan.
    estimate_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    # How much it matters against the others; None for no priority.
    priority: Mapped[TaskPriority | None] = mapped_column(_enum(TaskPriority), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # When the current status was entered; drives the needs_review-age nudge.
    status_changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    project: Mapped[Project | None] = relationship(back_populates="tasks")
    workstream: Mapped[Workstream | None] = relationship(back_populates="tasks")
    # A nudge is about its task; deleting the task retires its nudges with it.
    nudges: Mapped[list[Nudge]] = relationship(back_populates="task", cascade="all, delete-orphan")
    recurrence_template: Mapped[RecurrenceTemplate | None] = relationship()


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

    @property
    def cancelled(self) -> bool:
        """A meeting called off but left in the feed: Outlook publishes it with
        its subject prefixed "Canceled: ". It takes no time."""
        return CANCELLED_PREFIX.match(self.title) is not None

    @property
    def shown_title(self) -> str:
        """The title without a cancelled meeting's prefix, which its look says."""
        return CANCELLED_PREFIX.sub("", self.title, count=1)


CANCELLED_PREFIX = re.compile(r"^\s*cancell?ed\s*:\s*", re.IGNORECASE)


class NudgeType(enum.StrEnum):
    due_soon = "due_soon"
    needs_review = "needs_review"
    # A bill of Finances coming due, not yet paid.
    bill_due = "bill_due"


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
    # The window whose save it was ("" for any other writer) and that save's
    # number: a window's later save stands over its own earlier one.
    writer: Mapped[str] = mapped_column(String(40), default="")
    writer_seq: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Habit(Base):
    """Something Oscar tracks doing, day by day (morning skin care,
    exercise): written in a day's notes as "/habit morning-skin-care", which
    checks it for that day. Its days say when it is meant to happen: the
    weekdays it is due, Monday 0 to Sunday 6 ("0123456" every day, "1" only
    Tuesdays), or "" for any day; a due day with no check is a miss."""

    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    days: Mapped[str] = mapped_column(String(7), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    checks: Mapped[list[HabitCheck]] = relationship(
        back_populates="habit", cascade="all, delete-orphan", passive_deletes=True
    )


class HabitCheck(Base):
    """A habit on a day: done, or skipped (its box unticked), with what Oscar
    wrote about it. Kept by the day's notebook page, which is where it is
    written: one per habit per day."""

    __tablename__ = "habit_checks"
    __table_args__ = (
        UniqueConstraint("habit_id", "day"),
        Index("ix_habit_checks_day", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    done: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    habit: Mapped[Habit] = relationship(back_populates="checks")


class Sex(enum.StrEnum):
    female = "female"
    male = "male"


class ActivityLevel(enum.StrEnum):
    sedentary = "sedentary"
    light = "light"
    moderate = "moderate"
    active = "active"
    very_active = "very_active"


class WeightGoal(enum.StrEnum):
    lose = "lose"
    maintain = "maintain"
    gain = "gain"


class HealthProfile(Base):
    """Oscar himself, as the context health advice needs (Health > Me): his
    body, how active he is and what he is aiming for, what he eats and
    cannot, and notes. One row; his weight is its own log (WeightEntry)."""

    __tablename__ = "health_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    height_cm: Mapped[float | None] = mapped_column(Float, default=None)
    birth_date: Mapped[date | None] = mapped_column(Date, default=None)
    sex: Mapped[Sex | None] = mapped_column(_enum(Sex), default=None)
    activity: Mapped[ActivityLevel | None] = mapped_column(_enum(ActivityLevel), default=None)
    goal: Mapped[WeightGoal | None] = mapped_column(_enum(WeightGoal), default=None)
    target_weight_kg: Mapped[float | None] = mapped_column(Float, default=None)
    diet: Mapped[str] = mapped_column(Text, default="")
    allergies: Mapped[str] = mapped_column(Text, default="")
    avoids: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class WeightEntry(Base):
    """Oscar's weight on a day: one per day, the last written kept."""

    __tablename__ = "weight_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True)
    weight_kg: Mapped[float] = mapped_column(Float)


class ChatRole(enum.StrEnum):
    oscar = "oscar"
    claude = "claude"


class AgentKind(enum.StrEnum):
    """The agents the agent window chats with, each through its own CLI on
    this machine's sign-in (app/services/agents.py)."""

    claude = "claude"
    codex = "codex"


class AgentRole(enum.StrEnum):
    oscar = "oscar"
    agent = "agent"


class AgentConversation(Base):
    """One chat in the agent window, with one agent. The window shows the
    latest; New chat starts another, and an earlier one is kept."""

    __tablename__ = "agent_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent: Mapped[AgentKind] = mapped_column(_enum(AgentKind))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    messages: Mapped[list[AgentMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AgentMessage.id"
    )


class AgentMessage(Base):
    """One message of a chat in the agent window, Oscar's or the agent's."""

    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[AgentRole] = mapped_column(_enum(AgentRole))
    text: Mapped[str] = mapped_column(Text)
    # The agent's answer did not finish (an error, or the run was cut short).
    failed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    conversation: Mapped[AgentConversation] = relationship(back_populates="messages")


class NutritionMessage(Base):
    """One message of a day's chat on Nutrition, Oscar's or Claude's. The
    chat is the day's: each day starts a fresh one, the day's log file
    carrying what came of the days before."""

    __tablename__ = "nutrition_messages"
    __table_args__ = (Index("ix_nutrition_messages_day", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    role: Mapped[ChatRole] = mapped_column(_enum(ChatRole))
    text: Mapped[str] = mapped_column(Text)
    # Claude's answer did not finish (an error, or the run was cut short).
    failed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class GarminLink(Base):
    """The link to Oscar's Garmin Connect account (Health > Garmin): who is
    signed in and how the last sync went. One row while connected. Garmin's
    sign-in token is not here but in local/ (config [garmin].token_dir),
    beside the app's other secrets; his password is never kept."""

    __tablename__ = "garmin_link"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, default="")
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # The last sync that finished, and why the last one failed ("" when it did not).
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    sync_error: Mapped[str] = mapped_column(Text, default="")


class GarminDay(Base):
    """What Oscar's Garmin measured on a day, as Garmin Connect sums it: his
    steps, energy, heart, stress and body battery that day, and the sleep
    that ended that morning, with its HRV and the readiness that followed.
    A figure Garmin did not have is None. Today's is so far, redrawn each
    sync."""

    __tablename__ = "garmin_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True)
    steps: Mapped[int | None] = mapped_column(Integer, default=None)
    step_goal: Mapped[int | None] = mapped_column(Integer, default=None)
    distance_m: Mapped[float | None] = mapped_column(Float, default=None)
    # Energy burned: all of it (resting and active), and the active part.
    total_kcal: Mapped[int | None] = mapped_column(Integer, default=None)
    active_kcal: Mapped[int | None] = mapped_column(Integer, default=None)
    moderate_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    vigorous_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    resting_hr: Mapped[int | None] = mapped_column(Integer, default=None)
    stress_avg: Mapped[int | None] = mapped_column(Integer, default=None)
    body_battery_high: Mapped[int | None] = mapped_column(Integer, default=None)
    body_battery_low: Mapped[int | None] = mapped_column(Integer, default=None)
    sleep_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    deep_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    light_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    rem_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    awake_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    sleep_score: Mapped[int | None] = mapped_column(Integer, default=None)
    # Garmin's word for the score: EXCELLENT, GOOD, FAIR or POOR.
    sleep_quality: Mapped[str | None] = mapped_column(String(32), default=None)
    # Overnight HRV (ms): last night's average, the 7-day average, and
    # Garmin's status for it (BALANCED, UNBALANCED, LOW, POOR).
    hrv_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    hrv_week_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    hrv_status: Mapped[str | None] = mapped_column(String(32), default=None)
    # Training readiness on waking, 0-100, and its level (LOW ... PRIME).
    readiness: Mapped[int | None] = mapped_column(Integer, default=None)
    readiness_level: Mapped[str | None] = mapped_column(String(32), default=None)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class GarminActivity(Base):
    """An activity Oscar recorded on his Garmin (a run, a ride, a strength
    session), as Garmin Connect has it."""

    __tablename__ = "garmin_activities"
    __table_args__ = (Index("ix_garmin_activities_day", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    garmin_id: Mapped[int] = mapped_column(Integer, unique=True)
    day: Mapped[date] = mapped_column(Date)
    start: Mapped[datetime] = mapped_column(DateTime)
    name: Mapped[str] = mapped_column(Text, default="")
    # Garmin's type key: running, cycling, strength_training, walking...
    kind: Mapped[str] = mapped_column(String(64), default="")
    duration_s: Mapped[int | None] = mapped_column(Integer, default=None)
    distance_m: Mapped[float | None] = mapped_column(Float, default=None)
    kcal: Mapped[int | None] = mapped_column(Integer, default=None)
    avg_hr: Mapped[int | None] = mapped_column(Integer, default=None)
    max_hr: Mapped[int | None] = mapped_column(Integer, default=None)


# ---- Repositories (SPEC.md, GitHub) ----


class GitHubSource(enum.StrEnum):
    # The GitHub CLI's own sign-in, asked for at each sync and never copied.
    cli = "cli"
    # A token pasted on Repositories, kept in local/ ([github].tokens_dir).
    token = "token"


# Which connected account reaches which repository: a repository his two
# accounts both reach is one repository, reached by both.
github_link_repositories = Table(
    "github_link_repositories",
    Base.metadata,
    Column("link_id", ForeignKey("github_link.id", ondelete="CASCADE"), primary_key=True),
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True),
)


class GitHubLink(Base):
    """A GitHub account of Oscar's, connected (Repositories): who is signed
    in, how, and how its last sync went. One row per account. No token is
    here: the CLI keeps its own, and a pasted one is in local/."""

    __tablename__ = "github_link"
    __table_args__ = (Index("ix_github_link_user_id", "user_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[GitHubSource] = mapped_column(_enum(GitHubSource))
    # GitHub's id for the account, which a rename keeps; None for an
    # account connected before the app kept it, until its next sync.
    user_id: Mapped[int | None] = mapped_column(Integer, default=None)
    login: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(Text, default="")
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # The last sync that finished, and why the last one failed ("" when it did not).
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    sync_error: Mapped[str] = mapped_column(Text, default="")
    # GitHub stopped accepting the sign-in (or gh signed out): connect again.
    signed_out: Mapped[bool] = mapped_column(Boolean, default=False)

    repositories: Mapped[list[Repository]] = relationship(
        secondary=github_link_repositories, back_populates="links"
    )


class Repository(Base):
    """A GitHub repository Oscar can reach, as GitHub has it at the last
    sync: his own, those he collaborates on, and his organizations'; kept
    while any of his accounts reaches it."""

    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int] = mapped_column(Integer, unique=True)
    # owner/name, as GitHub writes it; its page is html_url.
    full_name: Mapped[str] = mapped_column(String(200))
    owner: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    private: Mapped[bool] = mapped_column(Boolean, default=True)
    fork: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # Its main language, as GitHub detects it ("" when none).
    language: Mapped[str] = mapped_column(String(64), default="")
    default_branch: Mapped[str] = mapped_column(String(255), default="")
    html_url: Mapped[str] = mapped_column(Text, default="")
    # Open issues and pull requests together, as GitHub counts them.
    open_issues: Mapped[int] = mapped_column(Integer, default=0)
    # The last push to any branch, local time; None for one never pushed to.
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    # The accounts that reach it, connected first first.
    links: Mapped[list[GitHubLink]] = relationship(
        secondary=github_link_repositories, back_populates="repositories",
        order_by="GitHubLink.id",
    )


# ---- Finances (SPEC.md, Finances): money in whole cents, Australian dollars ----


class AccountKind(enum.StrEnum):
    everyday = "everyday"
    savings = "savings"
    credit_card = "credit_card"
    loan = "loan"
    super = "super"
    investment = "investment"
    other = "other"


# What is owed rather than owned: its balance counts against net worth.
LIABILITY_KINDS = frozenset({AccountKind.credit_card, AccountKind.loan})


class CategoryKind(enum.StrEnum):
    spending = "spending"
    income = "income"
    # Money moved between his own accounts: neither spent nor earned.
    transfer = "transfer"


class BillCadence(enum.StrEnum):
    weekly = "weekly"
    fortnightly = "fortnightly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class MoneyAccount(Base):
    """An account of Oscar's: a bank account (Revolut, ING), a card, a loan,
    his super or his shares."""

    __tablename__ = "money_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[AccountKind] = mapped_column(_enum(AccountKind), default=AccountKind.everyday)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class MoneyBalance(Base):
    """An account's balance at the end of a day, in cents: read from an
    import's last row, or written by hand. Owed is negative."""

    __tablename__ = "money_balances"
    __table_args__ = (UniqueConstraint("account_id", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("money_accounts.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    cents: Mapped[int] = mapped_column(Integer)
    # "import" or "hand".
    source: Mapped[str] = mapped_column(String(16), default="hand")


class MoneyCategory(Base):
    """What money is spent on (Groceries), comes from (Salary), or a move
    between his own accounts; a spending category may have a budget a month."""

    __tablename__ = "money_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    kind: Mapped[CategoryKind] = mapped_column(_enum(CategoryKind), default=CategoryKind.spending)
    budget_cents: Mapped[int | None] = mapped_column(Integer, default=None)


class MoneyImport(Base):
    """A bank's CSV export, imported into an account."""

    __tablename__ = "money_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("money_accounts.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(Text, default="")
    # Whose format it was: "revolut" or "ing".
    bank: Mapped[str] = mapped_column(String(16))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    added: Mapped[int] = mapped_column(Integer, default=0)
    # Rows already imported before, and rows left out (pending, declined,
    # another currency).
    known: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)


class MoneyTransaction(Base):
    """Money in (positive) or out (negative) of an account on a day, as the
    bank's export has it, and what it was for."""

    __tablename__ = "money_transactions"
    __table_args__ = (
        UniqueConstraint("account_id", "fingerprint"),
        Index("ix_money_transactions_day", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("money_accounts.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text)
    cents: Mapped[int] = mapped_column(Integer)
    # The bank's own word for it, when it gives one (Revolut: CARD_PAYMENT,
    # TOPUP, TRANSFER...).
    bank_type: Mapped[str] = mapped_column(String(32), default="")
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("money_categories.id", ondelete="SET NULL"), default=None
    )
    note: Mapped[str] = mapped_column(Text, default="")
    # The row's identity within its account, so an export imported twice,
    # or two that overlap, add each transaction once.
    fingerprint: Mapped[str] = mapped_column(String(40))
    import_id: Mapped[int | None] = mapped_column(
        ForeignKey("money_imports.id", ondelete="SET NULL"), default=None
    )

    category: Mapped[MoneyCategory | None] = relationship(lazy="joined")
    account: Mapped[MoneyAccount] = relationship(lazy="joined")


class MoneyRule(Base):
    """A transaction whose description holds `pattern` (in any case) is
    sorted into the rule's category as it is imported."""

    __tablename__ = "money_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(String(120), unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("money_categories.id", ondelete="CASCADE"))

    category: Mapped[MoneyCategory] = relationship(lazy="joined")


class MoneyBill(Base):
    """A bill or subscription that comes round: its amount, how often, and
    when it is next due. A transaction whose description holds `match`
    near a due day pays it."""

    __tablename__ = "money_bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    cents: Mapped[int] = mapped_column(Integer)
    cadence: Mapped[BillCadence] = mapped_column(_enum(BillCadence), default=BillCadence.monthly)
    # A day it falls due; every other follows from it by the cadence.
    due: Mapped[date] = mapped_column(Date)
    match: Mapped[str] = mapped_column(String(120), default="")


class MoneyGoal(Base):
    """Money to save toward: kept in an account (its balance is the
    progress), or counted by hand."""

    __tablename__ = "money_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    target_cents: Mapped[int] = mapped_column(Integer)
    by: Mapped[date | None] = mapped_column(Date, default=None)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("money_accounts.id", ondelete="SET NULL"), default=None
    )
    saved_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    account: Mapped[MoneyAccount | None] = relationship(lazy="joined")


class MoneyMessage(Base):
    """One message of a month's chat on Spending, Oscar's or Claude's."""

    __tablename__ = "money_messages"
    __table_args__ = (Index("ix_money_messages_month", "month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The month's first day.
    month: Mapped[date] = mapped_column(Date)
    role: Mapped[ChatRole] = mapped_column(_enum(ChatRole))
    text: Mapped[str] = mapped_column(Text)
    failed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Setting(Base):
    """One of the app's own settings, kept by name, so it holds on every
    device: the sidebar's layout ("rail", app/services/rail.py)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
