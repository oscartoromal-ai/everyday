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

    # "- [ ] " makes the row a task: the marker becomes a tab, and in the gap
    # the task's box and the word Task (only a task's rows are tabbed in).
    page.keyboard.type("- [ ] Call the dentist")
    marks = page.locator(".pad-marks .pad-task-mark")
    assert marks.count() == 1
    assert marks.first.locator(".pad-check").is_visible()
    assert marks.first.locator(".pad-kind-name").inner_text() == "Task"
    # Enter goes on to the task's next row, tabbed in under its title.
    page.keyboard.press("Enter")
    page.keyboard.type("- ask about the crown")
    assert page.locator(".pad-rows-inner > div.task").all_inner_texts() == ["2", "3"]
    assert pad.input_value() == "Morning.\n\tCall the dentist\n\t- ask about the crown"

    # Ctrl+Enter saves it (the task is added) and goes on to a plain row;
    # the task stays bracketed.
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added: Call the dentist").wait_for()
    page.keyboard.type("After.")
    assert pad.input_value() == "Morning.\n\tCall the dentist\n\t- ask about the crown\nAfter."
    assert marks.count() == 1
    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        assert task.title == "Call the dentist"
        assert (task.notes, task.planned_for) == ("- ask about the crown", TODAY)
        task_id = task.id
    notes = "Morning.\n- [ ] Call the dentist\n\t- ask about the crown\nAfter."
    saved_as(app_db, [{"kind": "text", "text": notes, "links": {"1": task_id}}])

    # Going back into it and saving again writes the change to the task.
    page.keyboard.press("ArrowUp")
    page.keyboard.press("End")
    page.keyboard.type(" and the cleaning")
    page.keyboard.press("Escape")
    page.locator(".cal-toast.show", has_text="Task saved: Call the dentist").wait_for()
    with app_db() as db:
        assert tasks_svc.get_task(db, task_id).notes == "- ask about the crown and the cleaning"

    # Its box ticks the task; the row keeps its kind after a reload.
    marks.first.locator(".pad-check").click()
    marks.first.locator(".pad-check[aria-checked=true]").wait_for()
    ticked = "Morning.\n- [x] Call the dentist\n\t- ask about the crown and the cleaning\nAfter."
    saved_as(app_db, [{"kind": "text", "text": ticked, "links": {"1": task_id}}])
    with app_db() as db:
        assert tasks_svc.get_task(db, task_id).status == TaskStatus.done
    page.reload()
    assert pad.input_value().startswith("Morning.\n\tCall the dentist\n")
    assert marks.first.locator(".pad-check").get_attribute("aria-checked") == "true"

    # Backspace at a task row's start takes its tab away: a plain row again.
    pad.click()
    page.keyboard.press("Control+Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Home")
    page.keyboard.press("Backspace")
    assert marks.count() == 0
    plain = "Morning.\nCall the dentist\n\t- ask about the crown and the cleaning\nAfter."
    saved_as(app_db, [{"kind": "text", "text": plain}])


def test_a_task_row_sets_its_fields_from_its_controls(page, live, app_db) -> None:
    from datetime import timedelta

    from app.services import projects as projects_svc
    from app.services import tasks as tasks_svc

    with app_db() as db:
        home = projects_svc.create_project(db, name="Home")
        projects_svc.create_milestone(db, project_id=home.id, name="Garden")
        db.commit()
    tomorrow = TODAY + timedelta(days=1)
    page.goto(f"{live}/today")
    pad = page.locator("#notepad")
    pad.click()
    page.keyboard.type("- [ ] Mow the lawn")

    # At the title's right, the task sheet's icons; what they set before the
    # task is added goes with it when it is.
    props = page.locator(".pad-task-mark .pad-props[data-ready]")
    props.locator(".prop[data-prop=planned_for]").click()
    # By name, exactly: on a Sunday, Next week's aside also reads "tomorrow".
    page.locator(".sheet-menu").get_by_role("menuitemradio", name="Tomorrow", exact=True).click()
    assert props.locator(".prop[data-prop=planned_for] .prop-value").inner_text() == "tomorrow"
    # The caret is back in the notes, where writing carries on.
    assert page.evaluate("document.activeElement.id") == "notepad"
    page.keyboard.type(" today")
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added: Mow the lawn today").wait_for()
    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        assert (task.title, task.planned_for) == ("Mow the lawn today", tomorrow)
        task_id = task.id

    # Once added, a change goes straight to the task: a milestone, with its project.
    props.locator(".prop[data-prop=project]").click()
    page.locator(".sheet-menu [role=menuitemradio]", has_text="Garden").click()
    assert props.locator(".prop[data-prop=project] .prop-value").inner_text() == "Home › Garden"
    end = time.monotonic() + 5
    while time.monotonic() < end:
        with app_db() as db:
            task = tasks_svc.get_task(db, task_id)
            if task.milestone_id:
                break
        time.sleep(0.1)
    with app_db() as db:
        task = tasks_svc.get_task(db, task_id)
        assert (task.project.name, task.milestone.name) == ("Home", "Garden")
        assert (task.title, task.planned_for) == ("Mow the lawn today", tomorrow)

    # The controls show the task as it stands after a reload.
    notes = "- [ ] Mow the lawn today"
    saved_as(app_db, [{"kind": "text", "text": notes, "links": {"0": task_id}}])
    page.reload()
    assert props.locator(".prop[data-prop=planned_for] .prop-value").inner_text() == "tomorrow"
    assert props.locator(".prop[data-prop=project] .prop-value").inner_text() == "Home › Garden"
