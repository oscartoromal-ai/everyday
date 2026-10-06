"""The installed app updating itself from its repo.

The installed app knows the commit it was built from and the repo it came
from (build-info.json, written by desktop/build.ps1). Changes reach master
through pull requests merged on GitHub, so the commit to be at is the repo's
origin/master, not whatever the repo has checked out. The app watches it
(tick(), on a thread of its own, app/desktop): it fetches every
FETCH_SECONDS, and once
master is past the installed commit it starts the update itself, so that by
the time Oscar looks it is built. The update runs the app's own copy of
desktop/update.ps1 (bundled with it, so it always takes what the app passes
it), which builds that commit in the background and stages it, while the
app carries on. Uncommitted work is never part of an update. The Update
button (the rail's foot, partials/update_button.html) starts it by hand,
should the watch not have, and retries a failure, which the watch leaves to
Oscar until master moves on. Settings' Check for updates
(partials/update_check.html) fetches now rather than at the next fetch, and
starts the update when master is past the installed commit.

The install's folder (desktop/installer.iss) holds a launcher, the
`Personal Calendar.exe` its shortcuts start, and each version in a folder of
its own beside it (app-<commit>); the launcher starts the one current.txt
names. Staging puts the new version in its folder beside the running one.
The button then offers Restart: this app hands over to the staged one
(Shell.restart in app/desktop, through the standby it starts ahead,
app/desktop/standby.py), which takes the install as its own once its window
is up (take_over). A newer master while one is staged is built in its place.

Its progress lives in a status file in the app's data folder, written here as
the update starts and by the script as it stages or fails; the new app clears
it as it starts.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import winreg
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import FROZEN, REPO_ROOT
from app.desktop import win32

log = logging.getLogger(__name__)

BUILD_INFO = REPO_ROOT / "build-info.json"
# Bundled with the app (desktop/personal-calendar.spec); the repo's, run from it.
SCRIPT = REPO_ROOT / "desktop" / "update.ps1"
# Where the commits to update to come from.
REMOTE = "origin"
BRANCH = "master"
# What the install's folder holds besides its versions (desktop/installer.iss).
LAUNCHER = "Personal Calendar.exe"
CURRENT = "current.txt"
# Writes of current.txt tried, before taking over is given up.
TAKE_OVER_TRIES = 10
VERSION_PREFIX = "app-"
# Inno Setup's entry for the app in Installed apps: its AppId, then _is1.
UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{6C1B0E5A-3F4B-4E8C-9C1D-2B7A5E9F4D21}_is1"
)
# How long master's latest commit is taken as known, between looks.
CHECK_SECONDS = 20
# How often the watch fetches the remote, and looks at the update under way.
FETCH_SECONDS = 60
WATCH_SECONDS = 2
CREATE_NEW_PROCESS_GROUP = 0x00000200


@dataclass(frozen=True)
class UpdateState:
    # "ready" (a newer commit to install), "updating" (building it),
    # "staged" (built, for Restart), "restarting" or "failed".
    state: str
    installed: str
    latest: str
    log: str | None = None


def _read_json(path: Path) -> dict | None:
    try:
        # PowerShell writes UTF-8 with a byte-order mark.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def build_info() -> dict | None:
    """What the installed app was built from: its commit and version, and its
    repo. None run from the repo."""
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


class Updater:
    def __init__(
        self, sha: str, repo: Path, status_path: Path, git: str = "git",
        install: Path | None = None,
    ) -> None:
        self.sha = sha
        self.repo = repo
        self.status_path = status_path
        self.git = git
        # The install's folder, where updates are staged; None in the layout
        # before versions had folders of their own, which the installer replaces.
        self.install = install
        # What must let go of the staged version before a build replaces it:
        # the standby started on it (app/desktop), whose files are in use.
        self.before_build: Callable[[], None] | None = None
        self._head: str | None = None
        self._checked = float("-inf")
        self._fetched = float("-inf")
        self._lock = threading.Lock()
        self._fetching = threading.Lock()
        # One start at a time, the watch's or a button's, and none at all
        # while a restart is under way (hold()).
        self._starting = threading.Lock()
        self.held = False

    @classmethod
    def for_installed_app(cls, status_path: Path) -> Updater | None:
        """The installed app's updater; None run from the repo (always its
        latest code), or when its repo or git is not on this machine."""
        info = build_info()
        git = shutil.which("git")
        if not info or not git or not SCRIPT.exists() or not (Path(info["repo"]) / ".git").exists():
            return None
        return cls(
            info["sha"], Path(info["repo"]), status_path, git, install_root(Path(sys.executable))
        )

    def _git(self, *args: str, timeout: float = 10) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.git, "-C", str(self.repo), *args],
            capture_output=True, text=True, timeout=timeout,
            # Never a prompt for credentials: there is no one to answer it.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
        )

    def fetch(self) -> str | None:
        """The remote's master fetched into the repo, for latest(); why not,
        should it fail. One fetch at a time: a check waits for the background
        one, then fetches again."""
        with self._fetching:
            self._fetched = time.monotonic()
            try:
                out = self._git("fetch", "--quiet", REMOTE, BRANCH, timeout=120)
            except (OSError, subprocess.SubprocessError) as exc:
                log.warning("Could not fetch %s %s", REMOTE, BRANCH, exc_info=True)
                return str(exc) or type(exc).__name__
            if out.returncode:
                why = out.stderr.strip()
                log.warning("Could not fetch %s %s: %s", REMOTE, BRANCH, why)
                # Git's first fatal line says it ("fatal: unable to access ...");
                # advice follows it.
                lines = why.splitlines()
                fatal = [line for line in lines if line.startswith("fatal:")]
                return (fatal or lines or [f"git fetch exited {out.returncode}"])[0]
            self.look_up()
            return None

    def check(self) -> tuple[UpdateState | None, str | None]:
        """Check for updates (Settings): the remote looked at now, not at the
        next background fetch, and the update to a newer master started at
        once. What there is then, and why the remote could not be reached."""
        why = self.fetch()
        return (self.state() if why else self.start()), why

    def tick(self) -> None:
        """The watch's step (every WATCH_SECONDS): a fetch when one is due,
        else master looked up again every CHECK_SECONDS (fetched by hand in
        the repo, say), then the update started should master be past what is
        installed, or what is staged."""
        if time.monotonic() - self._fetched >= FETCH_SECONDS:
            self.fetch()
        elif time.monotonic() - self._checked > CHECK_SECONDS:
            self.look_up()
        self.start(automatic=True)

    def latest(self) -> str | None:
        """The commit to be at: the remote's master as last fetched (tick()),
        as last looked up; the installed one while master is not past it.
        Looked up here only the first time: a page drawing the Update button
        runs no git."""
        with self._lock:
            if self._checked == float("-inf"):
                self._look_up_locked()
            return self._head

    def look_up(self) -> None:
        """Master's latest commit read again, from the repo as fetched."""
        with self._lock:
            self._look_up_locked()

    def _look_up_locked(self) -> None:
        self._checked = time.monotonic()
        self._head = self._look_up()

    def _look_up(self) -> str | None:
        try:
            out = self._git("rev-parse", "--verify", "--quiet", f"refs/remotes/{REMOTE}/{BRANCH}")
            if out.returncode:
                log.warning("The repo has no %s/%s to update to", REMOTE, BRANCH)
                return None
            head = out.stdout.strip()
            # Never back: master behind the installed commit (one installed by
            # hand from a branch ahead of it) is nothing to update to.
            if self._git("merge-base", "--is-ancestor", head, self.sha).returncode == 0:
                return self.sha
            return head
        except (OSError, subprocess.SubprocessError):
            log.warning("Could not read master's latest commit", exc_info=True)
            return None

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
        latest = self.latest()
        if status:
            sha = status.get("sha", "")
            # No pid yet: the script has only just been started.
            pid = status.get("pid")
            if status.get("state") == "updating" and (pid is None or win32.process_alive(pid)):
                return UpdateState("updating", self.sha[:7], sha[:7])
            if status.get("state") == "staged":
                if self.staged():
                    return UpdateState("staged", self.sha[:7], sha[:7])
            elif latest != self.sha:
                # Failed, or its script gone without a word.
                return UpdateState("failed", self.sha[:7], sha[:7], status.get("log"))
            # Failed, but master is no longer past what is installed; or staged,
            # but its folder gone.
            self.clear()
        if latest is None or latest == self.sha:
            return None
        return UpdateState("ready", self.sha[:7], latest[:7])

    def start(self, automatic: bool = False) -> UpdateState | None:
        """The update to master's latest commit started, unless one runs or
        that commit is staged already. Started by the watch (`automatic`), a
        commit that failed is left for Oscar to retry."""
        with self._starting:
            return self._start(automatic)

    def hold(self) -> Path | None:
        """No update started from now on, for a restart: the staged version's
        program to restart on. None, holding nothing, should none be staged
        (a build started a moment ago in its place)."""
        with self._starting:
            exe = self.staged()
            self.held = exe is not None
            return exe

    def release(self) -> None:
        """The restart given up: updates start again."""
        self.held = False

    def _start(self, automatic: bool) -> UpdateState | None:
        current = self.state()
        if current is None or current.state == "updating" or self.held:
            return current
        if current.state in ("staged", "failed"):
            building = (self.status() or {}).get("sha")
            if (current.state == "staged" or automatic) and building == self.latest():
                return current
        self._checked = float("-inf")
        sha = self.latest()
        if sha is None or sha == self.sha:
            self.clear()
            return None
        if self.before_build:
            self.before_build()
        # What the script says outside its own log (update.log), such as why
        # PowerShell would not run it at all: the button points here should
        # it end without a word.
        console = self.status_path.parent / "logs" / "update-console.log"
        console.parent.mkdir(parents=True, exist_ok=True)
        starting = {"state": "updating", "sha": sha, "log": str(console)}
        self._write_status(starting)
        args = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPT), "-Repo", str(self.repo),
            "-Status", str(self.status_path), "-Sha", sha,
        ]
        if self.install:
            args += ["-Install", str(self.install)]
        with console.open("wb") as output:
            process = subprocess.Popen(
                args,
                cwd=self.repo,
                # Its own process group, so it outlives this app; no window
                # (win32.no_console_windows).
                creationflags=CREATE_NEW_PROCESS_GROUP,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        # Unless the script has already written that it staged or failed.
        if self.status() == starting:
            self._write_status({**starting, "pid": process.pid})
        log.info("Updating to %s (update.ps1, pid %s)", sha, process.pid)
        return self.state()

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
        """As the app starts: an update that installed it is done."""
        status = self.status()
        if status and status.get("sha") == self.sha:
            log.info("Updated to %s", self.sha)
            self.clear()
