import logging
import sys
import threading

import pytest

from app import migrate, serve
from app.config import get_settings


class StartedServers:
    """Servers that come up (or not, `up`), and stop when told."""

    up = True

    def __init__(self, app) -> None:  # noqa: ANN001
        self.stopped: list[str] = []

    def start(self) -> None:
        pass

    def wait_started(self, timeout: float = 30, *, first: bool = False) -> bool:
        assert first, "the app is up once its first server is"
        return self.up

    def stop(self, reason: str) -> None:
        self.stopped.append(reason)

    def join(self, timeout: float | None = None) -> None:
        pass

    def alive(self) -> bool:
        return False


@pytest.fixture
def started(monkeypatch):  # noqa: ANN201
    """serve.main over servers that pretend, and what it then did about the
    migration its start made: confirmed it, or put it back."""
    did: list[str] = []
    monkeypatch.setattr(serve, "prepare", lambda: None)
    monkeypatch.setattr(serve, "Servers", StartedServers)
    monkeypatch.setattr(migrate, "confirm", lambda path: did.append(f"confirmed {path}"))
    monkeypatch.setattr(migrate, "go_back", lambda path: did.append(f"put back {path}") or True)
    return did


def test_a_start_that_serves_confirms_what_it_migrated(started) -> None:
    serve.main()
    assert started == [f"confirmed {get_settings().db_path}"]


def test_a_start_that_cannot_serve_puts_back_what_it_migrated(started, monkeypatch) -> None:
    # The version before it can then start on the database, rather than
    # find it migrated past what it knows.
    monkeypatch.setattr(StartedServers, "up", False)
    serve.main()
    assert started == [f"put back {get_settings().db_path}"]


def test_the_hidden_app_logs_to_a_file(tmp_path, monkeypatch) -> None:
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    # A live server started by an earlier test sets uvicorn's own levels for
    # the process; this one needs uvicorn.error's INFO lines to pass.
    uvicorn_error = logging.getLogger("uvicorn.error")
    monkeypatch.setattr(uvicorn_error, "level", logging.NOTSET)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    path = tmp_path / "logs" / "personal-calendar.log"
    try:
        serve.configure_logging(path)
        # uvicorn runs with log_config=None, so its loggers reach the file too.
        logging.getLogger("uvicorn.error").info("Uvicorn running")
        logging.getLogger("app.serve").info("Shutting down: console closed (SIGBREAK)")
        for handler in root.handlers:
            handler.flush()
        text = path.read_text(encoding="utf-8")
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:], root.level = saved[0], saved[1]
    assert "uvicorn.error: Uvicorn running" in text
    assert "Shutting down: console closed (SIGBREAK)" in text
