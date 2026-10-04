"""A project's own page in a real browser: opened from the sidebar, a
repository added on it, its AGENTS.md written on a page of its own and
saved as it is written, and another document added, renamed and deleted.
The `live`, `page` and `app_db` fixtures are conftest.py's."""

import re

import pytest

from app.models import Project, ProjectDoc
from app.services import everyday
from app.services import projects as projects_svc

pytest.importorskip("playwright.sync_api")

# "Saved" alone, not "Not saved".
SAVED = re.compile("^Saved$")


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
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    assert docs(app_db, "Note-app")["AGENTS.md"] == "# Note-app\nRun uv sync first."
    page.locator(".page-back", has_text="Note-app").click()
    page.wait_for_url(f"{live}/projects/{project_id}")
    assert page.inner_text("a.doc-row .doc-summary") == "Note-app"

    # Another document: named, then written out on its own page.
    page.fill("#doc-new", "Architecture")
    page.press("#doc-new", "Enter")
    page.wait_for_url(f"{live}/projects/{project_id}/docs/*")
    page.keyboard.type("How the pieces fit.")
    assert page.input_value(".doc-name") == "Architecture.md"
    # Renamed, its name is made a file's: .md added.
    page.fill(".doc-name", "Design")
    page.press(".doc-name", "Enter")
    page.wait_for_function("() => document.title.startsWith('Design.md ·')")
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    assert page.input_value(".doc-name") == "Design.md"
    assert page.inner_text("[data-doc-file]").endswith("Design.md")
    assert docs(app_db, "Note-app")["Design.md"] == "How the pieces fit."

    # Deleted, it goes back to the project.
    page.locator(".doc-title .task-delete").click()
    page.locator("dialog[open] button", has_text="Delete").click()
    page.wait_for_url(f"{live}/projects/{project_id}")
    assert page.locator("a.doc-row").all_inner_texts()[0].startswith("AGENTS.md")
    with app_db() as db:
        assert db.query(ProjectDoc).filter_by(name="Design.md").count() == 0


def test_a_document_written_elsewhere_is_never_overwritten(page, live, app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Note-app")
        db.commit()
        project_id, doc_id = project.id, project.docs[0].id
    file = everyday.projects_dir() / "note-app" / "AGENTS.md"
    page.goto(f"{live}/projects/{project_id}/docs/{doc_id}")
    page.locator(".doc-body .cm-content").wait_for()

    # An agent writes the file; what is written here then is not saved over it.
    file.write_text("An agent's words.", encoding="utf-8")
    page.locator(".doc-body .cm-content").click()
    page.keyboard.type("Mine")
    page.locator("[data-doc-stale]").wait_for(state="visible")
    assert page.inner_text("[data-page-state]") == "Not saved"
    assert file.read_text(encoding="utf-8") == "An agent's words."

    # Shown, the agent's version is the one written on.
    page.locator("[data-doc-reload]").click()
    page.locator("[data-doc-stale]").wait_for(state="hidden")
    assert page.evaluate("window.DocEditor.text()") == "An agent's words."
    page.locator(".doc-body .cm-content").click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" And mine.")
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    assert file.read_text(encoding="utf-8") == "An agent's words. And mine."

    # Or kept: written over the agent's.
    file.write_text("The agent again.", encoding="utf-8")
    page.keyboard.type(" Still mine.")
    page.locator("[data-doc-stale]").wait_for(state="visible")
    page.locator("[data-doc-keep]").click()
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    assert file.read_text(encoding="utf-8") == "An agent's words. And mine. Still mine."

    # Back to the tab, the file is shown as it is now.
    file.write_text("Rewritten while away.", encoding="utf-8")
    page.evaluate(
        """() => {
            Object.defineProperty(
                document, "visibilityState", { value: "visible", configurable: true }
            );
            document.dispatchEvent(new Event("visibilitychange"));
        }"""
    )
    page.wait_for_function("() => window.DocEditor.text() === 'Rewritten while away.'")


def paths(app_db, project: str) -> list[str]:
    with app_db() as db:
        return [d.path for d in db.query(Project).filter_by(name=project).one().docs]


def test_the_context_is_filed_in_folders_on_its_tree(page, live, app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Note-app")
        projects_svc.create_doc(db, project_id=project.id, name="Plan.md", body="# Plan")
        db.commit()
        url = f"{live}/projects/{project.id}"
    page.goto(url)
    tree = page.locator("#project-context")

    # New folder: named in a row at the top, Enter keeps it, and it lands focused.
    tree.locator(".ctx-new-folder").click()
    page.keyboard.type("decisions")
    page.keyboard.press("Enter")
    decisions = tree.locator(".ctx-folder[data-name='decisions']")
    decisions.wait_for()
    assert page.evaluate("document.activeElement.closest('.ctx-node')?.dataset.name") == "decisions"
    assert decisions.locator(".doc-meta").text_content() == "Empty"

    # A subfolder from the folder's own tools; Esc on a new row lets it go.
    decisions.locator(":scope > .ctx-row").hover()
    decisions.locator(":scope > .ctx-row [data-ctx-new='folder']").click()
    page.keyboard.press("Escape")
    assert tree.locator(".ctx-draft").count() == 0
    decisions.locator(":scope > .ctx-row").hover()
    decisions.locator(":scope > .ctx-row [data-ctx-new='folder']").click()
    page.keyboard.type("adr")
    page.keyboard.press("Enter")
    tree.locator(".ctx-folder[data-name='decisions'] .ctx-folder[data-name='adr']").wait_for()

    # A document dragged into a folder, and out to the top again.
    plan = tree.locator(".ctx-doc[data-name='Plan.md'] > .ctx-row")
    plan.drag_to(decisions.locator(":scope > .ctx-row"))
    decisions.locator(".ctx-doc[data-name='Plan.md']").wait_for()
    assert "decisions/Plan.md" in paths(app_db, "Note-app")
    tree.locator(".ctx-doc[data-name='Plan.md'] > .ctx-row").drag_to(
        tree.locator(".ctx-doc[data-name='AGENTS.md'] > .ctx-row")
    )
    tree.locator("[data-ctx-root] > .ctx-doc[data-name='Plan.md']").wait_for()

    # F2 renames, the name before its extension chosen to be written over.
    tree.locator(".ctx-doc[data-name='Plan.md'] .ctx-open").focus()
    page.keyboard.press("F2")
    page.keyboard.type("Roadmap")
    page.keyboard.press("Enter")
    tree.locator(".ctx-doc[data-name='Roadmap.md']").wait_for()

    # Folded, it stays folded when the page comes back.
    decisions.locator(":scope > .ctx-row .ctx-toggle").click()
    page.wait_for_load_state("networkidle")
    page.reload()
    assert decisions.locator(":scope > .ctx-group").is_hidden()
    assert decisions.locator(".ctx-toggle").first.get_attribute("aria-expanded") == "false"

    # A document written in a folder as a path opens on its own page.
    page.fill("#doc-new", "decisions/adr/0001.md")
    page.press("#doc-new", "Enter")
    page.wait_for_url(f"{url}/docs/*")
    assert page.locator(".doc-folder select option:checked").inner_text() == "decisions/adr"
    page.goto(url)

    # Deleted, after asking, with everything in it.
    decisions.locator(":scope > .ctx-row .ctx-open").focus()
    page.keyboard.press("Delete")
    page.locator("dialog[open] .confirm-detail", has_text="and the 1 document in it").wait_for()
    page.locator("dialog[open] button", has_text="Delete").click()
    decisions.wait_for(state="detached")
    assert sorted(paths(app_db, "Note-app")) == ["AGENTS.md", "Roadmap.md"]


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


def test_a_document_is_drawn_as_it_reads_and_opens_in_its_last_mode(page, live, app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Note-app")
        # Written as the app writes it: its file first, the master copy.
        projects_svc.update_doc(
            db,
            project.docs[0].id,
            body="# Note-app\n- Run `uv sync` first\n- [ ] Write the deploy steps",
        )
        db.commit()
        url = f"{live}/projects/{project.id}/docs/{project.docs[0].id}"
    page.goto(url)
    editor = page.locator(".doc-body .cm-content")
    modes = page.locator("[data-md-modes]")
    # Live: the heading drawn without its "#", a bullet and a box drawn.
    assert modes.locator('[aria-pressed="true"]').inner_text() == "Live"
    assert editor.locator(".cm-line.cm-md-h1").inner_text() == "Note-app"
    assert editor.locator(".cm-md-bullet").count() == 1
    assert editor.locator(".cm-md-box").count() == 1

    # Source: its Markdown as written, and written there.
    modes.locator("button", has_text="Source").click()
    assert editor.locator(".cm-line").first.inner_text() == "# Note-app"
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")  # out of the list
    page.keyboard.type("## Tests")
    page.locator("[data-page-state]", has_text=SAVED).wait_for()
    assert docs(app_db, "Note-app")["AGENTS.md"].endswith("\n## Tests")

    # Reading (Ctrl+E), and opened again in it; Ctrl+E goes back to Source.
    page.keyboard.press("Control+e")
    assert editor.get_attribute("contenteditable") == "false"
    page.reload()
    assert modes.locator('[aria-pressed="true"]').inner_text() == "Reading"
    page.keyboard.press("Control+e")
    assert modes.locator('[aria-pressed="true"]').inner_text() == "Live"
