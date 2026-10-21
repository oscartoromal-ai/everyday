"""The New project window in a real browser: Projects' New project opens it
with the next colour picked and the caret in the name; Create project with
no name says so and sends nothing; a project made with everything lands on
its page, all of it there; a repository refused is said under its line,
the window open; Esc closes it, and it opens again empty; Shift+A on
Projects and the command menu open it too; and on a phone it fits. The
`live`, `page`, `phone` and `app_db` fixtures are conftest.py's."""

from pathlib import Path

import pytest
from github_fake import repo_payload

from app.models import GitHubSource
from app.services import github as github_svc
from app.services import projects as projects_svc

pytest.importorskip("playwright.sync_api")

WINDOW = "#project-dialog"
OPEN = f"{WINDOW}[open]"
NAME = f"{WINDOW} input[name=name]"
REPO = f"{WINDOW} input[name=location]"
CHECKED = f"document.querySelector('{WINDOW} input[name=color]:checked')?.value ?? null"
FOCUSED_NAME = f"document.activeElement?.matches('{NAME}')"


@pytest.fixture
def two(app_db) -> None:
    """Two projects, in the first two colours, so the next is the third."""
    with app_db() as db:
        projects_svc.create_project(db, name="Home", color=1)
        projects_svc.create_project(db, name="Work", color=2)
        db.commit()


def project_named(app_db, name: str):  # noqa: ANN201
    with app_db() as db:
        project = next((p for p in projects_svc.list_projects(db) if p.name == name), None)
        if project is None:
            return None
        return project.id, project.color, project.notes, [r.location for r in project.repos]


def open_from_the_button(page, live: str) -> None:
    page.goto(f"{live}/projects")
    page.get_by_role("button", name="New project").click()
    page.locator(OPEN).wait_for()


def test_the_button_opens_it_on_the_next_colour_the_caret_in_the_name(page, live, two) -> None:
    open_from_the_button(page, live)
    page.wait_for_function(FOCUSED_NAME)
    assert page.evaluate(CHECKED) == "3"
    assert page.locator(f"{WINDOW} h2").text_content() == "New project"
    # The fields, each its name over its line.
    labels = page.locator(f"{WINDOW} .field-label").all_inner_texts()
    assert [label.split()[0] for label in labels] == ["Name", "Colour", "Description", "Repository"]


def test_no_name_says_so_and_sends_nothing(page, live, app_db, two) -> None:
    open_from_the_button(page, live)
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    error = page.locator("#project-new-name-error")
    assert error.is_hidden()

    page.keyboard.type("   ")
    page.get_by_role("button", name="Create project").click()
    error.wait_for()
    assert error.text_content() == "A project needs a name."
    assert page.evaluate(FOCUSED_NAME)
    # The name's line in the error's colour, at 2px (once its change of colour has run).
    err = page.evaluate(
        "(() => { const s = document.createElement('span'); s.style.color = 'var(--err-fg)';"
        " document.body.append(s); const c = getComputedStyle(s).color; s.remove(); return c; })()"
    )
    page.wait_for_function(
        f"getComputedStyle(document.querySelector('{NAME}').parentElement).boxShadow"
        f" === '{err} 0px -2px 0px 0px inset'"
    )
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    assert posts == []
    assert page.locator(OPEN).count() == 1

    # A letter written, it is gone.
    page.keyboard.type("G")
    assert error.is_hidden()
    assert page.locator(NAME).get_attribute("aria-invalid") is None


def test_everything_written_lands_on_the_new_projects_page(
    page, live, app_db, two, tmp_path
) -> None:
    folder = tmp_path / "garden-shed"
    folder.mkdir()
    open_from_the_button(page, live)
    page.keyboard.type("Garden shed")
    page.locator(f"{WINDOW} .swatch").nth(4).click()
    page.locator(WINDOW).get_by_label("Description").fill("A place for the mower")
    page.locator(REPO).fill(str(folder))
    # The repositories' list, folded, so Ctrl+Enter is the window's.
    page.locator(f"{WINDOW} textarea[name=notes]").focus()
    page.keyboard.press("Control+Enter")

    page.wait_for_url(f"{live}/projects/*")
    found = project_named(app_db, "Garden shed")
    assert found is not None
    project_id, color, notes, repos = found
    assert page.url == f"{live}/projects/{project_id}"
    assert (color, notes, repos) == (5, "A place for the mower", [str(folder)])

    assert page.locator("h1").first.text_content().strip() == "Garden shed"
    assert page.locator(".project-description textarea").input_value() == "A place for the mower"
    assert page.locator(".project-details input[name=color]:checked").get_attribute("value") == "5"
    assert page.locator("#project-repos .item-name").all_inner_texts() == [Path(folder).name]
    rail = page.locator("#rail-projects .nav-label").all_inner_texts()
    assert rail == ["Home", "Work", "Garden shed"]


def test_a_repository_refused_is_said_under_its_line(page, live, app_db, two) -> None:
    open_from_the_button(page, live)
    page.keyboard.type("Too far")
    page.locator(REPO).fill("x" * 1001)
    # Nothing of his found, Enter takes the words as written.
    page.locator("#project-new-repo-options .repo-options-note").wait_for()
    page.keyboard.press("Enter")

    error = page.locator("#project-new-repo-error")
    error.wait_for()
    assert error.text_content() == "A repository's location is 1000 characters at most"
    assert page.evaluate(f"document.activeElement?.matches('{REPO}')")
    # The window open, with what was written; no toast, and no project.
    assert page.locator(OPEN).count() == 1
    assert page.locator(NAME).input_value() == "Too far"
    assert not page.locator(".cal-toast.show").count()
    assert project_named(app_db, "Too far") is None
    assert page.locator("#project-new-name-error").is_hidden()

    # Written again, it goes.
    page.locator(REPO).fill("")
    assert error.is_hidden()


def test_a_repository_picked_fills_the_line_and_creates_nothing_yet(page, live, app_db) -> None:
    with app_db() as db:
        project = projects_svc.create_project(db, name="Pylon")
        link = github_svc.connect(db, {"id": 1, "login": "me", "name": "Me"}, GitHubSource.cli)
        github_svc.keep_repositories(
            db,
            link,
            [
                repo_payload(1, "pylon-engine", owner="me", pushed_at="2026-10-03T00:00:00Z"),
                repo_payload(2, "pylon-web", owner="me", pushed_at="2026-10-02T00:00:00Z"),
            ],
        )
        db.commit()
        project_id = project.id
    # On a project's Overview, beside the card's own line to add one.
    page.goto(f"{live}/projects/{project_id}")
    page.evaluate("window.ProjectNew.open()")
    page.locator(OPEN).wait_for()
    page.keyboard.type("Pylon docs")
    options = page.locator('#project-new-repo-options [role="option"]')
    page.locator(REPO).click()
    page.wait_for_function(
        "document.querySelectorAll('#project-new-repo-options [role=option]').length === 2"
    )
    assert page.locator(REPO).get_attribute("aria-expanded") == "true"
    assert page.locator("#repo-options").is_hidden()
    # Esc folds the list away, the window staying; Down offers it again.
    page.keyboard.press("Escape")
    assert page.locator("#project-new-repo-options").is_hidden()
    page.wait_for_timeout(200)
    assert page.locator(OPEN).count() == 1
    page.keyboard.press("ArrowDown")
    options.first.wait_for()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    assert page.locator(REPO).get_attribute("aria-activedescendant") == "project-new-repo-option-2"
    page.keyboard.press("Enter")
    assert page.locator(REPO).input_value() == "https://github.com/me/pylon-web"
    assert page.locator("#project-new-repo-options").is_hidden()
    page.wait_for_timeout(300)
    assert page.locator(OPEN).count() == 1
    assert project_named(app_db, "Pylon docs") is None

    # A click picks too; then Enter on the line creates it.
    page.locator(REPO).fill("engine")
    options.first.wait_for()
    options.first.click()
    assert page.locator(REPO).input_value() == "https://github.com/me/pylon-engine"
    assert page.locator(OPEN).count() == 1
    page.keyboard.press("Enter")
    page.wait_for_url(lambda url: url != f"{live}/projects/{project_id}")
    assert project_named(app_db, "Pylon docs")[3] == ["https://github.com/me/pylon-engine"]


def test_esc_closes_it_and_it_opens_again_empty(page, live, two) -> None:
    open_from_the_button(page, live)
    page.keyboard.type("Half written")
    page.locator(f"{WINDOW} .swatch").nth(6).click()
    page.keyboard.press("Escape")
    page.locator(OPEN).wait_for(state="detached")
    # The button has the focus back.
    assert page.evaluate("document.activeElement?.matches('[data-project-new]')")

    page.get_by_role("button", name="New project").click()
    page.locator(OPEN).wait_for()
    page.wait_for_function(FOCUSED_NAME)
    assert page.locator(NAME).input_value() == ""
    assert page.evaluate(CHECKED) == "3"

    # Cancel closes it too, and so does a click on the backdrop.
    page.get_by_role("button", name="Cancel").click()
    page.locator(OPEN).wait_for(state="detached")
    page.get_by_role("button", name="New project").click()
    page.locator(OPEN).wait_for()
    page.mouse.click(10, 10)
    page.locator(OPEN).wait_for(state="detached")


def test_shift_a_on_projects_and_the_command_menu_open_it(page, live, two) -> None:
    page.goto(f"{live}/projects")
    page.evaluate("document.activeElement?.blur()")
    page.keyboard.press("Shift+A")
    page.locator(OPEN).wait_for()
    page.wait_for_function(FOCUSED_NAME)
    page.keyboard.press("Escape")
    page.locator(OPEN).wait_for(state="detached")

    # On any page, from the command menu.
    page.goto(f"{live}/calendar")
    page.evaluate("document.activeElement?.blur()")
    page.keyboard.press("Control+k")
    page.locator("#command-dialog[open]").wait_for()
    page.keyboard.type("new project")
    page.locator(".command-item", has_text="New project").first.wait_for()
    page.keyboard.press("Enter")
    page.locator(OPEN).wait_for()
    page.wait_for_function(FOCUSED_NAME)
    assert page.locator("#command-dialog[open]").count() == 0
    assert page.evaluate(CHECKED) == "3"


def test_on_a_phone_it_fits(phone, live, two) -> None:
    phone.goto(f"{live}/projects")
    phone.get_by_role("button", name="New project").click()
    phone.locator(OPEN).wait_for()
    box = phone.locator(WINDOW).bounding_box()
    assert box["x"] == pytest.approx(16, abs=1)
    assert box["width"] == pytest.approx(390 - 32, abs=1)
    # Nothing in it runs past its edges.
    over = phone.evaluate(
        f"""(() => {{
          const d = document.querySelector('{WINDOW}').getBoundingClientRect();
          return [...document.querySelectorAll('{WINDOW} *')]
            .filter((el) => el.getClientRects().length)
            .filter((el) => {{ const r = el.getBoundingClientRect();
              return r.right > d.right + 0.5 || r.bottom > d.bottom + 0.5; }})
            .map((el) => el.className || el.tagName);
        }})()"""
    )
    assert over == []
    assert box["y"] + box["height"] <= 844
