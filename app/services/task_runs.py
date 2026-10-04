"""A task's work, as an agent does it (SPEC.md, Agent runs): the
repositories it is worked in, what done means (its acceptance criteria) and
what came of it (its outcome), its pull requests, and the updates reported
as it went.

Agents report through report() (the API's POST /api/tasks/<id>/report, and
MCP's report_task): a note, the outcome, its pull requests, and how far it
got, never further than needs review. Done is the app's to say: a task
whose pull requests are all merged on GitHub is done (check_pull_requests,
a job), and one without any is done when Oscar says so.

GitHub is anything shaped as Accounts, so tests stand in a fake.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    GitHubLink,
    PullRequestState,
    Repository,
    Task,
    TaskPullRequest,
    TaskRepo,
    TaskStatus,
    TaskUpdate,
)
from app.services import DomainError
from app.services import tasks as tasks_svc
from app.services.syncing import Syncing
from app.sources.github import GitHub, GitHubError

log = logging.getLogger(__name__)

# How far an agent takes a task: never to done or cancelled, which are the
# app's (its pull requests merged) and Oscar's to say.
AGENT_STATUSES = (TaskStatus.in_progress, TaskStatus.blocked, TaskStatus.needs_review)

# A task finished or let go: its pull requests are not checked again.
SETTLED = (TaskStatus.done, TaskStatus.cancelled)


def _task(db: Session, task_id: int) -> Task:
    return tasks_svc.get_task(db, task_id)


# ---- its repositories ----


def project_locations(task: Task) -> list[str]:
    """Where its project's repositories are, in the project's order."""
    return [r.location for r in task.project.repos] if task.project else []


def set_repo(db: Session, task_id: int, location: str, on: bool) -> Task:
    """One of its project's repositories added to the task's, or taken off."""
    task = _task(db, task_id)
    location = location.strip()
    kept = next((r for r in task.repos if r.location == location), None)
    if on and kept is None:
        if location not in project_locations(task):
            raise DomainError(f"{location} is not one of the repositories of the task's project")
        task.repos.append(TaskRepo(location=location))
    elif not on and kept is not None:
        task.repos.remove(kept)
    db.flush()
    return task


def set_repos(db: Session, task_id: int, locations: list[str]) -> Task:
    """The task's repositories, all at once: some of its project's."""
    task = _task(db, task_id)
    wanted = list(dict.fromkeys(loc.strip() for loc in locations if loc.strip()))
    stray = [loc for loc in wanted if loc not in project_locations(task)]
    if stray:
        raise DomainError(f"{stray[0]} is not one of the repositories of the task's project")
    task.repos[:] = [
        next((r for r in task.repos if r.location == loc), None) or TaskRepo(location=loc)
        for loc in wanted
    ]
    db.flush()
    return task


# ---- its pull requests ----

# A pull request as written: its URL on GitHub, or owner/name#number.
_PR_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+)/pull/(\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)
_PR_REF = re.compile(r"^([A-Za-z0-9-]+/[A-Za-z0-9._-]+)#(\d+)$")


def parse_pull_request(text: str) -> tuple[str, int]:
    """(owner/name, number) of a pull request written as its URL on GitHub
    or as owner/name#number."""
    text = text.strip()
    found = _PR_URL.match(text) or _PR_REF.match(text)
    if not found:
        raise DomainError(
            f"Not a pull request on GitHub: {text or 'nothing'}. "
            "Write its URL, or owner/name#number"
        )
    return found[1], int(found[2])


def add_pull_request(db: Session, task_id: int, text: str) -> TaskPullRequest:
    """A pull request of the task's, by its URL; the one it has already
    when it is one of them."""
    task = _task(db, task_id)
    repo, number = parse_pull_request(text)
    kept = next(
        (p for p in task.pull_requests if p.repo.lower() == repo.lower() and p.number == number),
        None,
    )
    if kept is not None:
        return kept
    pr = TaskPullRequest(repo=repo, number=number)
    task.pull_requests.append(pr)
    db.flush()
    return pr


def remove_pull_request(db: Session, pr_id: int) -> Task:
    pr = db.get(TaskPullRequest, pr_id)
    if pr is None:
        raise DomainError(f"Pull request {pr_id} is not one of a task's")
    task = _task(db, pr.task_id)
    task.pull_requests.remove(pr)
    db.flush()
    return task


# ---- what was reported ----


def add_update(db: Session, task: Task, actor: str, text: str) -> TaskUpdate:
    update = TaskUpdate(at=datetime.now(), actor=actor, text=text.strip())
    task.updates.append(update)
    db.flush()
    return update


def report(
    db: Session,
    task_id: int,
    *,
    actor: str,
    status: TaskStatus | None = None,
    note: str | None = None,
    outcome: str | None = None,
    pull_requests: list[str] | None = None,
) -> Task:
    """An agent's word on the task's work: how far it got (in progress,
    blocked, or ready for review: never done), a note, what came of it, and
    its pull requests. All of it checked before any of it is kept."""
    task = _task(db, task_id)
    if status is not None and status not in AGENT_STATUSES:
        raise DomainError(
            "An agent takes a task as far as needs_review: in_progress, blocked or "
            "needs_review. Done is when its pull requests merge, or when Oscar says so"
        )
    prs = [parse_pull_request(text) for text in pull_requests or []]
    for repo, number in prs:
        add_pull_request(db, task_id, f"{repo}#{number}")
    if note and note.strip():
        add_update(db, task, actor, note)
    if outcome is not None:
        task.outcome = outcome.strip()
    if status is not None and task.status not in SETTLED:
        tasks_svc.set_status(db, task_id, status)
    db.flush()
    return task


# ---- done when its pull requests merge ----


class Accounts(Protocol):
    def api(self, link: GitHubLink) -> GitHub: ...

    def anonymous(self) -> GitHub: ...


def _state(raw: dict) -> PullRequestState:
    if raw.get("merged") or raw.get("merged_at"):
        return PullRequestState.merged
    if raw.get("state") == "closed":
        return PullRequestState.closed
    return PullRequestState.draft if raw.get("draft") else PullRequestState.open


def _links_for(db: Session, repo: str) -> list[GitHubLink]:
    """The connected accounts to ask about a repository: those that reach
    it first, then the others still signed in."""
    reaching = db.scalars(
        select(Repository).where(func.lower(Repository.full_name) == repo.lower())
    ).first()
    first = [link for link in (reaching.links if reaching else []) if not link.signed_out]
    rest = [
        link for link in db.scalars(select(GitHubLink).order_by(GitHubLink.id))
        if not link.signed_out and link not in first
    ]
    return first + rest


def _read(db: Session, accounts: Accounts, pr: TaskPullRequest) -> dict:
    """The pull request as GitHub has it, asked as each account that may
    reach its repository in turn, then signed in as none (a public one)."""
    last: GitHubError | None = None
    for link in _links_for(db, pr.repo):
        try:
            with accounts.api(link) as api:
                return api.pull_request(pr.repo, pr.number)
        except GitHubError as exc:
            last = exc
    try:
        with accounts.anonymous() as api:
            return api.pull_request(pr.repo, pr.number)
    except GitHubError as exc:
        raise last or exc from None


def settle(db: Session, task: Task) -> bool:
    """Done, when it has pull requests and every one of them merged. True
    when this made it so."""
    if task.status in SETTLED or not task.pull_requests:
        return False
    if any(p.state != PullRequestState.merged for p in task.pull_requests):
        return False
    tasks_svc.set_status(db, task.id, TaskStatus.done)
    merged = "Its pull request merged" if len(task.pull_requests) == 1 else (
        "All its pull requests merged"
    )
    add_update(db, task, "system", f"{merged}: done.")
    return True


def check_pull_requests(
    db: Session, accounts: Accounts, task_ids: list[int] | None = None, now: datetime | None = None
) -> int:
    """Every open task's pull requests (or those of `task_ids`) read again
    from GitHub, those not merged yet; then each task whose pull requests
    all merged made done. Answers how many tasks that made done."""
    stmt = select(Task).join(Task.pull_requests).where(Task.status.not_in(SETTLED)).distinct()
    if task_ids is not None:
        stmt = stmt.where(Task.id.in_(task_ids))
    done = 0
    for task in db.scalars(stmt).all():
        for pr in task.pull_requests:
            if pr.state == PullRequestState.merged:
                continue
            try:
                raw = _read(db, accounts, pr)
            except GitHubError as exc:
                pr.check_error = str(exc)
                log.info("Pull request %s#%s not read: %s", pr.repo, pr.number, exc)
            else:
                pr.state, pr.title, pr.check_error = _state(raw), raw.get("title") or "", ""
            pr.checked_at = now or datetime.now()
        db.flush()
        done += settle(db, task)
    db.flush()
    return done


checking = Syncing("pull-requests")


def run_check(
    factory: Callable[[], Session], accounts: Accounts, task_ids: list[int] | None = None
) -> None:
    """A check in its own session, committed: for a thread."""
    with factory() as db:
        db.info["actor"] = "system"
        done = check_pull_requests(db, accounts, task_ids)
        db.commit()
    if done:
        log.info("Pull requests merged: %d task(s) done", done)
