"""Tasks from the keyboard alone, in a real browser: the cursor, every key
that acts on it, writing and coming back, and the keys that work anywhere.
The `live` and `page` fixtures are conftest.py's."""

from datetime import date, timedelta

import pytest

from app.models import TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()

# Where the cursor is: the focused row's title, "Done" for a fold's header.
CURSOR = """(() => {
  const a = document.activeElement;
  if (a?.matches('.task-row')) return a.dataset.taskTitle;
  if (a?.matches('.done-fold > summary')) return 'Done';
  return null;
})()"""

# The cursor's path, in order: rows and fold headers the eye can see.
STOPS = """[...document.querySelectorAll(
  '#task-groups .task-row[tabindex], #task-groups .done-fold > summary')]
  .filter((e) => e.checkVisibility())
  .map((e) => e.dataset.taskTitle || 'Done')"""


@pytest.fixture
def tasks(app_db) -> dict[str, int]:
    with app_db() as db:
        home = projects_svc.create_project(db, name="Home")
        projects_svc.create_milestone(db, project_id=home.id, name="Garden")
        made = {
            "a": tasks_svc.create_task(db, title="Alpha"),
            "b": tasks_svc.create_task(db, title="Bravo"),
            "c": tasks_svc.create_task(db, title="Charlie", planned_for=TODAY),
            "d": tasks_svc.create_task(db, title="Delta", planned_for=TODAY + timedelta(days=1)),
            "e": tasks_svc.create_task(db, title="Echo", planned_for=TODAY),
        }
        tasks_svc.set_status(db, made["e"].id, TaskStatus.done)
        db.commit()
        return {k: t.id for k, t in made.items()}


def press(page, *keys: str) -> None:
    for key in keys:
        page.keyboard.press(key)


def cursor_on(page, title: str) -> None:
    page.wait_for_function(f"{CURSOR} === {title!r}", timeout=5000)


def cursor(page) -> str:
    return page.evaluate(CURSOR)


def following(page) -> str:
    """The row after the cursor's (or before it, at the end): where it goes
    once its row is dated, filed, finished or deleted away."""
    rows = [s for s in page.evaluate(STOPS) if s != "Done"]
    at = rows.index(cursor(page))
    return rows[at + 1] if at + 1 < len(rows) else rows[at - 1]


def test_the_cursor_moves_by_row_and_by_group(page, live, tasks) -> None:
    page.goto(live)
    stops = page.evaluate(STOPS)  # No date (two), Today, Tomorrow, then Done
    press(page, "j")
    cursor_on(page, stops[0])
    press(page, "j")
    cursor_on(page, stops[1])
    press(page, "Shift+J")  # No date -> Today
    cursor_on(page, "Charlie")
    press(page, "Shift+K")  # back to No date's first row
    cursor_on(page, stops[0])
    press(page, "End")
    cursor_on(page, "Done")
    press(page, "Space", "j")  # Space opens the fold; its rows join the path
    cursor_on(page, "Echo")
    press(page, "Home")
    cursor_on(page, stops[0])


def test_keys_act_on_the_row_and_the_cursor_moves_on(page, live, app_db, tasks) -> None:
    page.goto(live)
    press(page, "j")
    cursor_on(page, page.evaluate(STOPS)[0])

    first, after = cursor(page), following(page)
    press(page, "t")  # to today
    cursor_on(page, after)

    dated, after = cursor(page), following(page)
    press(page, "d")  # the day menu: Today, Tomorrow, ...
    page.locator(".sheet-menu").wait_for()
    press(page, "ArrowDown", "Enter")
    cursor_on(page, after)

    filed, after = cursor(page), following(page)
    press(page, "p")  # No project, Home, Garden
    page.locator(".sheet-menu").wait_for()
    press(page, "ArrowDown", "ArrowDown", "Enter")
    cursor_on(page, after)

    finished, after = cursor(page), following(page)
    press(page, "x")
    cursor_on(page, after)

    with app_db() as db:
        by_title = {t.title: t for t in tasks_svc.list_tasks(db)}
        assert by_title[first].planned_for == TODAY
        assert by_title[dated].planned_for == TODAY + timedelta(days=1)
        assert by_title[filed].milestone is not None and by_title[filed].milestone.name == "Garden"
        assert by_title[finished].status == TaskStatus.done


def test_writing_and_coming_back_to_the_list(page, live, app_db, tasks) -> None:
    page.goto(live)
    # N: a new task; Esc lands the cursor on it.
    press(page, "j", "n")
    page.keyboard.type("Foxtrot")
    press(page, "Control+Enter")
    page.locator(".task-row", has_text="Foxtrot").wait_for()
    press(page, "Escape")
    cursor_on(page, "Foxtrot")

    # E: edit; Esc saves and stays on the task.
    press(page, "e")
    page.locator(".task-sheet[data-sheet=edit][data-ready]").wait_for()
    page.keyboard.type(" soon")
    press(page, "Escape")
    cursor_on(page, "Foxtrot soon")

    # Delete asks: Esc cancels and stays; a confirmed delete moves on.
    press(page, "Delete")
    page.locator("#confirm-dialog[open]").wait_for()
    press(page, "Escape")
    cursor_on(page, "Foxtrot soon")
    after = following(page)
    press(page, "Delete")
    page.locator("#confirm-dialog[open]").wait_for()
    press(page, "Tab", "Enter")
    cursor_on(page, after)
    with app_db() as db:
        assert not [t for t in tasks_svc.list_tasks(db) if t.title.startswith("Foxtrot")]


def test_v_switches_the_view_and_keeps_the_cursor(page, live, tasks) -> None:
    page.goto(live)
    press(page, "j", "j")
    on = cursor(page)
    press(page, "v")
    page.wait_for_url("**/?view=project")
    cursor_on(page, on)


def test_keys_that_work_anywhere(page, live, tasks) -> None:
    page.goto(live)
    press(page, "?")
    page.locator("#keys-dialog[open]").wait_for()
    press(page, "Escape")
    page.locator("#keys-dialog[open]").wait_for(state="detached")
    press(page, "2")
    page.wait_for_url("**/today")
    press(page, "5")
    page.wait_for_url("**/projects")
