"""What the habits' places show: Today's habits pane (each habit's last
seven days, its streak, its days and the day's comments), the Habits page
(every habit over its last four weeks) and a habit's own page (its half
year, its numbers, and its file's words)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.dates import monday, short_date, upper_first
from app.models import Habit
from app.services import everyday, habit_md
from app.services import habits as habits_svc

STATES = {"done": "Done", "skipped": "Skipped", "missed": "Missed"}
# The Habits page's strip, and a habit's own page's weeks.
STRIP_DAYS = 28
YEAR_WEEKS = 26


def href(habit: Habit) -> str:
    return f"/habits/{quote(habit.slug)}"


def file_of(habit: Habit) -> str:
    """Its file, from the everyday files' folder."""
    return f"habits/{habit.slug}{everyday.DOC_SUFFIX}"


def _cells(checks: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Grid days as drawn: the day, its state, its comment and what its
    tooltip says ("Tue 20 Oct: done, knee sore")."""
    out = []
    for c in checks:
        state = c["state"]
        if state is None and c["day"] == today:
            state = "today"
        said = STATES.get(state or "", "not yet" if state == "today" else "nothing")
        tip = f"{upper_first(short_date(c['day'], today))}: {said.lower()}"
        if c["note"]:
            tip += f". {c['note']}"
        out.append(
            {
                "day": c["day"].isoformat(),
                "state": state,
                "note": c["note"],
                "tip": tip,
                "letter": c["day"].strftime("%a")[0],
            }
        )
    return out


def pane_ctx(db: Session, day: date, today: date) -> list[dict[str, Any]]:
    """Every habit as Today's pane draws it on `day`: how it stands that
    day (its id, name, days, last seven days and streak: habits.standing),
    and where its page is."""
    return [
        {**stands, "href": f"/habits/{quote(stands['slug'])}", "today": today.isoformat()}
        for stands in habits_svc.standing(db, day).values()
    ]


def pane_entry(db: Session, habit: Habit, day: date, today: date) -> dict[str, Any]:
    """One habit as Today's pane draws it, after it was ticked or commented."""
    return next(e for e in pane_ctx(db, day, today) if e["id"] == habit.id)


def _rate(row: dict[str, Any]) -> tuple[int, int]:
    """Of a grid row's days that count (done, skipped or missed: its own
    days, or any day it was ticked), how many were done."""
    counted = [c for c in row["checks"] if c["state"] in ("done", "skipped", "missed")]
    return sum(c["state"] == "done" for c in counted), len(counted)


def rate_label(row: dict[str, Any], *, short: bool) -> str:
    """How often a grid row's habit was done: of the days it was meant to
    happen ("5/7", "5 of 7 done") when it has days of its own, else the
    days it was done ("5", "5 days done"); "" (or "Nothing yet") when none."""
    done, counted = _rate(row)
    if not counted:
        return "" if short else "Nothing yet"
    if row["days"]:
        return f"{done}/{counted}" if short else f"{done} of {counted} done"
    return str(done) if short else f"{done} {'day' if done == 1 else 'days'} done"


def index_ctx(db: Session, today: date) -> dict[str, Any]:
    """The Habits page: every habit, its days, its streak, its last four
    weeks and how many of their days it was done."""
    start = today - timedelta(days=STRIP_DAYS - 1)
    strips = {r["id"]: r for r in habits_svc.grid(db, start, STRIP_DAYS)}
    standing = habits_svc.standing(db, today)
    habits = []
    for habit in habits_svc.list_habits(db):
        strip = strips[habit.id]
        habits.append(
            {
                "id": habit.id,
                "slug": habit.slug,
                "href": href(habit),
                "days": habit_md.days_label(habit.days),
                "streak": standing[habit.slug]["streak"],
                "cells": _cells(strip["checks"], today),
                "rate": rate_label(strip, short=True),
                "said": rate_label(strip, short=False),
                "about": habit.notes.strip().split("\n")[0][:140],
            }
        )
    return {
        "habits": habits,
        "strip_head": [
            {"letter": d.strftime("%a")[0], "name": d.strftime("%A"), "monday": d.weekday() == 0}
            for d in (start + timedelta(days=i) for i in range(STRIP_DAYS))
        ],
    }


def page_ctx(db: Session, habit: Habit, today: date) -> dict[str, Any]:
    """A habit's own page: its half year as weeks (Monday at the top, this
    week last), its streak, the days it was done of the last thirty that
    count, since when it is kept, and its file's words to write."""
    first = monday(today) - timedelta(weeks=YEAR_WEEKS - 1)
    days = (today - first).days + 1
    [year] = [r for r in habits_svc.grid(db, first, days) if r["id"] == habit.id]
    cells = _cells(year["checks"], today)
    weeks = []
    for w in range(YEAR_WEEKS):
        week = cells[w * 7 : (w + 1) * 7]
        start = first + timedelta(weeks=w)
        weeks.append(
            {
                "cells": week,
                # A month's name over the week its first day is in.
                "month": start.strftime("%b") if start.day <= 7 else "",
            }
        )
    month = {**year, "checks": year["checks"][-30:]}
    log = habits_svc.log_of(db, habit)
    body = habit_md.body(habit.notes, log)
    return {
        "habit": habit,
        "href": href(habit),
        "file": file_of(habit),
        "days_label": habit_md.days_label(habit.days),
        "since": upper_first(short_date(habit.created_at.date(), today)),
        "streak": habits_svc.standing(db, today)[habit.slug]["streak"],
        "rate": rate_label(month, short=False),
        "comments": len(log),
        "weeks": weeks,
        "weekday_letters": ["M", "", "W", "", "F", "", ""],
        "body": body,
        "version": everyday.version(body),
    }
