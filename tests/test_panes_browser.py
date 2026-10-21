"""Moving between panes by Ctrl+Alt+arrows, in a real browser: on Today,
from the notes' editor and back to their caret, down a column, back to the
pane of a column it was in last, out to the sidebar; on a task's page,
between its map, the task and the sidebar's pane; into the agent window
and out; the keys as chosen in keys.toml, and Keyboard's page recording
them. The `live`, `page`, `app_db` and `keys_file` fixtures are
conftest.py's."""

import pytest

from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

PANE = """() => {
  const pane = document.activeElement.closest('[data-nav-pane]');
  if (!pane) return null;
  return pane.closest('[data-pane]')?.dataset.pane || pane.id || pane.className.split(' ')[0];
}"""


def at(page) -> str | None:
    """The pane the focus is in: a Today pane's name, else its id or class."""
    return page.evaluate(PANE)


def notes(page):
    return page.locator(".notes-pane .cm-content")


def test_today_moves_between_its_panes_and_back_to_where_it_was(page, live) -> None:
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    notes(page).click()
    page.keyboard.type("hello")

    page.keyboard.press("Control+Alt+ArrowRight")
    assert at(page) == "timeline"
    page.keyboard.press("Control+Alt+ArrowLeft")
    assert at(page) == "notes"
    # The pane's edge is lit, a moment.
    assert page.locator(".notes-pane.is-lit").count() == 1
    # Back at the caret: the words go on where they stopped.
    page.keyboard.type(" world")
    assert notes(page).inner_text().startswith("hello world")

    # Left of the notes, the column's top pane; then down it.
    page.keyboard.press("Control+Alt+ArrowLeft")
    assert at(page) == "plan"
    page.keyboard.press("Control+Alt+ArrowDown")
    assert at(page) == "habits"
    # Its first control, never its grip or its eye.
    assert page.evaluate("document.activeElement.matches('.habit-new-open')")
    page.keyboard.press("Control+Alt+ArrowDown")
    assert at(page) == "stay"
    page.keyboard.press("Control+Alt+ArrowDown")
    assert at(page) == "stay"  # nothing below: it stays

    # From the notes, back to the pane of the column it was in last.
    page.keyboard.press("Control+Alt+ArrowRight")
    assert at(page) == "notes"
    page.keyboard.press("Control+Alt+ArrowLeft")
    assert at(page) == "stay"

    # Further left, the sidebar, at the page showing.
    page.keyboard.press("Control+Alt+ArrowLeft")
    assert at(page) == "rail"
    assert page.evaluate("document.activeElement.matches('.nav a[aria-current]')")
    assert page.locator(".nav a[aria-current]").text_content().strip().endswith("Today")


def test_a_pane_with_no_control_takes_the_focus_itself(page, live) -> None:
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    notes(page).click()
    page.keyboard.press("Control+Alt+ArrowLeft")
    # Nothing planned: the plan pane itself, ringed (and not lit as well,
    # nor once the focus has gone on).
    assert page.evaluate("document.activeElement.id") == "today-plan"
    assert page.evaluate("document.activeElement.matches(':focus-visible')")
    assert not page.locator("#today-plan.is-lit").count()
    page.keyboard.press("Control+Alt+ArrowRight")
    assert not page.locator("#today-plan.is-lit").count()


def test_a_tasks_page_moves_between_its_map_the_task_and_the_sidebar(page, live, app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Everyday")
        task = tasks_svc.create_task(
            db, title="Ship the release", project_id=project.id, notes="Write it\n\n# Plan\n"
        )
        tasks_svc.create_task(db, title="Another one", project_id=project.id)
        db.commit()
        task_id = task.id
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/tasks/{task_id}")
    page.locator("#side-tab-outline").click()
    page.locator("#side-outline [data-line]").wait_for()

    page.locator(".task-doc .cm-content").click()
    page.keyboard.press("Control+Alt+ArrowLeft")
    assert at(page) == "task-map"
    # The task itself, where the map marks it.
    assert page.evaluate("document.activeElement.matches('.map-row.is-here')")
    page.keyboard.press("Control+Alt+ArrowRight")
    assert at(page) == "task-doc"
    page.keyboard.press("Control+Alt+ArrowRight")
    assert at(page) == "side-outline"
    page.keyboard.press("Control+Alt+ArrowLeft")
    assert at(page) == "task-doc"
    assert page.evaluate("document.activeElement.matches('.cm-content')")


def test_the_agent_window_is_a_pane_beside_any_page(page, live) -> None:
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/calendar")
    page.evaluate("document.activeElement?.blur()")
    page.keyboard.press("a")
    page.locator("#agent-panel textarea").wait_for()
    page.wait_for_function("document.activeElement.matches('#agent-panel textarea')")

    page.keyboard.press("Control+Alt+ArrowLeft")
    assert at(page) == "main"
    page.keyboard.press("Control+Alt+ArrowRight")
    assert page.evaluate("document.activeElement.matches('#agent-panel textarea')")

    # Collapsed, it is no pane to go to.
    page.keyboard.press("Escape")
    page.keyboard.press("a")
    page.wait_for_function("document.documentElement.dataset.agent !== 'open'")
    page.locator(".main").click(position={"x": 5, "y": 5})
    page.keyboard.press("Control+Alt+ArrowRight")
    assert at(page) != "agent-panel"


def test_the_keys_as_chosen_and_recorded(page, live, keys_file) -> None:
    keys_file.write_text('[keys]\n"pane.left" = "Alt+Shift+H"\n', encoding="utf-8")
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    notes(page).click()
    page.keyboard.press("Control+Alt+ArrowLeft")
    assert at(page) == "notes"
    page.keyboard.press("Alt+Shift+H")
    assert at(page) == "plan"

    # While Keyboard records a key, the pane keys are only that key.
    page.goto(f"{live}/keys")
    row = page.locator('[data-action="app.theme"]')
    row.locator("[data-record]").click()
    page.keyboard.press("Control+Alt+ArrowDown")
    page.locator('[data-action="app.theme"] [data-remove="Ctrl+Alt+ArrowDown"]').wait_for()
