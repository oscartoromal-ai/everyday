"""A project's own page in a real browser: opened from the sidebar, a
repository added on it, its AGENTS.md written on a page of its own and
saved as it is written, and another document added, renamed and deleted.
The `live`, `page` and `app_db` fixtures are conftest.py's."""

import pytest

from app.models import Project, ProjectDoc
from app.services import projects as projects_svc

pytest.importorskip("playwright.sync_api")


def docs(app_db, project: str) -> dict[str, str]:
    with app_db() as db:
        found = db.query(Project).filter_by(name=project).one()
        return {d.name: d.body for d in found.docs}


def test_a_project_page_holds_its_repos_and_its_context(page, live, app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Note-app")
        db.commit()
        project_id = project.id
    page.goto(f"{live}/today")
    page.locator("#rail-projects a", has_text="Note-app").click()
    page.wait_for_url(f"{live}/projects/{project_id}")

    # A repository, named after its folder; the header counts it.
    page.fill("#repo-new", r"C:\code\note-app")
    page.press("#repo-new", "Enter")
    page.locator(".project-repos .item-name", has_text="note-app").wait_for()
    assert "1 repository" in page.inner_text("#project-head .rest")

    # AGENTS.md opens empty, ready to be written, and saves as it is.
    page.locator("a.doc-row", has_text="AGENTS.md").click()
    page.wait_for_url(f"{live}/projects/{project_id}/docs/*")
    page.keyboard.type("# Note-app\nRun uv sync first.")
    page.locator("[data-page-state]", has_text="Saved").wait_for()
    assert docs(app_db, "Note-app")["AGENTS.md"] == "# Note-app\nRun uv sync first."
    page.locator(".page-back", has_text="Note-app").click()
    page.wait_for_url(f"{live}/projects/{project_id}")
    assert page.inner_text("a.doc-row .doc-summary") == "Note-app"

    # Another document: named, then written out on its own page.
    page.fill("#doc-new", "Architecture")
    page.press("#doc-new", "Enter")
    page.wait_for_url(f"{live}/projects/{project_id}/docs/*")
    page.keyboard.type("How the pieces fit.")
    page.locator(".doc-name").click()
    page.keyboard.press("End")
    page.keyboard.type(".md")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.title.startsWith('Architecture.md ·')")
    page.locator("[data-page-state]", has_text="Saved").wait_for()
    assert docs(app_db, "Note-app")["Architecture.md"] == "How the pieces fit."

    # Deleted, it goes back to the project.
    page.locator(".doc-title .task-delete").click()
    page.locator("dialog[open] button", has_text="Delete").click()
    page.wait_for_url(f"{live}/projects/{project_id}")
    assert page.locator("a.doc-row").all_inner_texts()[0].startswith("AGENTS.md")
    with app_db() as db:
        assert db.query(ProjectDoc).filter_by(name="Architecture.md").count() == 0


def test_the_gantt_is_the_projects_next_tab(page, live, app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Note-app")
        db.commit()
        project_id = project.id
    page.goto(f"{live}/projects/{project_id}")
    page.locator(".project-tabs a", has_text="Gantt").click()
    page.wait_for_url(f"{live}/projects/{project_id}/gantt")
    page.locator("#gantt[role=grid]").wait_for()
    assert page.locator(".project-tabs a[aria-current]").inner_text() == "Gantt"
    page.locator(".project-tabs a", has_text="Overview").click()
    page.wait_for_url(f"{live}/projects/{project_id}")
