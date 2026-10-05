"""A version of the app started ahead of a restart, waiting to take over.

Started cold, a version takes seconds to load its code and its window
(WebView2), which a restart would spend with the window inert. So the
running app starts the version it is to restart on ahead of time, as soon as
there is one (an update staged; itself again, should that fail):
`<its program> --standby <the running app's pid> <an id>`. The standby loads
its code and its window, hidden and holding nothing (no claim, no port, no
database), says Ready, and waits.

On Restart the running app writes where it was for the standby (its page,
and whether its window was on screen), says Go, stops serving and gives up
its claim. The standby claims it, migrates the database and serves, draws
the page in its window, puts it over the old one, and says Up, for that one
to go. Should the running app end without saying Go (Quit, a crash), or say
Quit, the standby ends too.

The signals are named events, a set for each standby (its instance's name
and the id the running app gave it), so a standby gone never answers for
another.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from app.desktop import win32

log = logging.getLogger(__name__)

# How long a standby told to end has to.
STOP_SECONDS = 10


@dataclass(frozen=True)
class Handover:
    """Where the app restarting was: its page, and whether its window was
    off screen (in the tray)."""

    page: str
    background: bool


def _signal(instance: str, id: str, what: str) -> win32.Signal:
    return win32.Signal(f"{instance}.Standby.{id}.{what}")


def _handover_path(data: Path, id: str) -> Path:
    return data / f"handover-{id}.json"


class Standby:
    """The running app's side: the version at `exe`, started to stand by."""

    def __init__(self, exe: Path, instance: str, data: Path) -> None:
        self.exe = exe
        self.data = data
        self.id = uuid.uuid4().hex
        self.process = subprocess.Popen(
            [str(exe), "--standby", str(os.getpid()), self.id],
            # One frozen app starting another: that one sets itself up afresh.
            env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.pid = self.process.pid
        self._ready, self._go, self._up, self._quit = (
            _signal(instance, self.id, what) for what in ("Ready", "Go", "Up", "Quit")
        )
        log.info("Standing by: %s (pid %s)", exe, self.pid)

    def alive(self) -> bool:
        return self.process.poll() is None

    def wait_ready(self, timeout: float) -> bool:
        """Whether it said Ready within `timeout` seconds, alive."""
        return self._ready.wait_unless_exited(self.pid, timeout)

    def go(self, handover: Handover) -> None:
        """Told to take over, where `handover` says."""
        _handover_path(self.data, self.id).write_text(
            json.dumps(asdict(handover)), encoding="utf-8"
        )
        # Its window comes up in front, as this one's would.
        win32.allow_foreground(self.pid)
        self._go.set()

    def wait_up(self, timeout: float) -> bool:
        """Whether its window came up in this one's place within `timeout`."""
        return self._up.wait_unless_exited(self.pid, timeout)

    def stop(self) -> None:
        """Ended, as it is not to take over (or failed to)."""
        if self.alive():
            self._quit.set()
            try:
                self.process.wait(STOP_SECONDS)
            except subprocess.TimeoutExpired:
                log.warning("The standby (pid %s) did not end; ending it", self.pid)
                self.process.kill()
                self.process.wait()
        _handover_path(self.data, self.id).unlink(missing_ok=True)
        for signal in (self._ready, self._go, self._up, self._quit):
            signal.close()
        log.info("Stopped the standby (pid %s)", self.pid)


class Waiting:
    """The standby's own side, for the app with process id `parent`, by the
    `id` it was given."""

    def __init__(self, instance: str, parent: int, id: str, data: Path) -> None:
        self.id = id
        self.data = data
        self._ready, self._go, self._up, self._quit = (
            _signal(instance, id, what) for what in ("Ready", "Go", "Up", "Quit")
        )
        # Opened now: once it ends, its number may be another's.
        self._parent = win32.Process(parent)

    def wait_for_go(self) -> Handover | None:
        """Ready said, then where to take over once told Go; None when told
        Quit, or should the app it stands by for end first."""
        self._ready.set()
        if win32.wait_first([self._go, self._quit], self._parent, None) != 0:
            return None
        self._parent.close()
        path = _handover_path(self.data, self.id)
        try:
            handover = Handover(**json.loads(path.read_text(encoding="utf-8")))
            path.unlink()
        except (OSError, ValueError, TypeError):
            log.warning("No handover to read at %s; opening Today", path, exc_info=True)
            return Handover("/today", background=False)
        return handover

    def up(self) -> None:
        """Its window up in the old one's place: that one can go."""
        self._up.set()
