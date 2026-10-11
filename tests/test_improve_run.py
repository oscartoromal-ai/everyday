"""The picks fixed by agent runs (improve/run.py): launched, then followed."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.services.agent_runs import Run, RunError, RunState
from improve import run as improve_run
from improve.findings import Finding
from improve.ledger import Ledger
from improve.run import PullRequest, follow, launch

TODAY = date(2026, 10, 5)


class FakeRunner:
    name = "t3"

    def __init__(self, states: dict[str, RunState] | None = None) -> None:
        self.launched: list = []
        self._states = states or {}

    def launch(self, brief) -> Run:  # noqa: ANN001
        self.launched.append(brief)
        return Run("t3", f"thread-{len(self.launched)}")

    def states(self, runs: list[Run]) -> dict[str, RunState]:
        if self._states is None:
            raise RunError("T3 Code is not running")
        return {run.id: self._states.get(run.id, RunState.gone) for run in runs}


@pytest.fixture
def ledger(tmp_path) -> Ledger:
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.meet(
        [
            Finding("error", "boom", "KeyError in app/x.py:f", "the traceback", 3),
            Finding("lint", "E501", "ruff E501", "places"),
        ],
        TODAY,
    )
    return ledger


def _launch(ledger: Ledger, tmp_path: Path, runner: FakeRunner, **kwargs) -> object:  # noqa: ANN003
    prepared = []
    entry = launch(
        ledger,
        tmp_path / "repo",
        TODAY,
        runner,
        tmp_path / "worktrees",
        tmp_path / "logs",
        prepare=lambda repo, worktree, branch: prepared.append((worktree, branch)),
        existing=kwargs.pop("existing", lambda repo, fingerprint: None),
        **kwargs,
    )
    return entry, prepared


def test_the_pick_is_launched_in_a_worktree_of_its_own(ledger, tmp_path) -> None:
    runner = FakeRunner()

    entry, prepared = _launch(ledger, tmp_path, runner, agents="# AGENTS.md\n\nRead SPEC.md.")

    assert entry.title == "KeyError in app/x.py:f" and entry.status == "picked"
    branch = f"improve/2026-10-05-{entry.fingerprint.replace(':', '-')}"
    worktree = tmp_path / "worktrees" / branch.replace("/", "-")
    assert prepared == [(worktree, branch)]
    assert (entry.branch, entry.worktree, entry.run, entry.attempts) == (
        branch,
        str(worktree),
        "thread-1",
        1,
    )
    [brief] = runner.launched
    assert brief.title == "Improve: KeyError in app/x.py:f"
    assert (brief.repo, brief.worktree, brief.branch) == (tmp_path / "repo", worktree, branch)
    assert "the traceback" in brief.text and f"on the branch `{branch}`" in brief.text
    assert "## The project's AGENTS.md\n\n# AGENTS.md\n\nRead SPEC.md." in brief.text


def test_one_pick_is_fixed_at_a_time(ledger, tmp_path) -> None:
    runner = FakeRunner()
    _launch(ledger, tmp_path, runner)

    entry, _ = _launch(ledger, tmp_path, runner)
    assert entry is None and len(runner.launched) == 1

    entry, _ = _launch(ledger, tmp_path, runner, max_open=2)
    assert entry.title == "ruff E501"


def _picked(ledger: Ledger, tmp_path: Path, runner: FakeRunner):  # noqa: ANN202
    entry, _ = _launch(ledger, tmp_path, runner)
    return entry


def _follow(ledger, tmp_path, runner, pr=None, gate=(True, "gate says ok"), master=()):  # noqa: ANN001, ANN202
    posted, gated = [], []

    def check(repo, checkout, branch):  # noqa: ANN001, ANN202
        gated.append(branch)
        return gate

    said = follow(
        ledger,
        tmp_path / "repo",
        TODAY,
        runner,
        tmp_path / "gate",
        find=lambda repo, branch: pr,
        check=check,
        post=lambda repo, url, body: posted.append((url, body)),
        on_master=lambda repo, commit: commit in master,
    )
    return said, gated, posted


def test_a_pull_request_opened_is_gated_once_for_each_commit(ledger, tmp_path) -> None:
    runner = FakeRunner({"thread-1": RunState.finished})
    entry = _picked(ledger, tmp_path, runner)
    pr = PullRequest("https://github.com/o/r/pull/7", "OPEN", "abc123")

    said, gated, posted = _follow(ledger, tmp_path, runner, pr)
    assert gated == [entry.branch] and posted == [(pr.url, "gate says ok")]
    assert (entry.pr, entry.gated, entry.status) == (pr.url, "abc123", "picked")
    assert said == [f"gated ok: {entry.title} ({pr.url})"]

    said, gated, posted = _follow(ledger, tmp_path, runner, pr)
    assert gated == [] and posted == []
    assert said == [f"waiting on review: {entry.title} ({pr.url})"]

    newer = PullRequest(pr.url, "OPEN", "def456")
    _, gated, _ = _follow(ledger, tmp_path, runner, newer, gate=(False, "red"))
    assert gated == [entry.branch] and entry.gated == "def456"


def test_a_merged_pull_request_settles_its_pick_as_done(ledger, tmp_path, monkeypatch) -> None:
    removed = []
    monkeypatch.setattr(
        improve_run.agent_runs, "remove_worktree", lambda repo, worktree: removed.append(worktree)
    )
    runner = FakeRunner()
    entry = _picked(ledger, tmp_path, runner)

    _follow(ledger, tmp_path, runner, PullRequest("https://x/pull/7", "MERGED", "abc"))

    assert (entry.status, entry.pr, entry.since) == ("done", "https://x/pull/7", "2026-10-05")
    assert removed == [Path(entry.worktree)]


def test_a_pull_request_closed_unmerged_is_oscar_turning_it_down(ledger, tmp_path) -> None:
    runner = FakeRunner()
    entry = _picked(ledger, tmp_path, runner)

    _follow(ledger, tmp_path, runner, PullRequest("https://x/pull/7", "CLOSED", "abc"))

    assert entry.status == "ignored" and "closed without merging" in entry.note


@pytest.mark.parametrize("state", [RunState.working, RunState.waiting])
def test_a_run_still_going_is_left_be(ledger, tmp_path, state) -> None:
    runner = FakeRunner({"thread-1": state})
    entry = _picked(ledger, tmp_path, runner)

    said, _, _ = _follow(ledger, tmp_path, runner)

    assert entry.status == "picked" and said == [f"{state}: {entry.title}"]


def test_a_run_ended_with_no_pull_request_is_tried_again_then_given_up(ledger, tmp_path) -> None:
    runner = FakeRunner({"thread-1": RunState.finished, "thread-2": RunState.failed})
    entry = _picked(ledger, tmp_path, runner)

    _follow(ledger, tmp_path, runner)
    assert (entry.status, entry.branch, entry.run) == ("open", "", "")

    assert _picked(ledger, tmp_path, runner) is entry and entry.attempts == 2
    _follow(ledger, tmp_path, runner)
    assert entry.status == "ignored" and "2 agent runs made no pull request" in entry.note


def _outcome(entry, text: str) -> None:  # noqa: ANN001
    worktree = Path(entry.worktree)
    worktree.mkdir(parents=True, exist_ok=True)
    (worktree / "improve-outcome.md").write_text(text, encoding="utf-8")


def test_a_run_finding_master_fixed_it_already_settles_it_as_done(ledger, tmp_path) -> None:
    runner = FakeRunner({"thread-1": RunState.finished})
    entry = _picked(ledger, tmp_path, runner)
    _outcome(entry, "Already fixed by 1b81a3c\n\nThe window is waited on since.\n")

    said, _, _ = _follow(ledger, tmp_path, runner, master={"1b81a3c"})

    assert entry.status == "done" and entry.note == "already fixed by 1b81a3c on master"
    assert said == [f"already fixed: {entry.title} (1b81a3c)"]
    # Met again, the fix did not hold: it opens again.
    ledger.meet([Finding("error", "boom", entry.title, "again", 1)], TODAY)
    assert (entry.status, entry.reopened) == ("open", 1)


def test_a_fix_claimed_that_is_not_on_master_is_tried_again(ledger, tmp_path) -> None:
    runner = FakeRunner({"thread-1": RunState.finished})
    entry = _picked(ledger, tmp_path, runner)
    _outcome(entry, "Already fixed by 1b81a3c\n")

    _follow(ledger, tmp_path, runner, master=set())

    assert entry.status == "open" and "no pull request" in entry.note


def test_the_brief_says_how_to_tell_it_is_fixed_already(ledger, tmp_path) -> None:
    runner = FakeRunner()
    _launch(ledger, tmp_path, runner)

    [brief] = runner.launched
    assert "`improve-outcome.md`" in brief.text and "Already fixed by <commit>" in brief.text


def test_when_the_runner_cannot_be_asked_no_run_is_taken_to_have_ended(ledger, tmp_path) -> None:
    runner = FakeRunner({"thread-1": RunState.working})
    entry = _picked(ledger, tmp_path, runner)
    runner._states = None

    said, _, _ = _follow(ledger, tmp_path, runner)

    assert entry.status == "picked" and said == ["runs not looked at: T3 Code is not running"]
    # Nor with the runner turned off.
    _, _, _ = _follow(ledger, tmp_path, None)
    assert entry.status == "picked"


def test_a_gate_that_cannot_run_is_tried_at_the_next_follow(ledger, tmp_path) -> None:
    runner = FakeRunner()
    entry = _picked(ledger, tmp_path, runner)

    def broken(repo, checkout, branch):  # noqa: ANN001, ANN202
        raise RunError("git fetch: could not read from remote")

    said = follow(
        ledger,
        tmp_path / "repo",
        TODAY,
        runner,
        tmp_path / "gate",
        find=lambda repo, branch: PullRequest("https://x/pull/7", "OPEN", "abc"),
        check=broken,
        post=lambda *args: None,
    )

    assert entry.gated == "" and said[0].startswith("not gated:")


def test_the_projects_agents_doc_goes_with_the_brief(tmp_path) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.db import Base, make_engine
    from app.models import Project, ProjectRepo

    path = tmp_path / "live.db"
    everyday = tmp_path / "live-everyday-files"
    engine = make_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        project = Project(name="personal-life-app", folder="personal-life-app")
        db.add(project)
        db.flush()
        db.add(ProjectRepo(project_id=project.id, location="https://github.com/o/everyday-app"))
        db.commit()
    engine.dispose()
    agents = everyday / "projects" / "personal-life-app" / "AGENTS.md"
    agents.parent.mkdir(parents=True)
    agents.write_text("# AGENTS.md\n\nRules.\n", encoding="utf-8")

    assert improve_run.agents_doc(path, "o/everyday-app", "", everyday) == "# AGENTS.md\n\nRules."
    assert improve_run.agents_doc(path, "o/other", "", everyday) == ""
    assert improve_run.agents_doc(tmp_path / "none.db", "o/everyday-app", "", everyday) == ""


def test_a_pick_a_pull_request_already_improves_is_taken_up_not_launched(ledger, tmp_path) -> None:
    runner = FakeRunner({})
    url = "https://github.com/o/r/pull/47"

    entry, prepared = _launch(
        ledger,
        tmp_path,
        runner,
        existing=lambda repo, fingerprint: (url, f"improve/2026-10-04-{fingerprint}"),
    )

    assert runner.launched == [] and prepared == []
    assert (entry.status, entry.pr, entry.run) == ("picked", url, "")
    assert entry.branch.startswith("improve/2026-10-04-")
    # Followed from there by its branch, as a launched one is.
    said, _, _ = _follow(ledger, tmp_path, runner, PullRequest(url, "MERGED", "abc"))
    assert entry.status == "done" and said[0].startswith("done:")
