"""A task launched as an agent run (SPEC.md, Agent runs), and followed.

Launching gets the task's repositories (each its main clone in the everyday
files' repos/, cloned there first when it is a GitHub repository not there
yet), prepares its workspace in work/<id>-<words>/ on a branch of the
task's own (task/<id>-<words>), and hands a runner the brief: the task, what
done means, the project's context, where to work, and how to report back.
One repository's workspace is its worktree; several's is a folder holding
a worktree of each, all on the branch, which the runner works in as it is.

Following reads each run's state from its runner, never from the agent: a
run working puts its task in progress, one waiting on Oscar blocks it, one
finished asks for his review, one failed blocks it with a word why. The
pull requests its branch made are found on GitHub and linked to the task,
whose merging makes it done (task_runs). A task settled has its worktrees
removed, where nothing in them is uncommitted; their branches stay.

Runners are anything shaped as agent_runs.Runner, so tests stand in fakes.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Task, TaskRun, TaskStatus
from app.services import DomainError, everyday, project_files, task_files, task_runs
from app.services import github as github_svc
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.services.agent_runs import (
    Brief,
    Run,
    RunError,
    Runner,
    RunState,
    _git,
    remove_worktree,
)
from app.services.everyday import words
from app.services.syncing import Syncing
from app.sources.github import GitHubError, find_cli

log = logging.getLogger(__name__)

# The agent systems by name, as Oscar knows them.
RUNNER_NAMES = {"t3": "T3 Code"}


def runner_name(name: str) -> str:
    return RUNNER_NAMES.get(name, name)


def shown(workspace: str | Path) -> str:
    """A workspace's path from the everyday files' folder: work/12-fix-it."""
    try:
        return str(Path(workspace).relative_to(everyday.root()))
    except ValueError:
        return str(workspace)


# A run still going: its runner is asked how it stands.
ACTIVE = (RunState.working, RunState.waiting)

CLONE_TIMEOUT = 600


# ---- where it works ----


def branch_of(task: Task) -> str:
    return f"task/{task.id}-{words(task.title)}"


def workspace_of(task: Task) -> Path:
    return everyday.work_dir() / f"{task.id}-{words(task.title)}"


Cloner = Callable[[str, Path], None]


def _clone(full_name: str, dest: Path) -> None:
    """A GitHub repository cloned, through the GitHub CLI's sign-in when it
    is there, else as git would."""
    gh = find_cli(get_settings().github.cli)
    args = (
        [gh, "repo", "clone", full_name, str(dest)]
        if gh
        else ["git", "clone", f"https://github.com/{full_name}.git", str(dest)]
    )
    done = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=CLONE_TIMEOUT,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if done.returncode:
        raise DomainError(
            f"Could not clone {full_name}: {(done.stderr or done.stdout).strip()[-300:]}"
        )


def main_clone(location: str, clone: Cloner = _clone) -> Path:
    """Where a repository's main clone is: the folder it names, or, for one
    on GitHub, its clone in repos/, made there when it is not yet."""
    path = Path(location.strip())
    if path.is_absolute():
        if not (path / ".git").exists():
            raise DomainError(f"{location} is not a git repository")
        return path
    full = github_svc.full_name_of(location)
    if full is None:
        raise DomainError(f"{location} is neither a folder nor a repository on GitHub")
    dest = everyday.repos_dir() / full.split("/", 1)[1]
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        clone(full, dest)
    return dest


def _base(repo: Path) -> str:
    """What a new branch starts from: origin's default branch as fetched
    now, or, for a repository with no origin, where it stands."""
    try:
        _git("fetch", "--quiet", "origin", cwd=repo)
        head = _git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", cwd=repo).strip()
        return head.removeprefix("refs/remotes/")
    except RunError:
        return "HEAD"


def prepare(repo: Path, worktree: Path, branch: str) -> None:
    """A worktree of the repository on the task's branch: made from origin's
    default branch, or on the branch as it is when a run before made it."""
    if worktree.exists():
        return
    worktree.parent.mkdir(parents=True, exist_ok=True)
    base = _base(repo)
    has = _git("branch", "--list", branch, cwd=repo).strip()
    if has:
        _git("worktree", "add", str(worktree), branch, cwd=repo)
    else:
        _git("worktree", "add", "-b", branch, str(worktree), base, cwd=repo)


Preparer = Callable[[Path, Path, str], None]


# ---- the brief ----


def app_url() -> str:
    return f"http://127.0.0.1:{get_settings().server.port}"


def brief_text(task: Task, where: str, branch: str) -> str:
    project = task.project
    assert project is not None
    folder = project_files.folder_path(project)
    docs = project_files.docs_of(project)
    agents = next((d for d in docs if d.is_agents), None)
    others = [d.path for d in docs if not d.is_agents]
    acceptance = task.acceptance.strip() or (
        "None written: judge it from the task, and say in your outcome how you did."
    )
    context = (
        f"Read it before you start: its documents are files in {folder}"
        + (f" (besides AGENTS.md: {', '.join(others)})" if others else "")
        + ", which you may update when what you learn should outlast this task."
    )
    files_folder = task_files.arrange(task)
    held = task_files.paths(task.id)
    files = (
        f"The task is {files_folder / task_files.TASK_FILE}, and its other files are Markdown "
        f"documents beside it in {files_folder}"
        + (f": {', '.join(held)}" if held else " (none yet)")
        + ". Read them before you start. Write what you make for the task beyond code "
        "(a plan, research, notes) there, as Markdown, not in the repositories: Oscar reads "
        "them on the task's page. Its description, acceptance and outcome are task.md's to "
        "write too; its front matter is the planner's (report status below instead). "
        f"{everyday.root() / 'README.md'} says how the everyday files read."
    )
    report = (
        f"curl -s -X POST {app_url()}/api/tasks/{task.id}/report "
        '-H "Content-Type: application/json" '
        """-d '{"status": "needs_review", "note": "...", "outcome": "...", """
        """"pull_requests": ["https://github.com/owner/repo/pull/1"]}'"""
    )
    return "\n".join(
        [
            f"You are working on a task from Oscar's planner, task #{task.id}: {task.title}",
            "",
            "## The task",
            task.notes.strip() or "(No description beyond its title.)",
            "",
            "## What done means",
            acceptance,
            "",
            "## Its files",
            files,
            "",
            f"## Its project: {project.name}",
            context,
            "",
            "### AGENTS.md",
            (agents.body.strip() if agents and agents.body.strip() else "(Not written yet.)"),
            "",
            "## Where you work",
            where,
            f"Commit there on the branch {branch}, push it, and open a pull request on each "
            f"repository you changed, its description naming this task (Task #{task.id}). "
            "Oscar reviews and merges them; the task is done once they merge.",
            "",
            "## Report back",
            "Report with one HTTP call, any of its fields at once: status (in_progress, blocked "
            "when you need Oscar, needs_review once your pull requests are open; never done), "
            "note (a word on the work as it goes), outcome (what came of it, in Markdown) and "
            "pull_requests (their URLs):",
            report,
        ]
    )


# ---- launching ----


def active_run(task: Task) -> TaskRun | None:
    return next((r for r in task.runs if r.state in ACTIVE), None)


def launch(
    db: Session,
    task_id: int,
    runner: Runner,
    *,
    clone: Cloner = _clone,
    prepare_worktree: Preparer = prepare,
) -> TaskRun:
    """The task handed to an agent through `runner`, in its workspace."""
    task = tasks_svc.get_task(db, task_id)
    if task.project is None:
        raise DomainError("A task is launched in its project: give it one first")
    if not task.repos:
        raise DomainError("Choose the repositories it is worked in first")
    if task.status in task_runs.SETTLED:
        raise DomainError(f"It is {task.status.value.replace('_', ' ')}: nothing to launch")
    if active_run(task) is not None:
        raise DomainError("It has a run going already")
    project_files.refresh(db, task.project)
    clones = [
        (projects_svc.repo_name(r.location), main_clone(r.location, clone)) for r in task.repos
    ]
    branch, workspace = branch_of(task), workspace_of(task)
    if len(clones) == 1:
        name, repo = clones[0]
        prepare_worktree(repo, workspace, branch)
        where = f"A worktree of {name} at {workspace}."
        brief = Brief(task.title, "", repo, workspace, branch)
    else:
        workspace.mkdir(parents=True, exist_ok=True)
        for name, repo in clones:
            prepare_worktree(repo, workspace / name, branch)
        listed = "\n".join(f"- {name}: {workspace / name}" for name, _ in clones)
        where = f"{workspace}, holding a worktree of each repository:\n{listed}"
        brief = Brief(task.title, "", workspace, None, branch)
    brief = Brief(brief.title, brief_text(task, where, branch), brief.repo, brief.worktree, branch)
    try:
        run = runner.launch(brief)
    except RunError as exc:
        raise DomainError(f"{runner.name} could not launch it: {exc}") from exc
    record = TaskRun(
        runner=run.runner,
        run_id=run.id,
        branch=branch,
        workspace=str(workspace),
        state=RunState.working.value,
        started_at=datetime.now(),
    )
    task.runs.append(record)
    if task.status in (TaskStatus.todo, TaskStatus.blocked):
        tasks_svc.set_status(db, task.id, TaskStatus.in_progress)
    task_runs.add_update(
        db, task, "system", f"Launched on {runner_name(runner.name)}, in {shown(workspace)}."
    )
    db.flush()
    return record


# ---- following ----

# A run's state, as its task's: the status it moves the task to, from the
# statuses it moves it from, and what its update says.
FOLLOWS = {
    RunState.working: (
        TaskStatus.in_progress,
        (TaskStatus.todo, TaskStatus.blocked),
        None,
    ),
    RunState.waiting: (
        TaskStatus.blocked,
        (TaskStatus.todo, TaskStatus.in_progress),
        "The run is waiting on you: an approval, or an answer.",
    ),
    RunState.finished: (
        TaskStatus.needs_review,
        (TaskStatus.todo, TaskStatus.in_progress, TaskStatus.blocked),
        "The run finished: ready for your review.",
    ),
    RunState.failed: (
        TaskStatus.blocked,
        (TaskStatus.todo, TaskStatus.in_progress, TaskStatus.needs_review),
        "The run failed.",
    ),
}


def _moved(db: Session, task: Task, state: RunState) -> None:
    if state not in FOLLOWS or task.status in task_runs.SETTLED:
        return
    status, from_, said = FOLLOWS[state]
    if task.status in from_:
        tasks_svc.set_status(db, task.id, status)
    if said:
        task_runs.add_update(db, task, "system", said)


def _link_pull_requests(
    db: Session, accounts: task_runs.Accounts, run: TaskRun, task: Task
) -> None:
    """The pull requests its branch made, on each of its GitHub repositories,
    linked to the task."""
    for repo in task.repos:
        full = github_svc.full_name_of(repo.location)
        if full is None:
            continue
        try:
            found = task_runs.ask(
                db, accounts, full, lambda api, r=full: api.pull_requests_from(r, run.branch)
            )
        except GitHubError as exc:
            log.info("Pull requests from %s on %s not read: %s", run.branch, full, exc)
            continue
        for pr in found:
            if pr.get("html_url"):
                task_runs.add_pull_request(db, task.id, pr["html_url"])


def _clean(run: TaskRun, task: Task) -> None:
    """A settled task's worktrees removed, those with nothing uncommitted."""
    workspace = Path(run.workspace)
    if not workspace.exists():
        run.cleaned = True
        return
    worktrees = (
        [workspace]
        if (workspace / ".git").exists()
        else [p for p in workspace.iterdir() if (p / ".git").exists()]
    )
    left = False
    for worktree in worktrees:
        try:
            common = _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=worktree)
            repo = Path(common.strip()).parent
            left |= not remove_worktree(repo, worktree)
        except RunError as exc:
            log.warning("Worktree %s not removed: %s", worktree, exc)
            left = True
    if not left and workspace.exists() and not any(workspace.iterdir()):
        shutil.rmtree(workspace, ignore_errors=True)
    run.cleaned = not left


def follow(
    db: Session,
    runners: dict[str, Runner],
    accounts: task_runs.Accounts,
    now: datetime | None = None,
) -> None:
    """Every run going asked how it stands, its task moved with it and its
    pull requests linked; the runs of tasks settled cleaned up."""
    now = now or datetime.now()
    going = list(db.scalars(select(TaskRun).where(TaskRun.state.in_([s.value for s in ACTIVE]))))
    by_runner: dict[str, list[TaskRun]] = {}
    for run in going:
        by_runner.setdefault(run.runner, []).append(run)
    for name, runs in by_runner.items():
        runner = runners.get(name)
        if runner is None:
            continue
        try:
            states = runner.states([Run(name, r.run_id) for r in runs])
        except RunError as exc:
            for run in runs:
                run.check_error, run.checked_at = str(exc), now
            continue
        for run in runs:
            state = states.get(run.run_id, RunState.gone)
            run.checked_at, run.check_error = now, ""
            if state.value != run.state:
                run.state = state.value
                _moved(db, db.get(Task, run.task_id), state)
    db.flush()
    # Pull requests from the branches of runs whose task is still open.
    for run in db.scalars(select(TaskRun).where(TaskRun.cleaned.is_(False))):
        task = db.get(Task, run.task_id)
        if task.status not in task_runs.SETTLED:
            _link_pull_requests(db, accounts, run, task)
        elif run.state not in [s.value for s in ACTIVE]:
            _clean(run, task)
    db.flush()


following = Syncing("task-runs")


def run_follow(factory: Callable[[], Session], runners: dict[str, Runner], accounts) -> None:  # noqa: ANN001
    """Following in its own session, committed: for the scheduler."""
    with factory() as db:
        db.info["actor"] = "system"
        follow(db, runners, accounts)
        db.commit()
