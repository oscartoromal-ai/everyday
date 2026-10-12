"""A project opened again, in a real browser: from the sidebar, Projects or
the command menu it opens on the page it was left on, as it was left (the
window's scroll, a Gantt's time, rows and cursor); its own tabs, its links
within it and a task's "‹" link go where they say, and a document deleted
since leaves it on its Overview. The `live`, `page` and `app_db` fixtures
are conftest.py's."""

from datetime import date, timedelta

import pytest

from app.models import Project, Task
from app.services import project_files
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")


@pytest.fixture
def project(app_db) -> int:
    """Beta, 40 steps a week apart from today on: rows and weeks to scroll."""
    with app_db() as db:
        project = projects_svc.create_project(db, name="Beta")
        for n in range(40):
            tasks_svc.create_task(
                db,
                title=f"Step {n:02}",
                project_id=project.id,
                due=date.today() + timedelta(weeks=n),
            )
        db.commit()
        return project.id


def _open_from_rail(page, live, name: str = "Beta") -> None:
    page.locator("#rail-projects a", has_text=name).click()


def _gantt(page):
    return page.locator("#gantt")


def test_a_project_opens_again_on_its_gantt_as_it_was_left(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}/gantt")
    row = page.locator('.gantt-row[data-title="Step 30"]')
    row.locator(".gantt-due").click()
    page.keyboard.press("ArrowRight")  # into the time, on its week
    _gantt(page).evaluate("s => { s.scrollLeft = 1500; }")
    left, top = _gantt(page).evaluate("s => [s.scrollLeft, s.scrollTop]")
    assert left > 0 and top > 0
    cursor = row.locator(".is-cursor").get_attribute("data-col")

    page.locator('.nav a[href="/today"]').click()
    page.wait_for_url(f"{live}/today")
    _open_from_rail(page, live)
    page.wait_for_url(f"{live}/projects/{project}/gantt")
    page.locator("#gantt[role=grid]").wait_for()
    assert _gantt(page).evaluate("s => [s.scrollLeft, s.scrollTop]") == [left, top]
    row = page.locator('.gantt-row[data-title="Step 30"]')
    assert row.locator(".is-cursor").get_attribute("data-col") == cursor


def test_its_tasks_open_again_scrolled_from_the_command_menu(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}/tasks")
    page.mouse.move(700, 400)
    page.mouse.wheel(0, 900)
    page.wait_for_function("() => scrollY === 900")

    page.locator('.nav a[href="/today"]').click()
    page.wait_for_url(f"{live}/today")
    page.keyboard.press("Control+k")
    page.locator("#command-dialog[open]").wait_for()
    page.keyboard.type("Beta")
    page.locator(".command-item", has_text="Beta").first.click()
    page.wait_for_url(f"{live}/projects/{project}/tasks")
    page.wait_for_function("() => scrollY === 900")


def test_within_the_project_links_go_where_they_say(page, live, project) -> None:
    page.goto(f"{live}/projects/{project}/gantt")
    page.locator('.nav a[href="/today"]').click()
    _open_from_rail(page, live)
    page.wait_for_url(f"{live}/projects/{project}/gantt*")
    # The project, open: its name in the sidebar is its Overview, as its tab is.
    _open_from_rail(page, live)
    page.wait_for_url(f"{live}/projects/{project}")
    page.locator(".project-tabs a", has_text="Tasks").click()
    page.wait_for_url(f"{live}/projects/{project}/tasks")

    # Opened on Projects, it is where it was left: its Tasks.
    page.goto(f"{live}/projects")
    page.locator(".tl-name", has_text="Beta").click()
    page.wait_for_url(f"{live}/projects/{project}/tasks")


def test_a_tasks_own_link_goes_to_the_page_it_names(page, live, app_db, project) -> None:
    with app_db() as db:
        step = db.query(Task).filter_by(title="Step 05").one().id
    page.goto(f"{live}/projects/{project}/gantt")
    page.goto(f"{live}/tasks/{step}?back=/projects/{project}")
    back = page.locator(".page-back", has_text="Project").first
    back.click()
    page.wait_for_url(f"{live}/projects/{project}")


def test_a_document_deleted_since_leaves_it_on_its_overview(page, live, app_db, project) -> None:
    with app_db() as db:
        beta = db.get(Project, project)
        doc = project_files.create_doc(db, beta, "Plan", body="The plan.")
        db.commit()
    page.goto(f"{live}/projects/{project}/docs/{doc.path}")
    page.locator('.nav a[href="/today"]').click()
    page.wait_for_url(f"{live}/today")
    _open_from_rail(page, live)
    page.wait_for_url(f"{live}/projects/{project}/docs/{doc.path}")

    page.locator('.nav a[href="/today"]').click()
    page.wait_for_url(f"{live}/today")
    with app_db() as db:
        project_files.delete(db, db.get(Project, project), doc.path)
        db.commit()
    _open_from_rail(page, live)
    page.wait_for_url(f"{live}/projects/{project}")
    assert page.locator(".project-tabs a[aria-current]").inner_text() == "Overview"
