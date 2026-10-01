"""A project's Gantt in a real browser, worked as a spreadsheet: writing a
task and its weeks from the keyboard, a refused week, drawing and dragging
bars, Alt moves, rows moved into a workstream, and undo. The `live`, `page`
and `app_db` fixtures are conftest.py's."""

from datetime import date, timedelta

import pytest

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
    page.goto(f"{live}/projects/{project}")
    page.locator('.gantt-row.kind-add[data-key^="add-w"] .gantt-title').click()
    page.keyboard.type("Write the spec")
    page.keyboard.press("Tab")
    _row(page, "Write the spec").wait_for()
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
    page.goto(f"{live}/projects/{project}")
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


def test_a_click_ticks_and_a_double_click_writes(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}")
    _row(page, "Loose end").locator(".gantt-box").click()
    page.wait_for_function(
        "document.querySelector('.gantt-row[data-title=\"Loose end\"]').dataset.status === 'done'"
    )
    assert "is-done" in _row(page, "Loose end").get_attribute("class")

    _row(page, "Loose end").locator(".gantt-title").dblclick()
    field = page.locator(".gantt-input")
    field.wait_for()
    assert field.input_value() == "Loose end"
    page.keyboard.type(", tied")
    page.keyboard.press("Enter")
    _row(page, "Loose end, tied").wait_for()


def test_weeks_drill_down_to_days_and_back(page, live, project) -> None:
    with_bar = (THIS + timedelta(days=2)).isoformat()
    page.goto(f"{live}/projects/{project}")
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

    page.goto(f"{live}/projects/{project_id}?scale=days")
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


def test_a_row_is_dragged_into_a_workstream(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}")
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


def test_a_workstream_folds_to_its_row(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}")
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
    # The keys pass over what is folded: down from the lane is Other tasks.
    lane.locator(".gantt-title .gantt-text").click()
    page.keyboard.press("ArrowDown")
    assert page.evaluate("document.activeElement.closest('.gantt-row').dataset.key") == "other"
    # Alt+Right on its row opens it, Alt+Left folds it again.
    page.keyboard.press("ArrowUp")
    page.keyboard.press("Alt+ArrowRight")
    page.locator('.gantt-row[data-title="Spec"]').wait_for()
    page.keyboard.press("Alt+ArrowLeft")
    page.locator('.gantt-row[data-title="Spec"]').wait_for(state="hidden")
