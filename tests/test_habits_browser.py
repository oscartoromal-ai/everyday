"""Habits in a real browser: ticked and commented on in the pane beside a
day's notes (habits.js), never written in the notes; and a habit's own
page, its words written in its file (doc-editor.js, habits-page.js). The
`live`, `page` and `app_db` fixtures are conftest.py's."""

import time
from datetime import date, timedelta

import pytest

from app.models import HabitCheck
from app.services import everyday
from app.services import habits as habits_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def until(check, timeout: float = 5) -> None:  # noqa: ANN001
    end = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < end
        time.sleep(0.1)


def checks(app_db) -> dict[tuple[str, date], tuple[bool, str]]:  # noqa: ANN001
    with app_db() as db:
        return {(c.habit.slug, c.day): (c.done, c.note) for c in db.query(HabitCheck).all()}


def a_habit(app_db, name: str, days: str = "") -> int:  # noqa: ANN001
    with app_db() as db:
        habit = habits_svc.create(db, name, days)
        habit.created_at -= timedelta(days=30)
        db.commit()
        return habit.id


def test_a_habit_is_ticked_and_commented_on_beside_the_notes(page, live, app_db) -> None:
    run = a_habit(app_db, "morning-run")
    other = str((TODAY.weekday() + 1) % 7)
    a_habit(app_db, "evening-read", other)  # not due today
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    pane = page.locator("#pad-habits")
    row = pane.locator(f".habit-row[data-habit='{run}']")
    # The habits due today, none ticked yet.
    assert pane.locator(".habit-name-text").all_inner_texts() == ["morning-run"]
    assert pane.locator(".today-fold-summary .count").inner_text() == "0/1"

    # Its box ticks it for today: the notes have nothing of it.
    row.locator(".habit-box").click()
    until(lambda: checks(app_db) == {("morning-run", TODAY): (True, "")})
    assert "done" in row.get_attribute("class").split()
    assert pane.locator(".today-fold-summary .count").inner_text() == "1/1"
    assert row.locator(".habit-streak").inner_text() == "1d"
    assert page.evaluate("Notepad.text()") == ""

    # Its name opens the day's comment; Enter saves and closes it.
    row.locator(".habit-name").click()
    note = row.locator(".habit-note")
    assert note.evaluate("el => el === document.activeElement")
    page.keyboard.type("Easy, 5k.")
    page.keyboard.press("Enter")
    assert row.locator(".habit-drawer").is_hidden()
    until(lambda: checks(app_db) == {("morning-run", TODAY): (True, "Easy, 5k.")})
    assert "has-note" in row.get_attribute("class").split()
    assert row.locator(".habit-name svg").is_visible()
    log = (everyday.habits_dir() / "morning-run.md").read_text(encoding="utf-8")
    assert f"- {TODAY.isoformat()}: Easy, 5k." in log

    # Yesterday, picked: its box and comment are that day's. A comment on a
    # day not ticked says why it was skipped.
    row.locator(f".habit-day[data-day='{YESTERDAY.isoformat()}']").click()
    assert pane.locator(".habit-on").inner_text() != ""
    assert row.locator(".habit-box").get_attribute("aria-checked") == "false"
    row.locator(".habit-name").click()
    page.keyboard.type("Rain.")
    page.keyboard.press("Enter")
    until(lambda: checks(app_db).get(("morning-run", YESTERDAY)) == (False, "Rain."))
    yesterday = row.locator(f".habit-day[data-day='{YESTERDAY.isoformat()}']")
    assert "skipped" in yesterday.get_attribute("class").split()
    # Ticked after all, the comment stays; Right goes back to today.
    row.locator(".habit-box").click()
    until(lambda: checks(app_db).get(("morning-run", YESTERDAY)) == (True, "Rain."))
    row.locator(".habit-box").press("ArrowRight")
    assert pane.locator(".habit-on").is_hidden()
    assert row.locator(".habit-streak").inner_text() == "2d"

    # A new one starts at the pane's foot, due any day.
    pane.locator(".habit-new-open").click()
    page.keyboard.type("Vitamin D")
    page.keyboard.press("Enter")
    pane.locator(".habit-name-text", has_text="vitamin-d").wait_for()
    assert pane.locator(".today-fold-summary .count").inner_text() == "1/2"
    assert (everyday.habits_dir() / "vitamin-d.md").is_file()

    # Its days, from its icon: written, and the row stays while the page does.
    row.locator(".prop[data-prop=days]").click()
    page.locator(
        ".sheet-menu [role=menuitemcheckbox]",
        has_text=[
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ][int(other)],
    ).click()
    page.keyboard.press("Escape")

    def days() -> str:
        with app_db() as db:
            return habits_svc.find(db, "morning-run").days

    until(lambda: days() == other)
    assert row.is_visible()


def test_a_habits_page_writes_its_file(page, live, app_db) -> None:
    run = a_habit(app_db, "morning-run")
    with app_db() as db:
        habit = habits_svc.find(db, "morning-run")
        habits_svc.set_done(db, habit, YESTERDAY, True)
        db.commit()
    page.goto(f"{live}/habits")
    page.locator(".habits-name", has_text="morning-run").click()
    page.wait_for_url(f"{live}/habits/morning-run")
    assert page.locator(".habit-year .done").count() == 1
    # What it is, above its log; then a comment on a day, as the file has them.
    page.locator(".doc-body .cm-content").click()
    page.keyboard.press("Control+Home")
    page.keyboard.type("Five k before work.")
    page.keyboard.press("Enter")
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.type(f"- {YESTERDAY.isoformat()}: Felt strong.")
    page.locator("[data-page-state]", has_text="Saved").wait_for()
    until(lambda: checks(app_db) == {("morning-run", YESTERDAY): (True, "Felt strong.")})
    with app_db() as db:
        assert habits_svc.find(db, "morning-run").notes == "Five k before work."
    # Its half year shows the comment's day with its dot.
    page.locator(".habit-year i.done.noted").wait_for()

    # Renamed from its heading: its address and file follow.
    name = page.locator("[data-doc-name]")
    name.fill("Morning jog")
    name.press("Enter")
    page.wait_for_url(f"{live}/habits/morning-jog")
    assert page.locator("[data-habit-file]").inner_text() == "habits/morning-jog.md"
    with app_db() as db:
        assert habits_svc.get(db, run).slug == "morning-jog"
