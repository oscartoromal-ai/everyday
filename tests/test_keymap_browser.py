"""The app's keys as chosen, in a real browser: keys.toml written by hand
changes what a key does on the next page; Keyboard's page records a key,
takes one away and puts the defaults back, the new keys working at once;
the command menu does any action with its key beside it; and the new keys
that do what was mouse-only. The `live`, `page`, `app_db` and `keys_file`
fixtures are conftest.py's."""

from datetime import date, timedelta

import pytest

from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()
DENSE = "document.documentElement.dataset.density === 'compact'"
DARK = "document.documentElement.dataset.theme === 'dark'"


def outside(page) -> None:
    """Focus on nothing in particular, so single keys are the page's."""
    page.evaluate("document.activeElement?.blur()")


def test_keys_written_in_the_file_are_the_ones_that_work(page, live, keys_file) -> None:
    keys_file.write_text(
        '[keys]\n"app.search" = "Ctrl+P"\n"app.density" = "Shift+C"\n"nav.slot1" = "Alt+Q"\n',
        encoding="utf-8",
    )
    page.goto(f"{live}/calendar")
    outside(page)

    page.keyboard.press("Control+k")
    assert not page.locator("#command-dialog[open]").count()
    page.keyboard.press("Control+p")
    page.locator("#command-dialog[open]").wait_for()
    page.keyboard.press("Escape")
    # Closed, the menu's field keeps focus until the browser's next frame.
    page.wait_for_function("!document.getElementById('command-dialog').contains(document.activeElement)")

    page.keyboard.press("c")
    assert not page.evaluate(DENSE)
    page.keyboard.press("Shift+C")
    page.wait_for_function(DENSE)

    # The sidebar's first page (Today) is Alt+Q now, its badge says Q.
    assert page.locator('.nav a[data-slot="1"] .nav-key').text_content() == "Q"
    page.keyboard.press("Alt+1")
    page.wait_for_timeout(200)
    assert page.url.endswith("/calendar")
    page.keyboard.press("Alt+q")
    page.wait_for_url(f"{live}/today")


def test_keyboard_records_a_key_takes_one_away_and_puts_them_back(page, live, keys_file) -> None:
    page.goto(f"{live}/keys")
    row = page.locator('[data-action="app.density"]')
    row.locator("[data-record]").click()
    assert "Press a key" in row.locator("[data-record]").text_content()
    page.keyboard.press("Shift+D")
    page.locator('[data-action="app.density"] [data-remove="Shift+D"]').wait_for()
    assert '"app.density" = ["C", "Shift+D"]' in keys_file.read_text(encoding="utf-8")
    # Kept from the keys at once, with no page drawn again: and no other key
    # did anything while it was recorded (Shift+D is nobody's).
    outside(page)
    page.keyboard.press("Shift+D")
    page.wait_for_function(DENSE)

    page.locator('[data-action="app.density"] [data-remove="C"]').click()
    page.locator('[data-action="app.density"] [data-remove="C"]').wait_for(state="detached")
    assert '"app.density" = "Shift+D"' in keys_file.read_text(encoding="utf-8")
    outside(page)
    page.keyboard.press("c")
    page.wait_for_timeout(150)
    assert page.evaluate(DENSE)  # C does nothing now

    page.locator('[data-action="app.density"] [data-reset]').click()
    page.locator('[data-action="app.density"] [data-remove="C"]').wait_for()
    assert "app.density" not in keys_file.read_text(encoding="utf-8")


def test_esc_lets_a_recording_go_and_a_clash_is_said(page, live, keys_file) -> None:
    page.goto(f"{live}/keys")
    theme = page.locator('[data-action="app.theme"]')
    theme.locator("[data-record]").click()
    page.keyboard.press("Escape")
    assert theme.locator("[data-record]").text_content() == "+"
    assert not keys_file.exists()

    theme.locator("[data-record]").click()
    page.keyboard.press("c")
    clash = page.locator('[data-action="app.theme"] .keys-conflict')
    clash.wait_for()
    assert "Compact rows" in clash.text_content()
    page.locator('[data-action="app.density"] .keys-conflict').wait_for()

    # Every key back, after asking.
    page.locator("[data-reset-all]").click()
    page.locator("#confirm-dialog [value=go]").click()
    clash.wait_for(state="detached")
    assert page.locator("[data-reset-all]").is_disabled()


def test_finding_an_action_by_its_words_or_its_key(page, live) -> None:
    page.goto(f"{live}/keys")
    page.locator("[data-keys-find]").fill("theme")
    shown = page.locator(".keys-action:visible")
    assert shown.count() == 1 and "other theme" in shown.text_content()
    page.locator("[data-keys-find]").fill("ctrl+k")
    assert "Search tasks" in page.locator(".keys-action:visible").first.text_content()


def test_the_command_menu_does_any_action_and_says_its_key(page, live) -> None:
    page.goto(f"{live}/projects")
    page.keyboard.press("Control+k")
    page.locator("#command-dialog[open]").wait_for()
    page.keyboard.type("theme")
    item = page.locator(".command-item", has_text="Switch to the other theme")
    assert item.locator(".command-meta").text_content() == "Ctrl+Shift+L"
    dark = page.evaluate(DARK)
    page.keyboard.press("Enter")
    page.wait_for_function(f"({DARK}) === {str(not dark).lower()}")

    page.keyboard.press("Control+k")
    page.keyboard.type("change the keys")
    page.keyboard.press("Enter")
    page.wait_for_url(f"{live}/keys")


def test_the_new_keys_do_what_was_the_mouses_alone(page, live, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Write the report")
        db.commit()
        task_id = task.id

    # Theme, settings and the sidebar, from anywhere.
    page.goto(f"{live}/projects")
    outside(page)
    dark = page.evaluate(DARK)
    page.keyboard.press("Control+Shift+L")
    page.wait_for_function(f"({DARK}) === {str(not dark).lower()}")
    page.keyboard.press("Control+Shift+B")
    page.wait_for_function("document.documentElement.dataset.rail === 'collapsed'")
    page.keyboard.press("Control+Shift+B")
    page.keyboard.press("Control+,")
    page.locator("#settings-dialog[open]").wait_for()
    page.keyboard.press("Escape")
    page.locator("#settings-dialog[open]").wait_for(state="detached")

    # Shift+A, on Projects: a new project's name.
    outside(page)
    page.keyboard.press("Shift+A")
    assert page.evaluate("document.activeElement.matches('form.new-project input[name=name]')")

    # T, on another day: back to today.
    page.goto(f"{live}/day/{(TODAY - timedelta(days=3)).isoformat()}")
    outside(page)
    page.keyboard.press("t")
    page.wait_for_url(f"{live}/today")

    # On a task's page, Alt+D opens its do date's menu, from its words too.
    page.goto(f"{live}/tasks/{task_id}")
    page.locator("main .sheet-title").click()
    page.keyboard.press("Alt+d")
    page.locator(".sheet-menu[role=menu]").wait_for()

    # Ctrl+Enter on a task list (Plan, the tasks without a day): the cursor's task, on its page.
    page.goto(f"{live}/plan")
    page.locator(".task-row", has_text="Write the report").focus()
    page.keyboard.press("Control+Enter")
    page.wait_for_url(f"{live}/tasks/{task_id}")


def test_a_list_key_chosen_acts_on_the_cursors_row(page, live, app_db, keys_file) -> None:
    with app_db() as db:
        projects_svc.create_project(db, name="Home")
        tasks_svc.create_task(db, title="Alpha")
        tasks_svc.create_task(db, title="Bravo")
        db.commit()
    keys_file.write_text('[keys]\n"task.done" = "Y"\n"list.down" = "ArrowDown"\n', encoding="utf-8")
    page.goto(f"{live}/plan")
    page.locator(".task-row", has_text="Alpha").focus()
    page.keyboard.press("j")  # J no longer moves
    assert page.evaluate("document.activeElement.dataset.taskTitle") == "Alpha"
    page.keyboard.press("x")  # nor X marks it done
    page.wait_for_timeout(200)
    assert not page.locator(".task-row[data-task-title=Alpha] .task-check:checked").count()
    page.keyboard.press("y")
    page.locator(".task-row[data-task-title=Alpha] .task-check:checked").wait_for()


def test_a_calendar_key_chosen_switches_its_view(page, live, keys_file) -> None:
    keys_file.write_text('[keys]\n"calendar.week" = "Shift+W"\n', encoding="utf-8")
    page.goto(f"{live}/calendar?view=day")
    outside(page)
    assert page.locator("[data-calendar-view=week]").get_attribute("aria-keyshortcuts") == "Shift+W"
    page.keyboard.press("w")
    page.wait_for_timeout(200)
    assert "view=week" not in page.url
    page.keyboard.press("Shift+W")
    page.wait_for_url("**view=week**")


def test_a_mark_key_chosen_writes_the_mark_in_a_description(page, live, app_db, keys_file) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Japan", notes="the rail pass")
        db.commit()
        task_id = task.id
    keys_file.write_text('[keys]\n"editor.bold" = "Alt+B"\n', encoding="utf-8")
    page.goto(f"{live}/tasks/{task_id}")
    page.locator(".cm-line", has_text="rail pass").click()
    page.keyboard.press("End")
    page.keyboard.press("Shift+Control+ArrowLeft")
    page.keyboard.press("Control+b")  # Ctrl+B is not bold any more
    assert page.locator("main textarea[name=notes]").input_value() == "the rail pass"
    page.keyboard.press("Alt+b")
    assert page.locator("main textarea[name=notes]").input_value() == "the rail **pass**"
