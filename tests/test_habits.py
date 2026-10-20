from datetime import date, datetime, timedelta

import pytest

from app.models import Habit, HabitCheck
from app.services import DomainError, notebook
from app.services import habits as habits_svc

TODAY = date.today()


def checks(db) -> dict[str, tuple[bool, str]]:
    return {c.habit.slug: (c.done, c.note) for c in db.query(HabitCheck).all()}


def test_a_habit_written_on_a_page_is_checked_that_day(db) -> None:
    page = notebook.save_page(
        db,
        TODAY,
        [
            {"kind": "text", "text": "Morning."},
            {"kind": "habit", "habit": "Morning-Skin-Care", "text": "\nnew serum\n"},
            {"kind": "habit", "habit": "exercise", "done": False, "text": "sick"},
        ],
        version=0,
    )
    skin = db.query(Habit).filter_by(slug="morning-skin-care").one()
    # The page keeps each habit by id, in its place.
    note = "\nnew serum"  # written under its row, kept so
    assert page.blocks[1] == {"kind": "habit", "habit": skin.id, "done": True, "text": note}
    assert checks(db) == {"morning-skin-care": (True, "new serum"), "exercise": (False, "sick")}
    # Read back by name.
    [_, habit, _] = notebook.blocks_of(db, TODAY)
    assert habit["slug"] == "morning-skin-care"

    # Taken off the page, its check goes; a habit with no checks and no days
    # of its own (a name typed on the way to another) goes too.
    notebook.save_page(db, TODAY, [{"kind": "habit", "habit": "exercise"}], version=1)
    assert checks(db) == {"exercise": (True, "")}
    assert [h.slug for h in habits_svc.list_habits(db)] == ["exercise"]


def test_a_habit_with_days_stays_without_checks(db) -> None:
    habits_svc.set_days(db, "evening-skin-care", "6012")
    habit = habits_svc.get_or_create(db, "evening-skin-care")
    assert habit.days == "0126"
    notebook.save_page(db, TODAY, [{"kind": "text", "text": "x"}], version=0)
    assert [h.slug for h in habits_svc.list_habits(db)] == ["evening-skin-care"]
    with pytest.raises(DomainError):
        habits_svc.set_days(db, "evening-skin-care", "7")
    with pytest.raises(DomainError):
        habits_svc.get_or_create(db, "no spaces")


def test_the_grid_reads_done_skipped_missed_and_open(db) -> None:
    monday = TODAY - timedelta(days=TODAY.weekday() + 7)
    daily = habits_svc.set_days(db, "stretch", habits_svc.EVERY_DAY)
    anyday = habits_svc.get_or_create(db, "read")
    for habit in (daily, anyday):
        habit.created_at = datetime.combine(monday - timedelta(days=1), datetime.min.time())
    notebook.save_page(db, monday, [{"kind": "habit", "habit": "stretch"}], version=0)
    notebook.save_page(
        db, monday + timedelta(days=1),
        [{"kind": "habit", "habit": "stretch", "done": False, "text": "sore"},
         {"kind": "habit", "habit": "read"}],
        version=0,
    )
    rows = {r["slug"]: [c["state"] for c in r["checks"]] for r in habits_svc.grid(db, monday, 3)}
    # A day it was meant to happen, not written, is missed; a habit for any
    # day is never missed.
    assert rows == {"read": [None, "done", None], "stretch": ["done", "skipped", "missed"]}
    # Before it began, and today (still open), nothing is missed.
    [row] = [r for r in habits_svc.grid(db, TODAY, 1) if r["slug"] == "stretch"]
    assert row["checks"][0]["state"] is None


def test_a_habit_comes_into_a_day_with_its_week_and_streak(db) -> None:
    monday = TODAY - timedelta(days=TODAY.weekday() + 7)
    weekdays = habits_svc.set_days(db, "stretch", habits_svc.WEEKDAYS)
    anyday = habits_svc.get_or_create(db, "read")
    for habit in (weekdays, anyday):
        habit.created_at = datetime.combine(monday - timedelta(days=30), datetime.min.time())

    def day(n: int) -> date:  # n days before the Monday
        return monday - timedelta(days=n)

    # Stretch done Thursday and Friday, not written on Tuesday or Wednesday;
    # read done the weekend, not on Friday.
    notebook.save_page(db, day(4), [{"kind": "habit", "habit": "stretch"}], version=0)
    notebook.save_page(db, day(3), [{"kind": "habit", "habit": "stretch"}], version=0)
    for n in (2, 1):
        notebook.save_page(db, day(n), [{"kind": "habit", "habit": "read"}], version=0)

    standing = habits_svc.standing(db, monday)
    # Its last six days before the Monday, oldest first.
    week = [d["day"] for d in standing["stretch"]["week"]]
    assert week == [day(n).isoformat() for n in range(6, 0, -1)]
    assert [d["state"] for d in standing["stretch"]["week"]] == [
        "missed", "missed", "done", "done", None, None,
    ]
    # The weekend is not stretch's: its streak runs over it, to Wednesday's miss.
    assert standing["stretch"]["streak"] == 2
    # A habit for any day not written on one ends its streak there.
    assert standing["read"]["streak"] == 2
    # Nothing done the day before: no streak.
    assert habits_svc.standing(db, day(2))["read"]["streak"] == 0
