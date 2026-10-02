"""The command menu (Ctrl+K) in a real browser: a task found opens Tasks on
it, a day's words go to that day, an event found opens its card, and a thing
to do is done. The `live`, `page` and `app_db` fixtures are conftest.py's."""

from datetime import date, datetime, time, timedelta

import pytest

from app.models import Event, EventSource
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()


def menu(page, words: str) -> None:
    page.keyboard.press("Control+k")
    page.locator("#command-dialog[open]").wait_for()
    page.keyboard.type(words)


def test_a_task_found_opens_tasks_with_the_cursor_on_it(page, live, app_db) -> None:
    with app_db() as db:
        for title in ("Alpha", "Bravo", "Water the plants", "Delta"):
            tasks_svc.create_task(db, title=title)
        db.commit()
    page.goto(f"{live}/calendar")
    menu(page, "plants")
    page.locator(".command-item", has_text="Water the plants").wait_for()
    page.keyboard.press("Enter")
    page.wait_for_url(f"{live}/")
    page.wait_for_function(
        "document.activeElement?.matches('.task-row[data-task-title=\"Water the plants\"]')"
    )


def test_a_days_words_go_to_that_day(page, live) -> None:
    page.goto(f"{live}/")
    menu(page, "tomorrow")
    first = page.locator(".command-item").first
    assert "on the calendar" in first.text_content()
    page.keyboard.press("Enter")
    page.wait_for_url(f"**/calendar?start={(TODAY + timedelta(days=1)).isoformat()}")
    # And the notes of a day: the second.
    menu(page, "yesterday")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.wait_for_url(f"**/day/{(TODAY - timedelta(days=1)).isoformat()}")


def test_an_event_found_opens_its_card(page, live, app_db) -> None:
    start = datetime.combine(TODAY + timedelta(days=2), time(11, 30))
    with app_db() as db:
        db.add(Event(
            title="Design review - Huddle", start=start, end=start + timedelta(hours=1),
            source=EventSource.work, read_only=True, external_id="h",
            location="https://example.zoom.us/j/1",
        ))
        db.commit()
    page.goto(f"{live}/today")
    menu(page, "huddle")
    page.locator(".command-item", has_text="Design review - Huddle").click()
    page.locator(".event-card", has_text="Design review - Huddle").wait_for()
    # The card is opened once: the address no longer asks for it.
    assert "event=" not in page.url


def test_new_event_from_another_page_opens_the_composer(page, live) -> None:
    page.goto(f"{live}/")
    menu(page, "new event")
    page.keyboard.press("Enter")
    page.wait_for_url("**/calendar")
    page.locator(".event-composer").wait_for()
    assert page.evaluate("document.activeElement.matches('.composer-title')")


def test_the_rail_opens_it_and_esc_closes_it(page, live) -> None:
    page.goto(f"{live}/weeks")
    page.locator("[data-command-open]").click()
    page.locator("#command-dialog[open]").wait_for()
    page.keyboard.press("Escape")
    page.locator("#command-dialog[open]").wait_for(state="detached")
