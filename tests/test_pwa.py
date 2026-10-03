"""The app installed as a desktop app: the manifest, the service worker and
the badge's count over HTTP, then in a real browser: Chromium finds it
installable, a page opened while the server is away says so and reconnects,
the icon menu's New task opens the capture window, and the title bar takes
the theme's paper."""

from datetime import datetime

import pytest

from app.services import nudges as nudges_svc
from app.services import tasks as tasks_svc


def test_the_manifest_names_the_app_its_icons_and_shortcuts(client) -> None:
    res = client.get("/manifest.webmanifest")
    assert res.headers["content-type"].startswith("application/manifest+json")
    manifest = res.json()
    assert manifest["name"] == "Personal Calendar"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/today" and manifest["scope"] == "/"
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in manifest["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).headers["content-type"] == "image/png"
    for shortcut in manifest["shortcuts"]:
        assert client.get(shortcut["url"]).status_code == 200
    assert 'rel="manifest" href="/manifest.webmanifest"' in client.get("/today").text


def test_the_service_worker_is_served_from_the_root_and_always_checked(client) -> None:
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/javascript")
    assert res.headers["cache-control"] == "no-cache"


def test_the_badge_counts_the_nudges_waiting(client, db) -> None:
    assert client.get("/ui/nudges/count").json() == {"count": 0}
    tasks_svc.create_task(db, title="Renew passport", due=datetime.now().date())
    assert nudges_svc.evaluate(db, datetime.now())  # it is due today
    db.commit()
    assert client.get("/ui/nudges/count").json() == {"count": 1}


pytest.importorskip("playwright.sync_api")

CONTROLLED = "navigator.serviceWorker.controller !== null"


def test_chromium_finds_the_app_installable(page, live) -> None:
    page.goto(f"{live}/today")
    page.wait_for_function("navigator.serviceWorker.ready.then(() => true)")
    cdp = page.context.new_cdp_session(page)
    errors = cdp.send("Page.getInstallabilityErrors")["installabilityErrors"]
    # A test browser is a fresh, private profile; that alone is not the app's.
    assert [e["errorId"] for e in errors if e["errorId"] != "in-incognito"] == []


def test_a_page_opened_while_the_server_is_away_says_so_and_reconnects(page, live) -> None:
    page.goto(f"{live}/today")
    # The first page is taken once the worker is active; else the next one is.
    page.wait_for_function("navigator.serviceWorker.ready.then(() => true)")
    if not page.evaluate(CONTROLLED):
        page.reload()
    page.wait_for_function(CONTROLLED)

    page.context.set_offline(True)
    page.goto(f"{live}/projects")
    page.get_by_role("heading", name="Personal Calendar isn’t running").wait_for()
    assert page.get_by_role("status").text_content() == "Waiting for the app"

    # Back: within its two seconds, the page it was opening.
    page.context.set_offline(False)
    page.get_by_role("heading", name="Projects").wait_for(timeout=5000)
    assert page.url == f"{live}/projects"


def test_new_task_from_the_icon_menu_opens_the_capture_window(page, live) -> None:
    page.goto(f"{live}/today?capture=1")
    page.locator("#capture-dialog[open]").wait_for()
    page.wait_for_function("document.activeElement.matches('#capture-dialog .sheet-title')")
    assert page.url == f"{live}/today"  # a reload does not open it again


def test_the_title_bar_takes_the_themes_paper(page, live) -> None:
    bar = "document.querySelector('meta[name=\"theme-color\"]').content"
    paper = "getComputedStyle(document.documentElement).getPropertyValue('--paper').trim()"
    page.goto(f"{live}/today")
    light = page.evaluate(bar)
    assert light == page.evaluate(paper)
    page.locator(".theme-toggle").click()
    assert page.evaluate(bar) == page.evaluate(paper) != light
    page.reload()  # the saved theme's colour, before the page's scripts run
    assert page.evaluate(bar) == page.evaluate(paper) != light
