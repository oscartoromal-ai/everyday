"""A task's description in a real browser: Markdown written in its editor
(notes-editor.js on markdown-live.js) and shown as it reads, its marks
showing only where the caret is, its "- [ ] " lines boxes that tick (its
"- " lines bullets), and the
text saved exactly as written. The `live`, `page` and `app_db` fixtures are
conftest.py's."""

import re
from datetime import date

import pytest

from app.models import Task
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

# "Saved" alone, not "Not saved".
SAVED = re.compile("^Saved$")

NOTES = (
    "# Plan\n"
    "Book the **flights**, then the *rail pass*: [JR](https://japanrailpass.net).\n"
    "- [ ] compare `JR Pass` prices\n"
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
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
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


def test_sub_tasks_are_written_with_a_box_and_enter(page, live, app_db) -> None:
    task_id = open_task(page, live, app_db)
    page.keyboard.type("Pack")
    page.keyboard.press("Enter")
    page.keyboard.type("- [ ] adapters")
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
    expected = (
        "Pack\n- [ ] adapters\n- [ ] rail pass\n  from the JR office\n  - [ ] yen\nDone by Friday."
    )
    assert field(page) == expected
    assert saved(page, app_db, task_id) == expected


def test_a_dash_writes_a_bullet_not_a_sub_task(page, live, app_db) -> None:
    task_id = open_task(page, live, app_db)
    page.keyboard.type("- ICS, not CalDAV")
    assert page.locator(".cm-md-bullet").count() == 1
    assert page.locator(".cm-md-box").count() == 0
    # Enter goes on to the next bullet.
    page.keyboard.press("Enter")
    page.keyboard.type("no OAuth")
    assert page.locator(".cm-md-bullet").count() == 2
    # Ctrl+L makes the caret's a sub-task.
    page.keyboard.press("Control+l")
    assert field(page) == "- ICS, not CalDAV\n- [ ] no OAuth"
    assert page.locator(".cm-md-box").count() == 1
    assert saved(page, app_db, task_id) == "- ICS, not CalDAV\n- [ ] no OAuth"


def test_the_caret_never_stands_inside_a_box(page, live, app_db) -> None:
    task_id = open_task(page, live, app_db, "- [ ] adapters")
    page.locator(".cm-line", has_text="adapters").click()
    page.keyboard.press("Home")
    page.keyboard.type("two ")
    assert field(page) == "- [ ] two adapters"
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
    # Unticked, its box is open again ("- [ ] "), as a row's box writes it.
    page.locator(".cm-md-box").first.click()
    assert field(page) == "Before\n- [ ] adapters\n- yen"
    # Ctrl+L boxes the caret's bullet, then ticks it.
    page.locator(".cm-line", has_text="yen").click()
    page.keyboard.press("Control+l")
    assert field(page) == "Before\n- [ ] adapters\n- [ ] yen"
    page.keyboard.press("Control+l")
    assert field(page) == "Before\n- [ ] adapters\n- [x] yen"
    # Undo takes a tick back.
    page.keyboard.press("Control+z")
    assert field(page) == "Before\n- [ ] adapters\n- [ ] yen"


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
    page.goto(f"{live}/plan")
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


def caret(page) -> dict:
    """Where the drawn caret stands, and where the words of the line with
    `adapters` start, for the caret on an item's line to stand at."""
    return page.evaluate(
        """async () => {
            // The caret is drawn a frame after the selection moves.
            await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
            const ed = document.querySelector(".main [data-notes-editor]");
            const c = ed.querySelector(".cm-cursor").getBoundingClientRect();
            const view = window.NotesEditor.viewOf(ed);
            const at = view.state.doc.toString().indexOf("adapters");
            const words = view.coordsAtPos(at, 1);
            return { left: c.left, height: c.height, words: words.left,
                     tall: words.bottom - words.top };
        }"""
    )


def test_the_caret_shows_after_a_box_or_a_bullet(page, live, app_db) -> None:
    open_task(page, live, app_db)
    page.keyboard.type("- [ ] adapters")
    # A new sub-task, its words still to write: the caret stands where they
    # will, its full height, not on the box's edge.
    page.keyboard.press("Enter")
    at = caret(page)
    assert abs(at["left"] - at["words"]) <= 1.5
    assert at["height"] >= at["tall"] - 1
    # Back up onto a written sub-task's first word: the same.
    page.keyboard.type("yen")
    page.keyboard.press("Home")
    page.keyboard.press("ArrowUp")
    at = caret(page)
    assert abs(at["left"] - at["words"]) <= 1.5
    assert at["height"] >= at["tall"] - 1
    # A bullet's new item too.
    page.keyboard.press("End")
    page.keyboard.press("Control+l")
    page.keyboard.press("Control+l")
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.keyboard.type("- ")
    assert page.locator(".cm-md-bullet").count() == 1
    at = caret(page)
    assert abs(at["left"] - at["words"]) <= 1.5
    assert at["height"] >= at["tall"] - 1


def editor_focused(page) -> bool:
    return page.evaluate("() => !!document.activeElement?.closest('.main [data-notes-editor]')")


def test_tab_indents_and_shift_tab_steps_out_of_the_editor(page, live, app_db) -> None:
    open_task(page, live, app_db, "Pack\nadapters")
    page.locator(".cm-line", has_text="adapters").click()
    # Tab indents a plain line under the one above, and never leaves.
    page.keyboard.press("Tab")
    assert field(page) == "Pack\n  adapters"
    assert editor_focused(page)
    # As deep as it can go, Tab does nothing, and still stays.
    page.keyboard.press("Tab")
    assert field(page) == "Pack\n  adapters"
    assert editor_focused(page)
    # On a blank line it indents what will be written there.
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.keyboard.press("Tab")
    page.keyboard.type("- yen")
    assert field(page) == "Pack\n  adapters\n\n  - yen"
    # Shift+Tab steps an indented line back out ...
    page.keyboard.press("Shift+Tab")
    assert field(page) == "Pack\n  adapters\n\n- yen"
    assert editor_focused(page)
    # ... and at the left, out of the editor.
    page.keyboard.press("Shift+Tab")
    assert field(page) == "Pack\n  adapters\n\n- yen"
    assert not editor_focused(page)


def test_tab_indents_code_as_deep_as_it_needs(page, live, app_db) -> None:
    open_task(page, live, app_db, "```py\nif x:\nreturn\n```")
    page.locator(".cm-line", has_text="return").click()
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    assert field(page) == "```py\nif x:\n    return\n```"
    assert editor_focused(page)
