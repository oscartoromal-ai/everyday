"""Habits: things Oscar tracks doing, day by day.

A habit is made on Today's habits pane or the Habits page (or by writing
its file, habits/<name>.md, in the everyday files), and ticked for a day on
the pane or on Calendar's sheet: a check, done. A comment on a day is the
day's entry in the habit's log, its file's words (app.services.habit_md);
a comment on a day not ticked says why it was skipped. Its days say when
it is meant to happen, so a due day with no check reads as missed (grid).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
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


def slug_of(name: Any) -> str:
    """A name as written made a habit's: "Morning skin care" is
    morning-skin-care."""
    if not isinstance(name, str):
        raise DomainError("A habit's name must be text")
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise DomainError("A habit needs a name")
    return clean_slug(slug[:80].strip("-"))


def clean_days(days: Any) -> str:
    """Weekdays as kept: each of Monday 0 to Sunday 6 at most once, in order;
    "" for any day."""
    if not isinstance(days, str) or any(d not in EVERY_DAY for d in days):
        raise DomainError(f"Not a set of weekdays: {days!r} (0 Monday to 6 Sunday)")
    return "".join(sorted(set(days)))


def list_habits(db: Session) -> list[Habit]:
    return list(db.scalars(select(Habit).order_by(Habit.slug)))


def find(db: Session, slug: str) -> Habit | None:
    return db.scalars(select(Habit).where(Habit.slug == slug)).first()


def get(db: Session, habit_id: int) -> Habit:
    habit = db.get(Habit, habit_id)
    if habit is None:
        raise DomainError(f"Habit {habit_id} does not exist")
    return habit


def get_or_create(db: Session, slug: str) -> Habit:
    slug = clean_slug(slug)
    habit = find(db, slug)
    if habit is None:
        habit = Habit(slug=slug, days="")
        db.add(habit)
        db.flush()
    return habit


def create(db: Session, name: str, days: str = "") -> Habit:
    """A new habit, its name made one (slug_of); refused when a habit has it."""
    slug = slug_of(name)
    if find(db, slug) is not None:
        raise DomainError(f"There is a habit {slug} already")
    habit = Habit(slug=slug, days=clean_days(days))
    db.add(habit)
    db.flush()
    return habit


def rename(db: Session, habit_id: int, name: str) -> Habit:
    """The habit called something else; its file follows (app.services.settling)."""
    habit = get(db, habit_id)
    slug = slug_of(name)
    other = find(db, slug)
    if other is not None and other.id != habit.id:
        raise DomainError(f"There is a habit {slug} already")
    habit.slug = slug
    db.flush()
    return habit


def delete(db: Session, habit_id: int) -> None:
    """The habit gone, with its checks; its file to the trash."""
    db.delete(get(db, habit_id))
    db.flush()


def set_days(db: Session, slug: str, days: str) -> Habit:
    habit = get_or_create(db, slug)
    habit.days = clean_days(days)
    db.flush()
    return habit


def is_due(habit: Habit, day: date) -> bool:
    """Meant to happen that day: any day, or one of its weekdays."""
    return not habit.days or str(day.weekday()) in habit.days


def check_of(db: Session, habit: Habit, day: date) -> HabitCheck | None:
    return db.scalars(
        select(HabitCheck).where(HabitCheck.habit_id == habit.id, HabitCheck.day == day)
    ).first()


def _settle_check(db: Session, habit: Habit, day: date, done: bool, note: str) -> None:
    """The day's check as it now stands: done, or a comment on a day not
    done (skipped); neither, no check at all."""
    check = check_of(db, habit, day)
    if not done and not note:
        if check is not None:
            db.delete(check)
    elif check is None:
        db.add(HabitCheck(habit_id=habit.id, day=day, done=done, note=note,
                          updated_at=datetime.now()))
    elif (check.done, check.note) != (done, note):
        check.done, check.note, check.updated_at = done, note, datetime.now()
    db.flush()


def set_done(db: Session, habit: Habit, day: date, done: bool) -> None:
    """The habit ticked for the day, or not; its comment stays either way
    (unticked, it says why the day was skipped)."""
    check = check_of(db, habit, day)
    _settle_check(db, habit, day, done, check.note if check else "")


def set_note(db: Session, habit: Habit, day: date, note: str) -> None:
    """The day's comment, its entry in the habit's log (empty: none). On a
    day not ticked it makes the day skipped."""
    note = "\n".join(line.rstrip() for line in note.replace("\r\n", "\n").split("\n")).strip()
    check = check_of(db, habit, day)
    _settle_check(db, habit, day, check.done if check else False, note)


def log_of(db: Session, habit: Habit) -> dict[date, str]:
    """The habit's comments by day: its log."""
    return {
        c.day: c.note
        for c in db.scalars(select(HabitCheck).where(HabitCheck.habit_id == habit.id))
        if c.note.strip()
    }


def take_log(db: Session, habit: Habit, log: dict[date, str]) -> None:
    """The habit's comments as its file has them: a day's comment written
    there is the day's (a day not ticked, skipped), and one taken out of it
    goes (a day skipped with it then has nothing)."""
    for check in list(db.scalars(select(HabitCheck).where(HabitCheck.habit_id == habit.id))):
        if check.day not in log and check.note:
            _settle_check(db, habit, check.day, check.done, "")
    for day, note in log.items():
        check = check_of(db, habit, day)
        _settle_check(db, habit, day, check.done if check else False, note.strip())


def grid(db: Session, start: date, days: int) -> list[dict[str, Any]]:
    """Each habit over `days` days from `start`, day by day: "done",
    "skipped" (not ticked, with a comment), "missed" (one of its days, since
    it began, not ticked, the day past) or None (not due, any day's habit
    not ticked, or today still open), with the day's comment."""
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
        out.append({"id": habit.id, "slug": habit.slug, "days": habit.days, "checks": row})
    return out


def streak(row: dict[str, Any]) -> int:
    """A grid row's streak at its last day: the days in a row it was done
    (a day it is not meant to happen passed over, any other day not done
    ending it), the last day counted once done and passed over while it
    is still open (today, or a day to come)."""
    run = 0
    today = date.today()
    for i, check in enumerate(reversed(row["checks"])):
        off_day = row["days"] and str(check["day"].weekday()) not in row["days"]
        still_open = i == 0 and check["day"] >= today
        if check["state"] == "done":
            run += 1
        elif check["state"] is None and (off_day or still_open):
            continue
        else:
            break
    return run


def standing(db: Session, day: date, days: int = 7, reach: int = 366) -> dict[str, dict[str, Any]]:
    """How each habit stands on `day`, by name: its id and days, its last
    `days` days up to it, as the grid reads them ([{day, state, note}],
    oldest first), and its streak (streak), looking back `reach` days at
    most."""
    out = {}
    for row in grid(db, day - timedelta(days=reach - 1), reach):
        week = row["checks"][-days:]
        out[row["slug"]] = {
            "id": row["id"],
            "slug": row["slug"],
            "days": row["days"],
            "week": [{**c, "day": c["day"].isoformat()} for c in week],
            "streak": streak(row),
        }
    return out
