"""Recurrence: rule expansion and materialization of concrete occurrence rows.

Each occurrence is its own task/event row (individually checkable and editable)
carrying its template reference and occurrence date. Materialization only ever
fills dates beyond the template's newest existing occurrence (the frontier), so
deleting one occurrence never resurrects it.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import checklist
from app.models import (
    Event,
    EventSource,
    RecurrenceFrequency,
    RecurrenceKind,
    RecurrenceTemplate,
    Task,
    TaskStatus,
)
from app.services import DomainError

HORIZON_WEEKS = 8

WEEKDAY_PRESETS = {
    "daily": (RecurrenceFrequency.daily, ""),
    "weekdays": (RecurrenceFrequency.weekly, "1,2,3,4,5"),
    "weekly": (RecurrenceFrequency.weekly, ""),
    "monthly": (RecurrenceFrequency.monthly, ""),
}


def rule_dates(template: RecurrenceTemplate, start: date, end: date) -> list[date]:
    """Occurrence dates of `template` within [start, end], both inclusive."""
    lo = max(start, template.start_date)
    hi = min(end, template.until) if template.until else end
    if hi < lo:
        return []
    out: list[date] = []
    if template.frequency == RecurrenceFrequency.daily:
        offset = (lo - template.start_date).days
        remainder = offset % template.interval
        current = lo if remainder == 0 else lo + timedelta(days=template.interval - remainder)
        while current <= hi:
            out.append(current)
            current += timedelta(days=template.interval)
    elif template.frequency == RecurrenceFrequency.weekly:
        weekdays = (
            {int(d) for d in template.weekdays.split(",") if d}
            if template.weekdays
            else {template.start_date.isoweekday()}
        )
        anchor_week = template.start_date - timedelta(days=template.start_date.weekday())
        current = lo
        while current <= hi:
            weeks_since = (current - timedelta(days=current.weekday()) - anchor_week).days // 7
            if current.isoweekday() in weekdays and weeks_since % template.interval == 0:
                out.append(current)
            current += timedelta(days=1)
    elif template.frequency == RecurrenceFrequency.monthly:
        day_of_month = template.start_date.day
        year, month = lo.year, lo.month
        while True:
            months_since = (year - template.start_date.year) * 12 + (
                month - template.start_date.month
            )
            if months_since % template.interval == 0:
                try:
                    candidate = date(year, month, day_of_month)
                except ValueError:
                    candidate = None  # e.g. 31st in a short month: skipped
                if candidate and lo <= candidate <= hi:
                    out.append(candidate)
            if (year, month) >= (hi.year, hi.month):
                break
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def create_template(
    db: Session,
    *,
    kind: RecurrenceKind,
    repeat: str,
    start_date: date,
    title: str,
    notes: str = "",
    project_id: int | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    all_day: bool = False,
    interval: int = 1,
) -> RecurrenceTemplate:
    if repeat not in WEEKDAY_PRESETS:
        raise DomainError(f"Unknown repeat rule: {repeat}")
    frequency, weekdays = WEEKDAY_PRESETS[repeat]
    template = RecurrenceTemplate(
        kind=kind,
        frequency=frequency,
        weekdays=weekdays,
        interval=interval,
        start_date=start_date,
        title=title.strip(),
        notes=notes,
        project_id=project_id,
        start_time=start_time,
        end_time=end_time,
        all_day=all_day,
    )
    db.add(template)
    db.flush()
    return template


def preset_of(template: RecurrenceTemplate) -> str:
    """The WEEKDAY_PRESETS key that produced this template's rule."""
    if template.frequency == RecurrenceFrequency.daily:
        return "daily"
    if template.frequency == RecurrenceFrequency.monthly:
        return "monthly"
    return "weekdays" if template.weekdays == "1,2,3,4,5" else "weekly"


def _frontier(db: Session, template: RecurrenceTemplate) -> date | None:
    model = Task if template.kind == RecurrenceKind.task else Event
    return db.scalar(
        select(func.max(model.occurrence_date)).where(
            model.recurrence_template_id == template.id
        )
    )


def _spawn_occurrence(db: Session, template: RecurrenceTemplate, day: date) -> None:
    if template.kind == RecurrenceKind.task:
        db.add(
            Task(
                title=template.title,
                # Each occurrence starts with its sub-tasks open.
                notes=checklist.reset(template.notes),
                project_id=template.project_id,
                planned_for=day,
                recurrence_template_id=template.id,
                occurrence_date=day,
            )
        )
    else:
        if template.all_day or not template.start_time or not template.end_time:
            start = datetime.combine(day, time.min)
            end = start + timedelta(days=1)
            all_day = True
        else:
            start = datetime.combine(day, time.fromisoformat(template.start_time))
            end = datetime.combine(day, time.fromisoformat(template.end_time))
            all_day = False
        db.add(
            Event(
                title=template.title,
                start=start,
                end=end,
                all_day=all_day,
                source=EventSource.local,
                recurrence_template_id=template.id,
                occurrence_date=day,
            )
        )


def materialize_template(db: Session, template: RecurrenceTemplate, today: date) -> int:
    """Create missing occurrence rows out to the rolling horizon; returns count."""
    horizon_end = today + timedelta(weeks=HORIZON_WEEKS)
    frontier = _frontier(db, template)
    window_start = max(today, frontier + timedelta(days=1)) if frontier else today
    created = 0
    for day in rule_dates(template, window_start, horizon_end):
        _spawn_occurrence(db, template, day)
        created += 1
    db.flush()
    return created


def materialize_all(db: Session, today: date | None = None) -> int:
    today = today or date.today()
    created = 0
    for template in db.scalars(
        select(RecurrenceTemplate).where(RecurrenceTemplate.active.is_(True))
    ):
        created += materialize_template(db, template, today)
    return created


def stop_template(db: Session, template_id: int, *, from_date: date) -> None:
    """Deactivate a template and drop its pristine future occurrences."""
    template = db.get(RecurrenceTemplate, template_id)
    if template is None:
        raise DomainError(f"Recurrence template {template_id} does not exist")
    template.active = False
    _drop_pristine_future(db, template, from_date)
    db.flush()


def _drop_pristine_future(
    db: Session, template: RecurrenceTemplate, from_date: date
) -> None:
    if template.kind == RecurrenceKind.task:
        tasks = list(
            db.scalars(
                select(Task).where(
                    Task.recurrence_template_id == template.id,
                    Task.occurrence_date > from_date,
                    Task.status == TaskStatus.todo,
                )
            )
        )
        for task in tasks:
            db.delete(task)
    else:
        for event in db.scalars(
            select(Event).where(
                Event.recurrence_template_id == template.id,
                Event.occurrence_date > from_date,
            )
        ):
            db.delete(event)
