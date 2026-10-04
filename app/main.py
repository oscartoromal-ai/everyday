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
from app.fresh import FreshPagesMiddleware
from app.mcp.server import create_mcp
from app.security import BrowserGuardMiddleware
from app.services import DomainError
from app.ui import fragments as ui_fragments
from app.ui import gantt as ui_gantt
from app.ui import garmin as ui_garmin
from app.ui import me as ui_me
from app.ui import money as ui_money
from app.ui import nutrition as ui_nutrition
from app.ui import pages as ui_pages
from app.ui import project as ui_project
from app.ui import repositories as ui_repositories
from app.ui.views import keep_db

APP_DIR = Path(__file__).resolve().parent

# Each optional module's routes (config.py's OptionalModule).
OPTIONAL_ROUTERS = {
    "health": (ui_nutrition.router, ui_me.router, ui_garmin.router),
    "finances": (ui_money.router,),
    "code": (ui_repositories.router,),
}


def create_app(*, with_scheduler: bool = False) -> FastAPI:
    settings = get_settings()
    # Streamable HTTP MCP endpoint at /mcp, sharing the process and database,
    # with the tools of the modules installed.
    mcp_app = create_mcp(settings.install.without).http_app(path="/", stateless_http=True)

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
    app.include_router(ui_gantt.router, dependencies=ui)
    app.include_router(ui_project.router, dependencies=ui)
    # The optional modules' pages, unless the machine was installed without them.
    for module, routers in OPTIONAL_ROUTERS.items():
        if settings.installed(module):
            for router in routers:
                app.include_router(router, dependencies=ui)

    @app.exception_handler(DomainError)
    def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    allowed_hosts = {"127.0.0.1", "localhost", *settings.server.extra_hosts}
    app.add_middleware(FreshPagesMiddleware)
    app.add_middleware(BrowserGuardMiddleware, allowed_hosts=allowed_hosts)

    return app


# The dev server's app (`uvicorn app.main:app`). It runs no jobs, since it may share
# the desktop app's database; the desktop app (app/desktop) and `personal-calendar`
# (serve.py) build the one that does.
app = create_app()
