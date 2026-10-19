"""Today left open overnight, in a real browser: once the day has turned
and the page is left alone, it is the new day's. The browser's clock is
Playwright's, and the server's is its Today route's; the `live`, `page`
and `app_db` fixtures are conftest.py's."""

import time as wall
from datetime import date, datetime, time, timedelta

import pytest

from app.services import notebook as notebook_svc
from app.ui import pages

pytest.importorskip("playwright.sync_api")

TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)


@pytest.fixture
def clock(monkeypatch) -> dict:
    """The server's time, as its Today route reads it: `clock["now"]`. (Its
    `date` stays the real one: the routes' types are read from it.)"""
    clock = {"now": datetime.combine(TODAY, time(23, 59, 30))}

    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    day_page = pages._day_page
    monkeypatch.setattr(pages, "datetime", Now)
    monkeypatch.setattr(pages, "_day_page", lambda r, db, day: day_page(r, db, clock["now"].date()))
    return clock


def notes_of(app_db, day: date) -> list[dict]:
    with app_db() as db:
        page = notebook_svc.get_page(db, day)
        return page.blocks if page else []


def test_today_turns_to_the_new_day_once_it_is_left_alone(page, live, app_db, clock) -> None:
    page.clock.install(time=clock["now"])
    page.goto(f"{live}/today")
    notepad = page.locator("#notepad")
    assert notepad.get_attribute("data-day") == TODAY.isoformat()
    page.locator(".pad-editor .cm-content").click()
    page.keyboard.type("Late one.")

    # Midnight, a moment after the last word: the page stays as it is, written in.
    clock["now"] = datetime.combine(TOMORROW, time(0, 0, 10))
    page.clock.run_for("00:40")
    assert notepad.get_attribute("data-day") == TODAY.isoformat()

    # Left alone for a minute: it is the new day's, its notes empty, and
    # what was written last night is the day before's.
    clock["now"] = datetime.combine(TOMORROW, time(0, 1, 30))
    page.clock.run_for("01:00")
    page.wait_for_function(
        f"document.getElementById('notepad')?.dataset.day === '{TOMORROW.isoformat()}'"
    )
    assert page.locator(".day-header .rest").inner_text() == (
        f"{TOMORROW.strftime('%A')} {TOMORROW.day} {TOMORROW.strftime('%B %Y')}"
    )
    assert page.evaluate("Notepad.text()") == ""
    end = wall.monotonic() + 5
    while notes_of(app_db, TODAY) != [{"kind": "text", "text": "Late one."}]:
        assert wall.monotonic() < end, notes_of(app_db, TODAY)
        wall.sleep(0.1)
