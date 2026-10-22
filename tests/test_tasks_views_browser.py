"""What every view of a project's Tasks tab shares, in a real browser, the
List included: a task dropped between lists stays where it was; a control
in a row keeps its own Enter; Delete asks, then deletes; and each view is
drawn as it was left before any script runs. The `live`, `page` and
`app_db` fixtures are conftest.py's."""

import json
from datetime import date, timedelta
from urllib.parse import quote

import pytest

from app.models import TaskStatus
from app.services import projects as projects_svc
from app.services import task_views
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

VIEWS = [v.key for v in task_views.VIEWS]
TODAY = date.today()


@pytest.fixture
def made(app_db) -> dict:
    """A project of two workstreams, API with Parse (two sub-tasks) and
    Fetch, UI with Draw; Tidy in none; Swept done."""
    with app_db() as db:
        project = projects_svc.create_project(db, name="Calendar sync")
        api = projects_svc.create_workstream(db, project_id=project.id, name="API")
        ui = projects_svc.create_workstream(db, project_id=project.id, name="UI")

        def task(title: str, **fields) -> int:
            return tasks_svc.create_task(db, title=title, project_id=project.id, **fields).id

        made = {
            "parse": task("Parse", workstream_id=api.id, notes="- [ ] read\n- [ ] write"),
            "fetch": task("Fetch", workstream_id=api.id),
            "draw": task("Draw", workstream_id=ui.id),
            "tidy": task("Tidy"),
            "swept": task("Swept"),
        }
        tasks_svc.set_status(db, made["swept"], TaskStatus.done)
        db.commit()
        return {**made, "project": project.id, "api": api.id, "ui": ui.id}


def open_view(page, live, made, view: str) -> None:
    page.goto(f"{live}/projects/{made['project']}/tasks?view={view}")
    page.locator(f"#task-{made['fetch']}").wait_for()


def task(app_db, task_id: int):  # noqa: ANN201
    with app_db() as db:
        return tasks_svc.get_task(db, task_id)


def carry(page, row, x: float, y: float) -> None:
    """A row picked up, carried to (x, y) and let go there."""
    start = row.bounding_box()
    page.mouse.move(start["x"] + 40, start["y"] + start["height"] / 2)
    page.mouse.down()
    page.mouse.move(start["x"] + 50, start["y"] + start["height"] / 2 + 8, steps=4)
    page.mouse.move(x, y, steps=10)
    page.mouse.move(x + 1, y + 1, steps=2)
    page.mouse.up()


def between(page, view: str, made) -> tuple[float, float]:
    """A point in the view where no list is: between two of them, or over
    what is not one (the columns' names, the pane)."""
    box = lambda sel: page.locator(sel).first.bounding_box()  # noqa: E731
    if view == "list":
        one = box(f"#workstream-group-{made['api']}")
        return one["x"] + one["width"] / 2, one["y"] + one["height"] + 8
    if view in ("table", "schedule"):
        names = box(".tv-columns")
        return names["x"] + names["width"] / 2, names["y"] + names["height"] / 2
    if view == "pane":
        pane = box(".lp-details")
        return pane["x"] + pane["width"] / 2, pane["y"] + 40
    column = box(f"#workstream-group-{made['api']}")
    return column["x"] + column["width"] + 6, column["y"] + 100


@pytest.mark.parametrize("view", VIEWS)
def test_a_task_dropped_between_lists_stays_where_it_was(page, live, app_db, made, view) -> None:
    open_view(page, live, made, view)
    asked = []
    page.on(
        "request",
        lambda r: asked.append(r.url) if r.method == "PATCH" or r.url.endswith("/plan") else None,
    )
    carry(page, page.locator(f"#task-{made['fetch']}"), *between(page, view, made))
    assert page.locator(".drop-over").count() == 0  # nothing lit it as a target
    # A redraw asked for after the drop: a request the drop made would come before it.
    with page.expect_response(lambda r: "/tasks?view=" in r.url):
        page.evaluate("htmx.trigger(document.body, 'tasks:changed')")
    assert asked == []
    fetch = task(app_db, made["fetch"])
    assert fetch.workstream_id == made["api"] and fetch.planned_for is None


@pytest.mark.parametrize("view", VIEWS)
def test_a_tasks_box_steps_it_on_as_gantts(page, live, app_db, made, view) -> None:
    open_view(page, live, made, view)
    box = f"#task-{made['fetch']} .task-check"
    # Its colours, as the Gantt's: in progress blue, in review amber, edged
    # and filled inside.
    colours = """box => {
        const probe = (hue) => {
            const i = document.createElement("i");
            i.style.color = `var(${hue})`;
            document.body.append(i);
            const c = getComputedStyle(i).color;
            i.remove();
            return c;
        };
        const want = box.dataset.status === "in_progress" ? probe("--hue-6") : probe("--warn-fg");
        return getComputedStyle(box).borderTopColor === want
            && getComputedStyle(box, "::before").backgroundColor === want
            && getComputedStyle(box, "::before").visibility === "visible";
    }"""
    for status in (TaskStatus.in_progress, TaskStatus.needs_review):
        page.locator(box).click()
        page.wait_for_function("!document.querySelector('.htmx-request')")
        page.locator(f"{box}[data-status={status.value}]").wait_for()
        assert task(app_db, made["fetch"]).status == status
        assert not page.locator(box).is_checked()
        page.mouse.move(0, 0)
        assert page.locator(box).evaluate(colours)
    page.locator(box).click()
    page.wait_for_function("!document.querySelector('.htmx-request')")
    assert task(app_db, made["fetch"]).status == TaskStatus.done
    # Two quick clicks are two steps.
    other = f"#task-{made['draw']} .task-check"
    page.locator(other).click()
    page.locator(other).click()
    page.locator(f"{other}[data-status=needs_review]").wait_for()
    page.wait_for_function("!document.querySelector('.htmx-request')")
    assert task(app_db, made["draw"]).status == TaskStatus.needs_review


@pytest.mark.parametrize("view", VIEWS)
def test_a_control_in_a_row_keeps_its_own_enter(page, live, app_db, made, view) -> None:
    open_view(page, live, made, view)
    row = f"#task-{made['tidy']}"
    page.locator(row).focus()
    # Tab from the row to its box, its title, and on to its quick Tomorrow.
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    while page.evaluate("document.activeElement.dataset.plan") != "tomorrow":
        page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    page.wait_for_function(f"document.querySelector('{row} .tv-date, {row} .planned') !== null")
    assert task(app_db, made["tidy"]).planned_for == TODAY + timedelta(days=1)
    # Not taken for the row's Enter, which would have opened its sheet.
    assert page.locator(".sheet-item").count() == 0


@pytest.mark.parametrize("view", VIEWS)
def test_delete_asks_then_deletes_and_cancel_keeps_it(page, live, app_db, made, view) -> None:
    open_view(page, live, made, view)
    row = page.locator(f"#task-{made['tidy']}")
    row.focus()
    page.keyboard.press("Delete")
    dialog = page.locator("#confirm-dialog")
    dialog.wait_for()
    assert "Tidy" in dialog.inner_text()
    dialog.get_by_role("button", name="Cancel").click()
    page.wait_for_function(f"document.activeElement?.id === 'task-{made['tidy']}'")
    page.keyboard.press("Delete")
    dialog.get_by_role("button", name="Delete").click()
    row.wait_for(state="detached")
    with app_db() as db:
        assert made["tidy"] not in {t.id for t in tasks_svc.list_tasks(db)}


# A part of each view to fold, and what folding it hides.
FOLD = {
    "table": ("none", "#task-{tidy}"),
    "pane": ("ws-{api}", "#task-{parse}"),
    "schedule": ("when-today", "#sv-today .task-sheet[data-composer]"),
}


@pytest.mark.parametrize("view", ["table", "pane", "board", "schedule"])
def test_each_view_is_drawn_as_it_was_left_before_any_script_runs(page, live, made, view) -> None:
    """Its first paint is the state kept (the tab's cookie, drawn by the
    server): with the views' scripts held back, the fold, the sub-tasks shown
    and Show completed are already as they were left."""
    url = f"{live}/projects/{made['project']}/tasks"
    state = {"subtasks": [made["parse"]], "done": True}
    if view in FOLD:
        state["folds"] = [FOLD[view][0].format(**made)]
    page.context.add_cookies(
        [{"name": "tasks-state", "value": quote(json.dumps({view: state})), "url": url}]
    )
    page.route("**/tasks-*.js*", lambda route: route.abort())  # the views' scripts, all
    page.goto(f"{url}?view={view}")
    page.locator(f"#task-{made['swept']}").wait_for()  # the finished work, shown
    assert page.locator("#tasks-show-done-box").is_checked()
    if view in FOLD:
        part = page.locator(f"[data-fold-key='{state['folds'][0]}']")
        assert "folded" in part.get_attribute("class")
        assert part.locator("[data-fold]").get_attribute("aria-expanded") == "false"
        assert page.locator(FOLD[view][1].format(**made)).is_hidden()
    # Parse's sub-tasks (the Board: its description), shown under it.
    shown = {"board": f"#board-notes-{made['parse']}"}.get(view, f"#tv-subtasks-{made['parse']}")
    if view != "pane":
        assert page.locator(shown).is_visible() and "read" in page.locator(shown).inner_text()
    # The page, at the window's width, never wider (the agent window's edge).
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
