"""List and details in a real browser: a task picked on the list by a click
or by the keyboard's cursor, shown in the pane and kept across the list's
redraws and visits; ticks, edits, quick do-dates and sub-tasks from the
line and the pane; folds and Show completed kept; filing by drag; and on a
phone, a line that opens its task's page. The app serves from a thread
over a throwaway database (the `live`, `page` and `phone` fixtures,
conftest.py)."""

from datetime import date, timedelta

import pytest

from app.models import TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")


@pytest.fixture
def made(app_db) -> dict:
    """A project of two workstreams, API with two tasks (one with
    sub-tasks) and UI with one, a task in none, and one finished."""
    with app_db() as db:
        project = projects_svc.create_project(db, name="Calendar sync")
        api = projects_svc.create_workstream(db, project_id=project.id, name="API")
        ui = projects_svc.create_workstream(db, project_id=project.id, name="UI")
        parse = tasks_svc.create_task(
            db,
            title="parse",
            project_id=project.id,
            workstream_id=api.id,
            notes="Context.\n\n- [ ] read\n- [ ] write",
        )
        fetch = tasks_svc.create_task(
            db, title="fetch", project_id=project.id, workstream_id=api.id
        )
        draw = tasks_svc.create_task(db, title="draw", project_id=project.id, workstream_id=ui.id)
        tidy = tasks_svc.create_task(db, title="tidy", project_id=project.id)
        old = tasks_svc.create_task(db, title="old", project_id=project.id)
        tasks_svc.set_status(db, old.id, TaskStatus.done)
        db.commit()
        return {
            "project": project.id,
            "api": api.id,
            "ui": ui.id,
            "parse": parse.id,
            "fetch": fetch.id,
            "draw": draw.id,
            "tidy": tidy.id,
            "old": old.id,
        }


def open_pane(page, live, made) -> None:
    page.goto(f"{live}/projects/{made['project']}/tasks?view=pane")
    page.locator(".tasks-in-pane .lp-line").first.wait_for()


def redrawn(page) -> None:
    """The list drawn again from the server, as any change elsewhere does."""
    page.evaluate("document.querySelector('#project-tasks').dataset.old = '1'")
    page.evaluate("htmx.trigger(document.body, 'tasks:changed')")
    # Swapped and settled at once (no settle delay), the view's own drawing with it.
    page.wait_for_function("!document.querySelector('#project-tasks').dataset.old")


def task(app_db, task_id: int):  # noqa: ANN201
    with app_db() as db:
        return tasks_svc.get_task(db, task_id)


def click_line(page, task_id: int) -> None:
    """A click on a task's line, in its edge before its box: away from its
    title and the quick do-dates its hover shows."""
    page.locator(f"#task-{task_id}").click(position={"x": 16, "y": 12})


def focused_on(page, task_id: int) -> None:
    page.wait_for_function(f"document.activeElement.id === 'task-{task_id}'")


def shown_title(page) -> str:
    return page.locator(".lp-details .lp-card h2").inner_text()


def test_a_click_on_a_line_picks_it_and_the_pick_is_kept(page, live, made) -> None:
    open_pane(page, live, made)
    assert page.locator(".lp-details .lp-empty").is_visible()
    click_line(page, made["parse"])
    assert shown_title(page) == "parse"
    line = page.locator(f"#task-{made['parse']}")
    assert line.get_attribute("aria-current") == "true" and "picked" in line.get_attribute("class")
    card = page.locator(".lp-details .lp-card")
    workstream = card.locator("dt", has_text="Workstream").locator("xpath=..").locator("dd")
    assert workstream.inner_text() == "API"
    assert card.locator(".subtask", has_text="write").count() == 1
    # The list drawn again, and the page visited again: still picked.
    redrawn(page)
    assert shown_title(page) == "parse" and page.locator(".lp-line.picked").count() == 1
    page.reload()
    assert shown_title(page) == "parse"
    # Its box steps it on, without picking it (a click: the step swaps the box out).
    page.locator(f"#task-{made['draw']} .task-check").click()
    page.wait_for_function("!document.querySelector('.htmx-request')")
    box = f"#lp-ws-{made['ui']} #task-{made['draw']} .task-check"
    page.locator(f"{box}[data-status=in_progress]").wait_for()
    assert shown_title(page) == "parse"


def test_the_pane_follows_the_keyboards_cursor(page, live, made) -> None:
    open_pane(page, live, made)
    page.keyboard.press("ArrowDown")
    assert shown_title(page) == "parse"
    page.keyboard.press("j")
    assert shown_title(page) == "fetch"
    page.keyboard.press("ArrowDown")  # on into the next workstream
    assert shown_title(page) == "draw"
    page.keyboard.press("k")
    assert shown_title(page) == "fetch"
    # Space goes into the pane, at its title (a second Space ticks nothing),
    # Esc comes back to the line, and the cursor's keys there go on from it.
    page.keyboard.press("Space")
    assert page.evaluate("document.activeElement.matches('.lp-details [data-lp-edit]')")
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.id") == f"task-{made['fetch']}"
    page.keyboard.press("Space")
    page.keyboard.press("ArrowDown")
    assert page.evaluate("document.activeElement.id") == f"task-{made['draw']}"
    assert shown_title(page) == "draw"


def test_done_from_the_pane_shows_it_done_then_the_next_is_picked(page, live, app_db, made) -> None:
    # In review, its box (and X) makes it done.
    with app_db() as db:
        for name in ("parse", "fetch"):
            tasks_svc.set_status(db, made[name], TaskStatus.needs_review)
        db.commit()
    open_pane(page, live, made)
    click_line(page, made["parse"])
    assert page.locator(".lp-details .lp-done").inner_text() == "Needs review"
    page.locator(".lp-details .lp-done").click()
    page.locator(f"#lp-ws-{made['api']} #task-{made['parse']}").wait_for(state="detached")
    assert task(app_db, made["parse"]).status == TaskStatus.done
    # Still in the pane, done, to be unticked; gone on the next visit, where
    # nothing is picked.
    assert page.locator(".lp-details .lp-done").inner_text() == "Done"
    assert page.locator(".lp-details .lp-card.done").count() == 1
    page.reload()
    assert page.locator(".lp-details .lp-empty").is_visible()
    # Done by the keyboard, the cursor goes on to the next task, and the pane with it.
    click_line(page, made["fetch"])
    page.keyboard.press("x")
    page.locator(f"#lp-ws-{made['api']} #task-{made['fetch']}").wait_for(state="detached")
    focused_on(page, made["draw"])
    assert shown_title(page) == "draw"


def test_a_task_gone_gives_the_pane_to_the_one_after(page, live, app_db, made) -> None:
    open_pane(page, live, made)
    click_line(page, made["fetch"])
    with app_db() as db:
        tasks_svc.delete_task(db, made["fetch"])
        db.commit()
    redrawn(page)
    assert shown_title(page) == "draw"
    assert page.locator(f"#task-{made['draw']}").get_attribute("aria-current") == "true"


def test_enter_edits_on_the_line_and_esc_or_a_save_give_it_back(page, live, app_db, made) -> None:
    open_pane(page, live, made)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    sheet = page.locator(f"li#task-{made['parse']} .task-sheet[data-sheet=edit]")
    sheet.wait_for()
    assert shown_title(page) == "parse"  # the pane keeps the task while it is edited
    page.keyboard.press("Escape")
    line = page.locator(f"li#task-{made['parse']}.lp-line")
    line.wait_for()
    focused_on(page, made["parse"])
    assert line.get_attribute("aria-current") == "true"
    # The pane's title edits it too; a save comes back as the line, the pane with it.
    page.locator(".lp-details [data-lp-edit]").click()
    sheet.wait_for()
    page.keyboard.type(" files")
    page.keyboard.press("Escape")
    page.locator(f"li#task-{made['parse']}.lp-line", has_text="parse files").wait_for()
    assert task(app_db, made["parse"]).title == "parse files"
    page.wait_for_function("document.querySelector('.lp-card h2')?.innerText === 'parse files'")


def test_quick_do_dates_and_sub_tasks_from_the_pane(page, live, app_db, made) -> None:
    open_pane(page, live, made)
    click_line(page, made["parse"])
    page.locator(".lp-details [data-plan=tomorrow]").click()
    # (Beside the pane at this width, the line keeps its do-date unseen.)
    page.locator(f"#task-{made['parse']} .tv-date", has_text="tomorrow").wait_for(state="attached")
    assert task(app_db, made["parse"]).planned_for == date.today() + timedelta(days=1)
    assert page.locator(".lp-details .lp-fields .tv-date").inner_text() == "Tomorrow"
    # Tomorrow gone from it, the focus stays in the do-date's row.
    row = "document.activeElement.closest('.lp-fields > div')?.querySelector('dt').innerText"
    assert page.evaluate(row) == "Do-date"
    # A sub-task ticked in the pane: kept, counted on the line, the focus where it was.
    page.locator(".lp-details .subtask", has_text="write").locator("input").click()
    page.locator(f"#task-{made['parse']} .tv-subcount", has_text="1/2").wait_for()
    assert "- [x] write" in task(app_db, made["parse"]).notes
    assert page.locator(".lp-details .subtask", has_text="write").locator("input").is_checked()
    assert page.evaluate("document.activeElement.closest('.subtask')?.innerText.trim()") == "write"


def test_folds_and_show_completed_are_kept(page, live, made) -> None:
    open_pane(page, live, made)
    api = page.locator(f"[data-fold-key='ws-{made['api']}']")
    api.locator("[data-fold]").click()
    assert not page.locator(f"#task-{made['parse']}").is_visible()
    assert api.locator("[data-fold]").get_attribute("aria-expanded") == "false"
    page.keyboard.press("ArrowDown")  # the cursor passes the folded lines by
    assert shown_title(page) == "draw"
    done = page.locator(f"#task-{made['old']}")
    assert not done.is_visible()
    page.locator("[data-show-done]").click()
    done.wait_for()
    assert done.locator(".task-check").is_checked()
    redrawn(page)
    assert not page.locator(f"#task-{made['parse']}").is_visible() and done.is_visible()
    page.reload()
    assert not page.locator(f"#task-{made['parse']}").is_visible() and done.is_visible()
    api.locator("[data-fold]").click()
    assert page.locator(f"#task-{made['parse']}").is_visible()


def test_a_line_dragged_onto_a_section_is_filed_there(page, live, app_db, made) -> None:
    open_pane(page, live, made)
    ui = page.locator(f"[data-fold-key='ws-{made['ui']}'] .tv-head")
    page.locator(f"#task-{made['tidy']}").drag_to(ui)
    page.locator(f"#lp-ws-{made['ui']} #task-{made['tidy']}").wait_for()
    assert task(app_db, made["tidy"]).workstream_id == made["ui"]
    loose = page.locator("[data-fold-key='loose'] .tv-head")
    page.locator(f"#task-{made['draw']}").drag_to(loose)
    page.locator(f"#lp-loose #task-{made['draw']}").wait_for()
    assert task(app_db, made["draw"]).workstream_id is None
    # Dropped on the pane, it stays where it was: nothing is asked of the server.
    patches = []
    page.on("request", lambda r: patches.append(r.url) if r.method == "PATCH" else None)
    page.locator(f"#task-{made['fetch']}").drag_to(page.locator(".lp-details"))
    redrawn(page)  # a request after the drop: one the drop made would have gone before it
    assert patches == []
    assert task(app_db, made["fetch"]).workstream_id == made["api"]
    assert page.locator(f"#lp-ws-{made['api']} #task-{made['fetch']}").count() == 1


def test_the_composer_adds_to_its_own_section(page, live, app_db, made) -> None:
    open_pane(page, live, made)
    composer = page.locator(f"[data-fold-key='ws-{made['ui']}'] .task-sheet[data-sheet=compose]")
    composer.locator(".sheet-line").click()
    page.keyboard.type("paint")
    page.keyboard.press("Control+Enter")
    page.locator(f"#lp-ws-{made['ui']} .lp-line", has_text="paint").wait_for()
    with app_db() as db:
        added = next(t for t in tasks_svc.list_tasks(db) if t.title == "paint")
        assert added.workstream_id == made["ui"]


def test_on_a_phone_a_line_opens_its_tasks_page(phone, live, made) -> None:
    open_pane(phone, live, made)
    assert not phone.locator(".lp-details").is_visible()
    click_line(phone, made["parse"])
    phone.wait_for_url(f"{live}/tasks/{made['parse']}")


def test_a_mouse_tick_on_the_picked_line_picks_the_next_task(page, live, app_db, made) -> None:
    # In review, its box's click makes it done.
    with app_db() as db:
        tasks_svc.set_status(db, made["parse"], TaskStatus.needs_review)
        db.commit()
    open_pane(page, live, made)
    click_line(page, made["parse"])
    page.locator(f"#task-{made['parse']} .task-check").click()
    page.locator(f"#lp-ws-{made['api']} #task-{made['parse']}").wait_for(state="detached")
    assert task(app_db, made["parse"]).status == TaskStatus.done
    focused_on(page, made["fetch"])
    assert shown_title(page) == "fetch"


def test_delete_on_a_line_asks_then_deletes(page, live, app_db, made) -> None:
    open_pane(page, live, made)
    click_line(page, made["tidy"])
    page.keyboard.press("Delete")
    dialog = page.locator("#confirm-dialog")
    dialog.get_by_role("button", name="Delete").click()
    page.locator(f"#task-{made['tidy']}").wait_for(state="detached")
    with app_db() as db:
        assert made["tidy"] not in {t.id for t in tasks_svc.list_tasks(db)}


def test_n_writes_into_the_cursors_section(page, live, made) -> None:
    open_pane(page, live, made)
    click_line(page, made["draw"])
    page.keyboard.press("n")
    assert (
        page.evaluate("document.activeElement.closest('[data-task-group]')?.dataset.foldKey")
        == f"ws-{made['ui']}"
    )


def test_shift_j_and_k_jump_between_sections(page, live, made) -> None:
    open_pane(page, live, made)
    click_line(page, made["fetch"])
    page.keyboard.press("Shift+J")
    focused_on(page, made["draw"])
    page.keyboard.press("Shift+J")
    focused_on(page, made["tidy"])
    page.keyboard.press("Shift+K")  # to the start of the section before
    focused_on(page, made["draw"])


def test_compact_lines_are_28px_and_their_rule(page, live, made) -> None:
    open_pane(page, live, made)
    line = page.locator(f"#task-{made['fetch']}")
    assert line.bounding_box()["height"] == 36  # 35px and its rule
    page.evaluate("localStorage.setItem('pc-density', 'compact')")
    page.reload()
    assert line.bounding_box()["height"] == 28  # 27px and its rule, as every compact row
    head = page.locator(f"[data-fold-key='ws-{made['api']}'] .tv-head")
    assert head.bounding_box()["height"] == 38


def test_at_a_1024_window_the_list_has_the_room_and_a_line_opens_its_page(
    page, live, app_db, made
) -> None:
    long = "parse the calendar's feed, its recurring events and their exceptions too"
    with app_db() as db:
        tasks_svc.update_task(
            db,
            made["parse"],
            title=long,
            planned_for=date.today(),
            due=date.today() + timedelta(days=9),
        )
        db.commit()
    page.set_viewport_size({"width": 1024, "height": 800})
    open_pane(page, live, made)
    assert not page.locator(".lp-details").is_visible()
    parse = page.locator(f"#task-{made['parse']}")
    assert parse.locator(".task-title-btn").bounding_box()["width"] > 380
    assert parse.locator(".lp-slot-date").is_visible()
    assert parse.locator(".lp-slot-due").inner_text().startswith("due ")
    click_line(page, made["parse"])
    page.wait_for_url(f"{live}/tasks/{made['parse']}")


def test_beside_a_narrow_pane_a_line_drops_its_do_date_and_dues_word(
    page, live, app_db, made
) -> None:
    with app_db() as db:
        tasks_svc.update_task(
            db, made["parse"], planned_for=date.today(), due=date.today() + timedelta(days=9)
        )
        db.commit()
    open_pane(page, live, made)  # 1200: the view 896px wide, its pane 320px
    assert page.locator(".lp-details").is_visible()
    parse = page.locator(f"#task-{made['parse']}")
    assert not parse.locator(".lp-slot-date").is_visible()
    assert not parse.locator(".lp-slot-due").inner_text().startswith("due")
