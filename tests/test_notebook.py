from datetime import date, datetime, time, timedelta

import pytest

from app.services import DomainError, notebook
from app.services import blocks as blocks_svc
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
    assert notebook.task_ids_on(db, TODAY) == {stray.id}


def test_time_on_a_day_creates_moves_and_clears_the_block(db) -> None:
    task = tasks_svc.create_task(db, title="Run", planned_for=TODAY)
    block = blocks_svc.set_day_time(db, task, TODAY, time(7), None)
    assert (block.start, block.end) == (
        datetime.combine(TODAY, time(7)),
        datetime.combine(TODAY, time(8)),
    )
    moved = blocks_svc.set_day_time(db, task, TODAY, time(18), time(18, 30))
    assert moved.id == block.id and moved.end == datetime.combine(TODAY, time(18, 30))
    blocks_svc.set_day_time(db, task, TODAY, None, None)
    assert task.blocks == []


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
