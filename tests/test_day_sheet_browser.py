"""Calendar's sheet in a real browser, worked as a spreadsheet: where Oscar
stays written and filled down, a task written for a day, started and done,
its status chosen from its menu, a day's page opened from its plan, and a
habit's days painted with a drag. The `live`, `page` and `app_db` fixtures
are conftest.py's."""

from datetime import date, timedelta

import pytest

from app.models import Task, TaskStatus
from app.services import habits as habits_svc
from app.services import notebook
from app.services import tasks as tasks_svc
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
    tuesday = monday + timedelta(days=1)
    wednesday = monday + timedelta(days=2)
    cell(page, monday, '[data-name="place"]').click()
    # Typing writes over the cell; Enter writes it and goes down.
    page.keyboard.type("Leiden")
    page.keyboard.press("Enter")
    cell(page, monday, '[data-name="place"][data-value="Leiden"]').wait_for()
    assert page.locator(".ds-cell.is-cursor").get_attribute("data-col") == "1"
    assert page.locator("tr.has-cursor").get_attribute("data-day") == tuesday.isoformat()
    # Accommodation is a checkbox: Space ticks it sorted.
    page.keyboard.press("ArrowUp")
    page.keyboard.press("ArrowRight")
    page.keyboard.press(" ")
    cell(page, monday, '[data-kind="check"][data-done="true"]').wait_for()
    # Both filled down the next two days from it.
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("Shift+ArrowRight")
    page.keyboard.press("Shift+ArrowDown")
    page.keyboard.press("Shift+ArrowDown")
    page.keyboard.press("Control+d")
    cell(page, wednesday, '[data-name="accommodation"][data-done="true"]').wait_for()
    for day in (monday, tuesday, wednesday):
        assert stay(app_db, day) == [
            {"name": "place", "value": "Leiden", "done": False},
            {"name": "accommodation", "value": "", "done": True},
        ]
    # Delete clears the words and unticks the box; Esc while writing keeps
    # what was there.
    page.keyboard.press("Escape")
    page.keyboard.press("Delete")
    cell(page, wednesday, '[data-name="accommodation"][data-done="false"]').wait_for()
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("Delete")
    cell(page, wednesday, '[data-name="place"][data-value=""]').wait_for()
    page.keyboard.press("Enter")
    page.keyboard.type("Delft")
    page.keyboard.press("Escape")
    page.locator(".ds-input").wait_for(state="detached")
    assert cell(page, wednesday, '[data-name="place"]').get_attribute("data-value") == ""
    assert stay(app_db, monday)[0]["value"] == "Leiden"
    # A click ticks a day's box, as it does a habit's.
    cell(page, tuesday, '[data-name="accommodation"]').click()
    cell(page, tuesday, '[data-name="accommodation"][data-done="false"]').wait_for()
    # The sheet's own keys do not reach the page's: "Leiden" switched no view.
    assert "view=day" not in page.url


def test_a_day_folds_to_its_first_line_and_stays_folded(page, live, app_db) -> None:
    with app_db() as db:
        for title in ("Book driving test", "Lunch at Delft", "Do taxes"):
            tasks_svc.create_task(db, title=title, planned_for=TODAY)
        tasks_svc.create_task(db, title="Alone", planned_for=TODAY + timedelta(days=1))
        db.commit()
    open_sheet(page, live)
    row = page.locator(f'tr[data-day="{TODAY.isoformat()}"]')
    tall = row.bounding_box()["height"]
    # A day with one line has nothing to fold.
    assert cell(page, TODAY + timedelta(days=1), "[data-fold]").count() == 0
    row.locator("[data-fold]").click()
    page.locator("tr.is-folded").wait_for()
    assert row.bounding_box()["height"] < tall
    assert row.locator(".ds-more").inner_text() == "+2"
    assert row.locator(".ds-task:visible").count() == 1
    # Folded it stays, through a redraw and a visit.
    page.reload()
    page.locator("tr.is-folded").wait_for()
    # Alt+Right on the day opens it; the header's chevron folds every day.
    cell(page, TODAY, '[data-kind="plan"]').click(position={"x": 300, "y": 8})
    page.keyboard.press("Alt+ArrowRight")
    page.locator("tr.is-folded").wait_for(state="detached")
    page.locator("[data-fold-all]").click()
    page.locator(f'tr.is-folded[data-day="{TODAY.isoformat()}"]').wait_for()


def test_a_task_is_written_for_its_day_and_ticked(page, live, app_db) -> None:
    open_sheet(page, live)
    plan = cell(page, TODAY, '[data-kind="plan"]')
    plan.click()
    page.keyboard.press("Enter")
    # The cursor's whole row is shaded, not its cell alone.
    shades = page.locator("tr.has-cursor > *").evaluate_all(
        "cells => cells.map(c => getComputedStyle(c).backgroundImage)"
    )
    assert all(s.startswith("linear-gradient") for s in shades)
    # Words that run past the cell wrap, the box growing so all stay in sight.
    words = "Do taxes, " + "and gather every receipt from the year " * 4
    page.keyboard.type(words)
    box = page.locator(".ds-input")
    assert box.evaluate("b => b.scrollHeight <= b.clientHeight && b.clientHeight > 40")
    page.keyboard.press("Enter")
    cell(page, TODAY, ".ds-task").filter(has_text="Do taxes").wait_for()
    with app_db() as db:
        [made] = db.query(Task).all()
        assert (made.title, made.planned_for) == (words.strip(), TODAY)
    # A click starts it, a second makes it done.
    cell(page, TODAY, ".ds-check").click()
    cell(page, TODAY, ".ds-task.is-in-progress").wait_for()
    with app_db() as db:
        assert db.query(Task).one().status == TaskStatus.in_progress
    cell(page, TODAY, ".ds-check").click()
    cell(page, TODAY, ".ds-task.is-done").wait_for()
    with app_db() as db:
        assert db.query(Task).one().status == TaskStatus.done


def test_a_double_click_writes_in_a_cell_and_on_a_plan_opens_its_day(page, live, app_db) -> None:
    tomorrow = TODAY + timedelta(days=1)
    with app_db() as db:
        tasks_svc.create_task(db, title="Pay rent", planned_for=tomorrow)
        db.commit()
    open_sheet(page, live)
    cell(page, tomorrow, '[data-name="place"]').dblclick()
    page.locator(".ds-input").wait_for()
    page.keyboard.press("Escape")
    page.locator(".ds-input").wait_for(state="detached")
    # Beside its task, not on it: the task's own parts keep their clicks.
    cell(page, tomorrow, '[data-kind="plan"]').dblclick(position={"x": 300, "y": 8})
    page.wait_for_url(f"{live}/day/{tomorrow.isoformat()}")
    with app_db() as db:
        assert db.query(Task).one().status == TaskStatus.todo


def test_a_tasks_status_is_chosen_from_its_menu(page, live, app_db) -> None:
    with app_db() as db:
        tasks_svc.create_task(db, title="Pay rent", planned_for=TODAY)
        db.commit()
    open_sheet(page, live)
    menu = page.locator(".sheet-menu")
    # Its chevron opens the statuses, none chosen while it is to do.
    cell(page, TODAY, ".ds-status").click()
    assert menu.get_by_role("menuitemradio").all_inner_texts() == ["In progress", "Done"]
    assert menu.locator('[aria-checked="true"]').count() == 0
    menu.get_by_role("menuitemradio", name="Done").click()
    cell(page, TODAY, ".ds-task.is-done").wait_for()
    assert menu.count() == 0
    with app_db() as db:
        assert db.query(Task).one().status == TaskStatus.done
    # From the keys: In progress; Esc closes it, the cursor back on its cell.
    cell(page, TODAY, ".ds-status").click()
    page.keyboard.press("ArrowUp")
    page.keyboard.press("Enter")
    cell(page, TODAY, ".ds-task.is-in-progress").wait_for()
    cell(page, TODAY, ".ds-status").click()
    assert menu.locator('[aria-checked="true"]').inner_text() == "In progress"
    page.keyboard.press("Escape")
    assert menu.count() == 0
    assert page.evaluate("document.activeElement.dataset.kind") == "plan"
    # The status it has, chosen again, takes it back to to do.
    cell(page, TODAY, ".ds-status").click()
    menu.get_by_role("menuitemradio", name="In progress").click()
    cell(page, TODAY, ".ds-task.is-in-progress").wait_for(state="detached")
    with app_db() as db:
        assert db.query(Task).one().status == TaskStatus.todo


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


def test_a_task_is_deleted_from_its_bin_or_with_delete(page, live, app_db) -> None:
    with app_db() as db:
        tasks_svc.create_task(db, title="Cancel gym", planned_for=TODAY)
        tasks_svc.create_task(db, title="Pay rent", planned_for=TODAY)
        db.commit()
    open_sheet(page, live)
    gym = cell(page, TODAY, ".ds-task").filter(has_text="Cancel gym")
    # Its bin asks first; Cancel keeps it.
    gym.hover()
    gym.locator(".ds-delete").click()
    dialog = page.locator("#confirm-dialog")
    dialog.get_by_role("button", name="Cancel").click()
    with app_db() as db:
        assert db.query(Task).count() == 2
    gym.hover()
    gym.locator(".ds-delete").click()
    dialog.get_by_role("button", name="Delete").click()
    gym.wait_for(state="detached")
    with app_db() as db:
        assert [t.title for t in db.query(Task).all()] == ["Pay rent"]
    # Delete on the plan's cell asks for what it holds, the cursor kept.
    page.keyboard.press("Delete")
    assert "Pay rent" in dialog.locator(".confirm-name").inner_text()
    dialog.get_by_role("button", name="Delete").click()
    cell(page, TODAY, ".ds-task").wait_for(state="detached")
    with app_db() as db:
        assert db.query(Task).count() == 0
    assert page.locator(".ds-cell.is-cursor").get_attribute("data-kind") == "plan"


def test_cells_are_copied_and_pasted_as_a_spreadsheets(page, live, app_db) -> None:
    monday = START
    wednesday, thursday, saturday = (START + timedelta(days=i) for i in (2, 3, 5))
    with app_db() as db:
        notebook.set_stay_item(db, monday, "place", value="Leiden")
        notebook.set_stay_item(db, monday, "accommodation", done=True)
        tasks_svc.create_task(db, title="Pay rent", planned_for=monday)
        tasks_svc.create_task(db, title='Call "mum"', planned_for=monday)
        habits_svc.set_days(db, "morning-run", "")
        notebook.set_habit(db, monday, "morning-run", True)
        db.commit()
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=live)
    open_sheet(page, live)
    # Windows' clipboard breaks lines with CRLF.
    clipboard = lambda: page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")  # noqa: E731
    # The day's row across, as tab-separated text: a tick an x, a plan its
    # tasks a line each, quoted.
    cell(page, monday, '[data-name="place"]').click()
    for _ in range(3):
        page.keyboard.press("Shift+ArrowRight")
    page.keyboard.press("Control+c")
    page.wait_for_function("navigator.clipboard.readText().then(t => t.length > 0)")
    assert clipboard() == 'Leiden\tx\t"Pay rent\nCall ""mum"""\tx'
    # Pasted from Wednesday's place, the whole row written there.
    cell(page, wednesday, '[data-name="place"]').click()
    page.keyboard.press("Control+v")
    cell(page, wednesday, '[data-slug="morning-run"][data-state="done"]').wait_for()
    assert stay(app_db, wednesday) == [
        {"name": "place", "value": "Leiden", "done": False},
        {"name": "accommodation", "value": "", "done": True},
    ]
    with app_db() as db:
        titles = sorted(t.title for t in db.query(Task).filter(Task.planned_for == wednesday))
    assert titles == ['Call "mum"', "Pay rent"]
    # Again, over a place written since: the tasks the day has already are
    # not written twice.
    page.keyboard.type("Perth")
    page.keyboard.press("Enter")
    cell(page, wednesday, '[data-name="place"][data-value="Perth"]').click()
    page.keyboard.press("Control+v")
    cell(page, wednesday, '[data-name="place"][data-value="Leiden"]').wait_for()
    with app_db() as db:
        assert db.query(Task).filter(Task.planned_for == wednesday).count() == 2
    # One cell fills the range.
    cell(page, monday, '[data-name="place"]').click()
    page.keyboard.press("Control+c")
    cell(page, thursday, '[data-name="place"]').click()
    cell(page, saturday, '[data-name="place"]').click(modifiers=["Shift"])
    page.keyboard.press("Control+v")
    cell(page, saturday, '[data-name="place"][data-value="Leiden"]').wait_for()
    for day in (thursday, thursday + timedelta(days=1), saturday):
        assert stay(app_db, day)[0]["value"] == "Leiden"
    # A spreadsheet's cells paste too; an empty one clears.
    page.evaluate("text => navigator.clipboard.writeText(text)", "Delft\t\r\n")
    cell(page, wednesday, '[data-name="place"]').click()
    page.keyboard.press("Control+v")
    cell(page, wednesday, '[data-name="accommodation"][data-done="false"]').wait_for()
    assert cell(page, wednesday, '[data-name="place"]').get_attribute("data-value") == "Delft"
