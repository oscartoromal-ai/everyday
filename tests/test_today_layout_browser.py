"""Today's panes in a real browser: dragged by their title bars to another
place or column (a column not showing made by its zone), moved by the arrow
keys on their grip, hidden by their eye (with Undo) and shown again from
Panes, which also sets them back as they were; each kept through a reload.
The `live`, `page` and `app_db` fixtures are conftest.py's."""

import time

import pytest

from app.services import today_layout as today_layout_svc

pytest.importorskip("playwright.sync_api")


def columns(page) -> dict[str, list[str]]:
    """The panes showing, column by column, of the columns showing."""
    return page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('.today-col')]
        .filter((c) => c.checkVisibility())
        .map((c) => [c.dataset.col, [...c.querySelectorAll(':scope > .today-pane')]
          .filter((p) => !p.hidden).map((p) => p.dataset.pane)]))""")


def kept(
    app_db, expected: list[list[str]], hidden: set[str] = frozenset(), timeout: float = 5
) -> None:
    """The layout as the server has it, once the page has saved."""

    def now():
        with app_db() as db:
            layout = today_layout_svc.layout(db)
        return (
            [[p.pane.key for p in c.panes] for c in layout],
            {p.pane.key for c in layout for p in c.panes if p.hidden},
        )

    end = time.monotonic() + timeout
    while time.monotonic() < end and now() != (expected, set(hidden)):
        time.sleep(0.1)
    assert now() == (expected, set(hidden))


def stay_hidden(app_db) -> None:  # noqa: ANN001
    """The panes as they start, the stay and the work hidden: the plan and
    the habits alone in the left column."""
    with app_db() as db:
        today_layout_svc.save_layout(
            db, columns=today_layout_svc.default_columns(), hidden=["stay", "work"]
        )
        db.commit()


def drag(page, title: str, x: float, y: float) -> None:
    """A press on a pane's title, moved in steps to (x, y), let go, once the
    last move's slides are over (they move what is measured)."""
    page.wait_for_function("() => document.getAnimations().length === 0")
    start = page.locator(
        ".today-pane .pane-head :is(h2, .today-fold-label)", has_text=title
    ).bounding_box()
    page.mouse.move(start["x"] + 4, start["y"] + start["height"] / 2)
    page.mouse.down()
    page.mouse.move(x, y, steps=12)
    page.mouse.up()


def test_a_pane_dragged_to_another_column_lands_where_the_line_says(page, live, app_db) -> None:
    stay_hidden(app_db)
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    # The habits by their title, over the timeline's top half: before it.
    timeline = page.locator(".today-timeline").bounding_box()
    drag(page, "Habits", timeline["x"] + 100, timeline["y"] + 40)
    assert columns(page) == {"left": ["plan"], "center": ["notes"], "right": ["habits", "timeline"]}
    # The press on the habits' title bar was a drag, not a click folding them.
    assert page.locator("#pad-habits").evaluate("d => d.open")
    kept(app_db, [["plan", "stay", "work"], ["notes"], ["habits", "timeline"]], {"stay", "work"})

    # Over the timeline's bottom half: after it.
    drag(page, "Plan", timeline["x"] + 100, timeline["y"] + timeline["height"] - 20)
    assert columns(page) == {"center": ["notes"], "right": ["habits", "timeline", "plan"]}
    # With no left column showing, the notes take its room, and its fold goes.
    assert page.locator("[data-fold-col=left]").is_hidden()
    kept(app_db, [["stay", "work"], ["notes"], ["habits", "timeline", "plan"]], {"stay", "work"})

    page.reload()
    assert columns(page) == {"center": ["notes"], "right": ["habits", "timeline", "plan"]}

    # Esc, mid-drag, puts it back.
    start = page.locator(".today-timeline h2").bounding_box()
    page.mouse.move(start["x"] + 4, start["y"] + 8)
    page.mouse.down()
    page.mouse.move(start["x"] - 400, start["y"] + 200, steps=8)
    assert page.locator(".pane-drop-line:not([hidden])").count() == 1
    page.keyboard.press("Escape")
    page.mouse.up()
    assert page.locator(".pane-drop-line, .pane-lift, .pane-drop-zone").count() == 0
    assert columns(page) == {"center": ["notes"], "right": ["habits", "timeline", "plan"]}


def test_a_column_not_showing_is_made_by_dropping_on_its_zone(page, live, app_db) -> None:
    with app_db() as db:
        today_layout_svc.save_layout(
            db,
            columns=[["stay", "work"], ["notes"], ["plan", "habits", "timeline"]],
            hidden=["stay", "work"],
        )
        db.commit()
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    assert columns(page) == {"center": ["notes"], "right": ["plan", "habits", "timeline"]}
    start = page.locator(".today-pane .pane-head h2", has_text="Plan").bounding_box()
    page.mouse.move(start["x"] + 4, start["y"] + 8)
    page.mouse.down()
    page.mouse.move(start["x"] - 200, start["y"] + 100, steps=4)
    zone = page.locator(".pane-drop-zone")
    assert zone.count() == 1
    box = zone.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 200, steps=8)
    assert "is-over" in zone.get_attribute("class")
    page.mouse.up()
    assert columns(page) == {"left": ["plan"], "center": ["notes"], "right": ["habits", "timeline"]}
    kept(app_db, [["stay", "work", "plan"], ["notes"], ["habits", "timeline"]], {"stay", "work"})


def test_the_grip_moves_its_pane_by_the_arrow_keys_and_hides_it_by_delete(
    page, live, app_db
) -> None:
    stay_hidden(app_db)
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    grip = page.locator("#pad-habits [data-pane-grip]")
    grip.focus()
    page.keyboard.press("ArrowUp")
    assert columns(page)["left"] == ["habits", "plan"]
    # The arrow at an end does nothing, nor the day before or after.
    page.keyboard.press("ArrowLeft")
    assert page.url.endswith("/today")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    assert columns(page) == {"left": ["plan"], "center": ["notes"], "right": ["habits", "timeline"]}
    assert page.evaluate("document.activeElement.closest('.today-pane').dataset.pane") == "habits"
    kept(app_db, [["plan", "stay", "work"], ["notes"], ["habits", "timeline"]], {"stay", "work"})

    # Delete hides it, focus on Panes, the toast offering it back.
    page.keyboard.press("Delete")
    assert columns(page)["right"] == ["timeline"]
    assert page.evaluate("document.activeElement.className") == "panes-open"
    kept(
        app_db,
        [["plan", "stay", "work"], ["notes"], ["habits", "timeline"]],
        {"habits", "stay", "work"},
    )
    page.locator(".cal-toast .toast-action", has_text="Undo").click()
    assert columns(page)["right"] == ["habits", "timeline"]
    kept(app_db, [["plan", "stay", "work"], ["notes"], ["habits", "timeline"]], {"stay", "work"})


def test_panes_shows_a_hidden_pane_in_its_place_and_sets_them_back(page, live, app_db) -> None:
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    page.locator("#today-plan .pane-head h2").hover()
    page.locator("#today-plan [data-pane-hide]").click()
    assert columns(page)["left"] == ["habits", "stay", "work"]
    page.locator(".today-timeline .pane-head h2").hover()
    page.locator(".today-timeline [data-pane-hide]").click()
    assert columns(page) == {"left": ["habits", "stay", "work"], "center": ["notes"]}
    kept(
        app_db, [["plan", "habits", "stay", "work"], ["notes"], ["timeline"]], {"plan", "timeline"}
    )

    page.reload()
    assert columns(page) == {"left": ["habits", "stay", "work"], "center": ["notes"]}
    page.locator(".panes-open").click()
    menu = page.locator(".panes-menu")
    assert menu.locator("[role=menuitemcheckbox]").all_inner_texts() == [
        "Plan",
        "Habits",
        "Stay",
        "Work",
        "Notes",
        "Timeline",
    ]
    assert menu.locator("[aria-checked=true]").all_inner_texts() == [
        "Habits", "Stay", "Work", "Notes",
    ]
    # Shown again where it was, the menu staying open for the next.
    menu.locator("[role=menuitemcheckbox]", has_text="Plan").click()
    assert columns(page)["left"] == ["plan", "habits", "stay", "work"]
    assert menu.locator("[aria-checked=true]").all_inner_texts() == [
        "Plan", "Habits", "Stay", "Work", "Notes",
    ]
    page.keyboard.press("Escape")
    assert menu.count() == 0

    # Set back as they were, from anywhere they had gone; Undo has them back.
    page.locator("[data-fold-col=left]").click()
    page.locator(".panes-open").click()
    page.locator(".panes-menu .panes-reset").click()
    assert columns(page) == {
        "left": ["plan", "habits", "stay", "work"], "center": ["notes"], "right": ["timeline"],
    }
    kept(app_db, [["plan", "habits", "stay", "work"], ["notes"], ["timeline"]])
    page.locator(".cal-toast .toast-action", has_text="Undo").click()
    assert columns(page) == {"center": ["notes"]}
    kept(app_db, [["plan", "habits", "stay", "work"], ["notes"], ["timeline"]], {"timeline"})
