"""Nutrition in a real browser, with a stand-in for Claude: a message sent
with Enter, the answer streamed in as it is written, then the chat and the
day's log drawn again from what was saved."""

import asyncio
import socket
import threading
import time
from collections.abc import Generator
from datetime import date

import pytest

from app.config import get_settings
from app.services.nutrition_agent import AgentEvent, AgentRequest

pytest.importorskip("playwright.sync_api")

LOG = """\
---
date: {day}
meals:
  - name: Breakfast
    status: eaten
    items:
      - food: Rolled oats
        amount: 40 g
        assumed: true
        kcal: 150
        protein_g: 5
        fat_g: 3
        sat_fat_g: 0.5
        carbs_g: 24
        fibre_g: 4
---

## Next

Salmon tonight, for the omega-3.
"""


async def stand_in(request: AgentRequest):  # noqa: ANN201
    yield AgentEvent("status", "Reading the plan")
    await asyncio.sleep(0.3)
    path = request.folder / "log" / f"{request.day.isoformat()}.md"
    path.write_text(LOG.format(day=request.day.isoformat()), encoding="utf-8")
    yield AgentEvent("status", "Writing the day's log")
    for word in ["Logged", "**40", "g**", "of", "oats."]:
        await asyncio.sleep(0.05)
        yield AgentEvent("text", word + " ")


@pytest.fixture
def served(app_db, tmp_path, monkeypatch) -> Generator[str, None, None]:
    """The app over HTTP, as conftest's `live`, with the stand-in answering."""
    import uvicorn

    from app.main import create_app
    from app.ui.nutrition import get_agent

    folder = tmp_path / "nutrition"
    (folder / "log").mkdir(parents=True)
    (folder / "plan.md").write_text("---\ntargets:\n  kcal: {aim: 2500}\n---\n", encoding="utf-8")
    monkeypatch.setattr(get_settings().nutrition, "dir", str(folder))
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
def browser_page(served) -> Generator:
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no Chromium for Playwright: {exc}")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        yield page
        browser.close()
        assert errors == []


def test_a_message_streams_in_and_the_day_is_drawn_again(browser_page, served) -> None:
    page = browser_page
    page.goto(f"{served}/nutrition")
    assert "Nothing logged yet" in page.locator("#nutrition-log").inner_text()

    field = page.locator("#chat-composer textarea")
    field.fill("Oats for breakfast")
    field.press("Shift+Enter")  # a new line, not a send
    assert field.input_value() == "Oats for breakfast\n"
    field.press("Enter")

    # Drawn at once: the message, and Claude's row saying what it is doing.
    page.locator("#chat-log .chat-message.from-oscar", has_text="Oats for breakfast").wait_for()
    page.locator("#chat-log .chat-status", has_text="…").wait_for()
    assert field.input_value() == ""

    # Done: the answer as Markdown, and the log as the stand-in left it.
    page.locator("#chat-log .chat-message.from-agent strong", has_text="40 g").wait_for()
    log = page.locator("#nutrition-log")
    log.locator(".nutrition-item", has_text="Rolled oats").wait_for()
    assert "of 2,500 kcal" in log.inner_text()
    assert "Salmon tonight" in log.inner_text()
    assert page.locator("#chat-composer .chat-send").is_enabled()


def test_left_and_right_change_the_day(browser_page, served) -> None:
    page = browser_page
    page.goto(f"{served}/nutrition")
    page.locator("h1").click()
    page.keyboard.press("ArrowLeft")
    yesterday = date.fromordinal(date.today().toordinal() - 1)
    page.wait_for_url(f"**/nutrition/{yesterday.isoformat()}")
    assert page.locator(".day-today").is_visible()
