"""Finances in a real browser: an export imported from Accounts, a
transaction sorted on its line with the month's figures following, the
Spending chat's answer (a stand-in for Claude, using Claude's tools)
redrawing the month, and the phone's tab bar opening on the page's tab."""

import asyncio
import re
import socket
import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from app.services.claude_sdk import AgentEvent
from app.services.money_agent import AgentRequest, run_tool

pytest.importorskip("playwright.sync_api")

DATA = Path(__file__).parent / "data"


async def stand_in(request: AgentRequest):  # noqa: ANN201
    yield AgentEvent("status", "Adding a rule")
    await asyncio.sleep(0.2)
    run_tool(request.factory, "add_rule", {"words": "Coffee Club", "category": "Eating out"})
    for word in ["Sorted", "**2", "coffees**."]:
        await asyncio.sleep(0.05)
        yield AgentEvent("text", word + " ")


@pytest.fixture
def served(app_db) -> Generator[str, None, None]:
    """The app over HTTP, as conftest's `live`, with the stand-in answering."""
    import uvicorn

    from app.main import create_app
    from app.ui.money import get_agent

    app = create_app()
    app.dependency_overrides[get_agent] = lambda: stand_in
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


@pytest.fixture
def browser(served) -> Generator:
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            chromium = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no Chromium for Playwright: {exc}")
        errors: list[str] = []

        def open_page(width: int = 1400, height: int = 900):  # noqa: ANN202
            page = chromium.new_page(viewport={"width": width, "height": height})
            page.on("pageerror", lambda e: errors.append(str(e)))
            return page

        yield open_page
        chromium.close()
        assert errors == []


def test_import_sort_and_ask_claude(browser, served) -> None:
    page = browser()
    page.goto(f"{served}/accounts")
    page.set_input_files("#money-export", str(DATA / "revolut-2026-09.csv"))
    page.click(".money-import button")
    status = page.locator("#money-accounts [role=status]")
    status.wait_for()
    assert "6 added to Revolut" in status.inner_text()

    page.click("text=See September")
    # September's page, or /spending itself while September is this month.
    page.wait_for_url(re.compile(r"/spending(/2026-09)?$"))
    figures = page.locator("#money-totals")
    assert "5 transactions" in figures.inner_text()

    # Sorted on its line: the row keeps its choice, the month follows.
    row = page.locator(".money-transaction", has_text="Woolworths Metro")
    row.locator("select").select_option(label="Groceries")
    page.wait_for_function(
        "document.querySelector('#money-totals').innerText.includes('4 transactions')"
    )
    assert row.locator("select option:checked").inner_text() == "Groceries"
    assert "is-unsorted" not in (row.get_attribute("class") or "")

    # A budget written on its line, saved as it changes.
    budget = page.locator(".money-budget", has_text="Groceries").locator("input")
    budget.fill("40")
    budget.press("Tab")
    page.locator(".money-budget", has_text="Groceries").locator(".chip", has_text="Over").wait_for()

    # Claude's answer streams in; then the month is drawn again as it left it.
    field = page.locator("#chat-composer textarea")
    field.fill("Sort my coffees")
    field.press("Enter")
    page.locator("#chat-log .chat-message.from-oscar", has_text="Sort my coffees").wait_for()
    page.locator("#chat-log .chat-message.from-agent strong", has_text="2 coffees").wait_for()
    page.wait_for_function(
        "document.querySelector('#money-totals').innerText.includes('2 transactions')"
    )
    coffee = page.locator(".money-transaction", has_text="Coffee Club").first
    assert coffee.locator("select option:checked").inner_text() == "Eating out"


def test_the_next_export_from_a_bank_goes_into_its_account(browser, served) -> None:
    page = browser()
    page.goto(f"{served}/accounts")
    status = page.locator("#money-accounts [role=status]")
    for said in ("6 added to Revolut;", "0 added to Revolut; 6 already here;"):
        # The form as it opens: into the account its bank's exports go into.
        assert page.locator(".money-import select option:checked").inner_text() == (
            "Its bank's account"
        )
        page.set_input_files("#money-export", str(DATA / "revolut-2026-09.csv"))
        page.click(".money-import button")
        page.wait_for_function(
            "said => document.querySelector('#money-accounts [role=status]')"
            "?.innerText.includes(said)",
            arg=said,
        )
    assert status.inner_text().startswith("Revolut: ")
    assert page.locator(".money-account input[name=name]").evaluate_all(
        "fields => fields.map(f => f.value)"
    ) == ["Revolut"]
    # Its money counted once: the export's closing balance.
    net_worth = page.locator(".money-figure", has_text="Net worth").locator(".money-main")
    assert net_worth.inner_text() == "$520"


def test_the_import_fits_on_a_phone(browser, served) -> None:
    page = browser(390, 844)
    page.goto(f"{served}/accounts")
    form = page.locator(".money-import")
    field = form.locator(":scope > .sheet-field").bounding_box()
    into, account = form.locator(".money-of").bounding_box(), form.locator("select").bounding_box()
    button = form.locator("button").bounding_box()
    # "into" and its account on one line, the account whole and in the field.
    assert into["y"] == account["y"]
    assert account["x"] + account["width"] <= field["x"] + field["width"]
    assert form.locator("select").evaluate("s => s.scrollWidth <= s.clientWidth")
    # Import under them, in line with the field.
    assert button["y"] >= account["y"] + account["height"]
    assert button["x"] == field["x"]


def test_left_and_right_change_the_month(browser, served) -> None:
    page = browser()
    page.goto(f"{served}/spending/2026-09")
    page.locator("h1").click()
    page.keyboard.press("ArrowLeft")
    page.wait_for_url("**/spending/2026-08")
    assert page.locator(".day-today", has_text="This month").is_visible()


def test_the_phone_tab_bar_opens_on_the_page(browser, served) -> None:
    page = browser(390, 844)
    page.goto(f"{served}/goals")
    nav = page.locator(".nav")
    assert nav.evaluate("n => n.scrollWidth > n.clientWidth")
    current = page.locator('.nav a[aria-current="page"]')
    box, bar = current.bounding_box(), nav.bounding_box()
    assert bar["x"] <= box["x"] and box["x"] + box["width"] <= bar["x"] + bar["width"] + 1
    assert box["width"] >= 44
    assert "start" in (nav.get_attribute("data-more") or "")
