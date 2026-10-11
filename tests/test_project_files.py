"""A project's folder (SPEC.md, Files first): its documents are files and
nothing else, written by the app and by editors and agents alike; the
folder follows the project; project.toml keeps its id and repositories."""

import sqlite3
import tomllib
from datetime import datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import select

from app import migrate
from app.models import AGENTS_DOC, DocumentRevision, Project, Setting
from app.services import DomainError, documents, everyday, project_files, settling
from app.services import projects as projects_svc


def folder(name: str = "note-app"):  # noqa: ANN201
    return everyday.projects_dir() / name


def manifest(name: str = "note-app") -> dict:
    return tomllib.loads((folder(name) / "project.toml").read_text(encoding="utf-8"))


def made(db, name: str = "Note-app") -> Project:
    """A project, committed: its folder made."""
    project = projects_svc.create_project(db, name=name)
    db.commit()
    return project


def history(db, project: Project, name: str) -> list[tuple[str, str]]:
    return [
        (r.actor, r.body)
        for r in db.scalars(
            select(DocumentRevision)
            .where(DocumentRevision.owner == f"project:{project.id}", DocumentRevision.name == name)
            .order_by(DocumentRevision.id)
        )
    ]


def paths(project: Project) -> list[str]:
    return [d.path for d in project_files.docs_of(project)]


# ---- written by the app ----


def test_a_new_project_writes_its_folder(db) -> None:
    project = made(db)
    assert project.folder == "note-app"
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == ""
    assert manifest() == {"id": project.id, "repos": []}
    assert (folder() / "project.md").read_text(encoding="utf-8").startswith("---\n")
    # A second of the same name gets a folder of its own.
    assert made(db, "note app").folder == "note-app-2"


def test_the_apps_edits_go_to_the_files(db) -> None:
    project = made(db)
    project_files.save(db, project, AGENTS_DOC, "Run uv sync.")
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == "Run uv sync."

    doc = project_files.create_doc(db, project, "Architecture", body="It fits.")
    assert doc.path == "Architecture.md"
    assert (folder() / "Architecture.md").read_text(encoding="utf-8") == "It fits."
    assert project_files.place(db, project, "Architecture.md", name="Design") == "Design.md"
    assert not (folder() / "Architecture.md").exists()
    assert (folder() / "Design.md").read_text(encoding="utf-8") == "It fits."
    # Its history followed it.
    assert history(db, project, "Design.md") == [("oscar", "It fits.")]
    project_files.delete(db, project, "Design.md")
    assert not (folder() / "Design.md").exists()

    repo = projects_svc.add_repo(db, project_id=project.id, location=r"C:\code\note-app")
    projects_svc.add_repo(db, project_id=project.id, location="https://github.com/me/notes")
    assert manifest()["repos"] == [r"C:\code\note-app", "https://github.com/me/notes"]
    projects_svc.delete_repo(db, repo.id)
    assert manifest()["repos"] == ["https://github.com/me/notes"]


def test_agents_md_keeps_its_name_its_place_and_itself(db) -> None:
    project = made(db)
    with pytest.raises(DomainError, match="keeps its name"):
        project_files.place(db, project, AGENTS_DOC, name="Other")
    with pytest.raises(DomainError, match="keeps its"):
        project_files.delete(db, project, AGENTS_DOC)
    with pytest.raises(DomainError, match="not one of the context's"):
        project_files.create_doc(db, project, "project.md")
    with pytest.raises(DomainError):
        project_files.create_doc(db, project, "tasks/plan")


def test_names_beside_each_other_are_unique_in_any_case(db) -> None:
    project = made(db)
    project_files.create_doc(db, project, "Notes")
    with pytest.raises(DomainError, match="already has Notes.md"):
        project_files.create_doc(db, project, "notes.md")
    project_files.create_folder(db, project, "Plans")
    with pytest.raises(DomainError, match="already has Plans"):
        project_files.create_folder(db, project, "plans")
    with pytest.raises(DomainError, match="slash"):
        project_files.place(db, project, "Notes.md", name="a/b")


# ---- read from the files ----


def test_the_context_is_what_the_folder_holds(db) -> None:
    project = made(db)
    (folder() / "decisions" / "adr").mkdir(parents=True)
    (folder() / "decisions" / "adr" / "0001.md").write_text("Use files.", encoding="utf-8")
    (folder() / "empty").mkdir()
    (folder() / ".git").mkdir()  # hidden: not the context's
    (folder() / ".git" / "HEAD.md").write_text("x", encoding="utf-8")
    (folder() / "picture.png").write_bytes(b"not a document")
    top = project_files.tree(project)
    # The project's own files and its tasks are not its context.
    assert [f.path for f in top.all_folders()] == ["decisions", "decisions/adr", "empty"]
    assert paths(project) == [AGENTS_DOC, "decisions/adr/0001.md"]
    assert project_files.read(project, "decisions/adr/0001.md").body == "Use files."
    assert project_files.count_docs(project) == 2


def test_a_file_written_elsewhere_is_a_step_of_its_history_by_the_files_hand(db) -> None:
    project = made(db)
    project_files.save(db, project, AGENTS_DOC, "Mine.")
    (folder() / AGENTS_DOC).write_bytes(b"# Note-app\r\n\r\nRun uv sync.\r\n")
    settling.sync(db)
    assert history(db, project, AGENTS_DOC)[-1] == ("file", "# Note-app\n\nRun uv sync.\n")
    found = documents.search(db, "uv sync")
    assert [f["path"] for f in found] == ["projects/note-app/AGENTS.md"]


def test_agents_md_deleted_is_written_back(db) -> None:
    project = made(db)
    project_files.save(db, project, AGENTS_DOC, "Run uv sync.")
    db.commit()
    (folder() / AGENTS_DOC).unlink()
    project_files.refresh(db, project)
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == "Run uv sync."


def test_repositories_are_read_from_project_toml(db) -> None:
    project = made(db)
    projects_svc.add_repo(db, project_id=project.id, location="C:/code/one")
    (folder() / "project.toml").write_text(
        f'id = {project.id}\nrepos = ["C:/code/two", "C:/code/one"]\n', encoding="utf-8"
    )
    project_files.refresh(db, project)
    # In the file's order, each once, as the database keeps them.
    db.expire(project, ["repos"])
    assert [r.location for r in project.repos] == ["C:/code/two", "C:/code/one"]
    (folder() / "project.toml").write_text(
        f'id = {project.id}\nrepos = ["C:/code/one", "C:/code/one"]\n', encoding="utf-8"
    )
    project_files.refresh(db, project)
    project_files.refresh(db, project)
    db.expire(project, ["repos"])
    assert [r.location for r in project.repos] == ["C:/code/one"]
    with pytest.raises(DomainError, match="already"):
        projects_svc.add_repo(db, project_id=project.id, location=" C:/code/one ")


def test_a_project_toml_that_cannot_be_read_is_left_alone(db) -> None:
    project = made(db)
    projects_svc.add_repo(db, project_id=project.id, location="C:/code/one")
    (folder() / "project.toml").write_text("repos = [unfinished", encoding="utf-8")
    project_files.refresh(db, project)
    assert [r.location for r in project.repos] == ["C:/code/one"]
    assert (folder() / "project.toml").read_text(encoding="utf-8") == "repos = [unfinished"


def test_a_repository_taken_out_of_the_file_cannot_be_changed(db) -> None:
    project = made(db)
    repo = projects_svc.add_repo(db, project_id=project.id, location="C:/code/one")
    (folder() / "project.toml").write_text(f"id = {project.id}\nrepos = []\n", encoding="utf-8")
    with pytest.raises(DomainError, match="taken out there"):
        projects_svc.update_repo(db, repo.id, location="C:/code/two")


# ---- a save from an older copy ----


def test_a_save_from_an_older_copy_is_refused(db) -> None:
    project = made(db)
    read_at = everyday.version("")
    (folder() / AGENTS_DOC).write_text("An agent's words.", encoding="utf-8")
    with pytest.raises(project_files.DocChanged) as refused:
        project_files.save(db, project, AGENTS_DOC, "Mine.", base=read_at)
    assert refused.value.version == everyday.version("An agent's words.")
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == "An agent's words."
    # Kept anyway: written over the version now there.
    project_files.save(db, project, AGENTS_DOC, "Mine.", base=refused.value.version)
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == "Mine."
    # The agent's words are in its history, before Oscar's.
    assert [a for a, _ in history(db, project, AGENTS_DOC)][-2:] == ["file", "oscar"]


def test_the_page_asks_when_its_copy_is_older(client, db) -> None:
    project = made(db)
    page = client.get(f"/projects/{project.id}/docs/{AGENTS_DOC}").text
    assert f'data-version="{everyday.version("")}"' in page
    assert f'data-path="{AGENTS_DOC}"' in page
    assert "data-doc-stale" in page
    (folder() / AGENTS_DOC).write_text("An agent's words.", encoding="utf-8")
    refused = client.post(
        f"/ui/projects/{project.id}/doc",
        data={"path": AGENTS_DOC, "body": "Mine.", "base": everyday.version("")},
    )
    assert refused.status_code == 409
    assert refused.json()["version"] == everyday.version("An agent's words.")
    latest = client.get(f"/ui/projects/{project.id}/doc", params={"path": AGENTS_DOC}).json()
    assert latest == {
        "version": everyday.version("An agent's words."),
        "name": AGENTS_DOC,
        "body": "An agent's words.",
    }


def test_a_document_deleted_in_its_folder_is_gone_from_its_page(client, db) -> None:
    project = made(db)
    project_files.create_doc(db, project, "Notes")
    db.commit()
    (folder() / "Notes.md").unlink()
    assert client.get(f"/projects/{project.id}/docs/Notes.md").status_code == 404
    gone = client.post(f"/ui/projects/{project.id}/doc", data={"path": "Notes.md", "body": "x"})
    assert gone.status_code == 422


def test_a_path_that_leaves_the_folder_is_refused(client, db) -> None:
    project = made(db)
    for path in ("../other/AGENTS.md", "project.toml", "tasks/1-x/task.md"):
        with pytest.raises(DomainError):
            project_files.read(project, path)
    assert client.get(f"/projects/{project.id}/docs/..%2F..%2FREADME.md").status_code == 404


# ---- the folder follows the project ----


def test_a_folder_without_a_project_is_a_new_one(db) -> None:
    folder("Garden").mkdir(parents=True)
    (folder("Garden") / "Plan.md").write_text("Plant in spring.", encoding="utf-8")
    project_files.sync_all(db)
    project = db.scalars(select(Project)).one()
    assert (project.name, project.folder) == ("Garden", "Garden")
    assert paths(project) == [AGENTS_DOC, "Plan.md"]
    assert manifest("Garden")["id"] == project.id
    assert (folder("Garden") / AGENTS_DOC).exists()


def test_a_project_renamed_has_its_folder_renamed(db) -> None:
    project = made(db)
    project_files.create_doc(db, project, "Plan", body="Soon.")
    projects_svc.update_project(db, project.id, name="Notebook")
    db.commit()
    assert project.folder == "notebook"
    assert (folder("notebook") / "Plan.md").read_text(encoding="utf-8") == "Soon."
    assert not folder().exists()


def test_a_folder_renamed_by_hand_is_followed_then_named_after_its_project(db) -> None:
    project = made(db)
    folder().rename(folder("notes"))
    project_files.sync_all(db)
    assert db.scalars(select(Project)).all() == [project]
    settling.settle_project(db, project)
    assert project.folder == "note-app"
    assert folder().is_dir() and not folder("notes").exists()


def test_folders_named_after_each_others_projects_are_swapped_back(db) -> None:
    # As some were before folders followed their projects: each in a folder
    # named after the other.
    first, second = made(db, "Alpha"), made(db, "Beta")
    folder("alpha").rename(folder("swap"))
    folder("beta").rename(folder("alpha"))
    folder("swap").rename(folder("beta"))
    settling.settle_all(db)
    db.refresh(first)
    db.refresh(second)
    assert (first.folder, second.folder) == ("alpha", "beta")
    assert manifest("alpha")["id"] == first.id and manifest("beta")["id"] == second.id
    assert sorted(p.name for p in everyday.projects_dir().iterdir()) == ["alpha", "beta"]


def test_a_folder_gone_is_written_again_from_its_history(db) -> None:
    project = made(db)
    project_files.save(db, project, AGENTS_DOC, "Run uv sync.")
    project_files.create_doc(db, project, "decisions/0001", body="Use files.")
    db.commit()
    for path in sorted(folder().rglob("*"), key=lambda p: -len(p.parts)):
        path.rmdir() if path.is_dir() else path.unlink()
    folder().rmdir()
    settling.sync(db)
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == "Run uv sync."
    assert (folder() / "decisions" / "0001.md").read_text(encoding="utf-8") == "Use files."
    assert (folder() / "project.md").is_file()


def test_a_folder_made_by_hand_for_a_new_project_is_its_own(db) -> None:
    (folder() / "decisions").mkdir(parents=True)
    (folder() / "decisions" / "0001.md").write_text("Use files.", encoding="utf-8")
    project = made(db)
    assert project.folder == "note-app"
    assert paths(project) == [AGENTS_DOC, "decisions/0001.md"]
    assert manifest()["id"] == project.id
    # One that is another project's stays its: the next is numbered on.
    assert made(db, "note app").folder == "note-app-2"


# ---- folders of the context ----


def test_the_apps_folders_are_folders_on_disk(db) -> None:
    project = made(db)
    assert project_files.create_folder(db, project, "decisions") == "decisions"
    assert project_files.create_folder(db, project, "adr", "decisions") == "decisions/adr"
    assert (folder() / "decisions" / "adr").is_dir()
    doc = project_files.create_doc(db, project, "decisions/adr/0001", body="Use files.")
    assert doc.path == "decisions/adr/0001.md"
    assert (folder() / "decisions" / "adr" / "0001.md").read_text(encoding="utf-8") == "Use files."

    # Renamed, moved: on disk with it, its history following.
    assert project_files.place(db, project, "decisions/adr", name="records") == "decisions/records"
    assert (folder() / "decisions" / "records" / "0001.md").is_file()
    assert history(db, project, "decisions/records/0001.md") == [("oscar", "Use files.")]
    assert project_files.place(db, project, "decisions/records/0001.md", folder="") == "0001.md"
    assert (folder() / "0001.md").is_file()
    assert project_files.place(db, project, "decisions/records", folder="") == "records"
    with pytest.raises(DomainError, match="inside itself"):
        project_files.place(db, project, "decisions", folder="decisions")

    # Deleted, with everything in it.
    project_files.create_doc(db, project, "Plan", "decisions")
    project_files.delete(db, project, "decisions")
    assert not (folder() / "decisions").exists()


def test_a_folder_folded_is_remembered_and_follows_a_move(db) -> None:
    project = made(db)
    project_files.create_folder(db, project, "decisions/adr")
    project_files.set_folded(db, project, "decisions/adr", True)
    assert project_files.tree(project, project_files.folded_paths(db, project)).folders[0] \
        .folders[0].folded
    project_files.place(db, project, "decisions/adr", name="records")
    assert project_files.folded_paths(db, project) == {"decisions/records"}
    # Something put in a folded folder opens it, and those it is in.
    project_files.set_folded(db, project, "decisions", True)
    project_files.create_doc(db, project, "decisions/records/0002")
    assert project_files.folded_paths(db, project) == set()


# ---- history ----


def test_edits_in_a_row_by_one_hand_are_one_step(db) -> None:
    project = made(db)
    project_files.save(db, project, AGENTS_DOC, "One.")
    project_files.save(db, project, AGENTS_DOC, "One. Two.")
    assert history(db, project, AGENTS_DOC) == [("oscar", "One. Two.")]
    (folder() / AGENTS_DOC).write_text("An agent's.", encoding="utf-8")
    settling.sync(db)
    project_files.save(db, project, AGENTS_DOC, "Mine again.")
    assert [a for a, _ in history(db, project, AGENTS_DOC)] == ["oscar", "file", "oscar"]
    # Past the spell, a new step.
    last = db.scalars(select(DocumentRevision).order_by(DocumentRevision.id.desc())).first()
    last.at = datetime.now() - documents.WRITING_SPELL - timedelta(seconds=1)
    project_files.save(db, project, AGENTS_DOC, "Later.")
    assert len(history(db, project, AGENTS_DOC)) == 4


def test_the_migration_keeps_every_documents_history_and_files(tmp_path) -> None:
    path = tmp_path / "app.db"
    command.upgrade(migrate._config(path), "b4ac9ded1570")  # the revision before
    folder("old-one").mkdir(parents=True)
    (folder("old-one") / "AGENTS.md").write_text("Build it.", encoding="utf-8")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO projects (name, status, notes, color, folded, position, folder, "
            "created_at) VALUES ('Old one', 'active', '', 1, 0, 0, 'old-one', "
            "'2026-09-01 10:00:00')"
        )
        db.execute(
            "INSERT INTO project_doc_folders (project_id, parent_id, name, folded) "
            "VALUES (1, NULL, 'decisions', 1)"
        )
        db.execute(
            "INSERT INTO project_docs (project_id, folder_id, name, body, updated_at) VALUES "
            "(1, NULL, 'AGENTS.md', 'Build it.', '2026-09-02 10:00:00'), "
            "(1, 1, '0001.md', 'Never written out.', '2026-09-03 10:00:00')"
        )
        db.execute(
            "INSERT INTO project_doc_revisions (doc_id, at, actor, body) VALUES "
            "(1, '2026-09-02 10:00:00', 'oscar', 'Build it.'), "
            "(2, '2026-09-03 10:00:00', 'claude', 'Never written out.')"
        )
    migrate.upgrade(path)
    with sqlite3.connect(path) as db:
        steps = db.execute("SELECT owner, name, actor, body FROM document_revisions ORDER BY id")
        assert steps.fetchall() == [
            ("project:1", "AGENTS.md", "oscar", "Build it."),
            ("project:1", "decisions/0001.md", "claude", "Never written out."),
        ]
        tables = {n for (n,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not tables & {"project_docs", "project_doc_folders", "project_doc_revisions"}
        assert {"documents", "documents_fts", "document_revisions"} <= tables
        [(folded,)] = db.execute("SELECT value FROM settings WHERE key = 'context_folded'")
        assert folded == '{"1": ["decisions"]}'
    assert (folder("old-one") / "decisions" / "0001.md").read_text(encoding="utf-8") == (
        "Never written out."
    )


def test_the_folded_setting_survives_a_settle(db) -> None:
    project = made(db)
    project_files.create_folder(db, project, "plans")
    project_files.set_folded(db, project, "plans", True)
    db.commit()
    settling.settle_all(db)
    assert db.get(Setting, project_files.FOLDED_SETTING).value == {str(project.id): ["plans"]}
