"""Calendar's grid in a real browser: an event drawn on it and written in
the composer, a task given the time instead, an event's card, an event
dragged, and the view keys. The `live`, `page` and `app_db` fixtures are
conftest.py's."""

from datetime import date, datetime, time, timedelta

import pytest

from app.models import Block, Event
from app.services import events as events_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

# A week ahead, so nothing on it has passed; its Wednesday is the day drawn on.
MONDAY = date.today() - timedelta(days=date.today().weekday()) + timedelta(weeks=1)
WEDNESDAY = MONDAY + timedelta(days=2)


def open_week(page, live) -> None:
    page.goto(f"{live}/calendar?view=week&start={MONDAY.isoformat()}")
    # 09:00 at the top of the grid's window, whatever it opened on.
    page.evaluate("""() => {
      const g = document.getElementById('calendar-grid');
      g.scrollTop = 9 * 48;
    }""")


def y_of(page, hour: float) -> float:
    """The viewport's y of an hour on the grid."""
    top = page.evaluate("document.querySelector('.day-col').getBoundingClientRect().top")
    return top + hour * 48


def x_of(page, day: date) -> float:
    box = page.locator(f'.day-col[data-date="{day.isoformat()}"]').bounding_box()
    return box["x"] + box["width"] / 2


def events_titled(app_db, title: str) -> list[Event]:
    with app_db() as db:
        return [e for e in db.query(Event).all() if e.title == title]


def test_an_event_drawn_on_the_grid_and_written_in_the_composer(page, live, app_db) -> None:
    open_week(page, live)
    x = x_of(page, WEDNESDAY)
    page.mouse.move(x, y_of(page, 10) + 2)
    page.mouse.down()
    page.mouse.move(x, y_of(page, 11), steps=3)
    page.mouse.move(x, y_of(page, 11.5) - 1, steps=3)
    page.mouse.up()
    composer = page.locator(".event-composer")
    composer.wait_for()
    assert composer.locator("[name=day]").input_value() == WEDNESDAY.isoformat()
    assert composer.locator("[name=start_time]").input_value() == "10:00"
    assert composer.locator("[name=end_time]").input_value() == "11:30"
    assert composer.locator(".composer-note").text_content() == "1h 30m"
    # The time drawn shows on the grid, with the title as it is written.
    page.keyboard.type("Physio")
    page.locator(".cal-item.preview.composing", has_text="Physio").wait_for()
    page.keyboard.press("Enter")
    page.locator(".cal-toast.show", has_text="Event added: Physio").wait_for()
    page.locator(".cal-item.event.local", has_text="Physio").wait_for()
    assert page.locator(".event-composer").count() == 0
    [event] = events_titled(app_db, "Physio")
    assert (event.start, event.end) == (
        datetime.combine(WEDNESDAY, time(10)), datetime.combine(WEDNESDAY, time(11, 30)),
    )


def test_words_in_the_title_set_the_events_fields(page, live, app_db) -> None:
    open_week(page, live)
    page.keyboard.press("e")
    page.locator(".event-composer").wait_for()
    # No time: all day, until words give it one.
    assert page.locator(".composer-note").text_content() == "No time: all day"
    page.keyboard.type("Lunch with Ana tomorrow at 1pm ")
    title = page.locator(".composer-title")
    assert title.input_value() == "Lunch with Ana "
    tomorrow = date.today() + timedelta(days=1)
    assert page.locator(".event-composer [name=day]").input_value() == tomorrow.isoformat()
    assert page.locator(".event-composer [name=start_time]").input_value() == "13:00"
    # Backspace right after puts the last words back.
    page.keyboard.press("Backspace")
    assert title.input_value() == "Lunch with Ana at 1pm"
    assert page.locator(".event-composer [name=start_time]").input_value() == ""
    # Closed without a space, the last words are read too.
    page.keyboard.press("Enter")
    page.locator(".cal-toast.show", has_text="Event added: Lunch with Ana").wait_for()
    [event] = events_titled(app_db, "Lunch with Ana")
    assert event.start == datetime.combine(tomorrow, time(13))
    assert event.end == datetime.combine(tomorrow, time(14))


def test_a_time_drawn_can_go_to_a_task(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Write the report", planned_for=WEDNESDAY)
        tasks_svc.create_task(db, title="Book flights", planned_for=WEDNESDAY)
        db.commit()
        task_id = task.id
    open_week(page, live)
    page.mouse.click(x_of(page, WEDNESDAY), y_of(page, 14) + 10)
    picks = page.locator(".composer-tasks")
    picks.wait_for()
    # The title's words narrow the tasks offered.
    page.keyboard.type("report")
    assert picks.locator("li:not([hidden])").count() == 1
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.locator(".cal-item.block", has_text="Write the report").wait_for()
    with app_db() as db:
        [block] = db.query(Block).filter(Block.task_id == task_id).all()
        assert (block.start, block.end) == (
            datetime.combine(WEDNESDAY, time(14)), datetime.combine(WEDNESDAY, time(15)),
        )
    # The tray caught up: the task is no longer waiting for a slot.
    page.locator("#calendar-tray .tray-task", has_text="Book flights").wait_for()
    assert page.locator("#calendar-tray .tray-task", has_text="Write the report").count() == 0


def test_an_event_is_changed_on_its_card_dragged_and_deleted(page, live, app_db) -> None:
    with app_db() as db:
        events_svc.create_event(
            db, title="Dentist",
            start=datetime.combine(WEDNESDAY, time(11)), end=datetime.combine(WEDNESDAY, time(12)),
        )
        db.commit()
    open_week(page, live)
    page.locator(".cal-item.event", has_text="Dentist").click()
    card = page.locator(".event-card")
    card.wait_for()
    card.locator("[name=title]").fill("Dentist, Dr Ruiz")
    card.locator("[name=end_time]").fill("12:30")
    card.locator("button[type=submit]").click()
    card.wait_for(state="detached")
    item = page.locator(".cal-item.event", has_text="Dentist, Dr Ruiz")
    item.wait_for()
    [event] = events_titled(app_db, "Dentist, Dr Ruiz")
    assert event.end == datetime.combine(WEDNESDAY, time(12, 30))

    # Dragged an hour later, by where it was held.
    box = item.bounding_box()
    page.mouse.move(box["x"] + 20, box["y"] + 30)
    page.mouse.down()
    page.mouse.move(box["x"] + 20, box["y"] + 50, steps=3)
    page.mouse.move(box["x"] + 20, box["y"] + 78, steps=3)
    page.mouse.up()
    page.wait_for_function(
        f"document.querySelector('.cal-item.event[data-event-id=\"{event.id}\"]')?.dataset.start.endsWith('12:00:00')"
    )

    page.locator(".cal-item.event", has_text="Dentist, Dr Ruiz").click()
    page.locator(".event-card .btn.danger-quiet").click()
    page.locator("#confirm-dialog [value=go]").click()
    page.locator(".cal-item.event", has_text="Dentist").wait_for(state="detached")
    assert events_titled(app_db, "Dentist, Dr Ruiz") == []


def test_a_work_meetings_card_is_read_only(page, live, app_db) -> None:
    from app.models import EventSource

    with app_db() as db:
        db.add(Event(
            title="Canceled: Team sync", source=EventSource.work, read_only=True, external_id="x",
            start=datetime.combine(WEDNESDAY, time(9, 30)),
            end=datetime.combine(WEDNESDAY, time(10, 30)),
            location="https://example.zoom.us/j/1",
        ))
        db.commit()
    open_week(page, live)
    item = page.locator(".cal-item.event.work.cancelled", has_text="Team sync")
    assert item.text_content().strip().startswith("Team sync")
    item.click()
    card = page.locator(".event-card")
    card.wait_for()
    assert card.locator(".chip.cancelled").text_content() == "Cancelled"
    assert card.locator("form").count() == 0
    # Called off: nothing to join.
    assert card.locator(".event-join").count() == 0
    page.keyboard.press("Escape")
    card.wait_for(state="detached")


def test_keys_switch_the_days_shown_and_step_by_them(page, live) -> None:
    today = date.today()
    page.goto(f"{live}/calendar")
    page.keyboard.press("x")
    page.wait_for_url(f"**/calendar?view=3days&start={today.isoformat()}")
    assert page.locator(".day-col").count() == 3
    page.keyboard.press("ArrowRight")
    page.wait_for_url(f"**/calendar?start={(today + timedelta(days=3)).isoformat()}")
    page.keyboard.press("d")
    page.wait_for_url(f"**/calendar?view=day&start={(today + timedelta(days=3)).isoformat()}")
    assert page.locator(".day-col").count() == 1
    page.keyboard.press("ArrowLeft")
    page.wait_for_url(f"**/calendar?start={(today + timedelta(days=2)).isoformat()}")
    assert page.locator(".day-col").count() == 1  # remembered
    page.keyboard.press("w")
    page.wait_for_url("**/calendar?view=week**")
    assert page.locator(".day-col").count() == 7


def test_a_task_dropped_on_the_grid_takes_its_estimate(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(
            db, title="Write the report", planned_for=WEDNESDAY, estimate_minutes=90,
        )
        db.commit()
        task_id = task.id
    open_week(page, live)
    tray = page.locator("#calendar-tray .tray-task", has_text="Write the report")
    assert tray.locator(".estimate").text_content() == "1h 30m"
    tray.drag_to(
        page.locator(f'.day-col[data-date="{WEDNESDAY.isoformat()}"]'),
        target_position={"x": 40, "y": 10 * 48 + 2},
    )
    page.locator(".cal-item.block", has_text="Write the report").wait_for()
    with app_db() as db:
        [block] = db.query(Block).filter(Block.task_id == task_id).all()
        assert block.end - block.start == timedelta(minutes=90)
