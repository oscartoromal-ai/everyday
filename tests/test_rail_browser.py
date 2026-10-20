"""The sidebar in a real browser: modules hidden by their eye and brought
back from Settings, a section going once all its modules do; modules,
sections and projects dragged (never out of their section) and by Alt+Up/Down,
each kept through a reload. The `live`, `page` and `app_db` fixtures are
conftest.py's."""

import time

import pytest

from app.services import projects as projects_svc
from app.services import rail as rail_svc

pytest.importorskip("playwright.sync_api")


def drag(page, source, target, *, below: bool = False) -> None:
    """Press on source, move in steps to target's top (or bottom) quarter, let go,
    once the last drop's slides are over (they move what is measured)."""
    page.wait_for_function("() => document.getAnimations().length === 0")
    # A rail taller than the window scrolls its nav: both in sight, as a hand would have them.
    target.scroll_into_view_if_needed()
    source.scroll_into_view_if_needed()
    start = source.bounding_box()
    end = target.bounding_box()
    page.mouse.move(start["x"] + 30, start["y"] + start["height"] / 2)
    page.mouse.down()
    y = end["y"] + end["height"] * (0.85 if below else 0.15)
    page.mouse.move(start["x"] + 30, y, steps=12)
    page.mouse.up()


def sections(page) -> list[str]:
    return page.eval_on_selector_all(
        ".nav > .nav-group", "gs => gs.filter(g => g.checkVisibility()).map(g => g.dataset.section)"
    )


def modules(page, section: str) -> list[str]:
    return page.eval_on_selector_all(
        f'.nav-group[data-section="{section}"] > .nav-item:not([hidden])',
        "is => is.map(i => i.dataset.module)",
    )


def numbers(page) -> dict[str, str]:
    """Each module's Alt+number, top to bottom, as its link and its figure say."""
    found = page.eval_on_selector_all(
        ".nav-item",
        """is => is.map(i => [
            i.dataset.module,
            i.querySelector("a").getAttribute("aria-keyshortcuts"),
            i.querySelector(".nav-key").textContent,
        ])""",
    )
    for _, shortcut, figure in found:
        assert shortcut == (f"Alt+{figure}" if figure else None)
    return {module: figure for module, _, figure in found if figure}


def saved(app_db) -> list[tuple[str, list[str], bool]]:
    with app_db() as db:
        return [
            (s.section.key, [m.module.key for m in s.modules if not m.hidden], s.hidden)
            for s in rail_svc.layout(db)
        ]


def until(check) -> None:
    """The sidebar saves after the page has changed: wait for the database."""
    deadline = time.monotonic() + 5
    while not check():
        assert time.monotonic() < deadline, "not saved"
        time.sleep(0.05)


def test_modules_hide_and_come_back_from_settings(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    accounts = page.locator('.nav-item[data-module="accounts"]')
    accounts.hover()
    accounts.locator("[data-nav-hide]").click()
    assert accounts.is_hidden()
    page.locator(".cal-toast", has_text="Accounts hidden").wait_for()
    until(lambda: ("finances", ["spending", "bills", "goals"], False) in saved(app_db))

    # Every module of Finances hidden: the section goes, its name too.
    for key in ("spending", "bills", "goals"):
        item = page.locator(f'.nav-item[data-module="{key}"]')
        item.hover()
        item.locator("[data-nav-hide]").click()
    assert page.locator("#nav-finances").is_hidden()
    assert "finances" not in sections(page)
    until(lambda: ("finances", [], True) in saved(app_db))
    page.reload()
    assert page.locator("#nav-finances").is_hidden()
    # Hidden, they have no number: Repositories, past them, is Alt+8.
    assert numbers(page) == {
        "today": "1",
        "calendar": "2",
        "habits": "3",
        "projects": "4",
        "nutrition": "5",
        "me": "6",
        "garmin": "7",
        "repositories": "8",
    }

    # Settings lists the four, each with its section; Show brings one back.
    page.locator("[data-settings-open]").click()
    dialog = page.locator("#settings-dialog")
    rows = dialog.locator(".settings-module")
    assert rows.all_inner_texts() == [
        f"{n}\nFinances\nShow" for n in ("Spending", "Accounts", "Bills", "Goals")
    ]
    rows.first.get_by_role("button", name="Show Spending in the sidebar").click()
    assert rows.count() == 3
    assert page.locator('.nav-item[data-module="spending"]').is_visible()
    assert page.locator("#nav-finances").is_visible()
    for _ in range(3):
        rows.first.locator("button").click()
    assert dialog.locator(".settings-empty").is_visible()
    page.keyboard.press("Escape")
    until(lambda: ("finances", ["spending", "accounts", "bills", "goals"], False) in saved(app_db))
    # Shown again, they are numbered again, at once: Bills and Goals are past Alt+9.
    assert numbers(page) == {
        "today": "1",
        "calendar": "2",
        "habits": "3",
        "projects": "4",
        "nutrition": "5",
        "me": "6",
        "garmin": "7",
        "spending": "8",
        "accounts": "9",
    }


def test_modules_sections_and_projects_drag_within_their_own_place(page, live, app_db) -> None:
    with app_db() as db:
        for name in ("Alpha", "Beta", "Gamma"):
            projects_svc.create_project(db, name=name)
        db.commit()
    page.goto(f"{live}/today")
    nav = page.locator(".nav")

    # Calendar above Today, within Planner.
    drag(page, nav.locator('a[href="/calendar"]'), nav.locator('a[href="/today"]'))
    assert modules(page, "planner") == ["calendar", "today", "habits"]
    assert page.url == f"{live}/today"  # the drop is not a click

    # Health above Planner, by its name.
    drag(page, page.locator("#nav-health"), page.locator("#nav-planner"))
    assert sections(page)[:2] == ["health", "planner"]

    # Projects, its section's one module, moves its section: below Finances.
    drag(
        page,
        nav.locator('a[href="/projects"]'),
        page.locator('.nav-group[data-section="finances"]'),
        below=True,
    )
    assert sections(page) == ["health", "planner", "finances", "projects", "code"]

    # Spending dragged down onto Code stays in Finances, at its end.
    drag(page, nav.locator('a[href="/spending"]'), nav.locator('a[href="/repositories"]'))
    assert modules(page, "finances") == ["accounts", "bills", "goals", "spending"]
    assert modules(page, "code") == ["repositories"]

    # Gamma first among the projects.
    rail = page.locator("#rail-projects")
    drag(page, rail.locator("a", has_text="Gamma"), rail.locator("a", has_text="Alpha"))
    page.wait_for_function(
        "() => [...document.querySelectorAll('#rail-projects .nav-label')]"
        ".map(l => l.textContent).join() === 'Gamma,Alpha,Beta'"
    )
    until(
        lambda: saved(app_db)[2] == ("finances", ["accounts", "bills", "goals", "spending"], False)
    )

    page.reload()
    assert sections(page) == ["health", "planner", "finances", "projects", "code"]
    assert modules(page, "planner") == ["calendar", "today", "habits"]
    assert modules(page, "finances") == ["accounts", "bills", "goals", "spending"]
    assert rail.locator(".nav-label").all_inner_texts() == ["Gamma", "Alpha", "Beta"]
    with app_db() as db:
        assert [p.name for p in projects_svc.list_projects(db)] == ["Gamma", "Alpha", "Beta"]
    # Numbers follow the place: Health's three first, then Calendar, Today and Habits.
    assert list(numbers(page)) == [
        "nutrition",
        "me",
        "garmin",
        "calendar",
        "today",
        "habits",
        "accounts",
        "bills",
        "goals",
    ]
    page.keyboard.press("Alt+4")
    page.wait_for_url(f"{live}/calendar")


def test_alt_and_a_number_go_to_the_module_showing_there(page, live) -> None:
    page.goto(f"{live}/today")
    figures = page.locator(".nav-key:visible")
    # Every page's number shows, just left of its name, the names all in line.
    assert figures.all_inner_texts() == [str(n) for n in range(1, 10)]
    rows = page.eval_on_selector_all(
        ".nav-item:not([hidden]) a",
        """as => as.map(a => [
            a.querySelector(".nav-key").getBoundingClientRect().right,
            a.querySelector(".nav-label").getBoundingClientRect().left,
        ])""",
    )
    assert len({label for _, label in rows}) == 1
    assert all(label - figure == 6 for figure, label in rows)

    # From a field too: what was being written saves as the page goes.
    page.goto(f"{live}/projects")
    page.get_by_label("New project").focus()
    page.keyboard.press("Alt+2")
    page.wait_for_url(f"{live}/calendar")

    # Hidden, Today has no number; Calendar is Alt+1 at once.
    today = page.locator('.nav-item[data-module="today"]')
    today.hover()
    today.locator("[data-nav-hide]").click()
    assert figures.all_inner_texts() == [str(n) for n in range(1, 10)]
    assert numbers(page)["calendar"] == "1"
    page.keyboard.press("Alt+3")
    page.wait_for_url(f"{live}/projects")


def test_escape_puts_a_drag_back_and_alt_arrows_move_the_focused_one(page, live, app_db) -> None:
    page.goto(f"{live}/today")
    nav = page.locator(".nav")
    today = nav.locator('a[href="/today"]').bounding_box()
    page.mouse.move(today["x"] + 30, today["y"] + today["height"] / 2)
    page.mouse.down()
    calendar = nav.locator('a[href="/calendar"]').bounding_box()
    page.mouse.move(today["x"] + 30, calendar["y"] + calendar["height"] - 2, steps=10)
    assert modules(page, "planner") == ["calendar", "today", "habits"]
    page.keyboard.press("Escape")
    page.mouse.up()
    assert modules(page, "planner") == ["today", "calendar", "habits"]

    nav.locator('a[href="/me"]').focus()
    page.keyboard.press("Alt+ArrowUp")
    assert modules(page, "health") == ["me", "nutrition", "garmin"]
    assert page.evaluate("document.activeElement.getAttribute('href')") == "/me"
    page.keyboard.press("Alt+Shift+ArrowUp")
    page.keyboard.press("Alt+Shift+ArrowUp")
    assert sections(page)[0] == "health"
    until(lambda: saved(app_db)[0] == ("health", ["me", "nutrition", "garmin"], False))
