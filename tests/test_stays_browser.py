"""Where Oscar stays, in a real browser: written in its pane beside a day's
notes (stays.js), never in the notes; taken again from the last day, its
values offered as written before, carried on to the days after (Undo puts
them back), an item added and taken away; and read item by item under the
date. The `live`, `page` and `app_db` fixtures are conftest.py's."""

import time
from datetime import date, timedelta

import pytest

from app.services import stays as stays_svc

pytest.importorskip("playwright.sync_api")

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


def until(check, timeout: float = 5) -> None:  # noqa: ANN001
    end = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < end
        time.sleep(0.1)


def stay(app_db, day: date) -> list[tuple[str, str, bool]]:  # noqa: ANN001
    with app_db() as db:
        return [(i.name, i.value, i.done) for i in stays_svc.items_on(db, day)]


def test_a_stay_is_written_in_its_pane(page, live, app_db) -> None:
    with app_db() as db:
        stays_svc.set_item(db, TODAY - timedelta(days=2), "place", value="Delft")
        stays_svc.set_item(db, YESTERDAY, "place", value="Leiden")
        stays_svc.set_item(db, YESTERDAY, "accommodation", done=True)
        db.commit()
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{live}/today")
    pane = page.locator("#pad-stay")
    rows = pane.locator(".stay-row")
    facts = page.locator("#day-stay .day-stay-item")
    # None yet: the items yesterday's had, empty, and yesterday's to take again.
    assert rows.locator(".stay-name").all_inner_texts() == ["Place", "Accommodation"]
    assert rows.locator(".stay-value").evaluate_all("els => els.map(e => e.value)") == ["", ""]
    assert not facts.count()
    same = pane.locator(".stay-same")
    assert same.inner_text().split() == ["Same", "as", "yesterday", "Leiden"]
    assert pane.locator(".stay-carry").is_hidden()

    # Taken again, item for item; under the date, item by item.
    same.click()
    until(lambda: stay(app_db, TODAY) == stay(app_db, YESTERDAY))
    # Saved before the answer reaches the page: the pane is drawn from it after.
    same.wait_for(state="hidden")
    until(lambda: pane.locator(".stay-sum").inner_text() == "sorted")
    assert [t.split() for t in facts.all_inner_texts()] == [["Place", "Leiden"], ["Accommodation"]]
    # Its box: not sorted after all, in amber.
    rows.nth(1).locator(".stay-box").click()
    until(lambda: stay(app_db, TODAY)[1] == ("accommodation", "", False))
    until(lambda: pane.locator(".stay-sum").inner_text() == "not sorted")
    assert facts.nth(1).get_attribute("class") == "day-stay-item open"
    assert [t.split() for t in facts.all_inner_texts()][1] == ["Accommodation", "not", "sorted"]

    # A place written as it was before: offered under it, the last first.
    place = rows.nth(0).locator(".stay-value")
    place.click()
    place.press("Control+a")
    place.press_sequentially("de")
    offer = page.locator(".stay-offer [role=option]")
    assert offer.all_inner_texts() == ["Leiden", "Delft"]
    place.press_sequentially("l")
    assert offer.all_inner_texts() == ["Delft"]
    place.press("ArrowDown")
    place.press("Enter")
    until(lambda: stay(app_db, TODAY)[0] == ("place", "Delft", False))
    assert offer.count() == 0
    # Enter writes it and goes on to the next item's value; Esc puts one back.
    place.press("Enter")
    accommodation = rows.nth(1).locator(".stay-value")
    assert accommodation.evaluate("e => e === document.activeElement")
    accommodation.press_sequentially("Canal house")
    accommodation.press("Enter")
    until(lambda: stay(app_db, TODAY)[1] == ("accommodation", "Canal house", False))
    accommodation.click()
    accommodation.press_sequentially(" boat")
    accommodation.press("Escape")
    assert accommodation.input_value() == "Canal house"
    # The notes have nothing of it.
    assert page.evaluate("Notepad.text()") == ""

    # Carried on to the next day; Undo puts it back as it was.
    pane.locator(".stay-carry").click()
    page.locator(".stay-carry-menu [role=menuitem]", has_text="The next day").click()
    until(lambda: stay(app_db, TOMORROW) == stay(app_db, TODAY))
    through = pane.locator(".stay-through")
    until(lambda: through.inner_text().startswith("Same to "))
    page.locator(".cal-toast.show .toast-action").click()
    until(lambda: stay(app_db, TOMORROW) == [])
    through.wait_for(state="hidden")

    # An item begun at the pane's foot, and taken away (Undo, back).
    pane.locator(".stay-new-open").click()
    pane.locator(".stay-new input").fill("Parking")
    pane.locator(".stay-new input").press("Enter")
    parking = rows.nth(2).locator(".stay-value")
    parking.wait_for()
    assert parking.evaluate("e => e === document.activeElement")
    parking.press_sequentially("P2")
    parking.press("Tab")
    until(lambda: stay(app_db, TODAY)[2] == ("Parking", "P2", False))
    rows.nth(2).hover()
    rows.nth(2).locator(".stay-remove").click()
    until(lambda: len(stay(app_db, TODAY)) == 2)
    page.locator(".cal-toast.show .toast-action").click()
    until(lambda: len(stay(app_db, TODAY)) == 3)

    # Its column folded away, a click under the date brings it back to the value.
    page.locator('[data-fold-col="left"]').click()
    assert pane.is_hidden()
    facts.nth(0).click()
    assert pane.is_visible()
    assert place.evaluate("e => e === document.activeElement")
