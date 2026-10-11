import contextlib
import hashlib
import io
import json
import os
import threading
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.desktop import update, update_router
from app.desktop.update import Updater, UpdateState

REPO = "oscartoromal-ai/everyday-app"
API = f"https://api.github.com/repos/{REPO}"
TOKEN = "github_pat_updates"


def sha_of(n: int) -> str:
    return hashlib.sha1(str(n).encode()).hexdigest()


def zipped(sha: str, info: dict | None = None) -> bytes:
    """A version's folder zipped, as GitHub's release build zips it."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zipped:
        zipped.writestr("Personal Calendar.exe", b"app")
        zipped.writestr("_internal/build-info.json", json.dumps(info or {"sha": sha}))
        zipped.writestr("_internal/app/__init__.py", "")
    return out.getvalue()


class FakeGitHub:
    """GitHub's API for the app's repo, which only TOKEN may see: master's
    line of commits, and a release for some of them, each with its version
    zipped and its release.json, the latest last."""

    def __init__(self) -> None:
        self.commits: list[str] = []
        self.releases: list[dict] = []
        self.files: dict[int, bytes] = {}
        self.requests: list[str] = []
        self.down = False

    def commit(self) -> str:
        self.commits.append(sha_of(len(self.commits)))
        return self.commits[-1]

    def release(self, sha: str, archive: bytes | None = None, digest: str | None = "") -> str:
        archive = zipped(sha) if archive is None else archive
        if digest == "":
            digest = f"sha256:{hashlib.sha256(archive).hexdigest()}"
        assets = []
        for name, data, extra in (
            ("Personal-Calendar-Setup.exe", b"setup", {}),
            (f"app-{sha[:7]}.zip", archive, {"digest": digest}),
            ("release.json", json.dumps({"sha": sha}).encode("utf-8-sig"), {}),
        ):
            asset_id = len(self.files) + 1
            self.files[asset_id] = data
            assets.append(
                {
                    "id": asset_id,
                    "name": name,
                    "size": len(data),
                    "url": f"{API}/releases/assets/{asset_id}",
                    **extra,
                }
            )
        self.releases.append({"tag_name": f"build-{sha[:7]}", "assets": assets})
        return sha

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("no network", request=request)
        auth = request.headers.get("authorization")
        if auth and auth != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"message": "Bad credentials"})
        if auth is None:
            # A private repository, to anyone else.
            return httpx.Response(404, json={"message": "Not Found"})
        path = request.url.path.removeprefix(f"/repos/{REPO}")
        if path == "":
            return httpx.Response(200, json={"full_name": REPO})
        if path == "/releases/latest":
            if not self.releases:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json=self.releases[-1])
        if path.startswith("/releases/assets/"):
            assert request.headers["accept"] == "application/octet-stream"
            return httpx.Response(200, content=self.files[int(path.rsplit("/", 1)[1])])
        if path.startswith("/compare/"):
            base, head = path.removeprefix("/compare/").split("...")
            if base not in self.commits:
                return httpx.Response(404, json={"message": "Not Found"})
            at, to = self.commits.index(base), self.commits.index(head)
            status = "ahead" if to > at else "behind" if to < at else "identical"
            return httpx.Response(200, json={"status": status})
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


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


def updater_at(
    github: FakeGitHub,
    sha: str,
    tmp_path,
    install: Path | None = None,
    token: str | None = TOKEN,
    cli_token: str | None = None,
) -> Updater:
    """The installed app's updater at `sha`, signed in with `token` pasted
    in Settings, having looked at the latest release."""
    token_file = tmp_path / "local" / "github-update-token.txt"
    if token and not token_file.exists():
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token, encoding="utf-8")
    updater = Updater(
        sha,
        REPO,
        tmp_path / "data" / "update.json",
        install or installed_at(tmp_path, f"app-{sha[:7]}"),
        token_file=token_file,
        cli_token=lambda: cli_token,
        transport=httpx.MockTransport(github.handle),
    )
    updater.fetch()
    return updater


def staged_by(updater: Updater) -> UpdateState | None:
    """The update started, once it has downloaded and staged (or failed)."""
    state = updater.start()
    if updater.worker:
        updater.worker.join(60)
    return updater.state() if state else state


def test_nothing_to_do_while_the_installed_commit_is_the_latest_release(github, tmp_path) -> None:
    installed = github.release(github.commit())
    assert updater_at(github, installed, tmp_path).state() is None


def test_a_newer_release_is_ready_to_install(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    state = updater_at(github, installed, tmp_path).state()
    assert state == UpdateState("ready", installed[:7], latest[:7])


def test_a_release_made_later_is_seen_once_looked_at(github, tmp_path) -> None:
    installed = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    assert updater.state() is None
    latest = github.release(github.commit())
    assert updater.state() is None
    updater.fetch()
    assert updater.state() == UpdateState("ready", installed[:7], latest[:7])


def test_drawing_the_button_asks_github_nothing(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    updater_at(github, installed, tmp_path)
    asked = len(github.requests)

    # The next start of the same version, before its first look.
    again = Updater(
        installed,
        REPO,
        tmp_path / "data" / "update.json",
        tmp_path / "Programs",
        transport=httpx.MockTransport(github.handle),
    )
    assert again.state() == UpdateState("ready", installed[:7], latest[:7])
    assert len(github.requests) == asked


def test_a_release_is_read_once_then_only_its_tag_looked_at(github, tmp_path) -> None:
    installed = github.release(github.commit())
    github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    github.requests.clear()
    updater.fetch()
    assert github.requests == [f"/repos/{REPO}/releases/latest"]


def test_a_release_behind_the_installed_commit_is_no_update(github, tmp_path) -> None:
    github.release(github.commit())
    # Installed by hand from a commit past it.
    ahead = github.commit()
    assert updater_at(github, ahead, tmp_path).state() is None


def test_a_version_built_from_a_commit_github_lacks_takes_the_latest_release(
    github, tmp_path
) -> None:
    latest = github.release(github.commit())
    state = updater_at(github, "f" * 40, tmp_path).state()
    assert state == UpdateState("ready", "fffffff", latest[:7])


def test_no_update_before_the_first_release(github, tmp_path) -> None:
    installed = github.commit()
    updater = updater_at(github, installed, tmp_path)
    assert updater.state() is None
    assert not updater.locked


def test_a_release_holding_no_version_is_no_update(github, tmp_path) -> None:
    installed = github.release(github.commit())
    github.releases.append({"tag_name": "build-broken", "assets": []})
    assert updater_at(github, installed, tmp_path).state() is None


def test_without_a_token_github_hides_the_releases_and_settings_asks_for_one(
    github, tmp_path
) -> None:
    installed = github.release(github.commit())
    github.release(github.commit())
    updater = updater_at(github, installed, tmp_path, token=None)

    assert updater.state() is None
    assert updater.locked
    access = updater.access()
    assert access["repo"] == REPO and access["name"] == "everyday-app"
    url = urlsplit(access["token_url"])
    assert url.netloc == "github.com" and url.path == "/settings/personal-access-tokens/new"
    filled = parse_qs(url.query)
    # Fine-grained, the repo's owner's, reading its contents and nothing else.
    assert filled["target_name"] == ["oscartoromal-ai"] and filled["contents"] == ["read"]


def test_a_token_pasted_in_settings_opens_the_releases(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path, token=None)
    assert updater.locked

    updater.keep_token(f"  {TOKEN}\n")

    assert updater.fetch() is None
    assert not updater.locked and updater.access() is None
    assert updater.state() == UpdateState("ready", installed[:7], latest[:7])
    assert updater.token_file.read_text(encoding="utf-8") == TOKEN


def test_without_a_token_pasted_the_github_clis_is_used(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path, token=None, cli_token=TOKEN)
    assert updater.state() == UpdateState("ready", installed[:7], latest[:7])


def test_a_token_github_turns_down_locks_the_updates_out(github, tmp_path) -> None:
    installed = github.release(github.commit())
    github.release(github.commit())
    updater = updater_at(github, installed, tmp_path, token="github_pat_revoked")
    why = updater.fetch()
    assert updater.locked
    assert why == f"GitHub shows {REPO} to no one this computer signs in as."


def test_looking_says_why_github_is_out_of_reach(github, tmp_path) -> None:
    installed = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    github.down = True

    state, why = updater.check()

    assert state is None
    assert why == "Could not reach GitHub. Try again in a moment."
    assert not updater.locked


def test_starting_downloads_the_release_and_stages_it_beside_the_running_version(
    github, tmp_path
) -> None:
    installed = github.release(github.commit())
    before = github.release(github.commit())
    latest = github.release(github.commit())
    install = installed_at(tmp_path, f"app-{installed[:7]}", f"app-{before[:7]}")
    (install / f".staging-app-{before[:7]}").mkdir()
    updater = updater_at(github, installed, tmp_path, install)

    state = updater.start()

    assert state.state == "updating" and state.latest == latest[:7]
    updater.worker.join(60)
    assert updater.state() == UpdateState("staged", installed[:7], latest[:7])
    staged = install / f"app-{latest[:7]}"
    assert updater.staged() == staged / "Personal Calendar.exe"
    assert (staged / "_internal" / "app" / "__init__.py").is_file()
    # The running version stays; the ones before it and a half-staged one go.
    assert sorted(p.name for p in install.iterdir() if p.is_dir()) == sorted(
        [f"app-{installed[:7]}", f"app-{latest[:7]}"]
    )
    assert not (tmp_path / "data" / "update-download").exists()
    assert f"Staged {latest}" in updater.log_path.read_text(encoding="utf-8")


def test_a_second_press_while_it_downloads_starts_nothing_more(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    updater._write_status({"state": "updating", "sha": latest, "pid": os.getpid()})
    assert updater.start().state == "updating"
    assert updater.worker is None


def test_checking_looks_now_and_starts_the_update(github, tmp_path) -> None:
    installed = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    latest = github.release(github.commit())

    state, why = updater.check()

    assert why is None
    assert state == UpdateState("updating", installed[:7], latest[:7])
    updater.worker.join(60)


def test_checking_when_up_to_date_starts_nothing(github, tmp_path) -> None:
    installed = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    assert updater.check() == (None, None)
    assert updater.worker is None


def test_a_download_github_does_not_vouch_for_fails(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit(), digest="sha256:" + "0" * 64)
    install = installed_at(tmp_path, f"app-{installed[:7]}")
    updater = updater_at(github, installed, tmp_path, install)

    state = staged_by(updater)

    assert state == UpdateState("failed", installed[:7], latest[:7], str(updater.log_path))
    assert "its SHA-256 differs" in updater.log_path.read_text(encoding="utf-8")
    assert not (install / f"app-{latest[:7]}").exists()


def test_a_zip_of_another_commit_is_not_staged(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.commit()
    github.release(latest, archive=zipped(latest, info={"sha": installed}))
    install = installed_at(tmp_path, f"app-{installed[:7]}")
    updater = updater_at(github, installed, tmp_path, install)

    assert staged_by(updater).state == "failed"
    assert f"holds no version built from {latest}" in updater.log_path.read_text(encoding="utf-8")
    assert [p.name for p in install.iterdir() if p.is_dir()] == [f"app-{installed[:7]}"]


def test_a_release_without_a_digest_is_checked_by_its_size(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit(), digest=None)
    updater = updater_at(github, installed, tmp_path)
    assert staged_by(updater) == UpdateState("staged", installed[:7], latest[:7])


def stage(updater: Updater, sha: str, folder: Path) -> None:
    """As an update writes it once the release is in its folder."""
    updater._write_status({"state": "staged", "sha": sha, "app": str(folder)})


def test_a_staged_update_offers_restart(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    install = installed_at(tmp_path, f"app-{installed[:7]}", f"app-{latest[:7]}")
    updater = updater_at(github, installed, tmp_path, install)
    stage(updater, latest, install / f"app-{latest[:7]}")

    assert updater.state() == UpdateState("staged", installed[:7], latest[:7])
    # Update again downloads nothing more: Restart is what is left.
    assert updater.start().state == "staged"
    assert updater.worker is None


def test_a_staged_update_whose_folder_is_gone_is_offered_again(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    install = installed_at(tmp_path, f"app-{installed[:7]}")
    updater = updater_at(github, installed, tmp_path, install)
    stage(updater, latest, install / f"app-{latest[:7]}")

    assert updater.staged() is None
    assert updater.state() == UpdateState("ready", installed[:7], latest[:7])
    assert not updater.status_path.exists()


def watch_once(updater: Updater) -> None:
    """The watch's next step, its look due; and the update it started done."""
    updater._fetched = float("-inf")
    updater.tick()
    if updater.worker:
        updater.worker.join(60)


def test_the_watch_starts_the_update_once_a_newer_release_comes(github, tmp_path) -> None:
    installed = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    watch_once(updater)
    assert updater.worker is None

    latest = github.release(github.commit())
    watch_once(updater)

    assert updater.state() == UpdateState("staged", installed[:7], latest[:7])


def test_the_watch_looks_only_every_so_often(github, tmp_path) -> None:
    installed = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    github.release(github.commit())
    updater.tick()
    assert updater.worker is None


def test_the_watch_leaves_a_failed_update_to_oscar_until_another_release(github, tmp_path) -> None:
    installed = github.release(github.commit())
    failed = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    updater._write_status({"state": "failed", "sha": failed})

    watch_once(updater)
    assert updater.worker is None

    latest = github.release(github.commit())
    watch_once(updater)
    assert updater.state() == UpdateState("staged", installed[:7], latest[:7])


def test_retry_downloads_the_release_that_failed(github, tmp_path) -> None:
    installed = github.release(github.commit())
    failed = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    updater._write_status({"state": "failed", "sha": failed})

    assert staged_by(updater) == UpdateState("staged", installed[:7], failed[:7])


def test_a_newer_release_is_staged_in_place_of_the_one_staged(github, tmp_path) -> None:
    installed = github.release(github.commit())
    staged = github.release(github.commit())
    install = installed_at(tmp_path, f"app-{installed[:7]}", f"app-{staged[:7]}")
    updater = updater_at(github, installed, tmp_path, install)
    released = []
    updater.before_build = lambda: released.append(True)
    stage(updater, staged, install / f"app-{staged[:7]}")
    watch_once(updater)
    assert updater.worker is None and released == []

    latest = github.release(github.commit())
    watch_once(updater)

    # What stood by on the staged version let go of it first.
    assert released == [True]
    assert updater.state() == UpdateState("staged", installed[:7], latest[:7])
    assert not (install / f"app-{staged[:7]}").exists()


def test_nothing_is_downloaded_while_a_restart_is_under_way(github, tmp_path) -> None:
    installed = github.release(github.commit())
    staged = github.release(github.commit())
    install = installed_at(tmp_path, f"app-{installed[:7]}", f"app-{staged[:7]}")
    updater = updater_at(github, installed, tmp_path, install)
    stage(updater, staged, install / f"app-{staged[:7]}")

    assert updater.hold() == install / f"app-{staged[:7]}" / "Personal Calendar.exe"
    github.release(github.commit())
    watch_once(updater)
    assert updater.start().state == "staged"
    assert updater.worker is None

    # The restart given up: the newer release is downloaded.
    updater.release()
    watch_once(updater)
    assert updater.worker is not None


def test_nothing_staged_holds_nothing(github, tmp_path) -> None:
    installed = github.release(github.commit())
    github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    assert updater.hold() is None
    watch_once(updater)
    assert updater.worker is not None


def test_a_restart_that_did_not_come_up_has_failed(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    install = installed_at(tmp_path, f"app-{installed[:7]}", f"app-{latest[:7]}")
    updater = updater_at(github, installed, tmp_path, install)
    stage(updater, latest, install / f"app-{latest[:7]}")

    updater.failed("it did not come up", tmp_path / "personal-calendar.log")

    state = updater.state()
    assert state.state == "failed" and state.latest == latest[:7]
    assert state.log == str(tmp_path / "personal-calendar.log")


def test_an_update_whose_app_is_gone_has_failed(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    updater._write_status({"state": "updating", "sha": latest, "pid": 999999})
    assert updater.state().state == "failed"


def test_an_update_its_app_stopped_during_is_started_again_by_the_next(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    updater._write_status({"state": "updating", "sha": latest, "pid": 999999})

    updater.settle()

    assert updater.state() == UpdateState("ready", installed[:7], latest[:7])


def test_a_failure_says_where_its_log_is(github, tmp_path) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    updater._write_status({"state": "failed", "sha": latest, "log": "C:/logs/update.log"})
    assert updater.state() == UpdateState("failed", installed[:7], latest[:7], "C:/logs/update.log")


def test_a_failure_is_forgotten_once_the_latest_release_is_the_installed_one(
    github, tmp_path
) -> None:
    installed = github.release(github.commit())
    latest = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    updater._write_status({"state": "failed", "sha": latest})
    github.releases.pop()
    updater.fetch()
    assert updater.state() is None
    assert not updater.status_path.exists()


def test_the_new_app_settles_the_update_that_installed_it(github, tmp_path) -> None:
    installed = github.release(github.commit())
    updater = updater_at(github, installed, tmp_path)
    updater._write_status({"state": "staged", "sha": installed, "app": "C:/app"})
    updater.settle()
    assert not updater.status_path.exists()


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


def test_a_current_txt_held_a_moment_elsewhere_is_still_written(
    tmp_path, installed_apps, monkeypatch
) -> None:
    # An antivirus or an indexer opening current.txt as it is replaced: the
    # version coming up tries again, rather than fail with the app it
    # replaced already gone.
    install = installed_at(tmp_path, "app-1111111", "app-2222222")
    installed_apps.update(InstallLocation=f"{install}\\", DisplayVersion="0.1.0 (1111111)")
    replace, refused = update.os.replace, []

    def held(source, target) -> None:  # noqa: ANN001
        if len(refused) < 2:
            refused.append(target)
            raise PermissionError(13, "The process cannot access the file", str(target))
        replace(source, target)

    monkeypatch.setattr(update.os, "replace", held)
    monkeypatch.setattr(update.time, "sleep", lambda seconds: None)

    update.take_over(install / "app-2222222" / "Personal Calendar.exe", "0.1.0 (2222222)")

    assert len(refused) == 2
    assert (install / "current.txt").read_text(encoding="utf-8") == "app-2222222"


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


class FakeUpdater:
    repo = REPO

    def __init__(self, state) -> None:  # noqa: ANN001
        self._state = state
        self.started = False
        self.held = False
        self.locked = False
        self.failures: list[str] = []

    def state(self):  # noqa: ANN201
        return self._state

    def access(self):  # noqa: ANN201
        if not self.locked:
            return None
        return {"repo": REPO, "name": "everyday-app", "token_url": "https://github.com/new-token"}

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


def test_the_button_offers_the_latest_release() -> None:
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
    # Its failure imports the server's code (for its log's path), seconds
    # cold on a busy machine: the wait is there only to end a hang.
    assert shell.restarted.wait(60)
    assert shell.restarted_on == Path("C:/staged/Personal Calendar.exe")
    # Nothing is downloaded meanwhile, which would replace what it restarts on.
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
    """Its check finds `found` on GitHub, or cannot reach it (`why`)."""

    def __init__(self, state, found=None, why=None) -> None:  # noqa: ANN001
        super().__init__(state)
        self.found, self.why = found, why
        self.tokens: list[str] = []

    def check(self):  # noqa: ANN201
        if self.why:
            return self._state, self.why
        self._state = self.found
        return self._state, None

    def keep_token(self, token: str) -> None:
        self.tokens.append(token)
        self.locked = False


def check(updater, method="post", path="/ui/desktop/update/check", **kwargs):  # noqa: ANN001, ANN003, ANN201
    app = FastAPI()
    app.include_router(update_router(updater, FakeShell()))
    response = getattr(TestClient(app), method)(path, **kwargs)
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
    assert 'data-update="updating"' in html and "Downloading 2222222" in html
    assert 'hx-get="/ui/desktop/update/check"' in html and "every 4s" in html
    # The rail's button comes along: Updating… there too.
    assert 'id="rail-update"' in html and "Updating…" in html


def test_checking_says_why_github_is_out_of_reach() -> None:
    html = check(CheckingUpdater(None, why="Could not reach GitHub. Try again in a moment."))
    assert 'data-update="unreachable"' in html
    assert "Could not reach GitHub: Could not reach GitHub" in html and "Try again" in html


def test_out_of_reach_still_shows_an_update_under_way() -> None:
    updating = UpdateState("updating", "1111111", "2222222")
    html = check(CheckingUpdater(updating, why="no network"))
    assert 'data-update="updating"' in html and "no network" not in html


def test_settings_offers_restart_once_staged() -> None:
    html = check(CheckingUpdater(UpdateState("staged", "1111111", "2222222")), method="get")
    assert "2222222 is downloaded and ready" in html and "Restart to update" in html
    assert 'hx-post="/ui/desktop/restart"' in html and 'hx-target="#rail-update"' in html
    assert "every 4s" not in html


def test_locked_out_settings_takes_a_token() -> None:
    updater = CheckingUpdater(None, why=f"GitHub shows {REPO} to no one this computer signs in as.")
    updater.locked = True
    html = check(updater, method="get")
    assert 'data-update="locked"' in html and f"Updates come from {REPO} on GitHub" in html
    # Its field and button belong to base.html's form, outside Settings' own.
    assert 'name="token" form="update-access"' in html
    assert 'type="submit" class="btn quiet" data-update-check form="update-access"' in html
    assert 'href="https://github.com/new-token"' in html and "then everyday-app" in html
    assert "Check for updates" not in html


def test_a_token_pasted_is_kept_and_checked() -> None:
    updater = CheckingUpdater(None, found=UpdateState("updating", "1111111", "2222222"))
    updater.locked = True
    html = check(updater, path="/ui/desktop/update/access", data={"token": TOKEN})
    assert updater.tokens == [TOKEN]
    assert 'data-update="updating"' in html and 'id="rail-update"' in html
