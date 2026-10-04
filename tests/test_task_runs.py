"""A task's work as an agent does it (SPEC.md, Agent runs): its repositories,
acceptance criteria and outcome, its pull requests and updates; agents'
reports over the API and MCP; and done once its pull requests merge."""

import sqlite3
from datetime import datetime

import pytest
from alembic import command
from fastmcp import Client
from github_fake import (
    LOGIN,
    NAME,
    USER_ID,
    WORK_LOGIN,
    WORK_NAME,
    WORK_USER_ID,
    FakeCli,
    FakeGitHub,
    fake_account,
    repo_payload,
)

from app import migrate
from app.db import get_session_factory
from app.mcp.server import mcp
from app.models import GitHubSource, PullRequestState, Task, TaskStatus
from app.services import DomainError, task_runs
from app.services import github as github_svc
from app.services import history as history_svc
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.ui import task_run as ui_task_run
from app.ui.views import history_ctx

APP = "https://github.com/oscartoromal-ai/everyday-app"
DESIGN = "https://github.com/oscartoromal-ai/design-language"
ME = {"id": USER_ID, "login": LOGIN, "name": NAME}
WORK = {"id": WORK_USER_ID, "login": WORK_LOGIN, "name": WORK_NAME}


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


def a_task(db, **fields) -> Task:  # noqa: ANN001
    project = projects_svc.create_project(db, name="Everyday")
    projects_svc.add_repo(db, project_id=project.id, location=APP)
    projects_svc.add_repo(db, project_id=project.id, location=DESIGN)
    return tasks_svc.create_task(
        db, title="Add a task from anywhere", project_id=project.id, **fields
    )


# ---- its repositories ----


def test_a_task_is_worked_in_some_of_its_projects_repositories(db) -> None:
    task = a_task(db)
    task_runs.set_repo(db, task.id, APP, True)
    task_runs.set_repo(db, task.id, APP, True)  # once
    assert [r.location for r in task.repos] == [APP]
    task_runs.set_repos(db, task.id, [DESIGN, APP])
    assert [r.location for r in task.repos] == [DESIGN, APP]
    task_runs.set_repo(db, task.id, DESIGN, False)
    assert [r.location for r in task.repos] == [APP]
    with pytest.raises(DomainError, match="not one of the repositories"):
        task_runs.set_repo(db, task.id, "https://github.com/me/other", True)
    loose = tasks_svc.create_task(db, title="In no project")
    with pytest.raises(DomainError):
        task_runs.set_repos(db, loose.id, [APP])


# ---- its pull requests ----


@pytest.mark.parametrize(
    ("written", "repo", "number"),
    [
        (
            "https://github.com/oscartoromal-ai/everyday-app/pull/33",
            "oscartoromal-ai/everyday-app",
            33,
        ),
        ("github.com/me/app.js/pull/7/files", "me/app.js", 7),
        ("  me/app#12 ", "me/app", 12),
    ],
)
def test_a_pull_request_is_written_as_its_url_or_its_reference(written, repo, number) -> None:
    assert task_runs.parse_pull_request(written) == (repo, number)


@pytest.mark.parametrize("written", ["", "https://github.com/me/app/issues/3", "me/app", "#3"])
def test_what_is_not_a_pull_request_is_refused(written) -> None:
    with pytest.raises(DomainError, match="Not a pull request"):
        task_runs.parse_pull_request(written)


def test_pull_requests_are_added_once_and_taken_off(db) -> None:
    task = a_task(db)
    pr = task_runs.add_pull_request(db, task.id, f"{APP}/pull/33")
    assert task_runs.add_pull_request(db, task.id, "OscarToromal-AI/everyday-app#33") is pr
    assert (pr.url, pr.state) == (f"{APP}/pull/33", PullRequestState.unknown)
    task_runs.remove_pull_request(db, pr.id)
    assert task.pull_requests == []


# ---- reports ----


def test_an_agent_reports_how_far_it_got_never_done(db) -> None:
    task = a_task(db)
    task_runs.report(
        db,
        task.id,
        actor="agent",
        status=TaskStatus.in_progress,
        note="Started on the window.",
        pull_requests=[f"{APP}/pull/40"],
    )
    task_runs.report(
        db, task.id, actor="agent", status=TaskStatus.needs_review, outcome="  The window is in.  "
    )
    assert task.status == TaskStatus.needs_review
    assert task.outcome == "The window is in."
    assert [p.number for p in task.pull_requests] == [40]
    assert [(u.actor, u.text) for u in task.updates] == [("agent", "Started on the window.")]
    for status in (TaskStatus.done, TaskStatus.cancelled, TaskStatus.todo):
        with pytest.raises(DomainError, match="needs_review"):
            task_runs.report(db, task.id, actor="agent", status=status)
    # Nothing of a refused report is kept: a bad pull request refuses it all.
    with pytest.raises(DomainError):
        task_runs.report(db, task.id, actor="agent", note="More", pull_requests=["nope"])
    assert len(task.updates) == 1


def test_a_settled_task_keeps_its_status_whatever_is_reported(db) -> None:
    task = a_task(db, status=TaskStatus.done)
    task_runs.report(db, task.id, actor="agent", status=TaskStatus.in_progress, note="Late word")
    assert task.status == TaskStatus.done


def test_the_api_takes_an_agents_report_in_one_call(client, db) -> None:
    task = a_task(db)
    db.commit()
    answer = client.post(
        f"/api/tasks/{task.id}/report",
        json={
            "status": "needs_review",
            "note": "Ready.",
            "outcome": "Done in #41.",
            "pull_requests": f"{APP}/pull/41",
        },
    )
    assert answer.status_code == 200
    body = answer.json()
    assert (body["status"], body["outcome"]) == ("needs_review", "Done in #41.")
    assert body["pull_requests"] == [
        {
            "url": f"{APP}/pull/41",
            "repo": "oscartoromal-ai/everyday-app",
            "number": 41,
            "title": "",
            "state": "unknown",
        }
    ]
    # Its history names an agent as its hand.
    steps = history_svc.changes(db, task.id)
    assert steps[0]["actor"] == "agent"
    assert client.post(f"/api/tasks/{task.id}/report", json={"status": "done"}).status_code == 422
    assert client.post(f"/api/tasks/{task.id}/report", json={"colour": "red"}).status_code == 422


def test_the_api_gives_a_tasks_repositories_and_takes_them(client, db) -> None:
    task = a_task(db)
    db.commit()
    patched = client.patch(f"/api/tasks/{task.id}", json={"repos": [APP], "acceptance": "Tested"})
    assert (patched.json()["repos"], patched.json()["acceptance"]) == ([APP], "Tested")
    assert client.get(f"/api/tasks/{task.id}").json()["repos"] == [APP]


async def test_claude_reports_and_plans_over_mcp(app_db) -> None:
    with app_db() as db:
        task = a_task(db)
        db.commit()
        task_id = task.id
    async with Client(mcp) as client:
        planned = (
            await client.call_tool(
                "upsert_tasks",
                {
                    "tasks": [
                        {"task_id": task_id, "acceptance": "It opens with N.", "repos": [DESIGN]},
                    ]
                },
            )
        ).data
        assert (planned[0]["acceptance"], planned[0]["repos"]) == ("It opens with N.", [DESIGN])
        reported = (
            await client.call_tool(
                "report_task",
                {
                    "task_id": task_id,
                    "status": "in_progress",
                    "note": "On it.",
                },
            )
        ).data
        assert reported["status"] == "in_progress"
    with app_db() as db:
        assert [(u.actor, u.text) for u in db.get(Task, task_id).updates] == [("claude", "On it.")]


def test_history_words_the_acceptance_criteria_and_outcome(db) -> None:
    task = a_task(db)
    tasks_svc.update_task(db, task.id, acceptance="Tested")
    db.flush()
    lines = [
        line
        for step in history_ctx(history_svc.changes(db, task.id), datetime.now().date())
        for line in step["lines"]
    ]
    assert "Acceptance criteria written" in lines


# ---- done when its pull requests merge ----


def connected(db, user=ME):  # noqa: ANN001, ANN201
    return github_svc.connect(db, user, GitHubSource.cli)


def test_a_task_is_done_once_its_pull_requests_all_merge(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli())
    connected(db)
    github.repos = [repo_payload(1, "everyday-app")]
    github_svc.sync(db, account)
    task = a_task(db, status=TaskStatus.needs_review)
    github.pull("oscartoromal-ai/everyday-app", 41, title="The window")
    github.pull("oscartoromal-ai/everyday-app", 42, merged=True, state="closed")
    task_runs.add_pull_request(db, task.id, f"{APP}/pull/41")
    task_runs.add_pull_request(db, task.id, f"{APP}/pull/42")

    assert task_runs.check_pull_requests(db, account) == 0
    assert [(p.title, p.state) for p in task.pull_requests] == [
        ("The window", PullRequestState.open),
        ("Pull 42", PullRequestState.merged),
    ]
    assert task.status == TaskStatus.needs_review

    github.pull("oscartoromal-ai/everyday-app", 41, merged=True, state="closed")
    before = len(github.requests)
    assert task_runs.check_pull_requests(db, account) == 1
    # One merged already is not asked for again.
    assert len(github.requests) - before == 1
    assert task.status == TaskStatus.done
    assert task.updates[-1].text == "All its pull requests merged: done."
    # Done, it is not checked again.
    assert task_runs.check_pull_requests(db, account) == 0


def test_a_closed_or_draft_pull_request_keeps_its_task_open(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli())
    github.public = {"oscartoromal-ai/everyday-app"}
    task = a_task(db)
    github.pull("oscartoromal-ai/everyday-app", 1, state="closed")
    github.pull("oscartoromal-ai/everyday-app", 2, draft=True)
    task_runs.add_pull_request(db, task.id, f"{APP}/pull/1")
    task_runs.add_pull_request(db, task.id, f"{APP}/pull/2")
    task_runs.check_pull_requests(db, account)
    assert [p.state for p in task.pull_requests] == [
        PullRequestState.closed,
        PullRequestState.draft,
    ]
    assert task.status == TaskStatus.todo


def test_a_pull_request_is_asked_as_the_account_that_reaches_it(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli({LOGIN: "gho_cli", WORK_LOGIN: "gho_work"}))
    connected(db)
    connected(db, WORK)
    github.work_repos = [repo_payload(9, "board", owner="acme-labs")]
    github_svc.sync(db, account)
    task = a_task(db)
    github.pull("acme-labs/board", 5)
    task_runs.add_pull_request(db, task.id, "acme-labs/board#5")
    task_runs.check_pull_requests(db, account)
    asked = [r for r in github.requests if "/pulls/" in r.url.path]
    assert [r.headers["authorization"] for r in asked] == ["Bearer gho_work"]
    assert task.pull_requests[0].state == PullRequestState.open


def test_a_public_pull_request_is_read_signed_in_as_no_one(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli())
    github.public = {"astral-sh/uv"}
    task = a_task(db)
    github.pull("astral-sh/uv", 9000, merged=True)
    task_runs.add_pull_request(db, task.id, "astral-sh/uv#9000")
    assert task_runs.check_pull_requests(db, account) == 1
    asked = [r for r in github.requests if "/pulls/" in r.url.path]
    assert "authorization" not in asked[-1].headers


def test_a_pull_request_github_will_not_show_says_why(db, tmp_path, github) -> None:
    account = fake_account(tmp_path, github, FakeCli())
    task = a_task(db)
    task_runs.add_pull_request(db, task.id, "someone/private#1")
    task_runs.check_pull_requests(db, account, now=datetime(2026, 10, 4, 12))
    pr = task.pull_requests[0]
    assert pr.state == PullRequestState.unknown
    assert pr.checked_at == datetime(2026, 10, 4, 12)
    assert "Not Found" in pr.check_error


# ---- on the task's page ----


def test_the_page_writes_the_tasks_work(client, db, tmp_path, github) -> None:
    task = a_task(db)
    db.commit()
    page = client.get(f"/tasks/{task.id}").text
    assert 'id="task-run"' in page and "Agent work" in page
    assert 'aria-pressed="false"' in page and ">\n        everyday-app\n" in page

    toggled = client.post(f"/ui/tasks/{task.id}/repos", data={"location": APP, "on": "true"})
    assert 'aria-pressed="true"' in toggled.text
    assert (
        client.post(
            f"/ui/tasks/{task.id}/run", data={"acceptance": "It opens\r\nwith N"}
        ).status_code
        == 204
    )
    db.refresh(task)
    assert task.acceptance == "It opens\nwith N"

    added = client.post(f"/ui/tasks/{task.id}/pull-requests", data={"url": f"{APP}/pull/41"})
    assert "oscartoromal-ai/everyday-app#41" in added.text and "Not read yet" in added.text
    assert (
        client.post(f"/ui/tasks/{task.id}/pull-requests", data={"url": "nope"}).status_code == 422
    )

    github.public = {"oscartoromal-ai/everyday-app"}
    github.pull("oscartoromal-ai/everyday-app", 41, merged=True)
    client.app.dependency_overrides[ui_task_run.get_github] = lambda: fake_account(
        tmp_path, github, FakeCli()
    )
    checked = client.post(f"/ui/tasks/{task.id}/pull-requests/check")
    assert "Merged" in checked.text and checked.headers.get("HX-Refresh") == "true"
    db.refresh(task)
    assert task.status == TaskStatus.done

    pr_id = task.pull_requests[0].id
    removed = client.post(f"/ui/pull-requests/{pr_id}/delete")
    assert "everyday-app#41" not in removed.text


def test_the_job_checks_in_a_session_of_its_own(app_db, tmp_path, github) -> None:
    with app_db() as db:
        task = a_task(db)
        task_runs.add_pull_request(db, task.id, "astral-sh/uv#1")
        db.commit()
        task_id = task.id
    github.public = {"astral-sh/uv"}
    github.pull("astral-sh/uv", 1, merged=True)
    task_runs.run_check(get_session_factory(), fake_account(tmp_path, github, FakeCli()))
    with app_db() as db:
        task = db.get(Task, task_id)
        assert task.status == TaskStatus.done
        assert history_svc.changes(db, task_id)[0]["actor"] == "system"


def test_the_migration_adds_a_tasks_work(tmp_path) -> None:
    path = tmp_path / "app.db"
    command.upgrade(migrate._config(path), "a4c9e2f7b310")  # the revision before
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO tasks (title, notes, status, owner, created_at, status_changed_at) "
            "VALUES ('Old one', '', 'todo', 'oscar', '2026-09-01', '2026-09-01')"
        )
    migrate.upgrade(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT acceptance, outcome FROM tasks").fetchall() == [("", "")]
