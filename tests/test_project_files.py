"""A project's context as files (SPEC.md, Agent runs): its folder in the
everyday files' projects/ is the master copy, written first by the app and
read back into the database as an editor or an agent changes it."""

import shutil
import sqlite3
import threading
import time
import tomllib
from datetime import datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import select

from app import migrate
from app.models import AGENTS_DOC, Project, ProjectDoc, ProjectDocFolder, ProjectDocRevision
from app.services import DomainError, everyday, project_files
from app.services import projects as projects_svc


def folder(name: str = "note-app"):  # noqa: ANN201
    return everyday.projects_dir() / name


def manifest(name: str = "note-app") -> dict:
    return tomllib.loads((folder(name) / "project.toml").read_text(encoding="utf-8"))


def history(db, doc: ProjectDoc) -> list[tuple[str, str]]:
    return [
        (r.actor, r.body)
        for r in db.scalars(
            select(ProjectDocRevision)
            .where(ProjectDocRevision.doc_id == doc.id)
            .order_by(ProjectDocRevision.id)
        )
    ]


# ---- written by the app, file first ----


def test_a_new_project_writes_its_folder(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    assert project.folder == "note-app"
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == ""
    assert manifest() == {"id": project.id, "repos": []}
    # A second of the same name gets a folder of its own.
    assert projects_svc.create_project(db, name="note app").folder == "note-app-2"


def test_the_apps_edits_go_to_the_files(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    projects_svc.update_doc(db, project.docs[0].id, body="Run uv sync.")
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == "Run uv sync."

    doc = projects_svc.create_doc(db, project_id=project.id, name="Architecture", body="It fits.")
    assert (folder() / "Architecture.md").read_text(encoding="utf-8") == "It fits."
    projects_svc.update_doc(db, doc.id, name="Design")
    assert not (folder() / "Architecture.md").exists()
    assert (folder() / "Design.md").read_text(encoding="utf-8") == "It fits."
    projects_svc.delete_doc(db, doc.id)
    assert not (folder() / "Design.md").exists()

    repo = projects_svc.add_repo(db, project_id=project.id, location=r"C:\code\note-app")
    projects_svc.add_repo(db, project_id=project.id, location="https://github.com/me/notes")
    assert manifest()["repos"] == [r"C:\code\note-app", "https://github.com/me/notes"]
    projects_svc.delete_repo(db, repo.id)
    assert manifest()["repos"] == ["https://github.com/me/notes"]


# ---- read back from the files ----


def test_a_file_written_elsewhere_is_read_in_as_the_files_hand(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    agents = project.docs[0]
    (folder() / AGENTS_DOC).write_bytes(b"# Note-app\r\n\r\nRun uv sync.\r\n")
    project_files.refresh(db, project)
    # Its lines as the app keeps them, and the step the file's.
    assert agents.body == "# Note-app\n\nRun uv sync.\n"
    assert history(db, agents)[-1] == ("file", agents.body)


def test_files_added_renamed_and_deleted_are_documents_so(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    notes = projects_svc.create_doc(db, project_id=project.id, name="Notes", body="Some notes.")
    plan = projects_svc.create_doc(db, project_id=project.id, name="Plan", body="A plan.")
    (folder() / "Decisions.md").write_text("We chose files.", encoding="utf-8")
    (folder() / "Notes.md").rename(folder() / "Ideas.md")
    (folder() / "Plan.md").unlink()
    (folder() / "picture.png").write_bytes(b"not a document")
    project_files.refresh(db, project)
    names = {d.name: d for d in project.docs}
    assert set(names) == {AGENTS_DOC, "Decisions.md", "Ideas.md"}
    # Renamed, it is the same document: the same words under a new name.
    assert names["Ideas.md"].id == notes.id
    assert names["Decisions.md"].body == "We chose files."
    assert plan not in project.docs


def test_agents_md_deleted_is_written_back(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    projects_svc.update_doc(db, project.docs[0].id, body="Run uv sync.")
    (folder() / AGENTS_DOC).unlink()
    project_files.refresh(db, project)
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == "Run uv sync."
    assert [d.name for d in project.docs] == [AGENTS_DOC]


def test_repositories_are_read_from_project_toml(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
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
    project = projects_svc.create_project(db, name="Note-app")
    projects_svc.add_repo(db, project_id=project.id, location="C:/code/one")
    (folder() / "project.toml").write_text("repos = [unfinished", encoding="utf-8")
    project_files.refresh(db, project)
    assert [r.location for r in project.repos] == ["C:/code/one"]
    assert (folder() / "project.toml").read_text(encoding="utf-8") == "repos = [unfinished"


def test_a_repository_taken_out_of_the_file_cannot_be_changed(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    repo = projects_svc.add_repo(db, project_id=project.id, location="C:/code/one")
    (folder() / "project.toml").write_text(f"id = {project.id}\nrepos = []\n", encoding="utf-8")
    with pytest.raises(DomainError, match="taken out there"):
        projects_svc.update_repo(db, repo.id, location="C:/code/two")


# ---- a save from an older copy ----


def test_a_save_from_an_older_copy_is_refused(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    agents = project.docs[0]
    read_at = everyday.version(agents.body)
    (folder() / AGENTS_DOC).write_text("An agent's words.", encoding="utf-8")
    with pytest.raises(projects_svc.DocChanged) as refused:
        projects_svc.update_doc(db, agents.id, body="Mine.", base=read_at)
    assert refused.value.version == everyday.version("An agent's words.")
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == "An agent's words."
    # Kept anyway: written over the version now there.
    projects_svc.update_doc(db, agents.id, body="Mine.", base=refused.value.version)
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == "Mine."


def test_the_page_asks_when_its_copy_is_older(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    agents = project.docs[0]
    db.commit()
    page = client.get(f"/projects/{project.id}/docs/{agents.id}").text
    assert f'data-version="{everyday.version("")}"' in page
    assert "data-doc-stale" in page
    (folder() / AGENTS_DOC).write_text("An agent's words.", encoding="utf-8")
    refused = client.post(
        f"/ui/docs/{agents.id}", data={"body": "Mine.", "base": everyday.version("")}
    )
    assert refused.status_code == 409
    assert refused.json()["version"] == everyday.version("An agent's words.")
    latest = client.get(f"/ui/docs/{agents.id}/latest").json()
    assert latest == {
        "version": everyday.version("An agent's words."),
        "name": AGENTS_DOC,
        "body": "An agent's words.",
    }


def test_a_document_deleted_in_its_folder_is_gone_from_its_page(client, db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    doc = projects_svc.create_doc(db, project_id=project.id, name="Notes")
    db.commit()
    (folder() / "Notes.md").unlink()
    assert client.get(f"/projects/{project.id}/docs/{doc.id}").status_code == 404
    assert client.post(f"/ui/docs/{doc.id}", data={"body": "Mine."}).status_code == 422


# ---- every folder ----


def test_a_folder_without_a_project_is_a_new_one(db) -> None:
    (folder("Garden") / "AGENTS.md").parent.mkdir(parents=True)
    (folder("Garden") / "Plan.md").write_text("Plant in spring.", encoding="utf-8")
    project_files.sync_all(db)
    project = db.scalars(select(Project)).one()
    assert (project.name, project.folder) == ("Garden", "Garden")
    assert sorted(d.name for d in project.docs) == [AGENTS_DOC, "Plan.md"]
    assert manifest("Garden")["id"] == project.id
    assert (folder("Garden") / AGENTS_DOC).exists()


def test_a_folder_moved_is_followed_by_its_id(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    folder().rename(folder("notes"))
    project_files.sync_all(db)
    assert project.folder == "notes"
    assert db.scalars(select(Project)).all() == [project]


def test_a_folder_gone_is_written_again(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    projects_svc.update_doc(db, project.docs[0].id, body="Run uv sync.")
    (folder() / AGENTS_DOC).unlink()
    (folder() / "project.toml").unlink()
    folder().rmdir()
    project_files.sync_all(db)
    assert (folder() / AGENTS_DOC).read_text(encoding="utf-8") == "Run uv sync."


def test_projects_from_before_get_their_folders(db) -> None:
    # As the migration leaves them: no folder, names written before files.
    project = Project(name="Old one", color=1, position=0)
    project.docs = [
        ProjectDoc(name=AGENTS_DOC, body="Build it."),
        ProjectDoc(name="Notes", body="a"),
        ProjectDoc(name="Notes.md", body="b"),
        ProjectDoc(name="Plan: v2", body="c"),
    ]
    db.add(project)
    # One made by hand, named as the project is, is taken as its own.
    folder("old-one").mkdir(parents=True)
    (folder("old-one") / "Ideas.md").write_text("d", encoding="utf-8")
    project_files.sync_all(db)
    assert project.folder == "old-one"
    # A name already a file's is kept; the others are made one around it.
    assert {d.name: d.body for d in project.docs} == {
        AGENTS_DOC: "Build it.",
        "Notes (2).md": "a",
        "Notes.md": "b",
        "Plan- v2.md": "c",
        "Ideas.md": "d",
    }
    assert (folder("old-one") / "Notes (2).md").read_text(encoding="utf-8") == "a"
    assert db.scalars(select(Project)).all() == [project]


# ---- history ----


def test_edits_in_a_row_by_one_hand_are_one_step(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    agents = project.docs[0]
    projects_svc.update_doc(db, agents.id, body="One.")
    projects_svc.update_doc(db, agents.id, body="One. Two.")
    assert history(db, agents) == [("oscar", "One. Two.")]
    (folder() / AGENTS_DOC).write_text("An agent's.", encoding="utf-8")
    project_files.refresh(db, project)
    projects_svc.update_doc(db, agents.id, body="Mine again.")
    assert [a for a, _ in history(db, agents)] == ["oscar", "file", "oscar"]
    # Past the spell, a new step.
    last = db.scalars(select(ProjectDocRevision).order_by(ProjectDocRevision.id.desc())).first()
    last.at = datetime.now() - project_files.WRITING_SPELL - timedelta(seconds=1)
    projects_svc.update_doc(db, agents.id, body="Later.")
    assert len(history(db, agents)) == 4


def test_the_migration_starts_every_documents_history(tmp_path) -> None:
    path = tmp_path / "app.db"
    command.upgrade(migrate._config(path), "f3b8c2d71e95")  # the revision before
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO projects (name, status, notes, color, folded, position, created_at) "
            "VALUES ('Old one', 'active', '', 1, 0, 0, '2026-09-01 10:00:00')"
        )
        db.execute(
            "INSERT INTO project_docs (project_id, name, body, updated_at) "
            "VALUES (1, 'AGENTS.md', 'Build it.', '2026-09-02 10:00:00')"
        )
    migrate.upgrade(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT folder FROM projects").fetchall() == [(None,)]
        steps = db.execute("SELECT doc_id, at, actor, body FROM project_doc_revisions")
        assert steps.fetchall() == [(1, "2026-09-02 10:00:00", "system", "Build it.")]


# ---- watched ----


def test_the_watcher_reads_in_a_file_written_while_the_app_runs(app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Note-app")
        db.commit()
        doc_id = project.docs[0].id
    stop = threading.Event()
    watcher = threading.Thread(target=project_files.watch, args=(stop,), daemon=True)
    watcher.start()
    try:
        time.sleep(1)  # its first read, and watching started
        (folder() / AGENTS_DOC).write_text("Written by an agent.", encoding="utf-8")
        deadline = time.monotonic() + 15
        body = ""
        while time.monotonic() < deadline:
            with app_db() as db:
                body = db.get(ProjectDoc, doc_id).body
            if body == "Written by an agent.":
                break
            time.sleep(0.1)
        assert body == "Written by an agent."
    finally:
        stop.set()
        watcher.join(10)
    assert not watcher.is_alive()


# ---- folders, on disk ----


def test_the_apps_folders_are_folders_on_disk(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    decisions = projects_svc.create_folder(db, project_id=project.id, name="decisions")
    adr = projects_svc.create_folder(db, project_id=project.id, name="adr", parent_id=decisions.id)
    assert (folder() / "decisions" / "adr").is_dir()
    doc = projects_svc.create_doc(
        db, project_id=project.id, name="decisions/adr/0001", body="Use files."
    )
    assert doc.path == "decisions/adr/0001.md"
    assert (folder() / "decisions" / "adr" / "0001.md").read_text(encoding="utf-8") == "Use files."

    # Renamed, moved: on disk with it.
    projects_svc.update_folder(db, adr.id, name="records")
    assert (folder() / "decisions" / "records" / "0001.md").is_file()
    assert not (folder() / "decisions" / "adr").exists()
    projects_svc.update_doc(db, doc.id, folder_id=None)
    assert (folder() / "0001.md").is_file() and not (
        folder() / "decisions" / "records" / "0001.md"
    ).exists()
    projects_svc.update_folder(db, adr.id, parent_id=None)
    assert (folder() / "records").is_dir() and not (folder() / "decisions" / "records").exists()

    # Deleted, with everything in it.
    projects_svc.create_doc(db, project_id=project.id, name="Plan", folder_id=decisions.id)
    projects_svc.delete_folder(db, decisions.id)
    assert not (folder() / "decisions").exists()


def test_folders_and_files_made_elsewhere_are_the_contexts(db) -> None:
    project = projects_svc.create_project(db, name="Note-app")
    (folder() / "decisions" / "adr").mkdir(parents=True)
    (folder() / "decisions" / "adr" / "0001.md").write_text("Use files.", encoding="utf-8")
    (folder() / "empty").mkdir()
    (folder() / ".git").mkdir()  # hidden: not the context's
    (folder() / ".git" / "HEAD.md").write_text("x", encoding="utf-8")
    project_files.refresh(db, project)
    assert sorted(f.path for f in project.doc_folders) == ["decisions", "decisions/adr", "empty"]
    record = next(d for d in project.docs if d.name == "0001.md")
    assert (record.path, record.body) == ("decisions/adr/0001.md", "Use files.")

    # Moved to another folder by hand: the same document, its history kept.
    (folder() / "records").mkdir()
    (folder() / "decisions" / "adr" / "0001.md").rename(folder() / "records" / "0001.md")
    project_files.refresh(db, project)
    assert record.path == "records/0001.md" and record in project.docs

    # A folder deleted by hand goes, with what it held.
    (folder() / "records" / "0001.md").unlink()
    (folder() / "records").rmdir()
    shutil.rmtree(folder() / "decisions")
    project_files.refresh(db, project)
    assert [f.path for f in project.doc_folders] == ["empty"]
    assert [d.name for d in project.docs] == [AGENTS_DOC]


def test_folders_from_before_get_their_folders_on_disk(db) -> None:
    # As upstream's folders were before they were on disk.
    project = Project(name="Old one", color=1, position=0)
    db.add(project)
    db.flush()
    with db.no_autoflush:
        plans = ProjectDocFolder(name="Plans: Q4")
        project.doc_folders.append(plans)
        project.docs = [
            ProjectDoc(name=AGENTS_DOC, body="Build it."),
            ProjectDoc(name="Launch", body="Soon.", folder=plans),
        ]
    db.flush()
    project_files.sync_all(db)
    assert plans.name == "Plans- Q4"
    assert (folder("old-one") / "Plans- Q4" / "Launch.md").read_text(encoding="utf-8") == "Soon."


def test_a_folder_made_by_hand_for_a_new_project_is_its_own(db) -> None:
    (folder() / "decisions").mkdir(parents=True)
    (folder() / "decisions" / "0001.md").write_text("Use files.", encoding="utf-8")
    project = projects_svc.create_project(db, name="Note-app")
    assert project.folder == "note-app"
    project_files.refresh(db, project)
    assert [d.path for d in projects_svc.docs_of(project)] == [AGENTS_DOC, "decisions/0001.md"]
    assert manifest()["id"] == project.id
    # One that is another project's stays its: the next is numbered on.
    assert projects_svc.create_project(db, name="note app").folder == "note-app-2"
