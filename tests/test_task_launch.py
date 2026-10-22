"""A task launched as an agent run (SPEC.md, Agent runs): its repositories'
main clones, its workspace and branch, the brief, and the run followed from
its runner: its task moved with it, its pull requests linked, its worktrees
removed once the task is settled."""

from datetime import datetime
from pathlib import Path

import pytest
from github_fake import FakeCli, FakeGitHub, fake_account

from app.models import AGENTS_DOC, TaskStatus
from app.services import DomainError, everyday, project_files, task_launch, task_runs
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.services.agent_runs import Run, RunError, RunState, _git


class FakeRunner:
    """A runner that keeps the briefs it was given, and says each run's
    state as told."""

    name = "t3"

    def __init__(self) -> None:
        self.briefs = []
        self.state: dict[str, RunState] = {}
        self.fail: Exception | None = None

    def launch(self, brief):  # noqa: ANN001, ANN201
        if self.fail:
            raise self.fail
        self.briefs.append(brief)
        run = Run(self.name, f"thread-{len(self.briefs)}")
        self.state[run.id] = RunState.working
        return run

    def states(self, runs):  # noqa: ANN001, ANN201
        if self.fail:
            raise self.fail
        return {r.id: self.state[r.id] for r in runs}


def a_repo(root: Path, name: str) -> Path:
    """A repository with an origin whose default branch is main."""
    origin, repo = root / "origins" / name, root / "clones" / name
    origin.mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=origin)
    _git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "first",
        cwd=origin,
    )
    _git("clone", "-q", str(origin), str(repo), cwd=root)
    return repo


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


def a_task(db, *locations, **fields):  # noqa: ANN001, ANN201
    project = projects_svc.create_project(db, name="Everyday")
    for location in locations:
        projects_svc.add_repo(db, project_id=project.id, location=str(location))
    db.commit()  # its folder made
    project_files.save(db, project, AGENTS_DOC, "Run uv sync first.")
    task = tasks_svc.create_task(
        db,
        title="Add a task from anywhere",
        project_id=project.id,
        notes="A window opened with N.",
        acceptance="It opens from any page.",
        **fields,
    )
    task_runs.set_repos(db, task.id, [str(loc) for loc in locations])
    return task


# ---- where it works ----


def test_a_tasks_branch_and_workspace_are_named_after_it(db) -> None:
    task = a_task(db)
    assert task_launch.branch_of(task) == f"task/{task.id}-add-a-task-from-anywhere"
    assert (
        task_launch.workspace_of(task)
        == everyday.work_dir() / f"{task.id}-add-a-task-from-anywhere"
    )


def test_a_repository_on_github_is_cloned_into_repos_once(tmp_path) -> None:
    cloned = []

    def clone(full: str, dest: Path) -> None:
        cloned.append(full)
        (dest / ".git").mkdir(parents=True)

    url = "https://github.com/oscartoromal-ai/everyday-app"
    assert task_launch.main_clone(url, clone) == everyday.repos_dir() / "everyday-app"
    assert task_launch.main_clone(url, clone) == everyday.repos_dir() / "everyday-app"
    assert cloned == ["oscartoromal-ai/everyday-app"]
    repo = a_repo(tmp_path, "local")
    assert task_launch.main_clone(str(repo), clone) == repo
    for nowhere in (str(tmp_path / "missing"), "https://gitlab.com/me/app"):
        with pytest.raises(DomainError):
            task_launch.main_clone(nowhere, clone)


# ---- launching ----


def test_one_repositorys_task_is_launched_in_a_worktree_of_it(db, tmp_path) -> None:
    from app.services import task_files

    repo = a_repo(tmp_path, "app")
    task = a_task(db, repo)
    db.commit()  # its folder, and task.md, made
    task_files.create(db, task, "plan.md")
    runner = FakeRunner()
    run = task_launch.launch(db, task.id, runner)

    brief = runner.briefs[0]
    workspace = task_launch.workspace_of(task)
    # Its files: where they are, and what it holds already.
    folder = task_files.folder_of(task.id)
    assert folder == everyday.projects_dir() / "everyday" / "tasks" / task_files.folder_name(task)
    assert f"The task is {folder / 'task.md'}" in brief.text
    assert f"beside it in {folder}: plan.md." in brief.text
    assert (brief.repo, brief.worktree, brief.branch) == (
        repo,
        workspace,
        task_launch.branch_of(task),
    )
    assert _git("branch", "--show-current", cwd=workspace).strip() == task_launch.branch_of(task)
    # The brief: the task, what done means, the project's context, where, and the report.
    for words in (
        f"task #{task.id}: Add a task from anywhere",
        "A window opened with N.",
        "It opens from any page.",
        "Run uv sync first.",
        str(workspace),
        f"/api/tasks/{task.id}/report",
        "never done",
    ):
        assert words in brief.text
    assert (run.runner, run.run_id, run.state, run.workspace) == (
        "t3",
        "thread-1",
        "working",
        str(workspace),
    )
    assert task.status == TaskStatus.in_progress
    assert task.updates[-1].text == f"Launched on T3 Code, in {Path('work', workspace.name)}."


def test_several_repositories_task_is_launched_in_a_folder_of_their_worktrees(db, tmp_path) -> None:
    app, design = a_repo(tmp_path, "app"), a_repo(tmp_path, "design")
    task = a_task(db, app, design)
    runner = FakeRunner()
    task_launch.launch(db, task.id, runner)
    workspace = task_launch.workspace_of(task)
    brief = runner.briefs[0]
    assert (brief.repo, brief.worktree) == (workspace, None)
    for name in ("app", "design"):
        assert _git("branch", "--show-current", cwd=workspace / name).strip() == brief.branch
        assert f"- {name}: {workspace / name}" in brief.text


def test_what_cannot_be_launched_says_why(db, tmp_path) -> None:
    runner = FakeRunner()
    loose = tasks_svc.create_task(db, title="Loose")
    with pytest.raises(DomainError, match="project"):
        task_launch.launch(db, loose.id, runner)
    task = a_task(db)
    with pytest.raises(DomainError, match="repositories"):
        task_launch.launch(db, task.id, runner)
    task = a_task(db, a_repo(tmp_path, "app"))
    task_launch.launch(db, task.id, runner)
    with pytest.raises(DomainError, match="going already"):
        task_launch.launch(db, task.id, runner)
    tasks_svc.set_status(db, task.id, TaskStatus.done)
    runner.state["thread-1"] = RunState.finished
    task.runs[0].state = "finished"
    with pytest.raises(DomainError, match="done"):
        task_launch.launch(db, task.id, runner)


def test_a_runner_refusing_says_so(db, tmp_path) -> None:
    task = a_task(db, a_repo(tmp_path, "app"))
    runner = FakeRunner()
    runner.fail = RunError("T3 Code is not running")
    with pytest.raises(DomainError, match="not running"):
        task_launch.launch(db, task.id, runner)
    assert task.runs == []


def test_launched_again_it_goes_on_on_its_branch(db, tmp_path) -> None:
    repo = a_repo(tmp_path, "app")
    task = a_task(db, repo)
    runner = FakeRunner()
    task_launch.launch(db, task.id, runner)
    workspace = task_launch.workspace_of(task)
    (workspace / "work.txt").write_text("done so far", encoding="utf-8")
    _git("add", ".", cwd=workspace)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "work", cwd=workspace)
    _git("worktree", "remove", str(workspace), cwd=repo)
    task.runs[0].state = "finished"
    task_launch.launch(db, task.id, runner)
    assert (workspace / "work.txt").read_text(encoding="utf-8") == "done so far"
    assert len(task.runs) == 2


# ---- following ----


def test_a_run_moves_its_task_with_it(db, tmp_path, github) -> None:
    task = a_task(db, a_repo(tmp_path, "app"))
    runner = FakeRunner()
    task_launch.launch(db, task.id, runner)
    accounts = fake_account(tmp_path, github, FakeCli({}))
    seen = []
    for state, status in [
        (RunState.waiting, TaskStatus.blocked),
        (RunState.working, TaskStatus.in_progress),
        (RunState.finished, TaskStatus.needs_review),
    ]:
        runner.state["thread-1"] = state
        task_launch.follow(db, {"t3": runner}, accounts, now=datetime(2026, 10, 5, 12))
        seen.append((task.runs[0].state, task.status))
        assert task.status == status
    assert seen[-1] == ("finished", TaskStatus.needs_review)
    assert [u.text for u in task.updates[-2:]] == [
        "The run is waiting on you: an approval, or an answer.",
        "The run finished: ready for your review.",
    ]
    # Finished, it is not asked again.
    runner.state["thread-1"] = RunState.failed
    task_launch.follow(db, {"t3": runner}, accounts)
    assert task.runs[0].state == "finished"


def test_a_runner_that_cannot_answer_leaves_its_runs_as_they_were(db, tmp_path, github) -> None:
    task = a_task(db, a_repo(tmp_path, "app"))
    runner = FakeRunner()
    task_launch.launch(db, task.id, runner)
    runner.fail = RunError("T3 Code is not running")
    task_launch.follow(db, {"t3": runner}, fake_account(tmp_path, github, FakeCli({})))
    assert (task.runs[0].state, task.runs[0].check_error) == ("working", "T3 Code is not running")


def test_the_pull_requests_its_branch_made_are_linked(db, tmp_path, github) -> None:
    url = "https://github.com/oscartoromal-ai/everyday-app"
    task = a_task(db)
    projects_svc.add_repo(db, project_id=task.project_id, location=url)
    task_runs.set_repos(db, task.id, [url])

    def clone(full: str, dest: Path) -> None:
        _git("clone", "-q", str(a_repo(tmp_path, "origin-app")), str(dest), cwd=tmp_path)

    runner = FakeRunner()
    task_launch.launch(db, task.id, runner, clone=clone)
    github.public = {"oscartoromal-ai/everyday-app"}
    github.branch_pulls[("oscartoromal-ai/everyday-app", task_launch.branch_of(task))] = [
        {"number": 41, "html_url": f"{url}/pull/41"},
    ]
    task_launch.follow(db, {"t3": runner}, fake_account(tmp_path, github, FakeCli({})))
    assert [p.url for p in task.pull_requests] == [f"{url}/pull/41"]


def test_a_settled_tasks_worktrees_go_their_branches_stay(db, tmp_path, github) -> None:
    repo = a_repo(tmp_path, "app")
    task = a_task(db, repo)
    runner = FakeRunner()
    task_launch.launch(db, task.id, runner)
    workspace = task_launch.workspace_of(task)
    runner.state["thread-1"] = RunState.finished
    tasks_svc.set_status(db, task.id, TaskStatus.done)
    task_launch.follow(db, {"t3": runner}, fake_account(tmp_path, github, FakeCli({})))
    assert not workspace.exists() and task.runs[0].cleaned
    assert task_launch.branch_of(task) in _git("branch", "--list", cwd=repo)


# ---- through the API and the page ----


def test_the_api_launches_a_task(client, db, tmp_path, monkeypatch) -> None:
    from app.api import tasks as tasks_api

    runner = FakeRunner()
    monkeypatch.setattr(tasks_api, "get_runner", lambda name=None: runner)
    task = a_task(db, a_repo(tmp_path, "app"))
    db.commit()
    answer = client.post(f"/api/tasks/{task.id}/launch", json={})
    assert answer.status_code == 200
    assert answer.json()["runs"][0]["state"] == "working"
    assert client.post(f"/api/tasks/{task.id}/launch", json={}).status_code == 422


def test_the_page_launches_a_task_and_shows_its_runs(client, db, tmp_path, monkeypatch) -> None:
    from app.ui import task_run as ui_task_run

    runner = FakeRunner()
    asked: list[str | None] = []
    monkeypatch.setattr(
        ui_task_run, "get_runner", lambda name=None: asked.append(name) or runner
    )
    task = a_task(db, a_repo(tmp_path, "app"))
    db.commit()
    page = client.get(f"/tasks/{task.id}").text
    # herdr's first, T3 Code offered beside it.
    assert "Launch on herdr" in page and "or on T3 Code" in page
    launched = client.post(f"/ui/tasks/{task.id}/launch", data={"runner": "t3"})
    assert launched.headers["HX-Refresh"] == "true"
    assert asked == ["t3"]
    page = client.get(f"/tasks/{task.id}").text
    assert "Launch again on herdr" in page and "It has a run going." in page
    assert "or on T3 Code" not in page
    assert 'class="chip running">Working' in page
