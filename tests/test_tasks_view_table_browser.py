"""The Tasks tab's Table in a real browser: its rows tick, edit in place,
take quick do-dates and file by drag; its sections fold and its sub-tasks
show, kept across the redraws; Show completed; and the keyboard's cursor
over its rows. The app serves from a thread over a throwaway database
(the `live` and `page` fixtures, conftest.py)."""

from datetime import date

import pytest

from app.models import TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")


@pytest.fixture
def made(app_db) -> dict:
    """A project of two workstreams, API with two tasks (one with
    sub-tasks) and UI with one, and a task in none."""
    with app_db() as db:
        project = projects_svc.create_project(db, name="Calendar sync")
        api = projects_svc.create_workstream(db, project_id=project.id, name="API")
        ui = projects_svc.create_workstream(db, project_id=project.id, name="UI")
        parse = tasks_svc.create_task(
            db,
            title="parse",
            project_id=project.id,
            workstream_id=api.id,
            notes="- [ ] read\n- [ ] write",
        )
        fetch = tasks_svc.create_task(
            db, title="fetch", project_id=project.id, workstream_id=api.id
        )
        draw = tasks_svc.create_task(db, title="draw", project_id=project.id, workstream_id=ui.id)
        tidy = tasks_svc.create_task(db, title="tidy", project_id=project.id)
        db.commit()
        return {
            "project": project.id,
            "api": api.id,
            "ui": ui.id,
            "parse": parse.id,
            "fetch": fetch.id,
            "draw": draw.id,
            "tidy": tidy.id,
        }


def open_table(page, live, made) -> None:
    page.goto(f"{live}/projects/{made['project']}/tasks?view=table")
    page.locator(".tasks-in-table .tv-row").first.wait_for()


def redrawn(page) -> None:
    """The list drawn again from the server, as any change elsewhere does,
    and settled: tasks-views.js, listening first, has drawn what is kept."""
    page.evaluate(
        """() => {
          window.ttSettled = false;
          document.addEventListener("htmx:afterSettle", (e) => {
            if (e.detail.elt?.id === "project-tasks") window.ttSettled = true;
          });
          htmx.trigger(document.body, "tasks:changed");
        }"""
    )
    page.wait_for_function("window.ttSettled")


# Any two cells of a line drawn over each other, anything that has left its
# cell, and the table wider than its room (so the page would scroll sideways).
OVERLAPS = """() => {
  const seen = (el) => el.checkVisibility() && el.getBoundingClientRect().width > 0;
  const over = (a, b) => a.left < b.right - 0.5 && b.left < a.right - 0.5
    && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
  const wrong = [];
  document.querySelectorAll(".tasks-in-table .tv-line").forEach((line, n) => {
    const cells = [...line.children].filter(seen);
    cells.forEach((cell, i) => {
      const box = cell.getBoundingClientRect();
      cells.slice(i + 1).forEach((other) => {
        if (over(box, other.getBoundingClientRect())) wrong.push(`line ${n}: cells overlap`);
      });
      [...cell.children].filter(seen).forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.left < box.left - 0.5 || r.right > box.right + 0.5) {
          wrong.push(`line ${n}: ${el.className} out`);
        }
      });
    });
  });
  const table = document.querySelector("#project-tasks");
  const main = document.querySelector(".main").getBoundingClientRect();
  if (table.scrollWidth > table.clientWidth) wrong.push("the table scrolls");
  if (table.getBoundingClientRect().right > main.right) wrong.push("the table leaves the page");
  return wrong;
}"""


def quick_shown(row) -> bool:
    """Its quick do-dates in sight (out of it, they are a clipped pixel)."""
    return row.locator(".tv-quick").bounding_box()["width"] > 1


def task(app_db, task_id: int):  # noqa: ANN201
    with app_db() as db:
        return tasks_svc.get_task(db, task_id)


def test_a_tick_comes_back_as_the_tables_row_and_the_task_leaves(page, live, app_db, made) -> None:
    # In review, its box's click makes it done.
    with app_db() as db:
        tasks_svc.set_status(db, made["fetch"], TaskStatus.needs_review)
        db.commit()
    open_table(page, live, made)
    row = page.locator(f"#task-{made['fetch']}")
    # A click, not check(): the tick swaps the box out, and check() would read it again.
    row.locator(".task-check").click()
    # The page redraws (the calendar's refresh): finished, it is in no section.
    page.locator(f"#tt-ws-{made['api']} #task-{made['fetch']}").wait_for(state="detached")
    assert task(app_db, made["fetch"]).status.value == "done"
    done = page.locator(f"#tt-done #task-{made['fetch']}")
    assert done.count() == 1 and not done.is_visible()
    # Shown completed, it is there, ticked; Show completed is kept.
    page.locator("#tasks-show-done-box").click()
    done.wait_for()
    assert done.locator(".task-check").is_checked()
    page.reload()
    assert page.locator(f"#tt-done #task-{made['fetch']}").is_visible()
    assert page.locator("#tasks-show-done-box").is_checked()
    page.locator("#tasks-show-done-box").click()
    page.locator("#tt-done").wait_for(state="hidden")


def test_enter_edits_in_place_and_esc_or_a_save_gives_the_row_back(
    page, live, app_db, made
) -> None:
    open_table(page, live, made)
    page.keyboard.press("ArrowDown")  # the cursor on the first row
    first = f"#task-{made['parse']}"
    assert page.evaluate("document.activeElement.id") == first[1:]
    page.keyboard.press("Enter")
    sheet = page.locator(f"#tt-rows-ws-{made['api']} > li.sheet-item{first}")
    sheet.locator(".sheet-title").wait_for()
    # Nothing changed: Esc gives the row back, the cursor on it.
    page.keyboard.press("Escape")
    page.locator(f"#tt-rows-ws-{made['api']} > li.tv-row{first}").wait_for()
    page.wait_for_function(f"document.activeElement.id === '{first[1:]}'")

    page.keyboard.press("Enter")
    sheet.locator(".sheet-title").wait_for()
    page.keyboard.type(" the feed")
    page.keyboard.press("Escape")
    page.locator(f"li.tv-row{first} .task-title", has_text="parse the feed").wait_for()
    assert task(app_db, made["parse"]).title == "parse the feed"
    assert page.locator(f"#tt-ws-{made['api']} li.tv-row{first} .tv-cell").count() == 6


def test_the_quick_do_dates_show_on_hover_and_date_the_task(page, live, app_db, made) -> None:
    open_table(page, live, made)
    row = page.locator(f"#task-{made['tidy']}")
    assert not quick_shown(row)
    row.locator(".tv-line").hover()
    assert quick_shown(row)
    row.locator("[data-plan=today]").click()
    page.locator(f"#task-{made['tidy']} .tv-date", has_text="today").wait_for()
    assert task(app_db, made["tidy"]).planned_for == date.today()
    # T on the cursor's row does the same, and M gives tomorrow.
    page.mouse.move(0, 0)
    page.locator(f"#task-{made['fetch']}").focus()
    page.keyboard.press("t")
    page.locator(f"#task-{made['fetch']} .tv-date", has_text="today").wait_for()
    assert task(app_db, made["fetch"]).planned_for == date.today()
    page.locator(f"#task-{made['tidy']}").focus()
    page.keyboard.press("m")
    page.locator(f"#task-{made['tidy']} .tv-date", has_text="tomorrow").wait_for()


def test_the_quick_do_dates_are_reached_by_tab(page, live, app_db, made) -> None:
    open_table(page, live, made)
    page.mouse.move(0, 0)
    row = page.locator(f"#task-{made['tidy']}")
    row.focus()
    page.keyboard.press("Tab")  # its box
    page.keyboard.press("Tab")  # its title
    assert page.evaluate("document.activeElement.className") == "task-title-btn"
    assert quick_shown(row)
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.dataset.plan") == "today"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.dataset.plan") == "tomorrow"
    # Enter presses it (not the row's Enter, which edits).
    page.keyboard.press("Enter")
    page.locator(f"#task-{made['tidy']} .tv-date", has_text="tomorrow").wait_for()


@pytest.mark.parametrize("width", [800, 960, 1440])
def test_no_cell_runs_into_the_next_at_any_width(page, live, app_db, made, width) -> None:
    with app_db() as db:
        long = tasks_svc.create_task(
            db,
            title="Read the whole calendar feed, every event of every week, and parse it " * 3,
            project_id=made["project"],
            workstream_id=made["api"],
            planned_for=date.today(),
            due=date.today(),
        )
        db.commit()
    page.set_viewport_size({"width": width, "height": 900})
    open_table(page, live, made)
    assert page.evaluate(OVERLAPS) == []
    # Hovered, its quick do-dates stay in the name's cell.
    page.locator(f"#task-{long.id} .tv-line").hover()
    assert quick_shown(page.locator(f"#task-{long.id}"))
    assert page.evaluate(OVERLAPS) == []
    columns = page.locator(".tv-columns > .tv-cell:visible").count()
    # A phone's has no columns (its row is only for Show completed, and none is done).
    assert columns == {800: 0, 960: 3, 1440: 6}[width]


def test_a_section_folded_stays_folded_through_redraws(page, live, made) -> None:
    open_table(page, live, made)
    api = page.locator(f"#tt-ws-{made['api']}")
    api.locator("[data-fold]").click()
    assert "folded" in api.get_attribute("class")
    assert api.locator("[data-fold]").get_attribute("aria-expanded") == "false"
    assert not page.locator(f"#task-{made['parse']}").is_visible()
    assert not api.locator(".task-sheet[data-composer]").is_visible()
    redrawn(page)
    assert not page.locator(f"#task-{made['parse']}").is_visible()
    page.reload()
    assert not page.locator(f"#task-{made['parse']}").is_visible()
    # The cursor passes over it.
    page.keyboard.press("ArrowDown")
    assert page.evaluate("document.activeElement.id") == f"task-{made['draw']}"
    page.locator(f"#tt-ws-{made['api']} [data-fold]").click()
    assert page.locator(f"#task-{made['parse']}").is_visible()


def test_sub_tasks_show_under_the_row_and_tick_in_place(page, live, app_db, made) -> None:
    open_table(page, live, made)
    row = f"#task-{made['parse']}"
    part = page.locator(f"#tv-subtasks-{made['parse']}")
    assert not part.is_visible()
    page.locator(f"{row} .tv-expand").click()
    assert part.is_visible()
    assert page.locator(f"{row} .tv-expand").get_attribute("aria-expanded") == "true"
    part.locator(".subtask-check").first.click()
    page.locator(f"{row} .tv-subcount", has_text="1/2").wait_for()
    assert page.locator(f"#tv-subtasks-{made['parse']}").is_visible()
    assert "- [x] read" in task(app_db, made["parse"]).notes
    redrawn(page)
    assert page.locator(f"#tv-subtasks-{made['parse']}").is_visible()
    # Space on the cursor's row hides them, and shows them again.
    page.locator(row).focus()
    page.keyboard.press(" ")
    assert not page.locator(f"#tv-subtasks-{made['parse']}").is_visible()
    page.keyboard.press(" ")
    assert page.locator(f"#tv-subtasks-{made['parse']}").is_visible()
    assert page.evaluate("document.activeElement.id") == row[1:]


def test_a_row_dragged_onto_a_section_files_into_it(page, live, app_db, made) -> None:
    open_table(page, live, made)
    page.locator(f"#task-{made['tidy']} .tv-line").drag_to(
        page.locator(f"#tt-ws-{made['ui']} .tv-head")
    )
    page.locator(f"#tt-ws-{made['ui']} #task-{made['tidy']}").wait_for()
    assert task(app_db, made["tidy"]).workstream_id == made["ui"]
    page.locator(f"#task-{made['draw']} .tv-line").drag_to(
        page.locator("#tt-none .tv-head")
    )
    page.locator(f"#tt-none #task-{made['draw']}").wait_for()
    assert task(app_db, made["draw"]).workstream_id is None
    # Off the sections (the columns' names) it files nowhere: nothing is sent.
    sent = []
    page.on("request", lambda r: sent.append(r.url) if "/api/tasks/" in r.url else None)
    page.locator(f"#task-{made['fetch']} .tv-line").drag_to(page.locator(".tv-columns"))
    redrawn(page)
    assert sent == []
    assert task(app_db, made["fetch"]).workstream_id == made["api"]


def test_the_keyboard_cursor_walks_the_rows_and_n_adds_into_its_section(
    page, live, app_db, made
) -> None:
    # In review, X makes it done.
    with app_db() as db:
        tasks_svc.set_status(db, made["fetch"], TaskStatus.needs_review)
        db.commit()
    open_table(page, live, made)
    order = [made["parse"], made["fetch"], made["draw"], made["tidy"]]
    for task_id in order:
        page.keyboard.press("ArrowDown")
        assert page.evaluate("document.activeElement.id") == f"task-{task_id}"
    # Shift jumps a section: up to the start of UI's.
    page.keyboard.press("Shift+ArrowUp")
    assert page.evaluate("document.activeElement.id") == f"task-{made['draw']}"
    # N writes into the cursor's section, and the new task joins it.
    page.keyboard.press("n")
    page.keyboard.type("colour")
    page.keyboard.press("Control+Enter")
    page.locator(f"#tt-ws-{made['ui']} .tv-row", has_text="colour").wait_for()
    with app_db() as db:
        added = next(t for t in tasks_svc.list_tasks(db) if t.title == "colour")
        assert added.workstream_id == made["ui"]
    # X on a row in review makes it done, and the cursor moves on.
    page.locator(f"#task-{made['fetch']}").focus()
    page.keyboard.press("x")
    page.locator(f"#tt-ws-{made['api']} #task-{made['fetch']}").wait_for(state="detached")
    assert task(app_db, made["fetch"]).status.value == "done"
