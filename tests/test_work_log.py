"""The work seen in herdr, recorded (SPEC.md, Work in herdr): each terminal a
session, filed under the task or project it was for; its spans, Oscar at it
and its agent working or waiting on him; a day's work and a task's; and the
pages and API showing them. herdr is a stand-in answering on a real named
pipe (herdr_fake.py), so the app's own client runs against it."""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from herdr_fake import FakeHerdr
from sqlalchemy import select

from app.models import TaskRun, WorkSession, WorkSpan
from app.services import everyday, task_files, work_log
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc
from app.services.agent_runs import _git
from app.ui import work_view

T0 = datetime(2026, 10, 22, 9, 0, 0)


@pytest.fixture
def herdr(tmp_path):  # noqa: ANN201
    fake = FakeHerdr(tmp_path / "fake-herdr.sock")
    yield fake
    fake.stop()


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float = 5) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def watch(app_db, herdr):  # noqa: ANN201
    """A watcher over the fake herdr, Oscar at its screen while `at_screen`
    says so, and a clock moved by the test: look() looks once."""
    clock = Clock()
    state = {"at_screen": True}
    watcher = work_log.Watcher(app_db, herdr.herdr, lambda: state["at_screen"], 5, now=clock)

    class Watch:
        def look(self, seconds: float = 5) -> None:
            watcher.look()
            clock.tick(seconds)

    w = Watch()
    w.clock, w.state, w.watcher, w.factory = clock, state, watcher, app_db
    return w


def spans(factory) -> list[tuple[str, str, int]]:  # noqa: ANN001
    """Each span: its terminal, its kind, its length in seconds."""
    with factory() as db:
        return sorted(
            (s.session.terminal_id, s.kind, int((s.ended_at - s.started_at).total_seconds()))
            for s in db.scalars(select(WorkSpan))
        )


def test_herdr_is_read_over_its_pipe_and_a_missing_server_is_not_running(herdr, tmp_path):
    herdr.workspace("#3 Fix it", "C:\\code\\app", agent="claude", status="blocked")
    found = work_log.seen(herdr.herdr.snapshot())
    assert [(t.workspace, t.agent, t.status, t.agent_session) for t in found] == [
        ("#3 Fix it", "claude", "blocked", "session-1")
    ]
    from app.sources.herdr import Herdr, NotRunning

    with pytest.raises(NotRunning):
        Herdr(tmp_path / "nothing.sock").snapshot()


def test_a_terminal_is_a_session_and_its_agent_and_oscar_are_spans(watch, herdr) -> None:
    pane = herdr.workspace("scratch", "C:\\code\\app", agent="claude", status="working")
    herdr.focused = pane["pane_id"]
    for _ in range(8):
        watch.look()  # 40 seconds: a flush at 30
    herdr.status(pane["terminal_id"], "blocked")
    watch.state["at_screen"] = False  # Oscar away
    for _ in range(3):
        watch.look()
    herdr.close(pane["terminal_id"])
    watch.look()
    assert spans(watch.factory) == [
        ("term_1", "blocked", 15),
        ("term_1", "working", 40),
        ("term_1", "you", 40),
    ]
    with watch.factory() as db:
        session = db.scalars(select(WorkSession)).one()
        assert (session.agent, session.agent_session, session.title) == (
            "claude", "session-1", "Working on 1",
        )
        assert session.ended_at == T0 + timedelta(seconds=55)


def test_a_gap_ends_what_was_going_on_where_it_was_last_seen(watch, herdr) -> None:
    herdr.workspace("scratch", "C:\\code\\app", agent="claude", status="working")
    watch.look()
    watch.look(seconds=600)  # asleep for ten minutes
    watch.look()
    # The first span ends at its last look; a new one starts on waking.
    assert spans(watch.factory) == [("term_1", "working", 0), ("term_1", "working", 5)]


def test_the_app_started_again_takes_up_the_terminals_still_live(watch, herdr, app_db) -> None:
    herdr.workspace("scratch", "C:\\code\\app", agent="claude", status="working")
    for _ in range(7):
        watch.look()
    again = work_log.Watcher(app_db, herdr.herdr, lambda: False, 5, now=watch.clock)
    again.look()
    with app_db() as db:
        sessions = db.scalars(select(WorkSession)).all()
        assert len(sessions) == 1 and sessions[0].ended_at is None
    assert [s[1] for s in spans(app_db)] == ["working", "working"]


def a_project(db, *locations):  # noqa: ANN001, ANN201
    project = projects_svc.create_project(db, name="Everyday")
    for location in locations:
        projects_svc.add_repo(db, project_id=project.id, location=str(location))
    db.commit()
    return project


def filed(factory) -> dict[str, tuple]:  # noqa: ANN001
    with factory() as db:
        return {
            s.terminal_id: (s.task_id, s.project_id, s.filed_by)
            for s in db.scalars(select(WorkSession))
        }


def test_a_terminal_is_filed_under_the_task_or_project_it_is_for(
    watch, herdr, app_db, tmp_path
) -> None:
    repo = tmp_path / "code" / "app"
    repo.mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "1",
         cwd=repo)
    with app_db() as db:
        project = a_project(db, repo)
        task = tasks_svc.create_task(db, title="Fix the build", project_id=project.id)
        other = tasks_svc.create_task(db, title="Write the docs", project_id=project.id)
        db.commit()
        task_folder = task_files.arrange(task)
        db.commit()
        ids = (task.id, other.id, project.id)
    task_id, other_id, project_id = ids
    branch = tmp_path / "code" / "branch"
    _git("clone", "-q", str(repo), str(branch), cwd=tmp_path)
    _git("checkout", "-q", "-b", f"task/{other_id}-write-the-docs", cwd=branch)
    herdr.workspace(f"#{task_id} by its name", "C:\\elsewhere")
    herdr.workspace("in work", str(everyday.work_dir() / f"{task_id}-fix-the-build" / "app"))
    herdr.workspace("in its files", str(task_folder))
    herdr.workspace("on its branch", str(branch))
    herdr.workspace("in the repo", str(repo / "src"))
    herdr.workspace("nowhere", str(tmp_path))
    watch.look()
    assert filed(app_db) == {
        "term_1": (task_id, project_id, "label"),
        "term_2": (task_id, project_id, "workspace"),
        "term_3": (task_id, project_id, "files"),
        "term_4": (other_id, project_id, "branch"),
        "term_5": (None, project_id, "folder"),
        "term_6": (None, None, ""),
    }


def test_a_run_launched_in_herdr_files_its_terminal_and_oscar_s_filing_stays(
    watch, herdr, app_db, tmp_path
) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Fix the build")
        other = tasks_svc.create_task(db, title="Another")
        db.commit()
        task_id, other_id = task.id, other.id
    pane = herdr.workspace("a run", str(tmp_path))
    loose = herdr.workspace("loose", str(tmp_path))
    watch.look()
    assert filed(app_db)[pane["terminal_id"]] == (None, None, "")
    with app_db() as db:
        db.add(TaskRun(task_id=task_id, runner="herdr", run_id=pane["terminal_id"],
                       branch="b", workspace=str(tmp_path)))
        db.commit()
    for _ in range(6):  # a flush files the unfiled again
        watch.look()
    assert filed(app_db)[pane["terminal_id"]] == (task_id, None, "run")
    with app_db() as db:
        session = db.scalars(
            select(WorkSession).where(WorkSession.terminal_id == loose["terminal_id"])
        ).one()
        work_log.file(db, session.id, other_id)
        db.commit()
    herdr.workspaces[-1]["label"] = f"#{task_id} renamed"
    for _ in range(7):
        watch.look()
    assert filed(app_db)[loose["terminal_id"]] == (other_id, None, "oscar")


def test_a_day_s_work_is_a_line_for_each_thing_worked_on(watch, herdr, app_db) -> None:
    with app_db() as db:
        task = tasks_svc.create_task(db, title="Fix the build")
        db.commit()
        task_id = task.id
    one = herdr.workspace(f"#{task_id} one", "C:\\a", agent="claude", status="working")
    herdr.workspace(f"#{task_id} two", "C:\\b", agent="codex", status="working")
    loose = herdr.workspace("loose", "C:\\c")
    herdr.focused = loose["pane_id"]
    for _ in range(25):  # looks from 9:00:00 to 9:02:00
        watch.look()
    herdr.focused = one["pane_id"]  # at 9:02:05
    for _ in range(19):  # to 9:03:35, written as of the flush at 9:03:30
        watch.look()
    with app_db() as db:
        lines = work_log.day(db, T0.date())
        kinds = [(line.key[0], len(line.sessions)) for line in lines]
        assert kinds == [("session", 1), ("task", 2)]
        loose_line, task_line = lines
        assert round(loose_line.totals.you) == 125
        assert round(task_line.totals.you) == 85 and round(task_line.totals.working) == 420
        assert work_view.totals_words(task_line.totals) == "You 1m · agents 7m"
        # Another day has none of it.
        assert work_log.day(db, T0.date() + timedelta(days=1)) == []


def test_today_s_work_pane_says_herdr_is_not_running(client) -> None:
    html = client.get("/today").text
    assert 'data-pane="work"' in html
    assert "herdr is not running" in html


def test_today_s_work_pane_shows_the_agents_now_and_files_a_terminal(
    client, db, herdr, monkeypatch
) -> None:
    from app.sources import attention

    monkeypatch.setattr(work_view, "herdr", lambda: herdr.herdr)
    # Never the machine's own terminal brought forward.
    monkeypatch.setattr(attention, "bring_forward", lambda programs: True)
    task = tasks_svc.create_task(db, title="Fix the build")
    db.commit()
    blocked = herdr.workspace("#1 x", "C:\\a", agent="claude", status="blocked")
    herdr.workspace("y", "C:\\b", agent="codex", status="working")
    session = WorkSession(terminal_id="term_9", cwd="C:\\loose", started_at=T0, seen_at=T0)
    session.spans.append(
        WorkSpan(kind="you", started_at=datetime.combine(date.today(), datetime.min.time()),
                 ended_at=datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=1))
    )
    db.add(session)
    db.commit()
    html = client.get(f"/ui/work/{date.today()}").text
    # Waiting on Oscar first.
    assert html.index("Waiting on you") < html.index("Working")
    assert "C:\\loose" in html and "You 1h" in html
    assert f'value="#{task.id} Fix the build"' in html
    filed_html = client.post(
        f"/ui/work/sessions/{session.id}/file",
        data={"day": date.today().isoformat(), "task": f"#{task.id} Fix the build"},
    ).text
    assert f'href="/tasks/{task.id}"' in filed_html
    db.refresh(session)
    assert (session.task_id, session.filed_by) == (task.id, "oscar")
    shown = client.post("/ui/work/show", data={"terminal": blocked["terminal_id"]})
    assert shown.status_code == 204
    assert herdr.focused == blocked["pane_id"]
    assert client.post("/ui/work/show", data={"terminal": "term_gone"}).status_code == 422


def test_a_task_s_work_pane_lists_its_sessions(client, db) -> None:
    task = tasks_svc.create_task(db, title="Fix the build")
    db.commit()
    assert "Nothing recorded yet" in client.get(f"/ui/tasks/{task.id}/work").text
    session = WorkSession(
        terminal_id="term_1", cwd="C:\\a", agent="claude", title="Fixing it",
        task_id=task.id, filed_by="label", started_at=T0, seen_at=T0, ended_at=T0,
    )
    session.spans.append(WorkSpan(kind="working", started_at=T0, ended_at=T0 + timedelta(hours=2)))
    db.add(session)
    db.commit()
    html = client.get(f"/ui/tasks/{task.id}/work").text
    assert "claude · Fixing it" in html
    assert "Agents 2h" in html
    assert "found by its herdr workspace&#39;s name" in html
    page = client.get(f"/tasks/{task.id}").text
    assert 'id="side-time"' in page


def test_the_api_gives_a_day_s_work_and_files_a_terminal(client, db) -> None:
    task = tasks_svc.create_task(db, title="Fix the build")
    session = WorkSession(terminal_id="term_1", cwd="C:\\a", started_at=T0, seen_at=T0)
    session.spans.append(WorkSpan(kind="you", started_at=T0, ended_at=T0 + timedelta(minutes=5)))
    db.add(session)
    db.commit()
    day = client.get("/api/work", params={"day": T0.date().isoformat()}).json()
    assert day["lines"] == [
        {
            "task_id": None, "project_id": None, "session_id": session.id,
            "you_seconds": 300, "working_seconds": 0, "blocked_seconds": 0, "sessions": 1,
        }
    ]
    answer = client.patch(f"/api/work/sessions/{session.id}", json={"task_id": task.id})
    assert answer.status_code == 200
    assert (answer.json()["task_id"], answer.json()["filed_by"]) == (task.id, "oscar")
    assert client.patch("/api/work/sessions/999", json={"task_id": None}).status_code == 422


def test_a_place_is_short_to_read() -> None:
    assert work_view.place(str(everyday.root() / "work" / "12-fix")) == str(Path("work", "12-fix"))
    assert work_view.place(str(Path.home() / "code" / "app")) == str(Path("~", "code", "app"))
    assert work_view.hm(30) == "<1m" and work_view.hm(3900) == "1h 5m"
