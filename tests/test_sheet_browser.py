"""The task sheet in a real browser: typed words, menus, adding, and editing
that saves when focus leaves. The sheet is mostly task-sheet.js, which only a
browser runs; the app serves from a thread over a throwaway database
(the `live` and `page` fixtures, conftest.py)."""

from datetime import date, timedelta

import pytest

from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")


def next_weekday(day: int) -> date:
    """The sheet's reading of a weekday's name: the next one after today."""
    today = date.today()
    return today + timedelta(days=(day - today.weekday() - 1) % 7 + 1)


def test_typed_words_become_fields_and_backspace_takes_them_back(page, live) -> None:
    page.goto(f"{live}/")
    sheet = page.locator(".task-sheet[data-sheet=compose]")
    title = sheet.locator(".sheet-title")
    sheet.locator(".sheet-line").click()

    page.keyboard.type("Buy flowers friday at 5pm due saturday every week ")
    assert title.text_content() == "Buy flowers "
    assert sheet.locator("input[name=planned_for]").input_value() == next_weekday(4).isoformat()
    assert sheet.locator("input[name=time]").input_value() == "17:00-18:00"
    assert sheet.locator("input[name=due]").input_value() == next_weekday(5).isoformat()
    assert sheet.locator("input[name=repeat]").input_value() == "weekly"

    # Backspace straight after a conversion puts the words back, and they stay words.
    page.keyboard.type("tomorrow ")
    page.keyboard.press("Backspace")
    assert title.text_content() == "Buy flowers tomorrow"
    assert sheet.locator("input[name=planned_for]").input_value() == next_weekday(4).isoformat()
    page.keyboard.type(" for mum ")
    assert title.text_content() == "Buy flowers tomorrow for mum "

    # A time is a time only when it says so: a colon, am/pm, or "at".
    page.keyboard.type("and 2 cards 9-10:30am ")
    assert title.text_content() == "Buy flowers tomorrow for mum and 2 cards "
    assert sheet.locator("input[name=time]").input_value() == "09:00-10:30"


def test_the_composer_adds_with_its_fields(page, live, app_db) -> None:
    with app_db() as db:
        projects_svc.create_project(db, name="Home")
        db.commit()
    page.goto(f"{live}/projects")
    sheet = page.locator(".task-sheet[data-sheet=compose]")
    sheet.locator(".sheet-line").click()
    page.keyboard.type("Water the plants")
    sheet.locator(".prop[data-prop=due]").click()
    page.locator(".sheet-menu [role=menuitemradio]", has_text="Tomorrow").click()
    # The menu hands the caret back to the title, where writing carries on.
    assert page.evaluate("document.activeElement.className") == "sheet-title"
    page.keyboard.press("Control+Enter")
    page.locator(".task-row", has_text="Water the plants").wait_for()

    with app_db() as db:
        task = next(t for t in tasks_svc.list_tasks(db) if t.title == "Water the plants")
        assert task.due == date.today() + timedelta(days=1)
        assert task.project.name == "Home"
    assert sheet.locator(".sheet-title").text_content() == ""


def test_editing_saves_when_focus_leaves_the_sheet(page, live, app_db) -> None:
    with app_db() as db:
        home = projects_svc.create_project(db, name="Home")
        projects_svc.create_milestone(db, project_id=home.id, name="Garden")
        task = tasks_svc.create_task(db, title="Mow", planned_for=date.today(), notes="- oil")
        db.commit()
        task_id = task.id
    page.goto(f"{live}/today")

    # Opened and left untouched: back to the row, with nothing posted.
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    # Ready once task-sheet.js has taken it (htmx:load, after htmx settles the swap).
    sheet = page.locator(".task-sheet[data-sheet=edit][data-ready]")
    page.locator(".task-title-btn", has_text="Mow").click()
    sheet.wait_for()
    page.keyboard.press("Escape")
    sheet.wait_for(state="detached")
    page.locator(f"#task-{task_id}.task-row").wait_for()
    assert posts == []

    page.locator(".task-title-btn", has_text="Mow").click()
    sheet.wait_for()
    page.keyboard.type(" the lawn")
    page.locator(".prop[data-prop=project]").click()
    page.locator(".sheet-menu [role=menuitemradio]", has_text="Garden").click()
    # Tab walks the icons, the description, and the end line, then out: a save.
    for _ in range(10):
        page.keyboard.press("Tab")
    sheet.wait_for(state="detached")

    with app_db() as db:
        task = tasks_svc.get_task(db, task_id)
        assert task.title == "Mow the lawn"
        assert task.milestone.name == "Garden" and task.project.name == "Home"
        assert task.notes == "- oil"
