"""Files first (SPEC.md): words are files, fields and records are rows. A
task is its task.md, a project its project.md, a day's notes their file;
the app writes them after every commit and reads in what is written there
outside it, the database owning the fields."""

import threading
import time
import zipfile
from datetime import date, datetime

from fastmcp import Client
from sqlalchemy import select

from app.mcp.server import mcp
from app.models import (
    HabitCheck,
    NotebookPage,
    Project,
    Setting,
    Task,
    TaskOwner,
    TaskPriority,
    TaskRevision,
    TaskStatus,
)
from app.services import (
    backup,
    documents,
    everyday,
    notebook,
    notebook_md,
    readme,
    settling,
    task_files,
    task_md,
)
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

DAY = date(2026, 10, 11)


def task_md_of(task: Task) -> str:
    return (task_files.folder_of(task.id) / "task.md").read_text(encoding="utf-8")


def a_task(db, **fields) -> Task:  # noqa: ANN001
    task = tasks_svc.create_task(db, title="Fix the feed", **fields)
    db.commit()
    return task


# ---- a task is its task.md ----


def test_a_task_is_written_to_its_task_md(db) -> None:
    project = projects_svc.create_project(db, name="Calendar")
    db.commit()
    task = a_task(
        db, notes="Read the feed.\n- [ ] parse it", acceptance="It parses.",
        project_id=project.id, priority=TaskPriority.high, due=date(2026, 10, 20),
    )
    folder = everyday.projects_dir() / "calendar" / "tasks" / f"{task.id}-fix-the-feed"
    text = (folder / "task.md").read_text(encoding="utf-8")
    front, _ = everyday.split_front_matter(text)
    assert front["id"] == task.id and front["title"] == "Fix the feed"
    assert (front["status"], front["owner"], front["project"]) == ("todo", "oscar", "Calendar")
    assert (front["priority"], front["due"]) == ("high", date(2026, 10, 20))
    assert text.split("---\n", 2)[2] == (
        "\nRead the feed.\n- [ ] parse it\n\n## Acceptance\n\nIt parses.\n\n## Outcome\n"
    )
    # A field changed in the app is in the file at once.
    tasks_svc.set_status(db, task.id, TaskStatus.in_progress)
    db.commit()
    assert "status: in_progress" in task_md_of(task)


def test_a_project_or_workstream_renamed_is_renamed_in_its_tasks_files(db) -> None:
    project = projects_svc.create_project(db, name="Calendar")
    lane = projects_svc.create_workstream(db, project_id=project.id, name="Design")
    db.commit()
    task = a_task(db, project_id=project.id, workstream_id=lane.id)
    projects_svc.update_workstream(db, lane.id, name="Look")
    projects_svc.update_project(db, project.id, name="Planner")
    db.commit()
    text = task_md_of(task)
    assert "project: Planner" in text and "workstream: Look" in text
    assert task_files.folder_of(task.id).parent.parent.name == "planner"


def test_words_written_in_task_md_are_the_tasks(db) -> None:
    task = a_task(db, notes="Old.")
    path = task_files.folder_of(task.id) / "task.md"
    front = path.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    # An agent writes the description, the outcome, and (wrongly) the status.
    edited = front.replace("status: todo", "status: done") + (
        "\n---\n\nNew words.\n- [x] the first part\n\n## Acceptance\n\n## Outcome\n\nIt works.\n"
    )
    path.write_text(edited, encoding="utf-8")
    settling.sync(db)
    db.refresh(task)
    assert (task.notes, task.outcome) == ("New words.\n- [x] the first part", "It works.")
    # The fields are the database's: the status is put back in the file.
    assert task.status == TaskStatus.todo
    assert "status: todo" in task_md_of(task)
    last = db.scalars(select(TaskRevision).order_by(TaskRevision.id.desc())).first()
    assert last.actor == "file"


def test_a_file_edit_and_an_app_edit_at_once_both_stand(db) -> None:
    task = a_task(db, notes="Old.")
    path = task_files.folder_of(task.id) / "task.md"
    path.write_text(path.read_text(encoding="utf-8").replace("Old.", "The agent's."), "utf-8")
    # The app changes a field before the watcher has read the file.
    tasks_svc.update_task(db, task.id, owner=TaskOwner.claude)
    db.commit()
    db.refresh(task)
    assert task.notes == "The agent's." and task.owner == TaskOwner.claude
    assert "owner: claude" in task_md_of(task) and "The agent's." in task_md_of(task)


def test_task_md_reads_its_sections_from_the_end() -> None:
    text = (
        "---\nid: 1\n---\n\n## Acceptance\n\nA heading of the description's own.\n"
        "```\n## Outcome\n```\n\n## Acceptance\n\nDone when.\n\n## Outcome\n\nWhat came.\n"
    )
    words = task_md.parse(text)
    assert words.notes == (
        "## Acceptance\n\nA heading of the description's own.\n```\n## Outcome\n```"
    )
    assert (words.acceptance, words.outcome) == ("Done when.", "What came.")
    assert task_md.parse("Only words.").notes == "Only words."


def test_a_task_deleted_has_its_folder_put_in_the_trash(db) -> None:
    task = a_task(db)
    task_files.create(db, task, "research.md")
    db.commit()
    tasks_svc.delete_task(db, task.id)
    db.commit()
    assert task_files.folder_of(task.id) is None
    [trashed] = everyday.trash_dir().iterdir()
    assert (trashed / "research.md").is_file()


def test_a_folder_with_a_task_md_is_a_new_task(db) -> None:
    project = projects_svc.create_project(db, name="Calendar")
    db.commit()
    folder = everyday.projects_dir() / "calendar" / "tasks" / "write-the-docs"
    folder.mkdir(parents=True)
    (folder / "task.md").write_text(
        "---\ntitle: Write the docs\npriority: low\nstatus: done\n---\n\nAll of them.\n",
        encoding="utf-8",
    )
    (folder / "outline.md").write_text("1. Start", encoding="utf-8")
    settling.sync(db)
    task = db.scalars(select(Task).where(Task.title == "Write the docs")).one()
    assert (task.project_id, task.priority) == (project.id, TaskPriority.low)
    assert task.notes == "All of them."
    # A task made by a file starts open.
    assert task.status == TaskStatus.todo
    assert task_files.folder_of(task.id).name == f"{task.id}-write-the-docs"
    assert task_files.paths(task.id) == ["outline.md"]


def test_a_task_folder_deleted_by_hand_is_written_again(db) -> None:
    task = a_task(db, notes="Kept in the database too.")
    folder = task_files.folder_of(task.id)
    (folder / "task.md").unlink()
    folder.rmdir()
    settling.sync(db)
    assert "Kept in the database too." in task_md_of(task)


def test_a_crash_before_the_files_are_written_is_put_right_as_the_app_starts(db) -> None:
    task = a_task(db, notes="Before.")
    settling.enabled = False
    try:
        tasks_svc.update_task(db, task.id, notes="After.")
        db.commit()
    finally:
        settling.enabled = True
    assert "Before." in task_md_of(task)
    settling.settle_all(db)
    # The file was the app's, so the database's words win.
    assert "After." in task_md_of(task)
    db.refresh(task)
    assert task.notes == "After."


# ---- the everyday files claimed by one database ----


def test_files_of_another_database_are_written_over_not_read_in(db) -> None:
    task = a_task(db, notes="Mine.")
    path = task_files.folder_of(task.id) / "task.md"
    path.write_text(path.read_text(encoding="utf-8").replace("Mine.", "Another's."), "utf-8")
    # The folder was another database's since.
    (everyday.root() / settling.CLAIM_FILE).write_text("someone-else\n", encoding="utf-8")
    settling.settle_all(db)
    db.refresh(task)
    assert task.notes == "Mine." and "Mine." in task_md_of(task)
    # What was there is kept in its history.
    kept = documents.history(db, f"task:{task.id}", "task.md")
    assert "Another's." in kept[0].body
    claim = db.get(Setting, settling.CLAIM_SETTING).value
    assert (everyday.root() / settling.CLAIM_FILE).read_text(encoding="utf-8").strip() == claim


# ---- a project is its project.md ----


def test_a_projects_about_is_its_project_md(db) -> None:
    project = projects_svc.create_project(db, name="Calendar", notes="A planner.")
    projects_svc.create_workstream(db, project_id=project.id, name="Design")
    db.commit()
    path = everyday.projects_dir() / "calendar" / "project.md"
    front, body = everyday.split_front_matter(path.read_text(encoding="utf-8"))
    assert front["name"] == "Calendar"
    assert front["workstreams"] == [{"name": "Design", "status": "open"}]
    assert body == "\nA planner.\n"
    path.write_text(path.read_text(encoding="utf-8").replace("A planner.", "A notebook."), "utf-8")
    settling.sync(db)
    db.refresh(project)
    assert project.notes == "A notebook."


# ---- a day's notes are a file ----


def test_a_days_notes_are_their_file(db) -> None:
    task = a_task(db)
    blocks = [
        {"kind": "stay", "text": "\n- [ ] place: Lisbon"},
        {"kind": "text", "text": "Slow morning.\n- [ ] Fix the feed\n\tits words",
         "links": {"1": task.id}, "folded": [1]},
        {"kind": "reflection", "text": "Calmer."},
    ]
    notebook.save_page(db, DAY, blocks, version=0)
    db.commit()
    path = settling.page_path(DAY)
    assert path == everyday.notebook_dir() / "2026" / "2026-10-11.md"
    assert path.read_text(encoding="utf-8") == (
        "/stay\n\t- [ ] place: Lisbon\nSlow morning.\n"
        f"- [ ] Fix the feed <!-- task:{task.id} folded -->\n\tits words\n/reflection Calmer.\n"
    )
    # Read back as the page's blocks.
    page = notebook.get_page(db, DAY)
    assert notebook_md.parse(path.read_text(encoding="utf-8")) == notebook.normalize(
        db, page.blocks
    )


def test_notes_written_in_their_file_are_the_days(db) -> None:
    notebook.save_page(db, DAY, [{"kind": "text", "text": "Morning."}], version=0)
    db.commit()
    version = notebook.version_of(db, DAY)
    settling.page_path(DAY).write_text("Morning.\n/habit stretch\nEvening.\n", encoding="utf-8")
    settling.sync(db)
    page = notebook.get_page(db, DAY)
    db.refresh(page)
    # A habit is not the notes': "/habit" is words like any other there.
    assert page.blocks == [{"kind": "text", "text": "Morning.\n/habit stretch\nEvening."}]
    assert db.scalars(select(HabitCheck)).first() is None
    # A window with the page open is out of date now.
    assert page.version == version + 1


def test_a_file_for_a_day_with_no_page_makes_it(db) -> None:
    path = settling.page_path(date(2026, 10, 12))
    path.parent.mkdir(parents=True)
    path.write_text("Written by an agent.\n", encoding="utf-8")
    settling.sync(db)
    page = db.scalars(select(NotebookPage)).one()
    assert (page.day, page.blocks) == (date(2026, 10, 12), [
        {"kind": "text", "text": "Written by an agent."}
    ])


# ---- a habit is its file ----


def a_habit(db, name: str = "morning-run", days: str = ""):  # noqa: ANN001, ANN201
    from app.services import habits as habits_svc

    habit = habits_svc.create(db, name, days)
    habit.created_at = datetime(2026, 9, 30, 8, 0)
    db.commit()
    return habit


def habit_file(name: str = "morning-run") -> str:
    return (everyday.habits_dir() / f"{name}.md").read_text(encoding="utf-8")


def test_a_habit_is_its_file(db) -> None:
    from app.services import habits as habits_svc

    habit = a_habit(db, "Morning run", days="024")
    habit.notes = "Five k before work.\n\n- [ ] new shoes"
    habits_svc.set_done(db, habit, DAY, True)
    habits_svc.set_note(db, habit, DAY, "Easy.\nRan the hill too.")
    habits_svc.set_note(db, habit, date(2026, 10, 9), "Knee sore.")
    habits_svc.set_done(db, habit, date(2026, 10, 7), True)  # ticked, nothing said
    db.commit()
    assert habit.slug == "morning-run"
    assert habit_file() == (
        "---\n"
        "# Personal Calendar keeps these fields: an edit here is put back. Change them in the "
        "app,\n"
        "# over its API (README.md at the everyday files' top) or through Claude's tools; a "
        "day is\n"
        "# ticked on Today's habits pane or Calendar's sheet.\n"
        "# The words below, what the habit is and its log (a comment a day), are this file's.\n"
        f"id: {habit.id}\n"
        "name: morning-run\n"
        "days: Mon, Wed, Fri\n"
        "since: '2026-09-30'\n"
        "---\n"
        "\n"
        "Five k before work.\n\n- [ ] new shoes\n"
        "\n"
        "## Log\n"
        "\n"
        "- 2026-10-11: Easy.\n"
        "  Ran the hill too.\n"
        "- 2026-10-09: Knee sore.\n"
    )
    # A comment on a day not ticked: skipped; ticked, done, the comment kept.
    states = {c["day"]: c["state"] for c in habits_svc.grid(db, date(2026, 10, 7), 5)[0]["checks"]}
    assert states[date(2026, 10, 9)] == "skipped"
    assert states[DAY] == "done"
    # Found by its words.
    [found] = documents.search(db, "knee")
    assert (found["owner"], found["path"]) == (f"habit:{habit.id}", "habits/morning-run.md")


def test_words_written_in_a_habits_file_are_the_habits(db) -> None:
    from app.services import habits as habits_svc

    habit = a_habit(db)
    habits_svc.set_done(db, habit, DAY, True)
    habits_svc.set_note(db, habit, date(2026, 10, 9), "Knee sore.")
    db.commit()
    path = everyday.habits_dir() / "morning-run.md"
    # An agent says what it is, comments on a day ticked and on one not,
    # takes a comment out, and (wrongly) renames it in its front matter.
    path.write_text(
        habit_file().replace("name: morning-run", "name: evening-run").split("## Log")[0].replace(
            "---\n\n", "---\n\nWhy: to wake up.\n\n"
        )
        + "## Log\n\n- 2026-10-11: Felt strong.\n- 2026-10-10: Rain.\n  Stayed in.\n"
        "A line of its own.\n",
        encoding="utf-8",
    )
    settling.sync(db)
    db.refresh(habit)
    # What is not an entry stays with what it is, so nothing written is lost.
    assert habit.notes == "Why: to wake up.\n\nA line of its own."
    assert habits_svc.log_of(db, habit) == {
        DAY: "Felt strong.", date(2026, 10, 10): "Rain.\nStayed in.",
    }
    states = {c["day"]: c["state"] for c in habits_svc.grid(db, date(2026, 10, 9), 3)[0]["checks"]}
    # The comment taken out of a day skipped: nothing left of it.
    assert states == {date(2026, 10, 9): None, date(2026, 10, 10): "skipped", DAY: "done"}
    # The fields are the database's: its name is put back in the file.
    assert habit.slug == "morning-run"
    assert "name: morning-run" in habit_file()
    assert "Why: to wake up.\n\nA line of its own.\n\n## Log\n" in habit_file()


def test_a_habit_renamed_moves_its_file_and_deleted_goes_to_the_trash(db) -> None:
    from app.services import habits as habits_svc

    habit = a_habit(db)
    habits_svc.set_note(db, habit, DAY, "Rain.")
    db.commit()
    habits_svc.rename(db, habit.id, "Evening run")
    db.commit()
    assert not (everyday.habits_dir() / "morning-run.md").exists()
    assert "- 2026-10-11: Rain." in habit_file("evening-run")
    assert [f["path"] for f in documents.search(db, "rain")] == ["habits/evening-run.md"]
    habits_svc.delete(db, habit.id)
    db.commit()
    assert list(everyday.habits_dir().iterdir()) == []
    assert (everyday.trash_dir() / "habits" / "evening-run.md").is_file()
    assert documents.search(db, "rain") == []


def test_a_file_in_habits_is_a_new_habit(db) -> None:
    from app.services import habits as habits_svc

    everyday.habits_dir().mkdir(parents=True, exist_ok=True)
    (everyday.habits_dir() / "stretch.md").write_text(
        "---\ndays: Tue, Thu\n---\n\nTen minutes.\n\n## Log\n\n- 2026-10-08: Tight back.\n",
        encoding="utf-8",
    )
    # One whose name cannot be a habit's is left as it is.
    (everyday.habits_dir() / "Not One.md").write_text("Words.", encoding="utf-8")
    settling.sync(db)
    [habit] = habits_svc.list_habits(db)
    assert (habit.slug, habit.days, habit.notes) == ("stretch", "13", "Ten minutes.")
    assert habits_svc.log_of(db, habit) == {date(2026, 10, 8): "Tight back."}
    assert f"id: {habit.id}\nname: stretch\ndays: Tue, Thu\n" in habit_file("stretch")
    assert (everyday.habits_dir() / "Not One.md").read_text(encoding="utf-8") == "Words."


def test_a_habit_file_deleted_by_hand_is_written_again(db) -> None:
    from app.services import habits as habits_svc

    habit = a_habit(db)
    habits_svc.set_note(db, habit, DAY, "Kept in the database too.")
    db.commit()
    (everyday.habits_dir() / "morning-run.md").unlink()
    settling.sync(db)
    assert "Kept in the database too." in habit_file()


# ---- the index, the README, the backup ----


def test_every_file_is_found_by_its_words(db) -> None:
    project = projects_svc.create_project(db, name="Calendar")
    db.commit()
    task = a_task(db, notes="Parse the ICS feed.", project_id=project.id)
    task_files.create(db, task, "research.md")
    task_files.write(db, task.id, "research.md", "# Feeds\nCalDAV is heavier than ICS.")
    notebook.save_page(db, DAY, [{"kind": "text", "text": "Thought about caldav."}], version=0)
    db.commit()
    found = documents.search(db, "caldav")
    assert {f["owner"] for f in found} == {f"task:{task.id}", "notebook"}
    research = next(f for f in found if f["owner"].startswith("task:"))
    assert (research["name"], research["title"]) == ("research.md", "Feeds")
    assert documents.search(db, "pars ics", owners=("task:",))[0]["name"] == "task.md"
    assert documents.search(db, "") == []


def test_ctrl_k_finds_a_task_by_its_outcome(db) -> None:
    from datetime import datetime

    from app.services import search

    task = a_task(db)
    tasks_svc.update_task(db, task.id, outcome="Shipped behind a zebra flag.")
    db.commit()
    found = search.search(db, "zebra", datetime.now())
    assert [t["id"] for t in found["tasks"]] == [task.id]
    # Its task.md is the task, found there, not among the files.
    assert found["files"] == []


async def test_claude_searches_the_files(app_db) -> None:
    with app_db() as db:
        a_task(db, notes="Ask about the dentist.")
    async with Client(mcp) as client:
        found = (await client.call_tool("search", {"query": "dentist"})).data
    assert [f["name"] for f in found] == ["task.md"]


def test_the_readme_says_what_is_where(db) -> None:
    settling.settle_all(db)
    text = (everyday.root() / "README.md").read_text(encoding="utf-8")
    assert "words are files, fields and records are rows" in text
    assert "`file_hash`" in text and "documents_fts" in text
    assert text == readme.text()


def test_the_backup_zips_the_everyday_files_but_clones_and_checkouts(tmp_path, db) -> None:
    a_task(db)
    (everyday.repos_dir() / "app").mkdir(parents=True)
    (everyday.repos_dir() / "app" / "big.bin").write_bytes(b"x")
    (everyday.work_dir() / "1-x").mkdir(parents=True)
    zipped = backup.run_files_backup(everyday.root(), tmp_path / "backups", retain=2,
                                     today=DAY)
    names = zipfile.ZipFile(zipped).namelist()
    assert any(n.endswith("task.md") for n in names)
    assert not any(n.startswith(("repos/", "work/")) for n in names)
    for day in (12, 13):
        backup.run_files_backup(everyday.root(), tmp_path / "backups", retain=2,
                                today=date(2026, 10, day))
    assert sorted(p.name for p in (tmp_path / "backups").iterdir()) == [
        "everyday-files-2026-10-12.zip", "everyday-files-2026-10-13.zip"
    ]


# ---- watched ----


def test_the_watcher_reads_in_a_task_md_written_while_the_app_runs(app_db) -> None:
    with app_db() as db:
        task = a_task(db, notes="Before.")
        task_id = task.id
        path = task_files.folder_of(task_id) / "task.md"
    stop = threading.Event()
    watcher = threading.Thread(target=settling.watch, args=(stop,), daemon=True)
    watcher.start()
    try:
        time.sleep(1.5)  # everything settled, and watching started
        path.write_text(path.read_text(encoding="utf-8").replace("Before.", "After."), "utf-8")
        deadline = time.monotonic() + 15
        notes = ""
        while time.monotonic() < deadline:
            with app_db() as db:
                notes = db.get(Task, task_id).notes
            if notes == "After.":
                break
            time.sleep(0.1)
        assert notes == "After."
    finally:
        stop.set()
        watcher.join(10)
    assert not watcher.is_alive()
    with app_db() as db:
        assert db.scalars(select(Project)).all() == []
