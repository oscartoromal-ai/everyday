"""Agent runs (app/services/agent_runs.py) and T3 Code, their first runner."""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.services import agent_runs
from app.services.agent_runs import Brief, Run, RunError, RunState, T3Runner, thread_state
from app.sources.t3 import Connection, T3Error


def test_a_threads_state_is_its_runs() -> None:
    def thread(turn: str | None = None, session: str | None = None, **more) -> dict:  # noqa: ANN003
        return {
            "latestTurn": {"state": turn} if turn else None,
            "session": {"status": session} if session else None,
            **more,
        }

    assert thread_state(None) == RunState.gone
    assert thread_state(thread("completed", archivedAt="2026-10-05T00:00:00Z")) == RunState.gone
    assert thread_state(thread("running", "running", hasPendingApprovals=True)) == RunState.waiting
    assert thread_state(thread("running", "running", hasPendingUserInput=True)) == RunState.waiting
    assert thread_state(thread("running", "running")) == RunState.working
    assert thread_state(thread(None, "starting")) == RunState.working
    assert thread_state(thread()) == RunState.working
    assert thread_state(thread("completed", "ready")) == RunState.finished
    assert thread_state(thread("interrupted", "interrupted")) == RunState.failed
    assert thread_state(thread("error", "error")) == RunState.failed


class FakeWebSocket:
    """T3's socket: answers each request from `answers`, by tag."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.sent: list[dict] = []
        self.inbox: list[dict] = []

    def send(self, text: str) -> None:
        message = json.loads(text)
        self.sent.append(message)
        if message["_tag"] != "Request":
            return
        rid, answer = message["id"], self.answers[message["tag"]]
        # Something for another request first, and a ping, both passed over.
        self.inbox.append({"_tag": "Exit", "requestId": "other", "exit": {"_tag": "Success"}})
        self.inbox.append({"_tag": "Ping"})
        if message["tag"].startswith("orchestration.subscribe"):
            self.inbox.append({"_tag": "Chunk", "requestId": rid, "values": [answer]})
        else:
            self.inbox.append({"_tag": "Exit", "requestId": rid, "exit": answer})

    def recv(self, timeout: float) -> str:
        return json.dumps(self.inbox.pop(0))


def test_a_subscription_is_read_to_its_first_chunk_and_interrupted() -> None:
    snapshot = {"snapshot": {"projects": [], "threads": []}}
    ws = FakeWebSocket({"orchestration.subscribeShell": snapshot})

    assert Connection(ws).snapshot() == {"projects": [], "threads": []}
    assert [m["_tag"] for m in ws.sent] == ["Request", "Pong", "Ack", "Interrupt"]


def test_a_command_refused_is_an_error() -> None:
    refused = {"_tag": "Failure", "cause": "no such project"}
    ws = FakeWebSocket({"orchestration.dispatchCommand": refused})

    with pytest.raises(T3Error, match="no such project"):
        Connection(ws).dispatch({"type": "thread.create"})


class FakeT3:
    def __init__(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        self.dispatched: list[dict] = []

    @contextmanager
    def connect(self, label: str):  # noqa: ANN201
        fake = self

        class Conn:
            def snapshot(self) -> dict:
                return fake.snapshot

            def dispatch(self, command: dict) -> None:
                fake.dispatched.append(command)

        yield Conn()


def test_a_run_is_a_thread_in_its_worktree_on_the_repos_project(tmp_path) -> None:
    repo = tmp_path / "personal-calendar"
    t3 = FakeT3(
        {
            "projects": [
                {"id": "other", "workspaceRoot": str(tmp_path / "pylon")},
                {"id": "app", "workspaceRoot": str(repo).upper()},
            ],
            "threads": [],
        }
    )
    brief = Brief("Improve: x", "Fix x.", repo, tmp_path / "wt", "improve/x")

    run = T3Runner(t3, model="claude-opus-5-5").launch(brief)

    create, turn = t3.dispatched
    assert (create["type"], create["projectId"], create["threadId"]) == (
        "thread.create",
        "app",
        run.id,
    )
    assert (create["branch"], create["worktreePath"]) == ("improve/x", str(tmp_path / "wt"))
    assert create["runtimeMode"] == "full-access"
    assert create["modelSelection"] == {"instanceId": "claudeAgent", "model": "claude-opus-5-5"}
    assert (turn["type"], turn["threadId"], turn["message"]["text"]) == (
        "thread.turn.start",
        run.id,
        "Fix x.",
    )


def test_a_folder_t3_has_no_project_for_gets_one(tmp_path) -> None:
    t3 = FakeT3({"projects": [], "threads": []})
    brief = Brief("Improve: x", "Fix x.", tmp_path, tmp_path / "wt", "improve/x")

    T3Runner(t3).launch(brief)

    project, create, _turn = t3.dispatched
    assert (project["type"], project["workspaceRoot"], project["title"]) == (
        "project.create",
        str(tmp_path),
        tmp_path.name,
    )
    assert create["projectId"] == project["projectId"]


def test_a_folder_worked_in_as_it_is_has_no_worktree(tmp_path) -> None:
    # A task's workspace holding a worktree of each of its repositories.
    t3 = FakeT3({"projects": [{"id": "ws", "workspaceRoot": str(tmp_path)}], "threads": []})
    T3Runner(t3).launch(Brief("Two repos", "Fix x.", tmp_path, None, "task/1-x"))
    create = t3.dispatched[0]
    assert (create["projectId"], create["branch"], create["worktreePath"]) == ("ws", None, None)


def test_runs_states_are_read_from_their_threads() -> None:
    t3 = FakeT3(
        {
            "projects": [],
            "threads": [
                {"id": "a", "latestTurn": {"state": "completed"}, "session": {"status": "ready"}},
            ],
        }
    )

    states = T3Runner(t3).states([Run("t3", "a"), Run("t3", "b")])

    assert states == {"a": RunState.finished, "b": RunState.gone}


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    """A repo with an origin to fetch master from."""
    origin, repo = tmp_path / "origin", tmp_path / "repo"
    origin.mkdir()
    _git("init", "-q", "-b", "master", cwd=origin)
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
    _git("clone", "-q", str(origin), str(repo), cwd=tmp_path)
    return repo


def test_a_runs_worktree_is_on_a_branch_of_its_own_from_master(repo, tmp_path) -> None:
    worktree = tmp_path / "worktrees" / "improve-x"

    agent_runs.prepare_worktree(repo, worktree, "improve/x")

    assert _git("branch", "--show-current", cwd=worktree).strip() == "improve/x"
    # Its worktree goes once there is nothing uncommitted in it; its branch stays.
    (worktree / "notes.txt").write_text("work", encoding="utf-8")
    assert not agent_runs.remove_worktree(repo, worktree)
    (worktree / "notes.txt").unlink()
    assert agent_runs.remove_worktree(repo, worktree)
    assert not worktree.exists()
    assert "improve/x" in _git("branch", "--list", "improve/x", cwd=repo)
    assert not agent_runs.remove_worktree(repo, worktree)


def test_a_branch_already_there_is_not_taken_over(repo, tmp_path) -> None:
    agent_runs.prepare_worktree(repo, tmp_path / "a", "improve/x")

    with pytest.raises(RunError):
        agent_runs.prepare_worktree(repo, tmp_path / "b", "improve/x")


# ---- herdr ----


@pytest.fixture
def herdr(tmp_path):  # noqa: ANN201
    from herdr_fake import FakeHerdr

    fake = FakeHerdr(tmp_path / "fake-herdr.sock")
    yield fake
    fake.stop()


def test_a_run_in_herdr_is_an_agent_in_a_workspace_named_after_its_task(herdr, tmp_path) -> None:
    worktree = tmp_path / "work" / "12-fix-the-build"
    worktree.mkdir(parents=True)
    runner = agent_runs.HerdrRunner(herdr.herdr, model="claude-opus-5-5", agent="claude", args=[])
    brief = Brief("Fix the build", "The brief's words.", tmp_path / "repo", worktree,
                  "task/12-fix-the-build")
    run = runner.launch(brief)
    # The brief beside the worktree, never in it.
    written = tmp_path / "work" / ".briefs" / "12-fix-the-build.md"
    assert written.read_text(encoding="utf-8") == "The brief's words."
    asked = dict(herdr.asked)
    assert asked["workspace.create"] == {
        "cwd": str(worktree), "label": "#12 Fix the build", "focus": False,
    }
    start = asked["agent.start"]
    assert (start["name"], start["kind"]) == ("task-12", "claude")
    assert start["args"] == [
        "--model", "claude-opus-5-5",
        f"Your brief is in {written}: read it first, then do what it says.",
    ]
    assert run == Run("herdr", "term_1")
    # Launched again while its first agent lives: a name of its own.
    runner.launch(brief)
    assert [p["name"] for m, p in herdr.asked if m == "agent.start"] == ["task-12", "task-12-2"]


def test_an_agent_waiting_at_its_first_screen_is_launched(herdr, tmp_path) -> None:
    herdr.refuse["agent.start"] = "agent_not_ready"
    runner = agent_runs.HerdrRunner(herdr.herdr, agent="codex", args=["--full-auto"])
    run = runner.launch(Brief("Fix", "b", tmp_path, None, "main"))
    assert run.id == "term_1"
    start = dict(herdr.asked)["agent.start"]
    # No model for an agent other than Claude; its name from its folder.
    assert start["args"][:1] == ["--full-auto"] and len(start["args"]) == 2
    assert start["name"] == agent_runs.HerdrRunner._agent_name(
        Brief("Fix", "b", tmp_path, None, "main"), set()
    )
    herdr.refuse["agent.start"] = "pane_busy"
    with pytest.raises(RunError):
        runner.launch(Brief("Fix", "b", tmp_path, None, "main"))


def test_runs_states_are_read_from_their_terminals_in_herdr(herdr, tmp_path) -> None:
    working = herdr.workspace("a", str(tmp_path / "a"), agent="claude", status="working")
    blocked = herdr.workspace("b", str(tmp_path / "b"), agent="claude", status="blocked")
    idle = herdr.workspace("c", str(tmp_path / "c"), agent="claude", status="idle")
    shell = herdr.workspace("d", str(tmp_path / "d"))  # its agent gone, back at its shell
    runner = agent_runs.HerdrRunner(herdr.herdr)
    ids = [p["terminal_id"] for p in (working, blocked, idle, shell)] + ["term_gone"]
    states = runner.states([Run("herdr", i) for i in ids])
    assert [states[i] for i in ids] == [
        RunState.working, RunState.waiting, RunState.finished, RunState.finished, RunState.gone,
    ]
    # herdr's server stopped: every terminal went with it.
    stopped = agent_runs.HerdrRunner(agent_runs.Herdr(tmp_path / "no-server.sock"))
    assert stopped.states([Run("herdr", ids[0])]) == {ids[0]: RunState.gone}


def test_an_agent_at_rest_before_its_session_began_is_starting() -> None:
    pane = {"terminal_id": "term_1"}
    starting = {"agent_status": "done", "agent": "claude"}
    assert agent_runs.herdr_state(pane, starting) == RunState.working
    ran = {**starting, "agent_session": {"kind": "id", "value": "abc"}}
    assert agent_runs.herdr_state(pane, ran) == RunState.finished
