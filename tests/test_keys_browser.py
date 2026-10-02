"""Projects' list from the keyboard alone, in a real browser: the cursor,
every key that acts on it, writing and coming back, and the keys that work
anywhere.
The `live` and `page` fixtures are conftest.py's."""

from datetime import date, timedelta

import pytest

from app.models import ProjectStatus, TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()

# Where the cursor is: the focused row's title, a fold's name for its header
# ("Done", or a shelf's "Paused").
CURSOR = """(() => {
  const a = document.activeElement;
  if (a?.matches('.task-row')) return a.dataset.taskTitle;
  if (a?.matches('.done-fold > summary')) return a.textContent.trim().split(/\\s/)[0];
  if (a?.matches('[data-project-fold]')) {
    return a.closest('.project-card').querySelector('.project-name').textContent;
  }
  return null;
})()"""

# The cursor's path, in order: rows and fold headers the eye can see.
STOPS = """[...document.querySelectorAll([
    '[data-cursor] .task-row[tabindex]',
    '[data-cursor] .done-fold > summary',
    '[data-cursor] .project-card.folded [data-project-fold]',
  ].join(', '))]
  .filter((e) => e.checkVisibility())
  .map((e) => e.dataset.taskTitle
    || (e.matches('[data-project-fold]')
      && e.closest('.project-card').querySelector('.project-name').textContent)
    || e.textContent.trim().split(/\\s/)[0])"""

# The task rows alone, in the cursor's order.
ROWS = """[...document.querySelectorAll('[data-cursor] .task-row[tabindex]')]
  .filter((e) => e.checkVisibility()).map((e) => e.dataset.taskTitle)"""


@pytest.fixture
def tasks(app_db) -> dict[str, int]:
    with app_db() as db:
        home = projects_svc.create_project(db, name="Home")
        projects_svc.create_workstream(db, project_id=home.id, name="Garden")
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


# A list being re-rendered: the page's keys wait for it, and so do these
# tests before reading its rows (a change re-renders a list twice).
BUSY = "!!document.querySelector(\"[hx-trigger*='tasks:changed'].htmx-request\")"


def cursor_on(page, title: str) -> None:
    page.wait_for_function(f"{CURSOR} === {title!r} && !{BUSY}", timeout=5000)


def cursor(page) -> str:
    return page.evaluate(CURSOR)


def following(page) -> str:
    """The row after the cursor's (or before it, at the end): where it goes
    once its row is dated, filed, finished or deleted away."""
    rows = page.evaluate(ROWS)
    at = rows.index(cursor(page))
    return rows[at + 1] if at + 1 < len(rows) else rows[at - 1]


def test_the_cursor_moves_by_row_and_by_group(page, live, tasks) -> None:
    page.goto(f"{live}/projects")
    # No project's rows, soonest first (Home has none), then Done.
    assert page.evaluate(STOPS) == ["Charlie", "Delta", "Alpha", "Bravo", "Done"]
    press(page, "j")
    cursor_on(page, "Charlie")
    press(page, "j")
    cursor_on(page, "Delta")
    press(page, "Shift+J")  # No project -> Done
    cursor_on(page, "Done")
    press(page, "Shift+K")  # back to No project's first row
    cursor_on(page, "Charlie")
    press(page, "End")
    cursor_on(page, "Done")
    press(page, "Space", "j")  # Space opens the fold; its rows join the path
    cursor_on(page, "Echo")
    press(page, "Home")
    cursor_on(page, "Charlie")


def test_keys_act_on_the_row_and_the_cursor_moves_on(page, live, app_db, tasks) -> None:
    page.goto(f"{live}/projects")
    page.locator('.task-row[data-task-title="Alpha"]').focus()  # an undated one
    cursor_on(page, "Alpha")

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
        assert by_title[filed].workstream and by_title[filed].workstream.name == "Garden"
        assert by_title[finished].status == TaskStatus.done


def test_writing_and_coming_back_to_the_list(page, live, app_db, tasks) -> None:
    page.goto(f"{live}/projects")
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


def test_keys_that_work_anywhere(page, live, tasks) -> None:
    page.goto(f"{live}/projects")
    # Swapped-in content is live at once (base.html's htmx-config), which the
    # cursor, the sheet and the lists' refreshes all rely on.
    assert page.evaluate("htmx.config.defaultSettleDelay") == 0
    press(page, "?")
    page.locator("#keys-dialog[open]").wait_for()
    press(page, "Escape")
    page.locator("#keys-dialog[open]").wait_for(state="detached")
    press(page, "1")
    page.wait_for_url("**/today")
    press(page, "3")
    page.wait_for_url("**/projects")


def test_today_from_the_keyboard(page, live, app_db) -> None:
    page.goto(f"{live}/today")

    # N writes a task in the capture window: Today has only its notes.
    press(page, "n")
    page.locator("#capture-dialog[open]").wait_for()
    page.keyboard.type("Juliet")
    press(page, "Control+Enter")
    page.locator(".cal-toast.show", has_text="Juliet").wait_for()
    press(page, "Escape")
    with app_db() as db:
        assert [t.title for t in tasks_svc.list_tasks(db)] == ["Juliet"]

    # Left and Right, outside the notes, go a day back or on.
    press(page, "ArrowLeft")
    page.wait_for_url(f"**/day/{(TODAY - timedelta(days=1)).isoformat()}")
    press(page, "ArrowRight")
    page.wait_for_url("**/today")


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


def test_folding_projects(page, live, app_db) -> None:
    """A project folds to its header, by its chevron or by Left on one of its
    rows; it stays folded through a refresh and a reload; Right unfolds it."""
    with app_db() as db:
        health = projects_svc.create_project(db, name="Health")
        home = projects_svc.create_project(db, name="Home")
        tasks_svc.create_task(db, title="Kilo", project_id=health.id)
        tasks_svc.create_task(db, title="Lima", project_id=home.id)
        tasks_svc.create_task(db, title="Mike", project_id=home.id)
        db.commit()
        health_id, home_id = health.id, home.id
    page.goto(f"{live}/projects")
    folded = "(id) => document.querySelector(`#project-${id}`).classList.contains('folded')"

    def saved(project_id: int, shut: bool) -> None:
        """The fold reached the project (it is saved behind the page's own)."""
        for _ in range(100):
            with app_db() as db:
                if projects_svc.get_project(db, project_id).folded == shut:
                    return
            page.wait_for_timeout(20)
        raise AssertionError(f"project {project_id} not saved folded={shut}")

    # The chevron folds Health: its rows leave the cursor's path.
    page.click(f"#project-{health_id} [data-project-fold]")
    assert page.evaluate(folded, health_id)
    assert page.evaluate(ROWS) == ["Lima", "Mike"]
    saved(health_id, True)

    # Left on a Home row folds Home, the cursor on its header; a list
    # refresh and a reload keep both folded.
    press(page, "Home")
    cursor_on(page, "Health")
    press(page, "j")
    cursor_on(page, "Lima")
    press(page, "ArrowLeft")
    cursor_on(page, "Home")
    assert page.evaluate(folded, home_id)
    saved(home_id, True)
    page.evaluate("htmx.trigger(document.body, 'tasks:changed')")
    page.wait_for_function(f"!{BUSY}")
    assert page.evaluate(folded, home_id) and page.evaluate(folded, health_id)
    page.reload()
    assert page.evaluate(folded, home_id) and page.evaluate(folded, health_id)
    assert page.evaluate(STOPS) == ["Health", "Home"]

    # Right unfolds Home onto its first row; Alt+click unfolds every project.
    press(page, "End")
    cursor_on(page, "Home")
    press(page, "ArrowRight")
    cursor_on(page, "Lima")
    assert not page.evaluate(folded, home_id)
    page.click(f"#project-{home_id} [data-project-fold]", modifiers=["Alt"])
    assert page.evaluate(folded, home_id) and page.evaluate(folded, health_id)
    page.click(f"#project-{home_id} [data-project-fold]", modifiers=["Alt"])
    assert page.evaluate(ROWS) == ["Kilo", "Lima", "Mike"]
    saved(health_id, False)
    saved(home_id, False)


def test_shift_n_writes_a_new_task_from_any_page(page, live, app_db, tasks) -> None:
    # On Projects, into the page's own composer.
    page.goto(f"{live}/projects")
    press(page, "Shift+N")
    page.wait_for_function("document.activeElement.matches('.capture .sheet-title')", timeout=5000)
    press(page, "Escape")

    # On Today, a window: typed words work, the page says where each task
    # went, and the window stays for the next one until Esc.
    page.goto(f"{live}/today")
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
    still shows, and its words do not come back as a draft to add again."""
    page.goto(f"{live}/projects")
    press(page, "n")
    page.keyboard.type("Kilo")
    # The refresh goes out first, then the add, in one tick.
    page.evaluate("""() => {
      htmx.trigger(document.body, 'tasks:changed');
      document.querySelector('.capture .task-sheet').requestSubmit();
    }""")
    page.locator("#loose-list .task-row", has_text="Kilo").wait_for(timeout=5000)
    page.wait_for_timeout(300)  # any second refresh has landed too
    assert page.locator("#loose-list .task-row", has_text="Kilo").count() == 1
    assert page.locator(".capture .task-sheet .sheet-title").text_content() == ""
    with app_db() as db:
        assert [t.title for t in tasks_svc.list_tasks(db)].count("Kilo") == 1


def test_a_key_racing_a_list_refresh_still_opens_its_row(page, live, app_db, tasks) -> None:
    """A row's key pressed while its list is re-rendering still acts on it:
    P opens the row's sheet on its project menu, in the list as it is once
    the refresh lands, and the choice is saved. Held back on purpose, the
    refresh is always in flight when the key is pressed."""
    page.goto(f"{live}/projects")
    press(page, "j")
    cursor_on(page, page.evaluate(STOPS)[0])
    on = cursor(page)

    # The list's refresh is slow, and the edit sheet slower.
    def later(ms):
        def handle(route):
            page.wait_for_timeout(ms)
            route.continue_()

        return handle

    page.route(lambda url: url.endswith("/projects"), later(300))
    page.route("**/ui/tasks/*/edit", later(600))
    page.evaluate("htmx.trigger(document.body, 'tasks:changed')")
    press(page, "p")  # No project, Home, Garden
    page.locator(".task-sheet[data-sheet=edit]").wait_for()
    press(page, "ArrowDown", "ArrowDown", "Enter")
    page.locator(".task-sheet[data-sheet=edit]").wait_for(state="detached")
    with app_db() as db:
        task = next(t for t in tasks_svc.list_tasks(db) if t.title == on)
        assert task.workstream is not None and task.workstream.name == "Garden"


def test_left_and_right_step_the_calendar_a_week(page, live) -> None:
    from datetime import date, timedelta

    this = date.today() - timedelta(days=date.today().weekday())
    page.goto(f"{live}/projects")
    # From Projects, 2 opens the Calendar on this week; Right goes on a week.
    page.keyboard.press("2")
    page.wait_for_url("**/calendar")
    page.keyboard.press("ArrowRight")
    page.wait_for_url(f"**/calendar?start={(this + timedelta(days=7)).isoformat()}")
    page.keyboard.press("ArrowLeft")
    page.wait_for_url(f"**/calendar?start={this.isoformat()}")
    page.keyboard.press("ArrowLeft")
    page.wait_for_url(f"**/calendar?start={(this - timedelta(days=7)).isoformat()}")
