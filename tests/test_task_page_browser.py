"""A task's own page in a real browser, opened from Calendar's sheet: its
title there opens it, Ctrl+Enter writing one opens the task just written,
and what is written on the page is saved as it is written, the page going
back to the sheet. The `live`, `page` and `app_db` fixtures are
conftest.py's."""

import time
from datetime import date, timedelta

import pytest

from app.models import Task
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()


def plan_cell(page):
    return page.locator(f'tr[data-day="{TODAY.isoformat()}"] td.ds-plan')


def stored(app_db, title: str) -> Task:
    with app_db() as db:
        return db.query(Task).filter_by(title=title).one()


def test_a_task_written_on_the_sheet_opens_to_be_written_out(page, live, app_db) -> None:
    page.goto(f"{live}/calendar?view=sheet")
    plan_cell(page).click()
    page.keyboard.type("Plan the trip")
    page.keyboard.press("Control+Enter")
    page.wait_for_url(f"{live}/tasks/*")
    # The description takes the caret: the task is there to be written out.
    editor = page.locator(".main [data-notes-editor]")
    assert editor.evaluate("el => el.contains(document.activeElement)")
    page.keyboard.type("Flights first, then the rail pass.")
    page.locator("[data-page-state]", has_text="Saved").wait_for()
    assert stored(app_db, "Plan the trip").notes == "Flights first, then the rail pass."

    # The title is the page's heading, and its trailing words its fields.
    page.locator(".main .sheet-title").click()
    page.keyboard.press("End")
    page.keyboard.type(" to Japan tomorrow ")
    page.keyboard.press("Escape")
    page.wait_for_function(
        "() => document.title.startsWith('Plan the trip to Japan ·')"
    )
    task = stored(app_db, "Plan the trip to Japan")
    assert task.planned_for == TODAY + timedelta(days=1)

    # Back to the sheet, where its title opens it again.
    page.locator(".page-back", has_text="Calendar").click()
    page.wait_for_url(f"{live}/calendar?view=sheet")


def test_a_title_on_the_sheet_opens_its_page(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Taxes", planned_for=TODAY)
        db.commit()
    page.goto(f"{live}/calendar?view=sheet")
    plan_cell(page).locator("a.ds-title", has_text="Taxes").click()
    page.wait_for_url(f"{live}/tasks/{task.id}")
    page.locator(".main [data-notes-editor]").click()
    page.keyboard.type("- receipts")
    page.keyboard.press("Enter")
    page.keyboard.type("payslips")
    # Left before the pause: the page saves as it goes.
    page.locator(".page-back").click()
    page.wait_for_url(f"{live}/calendar?view=sheet")
    # Saved as the page went, its request outliving it.
    deadline = time.monotonic() + 5
    while True:
        with app_db() as db:
            notes = db.get(Task, task.id).notes
        if notes == "- receipts\n- payslips" or time.monotonic() > deadline:
            break
        time.sleep(0.05)
    assert notes == "- receipts\n- payslips"


def test_its_box_steps_it_through_progress_and_review_to_done(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Ship the release", planned_for=TODAY)
        db.commit()
    page.goto(f"{live}/tasks/{task.id}")
    box = page.locator("[data-sheet-check]")
    for status in ["in_progress", "needs_review", "done", "todo"]:
        box.click()
        page.locator("[data-page-state]", has_text="Saved").wait_for()
        deadline = time.monotonic() + 5
        while True:
            with app_db() as db:
                stored_status = db.get(Task, task.id).status
            if stored_status == status or time.monotonic() > deadline:
                break
            time.sleep(0.05)
        assert stored_status == status
        assert box.get_attribute("data-status") == status
        assert box.is_checked() == (status == "done")
        assert box.evaluate("el => el.indeterminate") == (status in ("in_progress", "needs_review"))
