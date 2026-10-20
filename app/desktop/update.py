"""The installed app updating itself from its repo's releases on GitHub.

Changes reach master through pull requests merged on GitHub, and GitHub
builds each commit master takes into a release of the repo
(.github/workflows/release.yml, with desktop/build.ps1): the installer, for a
machine the app is not on yet; the version's folder zipped (app-<commit>.zip),
for an update; and the version's build-info.json (release.json), naming the
commit it was built from. So every machine updates the same way, with no
repo, git or Python of its own, and an update is never uncommitted work.

The installed app knows the commit it was built from and its repo on GitHub
(build-info.json, written by desktop/build.ps1). It watches the repo's latest
release (tick(), on a thread of its own, app/desktop): it looks every
FETCH_SECONDS, and once that release is past the installed commit it starts
the update itself, so that by the time Oscar looks it is staged. The update
downloads the release's zip, on a thread of its own, and stages it, while the
app carries on. The Update button (the rail's foot,
partials/update_button.html) starts it by hand, should the watch not have,
and retries a failure, which the watch leaves to Oscar until another release
comes. Settings' Check for updates (partials/update_check.html) looks now
rather than at the next look, and starts the update when the release is past
the installed commit.

GitHub shows a private repo's releases only to a token that can read it:
the one pasted in Settings ([github] update_token_file), else the GitHub
CLI's, when it is signed in on the machine. Without one the watch is locked
out, and Settings says so and takes a token.

The install's folder (desktop/installer.iss) holds a launcher, the
`Personal Calendar.exe` its shortcuts start, and each version in a folder of
its own beside it (app-<commit>); the launcher starts the one current.txt
names. Staging puts the new version in its folder beside the running one.
The button then offers Restart: this app hands over to the staged one
(Shell.restart in app/desktop, through the standby it starts ahead,
app/desktop/standby.py), which takes the install as its own once its window
is up (take_over). A newer release while one is staged is staged in its
place.

Its progress lives in a status file in the app's data folder, written as the
update starts, stages or fails; the new app clears it as it starts. What
GitHub last said of the latest release is kept beside it, so that drawing
the Update button asks GitHub nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import sys
import threading
import time
import winreg
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.config import FROZEN, REPO_ROOT
from app.desktop import win32
from app.sources.github import GitHub, GitHubError, GitHubNotFound, GitHubSignedOut

log = logging.getLogger(__name__)

BUILD_INFO = REPO_ROOT / "build-info.json"
# What the install's folder holds besides its versions (desktop/installer.iss).
LAUNCHER = "Personal Calendar.exe"
CURRENT = "current.txt"
# Writes of current.txt tried, before taking over is given up.
TAKE_OVER_TRIES = 10
VERSION_PREFIX = "app-"
# A version being unpacked, beside the others, until it is whole.
STAGING_PREFIX = ".staging-"
# What a release holds besides the installer (.github/workflows/release.yml):
# the version's build-info.json, and its folder zipped, by the folder's name.
RELEASE_INFO = "release.json"
# Inno Setup's entry for the app in Installed apps: its AppId, then _is1.
UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{6C1B0E5A-3F4B-4E8C-9C1D-2B7A5E9F4D21}_is1"
)
# GitHub's page making a token, filled in from what follows the ? (access()).
NEW_TOKEN_URL = "https://github.com/settings/personal-access-tokens/new?"
# How often the watch looks at the latest release, and at the update under way.
FETCH_SECONDS = 60
WATCH_SECONDS = 2


@dataclass(frozen=True)
class UpdateState:
    # "ready" (a newer release to install), "updating" (downloading it),
    # "staged" (unpacked, for Restart), "restarting" or "failed".
    state: str
    installed: str
    latest: str
    log: str | None = None


@dataclass(frozen=True)
class Release:
    """A release to update to: the commit it was built from, and its
    version's folder zipped, as GitHub has it."""

    sha: str
    tag: str
    # The version's folder (app-<commit>), the zip's name but .zip.
    folder: str
    # The zip's, in GitHub's API.
    url: str
    size: int
    # "sha256:<hex>", should GitHub have worked it out.
    digest: str | None = None


class UpdateError(Exception):
    """What the update downloaded is not what the release said."""


def _read_json(path: Path) -> dict | None:
    try:
        # PowerShell writes UTF-8 with a byte-order mark.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def build_info() -> dict | None:
    """What the installed app was built from: its commit and version, its
    repo on GitHub (source), and its checkout when built here by hand
    (repo). None run from the repo."""
    return _read_json(BUILD_INFO) if FROZEN else None


def install_root(exe: Path) -> Path | None:
    """The install's folder, when `exe` is one of its versions."""
    root = exe.parent.parent
    if exe.parent.name.startswith(VERSION_PREFIX) and (root / LAUNCHER).exists():
        return root
    return None


def take_over(exe: Path, version: str) -> None:
    """The version at `exe` made the installed one: the launcher starts it
    from now on, and Installed apps lists its `version`."""
    root = install_root(exe)
    if root is None:
        return
    current = root / CURRENT
    try:
        if current.read_text(encoding="utf-8-sig").strip() == exe.parent.name:
            return
    except OSError:
        pass
    # Whole or not at all, for a launcher reading it meanwhile; tried again
    # a few times, should something else (an antivirus, an indexer) hold it.
    staging = current.with_suffix(".tmp")
    for attempt in range(TAKE_OVER_TRIES):
        try:
            staging.write_text(exe.parent.name, encoding="utf-8")
            os.replace(staging, current)
            break
        except OSError:
            if attempt == TAKE_OVER_TRIES - 1:
                raise
            time.sleep(0.2)
    try:
        access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, access) as key:
            # Only the install Installed apps lists, not a copy elsewhere.
            listed, _ = winreg.QueryValueEx(key, "InstallLocation")
            if Path(listed).resolve() == root.resolve():
                winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
    except OSError:
        log.warning("Could not set the version Installed apps lists", exc_info=True)
    log.info("Took over the install as %s", exe.parent.name)


def cli_token() -> str | None:
    """The GitHub CLI's token on this machine, when it is signed in."""
    from app.config import get_settings
    from app.sources.github import GitHubCli, find_cli

    return GitHubCli(find_cli(get_settings().github.cli)).token()


def _release(latest: dict, info: dict) -> Release | None:
    """The release GitHub has as `latest`, built from what `info` (its
    release.json) says; None should it not hold one zipped version."""
    zips = [
        asset
        for asset in latest.get("assets", [])
        if asset["name"].startswith(VERSION_PREFIX) and asset["name"].endswith(".zip")
    ]
    if len(zips) != 1 or not info.get("sha"):
        return None
    asset = zips[0]
    return Release(
        info["sha"],
        latest["tag_name"],
        asset["name"].removesuffix(".zip"),
        asset["url"],
        asset["size"],
        asset.get("digest"),
    )


def _check(archive: Path, release: Release) -> None:
    """The zip downloaded as GitHub has it, else UpdateError."""
    size = archive.stat().st_size
    if size != release.size:
        raise UpdateError(f"{archive.name} came to {size} bytes, not {release.size}")
    if not release.digest or not release.digest.startswith("sha256:"):
        return
    digest = hashlib.sha256()
    with archive.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    if digest.hexdigest() != release.digest.removeprefix("sha256:"):
        raise UpdateError(f"{archive.name} is not the file GitHub has (its SHA-256 differs)")


class Updater:
    def __init__(
        self,
        sha: str,
        repo: str,
        status_path: Path,
        install: Path,
        *,
        token_file: Path | None = None,
        cli_token: Callable[[], str | None] = lambda: None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.sha = sha
        # The repo on GitHub, owner/name.
        self.repo = repo
        self.status_path = status_path
        # The install's folder, where updates are staged.
        self.install = install
        self.token_file = token_file
        self._cli_token = cli_token
        self._transport = transport
        # What must let go of the staged version before an update replaces
        # it: the standby started on it (app/desktop), whose files are in use.
        self.before_build: Callable[[], None] | None = None
        # GitHub shows the repo to no token this machine has: Settings takes one.
        self.locked = False
        # The latest release's tag as last looked at, and the release to
        # update to then: None while it is not past the installed commit.
        self._tag: str | None = None
        self._release: Release | None = None
        self._remembered = False
        # The token to sign in with, read again once GitHub turns it down.
        self._token: str | None = None
        self._token_read = False
        self._fetched = float("-inf")
        self._fetching = threading.Lock()
        # One start at a time, the watch's or a button's, and none at all
        # while a restart is under way (hold()).
        self._starting = threading.Lock()
        self.held = False
        # The thread downloading and staging the last update started.
        self.worker: threading.Thread | None = None

    @classmethod
    def for_installed_app(cls, status_path: Path) -> Updater | None:
        """The installed app's updater; None run from the repo (always its
        latest code), or for a version that knows no repo on GitHub or no
        install's folder."""
        from app.config import get_settings

        info = build_info()
        install = install_root(Path(sys.executable))
        if not info or not info.get("source") or install is None:
            return None
        return cls(
            info["sha"],
            info["source"],
            status_path,
            install,
            token_file=get_settings().update_token_file,
            cli_token=cli_token,
        )

    def access(self) -> dict | None:
        """What Settings asks for while GitHub shows the releases to no
        token this machine has: the repo, and GitHub's page making a token
        that reads it, filled in. None while it shows them."""
        if not self.locked:
            return None
        owner, name = self.repo.split("/", 1)
        machine = platform.node()
        form = {
            "name": f"Personal Calendar updates ({machine})",
            "description": f"Lets Personal Calendar on {machine} download its updates.",
            "target_name": owner,
            "expires_in": "none",
            "contents": "read",
        }
        return {"repo": self.repo, "name": name, "token_url": NEW_TOKEN_URL + urlencode(form)}

    @property
    def log_path(self) -> Path:
        return self.status_path.parent / "logs" / "update.log"

    @property
    def _known_path(self) -> Path:
        return self.status_path.with_name("update-release.json")

    def _api(self) -> GitHub:
        if not self._token_read:
            self._token = self._kept_token() or self._cli_token() or None
            self._token_read = True
        return GitHub(self._token, transport=self._transport)

    def _kept_token(self) -> str:
        try:
            return self.token_file.read_text(encoding="utf-8").strip() if self.token_file else ""
        except OSError:
            return ""

    def keep_token(self, token: str) -> None:
        """The token pasted in Settings kept for the next looks; none
        pasted, the one kept forgotten."""
        if self.token_file is None:
            return
        if token.strip():
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(token.strip(), encoding="utf-8")
        else:
            self.token_file.unlink(missing_ok=True)
        self._token_read = False

    def fetch(self) -> str | None:
        """The repo's latest release looked at on GitHub, for latest(); why
        not, should GitHub not say. One look at a time: a check waits for
        the background one, then looks again."""
        with self._fetching:
            self._fetched = time.monotonic()
            try:
                with self._api() as api:
                    self._look(api)
            except (GitHubNotFound, GitHubSignedOut) as exc:
                log.warning("GitHub would not show %s's releases: %s", self.repo, exc)
                self.locked = True
                self._token_read = False
                return f"GitHub shows {self.repo} to no one this computer signs in as."
            except (GitHubError, KeyError, ValueError) as exc:
                log.warning("Could not look at %s's releases: %s", self.repo, exc)
                return str(exc) or type(exc).__name__
            self.locked = False
            return None

    def _look(self, api: GitHub) -> None:
        latest = api.latest_release(self.repo)
        tag = latest["tag_name"] if latest else None
        if self._remembered and tag == self._tag:
            return
        release = None
        if latest:
            info = next((a for a in latest.get("assets", []) if a["name"] == RELEASE_INFO), None)
            release = _release(latest, json.loads(api.asset(info["url"]))) if info else None
            if release is None:
                log.warning("The release %s holds no version to update to", tag)
            elif release.sha == self.sha or api.compare(self.repo, self.sha, release.sha) in (
                "behind",
                "identical",
            ):
                # Never back: a release behind the installed commit (one
                # installed by hand from a branch ahead of it) is nothing to
                # update to.
                release = None
        self._remember(tag, release)

    def _remember(self, tag: str | None, release: Release | None) -> None:
        self._tag, self._release, self._remembered = tag, release, True
        known = {"installed": self.sha, "tag": tag, "release": release and asdict(release)}
        try:
            self._known_path.parent.mkdir(parents=True, exist_ok=True)
            self._known_path.write_text(json.dumps(known), encoding="utf-8")
        except OSError:
            log.warning("Could not keep what GitHub said of %s", tag, exc_info=True)

    def check(self) -> tuple[UpdateState | None, str | None]:
        """Check for updates (Settings): the latest release looked at now,
        not at the next look, and the update to a newer one started at once.
        What there is then, and why GitHub could not say."""
        why = self.fetch()
        return (self.state() if why else self.start()), why

    def tick(self) -> None:
        """The watch's step (every WATCH_SECONDS): a look at the latest
        release when one is due, then the update started should it be past
        what is installed, or what is staged."""
        if time.monotonic() - self._fetched >= FETCH_SECONDS:
            self.fetch()
        self.start(automatic=True)

    def latest(self) -> Release | None:
        """The release to update to, as GitHub last said; None while the
        latest is not past the installed commit. A page drawing the Update
        button asks GitHub nothing: until the first look, it is what the
        last one said, while this version is the one installed then."""
        if not self._remembered:
            known = _read_json(self._known_path) or {}
            if known.get("installed") == self.sha:
                try:
                    release = Release(**known["release"]) if known.get("release") else None
                except TypeError:
                    release = None
                self._tag, self._release, self._remembered = known.get("tag"), release, True
        return self._release

    def status(self) -> dict | None:
        return _read_json(self.status_path)

    def staged(self) -> Path | None:
        """The staged version's program, while there is one to restart on."""
        status = self.status() or {}
        if status.get("state") != "staged" or status.get("sha") == self.sha:
            return None
        exe = Path(status.get("app", "")) / LAUNCHER
        return exe if exe.is_file() else None

    def state(self) -> UpdateState | None:
        """What the Update button shows, or None when there is nothing to do."""
        status = self.status()
        release = self.latest()
        if status:
            sha = status.get("sha", "")
            pid = status.get("pid")
            if status.get("state") == "updating" and (pid is None or win32.process_alive(pid)):
                return UpdateState("updating", self.sha[:7], sha[:7])
            if status.get("state") == "staged":
                if self.staged():
                    return UpdateState("staged", self.sha[:7], sha[:7])
            elif release is not None:
                # Failed, or its app gone while it downloaded.
                return UpdateState("failed", self.sha[:7], sha[:7], status.get("log"))
            # Failed, but the latest release is no longer past what is
            # installed; or staged, but its folder gone.
            self.clear()
        if release is None:
            return None
        return UpdateState("ready", self.sha[:7], release.sha[:7])

    def start(self, automatic: bool = False) -> UpdateState | None:
        """The update to the latest release started, unless one runs or that
        release is staged already. Started by the watch (`automatic`), a
        release that failed is left for Oscar to retry."""
        with self._starting:
            return self._start(automatic)

    def hold(self) -> Path | None:
        """No update started from now on, for a restart: the staged version's
        program to restart on. None, holding nothing, should none be staged
        (an update started a moment ago in its place)."""
        with self._starting:
            exe = self.staged()
            self.held = exe is not None
            return exe

    def release(self) -> None:
        """The restart given up: updates start again."""
        self.held = False

    def _start(self, automatic: bool) -> UpdateState | None:
        current = self.state()
        release = self.latest()
        if current is None or release is None or current.state == "updating" or self.held:
            return current
        if current.state in ("staged", "failed"):
            building = (self.status() or {}).get("sha")
            if (current.state == "staged" or automatic) and building == release.sha:
                return current
        if self.before_build:
            self.before_build()
        self._write_status(
            {
                "state": "updating",
                "sha": release.sha,
                "pid": os.getpid(),
                "log": str(self.log_path),
            }
        )
        self.worker = threading.Thread(
            target=self._stage, args=(release,), name="update", daemon=True
        )
        self.worker.start()
        log.info("Updating to %s (%s of %s)", release.sha, release.tag, self.repo)
        return self.state()

    def _stage(self, release: Release) -> None:
        """The release downloaded and staged beside the running version;
        the status file says so, or that it failed and why is in the log."""
        downloads = self.status_path.parent / "update-download"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")
        self._note(f"Updating to {release.sha}, {release.tag} of {self.repo}")
        try:
            downloads.mkdir(parents=True, exist_ok=True)
            archive = downloads / f"{release.folder}.zip"
            with self._api() as api:
                api.download(release.url, archive)
            _check(archive, release)
            self._note(f"Downloaded {archive.name} ({archive.stat().st_size >> 20} MB)")
            app = self._unpack(archive, release)
        except Exception as exc:
            log.exception("The update to %s failed", release.sha)
            self._note(f"The update failed: {exc}")
            self._write_status({"state": "failed", "sha": release.sha, "log": str(self.log_path)})
            return
        finally:
            shutil.rmtree(downloads, ignore_errors=True)
        self._write_status({"state": "staged", "sha": release.sha, "app": str(app)})
        self._note(f"Staged {release.sha} in {app}")

    def _unpack(self, archive: Path, release: Release) -> Path:
        """The zip unpacked into its version's folder, beside the running
        one; the versions before the running one gone."""
        running = (self.install / CURRENT).read_text(encoding="utf-8-sig").strip()
        if release.folder == running:
            raise UpdateError(f"{release.folder} is the version running")
        # The versions before the running one, and any half staged before.
        for path in self.install.iterdir():
            if (
                path.is_dir()
                and path.name != running
                and path.name.startswith((VERSION_PREFIX, STAGING_PREFIX))
            ):
                shutil.rmtree(path)
        staging = self.install / f"{STAGING_PREFIX}{release.folder}"
        try:
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(staging)
            built = _read_json(staging / "_internal" / "build-info.json") or {}
            if built.get("sha") != release.sha or not (staging / LAUNCHER).is_file():
                raise UpdateError(f"{archive.name} holds no version built from {release.sha}")
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        app = self.install / release.folder
        os.replace(staging, app)
        return app

    def _note(self, line: str) -> None:
        """A line of the update's own log (update.log), which the button
        points at should it fail."""
        log.info("%s", line)
        try:
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {line}\n")
        except OSError:
            pass

    def failed(self, why: str, log_path: Path) -> None:
        """The staged version did not come up; the button offers Retry."""
        sha = (self.status() or {}).get("sha", "")
        log.error("The update to %s failed: %s", sha, why)
        self._write_status({"state": "failed", "sha": sha, "log": str(log_path)})

    def _write_status(self, status: dict) -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(json.dumps(status), encoding="utf-8")

    def clear(self) -> None:
        self.status_path.unlink(missing_ok=True)

    def settle(self) -> None:
        """As the app starts: an update that installed it is done, and one
        an app before it was downloading when it stopped is no failure,
        only to be started again."""
        status = self.status()
        if not status:
            return
        if status.get("sha") == self.sha:
            log.info("Updated to %s", self.sha)
            self.clear()
        elif status.get("state") == "updating" and status.get("pid") != os.getpid():
            pid = status.get("pid")
            if pid is None or not win32.process_alive(pid):
                self.clear()
