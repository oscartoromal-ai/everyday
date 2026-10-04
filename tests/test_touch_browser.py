"""On a phone, a finger that scrolls changes nothing: a swipe begun on a
habit's cell, a task's box or an event scrolls the page, as the finger
meant, while a tap still does what a click does. The `live`, `phone` and
`app_db` fixtures are conftest.py's."""

from datetime import date, datetime, time, timedelta

import pytest

from app.models import Event, Task, TaskStatus
from app.services import events as events_svc
from app.services import habits as habits_svc
from app.services import notebook
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()


def finger(page, locator, *, swipe: float = 0) -> None:
    """A finger put on the middle of `locator` and lifted, `swipe` pixels
    higher (scrolling the page down), as the browser has it from a screen.
    A swiping finger stops before it is lifted, so the page does not glide
    on: a finger put on a gliding page only stops it, as on a phone."""
    box = locator.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    cdp = page.context.new_cdp_session(page)

    def touch(kind: str, *points: dict) -> None:
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": list(points)})

    touch("touchStart", {"x": x, "y": y})
    if swipe:
        for step in range(1, 11):
            touch("touchMove", {"x": x, "y": y - swipe * step / 10})
            page.wait_for_timeout(16)
        page.wait_for_timeout(300)
        touch("touchMove", {"x": x, "y": y - swipe})
    touch("touchEnd")


def settled(page) -> None:
    """Whatever a touch sent has been answered."""
    page.wait_for_load_state("networkidle")


def habit_done(app_db, day: date) -> bool:
    with app_db() as db:
        return habits_svc.grid(db, day, 1)[0]["checks"][0]["state"] == "done"


def test_a_swipe_on_the_sheet_ticks_and_toggles_nothing(phone, live, app_db) -> None:
    with app_db() as db:
        habits_svc.set_days(db, "morning-run", "")
        notebook.set_habit(db, TODAY - timedelta(days=1), "morning-run", True)
        tasks_svc.create_task(db, title="Pay rent", planned_for=TODAY)
        db.commit()
    phone.goto(f"{live}/calendar?view=sheet")
    run = phone.locator(f'tr[data-day="{TODAY.isoformat()}"] [data-slug="morning-run"]')
    run.scroll_into_view_if_needed()
    finger(phone, run, swipe=240)
    settled(phone)
    assert not habit_done(app_db, TODAY)
    box = phone.locator(f'tr[data-day="{TODAY.isoformat()}"] .ds-check')
    box.scroll_into_view_if_needed()
    finger(phone, box, swipe=240)
    settled(phone)
    with app_db() as db:
        assert db.query(Task).one().status == TaskStatus.todo
    # A tap is a click: it ticks the habit, and starts the task.
    run.scroll_into_view_if_needed()
    finger(phone, run)
    phone.locator(
        f'tr[data-day="{TODAY.isoformat()}"] [data-slug="morning-run"][data-state="done"]'
    ).wait_for()
    assert habit_done(app_db, TODAY)
    box.scroll_into_view_if_needed()
    finger(phone, box)
    phone.locator(f'tr[data-day="{TODAY.isoformat()}"] .ds-task.is-in-progress').wait_for()


def test_a_swipe_on_an_event_leaves_it_where_it_was(phone, live, app_db) -> None:
    start = datetime.combine(TODAY, time(11))
    with app_db() as db:
        events_svc.create_event(db, title="Dentist", start=start, end=start + timedelta(hours=1))
        db.commit()
    phone.goto(f"{live}/calendar?view=day&start={TODAY.isoformat()}")
    dentist = phone.locator(".cal-item.event", has_text="Dentist")
    dentist.scroll_into_view_if_needed()
    finger(phone, dentist, swipe=200)
    settled(phone)
    with app_db() as db:
        [event] = db.query(Event).all()
        assert (event.start, event.end) == (start, start + timedelta(hours=1))
    assert phone.locator(".event-card").count() == 0
