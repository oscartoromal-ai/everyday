"""Board, a view of a project's Tasks tab, in a real browser: ticking,
editing in place, quick do-dates, filing by drag, the finished work, the
keyboard across the columns, and writing into a column. The board is
tasks-board.js over tasks.js, tasks-views.js and task-sheet.js, which
only a browser runs; the `live`, `page` and `app_db` fixtures are
conftest.py's."""

from datetime import date, timedelta

import pytest

from app.models import TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()
# A board being drawn again: wait for it before reading it.
BUSY = "!!document.querySelector(\"[hx-trigger*='tasks:changed'].htmx-request\")"
CURSOR = "document.activeElement?.dataset?.taskTitle ?? null"


@pytest.fixture
def home(app_db) -> dict:
    """Home's board: Garden with Mow (today) and Weed, then House with Paint,
    a task's sub-tasks in it; Rake done in Garden."""
    with app_db() as db:
        home = projects_svc.create_project(db, name="Home")
        garden = projects_svc.create_workstream(db, project_id=home.id, name="Garden")
        house = projects_svc.create_workstream(db, project_id=home.id, name="House")

        def task(title: str, ws, **fields):  # noqa: ANN001, ANN202
            return tasks_svc.create_task(
                db, title=title, project_id=home.id, workstream_id=ws.id, **fields
            ).id

        made = {
            "mow": task("Mow", garden, planned_for=TODAY),
            "weed": task("Weed", garden),
            "paint": task("Paint", house, notes="- [ ] sand\n- [ ] prime"),
            "rake": task("Rake", garden),
        }
        tasks_svc.set_status(db, made["rake"], TaskStatus.done)
        db.commit()
        return {
            **made,
            "project": home.id,
            "garden": garden.id,
            "house": house.id,
            "url": f"/projects/{home.id}/tasks?view=board",
        }


def column(page, ws_id: int):
    return page.locator(f"#workstream-group-{ws_id}")


def settled(page) -> None:
    page.wait_for_function(f"!{BUSY}")


def task(app_db, task_id: int):
    with app_db() as db:
        return tasks_svc.get_task(db, task_id)


def quick_shown(card) -> bool:
    """Its quick do-dates in sight (out of it, they are a clipped pixel)."""
    return card.locator(".tv-quick").bounding_box()["width"] > 1


def test_a_tick_redraws_the_board_and_show_completed_shows_done(page, live, app_db, home) -> None:
    page.goto(f"{live}{home['url']}")
    garden = column(page, home["garden"])
    assert garden.locator(".board-card").evaluate_all("cs => cs.map(c => c.dataset.taskTitle)") == [
        "Mow",
        "Weed",
    ]
    done = page.locator("#board-done")
    assert done.is_hidden()

    garden.locator(".board-card[data-task-title='Weed'] .task-check").click()
    garden.locator(".board-card[data-task-title='Weed']").wait_for(state="detached")
    settled(page)
    assert task(app_db, home["weed"]).status == TaskStatus.done
    assert page.locator(".task-row:not(.board-card)").count() == 0  # never the list's rows

    # Show completed: Done, with this week's finished work, kept across visits.
    page.locator("[data-show-done]").click()
    done.wait_for()
    assert done.locator(".board-card").evaluate_all("cs => cs.map(c => c.dataset.taskTitle)") == [
        "Weed",
        "Rake",
    ]
    page.reload()
    assert page.locator("[data-show-done]").is_checked() and done.is_visible()

    # Unticked there, it goes back to its column.
    done.locator(".board-card[data-task-title='Weed'] .task-check").click()
    garden.locator(".board-card[data-task-title='Weed']").wait_for()
    settled(page)
    assert task(app_db, home["weed"]).status == TaskStatus.todo
    page.locator("[data-show-done]").click()
    done.wait_for(state="hidden")


def test_enter_edits_a_card_in_place_and_it_comes_back_a_card(page, live, app_db, home) -> None:
    page.goto(f"{live}{home['url']}")
    card = page.locator(f"#task-{home['weed']}")
    card.focus()
    page.keyboard.press("Enter")
    sheet = page.locator(f"#workstream-tasks-{home['garden']} > #task-{home['weed']}.sheet-item")
    sheet.wait_for()
    assert page.evaluate("document.activeElement.className") == "sheet-title"

    # Esc, nothing changed: the card again, as the board draws it, the cursor on it.
    page.keyboard.press("Escape")
    page.locator(f"#task-{home['weed']}.board-card").wait_for()
    assert page.locator(f"#task-{home['weed']} .task-body").count() == 0
    page.wait_for_function(f"{CURSOR} === 'Weed'")

    # Written and left: saved, and a card once more.
    page.keyboard.press("Enter")
    sheet.wait_for()
    page.keyboard.type(" the beds")
    page.keyboard.press("Escape")
    page.locator(f"#task-{home['weed']}.board-card[data-task-title='Weed the beds']").wait_for()
    settled(page)
    assert task(app_db, home["weed"]).title == "Weed the beds"
    assert page.locator(f"#task-{home['weed']}.board-card").count() == 1


def test_a_cards_quick_do_dates_show_on_hover(page, live, app_db, home) -> None:
    page.goto(f"{live}{home['url']}")
    card = page.locator(f"#task-{home['weed']}")
    today = card.locator("[data-plan='today']")
    assert not quick_shown(card)  # until the card is hovered
    box = card.bounding_box()
    card.hover()
    assert quick_shown(card)
    assert card.bounding_box()["height"] == box["height"]  # floating, the card as it was
    today.click()
    page.wait_for_function(
        f"document.querySelector('#task-{home['weed']} .tv-date')?.textContent === 'today'"
    )
    settled(page)
    assert task(app_db, home["weed"]).planned_for == TODAY

    # Mow is today's already: no Today, nor room for it; Tomorrow takes it on.
    mow = page.locator(f"#task-{home['mow']}")
    mow.hover()
    assert mow.locator("[data-plan='today']").count() == 0
    assert mow.locator(".plan-btn.slot").is_hidden()
    # At its top right, clear of its line and its days.
    bar = mow.locator(".tv-quick").bounding_box()
    assert bar["y"] + bar["height"] <= mow.locator(".board-dates").bounding_box()["y"]
    mow.locator("[data-plan='tomorrow']").click()
    page.wait_for_function(
        f"document.querySelector('#task-{home['mow']} .tv-date')?.textContent === 'tomorrow'"
    )
    settled(page)
    assert task(app_db, home["mow"]).planned_for == TODAY + timedelta(days=1)


def drag(page, card, onto=None, *, at=(0.5, 0.5), point=None) -> None:
    """A card picked up, carried and let go over `onto` (a locator), at the
    fraction `at` of its box (it can show only once a card is in hand), or
    at `point` on the page."""
    start = card.bounding_box()
    page.mouse.move(start["x"] + 60, start["y"] + 12)
    page.mouse.down()
    page.mouse.move(start["x"] + 70, start["y"] + 20, steps=4)
    if point:
        x, y = point
    else:
        box = onto.bounding_box()
        x, y = box["x"] + box["width"] * at[0], box["y"] + box["height"] * at[1]
    page.mouse.move(x, y, steps=8)
    page.mouse.move(x + 2, y + 2, steps=2)
    page.mouse.up()


def test_a_card_dragged_onto_a_column_is_filed_there(page, live, app_db, home) -> None:
    page.goto(f"{live}{home['url']}")
    house = column(page, home["house"])
    weed = page.locator(f"#task-{home['weed']}")

    # Onto House, low down its column, under its cards: filed into House.
    drag(page, weed, house, at=(0.5, 0.9))
    house.locator(f"#task-{home['weed']}").wait_for()
    settled(page)
    assert task(app_db, home["weed"]).workstream_id == home["house"]
    assert not page.locator(".drop-over").count()

    # Out of any workstream: No workstream shows while a card is in hand.
    loose = page.locator("#board-loose")
    assert loose.is_hidden()
    drag(page, page.locator(f"#task-{home['weed']}"), loose)
    loose.locator(f"#task-{home['weed']}").wait_for()
    settled(page)
    assert task(app_db, home["weed"]).workstream_id is None
    assert task(app_db, home["weed"]).project_id == home["project"]

    # Between the columns, onto the toolbar or the new workstream's: nowhere,
    # and nothing is asked of the server.
    sent = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "PATCH" else None)
    paint = page.locator(f"#task-{home['paint']}")
    drag(page, paint, page.locator(".board-new"))
    drag(page, paint, page.locator(".tasks-toolbar"))
    garden = column(page, home["garden"]).bounding_box()
    drag(page, paint, point=(garden["x"] + garden["width"] + 6, garden["y"] + 100))
    # A redraw asked for after them: a drop's request would have gone before it.
    with page.expect_response(lambda r: "view=board" in r.url):
        page.evaluate("htmx.trigger(document.body, 'tasks:changed')")
    settled(page)
    assert sent == []
    assert task(app_db, home["paint"]).workstream_id == home["house"]
    assert house.locator(f"#task-{home['paint']}").count() == 1


def test_the_keyboard_moves_across_the_columns(page, live, home) -> None:
    page.goto(f"{live}{home['url']}")
    page.locator(f"#task-{home['mow']}").focus()
    page.keyboard.press("ArrowDown")
    page.wait_for_function(f"{CURSOR} === 'Weed'")
    page.keyboard.press("ArrowRight")  # to House's card level with it
    page.wait_for_function(f"{CURSOR} === 'Paint'")
    page.keyboard.press("ArrowRight")  # nothing further right: it stays
    assert page.evaluate(CURSOR) == "Paint"

    # Space shows its description under the card, and hides it.
    subtasks = page.locator(f"#board-notes-{home['paint']}")
    assert subtasks.is_hidden()
    page.keyboard.press("Space")
    assert subtasks.is_visible() and "sand" in subtasks.inner_text()
    page.keyboard.press("Space")
    assert subtasks.is_hidden()

    page.keyboard.press("ArrowLeft")
    page.wait_for_function(f"{CURSOR} === 'Mow'")  # level with Paint, Garden's first
    page.keyboard.press("Shift+ArrowDown")  # the next list: House
    page.wait_for_function(f"{CURSOR} === 'Paint'")


def test_a_click_leaves_no_keyboard_look_behind(page, live, home) -> None:
    page.goto(f"{live}{home['url']}")
    paint = page.locator(f"#task-{home['paint']}")
    paint.locator("[data-subtasks]").click()  # its sub-tasks shown, the count focused
    page.mouse.move(5, 5)
    assert not quick_shown(paint)
    # Its look settles back to a card's at rest (past the hover's fade).
    page.wait_for_function(
        """([a, b]) => {
          const look = (id) => {
            const c = getComputedStyle(document.getElementById(id));
            return c.backgroundColor + c.borderColor;
          };
          return look(a) === look(b);
        }""",
        arg=[f"task-{home['paint']}", f"task-{home['weed']}"],
    )
    # The keyboard's cursor on a card: it shows them.
    page.keyboard.press("Home")
    page.wait_for_function(f"{CURSOR} === 'Mow'")
    page.wait_for_function(
        f"document.querySelector('#task-{home['mow']} .tv-quick').getBoundingClientRect().width > 1"
    )
    assert not quick_shown(paint)


def test_a_columns_composer_files_into_its_workstream(page, live, app_db, home) -> None:
    page.goto(f"{live}{home['url']}")
    house = column(page, home["house"])
    house.locator(".compose-slot .sheet-line").click()
    page.keyboard.type("Fix the gutter")
    page.keyboard.press("Control+Enter")
    house.locator(".board-card[data-task-title='Fix the gutter']").wait_for()
    settled(page)
    with app_db() as db:
        added = next(t for t in tasks_svc.list_tasks(db) if t.title == "Fix the gutter")
        assert added.workstream_id == home["house"]
    # The composer is empty again, ready for the next.
    assert house.locator(".compose-slot .sheet-title").text_content() == ""


def test_a_redraw_keeps_the_board_where_it_was(page, live, app_db, home) -> None:
    page.set_viewport_size({"width": 700, "height": 700})
    page.goto(f"{live}{home['url']}")
    board = page.locator(".board")
    board.evaluate("b => b.scrollLeft = b.scrollWidth")
    left = board.evaluate("b => b.scrollLeft")
    assert left > 0
    # A workstream being named, mid-word, as the board is drawn again.
    name = page.locator(".board-new input")
    name.click()
    page.keyboard.type("Shed")
    old = page.locator("#project-tasks").element_handle()
    page.evaluate("htmx.trigger(document.body, 'tasks:changed')")
    page.wait_for_function("(old) => !old.isConnected", arg=old)
    settled(page)
    assert board.evaluate("b => b.scrollLeft") == left
    assert name.input_value() == "Shed"
    assert page.evaluate("document.activeElement.name") == "name"
    page.keyboard.press("Enter")
    page.locator("#project-tasks h2", has_text="Shed").wait_for()
    assert page.locator(".board-new input").input_value() == ""
