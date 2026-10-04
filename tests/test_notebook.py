from datetime import date, timedelta

import pytest

from app.models import TaskStatus
from app.services import DomainError, notebook
from app.services import tasks as tasks_svc

TODAY = date.today()


def test_a_page_keeps_what_was_written_in_order(db) -> None:
    task = tasks_svc.create_task(db, title="Call the dentist", written_on=TODAY)
    page = notebook.save_page(
        db,
        TODAY,
        [
            {"kind": "text", "text": "\nSlow morning.\r\nCoffee first.\n  \n"},
            {"kind": "task", "id": task.id},
            {"kind": "text", "text": "   "},
            {"kind": "reflection", "text": "Calmer than yesterday."},
            {"kind": "text", "text": "Evening."},
        ],
        version=0,
    )
    assert page.version == 1
    # Blank lines are trimmed from the page's top and a reflection's edges;
    # between blocks they are the notes' spacing, kept.
    assert page.blocks == [
        {"kind": "text", "text": "Slow morning.\nCoffee first.\n  \n"},
        {"kind": "task", "id": task.id},
        {"kind": "text", "text": "   "},
        {"kind": "reflection", "text": "Calmer than yesterday."},
        {"kind": "text", "text": "Evening."},
    ]


def test_a_reflection_keeps_the_blank_lines_around_it(db) -> None:
    blocks = [
        {"kind": "text", "text": "\nMorning.\n"},
        {"kind": "reflection", "text": "\nCalmer.\nSlept well.\n\n"},
        {"kind": "text", "text": "\nAfter.\n\n"},
    ]
    # Its words keep their blank first line (written under its first row).
    assert notebook.normalize(db, blocks) == [
        {"kind": "text", "text": "Morning.\n"},
        {"kind": "reflection", "text": "\nCalmer.\nSlept well."},
        {"kind": "text", "text": "\nAfter."},
    ]


def test_a_save_from_an_older_copy_is_refused(db) -> None:
    notebook.save_page(db, TODAY, [{"kind": "text", "text": "one"}], version=0)
    with pytest.raises(notebook.StalePage):
        notebook.save_page(db, TODAY, [{"kind": "text", "text": "two"}], version=0)
    assert notebook.get_page(db, TODAY).blocks == [{"kind": "text", "text": "one"}]


def test_prose_split_by_nothing_joins_and_unknown_tasks_drop(db) -> None:
    blocks = notebook.normalize(
        db,
        [
            {"kind": "text", "text": "a"},
            {"kind": "task", "id": 999},
            {"kind": "text", "text": "b"},
        ],
    )
    assert blocks == [{"kind": "text", "text": "a\nb"}]
    with pytest.raises(DomainError):
        notebook.normalize(db, [{"kind": "poem", "text": "x"}])


def test_tasks_read_as_they_stand_now(db) -> None:
    kept = tasks_svc.create_task(db, title="Buy milk", written_on=TODAY)
    gone = tasks_svc.create_task(db, title="Old idea", written_on=TODAY)
    notebook.save_page(
        db, TODAY, [{"kind": "task", "id": kept.id}, {"kind": "task", "id": gone.id}], version=0
    )
    # Moved to another day elsewhere: it stays on the page it was written on.
    tasks_svc.update_task(db, kept.id, planned_for=TODAY + timedelta(days=3))
    tasks_svc.delete_task(db, gone.id)

    blocks = notebook.blocks_of(db, TODAY)
    assert blocks[0]["task"].planned_for == TODAY + timedelta(days=3)
    assert blocks[1]["task"] is None and blocks[1]["last_known"]["title"] == "Old idea"


def test_a_task_whose_reference_never_landed_still_shows(db) -> None:
    notebook.save_page(db, TODAY, [{"kind": "text", "text": "Morning."}], version=0)
    stray = tasks_svc.create_task(db, title="Water plants", written_on=TODAY)
    blocks = notebook.blocks_of(db, TODAY)
    assert [b["kind"] for b in blocks] == ["text", "task"]
    assert blocks[1]["id"] == stray.id
    assert notebook.task_ids_on(db, TODAY) == [stray.id]


def test_folded_task_rows_follow_their_text(db) -> None:
    blocks = [
        {"kind": "text", "text": "\n- [ ] a\n\tx", "folded": [1]},
        {"kind": "text", "text": "- [ ] b\n\ty", "folded": [0, 9]},
    ]
    # Trimmed from the top and joined, each still names its row; one past
    # the text is dropped.
    assert notebook.normalize(db, blocks) == [
        {"kind": "text", "text": "- [ ] a\n\tx\n- [ ] b\n\ty", "folded": [0, 2]},
    ]


def test_a_stay_keeps_its_items_as_written(db) -> None:
    text = "\n- [x] place: Lisbon\n- [ ] accommodation:\n- [ ] ferry\nno rush"
    page = notebook.save_page(
        db, TODAY - timedelta(days=1), [{"kind": "stay", "text": text + "\n\n"}], version=0
    )
    assert page.blocks == [{"kind": "stay", "text": text}]
    # Its items: each named, its value, sorted or not; its other lines its note.
    assert notebook.stay_items(text) == [
        {"name": "place", "value": "Lisbon", "done": True},
        {"name": "accommodation", "value": "", "done": False},
        {"name": "ferry", "value": "", "done": False},
    ]
    # A stay written later starts with them; the first ever with place and accommodation.
    assert notebook.last_stay_items(db, TODAY) == ["place", "accommodation", "ferry"]
    assert notebook.last_stay_items(db, TODAY - timedelta(days=1)) == ["place", "accommodation"]


def test_the_tasks_still_open_from_the_last_page_with_tasks(db) -> None:
    def written(day: date, *tasks) -> None:
        rows = "\n".join(f"- [ ] {t.title}" for t in tasks)
        links = {str(n): t.id for n, t in enumerate(tasks)}
        notebook.save_page(db, day, [{"kind": "text", "text": rows, "links": links}], version=0)

    def task(title: str, **fields):
        return tasks_svc.create_task(db, title=title, **fields)

    friday = TODAY - timedelta(days=3)
    written(friday - timedelta(days=1), task("From Thursday"))
    overdue = task("Call the bank", planned_for=friday)
    undated = task("Sort the photos")
    for_today = task("Pay rent", planned_for=TODAY)
    for_later = task("Plan the trip", planned_for=TODAY + timedelta(days=4))
    done = task("Buy milk", planned_for=friday)
    dropped = task("Old idea")
    written(friday, for_later, overdue, done, undated, dropped, for_today)
    tasks_svc.set_status(db, done.id, TaskStatus.done)
    tasks_svc.set_status(db, dropped.id, TaskStatus.cancelled)
    # A page with no tasks is passed over.
    yesterday = TODAY - timedelta(days=1)
    notebook.save_page(db, yesterday, [{"kind": "text", "text": "Rest."}], version=0)

    # From the last page before today that holds tasks: the open ones to be
    # worked by today (not those dated later), in the page's order.
    assert notebook.still_open(db, TODAY) == (friday, [overdue, undated, for_today])
    # The first page ever has nothing to bring.
    assert notebook.still_open(db, friday - timedelta(days=1)) == (None, [])


def test_a_windows_later_save_stands_over_its_earlier_one(db) -> None:
    def save(text: str, version: int, writer: str = "", seq: int = 0):  # noqa: ANN202
        blocks = [{"kind": "text", "text": text}]
        return notebook.save_page(db, TODAY, blocks, version=version, writer=writer, seq=seq)

    def text() -> str:
        return notebook.get_page(db, TODAY).blocks[0]["text"]

    save("Groceries", 0, "a", 1)
    # Its next save, from the copy before the first landed: it stands.
    save("Groceries, bank", 0, "a", 2)
    assert (text(), notebook.version_of(db, TODAY)) == ("Groceries, bank", 2)
    # An earlier save of its own landing late is stood over.
    with pytest.raises(notebook.SupersededSave):
        save("Groceries", 1, "a", 1)
    # Another window's copy from before is refused, as is the same window's
    # once anyone else (another window, the sheet) has saved since.
    with pytest.raises(notebook.StalePage):
        save("Gym", 1, "b", 1)
    save("Gym", 2, "", 0)
    with pytest.raises(notebook.StalePage):
        save("Groceries, bank, post", 2, "a", 3)
    assert text() == "Gym"
