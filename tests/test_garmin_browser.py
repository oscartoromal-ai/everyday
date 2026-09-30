"""Health > Garmin in a real browser, over a stand-in for Garmin Connect:
signing in with a code, the first sync drawing the day, and stepping days
with the arrow keys. The `live`, `page` and `app_db` fixtures are
conftest.py's."""

from datetime import date, datetime, timedelta

import pytest
from garmin_fake import NAME, PASSWORD, FakeGarmin, activity_payload, day_payload

from app.services import garmin as garmin_svc

pytest.importorskip("playwright.sync_api")


@pytest.fixture
def fake(monkeypatch) -> FakeGarmin:
    from app.ui import garmin as ui_garmin

    fake = FakeGarmin(code="123456")
    monkeypatch.setattr(ui_garmin, "account", lambda: fake)
    today = date.today()
    fake.days = {today - timedelta(days=i): day_payload(today) for i in range(3)}
    fake.found = [activity_payload(1, datetime.combine(today, datetime.min.time()).replace(hour=7))]
    yield fake
    garmin_svc.syncing.wait(5)


def test_connect_with_a_code_then_read_the_days(page, live, app_db, fake) -> None:
    page.goto(f"{live}/garmin")
    page.get_by_label("Email").fill("oscar@example.com")
    page.get_by_label("Password").fill("wrong")
    page.get_by_role("button", name="Connect").click()
    page.get_by_role("alert").get_by_text("did not accept that email and password").wait_for()
    assert page.get_by_label("Email").input_value() == "oscar@example.com"

    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_label("Password").press("Enter")
    code = page.get_by_label("Code")
    code.wait_for()
    assert code.evaluate("el => el === document.activeElement")
    code.fill("123456")
    code.press("Enter")

    # Signed in: the page drawn again, the first sync filling it in.
    page.get_by_role("heading", name="Today").wait_for()
    page.get_by_text("Morning Run").wait_for()
    page.locator("#garmin-account").get_by_text("today").wait_for()
    assert page.get_by_text(NAME).is_visible()
    assert "8,412" in page.locator("#garmin-sheet").inner_text()
    with app_db() as db:
        assert garmin_svc.link(db).full_name == NAME

    # Left and Right step through the days; the fortnight marks the one shown.
    page.keyboard.press("ArrowLeft")
    page.wait_for_url(f"**/garmin/{(date.today() - timedelta(days=1)).isoformat()}")
    assert page.locator(".garmin-trend-row.is-current").inner_text().startswith(
        (date.today() - timedelta(days=1)).strftime("%a")
    )
    page.keyboard.press("ArrowRight")
    page.wait_for_url(f"{live}/garmin")
