"""The installed app updating itself from its repo.

The installed app knows the commit it was built from and the repo it came
from (build-info.json, written by desktop/build.ps1). When the repo's latest
commit is another, an update is ready: the Update button (the rail's foot,
partials/update_button.html) starts desktop/update.ps1 from the repo, which
builds that commit in the background and stages it, while the app carries
on. Uncommitted work is never part of an update.

The install's folder (desktop/installer.iss) holds a launcher, the
`Personal Calendar.exe` its shortcuts start, and each version in a folder of
its own beside it (app-<commit>); the launcher starts the one current.txt
names. Staging puts the new version in its folder beside the running one.
The button then offers Restart: this app hands over to the staged one
(Shell.restart in app/desktop), which takes the install as its own once its
window is up (take_over).

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
from dataclasses import dataclass
from pathlib import Path

from app.config import FROZEN, REPO_ROOT
from app.desktop import win32

log = logging.getLogger(__name__)

BUILD_INFO = REPO_ROOT / "build-info.json"
# What the install's folder holds besides its versions (desktop/installer.iss).
LAUNCHER = "Personal Calendar.exe"
CURRENT = "current.txt"
VERSION_PREFIX = "app-"
# Inno Setup's entry for the app in Installed apps: its AppId, then _is1.
UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{6C1B0E5A-3F4B-4E8C-9C1D-2B7A5E9F4D21}_is1"
)
# How long the repo's latest commit is taken as known, between looks.
CHECK_SECONDS = 20
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
    # Whole or not at all, for a launcher reading it meanwhile.
    staging = current.with_suffix(".tmp")
    staging.write_text(exe.parent.name, encoding="utf-8")
    os.replace(staging, current)
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
        self._head: str | None = None
        self._checked = float("-inf")
        self._lock = threading.Lock()

    @classmethod
    def for_installed_app(cls, status_path: Path) -> Updater | None:
        """The installed app's updater; None run from the repo (always its
        latest code), or when its repo or git is not on this machine."""
        info = build_info()
        git = shutil.which("git")
        if not info or not git or not (Path(info["repo"]) / "desktop" / "update.ps1").exists():
            return None
        return cls(
            info["sha"], Path(info["repo"]), status_path, git, install_root(Path(sys.executable))
        )

    def latest(self) -> str | None:
        """The repo's latest commit, looked up at most every CHECK_SECONDS."""
        with self._lock:
            if time.monotonic() - self._checked > CHECK_SECONDS:
                self._checked = time.monotonic()
                try:
                    out = subprocess.run(
                        [self.git, "-C", str(self.repo), "rev-parse", "HEAD"],
                        capture_output=True, text=True, timeout=10, check=True,
                    )
                    self._head = out.stdout.strip()
                except (OSError, subprocess.SubprocessError):
                    log.warning("Could not read the repo's latest commit", exc_info=True)
                    self._head = None
            return self._head

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
            # Failed, but the repo is back at what is installed; or staged,
            # but its folder gone.
            self.clear()
        if latest is None or latest == self.sha:
            return None
        return UpdateState("ready", self.sha[:7], latest[:7])

    def start(self) -> UpdateState | None:
        """The update to the repo's latest commit started, unless one runs."""
        current = self.state()
        if current is None or current.state in ("updating", "staged"):
            return current
        self._checked = float("-inf")
        sha = self.latest()
        if sha is None or sha == self.sha:
            self.clear()
            return None
        script = self.repo / "desktop" / "update.ps1"
        self._write_status({"state": "updating", "sha": sha})
        args = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script), "-Status", str(self.status_path), "-Sha", sha,
        ]
        if self.install:
            args += ["-Install", str(self.install)]
        process = subprocess.Popen(
            args,
            cwd=self.repo,
            # Its own process group, so it outlives this app; no window
            # (win32.no_console_windows).
            creationflags=CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Unless the script has already written that it staged or failed.
        if self.status() == {"state": "updating", "sha": sha}:
            self._write_status({"state": "updating", "sha": sha, "pid": process.pid})
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
