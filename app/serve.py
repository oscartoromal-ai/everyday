"""Multi-interface serving: bind localhost plus the Tailscale interface.

One shared FastAPI app instance (built once via create_app(with_scheduler=True),
so the background scheduler exists exactly once) is served by one uvicorn
server per bind host, each in its own thread. Only the first server runs the
ASGI lifespan (startup/shutdown) -- the others run with lifespan="off" so the
scheduler and the MCP app's own lifespan aren't started a second time.

The app runs with no console to read (the desktop app, or hidden), so
everything it logs, uvicorn's lines included, also goes to a rotating file
beside the database (data/logs/), along with why it stopped. It brings its
database up to the code's schema before serving (migrate.py).

Entry point for `uv run personal-calendar` ([project.scripts] in pyproject.toml),
the app without its window; the desktop app (app/desktop) serves the same way.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from app.config import get_settings
from app.main import create_app

log = logging.getLogger(__name__)


def _bind_hosts() -> list[str]:
    settings = get_settings()
    hosts = [settings.server.host]
    if settings.server.tailscale_ip:
        hosts.append(settings.server.tailscale_ip)
    return hosts


def log_path() -> Path:
    return get_settings().db_path.parent / "logs" / "personal-calendar.log"


def configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"),
    ]
    # A windowed app has no stderr to write to.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )

    def log_uncaught(args: threading.ExceptHookArgs) -> None:
        exc = (args.exc_type, args.exc_value, args.exc_traceback)
        log.critical("Uncaught error in %s", args.thread.name if args.thread else "?", exc_info=exc)

    threading.excepthook = log_uncaught
    sys.excepthook = lambda *exc: log.critical("Uncaught error", exc_info=exc)


class Servers:
    """The app served on every bind host, each server in a thread of its own."""

    def __init__(self, app: FastAPI) -> None:
        self.port = get_settings().server.port
        self.hosts = _bind_hosts()
        self.servers: list[uvicorn.Server] = []
        self.threads: list[threading.Thread] = []
        for index, host in enumerate(self.hosts):
            # Only the first server manages the app lifespan (scheduler startup);
            # the rest serve HTTP against the same already-running app instance.
            lifespan = "auto" if index == 0 else "off"
            # log_config=None: uvicorn's loggers propagate to the root handlers above.
            config = uvicorn.Config(
                app, host=host, port=self.port, lifespan=lifespan, log_level="info", log_config=None
            )
            server = uvicorn.Server(config)
            self.servers.append(server)
            self.threads.append(
                threading.Thread(target=server.run, name=f"uvicorn-{host}", daemon=True)
            )

    @property
    def url(self) -> str:
        return f"http://{self.hosts[0]}:{self.port}"

    def start(self) -> None:
        log.info("Binding: %s", ", ".join(f"http://{h}:{self.port}" for h in self.hosts))
        for thread in self.threads:
            thread.start()

    def wait_started(self, timeout: float = 30) -> bool:
        """Whether every server is answering; False when one gave up (its port
        taken) or the time ran out."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if all(server.started for server in self.servers):
                return True
            if not all(thread.is_alive() for thread in self.threads):
                return False
            time.sleep(0.05)
        return False

    def alive(self) -> bool:
        return any(thread.is_alive() for thread in self.threads)

    def stop(self, reason: str) -> None:
        log.info("Shutting down: %s", reason)
        for server in self.servers:
            server.should_exit = True

    def join(self) -> None:
        for thread in self.threads:
            thread.join()


def prepare() -> FastAPI:
    """Logging set up, the database migrated: the app, ready to serve."""
    from app import migrate

    configure_logging(log_path())
    migrate.upgrade(get_settings().db_path)
    return create_app(with_scheduler=True)


def main() -> None:
    servers = Servers(prepare())

    # Windows delivers a closed console, logoff or shutdown as SIGBREAK.
    if hasattr(signal, "SIGBREAK"):
        signal.signal(
            signal.SIGBREAK, lambda signum, frame: servers.stop("console closed (SIGBREAK)")
        )

    servers.start()
    try:
        while servers.alive():
            for t in servers.threads:
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        servers.stop("Ctrl+C (SIGINT)")
        servers.join()
    log.info("Stopped")


if __name__ == "__main__":
    main()
