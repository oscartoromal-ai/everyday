"""A task's files (app.services.task_files): Markdown documents in a folder
of the everyday files' tasks/ for each task, found by its id, written whole,
refused from a stale copy, and never outside the folder."""

import pytest

from app.services import DomainError, everyday, task_files
from app.services import tasks as tasks_svc


@pytest.fixture
def task(db, everyday_files):  # noqa: ANN001, ANN201
    task = tasks_svc.create_task(db, title="Widen the task page!")
    db.commit()
    return task


def test_a_task_has_no_folder_until_it_has_a_file(task) -> None:
    assert task_files.folder_of(task.id) is None
    assert task_files.tree(task.id) == []
    assert task_files.create(task, "plan") == "plan.md"
    folder = task_files.folder_of(task.id)
    assert folder == everyday.tasks_dir() / f"{task.id}-widen-the-task-page"
    assert (folder / "plan.md").read_text(encoding="utf-8") == ""


def test_its_folder_is_found_by_its_id_whatever_it_is_called_now(task, db) -> None:
    task_files.create(task, "plan.md")
    tasks_svc.update_task(db, task.id, title="Something else")
    assert task_files.folder_of(task.id).name == f"{task.id}-widen-the-task-page"
    # Another task's id that starts the same is another folder.
    other = tasks_svc.create_task(db, title="Ten")
    db.commit()
    assert task_files.folder_of(other.id) is None


def test_the_tree_holds_folders_then_files_by_name(task) -> None:
    for path in ("Plan.md", "research/trees.md", "research/apps/obsidian.md", "notes.md"):
        task_files.create(task, path)
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


def test_a_file_is_written_whole_and_read_back(task) -> None:
    task_files.create(task, "plan.md")
    version = task_files.write(task.id, "plan.md", "# Plan\r\n- [ ] one\r\n")
    assert task_files.read(task.id, "plan.md") == ("# Plan\n- [ ] one\n", "plan.md")
    assert version == everyday.version("# Plan\n- [ ] one\n")


def test_a_save_from_a_stale_copy_is_refused(task) -> None:
    task_files.create(task, "plan.md")
    first = task_files.write(task.id, "plan.md", "mine")
    # An agent writes the file meanwhile.
    (task_files.folder_of(task.id) / "plan.md").write_text("theirs", encoding="utf-8")
    with pytest.raises(task_files.FileChanged) as caught:
        task_files.write(task.id, "plan.md", "mine, more", base=first)
    assert caught.value.version == everyday.version("theirs")
    # Kept over theirs, knowingly.
    task_files.write(task.id, "plan.md", "mine, more", base=caught.value.version)
    assert task_files.read(task.id, "plan.md")[0] == "mine, more"


@pytest.mark.parametrize("path", ["../escape.md", "C:/escape.md", "a/../../b.md", "", "con.md"])
def test_a_path_out_of_its_folder_or_one_windows_refuses_is_refused(task, path) -> None:
    task_files.create(task, "plan.md")
    with pytest.raises(DomainError):
        task_files.create(task, path)


def test_one_file_a_name(task) -> None:
    task_files.create(task, "plan.md")
    with pytest.raises(DomainError, match="already"):
        task_files.create(task, "plan")


def test_a_file_is_renamed_in_its_folder(task) -> None:
    task_files.create(task, "research/trees.md")
    task_files.create(task, "research/apps.md")
    assert task_files.rename(task.id, "research/trees.md", "Trees seen") == "research/Trees seen.md"
    with pytest.raises(DomainError, match="already"):
        task_files.rename(task.id, "research/Trees seen.md", "apps")
    # Its case alone.
    assert task_files.rename(task.id, "research/apps.md", "Apps") == "research/Apps.md"


def test_a_deleted_file_takes_the_folders_it_empties_with_it(task) -> None:
    task_files.create(task, "research/apps/obsidian.md")
    task_files.create(task, "plan.md")
    task_files.delete(task.id, "research/apps/obsidian.md")
    folder = task_files.folder_of(task.id)
    assert not (folder / "research").exists()
    assert task_files.paths(task.id) == ["plan.md"]


# ---- on the task's page ----


def test_a_file_opens_on_the_tasks_page_in_place_of_its_description(client, task) -> None:
    task_files.create(task, "research/trees.md")
    task_files.write(task.id, "research/trees.md", "# Trees")
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


def test_the_api_names_a_tasks_files(client, task) -> None:
    got = client.get(f"/api/tasks/{task.id}").json()
    assert got["files_folder"].endswith(f"{task.id}-widen-the-task-page")
    assert got["files"] == []
    task_files.create(task, "plan.md")
    assert client.get(f"/api/tasks/{task.id}").json()["files"] == ["plan.md"]
