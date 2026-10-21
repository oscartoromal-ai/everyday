"""A project's own page (/projects/<id>): the project at a glance, the
project itself, its repositories and its context, AGENTS.md first; each
document on a page of its own; and the context handed to an agent, over
MCP and the API."""

import os
import re
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from alembic import command
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app import migrate
from app.mcp.server import mcp
from app.models import AGENTS_DOC, Project, ProjectStatus, TaskStatus
from app.services import DomainError, everyday, project_files
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.ui.project_view import summary


def made(db, name: str = "Note-app") -> Project:
    """A project, committed: its folder made."""
    project = projects_svc.create_project(db, name=name)
    db.commit()
    return project


def paths_of(project: Project) -> list[str]:
    return [d.path for d in project_files.docs_of(project)]


def test_a_new_project_has_its_agents_md(db) -> None:
    project = made(db)
    assert [(d.name, d.body) for d in project_files.docs_of(project)] == [(AGENTS_DOC, "")]


def test_documents_are_named_once_and_agents_md_stays(db) -> None:
    project = made(db)
    notes = project_files.create_doc(db, project, "  Architecture   notes ")
    # A document's name is its file's: .md added when not written.
    assert notes.name == "Architecture notes.md"
    for taken in ("agents.md", "ARCHITECTURE NOTES", "architecture notes.MD", "  ", "CON", "a:b"):
        with pytest.raises(DomainError):
            project_files.create_doc(db, project, taken)
    # Renamed in another case is the same document, not a clash.
    assert (
        project_files.place(db, project, notes.path, name="architecture notes")
        == "architecture notes.md"
    )
    with pytest.raises(DomainError, match="keeps its name"):
        project_files.place(db, project, AGENTS_DOC, name="README.md")
    with pytest.raises(DomainError, match="keeps its"):
        project_files.delete(db, project, AGENTS_DOC)
    project_files.delete(db, project, "architecture notes.md")
    assert [d.name for d in project_files.docs_of(project)] == [AGENTS_DOC]


def test_a_document_is_dated_by_its_file(db) -> None:
    project = made(db)
    agents = everyday.projects_dir() / "note-app" / AGENTS_DOC
    os.utime(agents, (datetime(2026, 1, 1).timestamp(),) * 2)
    project_files.save(db, project, AGENTS_DOC, "")
    assert project_files.read(project, AGENTS_DOC).updated_at == datetime(2026, 1, 1)
    project_files.save(db, project, AGENTS_DOC, "# Note-app")
    assert project_files.read(project, AGENTS_DOC).updated_at > datetime(2026, 1, 1)


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
    db.commit()
    projects_svc.add_repo(db, project_id=project.id, location=r"C:\code\note-app")
    project_files.save(db, project, AGENTS_DOC, "# Note-app\n\nA notes app.")
    project_files.create_doc(db, project, "Architecture")
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
    assert f'href="/projects/{project.id}/docs/Architecture.md"' in html
    # Its own row in the sidebar is current, as on its Gantt.
    nav = html.split('id="rail-projects"')[1].split("</ul>")[0]
    assert 'aria-current="page"' in nav.split(f'href="/projects/{project.id}"')[1].split(">")[0]


def test_a_missing_project_or_document_is_not_found(client, db) -> None:
    project = made(db)
    assert client.get("/projects/999").status_code == 404
    assert client.get(f"/projects/{project.id}/docs/Nothing.md").status_code == 404
    # A document is found under its own project only.
    project_files.create_doc(db, project, "Plan")
    second = made(db, "Other")
    assert client.get(f"/projects/{project.id}/docs/Plan.md").status_code == 200
    assert client.get(f"/projects/{second.id}/docs/Plan.md").status_code == 404


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


def test_the_new_project_window_offers_his_github_ones_none_taken(client, db) -> None:
    from github_fake import repo_payload

    from app.models import GitHubSource
    from app.services import github as github_svc

    project = made(db)
    link = github_svc.connect(db, {"id": 1, "login": "me", "name": "Me"}, GitHubSource.cli)
    found = [repo_payload(1, "shed", owner="me"), repo_payload(2, "notes", owner="me")]
    github_svc.keep_repositories(db, link, found)
    projects_svc.add_repo(db, project_id=project.id, location="https://github.com/me/shed")
    db.commit()

    # The window's own box, its list and options named after it.
    offered = client.get("/ui/repo-options", params={"box": "project-new-repo-options"}).text
    assert offered.count('role="option"') == 2 and ">shed<" in offered
    assert 'id="project-new-repo-options"' in offered
    assert 'id="project-new-repo-listbox"' in offered
    assert 'id="project-new-repo-option-1"' in offered
    assert 'id="repo-options"' not in offered
    found = client.get("/ui/repo-options", params={"location": "note"}).text
    assert found.count('role="option"') == 1 and ">notes<" in found
    # Words nothing holds go with the project, not added at once.
    loose = {"location": "~/code/shed", "box": "project-new-repo-options"}
    assert "goes with the project as written" in client.get("/ui/repo-options", params=loose).text
    card_loose = f"/ui/projects/{project.id}/repo-options?location=~/code/shed"
    assert "Enter adds “~/code/shed” as written." in client.get(card_loose).text

    # The project card's, as they always were.
    card = client.get(f"/ui/projects/{project.id}/repo-options").text
    assert card.count('role="option"') == 1 and ">shed<" not in card
    assert 'id="repo-options"' in card
    assert 'id="repo-listbox"' in card
    assert 'id="repo-option-1"' in card
    page = client.get(f"/projects/{project.id}").text
    assert 'aria-controls="repo-listbox"' in page and 'id="repo-options"' in page


def checked_colour(html: str) -> str:
    """The colour the form's swatches start on."""
    (colour,) = re.findall(r'name="color" value="(\d)" checked', html)
    return colour


def test_the_new_project_window_starts_on_the_next_colour(client, db, monkeypatch) -> None:
    from app.config import get_settings

    made(db)  # colour 1
    form = client.get("/ui/projects/new").text
    assert checked_colour(form) == "2"
    assert form.count('class="swatch"') == 8
    assert 'hx-post="/ui/projects"' in form
    # The code module in: the line offers his GitHub repositories.
    assert 'hx-get="/ui/repo-options?box=project-new-repo-options"' in form
    assert 'data-repo-box="project-new-repo-options"' in form
    assert '<div class="repo-options" id="project-new-repo-options" hidden>' in form

    # Installed without it: a line to write a folder or URL on, and no more.
    monkeypatch.setattr(get_settings().install, "without", ["code"])
    plain = client.get("/ui/projects/new").text
    assert 'placeholder="Its folder or its URL"' in plain
    assert "data-repo-picker" not in plain and "project-new-repo-options" not in plain


def test_a_project_is_made_in_the_window_with_its_repository(client, db) -> None:
    made_ = client.post(
        "/ui/projects",
        data={
            "name": " Garden shed ",
            "color": "5",
            "notes": "Somewhere for the tools\n",
            "location": r"C:\code\shed",
        },
    )
    (project,) = projects_svc.list_projects(db)
    assert made_.status_code == 200 and made_.text == ""
    assert made_.headers["HX-Trigger"] == "tasks:changed, projects:changed"
    assert made_.headers["HX-Redirect"] == f"/projects/{project.id}"
    assert (project.name, project.color, project.notes) == (
        "Garden shed",
        5,
        "Somewhere for the tools",
    )
    assert [r.location for r in project.repos] == [r"C:\code\shed"]
    folder = project_files.folder_path(project)
    assert folder is not None
    assert everyday.read_manifest(folder).repos == [r"C:\code\shed"]
    assert (folder / AGENTS_DOC).is_file()


def test_a_project_is_made_from_its_name_alone(client, db) -> None:
    made(db)  # colour 1
    alone = client.post("/ui/projects", data={"name": "Shed", "location": "  "})
    shed = next(p for p in projects_svc.list_projects(db) if p.name == "Shed")
    assert alone.headers["HX-Redirect"] == f"/projects/{shed.id}"
    assert (shed.color, shed.notes, shed.repos) == (2, "", [])


def test_a_project_the_window_refuses_is_not_made(client, db, everyday_files) -> None:
    for name in ("", "   "):
        blank = client.post("/ui/projects", data={"name": name, "notes": "what for"})
        assert blank.status_code == 422
        assert blank.json() == {"detail": "Project name must not be empty", "field": "name"}
    assert client.post("/ui/projects", data={}).json()["field"] == "name"

    # A repository refused: neither the project nor its folder is kept.
    refused = client.post("/ui/projects", data={"name": "Shed", "location": "x" * 1001})
    assert refused.status_code == 422
    assert refused.json() == {
        "detail": "A repository's location is 1000 characters at most",
        "field": "location",
    }
    assert projects_svc.list_projects(db) == []
    projects = everyday_files / "projects"
    assert not projects.exists() or list(projects.iterdir()) == []

    # And the next one made is whole.
    client.post("/ui/projects", data={"name": "Shed", "location": r"C:\code\shed"})
    (shed,) = projects_svc.list_projects(db)
    assert [r.location for r in shed.repos] == [r"C:\code\shed"]


def test_a_document_is_added_written_renamed_and_deleted(client, db) -> None:
    project = made(db)
    added = client.post(f"/ui/projects/{project.id}/docs", data={"name": "Architecture"})
    assert added.headers["HX-Redirect"] == f"/projects/{project.id}/docs/Architecture.md"
    page = client.get(f"/projects/{project.id}/docs/Architecture.md").text
    assert "<title>Architecture.md · Note-app · Personal Calendar</title>" in page
    assert f'<a class="page-back" href="/projects/{project.id}">Note-app</a>' in page
    assert 'data-doc-name value="Architecture.md"' in page
    assert '<span class="doc-file" data-doc-file>projects/note-app/Architecture.md' in page

    saved = client.post(
        f"/ui/projects/{project.id}/doc",
        data={"path": "Architecture.md", "body": "# How\r\nIt fits.", "name": "Design"},
    )
    # Answered with its version, its name (a file's) and where it now is.
    assert saved.json() == {
        "version": everyday.version("# How\nIt fits."),
        "name": "Design.md",
        "path": "Design.md",
        "href": f"/projects/{project.id}/docs/Design.md",
        "file": "projects/note-app/Design.md",
    }
    assert project_files.read(project, "Design.md").body == "# How\nIt fits."
    assert client.post(
        f"/ui/projects/{project.id}/doc", data={"path": "Design.md", "name": "AGENTS.md"}
    ).status_code == 422

    deleted = client.post(f"/ui/projects/{project.id}/context/delete", data={"path": "Design.md"})
    assert deleted.headers["HX-Redirect"] == f"/projects/{project.id}"
    assert paths_of(project) == [AGENTS_DOC]


def test_agents_md_has_no_name_to_write_and_no_bin(client, db) -> None:
    project = made(db)
    page = client.get(f"/projects/{project.id}/docs/{AGENTS_DOC}").text
    assert "<h1>AGENTS.md</h1>" in page and "data-doc-name" not in page
    assert "/delete" not in page.split('class="doc-title"')[1].split("</div>")[0]
    gone = client.post(f"/ui/projects/{project.id}/context/delete", data={"path": AGENTS_DOC})
    assert gone.status_code == 422


def test_the_context_is_handed_over_the_api(client, db) -> None:
    project = made(db)
    project_files.create_doc(db, project, "Architecture", body="It fits.")
    project_files.save(db, project, AGENTS_DOC, "Run uv sync.")
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
        project = made(db)
        project_files.save(db, project, AGENTS_DOC, "Run uv sync.")
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
    project = made(db)
    assert project_files.create_folder(db, project, " decisions ") == "decisions"
    assert project_files.create_folder(db, project, "adr", "decisions") == "decisions/adr"
    # A folder and a document share their names, as on disk, in any case.
    for taken in ("Decisions", "AGENTS.md"):
        with pytest.raises(DomainError):
            project_files.create_folder(db, project, taken)
    # A document is its file, Markdown: "decisions" is decisions.md, beside the folder.
    assert project_files.create_doc(db, project, "decisions").name == "decisions.md"
    with pytest.raises(DomainError, match="already has adr"):
        project_files.create_folder(db, project, "ADR", "decisions")
    # The same name in another folder is another document, AGENTS.md too.
    inner = project_files.create_doc(db, project, "AGENTS.md", "decisions/adr")
    assert inner.path == "decisions/adr/AGENTS.md" and not inner.is_agents
    with pytest.raises(DomainError, match="slash"):
        project_files.place(db, project, inner.path, name="a/b")


def test_a_path_makes_the_folders_it_names(db) -> None:
    project = made(db)
    first = project_files.create_doc(db, project, "decisions/adr/0001.md")
    second = project_files.create_doc(db, project, "Decisions\\adr\\0002.md")
    assert (first.path, second.path) == ("decisions/adr/0001.md", "decisions/adr/0002.md")
    assert [f.path for f in project_files.folders_of(project)] == ["decisions", "decisions/adr"]
    deep = project_files.create_folder(db, project, "2026/oct", first.folder_path)
    assert deep == "decisions/adr/2026/oct"


def test_documents_and_folders_move_but_never_into_themselves(db) -> None:
    project = made(db)
    project_files.create_folder(db, project, "a/b")
    project_files.create_doc(db, project, "Plan.md")
    assert project_files.place(db, project, "Plan.md", folder="a/b") == "a/b/Plan.md"
    assert project_files.place(db, project, "a/b/Plan.md", folder="") == "Plan.md"
    for inside in ("a", "a/b"):
        with pytest.raises(DomainError, match="inside itself"):
            project_files.place(db, project, "a", folder=inside)
    assert project_files.place(db, project, "a/b", folder="", name="c") == "c"
    # Moved where its name is taken, it stays put.
    project_files.create_doc(db, project, "plan.md", "a")
    with pytest.raises(DomainError, match="already has plan.md"):
        project_files.place(db, project, "Plan.md", folder="a")
    with pytest.raises(DomainError, match="keeps its name and its place"):
        project_files.place(db, project, AGENTS_DOC, folder="a")


def test_a_folder_is_deleted_with_everything_in_it(db) -> None:
    project = made(db)
    project_files.create_doc(db, project, "a/b/deep.md")
    project_files.create_doc(db, project, "a/top.md")
    project_files.create_doc(db, project, "kept.md")
    project_files.delete(db, project, "a")
    assert paths_of(project) == ["AGENTS.md", "kept.md"]
    assert project_files.folders_of(project) == []


def test_the_context_reads_as_its_tree(db) -> None:
    project = made(db)
    for name in ("zeta.md", "Plan 10.md", "Plan 2.md", "b/two.md", "a/one.md", "a/c/three.md"):
        project_files.create_doc(db, project, name)
    project_files.create_folder(db, project, "empty")
    # AGENTS.md, then each folder's (its subfolders' first), then the rest,
    # by name, its numbers as numbers.
    assert paths_of(project) == [
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
    project = made(db)
    project_files.create_doc(db, project, "Plan.md")
    db.commit()
    made_folder = client.post(f"/ui/projects/{project.id}/folders", data={"name": "decisions"})
    assert 'id="project-context"' in made_folder.text
    assert 'data-folder="decisions" data-name="decisions"' in made_folder.text
    assert ">Empty</span>" in made_folder.text and 'hx-swap-oob="true"' in made_folder.text
    key = project_files.folders_of(project)[0].key

    # A document written in the folder opens on its own page.
    added = client.post(
        f"/ui/projects/{project.id}/docs", data={"name": "0001.md", "folder": "decisions"}
    )
    assert added.headers["HX-Redirect"] == f"/projects/{project.id}/docs/decisions/0001.md"

    # Folded, it stays so; a document dragged into it opens it again.
    folded = client.post(
        f"/ui/projects/{project.id}/context/fold", data={"path": "decisions", "folded": "true"}
    )
    assert folded.status_code == 204
    assert f'id="ctx-in-{key}" hidden' in client.get(f"/projects/{project.id}").text
    place = f"/ui/projects/{project.id}/context/place"
    moved = client.post(place, data={"path": "Plan.md", "folder": "decisions"})
    assert "2 documents" in moved.text and f'id="ctx-in-{key}" hidden' not in moved.text
    assert "decisions/Plan.md" in paths_of(project)

    # Renamed on the tree; back to the top from its own page.
    client.post(place, data={"path": "decisions", "name": "adr"})
    page = client.get(f"/projects/{project.id}/docs/adr/Plan.md").text
    assert '<option value="adr" selected>adr</option>' in page
    to_top = {"path": "adr/Plan.md", "folder": "/"}
    back = client.post(f"/ui/projects/{project.id}/doc", data=to_top)
    assert back.headers["HX-Redirect"] == f"/projects/{project.id}/docs/Plan.md"
    assert client.post(place, data={"path": "Plan.md", "name": "AGENTS.md"}).status_code == 422
    # Dragged into the folder and out to the top again.
    client.post(place, data={"path": "Plan.md", "folder": "adr"})
    client.post(place, data={"path": "adr/Plan.md", "folder": "/"})
    assert "Plan.md" in paths_of(project)

    # Deleted on the tree: the tree comes back, the folder and its contents gone.
    delete = f"/ui/projects/{project.id}/context/delete?tree=1"
    gone = client.post(delete, data={"path": "Plan.md"})
    assert 'id="project-context"' in gone.text and 'data-name="Plan.md"' not in gone.text
    gone = client.post(delete, data={"path": "adr"})
    assert 'data-name="adr"' not in gone.text
    assert paths_of(project) == [AGENTS_DOC]


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
    command.upgrade(migrate._config(path), "b4ac9ded1570")  # before files first
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
    command.upgrade(migrate._config(path), "b4ac9ded1570")  # before files first
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT project_id, name, body FROM project_docs").fetchall()
    assert rows == [(1, "AGENTS.md", "")]
