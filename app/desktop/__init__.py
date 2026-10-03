"""The desktop app: Personal Calendar as a Windows program of its own.

One process holds everything: the server (serve.py, on 127.0.0.1:8377 as
always, so Claude's MCP and the phone reach it), its scheduler, and the window,
an Edge WebView2 onto the server's pages. Closing the window hides it to the
tray, where the app keeps running; Quit, on the tray icon's menu, ends it. It
starts hidden at sign-in (--background, from the installer's Run entry).

Its data lives in its home (config.py): %LOCALAPPDATA%/Personal Calendar when
installed, the database created and migrated as it starts. Launching it again
while it runs brings its window forward (--open <path> at a page), through
/desktop on the running one's server.

Entry point for the installed app (desktop/personal-calendar.spec) and for
`uv run personal-calendar-desktop` from the repo.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from pathlib import Path

import httpx
import webview
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import REPO_ROOT, get_settings
from app.desktop import win32
from app.desktop.tray import Tray

log = logging.getLogger(__name__)

NAME = "Personal Calendar"
APP_ID = "Oscar.PersonalCalendar"
MUTEX = "Local\\Oscar.PersonalCalendar"
ICON = REPO_ROOT / "app" / "static" / "icons" / "app.ico"
# How often the nudges waiting are counted again, besides as they change.
BADGE_SECONDS = 60


class Shell:
    """The window and the tray icon, over the app's server at `url`."""

    def __init__(self, url: str, state_path: Path) -> None:
        self.url = url
        self.state_path = state_path
        self.state = self._load_state()
        self.quitting = False
        self.badge_due = threading.Event()
        self.window: webview.Window | None = None
        self.tray = Tray(self)

    # ---- what it remembers between runs: where the window was, its title
    # bar's colours, and whether the tray has been pointed out ----

    def _load_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    # ---- the window ----

    @property
    def hwnd(self) -> int:
        return int(self.window.native.Handle.ToInt64())

    def create_window(self) -> webview.Window:
        paper = self.state.get("title_bar", {}).get("paper", "#ffffff")
        self.window = webview.create_window(
            NAME,
            f"{self.url}/today",
            js_api=Api(self),
            width=1280,
            height=860,
            min_size=(400, 520),
            hidden=True,
            background_color=paper,
            # A web page's own manners: its text selects, it zooms with
            # Ctrl and the wheel, and its links and rows drag.
            text_select=True,
            zoomable=True,
            draggable=True,
        )
        self.window.events.closing += self._on_closing
        self.window.events.loaded += self._on_loaded
        return self.window

    def started(self, background: bool) -> None:
        """Once the window exists (pywebview's thread): back where it was, its
        title bar as it last was, shown unless started at sign-in."""
        # pywebview shows a hidden window for a moment as it makes it.
        self.window.events.shown.wait()
        placement = self.state.get("placement")
        if placement:
            win32.set_placement(self.hwnd, placement)
        if "title_bar" in self.state:
            self.paint_title_bar(**self.state["title_bar"])
        if not background:
            win32.show(self.hwnd, maximized=bool(placement and placement["maximized"]))
        threading.Thread(target=self._count_nudges, name="taskbar-badge", daemon=True).start()
        self.tray.start()

    def _on_loaded(self) -> None:
        # pywebview keeps WebView2's context menu (the spelling suggestions)
        # and its keys (find, print, reload) for debugging; they are the app's.
        from System import Func, Type  # pythonnet, there with pywebview's WinForms

        form = self.window.native

        def enable() -> None:
            settings = form.webview.CoreWebView2.Settings
            settings.AreDefaultContextMenusEnabled = True
            settings.AreBrowserAcceleratorKeysEnabled = True

        form.Invoke(Func[Type](enable))

    def _on_closing(self) -> bool:
        # Signing out or shutting down closes it for good, else Windows would
        # wait on a window that only hid.
        if win32.session_ending():
            self.quitting = True
            self.tray.stop()
        if self.quitting:
            return True
        self.state["placement"] = win32.get_placement(self.hwnd)
        self.window.hide()
        if not self.state.get("told_tray"):
            self.state["told_tray"] = True
            self.tray.notify(
                f"{NAME} is still running, for Claude and your reminders. "
                "Open it from here; Quit is on this icon's menu."
            )
        self._save_state()
        return False

    def open(self, path: str | None = None) -> None:
        """The window brought forward, at `path` when given."""
        if path:
            self.window.load_url(f"{self.url}{path}")
        maximized = self.state.get("placement", {}).get("maximized", False)
        win32.show(self.hwnd, maximized=maximized)
        self.badge_due.set()

    def new_task(self) -> None:
        """The capture window, over the page open (shell.js), else on Today."""
        opened = self.window.evaluate_js("window.openCapture ? window.openCapture() : false")
        if not opened:
            self.window.load_url(f"{self.url}/today?capture=1")
        self.open()

    def quit(self) -> None:
        self.quitting = True
        if self.window.native.Visible:
            self.state["placement"] = win32.get_placement(self.hwnd)
        self._save_state()
        self.tray.stop()
        self.window.destroy()

    def paint_title_bar(self, paper: str, ink: str, dark: bool, title: str | None = None) -> None:
        win32.paint_title_bar(self.hwnd, paper, ink, dark)
        if title:
            self.window.set_title(title)
        self.state["title_bar"] = {"paper": paper, "ink": ink, "dark": dark}

    # ---- the nudges waiting: a number on the taskbar button, a dot on the tray icon ----

    def _count_nudges(self) -> None:
        from app.db import get_session_factory
        from app.services import nudges as nudges_svc

        try:
            badge = win32.TaskbarBadge()
        except OSError:
            log.exception("No taskbar badge")
            badge = None
        while not self.quitting:
            try:
                with get_session_factory()() as db:
                    count = len(nudges_svc.active_nudges(db))
                if badge:
                    badge.show(self.hwnd, count)
                self.tray.show_count(count)
            except Exception:
                log.exception("Counting the nudges failed")
            self.badge_due.wait(BADGE_SECONDS)
            self.badge_due.clear()


class Api:
    """What the page calls (window.pywebview.api, from shell.js)."""

    def __init__(self, shell: Shell) -> None:
        self._shell = shell

    def title_bar(self, paper: str, ink: str, dark: bool, title: str) -> None:
        self._shell.paint_title_bar(paper, ink, dark, title)

    def nudges_changed(self) -> None:
        self._shell.badge_due.set()


class OpenRequest(BaseModel):
    path: str | None = None


def control_router(shell: Shell) -> APIRouter:
    """Another launch of the app, or its installer, asking this one to come
    forward or to quit. From this machine only."""
    router = APIRouter(prefix="/desktop", include_in_schema=False)

    def local_only(request: Request) -> None:
        if request.client is None or request.client.host != "127.0.0.1":
            raise HTTPException(status_code=403)

    @router.post("/open")
    def open_window(body: OpenRequest, request: Request) -> dict:
        local_only(request)
        if body.path is not None and not body.path.startswith("/"):
            raise HTTPException(status_code=422)
        shell.open(body.path)
        return {"ok": True}

    @router.post("/quit")
    def quit_app(request: Request) -> dict:
        local_only(request)
        threading.Thread(target=shell.quit, name="quit", daemon=True).start()
        return {"ok": True}

    return router


def _forward(url: str, path: str | None) -> bool:
    """Whether the running instance took the request to come forward (at
    `path`); False while it is not answering, starting or quitting."""
    win32.allow_any_foreground()
    try:
        httpx.post(f"{url}/desktop/open", json={"path": path}, timeout=5).raise_for_status()
    except httpx.TransportError:
        return False
    except httpx.HTTPStatusError as exc:
        log.error("Opening the running app failed: %s", exc)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(prog="personal-calendar-desktop")
    parser.add_argument("--background", action="store_true", help="start in the tray")
    parser.add_argument("--open", metavar="PATH", help="a page to open, e.g. /calendar")
    args = parser.parse_args()

    settings = get_settings()
    url = f"http://127.0.0.1:{settings.server.port}"
    win32.set_app_id(APP_ID)
    # Already running: that one comes forward. One quitting as this starts
    # leaves the claim to this one.
    deadline = time.monotonic() + 60
    while not win32.claim_single_instance(MUTEX):
        if args.background or _forward(url, args.open):
            return
        if time.monotonic() > deadline:
            win32.message_box(NAME, f"{NAME} is running but not answering at {url}.")
            return
        time.sleep(0.5)
    win32.no_console_windows()

    from app import migrate, serve

    try:
        app = serve.prepare()
    except migrate.DatabaseTooNew as exc:
        win32.message_box(NAME, f"This version of {NAME} is older than its data.\n\n{exc}")
        return
    except Exception as exc:
        log.exception("Could not start")
        win32.message_box(NAME, f"{NAME} could not start.\n\n{exc}\n\nLog: {serve.log_path()}")
        return

    shell = Shell(url, settings.db_path.parent / "desktop.json")
    app.include_router(control_router(shell))
    servers = serve.Servers(app)
    servers.start()
    if not servers.wait_started():
        servers.stop("could not serve")
        win32.message_box(
            NAME,
            f"{NAME} could not serve on {url}: is another copy of it running?\n\n"
            f"Log: {serve.log_path()}",
        )
        return

    shell.create_window()
    webview.start(
        shell.started,
        args.background,
        private_mode=False,
        storage_path=str(settings.db_path.parent / "webview"),
        icon=str(ICON),
    )
    servers.stop("quit from the tray")
    servers.join()
    log.info("Stopped")
