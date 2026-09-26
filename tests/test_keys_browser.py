"""Tasks from the keyboard alone, in a real browser: the cursor, every key
that acts on it, writing and coming back, and the keys that work anywhere.
The `live` and `page` fixtures are conftest.py's."""

from datetime import date, timedelta

import pytest

from app.models import ProjectStatus, TaskOwner, TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()

# Where the cursor is: the focused row's title, "Done" for a fold's header.
CURSOR = """(() => {
  const a = document.activeElement;
  if (a?.matches('.task-row')) return a.dataset.taskTitle;
  if (a?.matches('.done-fold > summary')) return 'Done';
  if (a?.matches('.project-shelf > summary')) return a.childNodes[0].textContent.trim();
  return null;
})()"""

# The cursor's path, in order: rows and fold headers the eye can see.
STOPS = """[...document.querySelectorAll([
    '[data-cursor] .task-row[tabindex]',
    '[data-cursor] .done-fold > summary',
    '[data-cursor] .project-shelf > summary',
  ].join(', '))]
  .filter((e) => e.checkVisibility())
  .map((e) => e.dataset.taskTitle
    || (e.closest('.done-fold') ? 'Done' : e.childNodes[0].textContent.trim()))"""

# The task rows alone, in the cursor's order.
ROWS = """[...document.querySelectorAll('[data-cursor] .task-row[tabindex]')]
  .filter((e) => e.checkVisibility()).map((e) => e.dataset.taskTitle)"""


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
    rows = page.evaluate(ROWS)
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
    # Swapped-in content is live at once (base.html's htmx-config), which the
    # cursor, the sheet and the lists' refreshes all rely on.
    assert page.evaluate("htmx.config.defaultSettleDelay") == 0
    press(page, "?")
    page.locator("#keys-dialog[open]").wait_for()
    press(page, "Escape")
    page.locator("#keys-dialog[open]").wait_for(state="detached")
    press(page, "2")
    page.wait_for_url("**/today")
    press(page, "5")
    page.wait_for_url("**/projects")


def fixed_clock(monkeypatch, hour: int) -> None:
    """Pin the fragment endpoints' clock (the live server runs in this process)."""
    import datetime as dt

    import app.ui.fragments as fragments

    moment = dt.datetime.combine(TODAY, dt.time(hour))

    class Fixed(dt.datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return moment

    monkeypatch.setattr(fragments, "datetime", Fixed)


def test_today_from_the_keyboard(page, live, app_db, monkeypatch) -> None:
    fixed_clock(monkeypatch, 10)
    with app_db() as db:
        first = tasks_svc.create_task(db, title="Golf", planned_for=TODAY)
        tasks_svc.create_task(db, title="Hotel", planned_for=TODAY)
        claude = tasks_svc.create_task(db, title="India", planned_for=TODAY, owner=TaskOwner.claude)
        db.commit()
        first_id, claude_id = first.id, claude.id
    page.goto(f"{live}/today")

    # The cursor runs through Today's list into Claude's section.
    press(page, "j")
    cursor_on(page, "Golf")
    press(page, "End")
    cursor_on(page, "India")

    # B: the next free hour, and on to the next row.
    press(page, "Home")
    cursor_on(page, "Golf")
    press(page, "b")
    page.locator(".cal-toast.show", has_text="Booked 10:00–11:00: Golf").wait_for()
    cursor_on(page, "Hotel")
    with app_db() as db:
        blocks = tasks_svc.get_task(db, first_id).blocks
        assert [(b.start.hour, b.end.hour) for b in blocks] == [(10, 11)]

    # M moves Claude's task to tomorrow from here too (no do-date buttons on Today).
    press(page, "End", "m")
    page.wait_for_function(f"{CURSOR} !== 'India'", timeout=5000)
    with app_db() as db:
        assert tasks_svc.get_task(db, claude_id).planned_for == TODAY + timedelta(days=1)

    # N writes at the end of Today's notebook.
    press(page, "n")
    page.keyboard.type("Juliet")
    press(page, "Control+Enter")
    page.locator("#notebook .task-row", has_text="Juliet").wait_for()


def test_projects_from_the_keyboard(page, live, app_db) -> None:
    with app_db() as db:
        health = projects_svc.create_project(db, name="Health")
        home = projects_svc.create_project(db, name="Home")
        shelved = projects_svc.create_project(db, name="Japanese")
        tasks_svc.create_task(db, title="Kilo", project_id=health.id)
        tasks_svc.create_task(db, title="Lima", project_id=home.id)
        tasks_svc.create_task(db, title="Mike", project_id=shelved.id)
        shelved.status = ProjectStatus.paused
        db.commit()
        home_id = home.id
    page.goto(f"{live}/projects")

    press(page, "j")
    cursor_on(page, "Kilo")
    press(page, "Shift+J")  # the next project
    cursor_on(page, "Lima")

    # N writes into the cursor's project.
    press(page, "n")
    page.keyboard.type("November")
    press(page, "Control+Enter")
    page.locator(f"#project-{home_id} .task-row", has_text="November").wait_for()
    press(page, "Escape")
    cursor_on(page, "November")

    # The Paused shelf is a stop; Space opens it and its tasks join the path.
    press(page, "End")
    cursor_on(page, "Paused")
    press(page, "Space", "j")
    cursor_on(page, "Mike")
    after = following(page)
    press(page, "t")
    # The cursor moves on once the list has refreshed around the change, and
    # the shelf it was in stays open through that refresh.
    cursor_on(page, after)
    assert page.evaluate("document.querySelector('#shelf-paused').open")
    with app_db() as db:
        mike = next(t for t in tasks_svc.list_tasks(db) if t.title == "Mike")
        assert mike.planned_for == TODAY


def test_shift_n_writes_a_new_task_from_any_page(page, live, app_db, tasks) -> None:
    # On a list page, into the page's own composer.
    page.goto(live)
    press(page, "Shift+N")
    page.wait_for_function("document.activeElement.matches('.capture .sheet-title')", timeout=5000)
    press(page, "Escape")

    # On Weeks, a window: typed words work, the page says where each task
    # went, and the window stays for the next one until Esc.
    page.goto(f"{live}/weeks")
    press(page, "Shift+N")
    page.locator("#capture-dialog[open]").wait_for()
    page.keyboard.type("Quebec tomorrow ")
    press(page, "Control+Enter")
    page.locator(".cal-toast.show", has_text="Added “Quebec” for tomorrow").wait_for()
    assert page.evaluate("document.activeElement.matches('#capture-dialog .sheet-title')")
    page.keyboard.type("Romeo")
    press(page, "Control+Enter")
    page.locator(".cal-toast.show", has_text="Added “Romeo” to No date").wait_for()
    press(page, "Escape")
    page.locator("#capture-dialog[open]").wait_for(state="detached")
    # Weeks' Unplanned tray caught up with the undated one.
    page.locator(".tray", has_text="Romeo").wait_for()

    # On Calendar, plain N too.
    page.goto(f"{live}/calendar")
    press(page, "n")
    page.locator("#capture-dialog[open]").wait_for()

    with app_db() as db:
        by_title = {t.title: t for t in tasks_svc.list_tasks(db)}
        assert by_title["Quebec"].planned_for == TODAY + timedelta(days=1)
        assert by_title["Romeo"].planned_for is None


def test_an_add_racing_a_list_refresh_lands_once(page, live, app_db) -> None:
    """A refresh fetched just before an add lands just after it: the new task
    shows once, in the notebook it was written in, and nowhere else."""
    page.goto(f"{live}/today")
    press(page, "n")
    page.keyboard.type("Kilo")
    # The refresh goes out first, then the add, in one tick.
    page.evaluate("""() => {
      htmx.trigger(document.body, 'tasks:changed');
      document.querySelector('#notebook .nb-draft .task-sheet').requestSubmit();
    }""")
    page.locator("#notebook .task-row", has_text="Kilo").wait_for(timeout=5000)
    page.wait_for_timeout(300)  # any second refresh has landed too
    assert page.locator(".task-row", has_text="Kilo").count() == 1
    assert page.locator("#notebook .nb-draft").count() == 0
    with app_db() as db:
        assert [t.title for t in tasks_svc.list_tasks(db)].count("Kilo") == 1
