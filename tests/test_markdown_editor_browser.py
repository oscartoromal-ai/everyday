"""A task's description in a real browser: Markdown written in its editor
(notes-editor.js on markdown-live.js) and shown as it reads, its marks
showing only where the caret is, its "- " lines boxes that tick, and the
text saved exactly as written. The `live`, `page` and `app_db` fixtures are
conftest.py's."""

from datetime import date

import pytest

from app.models import Task
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

NOTES = (
    "# Plan\n"
    "Book the **flights**, then the *rail pass*: [JR](https://japanrailpass.net).\n"
    "- compare `JR Pass` prices\n"
    "- [x] renew the passport\n"
    "> ask Ana\n"
    "Notes say [TBD] and \\*stars\\*."
)


def open_task(page, live, app_db, notes: str = "") -> int:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Japan", planned_for=date.today(), notes=notes)
        db.commit()
        task_id = task.id
    page.goto(f"{live}/tasks/{task_id}")
    page.locator(".main [data-notes-editor] .cm-content").wait_for()
    return task_id


def shown(page) -> str:
    """The description's words as they read on screen."""
    return page.locator(".main [data-notes-editor] .cm-content").inner_text()


def field(page) -> str:
    return page.locator(".main textarea[name=notes]").input_value()


def saved(page, app_db, task_id: int) -> str:
    page.locator("[data-page-state]", has_text="Saved").wait_for()
    with app_db() as db:
        return db.get(Task, task_id).notes


def test_markdown_reads_as_it_will_its_marks_where_the_caret_is(page, live, app_db) -> None:
    open_task(page, live, app_db, NOTES)
    page.locator(".page-back").focus()  # the editor unfocused: all of it reads as finished
    text = shown(page)
    assert "**" not in text and "# " not in text and "](" not in text and "> " not in text
    assert "Book the flights, then the rail pass: JR." in text
    # A box for each sub-task, ticked as its line says.
    boxes = page.locator(".cm-md-box")
    assert boxes.evaluate_all("els => els.map(e => e.ariaChecked)") == ["false", "true"]
    # What is not a link stays as written; an escape shows its star alone.
    assert "Notes say [TBD] and *stars*." in text
    assert page.locator(".cm-md-h1", has_text="Plan").count() == 1
    assert page.locator(".cm-md-strong", has_text="flights").count() == 1
    assert page.locator(".cm-md-link[data-href='https://japanrailpass.net']").count() == 1

    # The caret in the bold words: their marks show, and only theirs.
    page.locator(".cm-md-strong", has_text="flights").click()
    text = shown(page)
    assert "**flights**" in text and "*rail pass*" not in text and "](" not in text
    # On the heading's line: its "# ".
    page.locator(".cm-md-h1").click()
    assert "# Plan" in shown(page)
    # Showing them changed nothing: the field holds the text as written.
    assert field(page) == NOTES


def test_sub_tasks_are_written_with_dash_and_enter(page, live, app_db) -> None:
    task_id = open_task(page, live, app_db)
    page.keyboard.type("Pack")
    page.keyboard.press("Enter")
    page.keyboard.type("- adapters")
    assert page.locator(".cm-md-box").count() == 1
    # Enter goes on to the next sub-task; Shift+Enter writes a note under it.
    page.keyboard.press("Enter")
    page.keyboard.type("rail pass")
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("from the JR office")
    # Enter on a note goes on to its sub-task's next.
    page.keyboard.press("Enter")
    page.keyboard.type("yen")
    # Tab nests it under the one above.
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    # Enter on an empty sub-task steps out a level, then out of the list.
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.keyboard.type("Done by Friday.")
    expected = "Pack\n- adapters\n- rail pass\n  from the JR office\n  - yen\nDone by Friday."
    assert field(page) == expected
    assert saved(page, app_db, task_id) == expected


def test_the_caret_never_stands_inside_a_box(page, live, app_db) -> None:
    task_id = open_task(page, live, app_db, "- adapters")
    page.locator(".cm-line", has_text="adapters").click()
    page.keyboard.press("Home")
    page.keyboard.type("two ")
    assert field(page) == "- two adapters"
    # Backspace at its first word takes the box away, the words staying.
    page.keyboard.press("Home")
    page.keyboard.press("Backspace")
    assert field(page) == "two adapters"
    assert page.locator(".cm-md-box").count() == 0
    assert saved(page, app_db, task_id) == "two adapters"


def test_a_box_ticks_its_sub_task_as_the_server_writes_it(page, live, app_db) -> None:
    task_id = open_task(page, live, app_db, "Before\n- [ ] adapters\n- yen")
    page.locator(".cm-md-box").first.click()
    assert field(page) == "Before\n- [x] adapters\n- yen"
    assert page.locator(".cm-md-done", has_text="adapters").count() == 1
    assert saved(page, app_db, task_id) == "Before\n- [x] adapters\n- yen"
    # Unticked, it is written as an open one ("- "), as a row's box writes it.
    page.locator(".cm-md-box").first.click()
    assert field(page) == "Before\n- adapters\n- yen"
    # Ctrl+L ticks the caret's.
    page.locator(".cm-line", has_text="yen").click()
    page.keyboard.press("Control+l")
    assert field(page) == "Before\n- adapters\n- [x] yen"
    # Undo takes a tick back.
    page.keyboard.press("Control+z")
    assert field(page) == "Before\n- adapters\n- yen"


def test_ctrl_b_and_a_pasted_address_write_markdown(page, live, app_db) -> None:
    open_task(page, live, app_db, "the rail pass")
    page.locator(".cm-line", has_text="rail pass").click()
    page.keyboard.press("End")
    page.keyboard.press("Shift+Control+ArrowLeft")
    page.keyboard.press("Control+b")
    assert field(page) == "the rail **pass**"
    page.keyboard.press("Control+b")
    assert field(page) == "the rail pass"
    # An address pasted over words makes them its link.
    page.keyboard.press("Home")
    page.keyboard.press("Shift+End")
    page.evaluate(
        """() => {
            const data = new DataTransfer();
            data.setData("text/plain", "https://japanrailpass.net");
            document.querySelector("[data-notes-editor] .cm-content")
                .dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true }));
        }"""
    )
    assert field(page) == "[the rail pass](https://japanrailpass.net)"


def test_ctrl_enter_in_the_description_adds_the_task(page, live, app_db) -> None:
    page.goto(f"{live}/projects")
    sheet = page.locator(".main .task-sheet[data-sheet=compose]").first
    sheet.locator(".sheet-line").click()
    page.keyboard.type("Pack")
    page.keyboard.press("Enter")
    page.keyboard.type("- **adapters**")
    page.keyboard.press("Control+Enter")
    page.locator(".task-row", has_text="Pack").wait_for()
    with app_db() as db:
        task = next(t for t in tasks_svc.list_tasks(db) if t.title == "Pack")
        # No blank line from Ctrl+Enter: it belongs to the sheet.
        assert task.notes == "- **adapters**"
    # The composer is empty again, its editor too.
    page.wait_for_function(
        """() => window.NotesEditor.viewOf(document.querySelector(
            '.task-sheet[data-sheet=compose] [data-notes-editor]')).state.doc.length === 0"""
    )
    assert sheet.locator(".cm-placeholder").count() == 1
    # The row reads it as Markdown.
    row = page.locator(".task-row", has_text="Pack")
    row.locator(".notes-toggle").click()
    assert row.locator(".subtask strong", has_text="adapters").count() == 1
