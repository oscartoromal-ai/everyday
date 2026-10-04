"""Repositories in a real browser, over a stand-in for GitHub and the
GitHub CLI: connecting in one click, the first sync drawing the list,
finding one by its words, and reaching the page by its key and from the
command menu. The `live`, `page` and `app_db` fixtures are conftest.py's."""

import pytest
from github_fake import LOGIN, FakeCli, FakeGitHub, fake_account, repo_payload

from app.services import github as github_svc

pytest.importorskip("playwright.sync_api")


@pytest.fixture
def github(monkeypatch, tmp_path) -> FakeGitHub:
    from app.ui import repositories as ui_repositories

    fake = FakeGitHub()
    fake.repos = [
        repo_payload(1, "everyday-app", pushed_at="2026-10-04T00:34:43Z"),
        repo_payload(2, "pylon-engine", pushed_at="2026-10-03T04:37:55Z", language="Rust"),
        repo_payload(3, "pylon-legacy", pushed_at="2026-09-28T09:06:06Z", archived=True),
    ]
    account = fake_account(tmp_path, fake, FakeCli())
    monkeypatch.setattr(ui_repositories, "account", lambda: account)
    yield fake
    github_svc.syncing.wait(5)


def test_connect_in_one_click_then_find_a_repository(page, live, app_db, github) -> None:
    page.goto(f"{live}/repositories")
    cli = page.locator("#github-cli")
    cli.get_by_text(f"Signed in as {LOGIN}").wait_for()
    cli.get_by_role("button", name="Connect").click()

    # Connected: the page drawn again, the first sync filling in the list.
    page.get_by_role("link", name="everyday-app").wait_for()
    page.locator("#github-account").get_by_text("today").wait_for()
    rows = page.locator("#repos-active ~ .repos-rows .repo-name")
    assert rows.all_inner_texts() == ["everyday-app", "pylon-engine"]
    assert page.get_by_role("link", name="everyday-app").get_attribute("target") == "_blank"
    archived = page.locator(".repos-fold")
    assert not archived.evaluate("el => el.open")
    archived.locator("summary").click()
    assert archived.get_by_role("link", name="pylon-legacy").is_visible()
    with app_db() as db:
        assert github_svc.link(db).login == LOGIN

    find = page.get_by_label("Find a repository")
    find.fill("rust")
    page.wait_for_function(
        "document.querySelectorAll('#repos-list .repo-name').length === 1"
    )
    assert page.locator("#repos-list .repo-name").inner_text() == "pylon-engine"
    assert find.evaluate("el => el === document.activeElement")  # still writing
    find.fill("")
    page.wait_for_function("document.querySelectorAll('#repos-list .repo-name').length === 3")


def test_reached_by_its_key_and_the_command_menu(page, live, app_db, github) -> None:
    page.goto(f"{live}/today")
    page.locator("body").press("8")
    page.wait_for_url(f"{live}/repositories")
    assert page.get_by_role("link", name="Repositories").get_attribute("aria-current") == "page"

    page.goto(f"{live}/today")
    page.keyboard.press("Control+k")
    page.locator(".command-input").fill("repositories")
    page.locator(".command-results").get_by_text("Repositories").first.wait_for()
    page.keyboard.press("Enter")
    page.wait_for_url(f"{live}/repositories")
