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
    page.goto(f"{live}/plan")
    sheet = page.locator(".main .task-sheet[data-sheet=compose]")
    title = sheet.locator(".sheet-title")
    sheet.locator(".sheet-line").click()

    page.keyboard.type("Buy flowers friday due saturday every week ")
    assert title.text_content() == "Buy flowers "
    assert sheet.locator("input[name=planned_for]").input_value() == next_weekday(4).isoformat()
    assert sheet.locator("input[name=due]").input_value() == next_weekday(5).isoformat()
    assert sheet.locator("input[name=repeat]").input_value() == "weekly"

    # Backspace straight after a conversion puts the words back, and they stay words.
    page.keyboard.type("tomorrow ")
    page.keyboard.press("Backspace")
    assert title.text_content() == "Buy flowers tomorrow"
    assert sheet.locator("input[name=planned_for]").input_value() == next_weekday(4).isoformat()
    page.keyboard.type(" for mum ")
    assert title.text_content() == "Buy flowers tomorrow for mum "

    # A task takes no time on the calendar: a time stays words.
    page.keyboard.type("at 5pm ")
    assert title.text_content() == "Buy flowers tomorrow for mum at 5pm "
    assert sheet.locator("input[name=time]").count() == 0


def test_the_composer_adds_with_its_fields(page, live, app_db) -> None:
    with app_db() as db:
        home = projects_svc.create_project(db, name="Home")
        db.commit()
        home_id = home.id
    page.goto(f"{live}/projects/{home_id}/tasks")
    sheet = page.locator("#no-workstream .task-sheet[data-sheet=compose]")  # Home's
    sheet.locator(".sheet-line").click()
    page.keyboard.type("Water the plants")
    sheet.locator(".prop[data-prop=due]").click()
    # By name, exactly: on a Sunday, Next week's aside also reads "tomorrow".
    page.locator(".sheet-menu").get_by_role("menuitemradio", name="Tomorrow", exact=True).click()
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
        projects_svc.create_workstream(db, project_id=home.id, name="Garden")
        task = tasks_svc.create_task(
            db, title="Mow", project_id=home.id, planned_for=date.today(), notes="- oil"
        )
        db.commit()
        task_id, home_id = task.id, home.id
    page.goto(f"{live}/projects/{home_id}/tasks")

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
    page.locator(".main .prop[data-prop=project]").click()
    page.locator(".sheet-menu [role=menuitemradio]", has_text="Garden").click()
    # Tab walks the icons (estimate the last), the description, and the end line,
    # then out: a save.
    for _ in range(11):
        page.keyboard.press("Tab")
    sheet.wait_for(state="detached")

    with app_db() as db:
        task = tasks_svc.get_task(db, task_id)
        assert task.title == "Mow the lawn"
        assert task.workstream.name == "Garden" and task.project.name == "Home"
        assert task.notes == "- oil"


@pytest.mark.parametrize("leave", ["Alt+1", "Control+k"])
def test_an_edit_goes_with_a_page_chosen_from_the_keys(page, live, app_db, leave) -> None:
    """Left by a key (Alt+1 to Today, or Ctrl+K and Calendar chosen there)
    with a task's sheet still open: what is written is saved as it goes."""
    import time

    # A task is written in its list: its project's Tasks.
    with app_db() as db:
        home = projects_svc.create_project(db, name="Home")
        task_id = tasks_svc.create_task(
            db, title="Mow", planned_for=date.today(), project_id=home.id
        ).id
        db.commit()
    page.goto(f"{live}/projects/{home.id}/tasks")
    page.locator(".task-title-btn", has_text="Mow").click()
    page.locator(".task-sheet[data-sheet=edit][data-ready]").wait_for()
    page.keyboard.type(" the lawn")
    page.keyboard.press(leave)
    if leave == "Control+k":
        page.locator("#command-dialog").wait_for()
        page.keyboard.type("Calendar")
        page.keyboard.press("Enter")
    page.wait_for_url(lambda url: "/projects" not in url)

    end = time.monotonic() + 5
    while time.monotonic() < end:
        with app_db() as db:
            if tasks_svc.get_task(db, task_id).title == "Mow the lawn":
                return
        time.sleep(0.1)
    with app_db() as db:
        assert tasks_svc.get_task(db, task_id).title == "Mow the lawn"



def test_spelling_is_marked_only_in_the_line_being_written(page, live) -> None:
    page.goto(f"{live}/plan")
    sheet = page.locator(".main .task-sheet[data-sheet=compose]")
    title = sheet.locator(".sheet-title")
    sheet.locator(".sheet-line").click()
    page.keyboard.type("Wrte a titel")
    assert title.get_attribute("spellcheck") == "true"

    # From the title into the description: the title is left unmarked, and
    # of the description's lines only the caret's is marked.
    page.keyboard.press("Enter")
    assert title.get_attribute("spellcheck") == "false"
    page.keyboard.type("frst lin")
    page.keyboard.press("Enter")
    page.keyboard.type("secnd lin")
    # The editor's lines are unmarked but for the caret's (spellcheck="true").
    def marked(expected: list) -> None:
        page.wait_for_function(
            """expected => JSON.stringify([...document.querySelectorAll(
                '.main .task-sheet[data-sheet=compose] [data-notes-editor] .cm-line')]
                .map(e => e.closest('[spellcheck]').getAttribute('spellcheck') === 'true'))
                === JSON.stringify(expected)""",
            arg=expected, timeout=3000,
        )

    marked([False, True])
    page.keyboard.press("ArrowUp")
    marked([True, False])
    # Out of it, no line is.
    title.click()
    marked([False, False])


def test_an_estimate_is_written_as_words_or_picked(page, live, app_db) -> None:
    page.goto(f"{live}/plan")
    sheet = page.locator(".main .task-sheet[data-sheet=compose]")
    title = sheet.locator(".sheet-title")
    estimate = sheet.locator("input[name=estimate]")
    sheet.locator(".sheet-line").click()
    page.keyboard.type("Write the report 1h30 ")
    assert title.text_content() == "Write the report "
    assert estimate.input_value() == "90"
    assert sheet.locator(".prop[data-prop=estimate] .prop-value").text_content() == "1h 30m"
    # A bare number stays a word; "2 hours" is an estimate.
    page.keyboard.type("in 3 parts 2 hours ")
    assert title.text_content() == "Write the report in 3 parts "
    assert estimate.input_value() == "120"
    # Its menu: the usual lengths, the current one ticked.
    sheet.locator(".prop[data-prop=estimate]").click()
    menu = page.locator(".sheet-menu")
    two_hours = menu.get_by_role("menuitemradio", name="2h", exact=True)
    assert two_hours.get_attribute("aria-checked") == "true"
    menu.get_by_role("menuitemradio", name="45m", exact=True).click()
    page.keyboard.press("Control+Enter")
    page.locator(".task-row", has_text="Write the report in 3 parts").wait_for()
    with app_db() as db:
        [task] = tasks_svc.list_tasks(db)
        assert task.estimate_minutes == 45
