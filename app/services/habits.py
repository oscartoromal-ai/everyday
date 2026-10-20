"""Habits: things Oscar tracks doing, day by day.

A habit is written in a day's notes ("/habit morning-skin-care"), which
checks it for that day: done, or skipped when its box is unticked, with
what he wrote about it. The day's notebook page keeps its checks
(sync_day, on every save of the page). Its days say when it is meant to
happen, so a due day with no check reads as missed (grid).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Habit, HabitCheck
from app.services import DomainError

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
EVERY_DAY = "0123456"
WEEKDAYS = "01234"


def clean_slug(slug: Any) -> str:
    """A habit's name as it is kept: lower case, words joined by hyphens."""
    if not isinstance(slug, str):
        raise DomainError("A habit's name must be text")
    cleaned = slug.strip().lower()
    if not SLUG.match(cleaned):
        raise DomainError(f"Not a habit name: {slug!r} (letters, digits and hyphens)")
    return cleaned


def clean_days(days: Any) -> str:
    """Weekdays as kept: each of Monday 0 to Sunday 6 at most once, in order;
    "" for any day."""
    if not isinstance(days, str) or any(d not in EVERY_DAY for d in days):
        raise DomainError(f"Not a set of weekdays: {days!r} (0 Monday to 6 Sunday)")
    return "".join(sorted(set(days)))


def list_habits(db: Session) -> list[Habit]:
    return list(db.scalars(select(Habit).order_by(Habit.slug)))


def get_or_create(db: Session, slug: str) -> Habit:
    slug = clean_slug(slug)
    habit = db.scalars(select(Habit).where(Habit.slug == slug)).first()
    if habit is None:
        habit = Habit(slug=slug, days="")
        db.add(habit)
        db.flush()
    return habit


def set_days(db: Session, slug: str, days: str) -> Habit:
    habit = get_or_create(db, slug)
    habit.days = clean_days(days)
    db.flush()
    return habit


def is_due(habit: Habit, day: date) -> bool:
    """Meant to happen that day: any day, or one of its weekdays."""
    return not habit.days or str(day.weekday()) in habit.days


def sync_day(db: Session, day: date, written: list[dict[str, Any]]) -> dict[str, int]:
    """The day's checks as its page has them: `written` is each habit block
    on it ({habit: name, done, text}); a habit written twice counts once
    (done if either is). Checks for habits no longer on the page go, and a
    habit left with no checks and no days of its own (a name typed on the
    way to another) goes with them. Returns each written name's habit id."""
    wanted: dict[int, tuple[bool, str]] = {}
    ids: dict[str, int] = {}
    for block in written:
        habit = get_or_create(db, block["habit"])
        ids[habit.slug] = habit.id
        done, note = wanted.get(habit.id, (False, ""))
        wanted[habit.id] = (done or block["done"], note or block["text"].strip())
    existing = {c.habit_id: c for c in db.scalars(select(HabitCheck).where(HabitCheck.day == day))}
    now = datetime.now()
    for habit_id, (done, note) in wanted.items():
        check = existing.pop(habit_id, None)
        if check is None:
            db.add(HabitCheck(habit_id=habit_id, day=day, done=done, note=note, updated_at=now))
        elif (check.done, check.note) != (done, note):
            check.done, check.note, check.updated_at = done, note, now
    for check in existing.values():
        db.delete(check)
    db.flush()
    unused = select(Habit.id).where(
        Habit.days == "", ~Habit.checks.any(), Habit.id.notin_(list(wanted))
    )
    db.execute(delete(Habit).where(Habit.id.in_(unused)))
    db.flush()
    return ids


def grid(db: Session, start: date, days: int) -> list[dict[str, Any]]:
    """Each habit over `days` days from `start`, day by day: "done",
    "skipped" (written, its box unticked), "missed" (one of its days, since
    it began, not written, the day past) or None (not due, any day's habit
    not written, or today still open), with the day's note."""
    habits = list_habits(db)
    end = start + timedelta(days=days - 1)
    checks = {
        (c.habit_id, c.day): c
        for c in db.scalars(
            select(HabitCheck).where(HabitCheck.day >= start, HabitCheck.day <= end)
        )
    }
    today = date.today()
    out = []
    for habit in habits:
        row = []
        for i in range(days):
            day = start + timedelta(days=i)
            check = checks.get((habit.id, day))
            if check is not None:
                state = "done" if check.done else "skipped"
            elif habit.days and is_due(habit, day) and habit.created_at.date() <= day < today:
                state = "missed"
            else:
                state = None
            row.append({"day": day, "state": state, "note": check.note if check else ""})
        out.append({"slug": habit.slug, "days": habit.days, "checks": row})
    return out


def standing(db: Session, day: date, days: int = 6, reach: int = 366) -> dict[str, dict[str, Any]]:
    """How each habit comes into `day`, by name: its last `days` days before
    it, as the grid reads them ([{day, state}], oldest first), and its
    streak, the days in a row it was done up to the day before (a day it is
    not meant to happen passed over, any other day not done ending it),
    looking back `reach` days at most."""
    out = {}
    for row in grid(db, day - timedelta(days=reach), reach):
        streak = 0
        for check in reversed(row["checks"]):
            off_day = row["days"] and str(check["day"].weekday()) not in row["days"]
            if check["state"] == "done":
                streak += 1
            elif check["state"] is None and off_day:
                continue
            else:
                break
        week = row["checks"][-days:]
        out[row["slug"]] = {
            "week": [{"day": c["day"].isoformat(), "state": c["state"]} for c in week],
            "streak": streak,
        }
    return out
