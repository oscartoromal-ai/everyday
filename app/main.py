"""FastAPI app factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import calendar as calendar_api
from app.api import projects as projects_api
from app.api import tasks as tasks_api
from app.config import get_settings
from app.mcp.server import mcp
from app.security import BrowserGuardMiddleware
from app.services import DomainError
from app.ui import fragments as ui_fragments
from app.ui import pages as ui_pages

APP_DIR = Path(__file__).resolve().parent


def create_app(*, with_scheduler: bool = False) -> FastAPI:
    # Streamable HTTP MCP endpoint at /mcp, sharing the process and database.
    mcp_app = mcp.http_app(path="/", stateless_http=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.jobs.scheduler import create_scheduler

        scheduler = create_scheduler() if with_scheduler else None
        if scheduler:
            scheduler.start()
        async with mcp_app.lifespan(app):
            yield
        if scheduler:
            scheduler.shutdown(wait=False)

    app = FastAPI(
        title="Personal Calendar",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.mount("/mcp", mcp_app)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.include_router(tasks_api.router)
    app.include_router(projects_api.router)
    app.include_router(calendar_api.router)
    app.include_router(ui_pages.router)
    app.include_router(ui_fragments.router)

    @app.exception_handler(DomainError)
    def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    settings = get_settings()
    allowed_hosts = {"127.0.0.1", "localhost", *settings.server.extra_hosts}
    app.add_middleware(BrowserGuardMiddleware, allowed_hosts=allowed_hosts)

    return app


app = create_app(with_scheduler=True)
