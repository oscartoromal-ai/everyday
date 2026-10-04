"""Repositories in a real browser, over a stand-in for GitHub and the
GitHub CLI: connecting in one click, the first sync drawing the list,
finding one by its words, a second account added and disconnected, and
reaching the page by its key and from the command menu; then a project's
line to add a repository, picking one of his. The `live`, `page` and
`app_db` fixtures are conftest.py's."""

import pytest
from github_fake import (
    CLI_TOKEN,
    LOGIN,
    WORK_LOGIN,
    WORK_TOKEN,
    FakeCli,
    FakeGitHub,
    fake_account,
    repo_payload,
)

from app.models import GitHubSource
from app.services import github as github_svc
from app.services import projects as projects_svc
from app.services import rail as rail_svc

pytest.importorskip("playwright.sync_api")


@pytest.fixture
def cli() -> FakeCli:
    return FakeCli()


@pytest.fixture
def github(monkeypatch, tmp_path, cli) -> FakeGitHub:
    from app.ui import repositories as ui_repositories

    fake = FakeGitHub()
    fake.repos = [
        repo_payload(1, "everyday-app", pushed_at="2026-10-04T00:34:43Z"),
        repo_payload(2, "pylon-engine", pushed_at="2026-10-03T04:37:55Z", language="Rust"),
        repo_payload(3, "pylon-legacy", pushed_at="2026-09-28T09:06:06Z", archived=True),
    ]
    account = fake_account(tmp_path, fake, cli)
    monkeypatch.setattr(ui_repositories, "account", lambda: account)
    yield fake
    github_svc.syncing.wait(5)


def test_connect_in_one_click_then_find_a_repository(page, live, app_db, github) -> None:
    page.goto(f"{live}/repositories")
    offer = page.locator("#github-cli")
    offer.get_by_text(f"Signed in as {LOGIN}").wait_for()
    offer.get_by_role("button", name=f"Connect {LOGIN}").click()

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
        assert [link.login for link in github_svc.links(db)] == [LOGIN]

    find = page.get_by_label("Find a repository")
    find.fill("rust")
    page.wait_for_function(
        "document.querySelectorAll('#repos-list .repo-name').length === 1"
    )
    assert page.locator("#repos-list .repo-name").inner_text() == "pylon-engine"
    assert find.evaluate("el => el === document.activeElement")  # still writing
    find.fill("")
    page.wait_for_function("document.querySelectorAll('#repos-list .repo-name').length === 3")


def test_a_second_account_added_then_disconnected(page, live, app_db, github, cli) -> None:
    cli.accounts = {LOGIN: CLI_TOKEN, WORK_LOGIN: WORK_TOKEN}
    github.work_repos = [repo_payload(9, "roadmaps", owner=WORK_LOGIN)]
    with app_db() as db:
        github_svc.connect(db, {"id": 101, "login": LOGIN, "name": "Oscar"}, GitHubSource.cli)
        db.commit()
    page.goto(f"{live}/repositories")

    # Adding another is folded away; opened, gh offers the one not connected.
    add = page.locator(".github-add")
    assert not add.evaluate("el => el.open")
    add.get_by_text("Add another account").click()
    add.get_by_text(f"Signed in as {WORK_LOGIN}").wait_for()
    assert add.get_by_text(f"Signed in as {LOGIN}").count() == 0
    add.get_by_role("button", name=f"Connect {WORK_LOGIN}").click()

    page.get_by_role("link", name=f"{WORK_LOGIN}/roadmaps").wait_for()
    account = page.locator("#github-account")
    assert account.locator(".github-link").count() == 2
    assert account.locator(".me-label").first.inner_text() == "Accounts"

    account.locator(".github-link", has_text=WORK_LOGIN).get_by_role(
        "button", name="Disconnect"
    ).click()
    dialog = page.locator("#confirm-dialog")
    assert dialog.locator(".confirm-name").inner_text() == WORK_LOGIN
    dialog.locator("[value=go]").click()
    page.wait_for_function("!document.body.textContent.includes('roadmaps')")
    assert account.locator(".github-link").count() == 1
    with app_db() as db:
        assert [link.login for link in github_svc.links(db)] == [LOGIN]


def test_reached_by_its_key_and_the_command_menu(page, live, app_db, github) -> None:
    # Finances hidden, Repositories is the seventh module showing.
    with app_db() as db:
        rail_svc.save_layout(
            db, sections=[], modules={}, hidden=["spending", "accounts", "bills", "goals"]
        )
        db.commit()
    page.goto(f"{live}/today")
    page.keyboard.press("Alt+7")
    page.wait_for_url(f"{live}/repositories")
    assert page.get_by_role("link", name="Repositories").get_attribute("aria-current") == "page"

    page.goto(f"{live}/today")
    page.keyboard.press("Control+k")
    page.locator(".command-input").fill("repositories")
    page.locator(".command-results").get_by_text("Repositories").first.wait_for()
    page.keyboard.press("Enter")
    page.wait_for_url(f"{live}/repositories")


# ---- a project's line to add a repository ----


def test_a_project_picks_one_of_his_repositories(page, live, app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Pylon")
        link = github_svc.connect(db, {"id": 1, "login": "me", "name": "Me"}, GitHubSource.cli)
        github_svc.keep_repositories(db, link, [
            repo_payload(1, "everyday-app", owner="me", pushed_at="2026-10-04T00:00:00Z"),
            repo_payload(2, "pylon-engine", owner="me", pushed_at="2026-10-03T00:00:00Z",
                         language="Rust"),
            repo_payload(3, "pylon-web", owner="me", pushed_at="2026-10-02T00:00:00Z"),
        ])
        db.commit()
        project_id = project.id
    page.goto(f"{live}/projects/{project_id}")
    field = page.locator("#repo-new")
    options = page.locator('#repo-options [role="option"]')

    # Focused, it lists them last pushed first; written on, those it holds.
    field.click()
    page.wait_for_function("document.querySelectorAll('#repo-options [role=option]').length === 3")
    assert field.get_attribute("aria-expanded") == "true"
    assert options.locator(".repo-option-label").all_inner_texts() == [
        "everyday-app", "pylon-engine", "pylon-web",
    ]
    field.press_sequentially("pylon")
    page.wait_for_function("document.querySelectorAll('#repo-options [role=option]').length === 2")
    # The first found is the one Enter takes; Down moves on.
    assert options.first.get_attribute("aria-selected") == "true"
    field.press("ArrowDown")
    assert options.nth(1).get_attribute("aria-selected") == "true"
    assert field.get_attribute("aria-activedescendant") == options.nth(1).get_attribute("id")
    field.press("Enter")

    page.locator("#project-repos .item-name", has_text="pylon-web").wait_for()
    with app_db() as db:
        assert [r.location for r in projects_svc.get_project(db, project_id).repos] == [
            "https://github.com/me/pylon-web",
        ]
    # The focus back on the line does not offer more at once.
    page.wait_for_timeout(300)
    assert page.locator("#repo-new").evaluate("el => el === document.activeElement")
    assert page.locator("#repo-options").is_hidden()

    # A click picks one too; the project's own are no longer offered.
    page.locator("#repo-new").press("ArrowDown")
    page.wait_for_function("document.querySelectorAll('#repo-options [role=option]').length === 2")
    options.filter(has_text="everyday-app").click()
    page.locator("#project-repos .item-name", has_text="everyday-app").wait_for()

    # Words nothing holds are added as written; Esc folds the list first.
    field = page.locator("#repo-new")
    field.click()
    field.fill(r"C:\code\pylon-docs")
    page.locator("#repo-options").get_by_text("as written").wait_for()
    field.press("Escape")
    assert page.locator("#repo-options").is_hidden()
    field.press("Enter")
    page.locator("#project-repos .item-name", has_text="pylon-docs").wait_for()
