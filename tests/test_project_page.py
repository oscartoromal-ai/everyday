"""A project's own page (/projects/<id>): the project at a glance, the
project itself, its repositories and its context, AGENTS.md first; each
document on a page of its own; and the context handed to an agent, over
MCP and the API."""

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app import migrate
from app.mcp.server import mcp
from app.models import AGENTS_DOC, ProjectDoc, ProjectStatus, TaskStatus
from app.services import DomainError, everyday
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.ui.project_view import summary


def test_a_new_project_has_its_agents_md(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    assert [(d.name, d.body) for d in project.docs] == [(AGENTS_DOC, "")]


def test_documents_are_named_once_and_agents_md_stays(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    agents = project.docs[0]
    notes = projects_svc.create_doc(db, project_id=project.id, name="  Architecture   notes ")
    # A document's name is its file's: .md added when not written.
    assert notes.name == "Architecture notes.md"
    for taken in ("agents.md", "ARCHITECTURE NOTES", "architecture notes.MD", "  ", "CON", "a:b"):
        with pytest.raises(DomainError):
            projects_svc.create_doc(db, project_id=project.id, name=taken)
    # Renamed in another case is the same document, not a clash.
    assert (
        projects_svc.update_doc(db, notes.id, name="architecture notes").name
        == "architecture notes.md"
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
    assert f'<a href="/projects/{project.id}/tasks">Tasks</a>' in html
    assert f'<a href="/projects/{project.id}/gantt">Gantt</a>' in html
    assert 'value="C:\\code\\note-app"' in html and ">note-app</span>" in html
    # AGENTS.md first, what it is about beside it; then the others.
    assert html.index(">AGENTS.md<") < html.index(">Architecture.md<")
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


def test_each_card_saves_only_its_own_fields(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app", color=3)
    db.commit()
    # The description alone: its name, status and colour stay.
    client.post(f"/ui/projects/{project.id}/about", data={"notes": " A notes app "})
    db.refresh(project)
    assert (project.name, project.status, project.color, project.notes) == (
        "Note-app",
        ProjectStatus.active,
        3,
        "A notes app",
    )
    # The details alone: the description stays.
    client.post(
        f"/ui/projects/{project.id}/about", data={"name": "Notes", "status": "active", "color": "4"}
    )
    db.refresh(project)
    assert (project.name, project.color, project.notes) == ("Notes", 4, "A notes app")


def test_the_page_opens_on_the_project_at_a_glance(client, db) -> None:
    today = date.today()
    project = projects_svc.create_project(db, name="Note-app")
    tasks_svc.create_task(
        db,
        title="Ship sync",
        project_id=project.id,
        starts_on=today,
        due=today + timedelta(days=20),
    )
    tasks_svc.create_task(db, title="Write the spec", project_id=project.id, status=TaskStatus.done)
    db.commit()
    html = client.get(f"/projects/{project.id}").text
    glance = html.split('id="project-glance"')[1].split("</section>")[0]
    assert '<span class="chip ok">On track</span>' in glance
    assert "1 task open" in glance
    assert "50%" in glance and "1 of 2 tasks done" in glance
    assert 'title="Ship sync">Ship sync</p>' in glance
    assert "3 weeks" in glance
    # Its status changes the glance, drawn again with the header.
    answer = client.post(f"/ui/projects/{project.id}/about", data={"status": "paused"})
    assert 'id="project-glance" hx-swap-oob="true"' in answer.text
    assert '<span class="chip neutral">Paused</span>' in answer.text


def test_repositories_are_added_changed_and_removed(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    db.commit()
    added = client.post(f"/ui/projects/{project.id}/repos", data={"location": "C:/code/note-app"})
    assert 'id="project-repos"' in added.text and ">note-app</span>" in added.text
    # The header's count comes with it.
    assert 'hx-swap-oob="true"' in added.text and "1 repository" in added.text
    repo = project.repos[0]
    changed = client.post(f"/ui/repos/{repo.id}", data={"location": "C:/code/notes"})
    assert ">notes</span>" in changed.text
    assert client.post(f"/ui/repos/{repo.id}", data={"location": " "}).status_code == 422
    gone = client.post(f"/ui/repos/{repo.id}/delete")
    assert ">notes</span>" not in gone.text
    db.refresh(project)
    assert project.repos == []


def test_the_line_to_add_a_repository_offers_his_github_ones(client, db) -> None:
    from github_fake import repo_payload

    from app.models import GitHubSource, Repository
    from app.services import github as github_svc

    project = projects_svc.create_project(db, name="Note-app")
    db.commit()
    url = f"/ui/projects/{project.id}/repo-options"
    # Before GitHub is connected: where to connect it.
    assert 'href="/repositories">Connect GitHub</a>' in client.get(url).text
    assert "Enter adds" in client.get(url, params={"location": r"C:\code"}).text

    link = github_svc.connect(db, {"id": 1, "login": "me", "name": "Me"}, GitHubSource.cli)
    found = [
        repo_payload(i, f"repo-{i}", owner="me", pushed_at=f"2026-10-{i:02d}T10:00:00Z")
        for i in range(1, 12)
    ]
    found.append(repo_payload(20, "legacy", owner="acme-labs", archived=True))
    github_svc.keep_repositories(db, link, found)
    projects_svc.add_repo(db, project_id=project.id, location="git@github.com:me/repo-11.git")
    db.commit()
    assert db.query(Repository).count() == 12

    # Focused: the active ones not the project's yet, last pushed first, eight at most.
    offered = client.get(url).text
    assert offered.count('role="option"') == 8
    assert "repo-11" not in offered and "legacy" not in offered
    assert offered.index(">repo-10<") < offered.index(">repo-9<")
    assert 'data-location="https://github.com/me/repo-10"' in offered
    assert "2 more: keep writing to find them." in offered
    assert 'class="repo-owner"' not in offered  # his own go by their names

    legacy = client.get(url, params={"location": "LEGACY"}).text
    assert legacy.count('role="option"') == 1 and "acme-labs/" in legacy and "Archived" in legacy
    named = client.get(url, params={"location": "https://github.com/me/repo-3"}).text
    assert named.count('role="option"') == 1 and ">repo-3<" in named
    nothing = client.get(url, params={"location": r"C:\code\notes"}).text
    assert "Enter adds “C:\\code\\notes” as written." in nothing and 'role="option"' not in nothing
    assert client.get("/ui/projects/999/repo-options").status_code == 404

    # Just added, the line is quiet as the focus comes back to it.
    added = client.post(
        f"/ui/projects/{project.id}/repos", data={"location": "https://github.com/me/repo-3"}
    )
    assert "data-repo-picker data-quiet" in added.text
    assert ">repo-3<" not in client.get(url, params={"location": "repo-3"}).text


def test_a_document_is_added_written_renamed_and_deleted(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    db.commit()
    added = client.post(f"/ui/projects/{project.id}/docs", data={"name": "Architecture"})
    doc = db.query(ProjectDoc).filter_by(name="Architecture.md").one()
    assert added.headers["HX-Redirect"] == f"/projects/{project.id}/docs/{doc.id}"
    page = client.get(f"/projects/{project.id}/docs/{doc.id}").text
    assert "<title>Architecture.md · Note-app · Personal Calendar</title>" in page
    assert f'<a class="page-back" href="/projects/{project.id}">Note-app</a>' in page
    assert 'data-doc-name value="Architecture.md"' in page
    assert '<span class="doc-file" data-doc-file>projects' in page

    saved = client.post(f"/ui/docs/{doc.id}", data={"body": "# How\r\nIt fits.", "name": "Design"})
    # Answered with its version and its name, a file's.
    assert saved.json() == {
        "version": everyday.version("# How\nIt fits."),
        "name": "Design.md",
        "file": str(Path("projects", "note-app", "Design.md")),
    }
    db.refresh(doc)
    assert (doc.name, doc.body) == ("Design.md", "# How\nIt fits.")
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
        ("Architecture.md", "It fits."),
    ]
    assert context["folder"] == str(everyday.projects_dir() / "note-app")


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
            "path": "AGENTS.md",
            "body": "Run uv sync.",
            "updated_at": by_id["docs"][0]["updated_at"],
        }
        assert by_id["folders"] == []
        listed = (await client.call_tool("list_projects", {})).data
        assert listed[0]["repos"] == ["C:/code/note-app"]
        with pytest.raises(ToolError):
            await client.call_tool("get_project_context", {"name": "Nope"})


def test_folders_nest_and_names_are_unique_beside_each_other(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    decisions = projects_svc.create_folder(db, project_id=project.id, name=" decisions ")
    adr = projects_svc.create_folder(db, project_id=project.id, name="adr", parent_id=decisions.id)
    assert (decisions.name, adr.path) == ("decisions", "decisions/adr")
    # A folder and a document share their names, as on disk, in any case.
    for taken in ("Decisions", "AGENTS.md"):
        with pytest.raises(DomainError, match="already has"):
            projects_svc.create_folder(db, project_id=project.id, name=taken)
    # A document is its file, Markdown: "decisions" is decisions.md, beside the folder.
    assert projects_svc.create_doc(db, project_id=project.id, name="decisions").name == (
        "decisions.md"
    )
    with pytest.raises(DomainError, match="already has adr"):
        projects_svc.create_folder(db, project_id=project.id, name="ADR", parent_id=decisions.id)
    # The same name in another folder is another document, AGENTS.md too.
    inner = projects_svc.create_doc(db, project_id=project.id, name="AGENTS.md", folder_id=adr.id)
    assert inner.path == "decisions/adr/AGENTS.md" and not inner.is_agents
    with pytest.raises(DomainError, match="slash"):
        projects_svc.update_doc(db, inner.id, name="a/b")
    # Another project's folder is not one to file into.
    other = projects_svc.create_project(db, name="Other")
    with pytest.raises(DomainError, match="not one of"):
        projects_svc.create_doc(db, project_id=other.id, name="x", folder_id=adr.id)


def test_a_path_makes_the_folders_it_names(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    first = projects_svc.create_doc(db, project_id=project.id, name="decisions/adr/0001.md")
    second = projects_svc.create_doc(db, project_id=project.id, name="Decisions\\adr\\0002.md")
    assert (first.path, second.path) == ("decisions/adr/0001.md", "decisions/adr/0002.md")
    assert [f.path for f in projects_svc.folders_of(project)] == ["decisions", "decisions/adr"]
    deep = projects_svc.create_folder(
        db, project_id=project.id, name="2026/oct", parent_id=first.folder.id
    )
    assert deep.path == "decisions/adr/2026/oct"


def test_documents_and_folders_move_but_never_into_themselves(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    agents = project.docs[0]
    a = projects_svc.create_folder(db, project_id=project.id, name="a")
    b = projects_svc.create_folder(db, project_id=project.id, name="b", parent_id=a.id)
    doc = projects_svc.create_doc(db, project_id=project.id, name="Plan.md")
    projects_svc.update_doc(db, doc.id, folder_id=b.id)
    assert doc.path == "a/b/Plan.md"
    projects_svc.update_doc(db, doc.id, folder_id=None)
    assert doc.path == "Plan.md"
    for inside in (a.id, b.id):
        with pytest.raises(DomainError, match="inside itself"):
            projects_svc.update_folder(db, a.id, parent_id=inside)
    projects_svc.update_folder(db, b.id, parent_id=None, name="c")
    assert b.path == "c"
    # Moved where its name is taken, it stays put.
    projects_svc.create_doc(db, project_id=project.id, name="plan.md", folder_id=a.id)
    with pytest.raises(DomainError, match="already has plan.md"):
        projects_svc.update_doc(db, doc.id, folder_id=a.id)
    with pytest.raises(DomainError, match="stays at the top"):
        projects_svc.update_doc(db, agents.id, folder_id=a.id)


def test_a_folder_is_deleted_with_everything_in_it(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    projects_svc.create_doc(db, project_id=project.id, name="a/b/deep.md")
    projects_svc.create_doc(db, project_id=project.id, name="a/top.md")
    kept = projects_svc.create_doc(db, project_id=project.id, name="kept.md")
    a = projects_svc.folders_of(project)[0]
    projects_svc.delete_folder(db, a.id)
    db.commit()
    db.expire_all()
    assert [d.name for d in db.query(ProjectDoc).all()] == ["AGENTS.md", "kept.md"]
    assert projects_svc.folders_of(project) == [] and kept in project.docs


def test_the_context_reads_as_its_tree(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    for name in ("zeta.md", "Plan 10.md", "Plan 2.md", "b/two.md", "a/one.md", "a/c/three.md"):
        projects_svc.create_doc(db, project_id=project.id, name=name)
    projects_svc.create_folder(db, project_id=project.id, name="empty")
    # AGENTS.md, then each folder's (its subfolders' first), then the rest,
    # by name, its numbers as numbers.
    assert [d.path for d in projects_svc.docs_of(project)] == [
        "AGENTS.md",
        "a/c/three.md",
        "a/one.md",
        "b/two.md",
        "Plan 2.md",
        "Plan 10.md",
        "zeta.md",
    ]
    context = projects_svc.project_context(project)
    assert context["folders"] == ["a", "a/c", "b", "empty"]
    assert context["docs"][1]["name"] == "three.md"


def test_the_tree_is_drawn_and_worked_on_the_page(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    doc = projects_svc.create_doc(db, project_id=project.id, name="Plan.md")
    db.commit()
    made = client.post(f"/ui/projects/{project.id}/folders", data={"name": "decisions"})
    assert 'id="project-context"' in made.text and 'data-name="decisions"' in made.text
    assert ">Empty</span>" in made.text and 'hx-swap-oob="true"' in made.text
    folder = projects_svc.folders_of(project)[0]

    # A document written in the folder opens on its own page.
    added = client.post(
        f"/ui/projects/{project.id}/docs", data={"name": "0001.md", "folder": str(folder.id)}
    )
    inner = db.query(ProjectDoc).filter_by(name="0001.md").one()
    assert inner.folder_id == folder.id
    assert added.headers["HX-Redirect"] == f"/projects/{project.id}/docs/{inner.id}"

    # Folded, it stays so; a document dragged into it opens it again.
    assert client.post(f"/ui/folders/{folder.id}/fold", data={"folded": "true"}).status_code == 204
    db.refresh(folder)
    assert folder.folded
    assert f'id="ctx-in-{folder.id}" hidden' in client.get(f"/projects/{project.id}").text
    moved = client.post(f"/ui/docs/{doc.id}/place", data={"folder": str(folder.id)})
    assert "2 documents" in moved.text and f'id="ctx-in-{folder.id}" hidden' not in moved.text
    db.refresh(doc)
    assert doc.folder_id == folder.id

    # Renamed on the tree; back to the top from its own page.
    client.post(f"/ui/folders/{folder.id}/place", data={"name": "adr"})
    db.refresh(folder)
    assert folder.name == "adr"
    page = client.get(f"/projects/{project.id}/docs/{doc.id}").text
    assert f'<option value="{folder.id}" selected>adr</option>' in page
    assert client.post(f"/ui/docs/{doc.id}", data={"folder": "top"}).status_code == 200
    db.refresh(doc)
    assert doc.folder_id is None
    assert client.post(f"/ui/docs/{doc.id}/place", data={"name": "AGENTS.md"}).status_code == 422
    # Dragged into the folder and out to the top again.
    client.post(f"/ui/docs/{doc.id}/place", data={"folder": str(folder.id)})
    client.post(f"/ui/docs/{doc.id}/place", data={"folder": "top"})
    db.refresh(doc)
    assert doc.folder_id is None

    # Deleted on the tree: the tree comes back, the folder and its contents gone.
    gone = client.post(f"/ui/docs/{doc.id}/delete?tree=1")
    assert 'id="project-context"' in gone.text and 'data-name="Plan.md"' not in gone.text
    gone = client.post(f"/ui/folders/{folder.id}/delete")
    assert 'data-name="adr"' not in gone.text
    assert db.query(ProjectDoc).filter_by(name="0001.md").count() == 0


def test_the_folders_migration_keeps_every_document(tmp_path) -> None:
    path = tmp_path / "app.db"
    command.upgrade(migrate._config(path), "a9d3f6e21c48")  # the revision before
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO projects (name, status, notes, color, folded, position, created_at) "
            "VALUES ('Old one', 'active', '', 1, 0, 0, '2026-09-01 10:00:00')"
        )
        db.execute(
            "INSERT INTO project_docs (project_id, name, body, updated_at) "
            "VALUES (1, 'AGENTS.md', 'Run it.', '2026-09-01 10:00:00')"
        )
    migrate.upgrade(path)
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT project_id, name, body, folder_id FROM project_docs").fetchall()
        # The same name in two folders is allowed by the table now.
        db.execute("INSERT INTO project_doc_folders (project_id, name, folded) VALUES (1, 'a', 0)")
        db.execute(
            "INSERT INTO project_docs (project_id, folder_id, name, body, updated_at) "
            "VALUES (1, 1, 'AGENTS.md', '', '2026-09-01 10:00:00')"
        )
    assert rows == [(1, "AGENTS.md", "Run it.", None)]


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
