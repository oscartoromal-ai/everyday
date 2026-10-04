"""FastAPI app factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
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
from app.ui import gantt as ui_gantt
from app.ui import garmin as ui_garmin
from app.ui import money as ui_money
from app.ui import nutrition as ui_nutrition
from app.ui import pages as ui_pages
from app.ui import repositories as ui_repositories
from app.ui.views import keep_db

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
    # Every page's sidebar lists the projects, from the request's session.
    ui = [Depends(keep_db)]
    app.include_router(ui_pages.router, dependencies=ui)
    app.include_router(ui_fragments.router, dependencies=ui)
    app.include_router(ui_nutrition.router, dependencies=ui)
    app.include_router(ui_garmin.router, dependencies=ui)
    app.include_router(ui_money.router, dependencies=ui)
    app.include_router(ui_repositories.router, dependencies=ui)
    app.include_router(ui_gantt.router, dependencies=ui)

    @app.exception_handler(DomainError)
    def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    settings = get_settings()
    allowed_hosts = {"127.0.0.1", "localhost", *settings.server.extra_hosts}
    app.add_middleware(BrowserGuardMiddleware, allowed_hosts=allowed_hosts)

    return app


# The dev server's app (`uvicorn app.main:app`). It runs no jobs, since it may share
# the desktop app's database; the desktop app (app/desktop) and `personal-calendar`
# (serve.py) build the one that does.
app = create_app()
