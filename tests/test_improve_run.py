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


def _follow(ledger, tmp_path, runner, pr=None, gate=(True, "gate says ok")):  # noqa: ANN001, ANN202
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
    from app.models import Project, ProjectDoc, ProjectRepo

    path = tmp_path / "live.db"
    engine = make_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        project = Project(name="personal-life-app")
        db.add(project)
        db.flush()
        db.add_all(
            [
                ProjectRepo(project_id=project.id, location="https://github.com/o/everyday-app"),
                ProjectDoc(project_id=project.id, name="AGENTS.md", body="# AGENTS.md\n\nRules.\n"),
            ]
        )
        db.commit()
    engine.dispose()

    assert improve_run.agents_doc(path, "o/everyday-app", "") == "# AGENTS.md\n\nRules."
    assert improve_run.agents_doc(path, "o/other", "") == ""
    assert improve_run.agents_doc(tmp_path / "none.db", "o/everyday-app", "") == ""
