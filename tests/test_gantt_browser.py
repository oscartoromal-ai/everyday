"""A project's Gantt in a real browser, worked as a spreadsheet: writing a
task and its weeks from the keyboard, a refused week, drawing and dragging
bars, Alt moves, rows moved into a workstream, a workstream added by Alt+W,
undo, deleting a task, a title growing its row as it is written, and a task
opened on its page. The `live`, `page` and `app_db` fixtures are conftest.py's."""

from datetime import date, timedelta

import pytest

from app.models import Task, TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

THIS = date.today() - timedelta(days=date.today().weekday())


def _week(n: int) -> str:
    return (THIS + timedelta(weeks=n)).isoformat()


@pytest.fixture
def project(app_db) -> int:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Beta")
        projects_svc.create_workstream(db, project_id=project.id, name="Launch")
        tasks_svc.create_task(db, title="Loose end", project_id=project.id)
        db.commit()
        return project.id


def _row(page, title: str):
    return page.locator(f'.gantt-row[data-title="{title}"]')


def _span(page, title: str) -> tuple[str, str]:
    row = _row(page, title)
    return row.get_attribute("data-starts-on"), row.get_attribute("data-due")


def test_a_task_and_its_weeks_are_written_from_the_keyboard(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}/gantt")
    page.locator('.gantt-row.kind-add[data-key^="add-w"] .gantt-title').click()
    page.keyboard.type("Write the spec")
    page.keyboard.press("Tab")
    _row(page, "Write the spec").wait_for()
    # Its priority, as a letter, then on to its Start.
    page.keyboard.type("h")
    page.keyboard.press("Tab")
    page.wait_for_function(
        "document.querySelector('.gantt-row[data-title=\"Write the spec\"]')"
        ".dataset.priority === 'high'"
    )
    assert _row(page, "Write the spec").locator(".gantt-priority").inner_text() == "High"
    page.keyboard.type("next week")
    page.keyboard.press("Tab")
    page.wait_for_function(
        "document.querySelector('.gantt-row[data-title=\"Write the spec\"]').dataset.startsOn"
    )
    page.keyboard.type("3")
    page.keyboard.press("Enter")
    page.wait_for_function(
        "document.querySelector('.gantt-row[data-title=\"Write the spec\"] .gantt-length')"
        ".textContent.trim() === '3'"
    )
    assert _span(page, "Write the spec")[0] == _week(1)
    bar = _row(page, "Write the spec").locator(".gantt-bar")
    # The sheet opens a week back; Mon to Fri, three weeks on.
    assert bar.get_attribute("style") == "--s: 2.0; --n: 2.7143"

    # A week it cannot read is refused, and the cell opens again on the words.
    # Enter went down the Wks column; up and left is the task's Start.
    page.keyboard.press("ArrowUp")
    page.keyboard.press("ArrowLeft")
    page.keyboard.type("someday")
    page.keyboard.press("Enter")
    page.locator(".cal-toast").get_by_text("Not a week: someday").wait_for()
    field = page.locator(".gantt-input")
    field.wait_for()
    assert field.input_value() == "someday"
    page.keyboard.press("Escape")
    assert page.locator(".gantt-input").count() == 0


def test_bars_are_drawn_dragged_moved_and_undone(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}/gantt")
    row = _row(page, "Loose end")
    week = page.locator(".gantt-wk-head").first.bounding_box()["width"]

    # Drawn over three weeks from this one.
    start = row.locator(f'.gantt-wk[data-day="{_week(0)}"]').bounding_box()
    y = start["y"] + start["height"] / 2
    page.mouse.move(start["x"] + week / 2, y)
    page.mouse.down()
    page.mouse.move(start["x"] + week * 1.5, y, steps=4)
    page.mouse.move(start["x"] + week * 2.5, y, steps=4)
    page.mouse.up()
    page.wait_for_function(
        "document.querySelector('.gantt-row[data-title=\"Loose end\"]').dataset.startsOn"
    )
    assert _span(page, "Loose end") == (_week(0), (THIS + timedelta(weeks=2, days=4)).isoformat())

    # Dragged a week later by its middle.
    bar = row.locator(".gantt-bar").bounding_box()
    page.mouse.move(bar["x"] + bar["width"] / 2, bar["y"] + bar["height"] / 2)
    page.mouse.down()
    page.mouse.move(bar["x"] + bar["width"] / 2 + week, bar["y"] + bar["height"] / 2, steps=6)
    page.mouse.up()
    page.wait_for_function(
        f"document.querySelector('.gantt-row[data-title=\"Loose end\"]').dataset.startsOn"
        f" === '{_week(1)}'"
    )

    # Alt+Right a week later again, then undo both.
    page.keyboard.press("Alt+ArrowRight")
    page.wait_for_function(
        f"document.querySelector('.gantt-row[data-title=\"Loose end\"]').dataset.startsOn"
        f" === '{_week(2)}'"
    )
    page.keyboard.press("Control+z")
    page.keyboard.press("Control+z")
    page.wait_for_function(
        f"document.querySelector('.gantt-row[data-title=\"Loose end\"]').dataset.startsOn"
        f" === '{_week(0)}'"
    )

    # Alt+Up takes the row into the workstream above.
    row.locator(".gantt-title").click()
    page.keyboard.press("Alt+ArrowUp")
    page.locator('.gantt-group[data-group^="w"] .gantt-row[data-title="Loose end"]').wait_for()
    assert "indent" in _row(page, "Loose end").get_attribute("class")


def _status_is(page, title: str, status: str) -> None:
    page.wait_for_function(
        f"document.querySelector('.gantt-row[data-title=\"{title}\"]')"
        f".dataset.status === '{status}'"
    )


def test_a_click_steps_the_status_and_a_double_click_writes(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}/gantt")
    # The box steps it on: in progress, review, done, and round to to do.
    box = _row(page, "Loose end").locator(".gantt-check")
    for status in ("in_progress", "needs_review", "done", "todo", "in_progress"):
        box.click()
        _status_is(page, "Loose end", status)
    assert "status-in_progress" in _row(page, "Loose end").get_attribute("class")

    # Its chevron opens every status, the one it has ticked; one chosen is given.
    _row(page, "Loose end").locator("[data-status-menu]").click()
    menu = page.locator(".sheet-menu")
    assert menu.locator('[aria-checked="true"]').inner_text() == "In progress"
    assert menu.locator("[data-value]").all_inner_texts() == [
        "To do", "In progress", "Review", "Done"]
    menu.get_by_text("Done").click()
    _status_is(page, "Loose end", "done")
    menu.wait_for(state="detached")
    assert "is-done" in _row(page, "Loose end").get_attribute("class")
    # From the keyboard too, the cursor back on the box after.
    _row(page, "Loose end").locator("[data-status-menu]").click()
    page.keyboard.press("ArrowUp")
    page.keyboard.press("Enter")
    _status_is(page, "Loose end", "needs_review")
    assert page.evaluate("document.activeElement.dataset.col") == "0"
    # Undone, it is done again.
    page.keyboard.press("Control+z")
    _status_is(page, "Loose end", "done")

    _row(page, "Loose end").locator(".gantt-title").dblclick()
    field = page.locator(".gantt-input")
    field.wait_for()
    assert field.input_value() == "Loose end"
    page.keyboard.type(", tied")
    page.keyboard.press("Enter")
    _row(page, "Loose end, tied").wait_for()


def test_weeks_drill_down_to_days_and_back(page, live, project) -> None:
    with_bar = (THIS + timedelta(days=2)).isoformat()
    page.goto(f"{live}/projects/{project}/gantt")
    row = _row(page, "Loose end")
    row.locator(".gantt-start").click()
    page.keyboard.type(with_bar)
    page.keyboard.press("Enter")
    page.wait_for_function(
        f"document.querySelector('.gantt-row[data-title=\"Loose end\"]').dataset.startsOn"
        f" === '{with_bar}'"
    )
    sheet = page.locator("#gantt")
    left_day = sheet.evaluate(
        "s => s.scrollLeft / s.querySelector('.gantt-wk-head').offsetWidth * 7"
    )

    page.get_by_role("link", name="Days").click()
    page.locator('.gantt-table[data-scale="days"]').wait_for()
    assert page.get_by_role("link", name="Days").get_attribute("aria-current") == "true"
    assert page.locator(".gantt-head .gantt-length").inner_text() == "Days"
    assert "?scale=days" in page.url
    # The same days in view: the scroll is now in days.
    now_day = sheet.evaluate("s => s.scrollLeft / s.querySelector('.gantt-wk-head').offsetWidth")
    assert abs(now_day - left_day) < 1
    # A Wednesday to Friday bar, three days long.
    assert row.locator(".gantt-length").inner_text() == "3"
    assert "--n: 3.0" in row.locator(".gantt-bar").get_attribute("style")

    # Alt+Right moves it a day here.
    row.locator(".gantt-title").click()
    page.keyboard.press("Alt+ArrowRight")
    page.wait_for_function(
        f"document.querySelector('.gantt-row[data-title=\"Loose end\"]').dataset.startsOn"
        f" === '{(THIS + timedelta(days=3)).isoformat()}'"
    )

    # V, away from the sheet's cells, goes back to weeks.
    page.keyboard.press("Escape")
    page.keyboard.press("v")
    page.locator('.gantt-table[data-scale="weeks"]').wait_for()
    assert page.locator(".gantt-head .gantt-length").inner_text() == "Wks"


def test_right_from_due_lands_where_the_row_works(page, live, app_db) -> None:
    """Right from Due enters the time where the row's work is: a task's
    start (or its due), a workstream's first day, and for a task with no
    days the next workday after the dated task above it, never before today."""
    today = date.today()
    with app_db() as db:
        project = projects_svc.create_project(db, name="Gamma")
        lane = projects_svc.create_workstream(db, project_id=project.id, name="Launch")
        made = {"project_id": project.id, "workstream_id": lane.id}
        spec = {"starts_on": THIS + timedelta(days=16), "due": THIS + timedelta(days=18)}
        tasks_svc.create_task(db, title="Spec", **spec, **made)
        tasks_svc.create_task(db, title="Review", due=THIS + timedelta(days=25), **made)
        tasks_svc.create_task(db, title="Polish", **made)
        tasks_svc.create_task(db, title="Loose end", project_id=project.id)
        db.commit()
        project_id = project.id

    def lands_from_due(row) -> str:  # noqa: ANN001
        row.locator(".gantt-due").click()
        page.keyboard.press("ArrowRight")
        return page.evaluate("document.activeElement.dataset.day")

    page.goto(f"{live}/projects/{project_id}/gantt?scale=days")
    assert lands_from_due(_row(page, "Spec")) == (THIS + timedelta(days=16)).isoformat()
    assert lands_from_due(_row(page, "Review")) == (THIS + timedelta(days=25)).isoformat()
    # Review is due on a Friday: Polish follows it on the Monday.
    assert lands_from_due(_row(page, "Polish")) == (THIS + timedelta(days=28)).isoformat()
    assert lands_from_due(page.locator(".gantt-row.kind-workstream")) == (
        THIS + timedelta(days=16)
    ).isoformat()
    assert lands_from_due(_row(page, "Loose end")) == today.isoformat()
    # The day landed on is in sight, clear of the frozen pane.
    _row(page, "Polish").locator(".gantt-due").click()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.dataset.day") == (
        THIS + timedelta(days=28)
    ).isoformat()
    pane = page.locator(".gantt-head .gantt-pane").bounding_box()
    sheet = page.locator("#gantt").bounding_box()
    cell = page.locator(".gantt-cell.is-cursor").bounding_box()
    assert cell["x"] >= pane["x"] + pane["width"] - 1
    assert cell["x"] + cell["width"] <= sheet["x"] + sheet["width"] + 1


def test_ctrl_arrows_stop_at_the_edges_of_what_is_drawn(page, live, app_db) -> None:
    """Ctrl+arrow as in a spreadsheet: along a run of drawn days to its
    last, else on to the next drawn one, else to the sheet's edge; along a
    row with no days drawn on the way, today stops it."""
    day = lambda n: (THIS + timedelta(days=n - 14)).isoformat()  # noqa: E731
    today = date.today().isoformat()
    with app_db() as db:
        project = projects_svc.create_project(db, name="Delta")
        made = {"project_id": project.id}
        draft = {"starts_on": THIS - timedelta(days=12), "due": THIS - timedelta(days=10)}
        tasks_svc.create_task(db, title="Draft", **draft, **made)
        tasks_svc.create_task(db, title="Think", **made)
        tasks_svc.create_task(db, title="Check", due=THIS - timedelta(days=11), **made)
        db.commit()
        project_id = project.id

    def at() -> tuple[str, str | None]:
        return tuple(
            page.evaluate(
                "[document.activeElement.closest('.gantt-row').dataset.title,"
                " document.activeElement.dataset.day]"
            )
        )

    page.goto(f"{live}/projects/{project_id}/gantt?scale=days")
    # Into the time from Draft's Due (its bar's first day), a day on to Thursday.
    _row(page, "Draft").locator(".gantt-due").click()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    assert at() == ("Draft", day(3))
    # Down Thursday: over Think's empty day to Check's tick, then to the foot.
    page.keyboard.press("Control+ArrowDown")
    assert at() == ("Check", day(3))
    page.keyboard.press("Control+ArrowDown")
    assert page.evaluate("document.activeElement.closest('.gantt-row').dataset.key") == (
        "add"
    )
    page.keyboard.press("Control+ArrowUp")
    assert at() == ("Check", day(3))
    page.keyboard.press("Control+ArrowUp")
    assert at() == ("Draft", day(3))

    # Along Draft: to its bar's last day, over the empty days to today, the
    # sheet's end, back to the bar's last and first days, then on to its
    # Due, the words before the time.
    page.keyboard.press("Control+ArrowRight")
    assert at() == ("Draft", day(4))
    page.keyboard.press("Control+ArrowRight")
    assert at() == ("Draft", today)
    page.keyboard.press("Control+ArrowRight")
    last = _row(page, "Draft").locator(".gantt-wk").last.get_attribute("data-day")
    assert at() == ("Draft", last)
    page.keyboard.press("Control+ArrowLeft")
    assert at() == ("Draft", day(4))
    page.keyboard.press("Control+ArrowLeft")
    assert at() == ("Draft", day(2))
    page.keyboard.press("Control+ArrowLeft")
    assert page.evaluate("document.activeElement.dataset.col") == "5"  # Due

    # Think has no days: today stops it on the way in, and on the way back.
    _row(page, "Think").locator(".gantt-due").click()
    page.keyboard.press("Control+ArrowRight")
    assert at() == ("Think", today)
    page.keyboard.press("Control+ArrowRight")
    assert at() == ("Think", last)
    page.keyboard.press("Control+ArrowLeft")
    assert at() == ("Think", today)


def test_a_row_is_dragged_into_a_workstream(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}/gantt")
    grip = _row(page, "Loose end").locator("[data-row-grip]").bounding_box()
    target = page.locator('.gantt-row.kind-workstream').bounding_box()
    page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    page.mouse.down()
    page.mouse.move(grip["x"] + grip["width"] / 2, target["y"] + target["height"] * 0.75, steps=8)
    page.locator(".gantt-drop-line").wait_for()
    page.mouse.up()
    page.locator('.gantt-group[data-group^="w"] .gantt-row[data-title="Loose end"]').wait_for()
    # And back, with undo.
    page.keyboard.press("Control+z")
    page.locator('.gantt-group[data-group="other"] .gantt-row[data-title="Loose end"]').wait_for()


def test_a_workstream_is_moved_among_the_others(page, live, app_db, project) -> None:
    with app_db() as db:
        for name in ("Build", "Docs"):
            projects_svc.create_workstream(db, project_id=project, name=name)
        db.commit()
    page.goto(f"{live}/projects/{project}/gantt")

    def lanes() -> list[str]:
        return page.locator(".gantt-row.kind-workstream").evaluate_all(
            "rows => rows.map((r) => r.dataset.title)"
        )

    def until(names: list[str]) -> None:
        page.wait_for_function(
            "names => JSON.stringify([...document.querySelectorAll('.gantt-row.kind-workstream')]"
            ".map((r) => r.dataset.title)) === JSON.stringify(names)",
            arg=names,
        )

    assert lanes() == ["Launch", "Build", "Docs"]
    # Alt+Down on its row: its lane past the next, the cursor going with it.
    _row(page, "Launch").locator(".gantt-title .gantt-text").click()
    page.keyboard.press("Alt+ArrowDown")
    until(["Build", "Launch", "Docs"])
    page.keyboard.press("Alt+ArrowDown")
    until(["Build", "Docs", "Launch"])
    assert page.evaluate("document.activeElement.closest('.gantt-row').dataset.title") == "Launch"
    # The last goes no further, and leaves nothing to undo.
    page.keyboard.press("Alt+ArrowDown")
    page.keyboard.press("Control+z")
    until(["Build", "Launch", "Docs"])

    # Dragged by its number, over the top half of the first lane: first.
    grip = _row(page, "Docs").locator("[data-row-grip]").bounding_box()
    target = page.locator('.gantt-group[data-group^="w"]').first.bounding_box()
    page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    page.mouse.down()
    page.mouse.move(grip["x"] + grip["width"] / 2, target["y"] + 4, steps=8)
    page.locator(".gantt-drop-line").wait_for()
    assert "is-lifted" in page.locator('.gantt-group:has(> [data-title="Docs"])').get_attribute(
        "class"
    )
    page.mouse.up()
    until(["Docs", "Build", "Launch"])
    # Undone back where it was, last; redone; and kept.
    page.keyboard.press("Control+z")
    until(["Build", "Launch", "Docs"])
    page.keyboard.press("Control+y")
    until(["Docs", "Build", "Launch"])
    page.reload()
    assert lanes() == ["Docs", "Build", "Launch"]


def test_a_workstream_folds_to_its_row(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}/gantt")
    lane = page.locator(".gantt-row.kind-workstream")
    page.locator('.gantt-row.kind-add[data-key^="add-w"] .gantt-title').click()
    page.keyboard.type("Spec")
    page.keyboard.press("Enter")
    page.locator('.gantt-group[data-group^="w"] .gantt-row[data-title="Spec"]').wait_for()

    # Its chevron folds it: its tasks go, and its row counts them.
    lane.locator("[data-fold]").click()
    page.locator('.gantt-row[data-title="Spec"]').wait_for(state="hidden")
    assert lane.locator(".gantt-count").inner_text() == "1 task"
    # Remembered across a visit.
    page.reload()
    page.locator('.gantt-row[data-title="Spec"]').wait_for(state="hidden")
    # The keys pass over what is folded: down from the lane is the row to add
    # a workstream.
    lane.locator(".gantt-title .gantt-text").click()
    page.keyboard.press("ArrowDown")
    assert page.evaluate("document.activeElement.closest('.gantt-row').dataset.key") == (
        "add-workstream"
    )
    # Alt+Right on its row opens it, Alt+Left folds it again.
    page.keyboard.press("ArrowUp")
    page.keyboard.press("Alt+ArrowRight")
    page.locator('.gantt-row[data-title="Spec"]').wait_for()
    page.keyboard.press("Alt+ArrowLeft")
    page.locator('.gantt-row[data-title="Spec"]').wait_for(state="hidden")


def test_tasks_are_shown_by_status(page, live, app_db, project) -> None:
    with app_db() as db:
        shipped = tasks_svc.create_task(db, title="Shipped", project_id=project)
        tasks_svc.set_status(db, shipped.id, TaskStatus.done)
        started = tasks_svc.create_task(db, title="Started", project_id=project)
        tasks_svc.set_status(db, started.id, TaskStatus.in_progress)
        tasks_svc.create_task(db, title="Still open", project_id=project)
        db.commit()
    page.goto(f"{live}/projects/{project}/gantt")
    show = page.locator("[data-gantt-show]")
    assert show.inner_text() == "All tasks"

    # Done unticked in its menu hides the done task, the menu still open; the
    # cursor on it moves to the next row shown.
    _row(page, "Shipped").locator(".gantt-title .gantt-text").click()
    show.click()
    menu = page.locator(".sheet-menu")
    menu.get_by_text("Done").click()
    _row(page, "Shipped").wait_for(state="hidden")
    assert menu.locator('[data-value="done"]').get_attribute("aria-checked") == "false"
    assert show.inner_text() == "To do, In progress, Review"
    assert "is-filtered" in show.get_attribute("class")
    cursor = page.evaluate("document.querySelector('.gantt-row.has-cursor').dataset.title")
    assert cursor == "Started"
    # To do unticked too: only what is under way is left.
    menu.get_by_text("To do").click()
    _row(page, "Still open").wait_for(state="hidden")
    _row(page, "Loose end").wait_for(state="hidden")
    assert _row(page, "Started").is_visible()
    page.keyboard.press("Escape")
    menu.wait_for(state="detached")

    # The keys pass over the hidden, and they stay hidden across a visit.
    page.reload()
    _row(page, "Shipped").wait_for(state="hidden")
    assert show.inner_text() == "In progress, Review"
    _row(page, "Started").locator(".gantt-title .gantt-text").click()
    page.keyboard.press("ArrowUp")
    focused = page.evaluate("document.activeElement.closest('.gantt-row').dataset.key")
    assert focused == "add-workstream"  # over the hidden, to the row above them
    # A task stepped on to done hides; the last status shown cannot go.
    for _ in range(2):
        _row(page, "Started").locator(".gantt-check").click()
    _row(page, "Started").wait_for(state="hidden")
    show.click()
    menu.get_by_text("In progress").click()
    menu.get_by_text("Review").click()
    assert menu.locator('[aria-checked="true"]').all_inner_texts() == ["Review"]
    # Every status ticked again, every task is back.
    for status in ("To do", "In progress", "Done"):
        menu.get_by_text(status).click()
    for title in ("Loose end", "Shipped", "Started", "Still open"):
        _row(page, title).wait_for()
    assert show.inner_text() == "All tasks"


def test_a_task_is_deleted_from_its_bin_or_with_delete(page, live, app_db, project) -> None:
    with app_db() as db:
        tasks_svc.create_task(db, title="Spare", project_id=project)
        db.commit()
    page.goto(f"{live}/projects/{project}/gantt")
    loose = _row(page, "Loose end")
    dialog = page.locator("#confirm-dialog")
    # Its bin asks first; Cancel keeps it.
    loose.hover()
    loose.locator(".gantt-delete").click()
    assert dialog.locator(".confirm-name").inner_text() == "Loose end"
    dialog.get_by_role("button", name="Cancel").click()
    with app_db() as db:
        assert db.query(Task).filter_by(project_id=project).count() == 2
    loose.hover()
    loose.locator(".gantt-delete").click()
    dialog.get_by_role("button", name="Delete").click()
    loose.wait_for(state="detached")
    # Delete on Task deletes the task there, after asking; on its time it clears.
    _row(page, "Spare").locator(".gantt-title .gantt-text").click()
    page.keyboard.press("Delete")
    assert dialog.locator(".confirm-name").inner_text() == "Spare"
    dialog.get_by_role("button", name="Delete").click()
    _row(page, "Spare").wait_for(state="detached")
    with app_db() as db:
        assert db.query(Task).filter_by(project_id=project).count() == 0


def test_a_title_being_written_grows_its_row_to_show_every_word(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}/gantt")
    row = _row(page, "Loose end")
    line = row.bounding_box()["height"]
    row.locator(".gantt-title").dblclick()
    tail = ", and the many other loose ends that turned up while tying it"
    page.keyboard.type(tail)
    field = page.locator(".gantt-input")
    # Wrapped, not scrolled: the box is as tall as its words, the row with it.
    assert field.evaluate("el => el.scrollHeight <= el.clientHeight")
    assert row.bounding_box()["height"] > line
    page.keyboard.press("Enter")
    written = _row(page, f"Loose end{tail}")
    written.wait_for()
    assert page.locator(".gantt-input").count() == 0
    assert written.bounding_box()["height"] == line


def test_a_task_opens_on_its_page_and_comes_back(page, live, app_db, project) -> None:
    with app_db() as db:
        loose = db.query(Task).filter_by(title="Loose end").one().id
    page.goto(f"{live}/projects/{project}/gantt")
    row = _row(page, "Loose end")
    # Quiet until its row is hovered, as its bin is.
    assert row.locator(".gantt-open").evaluate("el => getComputedStyle(el).opacity") == "0"
    row.hover()
    row.locator(".gantt-open").click()
    page.wait_for_url(f"{live}/tasks/{loose}")
    back = page.locator(".page-back")
    assert back.inner_text() == "Gantt"
    back.click()
    page.wait_for_url(f"{live}/projects/{project}/gantt")
    # Ctrl+Enter opens the cursor's task, from any of its row's cells.
    _row(page, "Loose end").locator(".gantt-due").click()
    page.keyboard.press("Control+Enter")
    page.wait_for_url(f"{live}/tasks/{loose}")


def test_alt_w_writes_a_new_workstream_from_anywhere_on_the_page(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}/gantt")
    # From a task's cell in the sheet, where plain letters are written.
    _row(page, "Loose end").locator(".gantt-title .gantt-text").click()
    page.keyboard.press("Alt+w")
    assert page.locator(".gantt-row.kind-add-workstream .gantt-input").is_visible()
    page.keyboard.type("Polish")
    page.keyboard.press("Enter")
    page.locator('.gantt-row.kind-workstream[data-title="Polish"]').wait_for()
    # And from outside it.
    page.locator("h1").click()
    page.keyboard.press("Alt+w")
    assert page.locator(".gantt-row.kind-add-workstream .gantt-input").is_visible()
    page.keyboard.press("Escape")
    assert page.locator(".gantt-input").count() == 0
