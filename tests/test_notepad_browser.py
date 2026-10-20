"""Today's notepad in a real browser: notes for the day in Markdown, drawn
as they read, saved as they are written, and a question instead of an
overwrite when another window saved first. notepad.js only runs in a
browser; the `live` and `page` fixtures are conftest.py's."""

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


def folded_to(fold) -> tuple[str, str]:
    """A fold's name and count, as its summary line shows them."""
    summary = fold.locator(".today-fold-summary")
    return summary.locator(".today-fold-label").inner_text(), summary.locator(".count").inner_text()


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
        projects_svc.create_workstream(db, project_id=home.id, name="Garden")
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
    page.keyboard.type(" short")
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added: Mow the lawn short").wait_for()
    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        assert (task.title, task.planned_for) == ("Mow the lawn short", tomorrow)
        task_id = task.id

    # Once added, a change goes straight to the task: a workstream, with its project.
    # The project is its flag in the project's colour (in the menu too), its
    # name on hover, and the task's rules take the colour.
    flag = props.locator(".prop[data-prop=project]")
    title = page.locator(".pad-editor .cm-line.pad-title")
    assert "pad-project" not in title.get_attribute("class")
    flag.click()
    home = page.locator(".sheet-menu [role=menuitemradio]", has_text="Home")
    assert home.locator(".flag").count() == 1
    assert home.evaluate("e => e.style.getPropertyValue('--project')") == "var(--hue-1)"
    page.locator(".sheet-menu [role=menuitemradio]", has_text="Garden").click()
    assert flag.get_attribute("title") == "Project: Home › Garden"
    assert flag.locator(".prop-value").inner_text() == ""
    assert "in-project" in flag.get_attribute("class")
    assert "pad-hue-1" in title.get_attribute("class")
    end = time.monotonic() + 5
    while time.monotonic() < end:
        with app_db() as db:
            task = tasks_svc.get_task(db, task_id)
            if task.workstream_id:
                break
        time.sleep(0.1)
    with app_db() as db:
        task = tasks_svc.get_task(db, task_id)
        assert (task.project.name, task.workstream.name) == ("Home", "Garden")
        assert (task.title, task.planned_for) == ("Mow the lawn short", tomorrow)

    # The controls show the task as it stands after a reload.
    notes = "- [ ] Mow the lawn short"
    saved_as(app_db, [{"kind": "text", "text": notes, "links": {"0": task_id}}])
    page.reload()
    assert props.locator(".prop[data-prop=planned_for] .prop-value").inner_text() == "tomorrow"
    assert flag.get_attribute("title") == "Project: Home › Garden"
    assert "pad-hue-1" in title.get_attribute("class")


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


def test_habits_are_not_written_in_the_notes(page, live, app_db) -> None:
    from app.models import HabitCheck

    page.goto(f"{live}/today")
    # "/" offers the notes' own commands: a habit is not one of them.
    write_in(page)
    page.keyboard.type("/")
    offered = page.locator(".cm-tooltip-autocomplete li")
    offered.first.wait_for()
    assert [t.split()[0] for t in offered.all_inner_texts()] == ["/reflection", "/stay"]
    page.keyboard.press("Escape")
    # Written anyway, "/habit" is words like any other, and ticks nothing.
    page.keyboard.type("habit stretch")
    saved_as(app_db, [{"kind": "text", "text": "/habit stretch"}])
    assert page.locator(".pad-editor .cm-line.pad-habit").count() == 0
    with app_db() as db:
        assert db.query(HabitCheck).count() == 0


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


def test_a_task_folds_to_its_title(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("- [ ] Call the dentist")
    page.keyboard.press("Enter")
    page.keyboard.type("- ask about the crown")
    page.keyboard.press("Enter")
    page.keyboard.type("- and the cleaning")
    page.keyboard.press("Control+Enter")
    page.keyboard.type("- [ ] Pick up the parcel")
    written = page.evaluate("Notepad.text()")

    # Right under another task, a task draws no rule of its own above it.
    titles = page.locator(".pad-editor .cm-line.pad-title")
    assert "pad-joined" in titles.nth(1).get_attribute("class")
    assert "pad-joined" not in titles.nth(0).get_attribute("class")

    # Its chevron folds it to its title, its rows counted; the notes are unchanged.
    titles.first.locator(".pad-fold").click()
    assert titles.first.locator(".pad-folded-rows").inner_text() == "2 rows"
    assert page.locator(".pad-editor .cm-line").count() == 2
    assert page.evaluate("Notepad.text()") == written
    from app.services import tasks as tasks_svc

    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)  # added by Ctrl+Enter
        task_id = task.id
    saved_as(app_db, [{"kind": "text", "text": written, "links": {"0": task_id}, "folded": [0]}])

    # Folded after a reload too. End on its title goes to the title's end
    # (its rows share its line): what is typed there is its title's.
    page.reload()
    assert titles.first.locator(".pad-folded-rows").inner_text() == "2 rows"
    write_in(page)
    page.keyboard.press("Control+Home")
    page.keyboard.press("End")
    page.keyboard.type(" soon")
    written = written.replace("dentist", "dentist soon")
    assert page.evaluate("Notepad.text()") == written
    assert titles.first.locator(".pad-folded-rows").count() == 1
    # An edit that would reach its rows unfolds it first.
    page.keyboard.press("Delete")
    assert titles.first.locator(".pad-folded-rows").count() == 0
    assert page.evaluate("Notepad.text()") == written
    assert titles.first.locator(".pad-fold").get_attribute("aria-expanded") == "true"

    # Folded again, Ctrl+Enter from its title goes on to a row after it, still folded.
    titles.first.locator(".pad-fold").click()
    page.keyboard.press("Control+Home")
    page.keyboard.press("Control+Enter")
    assert titles.first.locator(".pad-folded-rows").inner_text() == "2 rows"
    text = page.evaluate("Notepad.text()")
    task = "- [ ] Call the dentist soon\n\t- ask about the crown\n\t- and the cleaning\n"
    assert text.startswith(task + "\n")


def test_a_task_has_sub_tasks(page, live, app_db) -> None:
    from app.models import TaskStatus
    from app.services import tasks as tasks_svc

    page.goto(f"{live}/today")
    write_in(page)
    # "- [ ] " on a task's row makes it a sub-task; Enter goes on to the next,
    # and on an empty one back to a plain row.
    page.keyboard.type("- [ ] Pack")
    page.keyboard.press("Enter")
    page.keyboard.type("- [ ] passport")
    page.keyboard.press("Enter")
    page.keyboard.type("charger")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.keyboard.type("small bag")
    written = "- [ ] Pack\n\t- [ ] passport\n\t- [ ] charger\n\tsmall bag"
    assert page.evaluate("Notepad.text()") == written
    subs = page.locator(".pad-editor .cm-line.pad-sub")
    assert subs.count() == 2
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added: Pack").wait_for()
    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        task_id = task.id

    def notes() -> str:
        with app_db() as db:
            return tasks_svc.get_task(db, task_id).notes

    # Ticked, a sub-task is crossed out, and the task's description says so at once.
    subs.first.locator(".pad-check").click()
    assert "pad-struck" in subs.first.get_attribute("class")
    assert "pad-struck" not in subs.nth(1).get_attribute("class")
    end = time.monotonic() + 5
    while notes() != "- [x] passport\n- [ ] charger\nsmall bag":
        assert time.monotonic() < end, notes()
        time.sleep(0.1)

    # Ticked, the task is crossed out, title and rows.
    title = page.locator(".pad-editor .cm-line.pad-title")
    title.locator(".pad-check").first.click()
    rows = page.locator(".pad-editor .cm-line")
    for i in range(4):
        assert "pad-struck" in rows.nth(i).get_attribute("class")
    with app_db() as db:
        end = time.monotonic() + 5
        while tasks_svc.get_task(db, task_id).status != TaskStatus.done:
            assert time.monotonic() < end
            time.sleep(0.1)
            db.expire_all()


def test_tasks_due_today_are_offered_with_their_due(page, live, app_db) -> None:
    from datetime import timedelta

    from app.models import Task
    from app.services import tasks as tasks_svc

    with app_db() as db:
        report = tasks_svc.create_task(db, title="File the report", due=TODAY)
        later = tasks_svc.create_task(db, title="Next week's", due=TODAY + timedelta(days=7))
        db.commit()
        report_id, later_id = report.id, later.id

    page.goto(f"{live}/today")
    strip = page.locator("#pad-carry")
    assert strip.locator(".pad-carry-title").all_inner_texts() == ["File the report"]
    assert strip.locator(".pad-carry-due").all_inner_texts() == ["due today"]

    # Written here, it is done today, and leaves the strip.
    strip.locator(".pad-carry-write").click()
    assert text_of(page) == "- [ ] File the report"
    assert strip.is_hidden()
    end = time.monotonic() + 5
    while True:
        with app_db() as db:
            if db.get(Task, report_id).planned_for == TODAY:
                assert db.get(Task, later_id).planned_for is None
                break
        assert time.monotonic() < end
        time.sleep(0.1)


def test_tasks_still_open_yesterday_are_brought_to_today(page, live, app_db) -> None:
    from datetime import timedelta

    from app.models import Task, TaskStatus
    from app.services import tasks as tasks_svc

    yesterday = TODAY - timedelta(days=1)
    with app_db() as db:
        bank = tasks_svc.create_task(
            db, title="Call the bank", planned_for=yesterday,
            notes="- [ ] ask about fees\n- [x] find the card",
        )
        milk = tasks_svc.create_task(db, title="Buy milk", planned_for=yesterday)
        rent = tasks_svc.create_task(db, title="Pay rent")
        tasks_svc.set_status(db, milk.id, TaskStatus.done)
        written = [{
            "kind": "text", "text": "- [ ] Call the bank\n- [x] Buy milk\n- [ ] Pay rent",
            "links": {"0": bank.id, "1": milk.id, "2": rent.id},
        }]
        notebook_svc.save_page(db, yesterday, written, version=0)
        db.commit()
        ids = (bank.id, rent.id)

    def planned() -> tuple:
        with app_db() as db:
            return tuple(db.get(Task, i).planned_for for i in ids)

    page.goto(f"{live}/today")
    # In the plan, carried over: yesterday's open tasks, the done one left
    # behind, each saying since when.
    strip = page.locator("#pad-late")
    assert folded_to(strip) == ("Carried over", "2")
    assert page.locator("#pad-carry").is_hidden()
    assert strip.locator(".plan-since").all_inner_texts() == ["from yesterday", "from yesterday"]
    assert strip.locator(".pad-carry-write").all_inner_texts() == ["Call the bank", "Pay rent"]

    # A title writes its rows, its title row the same task, its do-date today.
    strip.locator(".pad-carry-write", has_text="Call the bank").click()
    bank_rows = "- [ ] Call the bank\n\t- [ ] ask about fees\n\t- [x] find the card"
    assert text_of(page) == bank_rows
    assert strip.locator(".pad-carry-write").all_inner_texts() == ["Pay rent"]
    assert page.locator(".pad-carry-all").is_hidden()  # one left: its title is enough
    saved_as(app_db, [{"kind": "text", "text": bank_rows, "links": {"0": ids[0]}}])
    end = time.monotonic() + 5
    while planned()[0] != TODAY:
        assert time.monotonic() < end, planned()
        time.sleep(0.1)
    title = page.locator(".pad-editor .cm-line.pad-title").first
    prop = title.locator(".prop[data-prop=planned_for] .prop-value")
    assert prop.inner_text() == "today"
    # Its sub-tasks are its own: ticked, as they stand.
    assert page.locator(".pad-editor .pad-check[aria-checked=true]").count() == 1

    # Undone, it is offered again; Bring all writes every one left.
    page.keyboard.press("Control+z")
    assert text_of(page) == ""
    assert strip.locator(".pad-carry-write").all_inner_texts() == ["Call the bank", "Pay rent"]
    page.locator(".pad-carry-all").click()
    assert text_of(page) == bank_rows + "\n- [ ] Pay rent"
    assert strip.is_hidden()
    saved_as(app_db, [{
        "kind": "text", "text": bank_rows + "\n- [ ] Pay rent", "links": {"0": ids[0], "3": ids[1]},
    }])
    end = time.monotonic() + 5
    while planned() != (TODAY, TODAY):
        assert time.monotonic() < end, planned()
        time.sleep(0.1)

    # Ticked here, it is done; yesterday's page keeps what was written there.
    title.locator(".pad-check").first.click()
    end = time.monotonic() + 5
    while True:
        with app_db() as db:
            if db.get(Task, ids[0]).status == TaskStatus.done:
                assert notebook_svc.get_page(db, yesterday).blocks == written
                break
        assert time.monotonic() < end
        time.sleep(0.1)
    page.reload()
    assert strip.is_hidden()
    # Only today's page offers them.
    page.goto(f"{live}/day/{TODAY + timedelta(days=1)}")
    assert strip.is_hidden()


def test_the_plan_ticks_and_moves_its_tasks(page, live, app_db) -> None:
    from datetime import timedelta

    from app.models import Task, TaskStatus
    from app.services import habits as habits_svc
    from app.services import tasks as tasks_svc

    yesterday = TODAY - timedelta(days=1)
    with app_db() as db:
        report = tasks_svc.create_task(db, title="File the report", due=TODAY)
        bank = tasks_svc.create_task(db, title="Call the bank", planned_for=yesterday)
        rent = tasks_svc.create_task(db, title="Pay rent", planned_for=TODAY - timedelta(days=3))
        habits_svc.set_days(db, "stretch", "")
        db.commit()
        ids = {"report": report.id, "bank": bank.id, "rent": rent.id}

    def task(name: str) -> tuple:
        with app_db() as db:
            t = db.get(Task, ids[name])
            return t.status, t.planned_for

    def until(check, timeout: float = 5) -> None:  # noqa: ANN001
        end = time.monotonic() + timeout
        while not check():
            assert time.monotonic() < end
            time.sleep(0.1)

    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    today, late = page.locator("#pad-carry"), page.locator("#pad-late")

    def carried() -> list[str]:
        return sorted(late.locator(".pad-carry-title").all_inner_texts())

    # For today, what is meant for it; carried over, what was meant before.
    assert today.locator(".pad-carry-title").all_inner_texts() == ["File the report"]
    assert carried() == ["Call the bank", "Pay rent"]
    assert page.locator(".plan-empty").is_hidden()

    # Its box: written in the notes, ticked, and the task done.
    today.locator(".plan-tick").click()
    assert text_of(page) == "- [x] File the report"
    until(lambda: task("report")[0] == TaskStatus.done)
    assert today.is_hidden()

    # Its calendar moves it to another day: off the plan, Undo puts it back.
    row = late.locator(".plan-item", has_text="Call the bank")
    row.hover()
    row.locator(".plan-move").click()
    page.locator(".plan-move-menu [role=menuitemradio]", has_text="Tomorrow").click()
    until(lambda: task("bank")[1] == TODAY + timedelta(days=1))
    # The plan redrawn once the move is answered, a moment after it is saved.
    until(lambda: carried() == ["Pay rent"])
    toast = page.locator(".cal-toast.show", has_text="Moved “Call the bank” to tomorrow.")
    toast.locator(".toast-action").click()
    until(lambda: task("bank")[1] == yesterday)
    until(lambda: carried() == ["Call the bank", "Pay rent"])

    # Reschedule moves every one carried over, from the keyboard too.
    late.locator(".plan-move-all").focus()
    page.keyboard.press("Enter")
    page.locator(".plan-move-menu").wait_for()
    page.keyboard.press("End")
    page.keyboard.press("Enter")  # No date
    until(lambda: task("bank")[1] is None and task("rent")[1] is None)
    late.wait_for(state="hidden")
    assert page.locator(".plan-empty").is_visible()

    # A habit's box in its pane ticks it, and writes nothing in the notes.
    with app_db() as db:
        stretch_id = habits_svc.find(db, "stretch").id
    stretch = page.locator(f"#pad-habits .habit-row[data-habit='{stretch_id}']")
    stretch.locator(".habit-box").click()
    until(lambda: "done" in stretch.get_attribute("class").split())
    assert text_of(page) == "- [x] File the report"
    assert not page.evaluate("Notepad.view.hasFocus")


def test_tab_stays_in_the_notes_a_step_into_or_out_of_a_task(page, live) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    in_notes = "document.activeElement.classList.contains('cm-content')"

    # From a task's title, Tab goes under it; the notes keep the keyboard.
    page.keyboard.type("- [ ] Buy milk")
    page.keyboard.press("Tab")
    assert text_of(page) == "- [ ] Buy milk\n\t"
    assert page.evaluate(in_notes)
    page.keyboard.type("two litres")
    # On its row, Tab makes a sub-task; Shift+Tab steps back out, a step at a time.
    page.keyboard.press("Tab")
    assert text_of(page) == "- [ ] Buy milk\n\t- [ ] two litres"
    page.keyboard.press("Shift+Tab")
    assert text_of(page) == "- [ ] Buy milk\n\ttwo litres"
    page.keyboard.press("Shift+Tab")
    assert text_of(page) == "- [ ] Buy milk\ntwo litres"
    # A plain row right under a task joins it.
    page.keyboard.press("Tab")
    assert text_of(page) == "- [ ] Buy milk\n\ttwo litres"
    # Where there is nothing to step into (a blank row between), Tab still
    # keeps to the notes. Enter on the task's empty row steps out of it.
    page.keyboard.press("Control+End")
    for _ in range(3):
        page.keyboard.press("Enter")
    page.keyboard.type("Slow morning.")
    page.keyboard.press("Tab")
    assert text_of(page).endswith("\n\nSlow morning.")
    assert page.evaluate(in_notes)
    # Esc saves a task; Esc again, with nothing left to save, leaves the notes.
    page.keyboard.press("Control+Home")
    page.keyboard.press("Escape")
    page.locator(".cal-toast.show", has_text="Task added: Buy milk").wait_for()
    assert page.evaluate(in_notes)
    page.keyboard.press("Escape")
    assert not page.evaluate(in_notes)


def test_a_task_title_takes_its_fields_from_words(page, live, app_db) -> None:
    from datetime import timedelta

    from app.services import tasks as tasks_svc

    page.goto(f"{live}/today")
    write_in(page)
    title = page.locator(".pad-editor .cm-line.pad-title").first
    value = lambda name: title.locator(f".prop[data-prop={name}] .prop-value").inner_text()  # noqa: E731

    # As in the task sheet: the words and a space set the field and leave the title.
    page.keyboard.type("- [ ] Call the bank tomorrow ")
    assert text_of(page) == "- [ ] Call the bank "
    assert value("planned_for") == "tomorrow"
    # Backspace straight after puts them back, and they stay words.
    page.keyboard.press("Backspace")
    assert text_of(page) == "- [ ] Call the bank tomorrow"
    assert value("planned_for") == "today"
    # A task takes no time on the calendar: a time stays words.
    page.keyboard.type(" at 3pm ")
    assert text_of(page) == "- [ ] Call the bank tomorrow at 3pm "
    assert title.locator(".prop[data-prop=time]").count() == 0
    # A title's last words are taken as it is closed.
    page.keyboard.type("due friday")
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added: Call the bank tomorrow at 3pm").wait_for()
    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        weekday = (4 - TODAY.weekday() - 1) % 7 + 1
        assert (task.title, task.planned_for) == ("Call the bank tomorrow at 3pm", TODAY)
        assert task.due == TODAY + timedelta(days=weekday)


def test_a_title_s_words_made_a_field_come_back_with_undo(page, live, app_db) -> None:
    from app.services import tasks as tasks_svc

    page.goto(f"{live}/today")
    write_in(page)
    title = page.locator(".pad-editor .cm-line.pad-title").first
    value = lambda name: title.locator(f".prop[data-prop={name}] .prop-value").inner_text()  # noqa: E731

    # Ctrl+Z puts back the words and the field together, even after more
    # writing; Ctrl+Y makes the field again.
    page.keyboard.type("- [ ] Book flights for friday ")
    assert value("planned_for") != "today"
    page.keyboard.type("soon")
    page.keyboard.press("Control+z")
    assert text_of(page) == "- [ ] Book flights for "
    page.keyboard.press("Control+z")
    assert text_of(page) == "- [ ] Book flights for friday"
    assert value("planned_for") == "today"
    page.keyboard.press("Control+y")
    assert text_of(page) == "- [ ] Book flights for "
    assert value("planned_for") != "today"
    page.keyboard.press("Control+z")

    # Closing takes a title's last words; the toast says what they became,
    # and its Undo puts them back, written to the task.
    page.keyboard.press("End")
    page.keyboard.type(" due tomorrow")
    page.keyboard.press("Control+Enter")
    added = "Task added: Book flights for friday, due tomorrow"
    toast = page.locator(".cal-toast.show", has_text=added)
    toast.wait_for()
    toast.locator(".toast-action", has_text="Undo").click()
    assert text_of(page).startswith("- [ ] Book flights for friday due tomorrow\n")
    assert value("due") == ""
    end = time.monotonic() + 5
    while True:
        with app_db() as db:
            [task] = tasks_svc.list_tasks(db)
            if (task.title, task.due) == ("Book flights for friday due tomorrow", None):
                break
        assert time.monotonic() < end, (task.title, task.due)
        time.sleep(0.1)


def test_spelling_is_marked_only_in_the_row_being_written(page, live) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("Speling mistaek")
    page.keyboard.press("Enter")
    page.keyboard.type("Anothr wrng line")
    # The page follows the caret and focus a moment after they move.
    def marked(expected: list) -> None:
        page.wait_for_function(
            """expected => JSON.stringify(
                [...document.querySelectorAll('.pad-editor .cm-line')].slice(0, 2)
                    .map(e => e.getAttribute('spellcheck'))) === JSON.stringify(expected)""",
            arg=expected, timeout=3000,
        )

    marked(["false", "true"])
    page.keyboard.press("ArrowUp")
    marked(["true", "false"])
    # Out of the notes, no row is.
    page.keyboard.press("Escape")
    marked(["false", "false"])


PASTE = """text => {
  const dt = new DataTransfer();
  dt.setData('text/plain', text);
  document.querySelector('.pad-editor .cm-content').dispatchEvent(
    new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
}"""


def test_lines_pasted_inside_a_task_stay_inside_it(page, live) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("- [ ] Plan the trip")
    page.keyboard.press("Enter")
    page.keyboard.type("book flights")
    page.keyboard.press("Enter")
    page.keyboard.type("pack")

    # Into one of its rows: every line pasted is a row of it, a "- [ ] "
    # line a sub-task, and the rows after it stay its own.
    page.keyboard.press("ArrowUp")
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.evaluate(PASTE, "call the hotel\r\nrent a car\n- [ ] check visas")
    trip = "\n".join([
        "- [ ] Plan the trip", "\tbook flights", "\tcall the hotel", "\trent a car",
        "\t- [ ] check visas", "\tpack",
    ])
    assert text_of(page) == trip
    assert page.locator(".pad-editor .cm-line.pad-title").count() == 1

    # At its title: the first line joins it, the rest go under it; rows
    # copied from the notes keep their one tab.
    page.keyboard.press("Control+Home")
    page.keyboard.press("End")
    page.evaluate(PASTE, " to Lisbon\n\tsort insurance")
    lisbon = "- [ ] Plan the trip to Lisbon\n\tsort insurance\n\tbook flights"
    assert text_of(page).startswith(lisbon)
    # One paste is one undo.
    page.keyboard.press("Control+z")
    assert text_of(page) == trip

    # Outside any task (Enter twice steps out of it), a paste is just text.
    page.keyboard.press("Control+End")
    for _ in range(2):
        page.keyboard.press("Enter")
    page.evaluate(PASTE, "Slow morning.\nCoffee first.")
    assert text_of(page) == trip + "\nSlow morning.\nCoffee first."


def test_a_row_deleted_from_inside_a_task_leaves_the_rest_inside(page, live) -> None:
    packing = "- [ ] Pack\n\t- [ ] socks\n\t- [ ] shirts\n\t- [ ] shoes"

    def written() -> None:
        page.evaluate(
            """t => Notepad.view.dispatch(
              { changes: { from: 0, to: Notepad.view.state.doc.length, insert: t } })""",
            packing,
        )

    page.goto(f"{live}/today")
    write_in(page)
    written()

    # Backspace through a sub-task: once its box and tab are gone the row
    # goes whole, and the caret is at the end of the row above.
    page.locator(".pad-editor .cm-line", has_text="shirts").click()
    page.keyboard.press("End")
    for _ in range(8):
        page.keyboard.press("Backspace")
    assert text_of(page) == "- [ ] Pack\n\t- [ ] socks\n\t- [ ] shoes"
    assert page.locator(".pad-editor .cm-line.pad-title").count() == 1
    page.keyboard.type("!")
    assert text_of(page) == "- [ ] Pack\n\t- [ ] socks!\n\t- [ ] shoes"

    # Selected whole, box and tab too (as a drag from its left edge does), and deleted.
    written()
    page.evaluate("""() => { const v = Notepad.view, line = v.state.doc.line(3);
      v.dispatch({ selection: { anchor: line.from, head: line.to } }); v.focus(); }""")
    page.keyboard.press("Delete")
    assert text_of(page) == "- [ ] Pack\n\t- [ ] socks\n\t- [ ] shoes"
    assert page.locator(".pad-editor .cm-line.pad-title").count() == 1


def test_compact_rows_and_folded_panes_are_kept(page, live) -> None:
    def row_height() -> float:
        first = page.locator(".pad-editor .cm-line").first
        return first.evaluate("e => e.getBoundingClientRect().height")

    # Wide enough for the plan, the notes and the timeline side by side.
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    assert row_height() == 36
    # C, outside the text: compact rows, remembered; the text keeps its size.
    page.keyboard.press("c")
    assert row_height() == 28
    assert page.locator(".density-toggle").get_attribute("aria-pressed") == "true"
    # Ctrl+\, even writing in the notes: the timeline folds away, the notes taking its room.
    write_in(page)
    width = page.locator(".notepad-card").evaluate("e => e.getBoundingClientRect().width")
    page.keyboard.press("Control+\\")
    assert page.locator(".today-timeline").is_hidden()
    assert page.locator(".notepad-card").evaluate("e => e.getBoundingClientRect().width") > width
    assert text_of(page) == ""
    # In the notes, C is a letter.
    page.keyboard.type("c")
    assert text_of(page) == "c"
    assert row_height() == 28
    # Alt+P, in the notes too: the plan and the habits fold away as well.
    width = page.locator(".notepad-card").evaluate("e => e.getBoundingClientRect().width")
    page.keyboard.press("Alt+p")
    assert page.locator(".today-side").is_hidden()
    assert page.locator(".notepad-card").evaluate("e => e.getBoundingClientRect().width") > width
    assert page.locator(".plan-toggle").get_attribute("aria-pressed") == "true"
    assert text_of(page) == "c"

    page.reload()
    assert row_height() == 28
    assert page.locator(".today-timeline").is_hidden()
    assert page.locator(".today-side").is_hidden()
    page.locator(".timeline-toggle").click()
    page.locator(".plan-toggle").click()
    page.locator(".density-toggle").click()
    assert page.locator(".today-timeline").is_visible()
    assert page.locator(".today-side").is_visible()
    assert row_height() == 36


def test_the_density_and_mode_toggles_each_switch_only_their_own(page, live) -> None:
    def dark() -> bool:
        return page.evaluate("document.documentElement.dataset.theme === 'dark'")

    page.goto(f"{live}/today")
    mode = page.locator(".theme-toggle")
    was_dark = dark()
    page.locator(".density-toggle").click()
    assert page.evaluate("document.documentElement.dataset.density") == "compact"
    assert dark() == was_dark
    mode.click()
    assert dark() != was_dark
    assert mode.get_attribute("aria-pressed") == str(not was_dark).lower()
    assert page.locator(".density-toggle").get_attribute("aria-pressed") == "true"


def test_a_task_added_as_the_page_is_left_is_added_once(page, live, app_db) -> None:
    """A task row still being written when the page is left is added by the
    notes' own save, linked to its row: coming back and writing in it again,
    then leaving again, writes to that task and adds no second one."""
    from app.services import tasks as tasks_svc

    def tasks() -> list:
        with app_db() as db:
            return [(t.id, t.title, t.notes) for t in tasks_svc.list_tasks(db)]

    def settled(check) -> None:  # noqa: ANN001
        end = time.monotonic() + 5
        while not check() and time.monotonic() < end:
            time.sleep(0.1)
        assert check()

    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("- [ ] Note app")
    page.keyboard.press("Enter")
    page.keyboard.type("- Improve")
    page.goto(f"{live}/projects")  # left with the task row still open

    settled(lambda: [(title, notes) for _, title, notes in tasks()] == [("Note app", "- Improve")])
    [(task_id, _, _)] = tasks()
    settled(lambda: stored(app_db) == [
        {"kind": "text", "text": "- [ ] Note app\n\t- Improve", "links": {"0": task_id}},
    ])

    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.press("Control+End")
    page.keyboard.type(" tasks screen")
    page.goto(f"{live}/projects")
    settled(lambda: tasks() == [(task_id, "Note app", "- Improve tasks screen")])
    time.sleep(0.5)
    assert tasks() == [(task_id, "Note app", "- Improve tasks screen")]


def test_on_a_phone_the_timeline_scrolls_in_its_own_window_opened_on_now(page, live) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live}/today")
    grid = page.locator(".today-timeline .calendar-grid")
    box = grid.bounding_box()
    # A window on the day, under the notes, not all 24 hours laid out.
    assert box["height"] <= 0.75 * 844 + 1
    scroll = grid.evaluate("g => ({top: g.scrollTop, height: g.clientHeight})")
    now = page.locator(".today-timeline .now-line")
    # Opened on the usual day, now in view (around midnight the grid has no
    # now-line, and opens on the usual day's start).
    if now.count():
        now_at = now.evaluate("n => n.offsetTop")
        assert scroll["top"] <= now_at <= scroll["top"] + scroll["height"]
    else:
        assert scroll["top"] > 0


def test_a_task_row_left_while_a_save_is_on_its_way_is_added(
    page, live, app_db, monkeypatch
) -> None:
    """The page left while its last save is still on its way: the leaving
    save, which adds the task rows written since, follows it, and is not
    turned away as a stale copy of the page."""
    from app.services import tasks as tasks_svc

    real_save = notebook_svc.save_page
    slow = [True]

    def save_page(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if slow.pop() if slow else False:
            time.sleep(1)  # the first save is slow to land
        return real_save(*args, **kwargs)

    monkeypatch.setattr(notebook_svc, "save_page", save_page)
    page.goto(f"{live}/today")
    write_in(page)
    with page.expect_request(lambda r: r.method == "POST" and "/ui/notebook/" in r.url):
        page.keyboard.type("Groceries")
    page.keyboard.press("Enter")
    page.keyboard.type("- [ ] Call the bank")
    page.goto(f"{live}/projects")  # left with the first save still on its way

    end = time.monotonic() + 5
    while time.monotonic() < end and not any("links" in b for b in stored(app_db)):
        time.sleep(0.1)
    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
    assert task.title == "Call the bank"
    assert stored(app_db) == [
        {"kind": "text", "text": "Groceries\n- [ ] Call the bank", "links": {"1": task.id}},
    ]


def rows(page) -> list[str]:
    """The notes' rows as they read on screen."""
    return page.locator(".pad-editor .cm-line").all_inner_texts()


def test_the_notes_are_markdown_drawn_as_they_read(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("# Plan")
    page.keyboard.press("Enter")
    page.keyboard.type("Book **flights** and the `JR` pass")
    page.keyboard.press("Enter")
    page.keyboard.type("- [ ] Pack the **adapter**")
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added").wait_for()
    notes = "# Plan\nBook **flights** and the `JR` pass\n- [ ] Pack the **adapter**\n"
    assert text_of(page) == notes

    # Out of the notes, everything reads as finished, its marks hidden.
    page.keyboard.press("Escape")
    lines = page.locator(".pad-editor .cm-line")
    assert lines.nth(0).inner_text() == "Plan"
    assert "cm-md-h1" in lines.nth(0).get_attribute("class")
    assert lines.nth(1).inner_text() == "Book flights and the JR pass"
    assert lines.nth(1).locator(".cm-md-strong").inner_text() == "flights"
    assert lines.nth(1).locator(".cm-md-code").inner_text() == "JR"
    # A task's row is the notepad's: its box and Task, no box of Markdown's
    # beside its own, and its title the plain words it is everywhere else.
    title = page.locator(".pad-editor .cm-line.pad-title")
    assert title.locator(".pad-kind-name").inner_text() == "Task"
    assert "Pack the **adapter**" in title.inner_text()
    assert title.locator(".cm-md-strong").count() == 0
    assert page.locator(".pad-editor .cm-md-box").count() == 0
    # The caret on a mark's words shows its marks; the text is saved as written.
    lines.nth(1).locator(".cm-md-strong").click()
    assert "**flights**" in lines.nth(1).inner_text()
    links = {"2": stored_task_id(app_db)}
    saved_as(app_db, [{"kind": "text", "text": notes.rstrip("\n"), "links": links}])


def stored_task_id(app_db) -> int:
    from app.services import tasks as tasks_svc

    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        return task.id


def test_a_markdown_list_goes_on_and_a_plain_row_stays_plain(page, live) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    # A list goes on with Enter, nests with Tab, and steps out on an empty item.
    page.keyboard.type("- milk")
    page.keyboard.press("Enter")
    page.keyboard.type("oat")
    page.keyboard.press("Tab")
    assert text_of(page) == "- milk\n  - oat"
    assert page.locator(".pad-editor .cm-md-bullet").count() == 2
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    assert text_of(page) == "- milk\n  - oat\n"

    # A plain row right under a task's title is the notes' own: Enter on it
    # starts a plain row, never a task as Markdown would have it.
    page.keyboard.type("- [ ] Call mum")
    page.keyboard.press("Control+Enter")
    page.keyboard.type("then lunch")
    page.keyboard.press("Enter")
    page.keyboard.type("and a walk")
    assert text_of(page) == "- milk\n  - oat\n- [ ] Call mum\nthen lunch\nand a walk"
    assert page.locator(".pad-editor .cm-line.pad-title").count() == 1


def test_the_notes_modes_are_switched_and_remembered(page, live) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("## Errands")
    page.keyboard.press("Enter")
    page.keyboard.type("- [ ] Post the letter")
    page.keyboard.press("Tab")
    page.keyboard.type("the **blue** envelope")
    page.keyboard.press("Control+Enter")
    modes = page.locator(".today-page [data-md-modes]")
    content = page.locator(".pad-editor .cm-content")
    assert modes.locator('[aria-pressed="true"]').inner_text() == "Live"

    # Source: the Markdown as written; the task stays the notepad's row.
    modes.locator("button", has_text="Source").click()
    assert rows(page)[0] == "## Errands"
    assert "**blue**" in rows(page)[2]
    assert page.locator(".pad-editor .cm-line.pad-title .pad-kind-name").inner_text() == "Task"

    # Reading (Ctrl+E): drawn, not to be written; and so it opens again.
    page.keyboard.press("Control+e")
    assert modes.locator('[aria-pressed="true"]').inner_text() == "Reading"
    assert content.get_attribute("contenteditable") == "false"
    assert rows(page)[0] == "Errands"
    # A task's description is Markdown, as on its page: drawn too.
    assert "blue envelope" in rows(page)[2] and "**" not in rows(page)[2]
    page.reload()
    assert modes.locator('[aria-pressed="true"]').inner_text() == "Reading"
    page.keyboard.press("Control+e")
    assert modes.locator('[aria-pressed="true"]').inner_text() == "Live"


def test_a_task_in_the_notes_opens_on_its_page(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("- [ ] Renew the passport")
    # Not added yet: no page to open, so no Open.
    title = page.locator(".pad-editor .cm-line.pad-title")
    assert title.locator("[data-open-task]").is_hidden()
    # Ctrl+Shift+Enter adds it, and opens its page.
    page.keyboard.press("Control+Shift+Enter")
    page.wait_for_url(f"{live}/tasks/*")
    task_id = stored_task_id(app_db)
    assert page.url.endswith(f"/tasks/{task_id}")
    page.locator(".page-back", has_text="Today").click()
    page.wait_for_url(f"{live}/today")

    # Added, its row has Open after its icons.
    written = "- [ ] Renew the passport"
    saved_as(app_db, [{"kind": "text", "text": written, "links": {"0": task_id}}])
    page.reload()
    title.locator("[data-open-task]").click()
    page.wait_for_url(f"{live}/tasks/{task_id}")


def test_nudges_and_strips_fold_and_stay_folded(page, live, app_db) -> None:
    from datetime import datetime, timedelta

    from app.dates import short_date
    from app.services import nudges as nudges_svc
    from app.services import tasks as tasks_svc

    with app_db() as db:
        tasks_svc.create_task(db, title="File the report", due=TODAY)
        tasks_svc.create_task(db, title="Pay rent", planned_for=TODAY)
        tasks_svc.create_task(db, title="Book the flights", due=TODAY + timedelta(days=2))
        nudges_svc.evaluate(db, datetime.now())
        db.commit()

    page.goto(f"{live}/today")
    nudges = page.locator("#nudge-center")
    carry = page.locator("#pad-carry")
    # Each task in one place: the report, offered under the notes with its
    # due, is not nudged at the top as well.
    assert nudges.locator(".nudge-text").all_inner_texts() == [
        f"“Book the flights” is due {short_date(TODAY + timedelta(days=2), TODAY)}."
    ]
    assert folded_to(nudges) == ("Nudges", "1")
    assert folded_to(carry) == ("For today", "2")

    # Folded to its name and count, and so the next time the page opens.
    nudges.locator(".today-fold-summary").click()
    carry.locator(".today-fold-summary").click()
    assert nudges.locator(".nudge").is_hidden()
    assert carry.locator(".pad-carry-write").first.is_hidden()
    assert carry.locator(".pad-carry-all").is_hidden()
    page.wait_for_function("document.cookie.includes('today_folded=nudges.carry')")
    page.reload()
    assert nudges.get_attribute("open") is None
    assert carry.get_attribute("open") is None
    assert folded_to(carry) == ("For today", "2")
    # The key still brings them all.
    page.keyboard.press("Alt+c")
    assert text_of(page) == "- [ ] File the report\n- [ ] Pay rent"
    assert carry.is_hidden()

    # Open again, it stays open; its last nudge dismissed, the center goes.
    nudges.locator(".today-fold-summary").click()
    page.wait_for_function("!document.cookie.includes('nudges')")
    page.reload()
    assert nudges.get_attribute("open") == ""
    nudges.locator(".nudge-dismiss").click()
    nudges.wait_for(state="detached")


def test_a_task_saved_from_the_notes_keeps_what_was_changed_elsewhere(page, live, app_db) -> None:
    from datetime import timedelta

    from app.models import TaskStatus
    from app.services import tasks as tasks_svc

    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("- [ ] Ship the release")
    page.keyboard.press("Enter")
    page.keyboard.type("- tag it")
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Task added: Ship the release").wait_for()
    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        task_id = task.id
        # While Today is open, Claude starts it and gives it a due.
        tasks_svc.update_task(
            db, task_id, status=TaskStatus.in_progress, due=TODAY + timedelta(days=2)
        )
        db.commit()

    page.keyboard.press("ArrowUp")
    page.keyboard.press("End")
    page.keyboard.type(" v2")
    page.keyboard.press("Escape")
    page.locator(".cal-toast.show", has_text="Task saved: Ship the release").wait_for()
    with app_db() as db:
        task = tasks_svc.get_task(db, task_id)
        assert task.notes == "- tag it v2"
        assert task.status == TaskStatus.in_progress
        assert task.due == TODAY + timedelta(days=2)


def test_rows_moved_up_or_down_keep_their_tasks(page, live, app_db) -> None:
    """Alt+Up and Alt+Down move the caret's row over the next: a task row,
    the one moved or the one moved over, stays its task, and none is added."""
    from app.services import tasks as tasks_svc

    def tasks() -> list:
        with app_db() as db:
            return sorted((t.title, t.id) for t in tasks_svc.list_tasks(db))

    page.goto(f"{live}/today")
    write_in(page)
    page.keyboard.type("Morning.")
    page.keyboard.press("Enter")
    for title in ("One", "Two"):
        page.keyboard.type(f"- [ ] {title}")
        page.keyboard.press("Control+Enter")
        page.locator(".cal-toast.show", has_text=f"Task added: {title}").wait_for()
    page.keyboard.type("After.")
    [(_, one), (_, two)] = tasks()

    page.keyboard.press("ArrowUp")  # on Two
    page.keyboard.press("Alt+ArrowUp")
    assert text_of(page) == "Morning.\n- [ ] Two\n- [ ] One\nAfter."
    page.keyboard.press("Control+Home")  # on Morning.
    page.keyboard.press("Alt+ArrowDown")
    assert text_of(page) == "- [ ] Two\nMorning.\n- [ ] One\nAfter."
    # Undone a move at a time, and done again, the same.
    page.keyboard.press("Control+z")
    assert text_of(page) == "Morning.\n- [ ] Two\n- [ ] One\nAfter."
    page.keyboard.press("Control+z")
    assert text_of(page) == "Morning.\n- [ ] One\n- [ ] Two\nAfter."
    page.keyboard.press("Control+y")
    page.keyboard.press("Control+y")
    assert text_of(page) == "- [ ] Two\nMorning.\n- [ ] One\nAfter."

    page.goto(f"{live}/projects")  # leaving adds any task row not yet added
    saved_as(app_db, [{"kind": "text", "text": "- [ ] Two\nMorning.\n- [ ] One\nAfter.",
                      "links": {"0": two, "2": one}}])
    time.sleep(0.5)
    assert tasks() == [("One", one), ("Two", two)]
