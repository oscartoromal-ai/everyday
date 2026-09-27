"""Today's notebook in a real browser: writing prose, tasks and reflections
as one document, the keys that move through it, and how it saves. The page
is notebook.js over notes-editor.js and task-sheet.js, which only a browser
runs; the `live` and `page` fixtures are conftest.py's."""

import time
from datetime import date, datetime, timedelta

import pytest

from app.services import notebook as notebook_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)

BLOCKS = """[...document.querySelectorAll('#notebook > [data-block]')].map((b) =>
  b.dataset.block + ':' + (b.querySelector('.task-title, .sheet-title, .nb-gone-title')?.textContent
    ?? b.querySelector('textarea')?.value ?? ''))"""


def stored(app_db) -> list[dict]:
    with app_db() as db:
        page = notebook_svc.get_page(db, TODAY)
        return page.blocks if page else []


def saved_as(app_db, expected: list[dict], timeout: float = 5) -> None:
    """The page as the server has it, once the notebook has saved."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if stored(app_db) == expected:
            return
        time.sleep(0.1)
    assert stored(app_db) == expected


def write(page, text: str) -> None:
    page.keyboard.type(text)


def test_a_day_written_as_one_document(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    page.locator("#notebook .nb-prose").click()
    write(page, "Slow morning.")
    page.keyboard.press("Enter")

    # "- " opens a task box; its words become its fields, as in any sheet.
    write(page, "- Call the dentist tomorrow at 3pm ")
    assert page.evaluate(BLOCKS)[-2:] == ["draft:Call the dentist ", "text:"]
    page.keyboard.press("Enter")
    write(page, "ask about the crown")
    page.keyboard.press("Control+Enter")
    page.locator("#notebook ul.nb-task .task-row", has_text="Call the dentist").wait_for()

    # The caret is on the line after the box: the writing goes on.
    write(page, "Then a walk.")
    page.keyboard.press("Enter")
    write(page, "/ref")
    page.locator(".nb-slash [aria-selected=true]", has_text="Reflection").wait_for()
    page.keyboard.press("Enter")
    write(page, "Calmer than yesterday.")
    page.keyboard.press("Control+Enter")
    write(page, "Evening.")

    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        assert task.title == "Call the dentist"
        assert task.notes == "ask about the crown"
        # Dated tomorrow, with its time on the calendar, and still on today's page.
        assert (task.written_on, task.planned_for) == (TODAY, TOMORROW)
        assert [(b.start, b.end) for b in task.blocks] == [
            (datetime.combine(TOMORROW, datetime.min.time()) + timedelta(hours=15),
             datetime.combine(TOMORROW, datetime.min.time()) + timedelta(hours=16)),
        ]
        task_id = task.id
    saved_as(app_db, [
        {"kind": "text", "text": "Slow morning."},
        {"kind": "task", "id": task_id},
        {"kind": "text", "text": "Then a walk."},
        {"kind": "reflection", "text": "Calmer than yesterday."},
        {"kind": "text", "text": "Evening."},
    ])

    # As written, after a reload; the task shows as it stands, time included.
    page.reload()
    assert page.evaluate(BLOCKS) == [
        "text:Slow morning.",
        "task:Call the dentist",
        "text:Then a walk.",
        "reflection:Calmer than yesterday.",
        "text:Evening.",
    ]
    # RECORD names it and its day; TIME holds its hour.
    row = page.locator("#notebook .task-row")
    assert row.locator(".rec-no").inner_text().lower() == "task " + f"{task_id:03d}"
    assert row.locator(".rec-line.planned").inner_text().lower() == "tomorrow"
    assert row.locator(".cell-time").inner_text().split() == ["15:00", "16:00"]
    assert page.locator("#day-lists .task-row").count() == 0

    # Tomorrow's page lists it, with the way back to where it was written.
    page.keyboard.press("ArrowRight")
    page.wait_for_url(f"**/day/{TOMORROW.isoformat()}")
    origin = page.locator("#also-list .task-row .origin")
    assert origin.inner_text().lower() == "from today"  # set in caps by the sheet
    assert origin.get_attribute("href") == f"/day/{TODAY.isoformat()}"


def test_boxes_open_close_and_step_aside(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    page.locator("#notebook .nb-prose").click()
    write(page, "Morning.")
    page.keyboard.press("Enter")

    # Backspace in a fresh box's empty title puts the line back.
    write(page, "- ")
    page.keyboard.press("Backspace")
    assert page.evaluate(BLOCKS) == ["text:Morning.\n"]

    # N (outside the text) opens a box at the end; Esc on it empty closes it.
    page.keyboard.press("Escape")
    page.keyboard.press("n")
    page.keyboard.press("Escape")
    assert page.locator("#notebook .nb-draft").count() == 0

    page.keyboard.press("Escape")
    page.keyboard.press("n")
    write(page, "Buy bread")
    page.keyboard.press("Escape")
    row = page.locator("#notebook .task-row", has_text="Buy bread")
    row.wait_for()

    # Up from the line after it lands on its row, whose keys then work; a
    # finished task stays where it was written, and so does the cursor.
    page.keyboard.press("ArrowUp")
    page.wait_for_function("document.activeElement.dataset.taskTitle === 'Buy bread'")
    page.keyboard.press("x")
    page.locator("#notebook .task-row.done", has_text="Buy bread").wait_for()
    page.wait_for_timeout(300)
    assert page.evaluate("document.activeElement.dataset.taskTitle") == "Buy bread"
    page.keyboard.press("ArrowUp")
    page.wait_for_function("document.activeElement.matches('.nb-prose')")

    # Deleted from the page, its box goes, and the page saves without it.
    row.hover()
    row.locator(".task-delete").click()
    page.locator("#confirm-dialog [value=go]").click()
    row.wait_for(state="detached")
    assert page.locator("#notebook .nb-task").count() == 0
    saved_as(app_db, [{"kind": "text", "text": "Morning."}])


def test_a_task_deleted_elsewhere_keeps_its_place_quietly(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Old idea", written_on=TODAY)
        notebook_svc.save_page(
            db, TODAY, [{"kind": "task", "id": task.id}, {"kind": "text", "text": "After."}],
            version=0,
        )
        tasks_svc.delete_task(db, task.id)
        db.commit()
    page.goto(f"{live}/today")
    assert page.evaluate(BLOCKS) == ["text:", "task:Old idea", "text:After."]
    page.locator("[data-nb-remove]").click()
    assert page.evaluate(BLOCKS) == ["text:After."]
    saved_as(app_db, [{"kind": "text", "text": "After."}])


def test_a_page_changed_in_another_window_asks_which_to_keep(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    page.locator("#notebook .nb-prose").click()
    write(page, "Mine.")
    saved_as(app_db, [{"kind": "text", "text": "Mine."}])

    # Another window saves over it.
    with app_db() as db:
        notebook_svc.save_page(db, TODAY, [{"kind": "text", "text": "Theirs."}], version=1)
        db.commit()
    write(page, " More.")
    page.locator("#nb-stale:not([hidden])").wait_for()
    assert stored(app_db) == [{"kind": "text", "text": "Theirs."}]

    page.locator("[data-nb-keep]").click()
    saved_as(app_db, [{"kind": "text", "text": "Mine. More."}])
    assert page.locator("#nb-stale").is_hidden()
