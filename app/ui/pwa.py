"""The app installed as a desktop app (a PWA): its manifest and service
worker, both served from the root so their scope is the whole app, and the
count its taskbar icon shows.

Installing it (Edge or Chrome: Install app) gives the app its own window,
taskbar and Start menu entries, and the shortcuts below on its icon's menu.
The service worker only stands in when the server is not answering; every
page and request still comes from the server as it does in a tab.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from app.db import DbSession
from app.ui.views import STATIC_DIR, asset

router = APIRouter(include_in_schema=False)

NAME = "Personal Calendar"


def manifest() -> dict:
    return {
        "id": "/",
        "name": NAME,
        "short_name": NAME,
        "description": "Calendar, tasks and projects, kept with Claude.",
        "start_url": "/today",
        "scope": "/",
        "display": "standalone",
        # The light theme's paper; the page sets the bar's colour to its own
        # theme as it loads (base.html).
        "background_color": "#ffffff",
        "theme_color": "#ffffff",
        "icons": [
            {"src": asset("icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": asset("icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {
                "src": asset("icons/icon-maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
        # The icon's menu (right-click on the taskbar).
        "shortcuts": [
            {"name": "Today", "url": "/today"},
            {"name": "Calendar", "url": "/calendar"},
            {"name": "Projects", "url": "/projects"},
            {"name": "New task", "url": "/today?capture=1"},
        ],
    }


@router.get("/manifest.webmanifest")
def get_manifest() -> JSONResponse:
    return JSONResponse(manifest(), media_type="application/manifest+json")


@router.get("/sw.js")
def service_worker() -> FileResponse:
    # Checked on every load, so a changed worker takes over at once.
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/ui/nudges/count")
def nudge_count(db: DbSession) -> dict:
    """How many nudges are waiting: the number on the taskbar icon (shell.js)."""
    from app.services import nudges as nudges_svc

    return {"count": len(nudges_svc.active_nudges(db))}
