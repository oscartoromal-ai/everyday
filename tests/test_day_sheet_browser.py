"""Calendar's sheet in a real browser, worked as a spreadsheet: where Oscar
stays written and filled down, a task written for a day and ticked, and a
habit's days painted with a drag. The `live`, `page` and `app_db` fixtures
are conftest.py's."""

from datetime import date, timedelta

import pytest

from app.models import Task, TaskStatus
from app.services import habits as habits_svc
from app.services import notebook
from app.ui.day_sheet_view import home_start

pytest.importorskip("playwright.sync_api")

TODAY = date.today()
START = home_start(TODAY)


def cell(page, day: date, selector: str):
    return page.locator(f'tr[data-day="{day.isoformat()}"] {selector}')


def open_sheet(page, live) -> None:
    page.goto(f"{live}/calendar?view=sheet")
    page.locator("#day-sheet").wait_for()


def stay(app_db, day: date) -> list[dict]:
    with app_db() as db:
        page = notebook.get_page(db, day)
        blocks = [b for b in (page.blocks if page else []) if b["kind"] == "stay"]
        return notebook.stay_items(blocks[0]["text"]) if blocks else []


def test_a_stay_is_written_ticked_and_filled_down(page, live, app_db) -> None:
    open_sheet(page, live)
    monday = START
    cell(page, monday, '[data-name="place"]').click()
    # Typing writes over the cell; Enter writes it and goes down.
    page.keyboard.type("Leiden")
    page.keyboard.press("Enter")
    cell(page, monday, '[data-name="place"][data-value="Leiden"]').wait_for()
    assert page.locator(".ds-cell.is-cursor").get_attribute("data-col") == "1"
    tuesday = (monday + timedelta(days=1)).isoformat()
    assert page.locator("tr.has-cursor").get_attribute("data-day") == tuesday
    # Space ticks it sorted; the next day's is filled down from it.
    page.keyboard.press("ArrowUp")
    page.keyboard.press(" ")
    cell(page, monday, '[data-name="place"][data-done="true"]').wait_for()
    page.keyboard.press("Shift+ArrowDown")
    page.keyboard.press("Shift+ArrowDown")
    page.keyboard.press("Control+d")
    wednesday = monday + timedelta(days=2)
    cell(page, wednesday, '[data-name="place"][data-value="Leiden"]').wait_for()
    for day in (monday, monday + timedelta(days=1), wednesday):
        assert stay(app_db, day)[0] == {"name": "place", "value": "Leiden", "done": True}
    # Delete clears it; Esc while writing keeps what was there.
    page.keyboard.press("Escape")
    page.keyboard.press("Delete")
    cell(page, wednesday, '[data-name="place"][data-value=""]').wait_for()
    page.keyboard.press("Enter")
    page.keyboard.type("Delft")
    page.keyboard.press("Escape")
    page.locator(".ds-input").wait_for(state="detached")
    assert cell(page, wednesday, '[data-name="place"]').get_attribute("data-value") == ""
    assert stay(app_db, monday)[0]["value"] == "Leiden"
    # The sheet's own keys do not reach the page's: "Leiden" switched no view.
    assert "view=day" not in page.url


def test_a_task_is_written_for_its_day_and_ticked(page, live, app_db) -> None:
    open_sheet(page, live)
    plan = cell(page, TODAY, '[data-kind="plan"]')
    plan.dblclick()
    page.keyboard.type("Do taxes")
    page.keyboard.press("Enter")
    cell(page, TODAY, ".ds-task").filter(has_text="Do taxes").wait_for()
    with app_db() as db:
        [made] = db.query(Task).all()
        assert (made.title, made.planned_for) == ("Do taxes", TODAY)
    cell(page, TODAY, ".ds-check").click()
    cell(page, TODAY, ".ds-task.is-done").wait_for()
    with app_db() as db:
        assert db.query(Task).one().status == TaskStatus.done


def test_a_habits_days_are_painted_with_a_drag(page, live, app_db) -> None:
    with app_db() as db:
        habits_svc.set_days(db, "morning-run", "")
        notebook.set_habit(db, START, "morning-run", True)
        db.commit()
    open_sheet(page, live)
    first = cell(page, START + timedelta(days=1), '[data-slug="morning-run"]').bounding_box()
    last = cell(page, START + timedelta(days=4), '[data-slug="morning-run"]').bounding_box()
    page.mouse.move(first["x"] + 20, first["y"] + 10)
    page.mouse.down()
    page.mouse.move(last["x"] + 20, last["y"] + 10, steps=2)
    page.mouse.up()
    cell(page, START + timedelta(days=4), '[data-slug="morning-run"][data-state="done"]').wait_for()
    with app_db() as db:
        done = {
            day for day in (START + timedelta(days=i) for i in range(6))
            if habits_svc.grid(db, day, 1)[0]["checks"][0]["state"] == "done"
        }
    assert done == {START + timedelta(days=i) for i in range(5)}
    # A click on a done day unticks it; its notes no longer have it.
    cell(page, START, '[data-slug="morning-run"]').click()
    cell(page, START, '[data-slug="morning-run"][data-state=""]').wait_for()
    with app_db() as db:
        assert [b["kind"] for b in notebook.blocks_of(db, START)] == []
