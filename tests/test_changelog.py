"""The changelog: change files read, versions numbered from the order master
took them in (on throwaway repos, and on this one's own changes/), the
releases bundled for the installed app, and the page and Settings drawing
them."""

import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from app import changelog
from app.changelog import Change, ChangeFileError, Release

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


# ---- change files ----


def test_a_change_file_holds_its_changes_each_of_a_kind() -> None:
    f = changelog.parse(
        "x.md",
        "- Feature: Give tasks a *priority*\n"
        "  Shown wherever tasks are.\n"
        "\n"
        "  Set with p1 to p4.\n"
        "- fix: The Update button no longer fails\n"
        "- MAJOR: Add Finances\n",
    )
    assert f.shipped is None
    assert f.changes == (
        Change(
            "feature", "Give tasks a *priority*", "Shown wherever tasks are.\n\nSet with p1 to p4."
        ),
        Change("fix", "The Update button no longer fails"),
        Change("major", "Add Finances"),
    )


def test_a_change_file_can_name_the_commit_that_shipped_it() -> None:
    f = changelog.parse("x.md", "---\r\nshipped: e113b41\r\n---\r\n- Major: The planner\r\n")
    assert f.shipped == "e113b41"
    assert f.changes == (Change("major", "The planner"),)


@pytest.mark.parametrize(
    "text, why",
    [
        ("- Chore: Tidy up\n", "x.md:1: a change starts"),
        ("Give tasks a priority\n", "x.md:1: a change starts"),
        ("  Shown wherever\n- Feature: Priority\n", "x.md:1: an indented line under no change"),
        ("\n\n", "x.md: no changes in it"),
        ("---\nversion: 2.0.0\n---\n- Fix: A\n", "x.md: its front matter"),
    ],
)
def test_a_change_file_written_wrong_says_where(text: str, why: str) -> None:
    with pytest.raises(ChangeFileError, match=why):
        changelog.parse("x.md", text)


def test_a_release_is_the_largest_of_its_changes() -> None:
    changes = (Change("fix", "a"), Change("major", "b"), Change("feature", "c"))
    assert Release("1.0.0", None, None, changes).kind == "major"
    assert Release("1.1.0", None, None, changes[::2]).kind == "feature"


def test_the_kinds_bump_the_major_the_minor_and_the_patch() -> None:
    assert changelog.bump((1, 2, 3), "major") == (2, 0, 0)
    assert changelog.bump((1, 2, 3), "feature") == (1, 3, 0)
    assert changelog.bump((1, 2, 3), "fix") == (1, 2, 4)


# ---- versions, from git ----


class Repo:
    """A throwaway repo, its commits a day apart from 1 Oct 2026."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.day = 0
        self.git("init", "--quiet", "--initial-branch=master")

    def git(self, *args: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_AUTHOR_DATE": f"2026-10-{1 + self.day:02d}T12:00:00+11:00",
            "GIT_COMMITTER_DATE": f"2026-10-{1 + self.day:02d}T12:00:00+11:00",
        }
        out = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-C", str(self.root), *args],
            capture_output=True, text=True, check=True, env=env,
        )
        return out.stdout.strip()

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str, **files: str) -> str:
        for name, text in files.items():
            self.write(name.replace("__", "/"), text)
        self.git("add", "--all")
        self.git("commit", "--quiet", "--allow-empty", "-m", message)
        self.day += 1
        return self.git("rev-parse", "HEAD")

    def merge(self, branch: str) -> str:
        self.git("merge", "--quiet", "--no-ff", "-m", f"Merge {branch}", branch)
        self.day += 1
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path) -> Repo:
    return Repo(tmp_path)


def summary(releases: list[Release]) -> list[tuple]:
    return [(r.version, r.released, [c.summary for c in r.changes]) for r in releases]


@needs_git
def test_each_commit_on_masters_line_makes_a_version_of_what_it_brought(repo: Repo) -> None:
    repo.commit("Start", README="Hi\n")
    first = repo.commit("Planner", **{"changes__planner.md": "- Major: The planner\n"})
    # Neither a commit without changes nor a file other than Markdown is one.
    repo.commit("Tidy", changes__README="How to write a change\n")
    # A pull request: two commits, one file each, one version once merged.
    repo.git("switch", "--quiet", "-c", "priority")
    repo.commit("Priority", **{"changes__priority.md": "- Feature: Priority\n"})
    repo.commit("Its fix", **{"changes__priority-fix.md": "- Fix: Priority's menu\n"})
    repo.git("switch", "--quiet", "master")
    repo.commit("A fix on master", **{"changes__update.md": "- Fix: Update\n"})
    merged = repo.merge("priority")

    releases = changelog.from_git(repo.root)

    assert summary(releases) == [
        # Its largest change is a Feature; Features before Fixes.
        ("1.1.0", date(2026, 10, 7), ["Priority", "Priority's menu"]),
        ("1.0.1", date(2026, 10, 6), ["Update"]),
        ("1.0.0", date(2026, 10, 2), ["The planner"]),
    ]
    assert [releases[0].commit, releases[2].commit] == [merged, first]


@needs_git
def test_a_file_can_ship_in_an_earlier_version_it_names(repo: Repo) -> None:
    v1 = repo.commit("Planner", **{"changes__planner.md": "- Major: The planner\n"})
    calendar = repo.commit("Calendar")
    repo.commit(
        "Write down what shipped",
        **{
            "changes__calendar.md": f"---\nshipped: {calendar[:7]}\n---\n- Feature: A calendar\n",
            "changes__planner-fix.md": f"---\nshipped: {v1[:7]}\n---\n- Fix: Its first fix\n",
        },
    )

    assert summary(changelog.from_git(repo.root)) == [
        ("1.1.0", date(2026, 10, 2), ["A calendar"]),
        ("1.0.0", date(2026, 10, 1), ["The planner", "Its first fix"]),
    ]


@needs_git
def test_a_file_naming_a_commit_off_masters_line_is_refused(repo: Repo) -> None:
    repo.commit("Planner", **{"changes__planner.md": "- Major: The planner\n"})
    repo.git("switch", "--quiet", "-c", "side")
    side = repo.commit("Side")
    repo.git("switch", "--quiet", "master")
    repo.commit("Pin", **{"changes__pin.md": f"---\nshipped: {side[:7]}\n---\n- Fix: A\n"})

    with pytest.raises(ChangeFileError, match="pin.md: shipped: .* is not one commit"):
        changelog.from_git(repo.root)


@needs_git
def test_changes_not_yet_committed_are_unreleased_on_top(repo: Repo) -> None:
    repo.commit("Planner", **{"changes__planner.md": "- Major: The planner\n"})
    repo.write("changes/new.md", "- Fix: Something new\n")

    releases = changelog.from_git(repo.root)

    assert summary(releases) == [
        (None, None, ["Something new"]),
        ("1.0.0", date(2026, 10, 1), ["The planner"]),
    ]
    assert changelog.version(releases) == "1.0.0"


def test_the_releases_survive_the_trip_to_the_installed_app() -> None:
    releases = [
        Release(None, None, None, (Change("fix", "New"),)),
        Release("1.0.0", date(2026, 10, 1), "abc", (Change("major", "Planner", "More."),)),
    ]
    import json

    assert changelog.from_json(json.loads(changelog.to_json(releases))) == releases


def test_the_installed_app_reads_its_bundled_releases(monkeypatch, tmp_path) -> None:
    releases = [Release("1.0.0", date(2026, 10, 1), "abc", (Change("major", "Planner"),))]
    (tmp_path / "changelog.json").write_text(changelog.to_json(releases), encoding="utf-8")
    # As build.ps1 writes it: PowerShell's UTF-8, with a byte-order mark.
    (tmp_path / "build-info.json").write_text('{"commit": "abc1234+"}', encoding="utf-8-sig")
    monkeypatch.setattr(changelog, "FROZEN", True)
    monkeypatch.setattr(changelog, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(changelog, "BUNDLED", tmp_path / "changelog.json")
    monkeypatch.setattr(changelog, "_cache", None)

    assert changelog.running() == changelog.Running("1.0.0", "abc1234+", True, tuple(releases))


@needs_git
def test_this_repos_change_files_all_read_and_number() -> None:
    """Every file in changes/ is written right, and every commit one names
    is on master's line: what the build will refuse, caught first."""
    releases = changelog.from_git(changelog.REPO_ROOT)
    numbered = [r for r in releases if r.version]
    assert numbered[-1].version == "1.0.0"
    assert numbered[-1].released == date(2026, 8, 28)
    # Newest first, each a step up from the one before it.
    assert len({r.version for r in numbered}) == len(numbered)
    assert all(r.changes for r in releases)


# ---- the page, and Settings ----


def fake_running(monkeypatch) -> None:
    releases = (
        Release(None, None, None, (Change("fix", "Not merged"),)),
        Release(
            "2.1.0", date(2026, 10, 4), "def",
            (Change("feature", "Give tasks a *priority*", "Shown wherever tasks are."),),
        ),
        Release("2.0.0", date(2026, 10, 3), "abc", (Change("major", "Add Finances"),)),
    )
    running = changelog.Running("2.1.0", "1a2b3c4", False, releases)
    monkeypatch.setattr(changelog, "running", lambda: running)


def test_the_changelog_page_lists_every_version_newest_first(client, monkeypatch) -> None:
    fake_running(monkeypatch)

    html = client.get("/changelog").text

    assert "This is 2.1.0, run from 1a2b3c4." in html
    assert html.index("Unreleased") < html.index("2.1.0</span>") < html.index("2.0.0</span>")
    assert "Not merged yet" in html and "4 Oct 2026" in html
    # The running one marked; a change's words and details as Markdown.
    assert html.count("This version") == 1
    assert "Give tasks a <em>priority</em>" in html
    assert "<p>Shown wherever tasks are.</p>" in html
    assert '<li class="release-change" data-kind="major">' in html


def test_settings_names_the_version_and_opens_the_changelog(client, monkeypatch) -> None:
    fake_running(monkeypatch)

    html = client.get("/today").text

    assert '<a class="settings-version" href="/changelog">' in html
    assert '<span class="settings-version__number">2.1.0</span>' in html
    assert "run from 1a2b3c4" in html


def test_a_changelog_that_cannot_be_read_costs_the_version_not_the_page(
    client, monkeypatch, tmp_path
) -> None:
    (tmp_path / "changes").mkdir()
    (tmp_path / "changes" / "bad.md").write_text("Not a change\n", encoding="utf-8")
    monkeypatch.setattr(changelog, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(changelog, "_cache", None)
    monkeypatch.setattr(changelog, "_fingerprint", lambda repo: ())

    assert client.get("/today").status_code == 200
    html = client.get("/changelog").text
    assert "the changelog could not be read" in html
