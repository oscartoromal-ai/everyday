"""View-model for a task's work as an agent does it, on the task's page
(partials/task_run.html): the repositories it is worked in, what done means
and what came of it, its pull requests as GitHub last had them, and the
updates reported as it went."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.config import get_settings
from app.dates import short_date, upper_first
from app.models import PullRequestState, Task, TaskRun, TaskUpdate
from app.services import projects as projects_svc
from app.services import task_launch, task_runs
from app.ui.views import ACTOR_WORDS

# A pull request's state in words, and its chip's look (app.css, .chip).
PR_STATES = {
    PullRequestState.unknown: ("Not read yet", "queued"),
    PullRequestState.draft: ("Draft", "queued"),
    PullRequestState.open: ("Open", "needs_review"),
    PullRequestState.merged: ("Merged", "running"),
    PullRequestState.closed: ("Closed", "blocked"),
}


# A run's state in words, and its chip's look.
RUN_STATES = {
    "working": ("Working", "running"),
    "waiting": ("Waiting on you", "needs_review"),
    "finished": ("Finished", "queued"),
    "failed": ("Failed", "blocked"),
    "gone": ("Gone", "queued"),
}


def _when(update: TaskUpdate | TaskRun, today: date) -> str:
    at = update.at if isinstance(update, TaskUpdate) else update.started_at
    return f"{upper_first(short_date(at.date(), today))} {at:%H:%M}"


def _why_not(task: Task) -> str:
    """Why it cannot be launched now, or "" when it can."""
    if task.project is None:
        return "A task is launched in its project: give it one."
    if not task.repos:
        return "Choose the repositories it is worked in first."
    if task.status in task_runs.SETTLED:
        return "It is settled: nothing to launch."
    if task_launch.active_run(task) is not None:
        return "It has a run going."
    return ""


def run_ctx(task: Task, today: date) -> dict[str, Any]:
    on = {r.location for r in task.repos}
    locations = task_runs.project_locations(task)
    return {
        "task": task,
        "in_project": task.project is not None,
        # Its project's repositories, each on or not, and any it still names
        # that the project no longer has (taken out of project.toml since).
        "repos": [
            {"location": loc, "name": projects_svc.repo_name(loc), "on": loc in on}
            for loc in locations
        ] + [
            {"location": r.location, "name": projects_svc.repo_name(r.location), "on": True,
             "gone": True}
            for r in task.repos if r.location not in locations
        ],
        "pull_requests": [
            {
                "pr": pr,
                "label": f"{pr.repo}#{pr.number}",
                "state": PR_STATES[pr.state][0],
                "chip": PR_STATES[pr.state][1],
                "error": pr.check_error,
            }
            for pr in task.pull_requests
        ],
        "runs": [
            {
                "state": RUN_STATES.get(r.state, (r.state, "queued"))[0],
                "chip": RUN_STATES.get(r.state, (r.state, "queued"))[1],
                "runner": task_launch.runner_name(r.runner),
                "when": _when(r, today),
                "workspace": task_launch.shown(r.workspace),
                "workspace_full": r.workspace,
                "error": r.check_error,
            }
            for r in reversed(task.runs)
        ],
        "runner": task_launch.runner_name(get_settings().runs.runner),
        "why_not": _why_not(task),
        "updates": [
            {"when": _when(u, today), "who": ACTOR_WORDS.get(u.actor, u.actor), "text": u.text}
            for u in reversed(task.updates)
        ],
    }
