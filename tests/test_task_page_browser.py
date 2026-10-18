"""A task's own page in a real browser, opened from wherever tasks are
listed: Calendar's sheet (its title there, Ctrl+Enter writing one), a row on
a task list (its Open, Ctrl+Enter on the cursor), the task being edited there
(its Open, Ctrl+Shift+Enter, saved first) and a nudge. What is written on
the page is saved as it is written, the page going back to where it was
opened. Today's notes open it too (test_notepad_browser.py). The `live`, `page` and
`app_db` fixtures are conftest.py's."""

import re
import time
from datetime import date, timedelta

import pytest

from app.models import Task, TaskOwner
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

# "Saved" alone, not "Not saved".
SAVED = re.compile("^Saved$")

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
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    assert stored(app_db, "Plan the trip").notes == "Flights first, then the rail pass."

    # The title is the page's heading, and its trailing words its fields.
    page.locator(".main .sheet-title").click()
    page.keyboard.press("End")
    page.keyboard.type(" to Japan tomorrow ")
    page.keyboard.press("Escape")
    page.wait_for_function("() => document.title.startsWith('Plan the trip to Japan ·')")
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
        page.locator("[data-page-state]", has_text=SAVED).wait_for()
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


def test_writing_on_it_keeps_what_was_changed_elsewhere(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Ship the release", planned_for=TODAY)
        tasks_svc.set_status(db, task.id, "in_progress")
        db.commit()
    page.goto(f"{live}/tasks/{task.id}")
    # While it is open, its pull request merges and Claude gives it a due.
    with app_db() as db:
        tasks_svc.update_task(db, task.id, status="done", due=TODAY + timedelta(days=3))
        db.commit()
    page.locator(".main [data-notes-editor]").click()
    page.keyboard.type("Tagged v2.")
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    with app_db() as db:
        stored_task = db.get(Task, task.id)
        assert stored_task.notes == "Tagged v2."
        assert stored_task.status == "done"
        assert stored_task.due == TODAY + timedelta(days=3)

    # What is changed on it is saved over them: its own field, and only it.
    # (The header still says Saved from before: the task is what tells.)
    page.locator("[data-sheet-check]").click()
    deadline = time.monotonic() + 5
    while True:
        with app_db() as db:
            stored_task = db.get(Task, task.id)
            status, due = stored_task.status, stored_task.due
        if status == "needs_review" or time.monotonic() > deadline:
            break
        time.sleep(0.05)
    assert status == "needs_review"
    assert due == TODAY + timedelta(days=3)


def test_its_description_is_read_drawn_and_its_mode_remembered(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(
            db, title="Trip", notes="## Packing\n- [ ] passport\n- [ ] adapter", planned_for=TODAY
        )
        db.commit()
    page.goto(f"{live}/tasks/{task.id}")
    editor = page.locator(".main [data-notes-editor] .cm-content")
    modes = page.locator("[data-md-modes]")
    # Opened in Live: the heading drawn, its marks hidden.
    assert modes.locator('[aria-pressed="true"]').inner_text() == "Live"
    assert editor.locator(".cm-line").first.inner_text() == "Packing"

    # Read (Ctrl+E): not to be written, though its boxes still tick.
    page.keyboard.press("Control+e")
    assert modes.locator('[aria-pressed="true"]').inner_text() == "Reading"
    assert editor.get_attribute("contenteditable") == "false"
    editor.locator(".cm-md-box").first.click()
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    assert stored(app_db, "Trip").notes == "## Packing\n- [x] passport\n- [ ] adapter"

    # Opened again, it is read; Source shows its Markdown as written.
    page.reload()
    assert modes.locator('[aria-pressed="true"]').inner_text() == "Reading"
    modes.locator("button", has_text="Source").click()
    assert editor.locator(".cm-line").first.inner_text() == "## Packing"
    assert editor.get_attribute("contenteditable") == "true"


def test_a_row_on_a_task_list_opens_its_page(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Renew the passport")
        db.commit()
    page.goto(f"{live}/plan")  # the open tasks without a day
    row = page.locator(f"#task-{task.id}")
    # Its Open, quiet until the row is hovered, as its bin is.
    row.hover()
    row.locator(".task-open").click()
    page.wait_for_url(f"{live}/tasks/{task.id}")
    page.locator(".page-back", has_text="Plan").click()
    page.wait_for_url(f"{live}/plan")

    # Ctrl+Enter on the cursor's row, as on the Gantt and Calendar's sheet.
    row.focus()
    page.keyboard.press("Control+Enter")
    page.wait_for_url(f"{live}/tasks/{task.id}")


def test_a_task_being_edited_opens_its_page_saved_first(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Book flights")
        db.commit()
    page.goto(f"{live}/plan")
    page.locator(f"#task-{task.id} .task-title-btn").click()
    sheet = page.locator(f"#task-{task.id} .task-sheet[data-sheet='edit']")
    sheet.locator(".sheet-title").click()
    page.keyboard.press("End")
    page.keyboard.type(" to Tokyo")
    # Its Open: written, then opened, the page showing what was written.
    sheet.locator("[data-open-task]").click()
    page.wait_for_url(f"{live}/tasks/{task.id}")
    assert page.locator(".main .sheet-title").inner_text() == "Book flights to Tokyo"
    assert stored(app_db, "Book flights to Tokyo").id == task.id

    # Ctrl+Shift+Enter in it does the same, its trailing words taken as fields.
    page.goto(f"{live}/plan")
    page.locator(f"#task-{task.id} .task-title-btn").click()
    sheet.locator(".sheet-title").click()
    page.keyboard.press("End")
    page.keyboard.type(" tomorrow")
    page.keyboard.press("Control+Shift+Enter")
    page.wait_for_url(f"{live}/tasks/{task.id}")
    assert stored(app_db, "Book flights to Tokyo").planned_for == TODAY + timedelta(days=1)


def test_a_nudge_opens_its_task_s_page(page, live, app_db) -> None:
    from datetime import datetime

    from app.services import nudges as nudges_svc

    with app_db() as db:
        task = tasks_svc.create_task(db, title="Pay the invoice", due=TODAY + timedelta(days=1))
        nudges_svc.evaluate(db, datetime.now())
        db.commit()
    page.goto(f"{live}/today")
    page.locator(".nudge-action", has_text="Open").click()
    page.wait_for_url(f"{live}/tasks/{task.id}")
    page.locator(".page-back", has_text="Today").click()
    page.wait_for_url(f"{live}/today")


def work(app_db) -> dict:  # noqa: ANN001
    """The work of the one task in a project, read in a session of its own."""
    with app_db() as db:
        task = db.query(Task).filter(Task.project_id.is_not(None)).one()
        return {
            "repos": [r.location for r in task.repos],
            "acceptance": task.acceptance,
            "prs": [p.url for p in task.pull_requests],
        }


def test_a_tasks_work_is_written_on_its_page(page, live, app_db) -> None:
    from app.services import projects as projects_svc

    app = "https://github.com/oscartoromal-ai/everyday-app"
    with app_db() as db:
        project = projects_svc.create_project(db, name="Everyday")
        projects_svc.add_repo(db, project_id=project.id, location=app)
        task = tasks_svc.create_task(
            db, title="Add a task from anywhere", project_id=project.id, owner=TaskOwner.claude
        )
        db.commit()
        task_id = task.id
    page.goto(f"{live}/tasks/{task_id}")
    # Its work is a pane of the sidebar, shown by its icon.
    page.locator('[data-side-tab="work"]').click()
    run = page.locator("#task-run")

    # A repository of its project's, pressed to work the task in it.
    run.locator(".run-repo", has_text="everyday-app").click()
    run.locator('.run-repo[aria-pressed="true"]').wait_for()
    assert work(app_db)["repos"] == [app]

    # What done means, saved as it is written; the header says so.
    page.locator("#task-run textarea[name=acceptance]").fill("It opens with N.")
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    assert work(app_db)["acceptance"] == "It opens with N."

    # A pull request, by its URL; then taken off.
    page.locator("#task-run .run-add input").fill(f"{app}/pull/41")
    page.keyboard.press("Enter")
    page.locator("#task-run .run-pr", has_text="everyday-app#41").wait_for()
    assert page.locator("#task-run .run-pr .chip").inner_text() == "Not read yet"
    page.locator("#task-run .run-pr").hover()
    page.locator("#task-run .run-pr .task-delete").click()
    page.locator("#task-run .run-pr").wait_for(state="detached")
    assert work(app_db)["prs"] == []


# The text of the editor's line the caret is on, as drawn.
CARET_LINE = (
    "(n => (n.nodeType === 1 ? n : n.parentElement).closest('.cm-line')?.textContent)"
    "(window.getSelection().anchorNode)"
)


def test_its_sidebar_panes_are_chosen_by_their_icons(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(
            db, title="Trip", notes="# Plan\nwords\n## Flights\n- [ ] book", planned_for=TODAY
        )
        db.commit()
    page.goto(f"{live}/tasks/{task.id}")
    is_open = "document.documentElement.dataset.agent === 'open'"
    assert not page.evaluate(is_open)
    # Oscar's task opens on its outline: the description's headings.
    page.locator('[data-side-tab="outline"]').click()
    assert page.evaluate(is_open)
    assert page.locator(".outline button").all_inner_texts() == ["Plan", "Flights"]
    # A heading's line takes the caret, at its start, its marks showing once
    # the editor has focus (CodeMirror hears of focus a moment late).
    page.locator(".outline button", has_text="Flights").click()
    page.wait_for_function(CARET_LINE + " === '## Flights'")
    assert page.evaluate("window.getSelection().anchorOffset") == 0
    # Another icon shows its pane; the shown pane's icon collapses the sidebar.
    page.locator('[data-side-tab="history"]').click()
    page.locator("#side-history .history-step").first.wait_for()
    page.locator('[data-side-tab="history"]').click()
    assert not page.evaluate(is_open)


def test_handed_to_an_agent_its_work_shows(page, live, app_db) -> None:
    from app.services import projects as projects_svc

    with app_db() as db:
        project = projects_svc.create_project(db, name="Everyday")
        task = tasks_svc.create_task(db, title="Widen the page", project_id=project.id)
        db.commit()
    # Wide enough for the map beside the document with the sidebar open.
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/tasks/{task.id}")
    page.locator('[data-side-tab="work"]').click()
    pane = page.locator("#side-work")
    assert not pane.locator("#task-run").is_visible()
    pane.get_by_role("button", name="Hand to an agent").click()
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    assert stored(app_db, "Widen the page").owner == TaskOwner.claude
    pane.locator("#task-run textarea[name=acceptance]").wait_for(state="visible")
    assert not pane.get_by_role("button", name="Hand to an agent").is_visible()
    # The map marks it Claude's.
    assert page.locator('.map-task.is-here .map-agent').is_visible()


def test_its_map_folds_are_remembered(page, live, app_db) -> None:
    from app.services import projects as projects_svc

    with app_db() as db:
        project = projects_svc.create_project(db, name="Everyday")
        lane = projects_svc.create_workstream(db, project_id=project.id, name="Usability")
        other = projects_svc.create_workstream(db, project_id=project.id, name="Phone")
        task = tasks_svc.create_task(db, title="Here", project_id=project.id, workstream_id=lane.id)
        tasks_svc.create_task(db, title="Swipe", project_id=project.id, workstream_id=other.id)
        db.commit()
    page.goto(f"{live}/tasks/{task.id}")
    swipe = page.locator(".map-task", has_text="Swipe")
    assert not swipe.is_visible()
    page.locator(".map-lane", has_text="Phone").click()
    assert swipe.is_visible()
    page.reload()
    assert page.locator(".map-task", has_text="Swipe").is_visible()
    # A task there opens its own page, its map the same.
    page.locator(".map-task", has_text="Swipe").click()
    page.wait_for_url(re.compile(r"/tasks/\d+$"))
    assert page.locator('.map-task.is-here').inner_text() == "Swipe"


def test_a_file_is_added_written_and_renamed_on_the_tasks_page(page, live, app_db) -> None:
    from app.services import task_files

    with app_db() as db:
        task = tasks_svc.create_task(db, title="Plan the move")
        db.commit()
    # Wide enough for the map beside the document with the sidebar open.
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/tasks/{task.id}")
    # Written on the map's last line, a path naming its folder: opened to be written.
    page.locator(".map-new input").fill("notes/plan")
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(r"/files/notes/plan\.md$"))
    assert page.locator('.map-file[aria-current="page"] .map-name').inner_text() == "plan.md"
    page.locator(".doc-body .cm-content").click()
    page.keyboard.type("# Plan")
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    assert task_files.read(task.id, "notes/plan.md")[0] == "# Plan"
    # The outline follows the file.
    page.locator('[data-side-tab="outline"]').click()
    assert page.locator(".outline button").all_inner_texts() == ["Plan"]
    # Renamed in its heading: its address and its row follow.
    page.locator("[data-doc-name]").fill("The plan")
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(r"/files/notes/The%20plan\.md$"))
    assert page.locator('.map-file[aria-current="page"] .map-name').inner_text() == "The plan.md"
    assert task_files.paths(task.id) == ["notes/The plan.md"]
    # Its description, from the map.
    page.locator(".map-file", has_text="Description").click()
    page.wait_for_url(re.compile(rf"/tasks/{task.id}$"))
    assert page.locator(".task-page .sheet-title").inner_text() == "Plan the move"
