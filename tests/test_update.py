import contextlib
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.desktop import update, update_router
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


def updater_at(repo, sha, tmp_path, install=None) -> Updater:
    updater = Updater(sha, repo, tmp_path / "data" / "update.json", install=install)
    updater._checked = float("-inf")
    return updater


def installed_at(tmp_path, *versions: str) -> Path:
    """An install's folder: its launcher, current.txt naming the first of
    `versions`, and each version's folder with its program."""
    root = tmp_path / "Programs" / "Personal Calendar"
    root.mkdir(parents=True)
    (root / "Personal Calendar.exe").write_bytes(b"launcher")
    (root / "current.txt").write_text(versions[0], encoding="utf-8")
    for version in versions:
        (root / version).mkdir()
        (root / version / "Personal Calendar.exe").write_bytes(b"app")
    return root


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


@pytest.fixture
def scripts_started(monkeypatch) -> list[list[str]]:
    """update.ps1's starts, each its arguments; it does not run."""
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
    return started


def test_starting_runs_the_repos_script_on_the_latest_commit(
    repo, tmp_path, scripts_started
) -> None:
    installed = commit(repo, "a")
    latest = commit(repo, "b")
    install = installed_at(tmp_path, f"app-{installed[:7]}")
    updater = updater_at(repo, installed, tmp_path, install)

    state = updater.start()

    assert state.state == "updating" and state.latest == latest[:7]
    (args,) = scripts_started
    assert args[args.index("-File") + 1] == str(repo / "desktop" / "update.ps1")
    assert args[args.index("-Sha") + 1] == latest
    # Staged beside the running version.
    assert args[args.index("-Install") + 1] == str(install)
    status = json.loads(updater.status_path.read_text(encoding="utf-8"))
    assert status == {"state": "updating", "sha": latest, "pid": os.getpid()}
    # A second press starts nothing more.
    assert updater.start().state == "updating"
    assert len(scripts_started) == 1


def test_an_app_from_before_versions_had_folders_is_updated_by_the_installer(
    repo, tmp_path, scripts_started
) -> None:
    installed = commit(repo, "a")
    commit(repo, "b")
    updater_at(repo, installed, tmp_path).start()
    (args,) = scripts_started
    assert "-Install" not in args


def stage(updater: Updater, sha: str, folder: Path) -> None:
    """As update.ps1 writes it once the build is in its folder."""
    updater.status_path.parent.mkdir(parents=True, exist_ok=True)
    updater.status_path.write_text(
        json.dumps({"state": "staged", "sha": sha, "app": str(folder)}), encoding="utf-8-sig"
    )


def test_a_staged_update_offers_restart(repo, tmp_path, scripts_started) -> None:
    installed = commit(repo, "a")
    latest = commit(repo, "b")
    install = installed_at(tmp_path, f"app-{installed[:7]}", f"app-{latest[:7]}")
    updater = updater_at(repo, installed, tmp_path, install)
    stage(updater, latest, install / f"app-{latest[:7]}")

    assert updater.state() == UpdateState("staged", installed[:7], latest[:7])
    assert updater.staged() == install / f"app-{latest[:7]}" / "Personal Calendar.exe"
    # Update again builds nothing more: Restart is what is left.
    assert updater.start().state == "staged"
    assert scripts_started == []


def test_a_staged_update_whose_folder_is_gone_is_offered_again(repo, tmp_path) -> None:
    installed = commit(repo, "a")
    latest = commit(repo, "b")
    install = installed_at(tmp_path, f"app-{installed[:7]}")
    updater = updater_at(repo, installed, tmp_path, install)
    stage(updater, latest, install / f"app-{latest[:7]}")

    assert updater.staged() is None
    assert updater.state() == UpdateState("ready", installed[:7], latest[:7])
    assert not updater.status_path.exists()


def test_a_restart_that_did_not_come_up_has_failed(repo, tmp_path) -> None:
    installed = commit(repo, "a")
    latest = commit(repo, "b")
    install = installed_at(tmp_path, f"app-{installed[:7]}", f"app-{latest[:7]}")
    updater = updater_at(repo, installed, tmp_path, install)
    stage(updater, latest, install / f"app-{latest[:7]}")

    updater.failed("it did not come up", tmp_path / "personal-calendar.log")

    state = updater.state()
    assert state.state == "failed" and state.latest == latest[:7]
    assert state.log == str(tmp_path / "personal-calendar.log")


@pytest.fixture
def installed_apps(monkeypatch) -> dict:
    """Installed apps' entry for the app, as Inno Setup wrote it."""
    entry = {}
    monkeypatch.setattr(update.winreg, "OpenKey", lambda *args: contextlib.nullcontext("key"))
    monkeypatch.setattr(
        update.winreg, "QueryValueEx", lambda key, name: (entry[name], update.winreg.REG_SZ)
    )
    monkeypatch.setattr(
        update.winreg, "SetValueEx", lambda key, name, _, kind, value: entry.update({name: value})
    )
    return entry


def test_the_version_coming_up_takes_over_the_install(tmp_path, installed_apps) -> None:
    install = installed_at(tmp_path, "app-1111111", "app-2222222")
    installed_apps.update(InstallLocation=f"{install}\\", DisplayVersion="0.1.0 (1111111)")

    update.take_over(install / "app-2222222" / "Personal Calendar.exe", "0.1.0 (2222222)")

    # The launcher starts it from now on; Installed apps lists it.
    assert (install / "current.txt").read_text(encoding="utf-8") == "app-2222222"
    assert installed_apps["DisplayVersion"] == "0.1.0 (2222222)"


def test_a_version_the_launcher_started_is_the_install_already(tmp_path, installed_apps) -> None:
    install = installed_at(tmp_path, "app-2222222")
    installed_apps.update(InstallLocation=f"{install}\\", DisplayVersion="as installed")
    update.take_over(install / "app-2222222" / "Personal Calendar.exe", "0.1.0 (2222222)")
    assert installed_apps["DisplayVersion"] == "as installed"


def test_a_copy_installed_elsewhere_leaves_installed_apps_alone(tmp_path, installed_apps) -> None:
    install = installed_at(tmp_path, "app-1111111", "app-2222222")
    installed_apps.update(InstallLocation="C:\\Programs\\Personal Calendar\\", DisplayVersion="x")
    update.take_over(install / "app-2222222" / "Personal Calendar.exe", "0.1.0 (2222222)")
    assert (install / "current.txt").read_text(encoding="utf-8") == "app-2222222"
    assert installed_apps["DisplayVersion"] == "x"


def test_a_program_outside_an_install_takes_nothing_over(tmp_path) -> None:
    exe = tmp_path / "build" / "dist" / "Personal Calendar" / "Personal Calendar.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"app")
    update.take_over(exe, "0.1.0 (2222222)")
    assert update.install_root(exe) is None
    assert not (exe.parent.parent / "current.txt").exists()


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
        self.failures: list[str] = []

    def state(self):  # noqa: ANN201
        return self._state

    def staged(self):  # noqa: ANN201
        return Path("C:/staged/Personal Calendar.exe") if self._state.state == "staged" else None

    def start(self):  # noqa: ANN201
        self.started = True
        self._state = UpdateState("updating", "1111111", "2222222")
        return self._state

    def failed(self, why, log_path) -> None:  # noqa: ANN001
        self.failures.append(why)


class FakeShell:
    def __init__(self) -> None:
        self.restarted = threading.Event()
        self.restarted_on: Path | None = None

    def restart(self, exe, on_failure) -> None:  # noqa: ANN001
        self.restarted_on = exe
        on_failure("it did not come up")
        self.restarted.set()


def button(state, method="get", path="/ui/desktop/update"):  # noqa: ANN001, ANN201
    updater, shell = FakeUpdater(state), FakeShell()
    app = FastAPI()
    app.include_router(update_router(updater, shell))
    response = getattr(TestClient(app), method)(path)
    assert response.status_code == 200
    return response.text, updater, shell


def test_the_button_offers_the_latest_commit() -> None:
    html, _, _ = button(UpdateState("ready", "1111111", "2222222"))
    assert 'data-update="ready"' in html and ">Update<" in html
    assert "2222222" in html and "1111111" in html
    assert 'hx-post="/ui/desktop/update"' in html


def test_pressing_it_starts_the_update_and_watches_it() -> None:
    html, updater, _ = button(UpdateState("ready", "1111111", "2222222"), method="post")
    assert updater.started
    assert 'data-update="updating"' in html and "Updating…" in html
    assert 'hx-trigger="every 4s"' in html


def test_once_staged_it_offers_restart() -> None:
    html, _, _ = button(UpdateState("staged", "1111111", "2222222"))
    assert 'data-update="staged"' in html and "Restart to update" in html
    assert 'hx-post="/ui/desktop/restart"' in html
    assert "hx-trigger" not in html


def test_pressing_restart_hands_over_to_the_staged_app() -> None:
    html, updater, shell = button(
        UpdateState("staged", "1111111", "2222222"), method="post", path="/ui/desktop/restart"
    )
    assert 'data-update="restarting"' in html and "Restarting…" in html
    assert shell.restarted.wait(5)
    assert shell.restarted_on == Path("C:/staged/Personal Calendar.exe")
    # Should it not come up, the button says so.
    assert updater.failures == ["it did not come up"]


def test_restart_with_nothing_staged_shows_what_there_is() -> None:
    html, _, shell = button(
        UpdateState("updating", "1111111", "2222222"), method="post", path="/ui/desktop/restart"
    )
    assert 'data-update="updating"' in html
    assert shell.restarted_on is None


def test_a_failed_update_offers_a_retry_and_its_log() -> None:
    html, _, _ = button(UpdateState("failed", "1111111", "2222222", "C:/logs/update.log"))
    assert "Update failed" in html and "Retry" in html and "C:/logs/update.log" in html


def test_no_button_when_there_is_nothing_to_update() -> None:
    html, _, _ = button(None)
    assert html.strip() == ""
