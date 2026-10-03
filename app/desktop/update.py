"""The installed app updating itself from its repo.

The installed app knows the commit it was built from and the repo it came
from (build-info.json, written by desktop/build.ps1). When the repo's latest
commit is another, an update is ready: the Update button (the rail's foot,
partials/update_button.html) starts desktop/update.ps1 from the repo, which
builds that commit and installs it in the background; the install quits this
app and opens the new one. Uncommitted work is never part of an update.

Its progress lives in a status file in the app's data folder, written here as
the update starts and by the script if it fails; the new app clears it as it
starts.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import FROZEN, REPO_ROOT
from app.desktop import win32

log = logging.getLogger(__name__)

BUILD_INFO = REPO_ROOT / "build-info.json"
# How long the repo's latest commit is taken as known, between looks.
CHECK_SECONDS = 20
CREATE_NEW_PROCESS_GROUP = 0x00000200


@dataclass(frozen=True)
class UpdateState:
    # "ready" (a newer commit to install), "updating" or "failed".
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


class Updater:
    def __init__(self, sha: str, repo: Path, status_path: Path, git: str = "git") -> None:
        self.sha = sha
        self.repo = repo
        self.status_path = status_path
        self.git = git
        self._head: str | None = None
        self._checked = float("-inf")
        self._lock = threading.Lock()

    @classmethod
    def for_installed_app(cls, status_path: Path) -> Updater | None:
        """The installed app's updater; None run from the repo (always its
        latest code), or when its repo or git is not on this machine."""
        info = _read_json(BUILD_INFO) if FROZEN else None
        git = shutil.which("git")
        if not info or not git or not (Path(info["repo"]) / "desktop" / "update.ps1").exists():
            return None
        return cls(info["sha"], Path(info["repo"]), status_path, git)

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
            if latest != self.sha:
                # Failed, or its script gone without a word.
                return UpdateState("failed", self.sha[:7], sha[:7], status.get("log"))
            # Failed, but the repo is back at what is installed.
            self.clear()
        if latest is None or latest == self.sha:
            return None
        return UpdateState("ready", self.sha[:7], latest[:7])

    def start(self) -> UpdateState | None:
        """The update to the repo's latest commit started, unless one runs."""
        current = self.state()
        if current is None or current.state == "updating":
            return current
        self._checked = float("-inf")
        sha = self.latest()
        if sha is None or sha == self.sha:
            self.clear()
            return None
        script = self.repo / "desktop" / "update.ps1"
        self._write_status({"state": "updating", "sha": sha})
        process = subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(script), "-Status", str(self.status_path), "-Sha", sha,
            ],
            cwd=self.repo,
            # Its own process group, so it outlives this app, which the
            # install quits; no window (win32.no_console_windows).
            creationflags=CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Unless the script has already written that it failed.
        if (self.status() or {}).get("state") == "updating":
            self._write_status({"state": "updating", "sha": sha, "pid": process.pid})
        log.info("Updating to %s (update.ps1, pid %s)", sha, process.pid)
        return self.state()

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
