from datetime import date, datetime, timedelta

import pytest

from app.models import HabitCheck
from app.services import DomainError
from app.services import habits as habits_svc

TODAY = date.today()


def checks(db) -> dict[tuple[str, date], tuple[bool, str]]:
    return {(c.habit.slug, c.day): (c.done, c.note) for c in db.query(HabitCheck).all()}


def since(habit, day: date) -> None:  # noqa: ANN001
    habit.created_at = datetime.combine(day, datetime.min.time())


def test_a_habit_is_named_as_it_is_written(db) -> None:
    habit = habits_svc.create(db, "  Morning Skin-care! ")
    assert habit.slug == "morning-skin-care"
    with pytest.raises(DomainError):
        habits_svc.create(db, "morning skin care")  # the same name
    with pytest.raises(DomainError):
        habits_svc.create(db, "!!")
    other = habits_svc.create(db, "evening")
    with pytest.raises(DomainError):
        habits_svc.rename(db, other.id, "Morning skin care")
    assert habits_svc.rename(db, other.id, "Evening skin care").slug == "evening-skin-care"
    with pytest.raises(DomainError):
        habits_svc.set_days(db, "evening-skin-care", "7")


def test_a_day_is_ticked_and_commented_on(db) -> None:
    habit = habits_svc.create(db, "stretch")
    day = TODAY - timedelta(days=1)
    habits_svc.set_done(db, habit, day, True)
    assert checks(db) == {("stretch", day): (True, "")}
    habits_svc.set_note(db, habit, day, "  Ten minutes.\r\nTight back.  \n")
    assert checks(db) == {("stretch", day): (True, "Ten minutes.\nTight back.")}
    # Unticked, its comment stays: the day was skipped, and why.
    habits_svc.set_done(db, habit, day, False)
    assert checks(db) == {("stretch", day): (False, "Ten minutes.\nTight back.")}
    # With nothing said either, the day has nothing.
    habits_svc.set_note(db, habit, day, "")
    assert checks(db) == {}
    # A comment on a day not ticked makes it skipped.
    habits_svc.set_note(db, habit, day, "Sick.")
    assert checks(db) == {("stretch", day): (False, "Sick.")}
    assert habits_svc.log_of(db, habit) == {day: "Sick."}


def test_a_habit_deleted_takes_its_days_with_it(db) -> None:
    habit = habits_svc.create(db, "stretch")
    habits_svc.set_done(db, habit, TODAY, True)
    db.commit()
    habits_svc.delete(db, habit.id)
    db.commit()
    assert habits_svc.list_habits(db) == [] and checks(db) == {}


def test_the_grid_reads_done_skipped_missed_and_open(db) -> None:
    monday = TODAY - timedelta(days=TODAY.weekday() + 7)
    daily = habits_svc.create(db, "stretch", habits_svc.EVERY_DAY)
    anyday = habits_svc.create(db, "read")
    for habit in (daily, anyday):
        since(habit, monday - timedelta(days=1))
    habits_svc.set_done(db, daily, monday, True)
    habits_svc.set_note(db, daily, monday + timedelta(days=1), "sore")
    habits_svc.set_done(db, anyday, monday + timedelta(days=1), True)
    rows = {r["slug"]: [c["state"] for c in r["checks"]] for r in habits_svc.grid(db, monday, 3)}
    # A day it was meant to happen, not ticked, is missed; a habit for any
    # day is never missed.
    assert rows == {"read": [None, "done", None], "stretch": ["done", "skipped", "missed"]}
    [row] = [r for r in habits_svc.grid(db, monday, 3) if r["slug"] == "stretch"]
    assert row["checks"][1]["note"] == "sore"
    # Before it began, and today (still open), nothing is missed.
    [row] = [r for r in habits_svc.grid(db, TODAY, 1) if r["slug"] == "stretch"]
    assert row["checks"][0]["state"] is None


def test_a_habit_stands_on_a_day_with_its_week_and_streak(db) -> None:
    monday = TODAY - timedelta(days=TODAY.weekday() + 7)
    weekdays = habits_svc.create(db, "stretch", habits_svc.WEEKDAYS)
    anyday = habits_svc.create(db, "read")
    for habit in (weekdays, anyday):
        since(habit, monday - timedelta(days=30))

    def day(n: int) -> date:  # n days before the Monday
        return monday - timedelta(days=n)

    # Stretch done Thursday and Friday, not Monday to Wednesday; read done
    # the weekend, not on Friday.
    for n in (4, 3):
        habits_svc.set_done(db, weekdays, day(n), True)
    for n in (2, 1):
        habits_svc.set_done(db, anyday, day(n), True)

    sunday = habits_svc.standing(db, day(1))
    # Its last seven days up to the day, oldest first.
    week = [d["day"] for d in sunday["stretch"]["week"]]
    assert week == [day(n).isoformat() for n in range(7, 0, -1)]
    assert [d["state"] for d in sunday["stretch"]["week"]] == [
        "missed", "missed", "missed", "done", "done", None, None,
    ]
    # The weekend is not stretch's: its streak runs over it, to Wednesday's miss.
    assert sunday["stretch"]["streak"] == 2
    # The day itself counts once done.
    assert sunday["read"]["streak"] == 2
    # A day still open does not end a streak: on the Monday (past, so
    # missed), it does.
    assert habits_svc.standing(db, monday)["stretch"]["streak"] == 0
    assert habits_svc.standing(db, monday)["read"]["streak"] == 0


def test_today_still_open_keeps_the_streak_going(db) -> None:
    habit = habits_svc.create(db, "read")
    since(habit, TODAY - timedelta(days=10))
    for n in (1, 2):
        habits_svc.set_done(db, habit, TODAY - timedelta(days=n), True)
    assert habits_svc.standing(db, TODAY)["read"]["streak"] == 2
    habits_svc.set_done(db, habit, TODAY, True)
    assert habits_svc.standing(db, TODAY)["read"]["streak"] == 3
    # Skipped, with a comment why: it ends there.
    habits_svc.set_done(db, habit, TODAY, False)
    habits_svc.set_note(db, habit, TODAY, "Too tired.")
    assert habits_svc.standing(db, TODAY)["read"]["streak"] == 0


# ---- the pages, and what the pane and they write ----


def test_the_pane_starts_ticks_and_comments_on_a_habit(client, db) -> None:
    from app.services import everyday

    yesterday = TODAY - timedelta(days=1)
    answer = client.post("/ui/habits", data={"name": "Morning run", "on": TODAY.isoformat()})
    assert answer.status_code == 200
    habit = answer.json()["habit"]
    assert (habit["slug"], habit["href"]) == ("morning-run", "/habits/morning-run")
    assert habit["streak"] == 0
    assert [d["day"] for d in habit["week"]][-1] == TODAY.isoformat()
    url = f"/ui/habits/{habit['id']}"
    ticked = client.post(f"{url}/done", data={"day": yesterday.isoformat(), "done": "true"}).json()
    assert ticked["habit"]["week"][-2]["state"] == "done"
    assert ticked["habit"]["streak"] == 1
    said = client.post(f"{url}/note", data={"day": TODAY.isoformat(), "note": "Rain."}).json()
    today = {"day": TODAY.isoformat(), "state": "skipped", "note": "Rain."}
    assert said["habit"]["week"][-1] == today
    assert "- " + TODAY.isoformat() + ": Rain." in (
        everyday.habits_dir() / "morning-run.md"
    ).read_text(encoding="utf-8")
    days = client.post(f"{url}/days", data={"days": "024"}).json()
    assert (days["days"], days["label"]) == ("024", "Mon, Wed, Fri")
    # The same name again is refused, saying why.
    again = client.post("/ui/habits", data={"name": "morning run"})
    assert again.status_code == 422 and "already" in again.json()["detail"]
    # From the Habits page, a new one goes to its page.
    made = client.post("/ui/habits", data={"name": "Stretch"}, headers={"HX-Request": "true"})
    assert made.headers["HX-Redirect"] == "/habits/stretch"


def test_a_habits_page_writes_its_words_and_its_name(client, db) -> None:
    from app.services import everyday

    habit = habits_svc.create(db, "stretch")
    habits_svc.set_done(db, habit, TODAY, True)
    db.commit()
    page = client.get("/habits/stretch")
    assert page.status_code == 200 and "habits/stretch.md" in page.text
    index = client.get("/habits")
    assert index.status_code == 200 and 'href="/habits/stretch"' in index.text
    assert client.get("/habits/nothing").status_code == 404

    latest = client.get(f"/ui/habits/{habit.id}/file").json()
    assert latest["body"] == "## Log\n"
    body = f"Ten minutes.\n\n## Log\n\n- {TODAY.isoformat()}: Tight back.\n"
    file_url = f"/ui/habits/{habit.id}/file"
    saved = client.post(file_url, data={"body": body, "base": latest["version"]})
    assert saved.status_code == 200
    assert habits_svc.log_of(db, habit) == {TODAY: "Tight back."}
    # A save over a copy the file has moved on from asks which to keep.
    stale = client.post(file_url, data={"body": "x", "base": latest["version"]})
    assert stale.status_code == 409 and stale.json()["version"] == saved.json()["version"]
    # Renamed from its heading: its page and file follow.
    renamed = client.post(f"/ui/habits/{habit.id}/file", data={"name": "Back stretch"}).json()
    assert (renamed["name"], renamed["href"]) == ("back-stretch", "/habits/back-stretch")
    assert (everyday.habits_dir() / "back-stretch.md").is_file()
    year = client.get(f"/ui/habits/{habit.id}/year")
    assert year.status_code == 200 and "Tight back." in year.text
    gone = client.post(f"/ui/habits/{habit.id}/delete")
    assert gone.headers["HX-Redirect"] == "/habits"
    assert habits_svc.list_habits(db) == []
