"""Today's notepad in a real browser: plain notes for the day, saved as they
are written, and a question instead of an overwrite when another window
saved first. notepad.js only runs in a browser; the `live` and `page`
fixtures are conftest.py's."""

import time
from datetime import date

import pytest

from app.services import notebook as notebook_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()


def stored(app_db) -> list[dict]:
    with app_db() as db:
        page = notebook_svc.get_page(db, TODAY)
        return page.blocks if page else []


def saved_as(app_db, expected: list[dict], timeout: float = 5) -> None:
    """The notes as the server has them, once the page has saved."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if stored(app_db) == expected:
            return
        time.sleep(0.1)
    assert stored(app_db) == expected


def test_notes_save_as_they_are_written(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    page.locator("#notepad").click()
    page.keyboard.type("Slow morning.")
    page.keyboard.press("Enter")
    page.keyboard.type("- call the dentist")
    saved_as(app_db, [{"kind": "text", "text": "Slow morning.\n- call the dentist"}])

    # Just text: a "- " line stays a line, and no task is made of it.
    page.reload()
    assert page.locator("#notepad").input_value() == "Slow morning.\n- call the dentist"
    from app.services import tasks as tasks_svc

    with app_db() as db:
        assert tasks_svc.list_tasks(db) == []


def test_notes_changed_in_another_window_ask_which_to_keep(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    page.locator("#notepad").click()
    page.keyboard.type("Mine.")
    saved_as(app_db, [{"kind": "text", "text": "Mine."}])

    with app_db() as db:
        notebook_svc.save_page(db, TODAY, [{"kind": "text", "text": "Theirs."}], version=1)
        db.commit()
    page.keyboard.type(" More.")
    page.locator("#pad-stale:not([hidden])").wait_for()
    assert stored(app_db) == [{"kind": "text", "text": "Theirs."}]

    page.locator("[data-pad-keep]").click()
    saved_as(app_db, [{"kind": "text", "text": "Mine. More."}])
    assert page.locator("#pad-stale").is_hidden()


def test_a_task_is_written_in_the_notes(page, live, app_db) -> None:
    from app.models import TaskStatus
    from app.services import tasks as tasks_svc

    page.goto(f"{live}/today")
    pad = page.locator("#notepad")
    pad.click()
    page.keyboard.type("Morning.")
    page.keyboard.press("Enter")

    # "- [ ] " makes the row a task: the marker leaves the text for the row's
    # checkbox, and the rows the task covers are bracketed as it grows.
    page.keyboard.type("- [ ] Call the dentist")
    kinds = page.locator(".pad-rows-inner > div")
    assert kinds.nth(1).locator(".pad-check").is_visible()
    assert kinds.nth(1).locator(".pad-kind-name").inner_text() == "Task"
    assert page.locator(".pad-task-mark").is_visible()
    page.keyboard.press("Enter")
    page.keyboard.type("- ask about the crown")
    assert page.locator(".pad-rows-inner > div.task .pad-n").all_inner_texts() == ["2", "3"]

    # Ctrl+Enter closes it (the task is added) and goes on to the next row.
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added: Call the dentist").wait_for()
    assert page.locator(".pad-task-mark").is_hidden()
    page.keyboard.type("After.")
    assert pad.input_value() == "Morning.\nCall the dentist\n- ask about the crown\nAfter."
    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        assert task.title == "Call the dentist"
        assert (task.notes, task.planned_for) == ("- ask about the crown", TODAY)
        task_id = task.id
    notes = "Morning.\n- [ ] Call the dentist\n- ask about the crown\nAfter."
    saved_as(app_db, [{"kind": "text", "text": notes, "links": {"1": task_id}}])

    # Its box ticks the task; the row keeps its kind after a reload.
    kinds.nth(1).locator(".pad-check").click()
    kinds.nth(1).locator(".pad-check[aria-checked=true]").wait_for()
    ticked = notes.replace("- [ ] ", "- [x] ")
    saved_as(app_db, [{"kind": "text", "text": ticked, "links": {"1": task_id}}])
    with app_db() as db:
        assert tasks_svc.get_task(db, task_id).status == TaskStatus.done
    page.reload()
    assert pad.input_value().startswith("Morning.\nCall the dentist\n")
    assert kinds.nth(1).locator(".pad-check").get_attribute("aria-checked") == "true"

    # Backspace at a task row's start makes it a plain row again.
    pad.click()
    page.keyboard.press("Control+Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Home")
    page.keyboard.press("Backspace")
    assert kinds.nth(1).locator(".pad-check").count() == 0
    saved_as(app_db, [{"kind": "text", "text": ticked.replace("- [x] ", "")}])
