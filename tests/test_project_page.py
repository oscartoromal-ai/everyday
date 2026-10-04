"""A project's own page (/projects/<id>): the project, its repositories and
its context, AGENTS.md first; each document on a page of its own; and the
context handed to an agent, over MCP and the API."""

import sqlite3
from datetime import datetime

import pytest
from alembic import command
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app import migrate
from app.mcp.server import mcp
from app.models import AGENTS_DOC, ProjectDoc, ProjectStatus
from app.services import DomainError
from app.services import projects as projects_svc
from app.ui.project_view import summary


def test_a_new_project_has_its_agents_md(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    assert [(d.name, d.body) for d in project.docs] == [(AGENTS_DOC, "")]


def test_documents_are_named_once_and_agents_md_stays(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    agents = project.docs[0]
    notes = projects_svc.create_doc(db, project_id=project.id, name="  Architecture   notes ")
    assert notes.name == "Architecture notes"
    for taken in ("agents.md", "ARCHITECTURE NOTES", "  "):
        with pytest.raises(DomainError):
            projects_svc.create_doc(db, project_id=project.id, name=taken)
    # Renamed in another case is the same document, not a clash.
    assert (
        projects_svc.update_doc(db, notes.id, name="architecture notes").name
        == "architecture notes"
    )
    with pytest.raises(DomainError, match="keeps its name"):
        projects_svc.update_doc(db, agents.id, name="README.md")
    with pytest.raises(DomainError, match="keeps its"):
        projects_svc.delete_doc(db, agents.id)
    projects_svc.delete_doc(db, notes.id)
    assert [d.name for d in project.docs] == [AGENTS_DOC]


def test_a_document_is_dated_when_its_words_change(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    doc = project.docs[0]
    doc.updated_at = datetime(2026, 1, 1)
    projects_svc.update_doc(db, doc.id, body=doc.body)
    assert doc.updated_at == datetime(2026, 1, 1)
    projects_svc.update_doc(db, doc.id, body="# Note-app")
    assert doc.updated_at > datetime(2026, 1, 1)


def test_a_repository_is_named_after_where_it_is(db) -> None:
    for location, name in [
        (r"C:\Users\me\note-app", "note-app"),
        ("C:/code/app/", "app"),
        ("https://github.com/me/note-app-server.git", "note-app-server"),
    ]:
        assert projects_svc.repo_name(location) == name
    project = projects_svc.create_project(db, name="Note-app")
    with pytest.raises(DomainError):
        projects_svc.add_repo(db, project_id=project.id, location="   ")


def test_a_documents_summary_is_its_first_words() -> None:
    assert summary("\n\n## Build it\nuv sync") == "Build it"
    assert summary("") == ""


def test_the_page_shows_the_project_its_repos_and_its_context(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app", color=3)
    projects_svc.add_repo(db, project_id=project.id, location=r"C:\code\note-app")
    projects_svc.update_doc(db, project.docs[0].id, body="# Note-app\n\nA notes app.")
    other = projects_svc.create_doc(db, project_id=project.id, name="Architecture")
    db.commit()
    html = client.get(f"/projects/{project.id}").text
    assert "<title>Note-app · Personal Calendar</title>" in html
    assert "Active · nothing open · 1 repository · 2 documents" in html
    assert f'<a href="/projects/{project.id}" aria-current="page">Overview</a>' in html
    assert f'<a href="/projects/{project.id}/gantt">Gantt</a>' in html
    assert 'value="C:\\code\\note-app"' in html and "<span>note-app</span>" in html
    # AGENTS.md first, what it is about beside it; then the others.
    assert html.index(">AGENTS.md<") < html.index(">Architecture<")
    assert '<span class="doc-summary">Note-app</span>' in html
    assert f'href="/projects/{project.id}/docs/{other.id}"' in html
    # Its own row in the sidebar is current, as on its Gantt.
    nav = html.split('id="rail-projects"')[1].split("</ul>")[0]
    assert 'aria-current="page"' in nav.split(f'href="/projects/{project.id}"')[1].split(">")[0]


def test_a_missing_project_or_document_is_not_found(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    db.commit()
    assert client.get("/projects/999").status_code == 404
    assert client.get(f"/projects/{project.id}/docs/999").status_code == 404
    # A document is found under its own project only.
    second = projects_svc.create_project(db, name="Other")
    db.commit()
    assert client.get(f"/projects/{second.id}/docs/{project.docs[0].id}").status_code == 404


def test_the_project_is_written_on_its_page(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    db.commit()
    answer = client.post(
        f"/ui/projects/{project.id}/about",
        data={
            "name": "Notes",
            "status": "paused",
            "color": "5",
            "notes": " A notes app ",
        },
    )
    assert answer.headers["HX-Trigger"] == "projects:changed"
    assert 'id="project-head"' in answer.text and "<span>Notes</span>" in answer.text
    assert "Paused · nothing open" in answer.text
    db.refresh(project)
    assert (project.name, project.status, project.color, project.notes) == (
        "Notes",
        ProjectStatus.paused,
        5,
        "A notes app",
    )


def test_repositories_are_added_changed_and_removed(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    db.commit()
    added = client.post(f"/ui/projects/{project.id}/repos", data={"location": "C:/code/note-app"})
    assert 'id="project-repos"' in added.text and "<span>note-app</span>" in added.text
    # The header's count comes with it.
    assert 'hx-swap-oob="true"' in added.text and "1 repository" in added.text
    repo = project.repos[0]
    changed = client.post(f"/ui/repos/{repo.id}", data={"location": "C:/code/notes"})
    assert "<span>notes</span>" in changed.text
    assert client.post(f"/ui/repos/{repo.id}", data={"location": " "}).status_code == 422
    gone = client.post(f"/ui/repos/{repo.id}/delete")
    assert "<span>notes</span>" not in gone.text
    db.refresh(project)
    assert project.repos == []


def test_a_document_is_added_written_renamed_and_deleted(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    db.commit()
    added = client.post(f"/ui/projects/{project.id}/docs", data={"name": "Architecture"})
    doc = db.query(ProjectDoc).filter_by(name="Architecture").one()
    assert added.headers["HX-Redirect"] == f"/projects/{project.id}/docs/{doc.id}"
    page = client.get(f"/projects/{project.id}/docs/{doc.id}").text
    assert "<title>Architecture · Note-app · Personal Calendar</title>" in page
    assert f'<a class="page-back" href="/projects/{project.id}">Note-app</a>' in page
    assert 'data-doc-name value="Architecture"' in page

    saved = client.post(
        f"/ui/docs/{doc.id}", data={"body": "# How\r\nIt fits.", "name": "Architecture.md"}
    )
    assert saved.status_code == 204
    db.refresh(doc)
    assert (doc.name, doc.body) == ("Architecture.md", "# How\nIt fits.")
    assert client.post(f"/ui/docs/{doc.id}", data={"name": "AGENTS.md"}).status_code == 422

    deleted = client.post(f"/ui/docs/{doc.id}/delete")
    assert deleted.headers["HX-Redirect"] == f"/projects/{project.id}"
    assert db.get(ProjectDoc, doc.id) is None


def test_agents_md_has_no_name_to_write_and_no_bin(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    db.commit()
    page = client.get(f"/projects/{project.id}/docs/{project.docs[0].id}").text
    assert "<h1>AGENTS.md</h1>" in page and "data-doc-name" not in page
    assert "/delete" not in page.split('class="doc-title"')[1].split("</div>")[0]
    assert client.post(f"/ui/docs/{project.docs[0].id}/delete").status_code == 422


def test_the_context_is_handed_over_the_api(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    projects_svc.create_doc(db, project_id=project.id, name="Architecture", body="It fits.")
    projects_svc.update_doc(db, project.docs[0].id, body="Run uv sync.")
    projects_svc.add_repo(db, project_id=project.id, location="C:/code/note-app")
    db.commit()
    context = client.get(f"/api/projects/{project.id}/context").json()
    assert context["name"] == "Note-app" and context["status"] == "active"
    assert context["repos"] == [{"name": "note-app", "location": "C:/code/note-app"}]
    assert [(d["name"], d["body"]) for d in context["docs"]] == [
        ("AGENTS.md", "Run uv sync."),
        ("Architecture", "It fits."),
    ]


async def test_the_context_is_handed_over_mcp(app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Note-app")
        projects_svc.update_doc(db, project.docs[0].id, body="Run uv sync.")
        projects_svc.add_repo(db, project_id=project.id, location="C:/code/note-app")
        db.commit()
        project_id = project.id
    async with Client(mcp) as client:
        by_id = (await client.call_tool("get_project_context", {"project_id": project_id})).data
        by_name = (await client.call_tool("get_project_context", {"name": "Note-app"})).data
        assert by_id == by_name
        assert by_id["docs"][0] == {
            "name": "AGENTS.md",
            "body": "Run uv sync.",
            "updated_at": by_id["docs"][0]["updated_at"],
        }
        listed = (await client.call_tool("list_projects", {})).data
        assert listed[0]["repos"] == ["C:/code/note-app"]
        with pytest.raises(ToolError):
            await client.call_tool("get_project_context", {"name": "Nope"})


def test_the_migration_gives_every_project_its_agents_md(tmp_path) -> None:
    path = tmp_path / "app.db"
    command.upgrade(migrate._config(path), "d5a77acb11b0")  # the revision before
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO projects (name, status, notes, color, folded, created_at) "
            "VALUES ('Old one', 'active', '', 1, 0, '2026-09-01 10:00:00')"
        )
    migrate.upgrade(path)
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT project_id, name, body FROM project_docs").fetchall()
    assert rows == [(1, "AGENTS.md", "")]
