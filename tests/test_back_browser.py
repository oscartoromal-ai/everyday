"""Back in a real browser: the sidebar's Back names the page before and goes
back to it as it is now and as it was left (its scroll, a Gantt's cursor),
as Alt+Left does; a page's own "‹" link and a task deleted on its page go
back the same way. The `live`, `page` and `app_db` fixtures are conftest.py's."""

import pytest

from app.models import Task
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")


@pytest.fixture
def project(app_db) -> int:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Beta")
        for n in range(40):
            tasks_svc.create_task(db, title=f"Step {n:02}", project_id=project.id)
        db.commit()
        return project.id


def _task_id(app_db, title: str) -> int:
    with app_db() as db:
        return db.query(Task).filter_by(title=title).one().id


def _back(page):
    return page.locator("[data-back]")


def _index(page) -> int:
    return page.evaluate("navigation.currentEntry.index")


def test_pages_are_never_cached(client) -> None:
    # Back draws the page before as it is now, not as it was first drawn.
    assert client.get("/projects").headers["cache-control"] == "no-store"
    assert "no-store" not in client.get("/static/app.css").headers.get("cache-control", "")


def test_back_names_the_page_before_and_goes_back_as_it_was_left(page, live, project) -> None:
    page.goto(f"{live}/projects")
    # The window's first page: nothing to go back to, Back faint in its place.
    assert _back(page).is_disabled()
    assert _back(page).inner_text() == "Back"
    page.mouse.move(700, 400)
    page.mouse.wheel(0, 900)
    page.wait_for_function("() => scrollY === 900")

    page.locator("#rail-projects a", has_text="Beta").click()
    page.wait_for_url(f"{live}/projects/{project}")
    assert _back(page).is_enabled()
    assert _back(page).inner_text() == "Back to Projects"
    assert _back(page).get_attribute("title") == "Back to Projects (Alt+←)"

    _back(page).click()
    page.wait_for_url(f"{live}/projects")
    page.wait_for_function("() => scrollY === 900")
    assert _back(page).is_disabled()


def test_a_task_opened_from_the_gantt_comes_back_to_its_cursor(page, live, app_db, project) -> None:
    step = _task_id(app_db, "Step 30")
    page.goto(f"{live}/projects/{project}/gantt")
    row = page.locator('.gantt-row[data-title="Step 30"]')
    row.locator(".gantt-due").click()
    top = page.locator("#gantt").evaluate("s => s.scrollTop")
    assert top > 0  # Step 30 is brought into view, below the first rows
    page.keyboard.press("Control+Enter")
    page.wait_for_url(f"{live}/tasks/{step}")
    assert _back(page).inner_text() == "Back to Beta · Gantt"

    # Written out on its page, then back with Alt+Left.
    page.locator(".sheet-title").click()
    page.keyboard.press("End")
    page.keyboard.type(" done right")
    page.keyboard.press("Escape")
    page.wait_for_function("() => document.title.startsWith('Step 30 done right ·')")
    page.keyboard.press("Alt+ArrowLeft")
    page.wait_for_url(f"{live}/projects/{project}/gantt*")

    # The Gantt as it is now, the cursor on the task's cell, focused, the
    # same rows in view.
    row = page.locator('.gantt-row[data-title="Step 30 done right"]')
    assert row.evaluate("r => r.classList.contains('has-cursor')")
    assert row.locator(".gantt-due").evaluate(
        "c => c.classList.contains('is-cursor') && c === document.activeElement"
    )
    assert page.locator("#gantt").evaluate("s => s.scrollTop") == top
    assert _back(page).is_disabled()  # the Gantt was the window's first page


def test_a_pages_own_link_goes_back_when_it_names_the_page_before(page, live, project) -> None:
    page.goto(f"{live}/projects")
    page.locator("#rail-projects a", has_text="Beta").click()
    page.wait_for_url(f"{live}/projects/{project}")
    at = _index(page)
    page.locator(".page-back", has_text="Projects").click()
    page.wait_for_url(f"{live}/projects")
    assert _index(page) == at - 1  # back, not a new page on top

    # From elsewhere it opens the page it names.
    page.goto(f"{live}/today")
    page.goto(f"{live}/projects/{project}")
    at = _index(page)
    page.locator(".page-back", has_text="Projects").click()
    page.wait_for_url(f"{live}/projects")
    assert _index(page) == at + 1
    assert _back(page).inner_text() == "Back to Beta"


def test_a_task_deleted_on_its_page_goes_back_to_where_it_was_opened(
    page, live, app_db, project
) -> None:
    step = _task_id(app_db, "Step 05")
    page.goto(f"{live}/projects/{project}/gantt")
    page.locator('.gantt-row[data-title="Step 05"] .gantt-due').click()
    page.keyboard.press("Control+Enter")
    page.wait_for_url(f"{live}/tasks/{step}")
    at = _index(page)
    page.locator(".task-page .task-delete").click()
    page.locator("#confirm-dialog [value=go]").click()
    page.wait_for_url(f"{live}/projects/{project}/gantt*")
    assert _index(page) == at - 1
    assert page.locator('.gantt-row[data-title="Step 05"]').count() == 0
