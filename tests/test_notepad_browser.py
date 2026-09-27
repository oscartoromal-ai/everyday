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


def text_of(page) -> str:
    """The notes as written in the page's editor."""
    return page.evaluate("Notepad.text()")


def write_in(page) -> None:
    """Into the notes, as a click on them does."""
    page.locator(".pad-editor .cm-content").click()


def test_notes_save_as_they_are_written(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("Slow morning.")
    page.keyboard.press("Enter")
    page.keyboard.type("- call the dentist")
    saved_as(app_db, [{"kind": "text", "text": "Slow morning.\n- call the dentist"}])

    # Just text: a "- " line stays a line, and no task is made of it.
    page.reload()
    assert text_of(page) == "Slow morning.\n- call the dentist"
    from app.services import tasks as tasks_svc

    with app_db() as db:
        assert tasks_svc.list_tasks(db) == []


def test_notes_changed_in_another_window_ask_which_to_keep(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    write_in(page)
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
    write_in(page)
    page.keyboard.type("Morning.")
    page.keyboard.press("Enter")

    # "- [ ] " makes the row a task: drawn as its box and the word Task.
    page.keyboard.type("- [ ] Call the dentist")
    titles = page.locator(".pad-editor .cm-line.pad-title")
    assert titles.count() == 1
    assert titles.first.locator(".pad-check").is_visible()
    assert titles.first.locator(".pad-kind-name").inner_text() == "Task"
    # Enter goes on to the task's next row, tabbed in under its title.
    page.keyboard.press("Enter")
    page.keyboard.type("- ask about the crown")
    current = page.locator(".cm-lineNumbers .cm-gutterElement.pad-current")
    assert current.all_inner_texts() == ["2", "3"]
    assert text_of(page) == "Morning.\n- [ ] Call the dentist\n\t- ask about the crown"

    # Ctrl+Enter saves it (the task is added) and goes on to a plain row;
    # the task stays bracketed.
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added: Call the dentist").wait_for()
    page.keyboard.type("After.")
    notes = "Morning.\n- [ ] Call the dentist\n\t- ask about the crown\nAfter."
    assert text_of(page) == notes
    assert page.locator(".pad-editor .cm-line.pad-last").count() == 1
    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        assert task.title == "Call the dentist"
        assert (task.notes, task.planned_for) == ("- ask about the crown", TODAY)
        task_id = task.id
    saved_as(app_db, [{"kind": "text", "text": notes, "links": {"1": task_id}}])

    # Going back into it and saving again writes the change to the task.
    page.keyboard.press("ArrowUp")
    page.keyboard.press("End")
    page.keyboard.type(" and the cleaning")
    page.keyboard.press("Escape")
    page.locator(".cal-toast.show", has_text="Task saved: Call the dentist").wait_for()
    with app_db() as db:
        assert tasks_svc.get_task(db, task_id).notes == "- ask about the crown and the cleaning"

    # Its box ticks the task; the row keeps its task after a reload.
    titles.first.locator(".pad-check").click()
    titles.first.locator(".pad-check[aria-checked=true]").wait_for()
    ticked = "Morning.\n- [x] Call the dentist\n\t- ask about the crown and the cleaning\nAfter."
    saved_as(app_db, [{"kind": "text", "text": ticked, "links": {"1": task_id}}])
    with app_db() as db:
        assert tasks_svc.get_task(db, task_id).status == TaskStatus.done
    page.reload()
    assert text_of(page).startswith("Morning.\n- [x] Call the dentist\n")
    assert titles.first.locator(".pad-check").get_attribute("aria-checked") == "true"

    # The caret never stands in the box: Home goes to the title's first word,
    # and Backspace there takes the box away, a plain row again.
    write_in(page)
    page.keyboard.press("Control+Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("End")
    page.keyboard.press("Home")
    page.keyboard.press("Backspace")
    assert titles.count() == 0
    plain = "Morning.\nCall the dentist\n\t- ask about the crown and the cleaning\nAfter."
    saved_as(app_db, [{"kind": "text", "text": plain}])


def test_a_long_row_wraps_and_the_icons_keep_to_its_end(page, live) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("- [ ] Short")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")  # out of the task
    long = "a title long enough to run past the width of the box " * 3
    page.keyboard.type(f"- [ ] {long.strip()}")
    titles = page.locator(".pad-editor .cm-line.pad-title")
    short, wrapped = titles.nth(0), titles.nth(1)
    box = page.locator(".pad-editor .cm-content").bounding_box()

    def props_of(title):
        return title.locator(".pad-props").bounding_box()

    # A short title: its icons at the row's right, on its line.
    row = short.bounding_box()
    icons = props_of(short)
    assert row["height"] == 36
    assert abs(icons["y"] - (row["y"] + 7)) <= 1
    # A long one wraps inside its row (no scrolling sideways), and its icons
    # go under its last line, still at the right: the row grows, no row is added.
    row = wrapped.bounding_box()
    icons = props_of(wrapped)
    assert row["height"] > 36 * 2
    assert page.evaluate("Notepad.view.scrollDOM.scrollWidth <= Notepad.view.scrollDOM.clientWidth")
    assert icons["y"] + icons["height"] >= row["y"] + row["height"] - 7 - 1
    right = props_of(short)["x"] + props_of(short)["width"]
    assert abs((icons["x"] + icons["width"]) - right) <= 1
    assert icons["x"] + icons["width"] <= box["x"] + box["width"]
    assert text_of(page).count("\n") == 1  # one row each


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
    write_in(page)
    page.keyboard.type("- [ ] Mow the lawn")

    # At the title's right, the task sheet's icons; what they set before the
    # task is added goes with it when it is.
    props = page.locator(".pad-editor .pad-props[data-ready]")
    props.locator(".prop[data-prop=planned_for]").click()
    # By name, exactly: on a Sunday, Next week's aside also reads "tomorrow".
    page.locator(".sheet-menu").get_by_role("menuitemradio", name="Tomorrow", exact=True).click()
    assert props.locator(".prop[data-prop=planned_for] .prop-value").inner_text() == "tomorrow"
    # The caret is back in the notes, where writing carries on.
    assert page.evaluate("document.activeElement.classList.contains('cm-content')")
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


def test_a_task_row_is_deleted_from_its_controls(page, live, app_db) -> None:
    from app.services import tasks as tasks_svc

    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("Morning.")
    page.keyboard.press("Enter")
    page.keyboard.type("- [ ] Not this one")
    page.keyboard.press("Enter")
    page.keyboard.type("- or this")
    titles = page.locator(".pad-editor .cm-line.pad-title")

    # Not added yet: its rows go, with no question, and undo brings them back.
    titles.first.locator("[data-pad-remove]").click()
    assert text_of(page) == "Morning."
    assert titles.count() == 0
    page.keyboard.press("Control+z")
    assert text_of(page) == "Morning.\n- [ ] Not this one\n\t- or this"
    page.keyboard.press("Control+a")
    page.keyboard.type("Morning.\n- [ ] Call the dentist")
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added: Call the dentist").wait_for()
    page.keyboard.type("After.")

    # Added: the app's own question first; kept, nothing changes.
    titles.first.locator("[data-pad-remove]").click()
    dialog = page.locator("#confirm-dialog")
    dialog.get_by_role("button", name="Cancel").click()
    assert text_of(page) == "Morning.\n- [ ] Call the dentist\nAfter."
    with app_db() as db:
        assert len(tasks_svc.list_tasks(db)) == 1

    # Confirmed: the task goes from the plan and its row from the notes.
    titles.first.locator("[data-pad-remove]").click()
    dialog.get_by_role("button", name="Delete").click()
    page.locator(".cal-toast.show", has_text="Task deleted: Call the dentist").wait_for()
    assert text_of(page) == "Morning.\nAfter."
    assert titles.count() == 0
    with app_db() as db:
        assert tasks_svc.list_tasks(db) == []
    saved_as(app_db, [{"kind": "text", "text": "Morning.\nAfter."}])


def test_a_reflection_is_written_in_the_notes(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("Morning.")
    page.keyboard.press("Enter")

    # "/reflection" at a row's start makes the row a reflection: the word
    # Reflection in its indent, its rows bracketed in light blue.
    page.keyboard.type("/reflection Calmer than yesterday.")
    reflection = page.locator(".pad-editor .cm-line.pad-reflection")
    assert reflection.count() == 1
    assert reflection.first.locator(".pad-reflection-name").inner_text() == "Reflection"
    # Enter goes on to its next row, tabbed in under it; Ctrl+Enter out of it.
    page.keyboard.press("Enter")
    page.keyboard.type("Slept well.")
    assert reflection.count() == 2
    page.keyboard.press("Control+Enter")
    page.keyboard.type("After.")
    assert reflection.count() == 2
    written = "Morning.\n/reflection Calmer than yesterday.\n\tSlept well.\nAfter."
    assert page.evaluate("Notepad.text()") == written

    # Saved as a reflection between the text around it, and read back as written.
    saved_as(app_db, [
        {"kind": "text", "text": "Morning."},
        {"kind": "reflection", "text": "Calmer than yesterday.\nSlept well."},
        {"kind": "text", "text": "After."},
    ])
    page.reload()
    assert page.evaluate("Notepad.text()") == written
    assert reflection.count() == 2

    # Backspace at its first word takes the label away: a plain row again.
    write_in(page)
    page.keyboard.press("Control+Home")
    page.keyboard.press("ArrowDown")
    # Home there stays at its first word; Left goes on to the row above.
    head = "Notepad.view.state.selection.main.head"
    page.keyboard.press("Home")
    assert page.evaluate(head) == len("Morning.\n/reflection ")
    page.keyboard.press("ArrowLeft")
    assert page.evaluate(head) == len("Morning.")
    page.keyboard.press("ArrowRight")
    assert page.evaluate(head) == len("Morning.\n/reflection ")
    page.keyboard.press("Backspace")
    assert page.evaluate("Notepad.text()").startswith("Morning.\nCalmer than yesterday.\n")
    assert page.locator(".pad-editor .cm-line.pad-reflection").count() == 0


def test_a_habit_is_checked_from_the_notes(page, live, app_db) -> None:
    from app.models import Habit, HabitCheck
    from app.services import habits as habits_svc

    today = str(TODAY.weekday())
    other = str((TODAY.weekday() + 1) % 7)
    with app_db() as db:
        habits_svc.set_days(db, "stretch", "")  # any day: due today
        habits_svc.set_days(db, "evening-skin-care", other)  # not today
        db.commit()

    def checks() -> dict[str, tuple[bool, str]]:
        with app_db() as db:
            return {c.habit.slug: (c.done, c.note) for c in db.query(HabitCheck).all()}

    page.goto(f"{live}/today")
    # Under the notes, the habits due today not yet written.
    strip = page.locator("#pad-habits")
    assert strip.locator(".pad-habit-write").all_inner_texts() == ["stretch"]

    # "/" offers the commands; "/habit " the names.
    write_in(page)
    page.keyboard.type("/ha")
    page.locator(".cm-tooltip-autocomplete li", has_text="/habit").wait_for()
    # Enter picks from what is offered once it has been on screen a moment
    # (CodeMirror's interactionDelay: a key pressed at once still types).
    page.wait_for_timeout(150)
    page.keyboard.press("Enter")
    page.locator(".cm-tooltip-autocomplete li", has_text="evening-skin-care").wait_for()
    page.keyboard.type("morning-skin-care new serum")
    # Past its name nothing is offered, and Ctrl+Enter goes on to a plain row.
    assert page.locator(".cm-tooltip-autocomplete").count() == 0
    habit = page.locator(".pad-editor .cm-line.pad-habit")
    assert habit.first.locator(".pad-kind-name").inner_text() == "Habit"
    assert habit.first.locator(".pad-check").get_attribute("aria-checked") == "true"
    page.keyboard.press("Control+Enter")
    assert page.evaluate("Notepad.text()") == "/habit morning-skin-care new serum\n"

    # A name in the strip writes its row.
    strip.locator(".pad-habit-write", has_text="stretch").click()
    assert page.evaluate("Notepad.text()") == "/habit morning-skin-care new serum\n/habit stretch"
    assert strip.is_hidden()
    page.keyboard.type(" ten minutes")
    end = time.monotonic() + 5
    while checks() != {"morning-skin-care": (True, "new serum"), "stretch": (True, "ten minutes")}:
        assert time.monotonic() < end, checks()
        time.sleep(0.1)

    # Unticked, it is skipped that day, and reads back so.
    habit.first.locator(".pad-check").click()
    assert page.evaluate("Notepad.text()").startswith("/habit [ ] morning-skin-care new serum\n")
    end = time.monotonic() + 5
    while checks().get("morning-skin-care") != (False, "new serum"):
        assert time.monotonic() < end, checks()
        time.sleep(0.1)
    page.reload()
    assert habit.first.locator(".pad-check").get_attribute("aria-checked") == "false"

    # Its icon sets its days: not due today, it leaves the strip.
    habit.nth(1).locator(".prop[data-prop=days]").click()
    page.locator(".sheet-menu [role=menuitemcheckbox]", has_text=[
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    ][int(other)]).click()
    page.keyboard.press("Escape")
    assert habit.nth(1).locator(".prop[data-prop=days] .prop-value").inner_text() != ""
    end = time.monotonic() + 5
    while True:
        with app_db() as db:
            if db.query(Habit).filter_by(slug="stretch").one().days == other:
                break
        assert time.monotonic() < end
        time.sleep(0.1)
    assert today != other


def test_a_stay_is_written_in_the_notes(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    # "/stay" comes with its items (place and accommodation, the first time).
    page.keyboard.type("/st")
    page.locator(".cm-tooltip-autocomplete li", has_text="/stay").wait_for()
    page.wait_for_timeout(150)  # CodeMirror's interactionDelay
    page.keyboard.press("Enter")
    page.keyboard.type("Lisbon")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("End")
    page.keyboard.type("Airbnb")
    # Enter on an item starts the next; its name is offered from the others.
    page.keyboard.press("Enter")
    page.keyboard.type("ferry: Sunday")
    written = "/stay\n\t- [ ] place: Lisbon\n\t- [ ] accommodation: Airbnb\n\t- [ ] ferry: Sunday"
    assert page.evaluate("Notepad.text()") == written
    stay = page.locator(".pad-editor .cm-line.pad-stay")
    assert stay.first.locator(".pad-stay-name").inner_text() == "Stay"
    assert stay.locator(".pad-item-check").count() == 3

    # Its box: sorted.
    stay.locator(".pad-item-check").first.click()
    assert page.evaluate("Notepad.text()").startswith("/stay\n\t- [x] place: Lisbon\n")
    # Under the date, item by item; a click goes to its row.
    line = page.locator("#day-stay .day-stay-item")
    assert [t.split() for t in line.all_inner_texts()] == [
        ["Place", "Lisbon"], ["Accommodation", "Airbnb"], ["Ferry", "Sunday"],
    ]
    assert line.nth(0).get_attribute("class") == "day-stay-item done"
    line.nth(1).click()
    caret_row = "(s => s.doc.lineAt(s.selection.main.head).number)(Notepad.view.state)"
    assert page.evaluate(caret_row) == 3

    # Saved as a stay, and read back as written.
    stay_text = "\n- [x] place: Lisbon\n- [ ] accommodation: Airbnb\n- [ ] ferry: Sunday"
    saved_as(app_db, [{"kind": "stay", "text": stay_text}])
    page.reload()
    assert page.evaluate("Notepad.text()") == written.replace("[ ] place", "[x] place")
    assert line.count() == 3
