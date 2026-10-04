"""A sync running in the background, one at a time: the scheduler's, or one
asked for from a page. Garmin's and GitHub's each have one."""

from __future__ import annotations

import threading
from collections.abc import Callable


class Syncing:
    """The sync running in the background, one at a time: the scheduler's,
    or one asked for from the page."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, work: Callable[[], None]) -> bool:
        """Run `work` in its own thread unless a sync already runs."""
        with self._lock:
            if self.running:
                return False
            self._thread = threading.Thread(target=work, name=self.name, daemon=True)
            self._thread.start()
            return True

    def wait(self, timeout: float | None = None) -> None:
        """Until the sync running in its own thread, if any, is done."""
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def run_here(self, work: Callable[[], None]) -> bool:
        """Run `work` on this thread (the scheduler's) unless one runs."""
        with self._lock:
            if self.running:
                return False
            self._thread = threading.current_thread()
        try:
            work()
        finally:
            with self._lock:
                self._thread = None
        return True
