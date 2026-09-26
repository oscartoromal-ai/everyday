"""Multi-interface serving: bind localhost plus the Tailscale interface.

One shared FastAPI app instance (built once via create_app(with_scheduler=True),
so the background scheduler exists exactly once) is served by one uvicorn
server per bind host, each in its own thread. Only the first server runs the
ASGI lifespan (startup/shutdown) -- the others run with lifespan="off" so the
scheduler and the MCP app's own lifespan aren't started a second time.

The always-on app runs hidden, so everything it logs, uvicorn's lines included,
also goes to a rotating file beside the database (data/logs/), along with why
it stopped.

Entry point for `uv run personal-calendar` ([project.scripts] in pyproject.toml).
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

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


def _configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"),
    ]
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


def main() -> None:
    _configure_logging(log_path())

    settings = get_settings()
    port = settings.server.port
    hosts = _bind_hosts()
    app = create_app(with_scheduler=True)

    servers: list[uvicorn.Server] = []
    threads: list[threading.Thread] = []
    for index, host in enumerate(hosts):
        # Only the first server manages the app lifespan (scheduler startup);
        # the rest serve HTTP against the same already-running app instance.
        lifespan = "auto" if index == 0 else "off"
        # log_config=None: uvicorn's loggers propagate to the root handlers above.
        config = uvicorn.Config(
            app, host=host, port=port, lifespan=lifespan, log_level="info", log_config=None
        )
        server = uvicorn.Server(config)
        servers.append(server)
        threads.append(threading.Thread(target=server.run, name=f"uvicorn-{host}", daemon=True))

    def stop(reason: str) -> None:
        log.info("Shutting down: %s", reason)
        for server in servers:
            server.should_exit = True

    # Windows delivers a closed console, logoff or shutdown as SIGBREAK.
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda signum, frame: stop("console closed (SIGBREAK)"))

    log.info("Binding: %s", ", ".join(f"http://{h}:{port}" for h in hosts))
    for thread in threads:
        thread.start()

    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        stop("Ctrl+C (SIGINT)")
        for t in threads:
            t.join()
    log.info("Stopped")


if __name__ == "__main__":
    main()
