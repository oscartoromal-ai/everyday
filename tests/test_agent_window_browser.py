"""The agent window in a real browser, with a stand-in agent: expanded and
collapsed (the sidebar's Agent, its own Collapse, A), remembered from page
to page, a message streamed in, and an answer that goes on while Oscar
moves to another page."""

import asyncio
import socket
import threading
import time
from collections.abc import Generator

import pytest

from app.models import AgentKind
from app.services.agents import AgentRequest
from app.services.claude_sdk import AgentEvent

pytest.importorskip("playwright.sync_api")


async def stand_in(request: AgentRequest):  # noqa: ANN201
    yield AgentEvent("status", "Thinking it over")
    await asyncio.sleep(0.3)
    for word in ["Plan", "the", "**week**", "first."]:
        await asyncio.sleep(0.1)
        yield AgentEvent("text", word + " ")


@pytest.fixture
def served(app_db) -> Generator[str, None, None]:
    """The app over HTTP, as conftest's `live`, with the stand-in answering."""
    import uvicorn

    from app.main import create_app
    from app.ui.agent_window import get_agents

    app = create_app()
    app.dependency_overrides[get_agents] = lambda: {kind: stand_in for kind in AgentKind}
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


def is_open(page) -> bool:  # noqa: ANN001
    return page.evaluate("document.documentElement.dataset.agent === 'open'")


def test_it_expands_and_collapses_and_is_remembered(browser_page, served) -> None:
    page = browser_page
    page.goto(f"{served}/today")
    panel = page.locator("#agent-panel")
    assert not is_open(page) and not panel.is_visible()
    # Collapsed, the sidebar's panes are out of the tab order.
    assert page.evaluate("document.getElementById('agent-panel').closest('[inert]') !== null")

    # The sidebar's Agent: docked open, its message in focus.
    page.locator(".rail-button[data-agent-toggle]").click()
    assert is_open(page)
    panel.locator("textarea").wait_for(state="visible")
    assert page.evaluate("document.activeElement.name") == "message"
    page.wait_for_function("document.getElementById('agent-panel').offsetWidth >= 399")
    assert page.locator(".rail-button[data-agent-toggle]").get_attribute("aria-expanded") == "true"

    # Remembered from page to page, open before paint.
    page.goto(f"{served}/calendar")
    assert is_open(page) and panel.is_visible()

    # Its own Collapse: the focus goes back to the sidebar's Agent.
    panel.locator("[data-agent-toggle]").click()
    assert not is_open(page)
    assert page.evaluate("document.activeElement.classList.contains('agent-open')")
    page.goto(f"{served}/today")
    assert not is_open(page)

    # A, outside a field, opens it; Esc steps out of the message; A closes it.
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("a")
    assert is_open(page)
    page.keyboard.press("Escape")
    page.keyboard.press("a")
    assert not is_open(page)


def test_a_message_streams_in_and_goes_on_from_page_to_page(browser_page, served) -> None:
    page = browser_page
    page.goto(f"{served}/today")
    page.keyboard.press("a")
    field = page.locator("#agent-panel textarea")
    field.fill("How should I plan?")
    field.press("Enter")

    log = page.locator("#agent-log")
    log.locator(".chat-message.from-oscar", has_text="How should I plan?").wait_for()
    log.locator(".chat-status", has_text="Thinking it over…").wait_for()
    # An answer on its way: the sidebar's Agent shows it, even collapsed.
    assert page.locator(".agent-open__dot").is_visible()

    # Away to another page mid-answer: it goes on, and lands there.
    page.goto(f"{served}/calendar")
    log.locator(".chat-message.from-agent strong", has_text="week").wait_for(timeout=10000)
    assert not page.locator(".agent-open__dot").is_visible()

    # New chat: an empty chat, the message in focus.
    page.locator("#agent-panel button[title='New chat']").click()
    page.locator("#agent-log .chat-empty").wait_for()
    assert page.evaluate("document.activeElement.name") == "message"


def test_another_agent_is_chosen_from_the_head(browser_page, served) -> None:
    page = browser_page
    page.goto(f"{served}/today")
    page.keyboard.press("a")
    page.locator(".agent-select").select_option("codex")
    page.locator("#agent-log .chat-empty", has_text="Ask Codex anything").wait_for()
    assert page.locator("#agent-panel textarea").get_attribute("placeholder") == "Ask Codex…"


@pytest.mark.parametrize(("width", "plan_beside", "timeline_beside"), [
    (1280, False, False), (1500, True, False), (1600, True, False), (1840, True, True),
])
def test_docked_beside_today_it_leaves_the_notes_room(
    browser_page, served, width, plan_beside, timeline_beside,
) -> None:
    """Docked, the agent's window takes the page's width from Today: the
    timeline goes under the notes until the three fit side by side, then
    the plan too, the notes never under the 405px they have beside it
    without the agent."""
    page = browser_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{served}/today")
    page.locator(".rail-button[data-agent-toggle]").click()
    # Once it has slid in and the page stands still: the notes, the plan and
    # the timeline, read together.
    pad, side, timeline = page.evaluate("""async () => {
        const boxes = () => ['.today-pad', '[data-col=left]', '.today-timeline'].map((s) => {
            const r = document.querySelector(s).getBoundingClientRect();
            return { x: r.x, y: r.y, width: r.width, height: r.height };
        });
        const frame = () => new Promise((done) => requestAnimationFrame(done));
        let last = JSON.stringify(boxes()), still = 0;
        while (still < 10) {
            await frame();
            const now = JSON.stringify(boxes());
            still = now === last ? still + 1 : 0;
            last = now;
        }
        return boxes();
    }""")
    assert pad["width"] >= 405
    if plan_beside:
        assert side["x"] + side["width"] <= pad["x"]
    else:
        assert side["y"] >= pad["y"] + pad["height"]
    if timeline_beside:
        assert timeline["x"] >= pad["x"] + pad["width"]
    else:
        assert timeline["y"] >= pad["y"] + pad["height"]
        assert timeline["width"] == pad["width"]
