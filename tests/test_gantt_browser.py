"""A project's Gantt in a real browser, worked as a spreadsheet: writing a
task and its weeks from the keyboard, a refused week, drawing and dragging
bars, Alt moves, rows moved into a milestone, and undo. The `live`, `page`
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
        projects_svc.create_milestone(db, project_id=project.id, name="Launch")
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
    page.locator('.gantt-row.kind-add[data-key^="add-m"] .gantt-title').click()
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
        "document.querySelector('.gantt-row[data-title=\"Write the spec\"] .gantt-wks')"
        ".textContent.trim() === '3'"
    )
    assert _span(page, "Write the spec")[0] == _week(1)
    bar = _row(page, "Write the spec").locator(".gantt-bar")
    assert bar.get_attribute("style") == "--s: 2; --n: 3"  # the sheet opens a week back

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
    start = row.locator(f'.gantt-wk[data-week="{_week(0)}"]').bounding_box()
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

    # Alt+Up takes the row into the milestone above.
    row.locator(".gantt-title").click()
    page.keyboard.press("Alt+ArrowUp")
    page.locator('.gantt-group[data-group^="m"] .gantt-row[data-title="Loose end"]').wait_for()
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
