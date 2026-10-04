"""The New task window in a real browser: opened from the sidebar on any page,
the task filed into a project and workstream from its foot or with "#", a
project's pages starting it in that project. The `live`, `page` and `app_db`
fixtures are conftest.py's."""

import pytest

from app.services import history as history_svc
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

WINDOW = "#capture-dialog"
CHIP = f"{WINDOW} .file-into .prop-value"
TITLE = f"{WINDOW} .sheet-title"
# The items a menu of projects shows, and the one Enter takes.
SHOWN = """[...document.querySelectorAll('.sheet-menu [role=menuitemradio]:not([hidden])')]
  .map((e) => e.textContent.trim())"""
ACTIVE = "document.querySelector('.sheet-menu [data-active]')?.textContent.trim() ?? null"


@pytest.fixture
def places(app_db) -> dict[str, int]:
    """Two projects, with workstreams."""
    with app_db() as db:
        home = projects_svc.create_project(db, name="Home")
        work = projects_svc.create_project(db, name="Work")
        ids = {
            "home": home.id,
            "work": work.id,
            "garden": projects_svc.create_workstream(db, project_id=home.id, name="Garden").id,
            "kitchen": projects_svc.create_workstream(db, project_id=home.id, name="Kitchen").id,
            "release": projects_svc.create_workstream(db, project_id=work.id, name="Release").id,
        }
        db.commit()
    return ids


def task_named(app_db, title: str):  # noqa: ANN201
    with app_db() as db:
        task = next(t for t in tasks_svc.list_tasks(db) if t.title == title)
        return task.project_id, task.workstream_id


def test_the_sidebar_opens_it_on_any_page_and_files_the_task(page, live, app_db, places) -> None:
    page.goto(f"{live}/garmin")
    page.locator("[data-capture-open]").click()
    page.locator(f"{WINDOW}[open]").wait_for()
    assert page.evaluate(f"document.activeElement.matches('{TITLE}')")
    assert page.locator(CHIP).text_content() == "No project"

    # Its foot: a menu found by a few letters of each name.
    page.locator(f"{WINDOW} .file-into").click()
    page.wait_for_function("document.activeElement?.matches('.sheet-menu-find')")
    page.keyboard.type("home kit")
    assert page.evaluate(SHOWN) == ["Home", "Kitchen"]
    assert page.evaluate(ACTIVE) == "Kitchen"
    page.keyboard.press("Enter")
    assert page.locator(CHIP).text_content() == "Home › Kitchen"
    # The writing goes on where it was.
    assert page.evaluate(f"document.activeElement.matches('{TITLE}')")

    page.keyboard.type("Fix the tap")
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Added “Fix the tap” to Home › Kitchen").wait_for()
    assert task_named(app_db, "Fix the tap") == (places["home"], places["kitchen"])

    # The window stays, for one more for the same place.
    assert page.locator(TITLE).text_content() == ""
    assert page.locator(CHIP).text_content() == "Home › Kitchen"
    page.keyboard.type("Descale the kettle")
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Descale the kettle").wait_for()
    assert task_named(app_db, "Descale the kettle") == (places["home"], places["kitchen"])

    # Its Open, over the window, goes to the task's page.
    page.locator(".cal-toast.show .toast-action", has_text="Open").click()
    page.wait_for_url("**/tasks/*")
    assert page.locator(".task-page .sheet-title").text_content() == "Descale the kettle"

    # Opened again, it starts afresh.
    page.locator("[data-capture-open]").click()
    page.locator(f"{WINDOW}[open]").wait_for()
    assert page.locator(CHIP).text_content() == "No project"


def test_a_hash_files_it_and_backspace_takes_it_back(page, live, app_db, places) -> None:
    page.goto(f"{live}/me")
    page.keyboard.press("n")
    page.locator(f"{WINDOW}[open]").wait_for()

    # "#" drops the projects down; the words after it narrow them.
    page.keyboard.type("Call the plumber #")
    page.locator(".sheet-menu.inline").wait_for()
    assert page.evaluate(SHOWN) == ["No project", "Home", "Garden", "Kitchen", "Work", "Release"]
    page.keyboard.type("work rel")
    assert page.evaluate(SHOWN) == ["Work", "Release"]
    assert page.evaluate(ACTIVE) == "Release"
    # The title keeps the focus, and Tab takes the active one.
    assert page.evaluate(f"document.activeElement.matches('{TITLE}')")
    page.keyboard.press("Tab")
    assert page.locator(".sheet-menu").count() == 0
    assert page.locator(TITLE).text_content() == "Call the plumber "
    assert page.locator(CHIP).text_content() == "Work › Release"

    # Backspace right after puts the words back, and the project as it was.
    page.keyboard.press("Backspace")
    assert page.locator(TITLE).text_content() == "Call the plumber #work rel"
    assert page.locator(CHIP).text_content() == "No project"
    page.keyboard.type("e")
    page.locator(".sheet-menu.inline").wait_for()
    page.keyboard.press("Enter")
    assert page.locator(CHIP).text_content() == "Work › Release"

    # A "#" no name matches is just words; and Esc closes the menu, not the window.
    page.keyboard.type("about leak #42")
    assert page.locator(".sheet-menu").count() == 0
    page.keyboard.type(" #")
    page.locator(".sheet-menu.inline").wait_for()
    page.keyboard.press("Escape")
    assert page.locator(".sheet-menu").count() == 0
    assert page.locator(f"{WINDOW}[open]").count() == 1
    page.keyboard.press("Backspace")

    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="to Work › Release").wait_for()
    filed = task_named(app_db, "Call the plumber about leak #42")
    assert filed == (places["work"], places["release"])


def test_a_hash_files_a_task_on_its_own_page(page, live, app_db, places) -> None:
    with app_db() as db:
        task_id = tasks_svc.create_task(db, title="Prune the roses").id
        db.commit()
    page.goto(f"{live}/tasks/{task_id}")
    title = page.locator(".task-page .sheet-title")
    title.click()
    page.keyboard.press("End")
    page.keyboard.type(" #gard")
    page.locator(".sheet-menu.inline").wait_for()
    page.keyboard.press("Enter")
    page.locator("[data-page-state]", has_text="Saved").wait_for()
    # Saved filed, and under its own words only.
    with app_db() as db:
        task = tasks_svc.get_task(db, task_id)
        assert (task.title, task.project_id, task.workstream_id) == (
            "Prune the roses", places["home"], places["garden"],
        )
        # The "#" and its words were never saved as the title.
        titles = {r.snapshot["title"] for r in history_svc.revisions(db, task_id)}
        assert titles == {"Prune the roses"}


def test_a_projects_pages_start_it_in_that_project(page, live, app_db, places) -> None:
    page.goto(f"{live}/projects/{places['home']}/gantt")
    page.keyboard.press("n")
    page.locator(f"{WINDOW}[open]").wait_for()
    assert page.locator(CHIP).text_content() == "Home"
    page.keyboard.type("Plant tulips")
    page.keyboard.press("Control+Enter")
    page.locator(".cal-toast.show", has_text="Added “Plant tulips” to Home").wait_for()
    page.keyboard.press("Escape")
    # The Gantt draws itself again with it.
    page.locator("#gantt", has_text="Plant tulips").wait_for()
    assert task_named(app_db, "Plant tulips") == (places["home"], None)
