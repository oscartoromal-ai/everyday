"""Multi-interface serving: bind localhost plus the Tailscale interface.

One shared FastAPI app instance (built once via create_app(with_scheduler=True),
so the background scheduler exists exactly once) is served by one uvicorn
server per bind host, each in its own thread. Only the first server runs the
ASGI lifespan (startup/shutdown) -- the others run with lifespan="off" so the
scheduler and the MCP app's own lifespan aren't started a second time.

Entry point for `uv run personal-calendar` ([project.scripts] in pyproject.toml).
"""

from __future__ import annotations

import logging
import threading

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


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

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
        config = uvicorn.Config(app, host=host, port=port, lifespan=lifespan, log_level="info")
        server = uvicorn.Server(config)
        servers.append(server)
        threads.append(threading.Thread(target=server.run, name=f"uvicorn-{host}", daemon=True))

    log.info("Binding: %s", ", ".join(f"http://{h}:{port}" for h in hosts))
    for thread in threads:
        thread.start()

    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        log.info("Shutting down")
        for server in servers:
            server.should_exit = True
        for t in threads:
            t.join()


if __name__ == "__main__":
    main()
