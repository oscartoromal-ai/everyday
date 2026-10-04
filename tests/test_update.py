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
def origin(tmp_path):
    """GitHub's copy: its master gets the merged pull requests."""
    path = tmp_path / "origin"
    path.mkdir()
    git(path, "init", "-q", "-b", "master")
    return path


@pytest.fixture
def repo(tmp_path, origin):
    """The checkout the app was built from, with origin as its remote."""
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "master")
    git(path, "remote", "add", "origin", str(origin))
    return path


def updater_at(repo, sha, tmp_path, install=None) -> Updater:
    updater = Updater(sha, repo, tmp_path / "data" / "update.json", install=install)
    updater.fetch()
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


def test_nothing_to_do_while_the_installed_commit_is_the_latest(origin, repo, tmp_path) -> None:
    installed = commit(origin, "a")
    assert updater_at(repo, installed, tmp_path).state() is None


def test_a_newer_commit_is_ready_to_install(origin, repo, tmp_path) -> None:
    installed = commit(origin, "a")
    latest = commit(origin, "b")
    state = updater_at(repo, installed, tmp_path).state()
    assert state == UpdateState("ready", installed[:7], latest[:7])


def test_a_commit_merged_later_is_seen_once_fetched(origin, repo, tmp_path) -> None:
    installed = commit(origin, "a")
    updater = updater_at(repo, installed, tmp_path)
    assert updater.state() is None
    latest = commit(origin, "b")
    updater.fetch()
    assert updater.state() == UpdateState("ready", installed[:7], latest[:7])


def test_the_repos_checkout_is_not_what_it_updates_to(origin, repo, tmp_path) -> None:
    # The checkout's master is stale, with commits of its own that reached
    # origin rebased: updating to it would go back, with an older script.
    stale = commit(repo, "stale")
    installed = commit(origin, "a")
    latest = commit(origin, "b")
    (repo / "stale").write_text("half done", encoding="utf-8")
    state = updater_at(repo, installed, tmp_path).state()
    assert state == UpdateState("ready", installed[:7], latest[:7])
    assert git(repo, "rev-parse", "HEAD") == stale


def test_master_behind_the_installed_commit_is_no_update(origin, repo, tmp_path) -> None:
    commit(origin, "a")
    updater = updater_at(repo, "0" * 40, tmp_path)
    # Installed by hand from a branch ahead of master.
    git(repo, "checkout", "-q", "-b", "branch", "origin/master")
    updater.sha = commit(repo, "b")
    updater._checked = float("-inf")
    assert updater.state() is None


def test_no_update_without_the_remotes_master(repo, tmp_path) -> None:
    git(repo, "remote", "set-url", "origin", str(tmp_path / "nowhere"))
    installed = commit(repo, "a")
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


def test_starting_runs_the_apps_own_script_on_the_latest_commit(
    origin, repo, tmp_path, scripts_started
) -> None:
    installed = commit(origin, "a")
    latest = commit(origin, "b")
    install = installed_at(tmp_path, f"app-{installed[:7]}")
    updater = updater_at(repo, installed, tmp_path, install)

    state = updater.start()

    assert state.state == "updating" and state.latest == latest[:7]
    (args,) = scripts_started
    # The script bundled with the app, not whatever the repo has checked out.
    assert args[args.index("-File") + 1] == str(update.SCRIPT)
    assert args[args.index("-Repo") + 1] == str(repo)
    assert args[args.index("-Sha") + 1] == latest
    # Staged beside the running version.
    assert args[args.index("-Install") + 1] == str(install)
    status = json.loads(updater.status_path.read_text(encoding="utf-8"))
    console = str(tmp_path / "data" / "logs" / "update-console.log")
    assert status == {"state": "updating", "sha": latest, "log": console, "pid": os.getpid()}
    # A second press starts nothing more.
    assert updater.start().state == "updating"
    assert len(scripts_started) == 1


def test_checking_fetches_now_and_starts_the_update(
    origin, repo, tmp_path, scripts_started
) -> None:
    installed = commit(origin, "a")
    updater = updater_at(repo, installed, tmp_path)
    assert updater.state() is None
    # Merged since the last fetch, and looked up moments ago.
    latest = commit(origin, "b")
    assert updater.state() is None

    state, why = updater.check()

    assert why is None
    assert state == UpdateState("updating", installed[:7], latest[:7])
    (args,) = scripts_started
    assert args[args.index("-Sha") + 1] == latest


def test_checking_when_up_to_date_starts_nothing(origin, repo, tmp_path, scripts_started) -> None:
    installed = commit(origin, "a")
    assert updater_at(repo, installed, tmp_path).check() == (None, None)
    assert scripts_started == []


def test_checking_says_why_the_remote_is_out_of_reach(
    origin, repo, tmp_path, scripts_started
) -> None:
    installed = commit(origin, "a")
    updater = updater_at(repo, installed, tmp_path)
    git(repo, "remote", "set-url", "origin", str(tmp_path / "nowhere"))

    state, why = updater.check()

    assert state is None
    assert why and "nowhere" in why
    assert scripts_started == []


def test_a_script_powershell_would_not_run_points_at_why(
    origin, repo, tmp_path, monkeypatch
) -> None:
    installed = commit(origin, "a")
    latest = commit(origin, "b")
    updater = updater_at(repo, installed, tmp_path)

    class EndedProcess:
        pid = 999999

    real_popen = subprocess.Popen

    def popen(args, **kwargs):  # noqa: ANN001, ANN202
        if args[0] != "powershell.exe":  # its git lookups run for real
            return real_popen(args, **kwargs)
        kwargs["stdout"].write(b"update.ps1 : A parameter cannot be found that matches\r\n")
        return EndedProcess()

    monkeypatch.setattr("app.desktop.update.subprocess.Popen", popen)
    updater.start()

    state = updater.state()
    assert state.state == "failed" and state.latest == latest[:7]
    assert "A parameter cannot be found" in Path(state.log).read_text(encoding="utf-8")


def test_the_bundled_script_runs_on_the_repo_it_is_given() -> None:
    # As PowerShell binds what start() passes: an unknown name fails it
    # before its first line, so the log would say nothing.
    out = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-Command",
            f"(Get-Command '{update.SCRIPT}').Parameters.Keys -join ','",
        ],
        capture_output=True, text=True, check=True,
    )
    assert {"Repo", "Status", "Sha", "Install"} <= set(out.stdout.strip().split(","))


def test_an_app_from_before_versions_had_folders_is_updated_by_the_installer(
    origin, repo, tmp_path, scripts_started
) -> None:
    installed = commit(origin, "a")
    commit(origin, "b")
    updater_at(repo, installed, tmp_path).start()
    (args,) = scripts_started
    assert "-Install" not in args


def stage(updater: Updater, sha: str, folder: Path) -> None:
    """As update.ps1 writes it once the build is in its folder."""
    updater.status_path.parent.mkdir(parents=True, exist_ok=True)
    updater.status_path.write_text(
        json.dumps({"state": "staged", "sha": sha, "app": str(folder)}), encoding="utf-8-sig"
    )


def test_a_staged_update_offers_restart(origin, repo, tmp_path, scripts_started) -> None:
    installed = commit(origin, "a")
    latest = commit(origin, "b")
    install = installed_at(tmp_path, f"app-{installed[:7]}", f"app-{latest[:7]}")
    updater = updater_at(repo, installed, tmp_path, install)
    stage(updater, latest, install / f"app-{latest[:7]}")

    assert updater.state() == UpdateState("staged", installed[:7], latest[:7])
    assert updater.staged() == install / f"app-{latest[:7]}" / "Personal Calendar.exe"
    # Update again builds nothing more: Restart is what is left.
    assert updater.start().state == "staged"
    assert scripts_started == []


def test_a_staged_update_whose_folder_is_gone_is_offered_again(origin, repo, tmp_path) -> None:
    installed = commit(origin, "a")
    latest = commit(origin, "b")
    install = installed_at(tmp_path, f"app-{installed[:7]}")
    updater = updater_at(repo, installed, tmp_path, install)
    stage(updater, latest, install / f"app-{latest[:7]}")

    assert updater.staged() is None
    assert updater.state() == UpdateState("ready", installed[:7], latest[:7])
    assert not updater.status_path.exists()


def watch_once(updater: Updater) -> None:
    """The watch's next step, its fetch due."""
    updater._fetched = float("-inf")
    updater.tick()


def test_the_watch_starts_the_update_once_master_moves_on(
    origin, repo, tmp_path, scripts_started
) -> None:
    installed = commit(origin, "a")
    updater = updater_at(repo, installed, tmp_path)
    watch_once(updater)
    assert scripts_started == []

    latest = commit(origin, "b")
    watch_once(updater)

    (args,) = scripts_started
    assert args[args.index("-Sha") + 1] == latest
    assert updater.state() == UpdateState("updating", installed[:7], latest[:7])
    # Watching on starts nothing more.
    watch_once(updater)
    assert len(scripts_started) == 1


def test_the_watch_fetches_only_every_so_often(origin, repo, tmp_path, scripts_started) -> None:
    installed = commit(origin, "a")
    updater = updater_at(repo, installed, tmp_path)
    commit(origin, "b")
    updater.tick()
    assert scripts_started == []


def test_the_watch_leaves_a_failed_update_to_oscar_until_master_moves_on(
    origin, repo, tmp_path, scripts_started
) -> None:
    installed = commit(origin, "a")
    failed = commit(origin, "b")
    updater = updater_at(repo, installed, tmp_path)
    updater._write_status({"state": "failed", "sha": failed})

    watch_once(updater)
    assert scripts_started == []

    latest = commit(origin, "c")
    watch_once(updater)
    (args,) = scripts_started
    assert args[args.index("-Sha") + 1] == latest


def test_retry_builds_the_commit_that_failed(origin, repo, tmp_path, scripts_started) -> None:
    installed = commit(origin, "a")
    failed = commit(origin, "b")
    updater = updater_at(repo, installed, tmp_path)
    updater._write_status({"state": "failed", "sha": failed})

    assert updater.start().state == "updating"

    (args,) = scripts_started
    assert args[args.index("-Sha") + 1] == failed


def test_a_newer_master_is_built_in_place_of_the_one_staged(
    origin, repo, tmp_path, scripts_started
) -> None:
    installed = commit(origin, "a")
    staged = commit(origin, "b")
    install = installed_at(tmp_path, f"app-{installed[:7]}", f"app-{staged[:7]}")
    updater = updater_at(repo, installed, tmp_path, install)
    released = []
    updater.before_build = lambda: released.append(True)
    stage(updater, staged, install / f"app-{staged[:7]}")
    watch_once(updater)
    assert scripts_started == [] and released == []

    latest = commit(origin, "c")
    watch_once(updater)

    # What stood by on the staged version let go of it first.
    assert released == [True]
    (args,) = scripts_started
    assert args[args.index("-Sha") + 1] == latest


def test_nothing_is_built_while_a_restart_is_under_way(
    origin, repo, tmp_path, scripts_started
) -> None:
    installed = commit(origin, "a")
    staged = commit(origin, "b")
    install = installed_at(tmp_path, f"app-{installed[:7]}", f"app-{staged[:7]}")
    updater = updater_at(repo, installed, tmp_path, install)
    stage(updater, staged, install / f"app-{staged[:7]}")

    assert updater.hold() == install / f"app-{staged[:7]}" / "Personal Calendar.exe"
    commit(origin, "c")
    watch_once(updater)
    assert updater.start().state == "staged"
    assert scripts_started == []

    # The restart given up: the newer master is built.
    updater.release()
    watch_once(updater)
    assert len(scripts_started) == 1


def test_nothing_staged_holds_nothing(origin, repo, tmp_path, scripts_started) -> None:
    installed = commit(origin, "a")
    commit(origin, "b")
    updater = updater_at(repo, installed, tmp_path)
    assert updater.hold() is None
    watch_once(updater)
    assert len(scripts_started) == 1


def test_a_restart_that_did_not_come_up_has_failed(origin, repo, tmp_path) -> None:
    installed = commit(origin, "a")
    latest = commit(origin, "b")
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


def test_an_update_whose_script_is_gone_has_failed(origin, repo, tmp_path) -> None:
    installed = commit(origin, "a")
    latest = commit(origin, "b")
    updater = updater_at(repo, installed, tmp_path)
    updater._write_status({"state": "updating", "sha": latest, "pid": 999999})
    assert updater.state().state == "failed"


def test_a_failure_says_where_its_log_is(origin, repo, tmp_path) -> None:
    installed = commit(origin, "a")
    latest = commit(origin, "b")
    updater = updater_at(repo, installed, tmp_path)
    # As update.ps1 writes it: UTF-8 with a byte-order mark.
    updater.status_path.parent.mkdir(parents=True)
    updater.status_path.write_text(
        json.dumps({"state": "failed", "sha": latest, "log": "C:/logs/update.log"}),
        encoding="utf-8-sig",
    )
    assert updater.state() == UpdateState("failed", installed[:7], latest[:7], "C:/logs/update.log")


def test_a_failure_is_forgotten_once_master_is_back_at_the_installed_commit(
    origin, repo, tmp_path
) -> None:
    installed = commit(origin, "a")
    latest = commit(origin, "b")
    updater = updater_at(repo, installed, tmp_path)
    updater._write_status({"state": "failed", "sha": latest})
    git(origin, "reset", "-q", "--hard", installed)
    updater.fetch()
    assert updater.state() is None
    assert not updater.status_path.exists()


def test_the_new_app_settles_the_update_that_installed_it(origin, repo, tmp_path) -> None:
    installed = commit(origin, "a")
    updater = updater_at(repo, installed, tmp_path)
    updater._write_status({"state": "updating", "sha": installed, "pid": 999999})
    updater.settle()
    assert not updater.status_path.exists()


class FakeUpdater:
    def __init__(self, state) -> None:  # noqa: ANN001
        self._state = state
        self.started = False
        self.held = False
        self.failures: list[str] = []

    def state(self):  # noqa: ANN201
        return self._state

    def staged(self):  # noqa: ANN201
        staged = self._state and self._state.state == "staged"
        return Path("C:/staged/Personal Calendar.exe") if staged else None

    def hold(self):  # noqa: ANN201
        exe = self.staged()
        self.held = exe is not None
        return exe

    def release(self) -> None:
        self.held = False

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
    # Nothing is built meanwhile, which would replace what it restarts on.
    assert updater.held
    # Should it not come up, the button says so.
    assert updater.failures == ["it did not come up"]


def test_restart_with_nothing_staged_shows_what_there_is() -> None:
    html, updater, shell = button(
        UpdateState("updating", "1111111", "2222222"), method="post", path="/ui/desktop/restart"
    )
    assert 'data-update="updating"' in html
    assert shell.restarted_on is None
    assert not updater.held


def test_a_failed_update_offers_a_retry_and_its_log() -> None:
    html, _, _ = button(UpdateState("failed", "1111111", "2222222", "C:/logs/update.log"))
    assert "Update failed" in html and "Retry" in html and "C:/logs/update.log" in html


def test_no_button_when_there_is_nothing_to_update() -> None:
    html, _, _ = button(None)
    assert html.strip() == ""


class CheckingUpdater(FakeUpdater):
    """Its check finds `found` on the remote, or cannot reach it (`why`)."""

    def __init__(self, state, found=None, why=None) -> None:  # noqa: ANN001
        super().__init__(state)
        self.found, self.why = found, why

    def check(self):  # noqa: ANN201
        if self.why:
            return self._state, self.why
        self._state = self.found
        return self._state, None


def check(updater, method="post"):  # noqa: ANN001, ANN201
    app = FastAPI()
    app.include_router(update_router(updater, FakeShell()))
    response = getattr(TestClient(app), method)("/ui/desktop/update/check")
    assert response.status_code == 200
    return response.text


def test_settings_offers_to_check_for_updates() -> None:
    html = check(CheckingUpdater(None), method="get")
    assert 'id="update-check"' in html and "Check for updates" in html
    assert 'hx-post="/ui/desktop/update/check"' in html
    # Shown with the page, the rail's button is already there.
    assert "hx-swap-oob" not in html


def test_checking_says_when_it_is_up_to_date() -> None:
    html = check(CheckingUpdater(None))
    assert 'data-update="current"' in html and "Up to date" in html
    assert 'id="rail-update"' in html and "hx-swap-oob" in html


def test_checking_starts_downloading_a_newer_version_and_watches_it() -> None:
    html = check(CheckingUpdater(None, found=UpdateState("updating", "1111111", "2222222")))
    assert 'data-update="updating"' in html and "Downloading and building 2222222" in html
    assert 'hx-get="/ui/desktop/update/check"' in html and "every 4s" in html
    # The rail's button comes along: Updating… there too.
    assert 'id="rail-update"' in html and "Updating…" in html


def test_checking_says_why_github_is_out_of_reach() -> None:
    html = check(CheckingUpdater(None, why="fatal: unable to access 'https://github.com/'"))
    assert 'data-update="unreachable"' in html
    assert "Could not reach GitHub: fatal: unable to access" in html and "Try again" in html


def test_out_of_reach_still_shows_an_update_under_way() -> None:
    updating = UpdateState("updating", "1111111", "2222222")
    html = check(CheckingUpdater(updating, why="fatal: no network"))
    assert 'data-update="updating"' in html and "no network" not in html


def test_settings_offers_restart_once_staged() -> None:
    html = check(CheckingUpdater(UpdateState("staged", "1111111", "2222222")), method="get")
    assert "2222222 is downloaded and ready" in html and "Restart to update" in html
    assert 'hx-post="/ui/desktop/restart"' in html and 'hx-target="#rail-update"' in html
    assert "every 4s" not in html
