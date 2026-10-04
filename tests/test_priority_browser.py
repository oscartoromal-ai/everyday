"""A task's priority in a real browser: written as "p1" to "p4" in the task
sheet or picked from its menu, given from Projects' list with "!", written
in Today's notes, and worked as a cell on a project's Gantt. The `live`,
`page` and `app_db` fixtures are conftest.py's."""

import time
from datetime import date

import pytest

from app.models import TaskPriority
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()


def priority_of(app_db, title: str, expected: TaskPriority | None, timeout: float = 5) -> None:
    """The task's priority as the server has it, once the page has saved it."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with app_db() as db:
            task = next(t for t in tasks_svc.list_tasks(db) if t.title == title)
            if task.priority == expected:
                return
        time.sleep(0.1)
    assert task.priority == expected


def test_the_sheet_takes_it_as_words_or_from_its_menu(page, live, app_db) -> None:
    page.goto(f"{live}/plan")
    sheet = page.locator(".main .task-sheet[data-sheet=compose]")
    title = sheet.locator(".sheet-title")
    prop = sheet.locator(".prop[data-prop=priority]")
    sheet.locator(".sheet-line").click()

    page.keyboard.type("Book the venue p1 ")
    assert title.text_content() == "Book the venue "
    assert sheet.locator("input[name=priority]").input_value() == "urgent"
    assert prop.locator(".prop-value").text_content() == "Urgent"
    assert prop.locator(".priority-icon").get_attribute("data-priority") == "urgent"
    assert prop.get_attribute("aria-label") == "Priority: Urgent"
    # Backspace right after puts the words back.
    page.keyboard.press("Backspace")
    assert title.text_content() == "Book the venue p1"
    assert sheet.locator("input[name=priority]").input_value() == ""
    assert prop.locator(".priority-icon").get_attribute("data-priority") == ""
    page.keyboard.press("Backspace")
    page.keyboard.press("Backspace")

    # Its menu: most first, each after its bars, P1 to P4 beside them.
    prop.click()
    menu = page.locator(".sheet-menu")
    items = menu.get_by_role("menuitemradio")
    assert items.all_inner_texts() == [
        "Urgent\nP1", "High\nP2", "Medium\nP3", "Low\nP4", "No priority",
    ]
    assert menu.get_by_role("menuitemradio", name="No priority").get_attribute(
        "aria-checked") == "true"
    icons = menu.locator(".priority-icon")
    assert [icons.nth(i).get_attribute("data-priority") for i in range(5)] == [
        "urgent", "high", "medium", "low", "",
    ]
    menu.get_by_role("menuitemradio", name="Medium").click()
    assert prop.locator(".prop-value").text_content() == "Medium"
    page.keyboard.press("Control+Enter")
    row = page.locator(".task-row", has_text="Book the venue")
    row.wait_for()
    assert row.locator(".priority").inner_text() == "Medium"
    assert row.locator(".priority").get_attribute("title") == "Priority: Medium"
    priority_of(app_db, "Book the venue", TaskPriority.medium)


def test_bang_gives_a_row_its_priority_and_the_cursor_stays(page, live, app_db) -> None:
    with app_db() as db:
        tasks_svc.create_task(db, title="Alpha")
        tasks_svc.create_task(db, title="Bravo")
        db.commit()
    page.goto(f"{live}/plan")
    page.locator('.task-row[data-task-title="Alpha"]').focus()
    page.keyboard.press("!")
    page.locator(".sheet-menu").wait_for()
    page.keyboard.press("ArrowDown")  # from No priority, round to Urgent
    page.keyboard.press("Enter")
    priority_of(app_db, "Alpha", TaskPriority.urgent)
    page.wait_for_function(
        "document.activeElement?.dataset?.taskTitle === 'Alpha'"
        " && !!document.activeElement.querySelector('.priority')"
    )
    assert page.locator('.task-row[data-task-title="Alpha"] .priority').inner_text() == "Urgent"


def test_a_task_written_in_the_notes_takes_it(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    page.locator(".pad-editor .cm-content").click()
    page.keyboard.type("- [ ] Book the venue p2 ")
    props = page.locator(".pad-editor .pad-props[data-ready]")
    assert props.locator(".prop[data-prop=priority] .prop-value").inner_text() == "High"
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added: Book the venue").wait_for()
    priority_of(app_db, "Book the venue", TaskPriority.high)

    # Once added, its controls change the task itself.
    props.locator(".prop[data-prop=priority]").click()
    page.locator(".sheet-menu").get_by_role("menuitemradio", name="Low").click()
    priority_of(app_db, "Book the venue", TaskPriority.low)


def test_the_gantt_works_it_as_a_cell(page, live, app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Launch")
        tasks_svc.create_task(db, title="Book the venue", project_id=project.id)
        db.commit()
        project_id = project.id
    page.goto(f"{live}/projects/{project_id}/gantt")
    row = page.locator('.gantt-row[data-title="Book the venue"]')
    cell = row.locator(".gantt-priority")
    head = page.locator(".gantt-head .gantt-priority")
    assert head.inner_text() == "Priority"

    # Enter opens its menu; the choice is drawn as the bars and the word.
    cell.click()
    page.keyboard.press("Enter")
    menu = page.locator(".sheet-menu")
    menu.wait_for()
    assert menu.get_by_role("menuitemradio").all_inner_texts() == [
        "Urgent", "High", "Medium", "Low", "No priority",
    ]
    page.keyboard.press("Home")
    page.keyboard.press("Enter")
    page.wait_for_function(
        "document.querySelector('.gantt-row[data-title=\"Book the venue\"]')"
        ".dataset.priority === 'urgent'"
    )
    assert cell.inner_text() == "Urgent"
    assert cell.locator(".priority-icon").get_attribute("data-priority") == "urgent"
    priority_of(app_db, "Book the venue", TaskPriority.urgent)
    # The cursor stays on the cell, with the focus.
    assert page.evaluate("document.activeElement.dataset.col") == "2"

    # Typed over, as any cell; a word it cannot read is refused.
    page.keyboard.type("4")
    page.keyboard.press("Enter")
    priority_of(app_db, "Book the venue", TaskPriority.low)
    page.keyboard.press("ArrowUp")
    page.keyboard.type("top")
    page.keyboard.press("Enter")
    page.locator(".cal-toast").get_by_text("Not a priority: top").wait_for()
    page.keyboard.press("Escape")

    # Delete clears it; undo brings it back.
    page.keyboard.press("Delete")
    priority_of(app_db, "Book the venue", None)
    page.wait_for_function(
        "document.querySelector('.gantt-row[data-title=\"Book the venue\"]')"
        ".dataset.priority === ''"
    )
    assert cell.inner_text() == ""
    page.keyboard.press("Control+z")
    priority_of(app_db, "Book the venue", TaskPriority.low)

    # A double click opens the menu too, and it stays open.
    cell.dblclick()
    menu.wait_for()
    time.sleep(0.2)
    assert menu.is_visible()
    menu.get_by_role("menuitemradio", name="High").click()
    priority_of(app_db, "Book the venue", TaskPriority.high)
