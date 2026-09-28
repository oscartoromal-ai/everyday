"""Health > Me in a real browser: saved as it changes, a weigh-in drawing
what follows again, and a refused value said in a toast. The `live` and
`page` fixtures are conftest.py's."""

import time

import pytest

from app.services import health as health_svc

pytest.importorskip("playwright.sync_api")


def test_me_saves_as_it_changes(page, live, app_db) -> None:
    page.goto(f"{live}/me")
    page.locator("input[name=height_cm]").fill("180")
    page.locator("input[name=height_cm]").press("Tab")
    page.locator("input[name=birth_date]").fill("1990-05-14")
    page.locator("select[name=sex]").select_option("male")
    page.locator("select[name=activity]").select_option("light")
    page.locator("input[name=allergies]").fill("peanuts")
    page.locator("input[name=allergies]").press("Tab")
    end = time.monotonic() + 5
    while True:
        with app_db() as db:
            me = health_svc.context(db)
        saved = (me["height_cm"], me["sex"], me["activity"], me["allergies"])
        if saved == (180, "male", "light", "peanuts"):
            break
        assert time.monotonic() < end, me
        time.sleep(0.1)

    # A weigh-in joins the log and draws what follows again.
    figures = page.locator("#me-context")
    assert "Not yet" in figures.inner_text()
    page.locator("input[name=weight_kg]").fill("81.4")
    page.locator("input[name=weight_kg]").press("Enter")
    page.locator(".weight-log li", has_text="81.4 kg").wait_for()
    page.locator("#me-context", has_text="kcal a day keeps your weight").wait_for()
    assert page.locator("input[name=weight_kg]").input_value() == ""

    # A slip of the keyboard is refused, and the toast says why.
    page.locator("input[name=height_cm]").fill("1800")
    page.locator("input[name=height_cm]").press("Tab")
    page.locator(".cal-toast.show", has_text="Height (cm) should be between 50 and 272").wait_for()
    with app_db() as db:
        assert health_svc.context(db)["height_cm"] == 180
