import json
import os
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.desktop import update_router
from app.desktop.update import Updater, UpdateState


def git(repo, *args) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.test", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def commit(repo, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    return path


def updater_at(repo, sha, tmp_path) -> Updater:
    updater = Updater(sha, repo, tmp_path / "data" / "update.json")
    updater._checked = float("-inf")
    return updater


def test_nothing_to_do_while_the_installed_commit_is_the_latest(repo, tmp_path) -> None:
    installed = commit(repo, "a")
    assert updater_at(repo, installed, tmp_path).state() is None


def test_a_newer_commit_is_ready_to_install(repo, tmp_path) -> None:
    installed = commit(repo, "a")
    latest = commit(repo, "b")
    state = updater_at(repo, installed, tmp_path).state()
    assert state == UpdateState("ready", installed[:7], latest[:7])


def test_uncommitted_work_is_not_an_update(repo, tmp_path) -> None:
    installed = commit(repo, "a")
    (repo / "a").write_text("half done", encoding="utf-8")
    assert updater_at(repo, installed, tmp_path).state() is None


def test_starting_runs_the_repos_script_on_the_latest_commit(repo, tmp_path, monkeypatch) -> None:
    installed = commit(repo, "a")
    latest = commit(repo, "b")
    started = []

    class FakeProcess:
        pid = os.getpid()  # alive while the test runs

    real_popen = subprocess.Popen

    def popen(args, **kwargs):  # noqa: ANN001, ANN202
        if args[0] != "powershell.exe":  # its git lookups run for real
            return real_popen(args, **kwargs)
        started.append(args)
        return FakeProcess()

    monkeypatch.setattr("app.desktop.update.subprocess.Popen", popen)
    updater = updater_at(repo, installed, tmp_path)

    state = updater.start()

    assert state.state == "updating" and state.latest == latest[:7]
    (args,) = started
    assert args[args.index("-File") + 1] == str(repo / "desktop" / "update.ps1")
    assert args[args.index("-Sha") + 1] == latest
    status = json.loads(updater.status_path.read_text(encoding="utf-8"))
    assert status == {"state": "updating", "sha": latest, "pid": os.getpid()}
    # A second press starts nothing more.
    assert updater.start().state == "updating"
    assert len(started) == 1


def test_an_update_whose_script_is_gone_has_failed(repo, tmp_path) -> None:
    installed = commit(repo, "a")
    latest = commit(repo, "b")
    updater = updater_at(repo, installed, tmp_path)
    updater._write_status({"state": "updating", "sha": latest, "pid": 999999})
    assert updater.state().state == "failed"


def test_a_failure_says_where_its_log_is(repo, tmp_path) -> None:
    installed = commit(repo, "a")
    latest = commit(repo, "b")
    updater = updater_at(repo, installed, tmp_path)
    # As update.ps1 writes it: UTF-8 with a byte-order mark.
    updater.status_path.parent.mkdir(parents=True)
    updater.status_path.write_text(
        json.dumps({"state": "failed", "sha": latest, "log": "C:/logs/update.log"}),
        encoding="utf-8-sig",
    )
    assert updater.state() == UpdateState("failed", installed[:7], latest[:7], "C:/logs/update.log")


def test_a_failure_is_forgotten_once_the_repo_is_back_at_the_installed_commit(
    repo, tmp_path
) -> None:
    installed = commit(repo, "a")
    latest = commit(repo, "b")
    updater = updater_at(repo, installed, tmp_path)
    updater._write_status({"state": "failed", "sha": latest})
    git(repo, "reset", "-q", "--hard", installed)
    assert updater.state() is None
    assert not updater.status_path.exists()


def test_the_new_app_settles_the_update_that_installed_it(repo, tmp_path) -> None:
    installed = commit(repo, "a")
    updater = updater_at(repo, installed, tmp_path)
    updater._write_status({"state": "updating", "sha": installed, "pid": 999999})
    updater.settle()
    assert not updater.status_path.exists()


class FakeUpdater:
    def __init__(self, state) -> None:  # noqa: ANN001
        self._state = state
        self.started = False

    def state(self):  # noqa: ANN201
        return self._state

    def start(self):  # noqa: ANN201
        self.started = True
        self._state = UpdateState("updating", "1111111", "2222222")
        return self._state


def button(state, method="get") -> tuple[str, FakeUpdater]:  # noqa: ANN001
    updater = FakeUpdater(state)
    app = FastAPI()
    app.include_router(update_router(updater))
    response = getattr(TestClient(app), method)("/ui/desktop/update")
    assert response.status_code == 200
    return response.text, updater


def test_the_button_offers_the_latest_commit() -> None:
    html, _ = button(UpdateState("ready", "1111111", "2222222"))
    assert 'data-update="ready"' in html and ">Update<" in html
    assert "2222222" in html and "1111111" in html
    assert 'hx-post="/ui/desktop/update"' in html


def test_pressing_it_starts_the_update_and_watches_it() -> None:
    html, updater = button(UpdateState("ready", "1111111", "2222222"), method="post")
    assert updater.started
    assert 'data-update="updating"' in html and "Updating…" in html
    assert 'hx-trigger="every 4s"' in html


def test_a_failed_update_offers_a_retry_and_its_log() -> None:
    html, _ = button(UpdateState("failed", "1111111", "2222222", "C:/logs/update.log"))
    assert "Update failed" in html and "Retry" in html and "C:/logs/update.log" in html


def test_no_button_when_there_is_nothing_to_update() -> None:
    html, _ = button(None)
    assert html.strip() == ""
