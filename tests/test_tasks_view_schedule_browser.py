"""By do-date, a view of a project's Tasks tab, in a real browser: a tick,
an edit and a quick do-date answered in the view; a task dragged onto a
section for its day, never onto Overdue and never filed by tasks.js; folds,
sub-tasks and Show completed kept across redraws; a new task landing in its
section; and the keyboard's cursor over the rows. The `live`, `page` and
`app_db` fixtures are conftest.py's."""

from datetime import date, datetime, time, timedelta

import pytest

from app.models import Task, TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()

# A redraw of the tab in flight (a change draws it twice: for the task, for
# the calendar); these tests wait it out before reading the rows.
BUSY = "!!document.querySelector('#project-tasks.htmx-request, #project-tasks .htmx-request')"

# The rows of a section, in order, by title.
TITLES = """(key) => [...document.querySelectorAll(`#sv-${key} .tv-row`)]
  .map((r) => r.dataset.taskTitle)"""

# The keyboard's path: the rows the eye can see, in order.
STOPS = """[...document.querySelectorAll('[data-cursor] .task-row[tabindex]')]
  .filter((e) => e.checkVisibility()).map((e) => e.dataset.taskTitle)"""


@pytest.fixture
def home(app_db) -> dict:
    """Home's tasks: Late (overdue), Now (today), Next (tomorrow), Paint
    (none, in the Garden workstream, two sub-tasks) and Rest (none), and
    Swept, done; its tab in By do-date at `home["url"]`."""
    with app_db() as db:
        project = projects_svc.create_project(db, name="Home")
        garden = projects_svc.create_workstream(db, project_id=project.id, name="Garden")

        def task(title: str, **fields) -> int:
            return tasks_svc.create_task(db, title=title, project_id=project.id, **fields).id

        made = {
            "late": task("Late", planned_for=TODAY - timedelta(days=2)),
            "now": task("Now", planned_for=TODAY),
            "next": task("Next", planned_for=TODAY + timedelta(days=1)),
            "paint": task("Paint", workstream_id=garden.id, notes="- [ ] sand\n- [ ] prime"),
            "rest": task("Rest"),
            "swept": task("Swept", planned_for=TODAY - timedelta(days=1)),
        }
        tasks_svc.set_status(db, made["swept"], TaskStatus.done)
        db.commit()
        return {**made, "garden": garden.id, "url": f"/projects/{project.id}/tasks?view=schedule"}


def task_of(app_db, task_id: int) -> Task:
    with app_db() as db:
        return db.get(Task, task_id)


def settle(page) -> None:
    page.wait_for_function(f"!{BUSY}", timeout=5000)


def titles(page, key: str) -> list[str]:
    settle(page)
    return page.evaluate(f"({TITLES})({key!r})")


def wait_in(page, key: str, title: str) -> None:
    page.wait_for_function(f"({TITLES})({key!r}).includes({title!r}) && !{BUSY}", timeout=5000)


def open_tab(page, live, home) -> None:
    page.goto(f"{live}{home['url']}")
    page.locator("#sv-today").wait_for()


def test_a_tick_is_drawn_in_the_view_and_the_task_leaves_its_section(
    page, live, app_db, home
) -> None:
    # In review, its box's click makes it done.
    with app_db() as db:
        tasks_svc.set_status(db, home["now"], TaskStatus.needs_review)
        db.commit()
    open_tab(page, live, home)
    # A click, not check(): the tick swaps the box out, and check() would read it again.
    page.locator("#sv-today .tv-row", has_text="Now").locator(".task-check").click()
    page.wait_for_function("!document.querySelector('#sv-today .tv-row')", timeout=5000)
    assert task_of(app_db, home["now"]).status == TaskStatus.done
    # It is under Completed, shown once Show completed is ticked.
    assert not page.locator("#sv-done").is_visible()
    page.locator("[data-show-done]").click()
    page.locator("#sv-done").wait_for()
    assert titles(page, "done") == ["Now", "Swept"]
    assert page.locator(f"#sv-done #task-{home['now']}.tv-row.done").is_visible()
    # Kept on this device: the page opened again shows it still.
    page.reload()
    page.locator("#sv-done").wait_for(state="visible")
    assert page.locator("[data-show-done]").is_checked()


def test_enter_edits_in_place_and_esc_or_a_save_gives_the_row_back(
    page, live, app_db, home
) -> None:
    open_tab(page, live, home)
    row = f"#task-{home['rest']}"
    page.locator(row).focus()
    page.keyboard.press("Enter")
    page.locator(f"{row}.sheet-item .task-sheet[data-sheet=edit][data-ready]").wait_for()
    # Unchanged, Esc gives back this view's row, not the list's.
    page.keyboard.press("Escape")
    page.locator(f"{row}.tv-row").wait_for()
    assert page.locator(f"{row} .tv-line .tv-cell").count() == 6
    page.wait_for_function(f"document.activeElement?.id === 'task-{home['rest']}'", timeout=5000)

    # Changed, it is saved, and comes back as this view's row with the change.
    page.keyboard.press("Enter")
    page.locator(f"{row} .task-sheet[data-sheet=edit][data-ready]").wait_for()
    page.keyboard.type(" a while")
    page.keyboard.press("Escape")
    page.locator(f"{row}.tv-row", has_text="Rest a while").wait_for()
    settle(page)
    assert page.locator(f"#sv-none {row}.tv-row").count() == 1
    assert task_of(app_db, home["rest"]).title == "Rest a while"


def test_quick_do_dates_move_a_row_to_today_and_tomorrow(page, live, app_db, home) -> None:
    open_tab(page, live, home)
    page.locator(f"#task-{home['rest']} .tv-line").hover()
    page.locator(f"#task-{home['rest']} [data-plan='today']").click()
    wait_in(page, "today", "Rest")
    assert titles(page, "today") == ["Now", "Rest"]
    assert task_of(app_db, home["rest"]).planned_for == TODAY

    # M, from the keyboard: to Tomorrow.
    page.locator(f"#task-{home['rest']}").focus()
    page.keyboard.press("m")
    wait_in(page, "tomorrow", "Rest")
    assert task_of(app_db, home["rest"]).planned_for == TODAY + timedelta(days=1)
    # The hover's buttons sit at the name's end, out of sight until then.
    assert page.locator(f"#task-{home['now']} .tv-quick").bounding_box()["width"] <= 1


def test_a_task_dragged_onto_a_section_takes_its_day(page, live, app_db, home) -> None:
    open_tab(page, live, home)
    paint = f"#task-{home['paint']}"

    page.locator(paint).drag_to(page.locator("#sv-week .tv-head"))
    wait_in(page, "week", "Paint")
    task = task_of(app_db, home["paint"])
    assert task.planned_for == TODAY + timedelta(days=2)
    # Filed nowhere: tasks.js's filing by drag never heard of it.
    assert task.workstream_id == home["garden"]

    page.locator(paint).drag_to(page.locator("#sv-later .tv-head"))
    wait_in(page, "later", "Paint")
    assert task_of(app_db, home["paint"]).planned_for == TODAY + timedelta(days=8)

    page.locator(paint).drag_to(page.locator(f"#task-{home['now']}"))  # onto a row of Today's
    wait_in(page, "today", "Paint")
    assert task_of(app_db, home["paint"]).planned_for == TODAY

    page.locator(paint).drag_to(page.locator("#sv-none .tv-head"))
    wait_in(page, "none", "Paint")
    task = task_of(app_db, home["paint"])
    assert task.planned_for is None and task.workstream_id == home["garden"]


def test_overdue_and_the_section_it_is_in_take_no_drop(page, live, app_db, home) -> None:
    open_tab(page, live, home)
    planned = []
    page.on("request", lambda r: "/plan" in r.url and planned.append(r.url))
    page.locator(f"#task-{home['now']}").drag_to(page.locator("#sv-overdue .tv-head"))
    page.locator(f"#task-{home['rest']}").drag_to(page.locator("#sv-none .tv-head"))
    # A redraw asked for after them: any do-date they posted would come before it.
    with page.expect_response(lambda r: "view=schedule" in r.url):
        page.evaluate("htmx.trigger(document.body, 'tasks:changed')")
    settle(page)
    assert planned == []
    assert titles(page, "overdue") == ["Late"] and titles(page, "today") == ["Now"]
    assert task_of(app_db, home["now"]).planned_for == TODAY
    assert task_of(app_db, home["rest"]).planned_for is None
    # Nothing is left lit, or faded.
    assert (
        page.locator("#project-tasks .drop-over, #project-tasks .dragging").count() == 0
    )


def test_a_section_held_over_lights_and_says_its_day(page, live, home) -> None:
    open_tab(page, live, home)
    row = page.locator(f"#task-{home['next']}").bounding_box()
    week = page.locator("#sv-week .tv-head").bounding_box()
    overdue = page.locator("#sv-overdue .tv-head").bounding_box()
    page.mouse.move(row["x"] + 300, row["y"] + row["height"] / 2)
    page.mouse.down()
    page.mouse.move(row["x"] + 310, row["y"] + 40, steps=4)
    page.mouse.move(week["x"] + 300, week["y"] + 20, steps=8)
    page.locator("#sv-week.drop-over").wait_for()
    assert page.locator("#sv-week .tv-drop-note").is_visible()
    assert page.locator(f"#task-{home['next']}.dragging").count() == 1
    page.mouse.move(overdue["x"] + 300, overdue["y"] + 20, steps=8)
    page.wait_for_function("!document.querySelector('.drop-over')", timeout=2000)
    page.mouse.up()


def test_a_fold_is_kept_across_a_redraw(page, live, home) -> None:
    open_tab(page, live, home)
    page.locator("#sv-today [data-fold]").click()
    assert "folded" in page.locator("#sv-today").get_attribute("class")
    assert not page.locator(f"#task-{home['now']}").is_visible()
    # A click on its head unfolds it, as its chevron does.
    page.locator("#sv-tomorrow .tv-head h2").click()
    assert "folded" in page.locator("#sv-tomorrow").get_attribute("class")
    page.evaluate("htmx.trigger(document.body, 'tasks:changed')")
    page.wait_for_function(
        "document.querySelector('#sv-today')?.classList.contains('folded')", timeout=5000
    )
    settle(page)
    assert "folded" in page.locator("#sv-tomorrow").get_attribute("class")
    assert not page.locator(f"#task-{home['now']}").is_visible()
    page.locator("#sv-today .tv-head").click()
    assert page.locator(f"#task-{home['now']}").is_visible()


def test_sub_tasks_show_under_the_row_and_tick_there(page, live, app_db, home) -> None:
    open_tab(page, live, home)
    paint = f"#task-{home['paint']}"
    part = page.locator(f"#tv-subtasks-{home['paint']}")
    assert not part.is_visible()
    page.locator(f"{paint} .tv-subcount").click()
    assert part.is_visible()
    assert page.locator(f"{paint} .tv-expand").get_attribute("aria-expanded") == "true"
    # Their count says what it does next, to a reader.
    count = page.locator(f"{paint} .tv-subcount")
    assert count.get_attribute("aria-label") == "0 of 2 sub-tasks done: hide them"
    part.locator(".subtask-check").first.click()
    page.locator(f"{paint} .tv-subcount", has_text="1/2").wait_for()
    assert page.locator(f"#tv-subtasks-{home['paint']}").is_visible()
    assert "- [x] sand" in task_of(app_db, home["paint"]).notes
    # Space on the row hides them again, and they stay hidden through a redraw.
    page.locator(paint).focus()
    page.keyboard.press(" ")
    assert not page.locator(f"#tv-subtasks-{home['paint']}").is_visible()
    assert count.get_attribute("aria-label") == "1 of 2 sub-tasks done: show them"
    page.evaluate("htmx.trigger(document.body, 'tasks:changed')")
    settle(page)
    assert not page.locator(f"#tv-subtasks-{home['paint']}").is_visible()


def test_a_new_task_lands_in_the_section_of_its_day(page, live, app_db, home) -> None:
    open_tab(page, live, home)
    # Every row ever drawn into No do-date's list, to see none lands there by mistake.
    page.evaluate("""() => {
      window.__landed = [];
      new MutationObserver((changes) => changes.forEach((c) => c.addedNodes.forEach((n) => {
        if (n.dataset?.taskTitle) window.__landed.push([n.parentElement?.id, n.dataset.taskTitle]);
      }))).observe(document.getElementById('project-tasks').parentElement,
        { childList: true, subtree: true });
    }""")
    page.locator("#sv-today .sheet-title").click()
    page.keyboard.type("Water")
    page.keyboard.press("Control+Enter")
    wait_in(page, "today", "Water")
    page.keyboard.press("Escape")

    # Written under No do-date but dated tomorrow: it waits for the redraw, in Tomorrow.
    page.locator("#sv-none .sheet-title").click()
    page.keyboard.type("Mow tomorrow")
    page.keyboard.press("Control+Enter")
    wait_in(page, "tomorrow", "Mow")
    landed = page.evaluate("window.__landed")
    assert ["sv-rows-none", "Mow"] not in landed and ["sv-rows-today", "Water"] in landed
    with app_db() as db:
        by_title = {t.title: t for t in tasks_svc.list_tasks(db)}
    assert by_title["Water"].planned_for == TODAY
    assert by_title["Mow"].planned_for == TODAY + timedelta(days=1)


def test_the_cursor_moves_over_the_rows_section_by_section(page, live, app_db, home) -> None:
    open_tab(page, live, home)
    assert page.evaluate(STOPS) == ["Late", "Now", "Next", "Paint", "Rest"]
    page.keyboard.press("j")
    page.wait_for_function("document.activeElement?.dataset.taskTitle === 'Late'", timeout=5000)
    page.keyboard.press("Shift+J")  # a section on: Today
    page.wait_for_function("document.activeElement?.dataset.taskTitle === 'Now'", timeout=5000)
    page.keyboard.press("Shift+J")
    page.wait_for_function("document.activeElement?.dataset.taskTitle === 'Next'", timeout=5000)
    page.keyboard.press("j")
    page.wait_for_function("document.activeElement?.dataset.taskTitle === 'Paint'", timeout=5000)
    # Its do-date buttons show on the row the cursor is on.
    assert page.locator(f"#task-{home['paint']} [data-plan='today']").is_visible()
    # X steps it on, as its box does, the cursor staying on it: in progress,
    # then review; then done, and the cursor goes on to the next row.
    for status in (TaskStatus.in_progress, TaskStatus.needs_review):
        page.keyboard.press("x")
        page.locator(f"#task-{home['paint']} .task-check[data-status={status.value}]").wait_for()
        page.wait_for_function("!document.querySelector('.htmx-request')")
        assert task_of(app_db, home["paint"]).status == status
        assert page.evaluate("document.activeElement?.dataset.taskTitle") == "Paint"
    page.keyboard.press("x")
    page.wait_for_function("document.activeElement?.dataset.taskTitle === 'Rest'", timeout=5000)
    assert task_of(app_db, home["paint"]).status == TaskStatus.done


def test_a_head_with_nothing_under_it_does_not_fold(page, live, app_db, home) -> None:
    open_tab(page, live, home)
    # Later is empty and takes no new task: nothing to fold, its head a plain one.
    assert page.locator("#sv-later [data-fold]").count() == 0
    page.locator("#sv-later .tv-head h2").click()
    assert "folded" not in page.locator("#sv-later").get_attribute("class")
    assert "when-later" not in page.evaluate("decodeURIComponent(document.cookie)")
    # A task dropped there later shows there.
    page.locator(f"#task-{home['rest']}").drag_to(page.locator("#sv-later .tv-head"))
    wait_in(page, "later", "Rest")
    assert page.locator(f"#sv-later #task-{home['rest']}").is_visible()


def test_a_folded_section_opens_for_a_task_dropped_on_it(page, live, app_db, home) -> None:
    open_tab(page, live, home)
    page.locator("#sv-today [data-fold]").click()
    assert "folded" in page.locator("#sv-today").get_attribute("class")
    page.locator(f"#task-{home['rest']}").drag_to(page.locator("#sv-today .tv-head"))
    wait_in(page, "today", "Rest")
    assert "folded" not in page.locator("#sv-today").get_attribute("class")
    assert page.locator(f"#sv-today #task-{home['rest']}").is_visible()
    assert page.locator("#sv-today [data-fold]").get_attribute("aria-expanded") == "true"
    # And stays open through the next redraw.
    page.evaluate("htmx.trigger(document.body, 'tasks:changed')")
    settle(page)
    assert "folded" not in page.locator("#sv-today").get_attribute("class")


def test_a_drop_takes_its_day_from_the_day_it_is_dropped_on(page, live, app_db, home) -> None:
    open_tab(page, live, home)
    # The page left open past midnight: Tomorrow is now the day after.
    later = datetime.combine(TODAY + timedelta(days=1), time(10))
    page.clock.set_fixed_time(later)
    page.locator(f"#task-{home['rest']}").drag_to(page.locator("#sv-tomorrow .tv-head"))
    page.wait_for_function(f"!document.querySelector('#sv-none #task-{home['rest']}') && !{BUSY}")
    assert task_of(app_db, home["rest"]).planned_for == TODAY + timedelta(days=2)


def test_a_sheet_saved_with_another_day_moves_the_row(page, live, app_db, home) -> None:
    open_tab(page, live, home)
    row = f"#task-{home['rest']}"
    page.locator(row).focus()
    page.keyboard.press("Enter")
    page.locator(f"{row} .task-sheet[data-sheet=edit][data-ready]").wait_for()
    # Its title's trailing word is its do-date, as the sheet takes it.
    page.keyboard.type(" tomorrow")
    page.keyboard.press("Escape")
    wait_in(page, "tomorrow", "Rest")
    assert page.locator(f"#sv-tomorrow {row}.tv-row").count() == 1
    assert page.locator(f"#sv-none {row}").count() == 0
    assert task_of(app_db, home["rest"]).planned_for == TODAY + timedelta(days=1)
