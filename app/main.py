"""FastAPI app factory."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import calendar as calendar_api
from app.api import projects as projects_api
from app.api import tasks as tasks_api
from app.config import get_settings
from app.db import get_session_factory
from app.fresh import FreshPagesMiddleware
from app.mcp.server import create_mcp
from app.security import BrowserGuardMiddleware
from app.services import DomainError
from app.services import llm as llm_svc
from app.ui import agent_window as ui_agent_window
from app.ui import fragments as ui_fragments
from app.ui import gantt as ui_gantt
from app.ui import garmin as ui_garmin
from app.ui import habits as ui_habits
from app.ui import keys as ui_keys
from app.ui import me as ui_me
from app.ui import models as ui_models
from app.ui import money as ui_money
from app.ui import nutrition as ui_nutrition
from app.ui import pages as ui_pages
from app.ui import project as ui_project
from app.ui import repositories as ui_repositories
from app.ui import task_files as ui_task_files
from app.ui import task_run as ui_task_run
from app.ui.views import keep_db
from app.usage import UsageMiddleware

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
        from app.jobs.scheduler import create_scheduler, run_usage_flush
        from app.services import settling

        scheduler = create_scheduler() if with_scheduler else None
        # The everyday files settled, then watched (with the jobs, as the dev
        # server may share the desktop app's database).
        watching = threading.Event()
        if scheduler:
            scheduler.start()
            # The model providers as they stand, checked in the background
            # when the last check is old: the agent window beside every page
            # says from it whether each agent is here.
            factory = get_session_factory()
            with factory() as db:
                if llm_svc.stale(db):
                    llm_svc.checking.start(lambda: llm_svc.run_check(factory))
            threading.Thread(
                target=settling.watch, args=(watching,), name="everyday-files", daemon=True
            ).start()
        async with mcp_app.lifespan(app):
            yield
        watching.set()
        if scheduler:
            scheduler.shutdown(wait=False)
            # The last minute's use, before the app goes.
            run_usage_flush()

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
    app.include_router(ui_habits.router, dependencies=ui)
    app.include_router(ui_task_run.router, dependencies=ui)
    app.include_router(ui_task_files.router, dependencies=ui)
    app.include_router(ui_models.router, dependencies=ui)
    app.include_router(ui_agent_window.router, dependencies=ui)
    app.include_router(ui_keys.router, dependencies=ui)
    # The optional modules' pages, unless the machine was installed without them.
    for module, routers in OPTIONAL_ROUTERS.items():
        if settings.installed(module):
            for router in routers:
                app.include_router(router, dependencies=ui)

    @app.exception_handler(DomainError)
    def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    allowed_hosts = {"127.0.0.1", "localhost", *settings.server.extra_hosts}
    # Innermost, so it sees the route that answered (app/usage.py).
    app.add_middleware(UsageMiddleware)
    app.add_middleware(FreshPagesMiddleware)
    app.add_middleware(BrowserGuardMiddleware, allowed_hosts=allowed_hosts)

    return app


# The dev server's app (`uvicorn app.main:app`). It runs no jobs, since it may share
# the desktop app's database; the desktop app (app/desktop) and `personal-calendar`
# (serve.py) build the one that does.
app = create_app()
