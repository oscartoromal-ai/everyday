"""A task's folder and its files (app.services.task_files): every task has a
folder, in its project's folder of the everyday files (or the top tasks/),
following the task as it moves or is renamed; task.md there is the task,
and beside it Markdown files written whole, refused from a stale copy, and
never outside the folder."""

import pytest

from app.services import DomainError, everyday, task_files
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc


@pytest.fixture
def task(db, everyday_files):  # noqa: ANN001, ANN201
    task = tasks_svc.create_task(db, title="Widen the task page!")
    db.commit()
    return task


def test_every_task_has_a_folder_holding_its_task_md(task) -> None:
    folder = task_files.folder_of(task.id)
    assert folder == everyday.tasks_dir() / f"{task.id}-widen-the-task-page"
    assert (folder / "task.md").is_file()
    # task.md is the task, not one of its files.
    assert task_files.tree(task.id) == []


def test_its_folder_follows_the_task(task, db) -> None:
    project = projects_svc.create_project(db, name="Calendar")
    db.commit()
    task_files.create(db, task, "plan.md")
    tasks_svc.update_task(db, task.id, project_id=project.id)
    db.commit()
    moved = everyday.projects_dir() / "calendar" / "tasks" / f"{task.id}-widen-the-task-page"
    assert task_files.folder_of(task.id) == moved
    assert (moved / "plan.md").is_file() and (moved / "task.md").is_file()
    assert not (everyday.tasks_dir() / f"{task.id}-widen-the-task-page").exists()
    tasks_svc.update_task(db, task.id, title="Something else")
    db.commit()
    assert task_files.folder_of(task.id).name == f"{task.id}-something-else"
    # Another task's id that starts the same is another folder.
    other = tasks_svc.create_task(db, title="Ten")
    db.commit()
    assert task_files.folder_of(other.id).name == f"{other.id}-ten"


def test_a_second_folder_of_a_task_is_merged_into_it(task) -> None:
    folder = task_files.folder_of(task.id)
    (folder / "plan.md").write_text("mine", encoding="utf-8")
    # An agent writing to where the folder was before it moved.
    stray = everyday.tasks_dir() / f"{task.id}-old-title"
    (stray / "research").mkdir(parents=True)
    (stray / "plan.md").write_text("theirs", encoding="utf-8")
    (stray / "research" / "notes.md").write_text("notes", encoding="utf-8")
    assert task_files.arrange(task) == folder
    assert not stray.exists()
    assert (folder / "plan.md").read_text(encoding="utf-8") == "mine"
    assert (folder / "plan (2).md").read_text(encoding="utf-8") == "theirs"
    assert (folder / "research" / "notes.md").is_file()


def test_task_md_is_not_a_file_to_make_or_rename_to(task, db) -> None:
    with pytest.raises(DomainError, match="task itself"):
        task_files.create(db, task, "task.md")
    task_files.create(db, task, "plan.md")
    with pytest.raises(DomainError, match="task itself"):
        task_files.rename(db, task.id, "plan.md", "task")
    # In a folder of its own, it is a file like any other.
    assert task_files.create(db, task, "drafts/task.md") == "drafts/task.md"


def test_the_tree_holds_folders_then_files_by_name(task, db) -> None:
    for path in ("Plan.md", "research/trees.md", "research/apps/obsidian.md", "notes.md"):
        task_files.create(db, task, path)
    folder = task_files.folder_of(task.id)
    (folder / "picture.png").write_bytes(b"")  # not Markdown: not shown
    (folder / ".hidden.md").write_text("", encoding="utf-8")
    assert task_files.tree(task.id) == [
        {
            "kind": "folder",
            "name": "research",
            "path": "research",
            "children": [
                {
                    "kind": "folder",
                    "name": "apps",
                    "path": "research/apps",
                    "children": [
                        {"kind": "file", "name": "obsidian.md", "path": "research/apps/obsidian.md"}
                    ],
                },
                {"kind": "file", "name": "trees.md", "path": "research/trees.md"},
            ],
        },
        {"kind": "file", "name": "notes.md", "path": "notes.md"},
        {"kind": "file", "name": "Plan.md", "path": "Plan.md"},
    ]
    assert task_files.paths(task.id) == [
        "research/apps/obsidian.md",
        "research/trees.md",
        "notes.md",
        "Plan.md",
    ]


def test_a_file_is_written_whole_and_read_back(task, db) -> None:
    task_files.create(db, task, "plan.md")
    version = task_files.write(db, task.id, "plan.md", "# Plan\r\n- [ ] one\r\n")
    assert task_files.read(task.id, "plan.md") == ("# Plan\n- [ ] one\n", "plan.md")
    assert version == everyday.version("# Plan\n- [ ] one\n")


def test_a_save_from_a_stale_copy_is_refused(task, db) -> None:
    task_files.create(db, task, "plan.md")
    first = task_files.write(db, task.id, "plan.md", "mine")
    # An agent writes the file meanwhile.
    (task_files.folder_of(task.id) / "plan.md").write_text("theirs", encoding="utf-8")
    with pytest.raises(task_files.FileChanged) as caught:
        task_files.write(db, task.id, "plan.md", "mine, more", base=first)
    assert caught.value.version == everyday.version("theirs")
    # Kept over theirs, knowingly.
    task_files.write(db, task.id, "plan.md", "mine, more", base=caught.value.version)
    assert task_files.read(task.id, "plan.md")[0] == "mine, more"


@pytest.mark.parametrize("path", ["../escape.md", "C:/escape.md", "a/../../b.md", "", "con.md"])
def test_a_path_out_of_its_folder_or_one_windows_refuses_is_refused(task, db, path) -> None:
    task_files.create(db, task, "plan.md")
    with pytest.raises(DomainError):
        task_files.create(db, task, path)


def test_one_file_a_name(task, db) -> None:
    task_files.create(db, task, "plan.md")
    with pytest.raises(DomainError, match="already"):
        task_files.create(db, task, "plan")


def test_a_file_is_renamed_in_its_folder(task, db) -> None:
    task_files.create(db, task, "research/trees.md")
    task_files.create(db, task, "research/apps.md")
    renamed = task_files.rename(db, task.id, "research/trees.md", "Trees seen")
    assert renamed == "research/Trees seen.md"
    with pytest.raises(DomainError, match="already"):
        task_files.rename(db, task.id, "research/Trees seen.md", "apps")
    # Its case alone.
    assert task_files.rename(db, task.id, "research/apps.md", "Apps") == "research/Apps.md"


def test_a_deleted_file_takes_the_folders_it_empties_with_it(task, db) -> None:
    task_files.create(db, task, "research/apps/obsidian.md")
    task_files.create(db, task, "plan.md")
    task_files.delete(db, task.id, "research/apps/obsidian.md")
    folder = task_files.folder_of(task.id)
    assert not (folder / "research").exists()
    assert task_files.paths(task.id) == ["plan.md"]


# ---- on the task's page ----


def test_a_file_opens_on_the_tasks_page_in_place_of_its_description(client, task, db) -> None:
    task_files.create(db, task, "research/trees.md")
    task_files.write(db, task.id, "research/trees.md", "# Trees")
    html = client.get(f"/tasks/{task.id}/files/research/trees.md").text
    assert '<input class="doc-name" data-doc-name value="trees.md"' in html
    assert 'data-path="research/trees.md"' in html
    assert "# Trees</textarea>" in html
    assert f'<a class="page-back" href="/tasks/{task.id}">Widen the task page!</a>' in html
    # The map: its description, its files, the one open marked.
    assert f'href="/tasks/{task.id}" style="--depth: 1">' in html
    assert ">Description<" in html
    trees = f'href="/tasks/{task.id}/files/research/trees.md" style="--depth: 2"'
    assert f'{trees} title="research/trees.md" aria-current="page"' in html
    assert client.get(f"/tasks/{task.id}/files/gone.md").status_code == 404
    # Its description's page lists them too, the description marked.
    html = client.get(f"/tasks/{task.id}").text
    assert f'href="/tasks/{task.id}" style="--depth: 1" aria-current="page">' in html
    assert "trees.md" in html


def test_a_file_is_added_written_renamed_and_deleted_from_the_page(client, task) -> None:
    added = client.post(f"/ui/tasks/{task.id}/files", data={"path": "notes/plan"})
    assert added.status_code == 204
    assert added.headers["HX-Redirect"] == f"/tasks/{task.id}/files/notes/plan.md"
    saved = client.post(
        f"/ui/tasks/{task.id}/file",
        data={"path": "notes/plan.md", "body": "# Plan", "base": everyday.version("")},
    ).json()
    assert saved == {
        "version": everyday.version("# Plan"),
        "name": "plan.md",
        "path": "notes/plan.md",
        "href": f"/tasks/{task.id}/files/notes/plan.md",
    }
    # From a copy older than the file: refused, with the file's version.
    stale = client.post(
        f"/ui/tasks/{task.id}/file",
        data={"path": "notes/plan.md", "body": "old", "base": everyday.version("")},
    )
    assert stale.status_code == 409
    assert stale.json()["version"] == everyday.version("# Plan")
    renamed = client.post(
        f"/ui/tasks/{task.id}/file", data={"path": "notes/plan.md", "name": "The plan"}
    ).json()
    assert renamed["path"] == "notes/The plan.md"
    assert renamed["href"] == f"/tasks/{task.id}/files/notes/The%20plan.md"
    latest = client.get(f"/ui/tasks/{task.id}/file", params={"path": "notes/The plan.md"})
    assert latest.json()["body"] == "# Plan"
    gone = client.post(f"/ui/tasks/{task.id}/file/delete", data={"path": "notes/The plan.md"})
    assert gone.headers["HX-Redirect"] == f"/tasks/{task.id}"
    assert task_files.paths(task.id) == []


def test_a_path_out_of_the_folder_is_refused_from_the_page(client, task) -> None:
    answer = client.post(f"/ui/tasks/{task.id}/files", data={"path": "../../escape"})
    assert answer.status_code == 422


def test_handed_to_an_agent_from_a_files_page(client, task, db) -> None:
    from app.models import TaskOwner

    assert client.post(f"/ui/tasks/{task.id}/owner", data={"owner": "claude"}).status_code == 204
    db.refresh(task)
    assert task.owner == TaskOwner.claude


def test_the_api_names_a_tasks_files(client, task, db) -> None:
    got = client.get(f"/api/tasks/{task.id}").json()
    assert got["files_folder"].endswith(f"{task.id}-widen-the-task-page")
    assert got["task_file"] == str(task_files.folder_of(task.id) / "task.md")
    assert got["files"] == []
    task_files.create(db, task, "plan.md")
    assert client.get(f"/api/tasks/{task.id}").json()["files"] == ["plan.md"]
