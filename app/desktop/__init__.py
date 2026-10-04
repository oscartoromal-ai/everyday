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

Restarting on an update (update.py) hands over between two processes: the
updated app starts (--replacing), this one stops serving and gives up its
claim, and the new one comes up where this window is, at its page, over it,
then tells this one to go (the handoff event). The window never leaves the
screen, and the server is away only while the new one starts.

Entry point for the installed app (desktop/personal-calendar.spec) and for
`uv run personal-calendar-desktop` from the repo.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import webview
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.config import REPO_ROOT, get_settings
from app.desktop import update, win32
from app.desktop.tray import Tray
from app.desktop.update import Updater, UpdateState

if TYPE_CHECKING:
    from app import serve

log = logging.getLogger(__name__)

NAME = "Personal Calendar"
APP_ID = "Oscar.PersonalCalendar"
MUTEX = "Local\\Oscar.PersonalCalendar"
# How long an updated app has to come up: its start, its database migrated.
HANDOFF_SECONDS = 90
ICON = REPO_ROOT / "app" / "static" / "icons" / "app.ico"
# How often the nudges waiting are counted again, besides as they change.
BADGE_SECONDS = 60
# The languages Oscar writes in: a word is spelt right in any of them. WebView2
# checks with Windows' own spellers, so each needs Windows' basic typing
# feature for its language (Language.Basic~~~es-ES~0.0.1.0, as admin).
SPELLING = ["en-US", "es-ES"]


def instance_name(port: int) -> str:
    """What the app serving on `port` goes by, for its one-instance claim and
    its handoff: one app per port. The installed app's, on 8377, is the name
    its installer looks for."""
    return MUTEX if port == 8377 else f"{MUTEX}.{port}"


class Shell:
    """The window and the tray icon, over the app's server at `url`."""

    def __init__(self, url: str, state_path: Path, instance: str) -> None:
        self.url = url
        self.state_path = state_path
        # Set by an updated app once its window is up, for the one it
        # replaces to go.
        self.handoff_name = f"{instance}.Handoff"
        self.state = self._load_state()
        self.quitting = False
        self.quit_reason = "the window closed"
        self.badge_due = threading.Event()
        self.window: webview.Window | None = None
        self.tray = Tray(self)
        # Set once the window is where it belongs; until then another launch
        # waits to bring it forward.
        self.ready = threading.Event()
        # Started to take over from an app restarting on its update.
        self.replacing = False
        self.servers: serve.Servers | None = None

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

    def create_window(self, path: str = "/today") -> webview.Window:
        paper = self.state.get("title_bar", {}).get("paper", "#ffffff")
        self.window = webview.create_window(
            NAME,
            f"{self.url}{path}",
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
        if self.replacing:
            # Over the window it replaces, its page drawn already.
            self.window.events.loaded.wait(30)
        placement = self.state.get("placement")
        if placement:
            win32.set_placement(self.hwnd, placement)
        if "title_bar" in self.state:
            self.paint_title_bar(**self.state["title_bar"])
        if not background:
            self._show(maximized=bool(placement and placement["maximized"]))
        self.ready.set()
        if self.replacing:
            handoff = win32.Signal(self.handoff_name)
            handoff.set()
            handoff.close()
        info = update.build_info()
        if info:
            update.take_over(Path(sys.executable), info.get("version", info["commit"]))
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
            self.quit_reason = "Windows signing out"
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

    def _show(self, maximized: bool) -> None:
        """The window on screen and in front, and WinForms told so: WebView2
        draws the page only while its control is visible to WinForms, which
        Windows' own showing leaves unaware. Hidden through WinForms while
        WebView2 was up already (pywebview hides a new window so; an app
        restarting on its update has its browser running), it would stay
        blank."""
        win32.show(self.hwnd, maximized=maximized)
        self.window.show()

    def open(self, path: str | None = None) -> None:
        """The window brought forward, at `path` when given."""
        if path:
            self.window.load_url(f"{self.url}{path}")
        maximized = self.state.get("placement", {}).get("maximized", False)
        self._show(maximized=maximized)
        self.badge_due.set()

    def new_task(self) -> None:
        """The capture window, over the page open (shell.js), else on Today."""
        opened = self.window.evaluate_js("window.openCapture ? window.openCapture() : false")
        if not opened:
            self.window.load_url(f"{self.url}/today?capture=1")
        self.open()

    def restart(self, exe: Path, on_failure: Callable[[str], None]) -> None:
        """This app replaced by the updated one at `exe`, which comes up over
        this window, at its page. Should it not, `on_failure` hears why and
        this version starts again the same way."""
        from app import serve

        visible = win32.is_visible(self.hwnd)
        current = self.window.get_current_url() or ""
        page = current[len(self.url):] if current.startswith(f"{self.url}/") else "/today"
        if visible:
            self.state["placement"] = win32.get_placement(self.hwnd)
        self._save_state()
        # Nothing done in this window from now on would be kept.
        self.window.evaluate_js(
            "document.documentElement.dataset.restarting = ''; document.body.inert = true"
        )
        handoff = win32.Signal(self.handoff_name)
        handoff.reset()
        try:
            if self._hand_over(exe, page, visible, handoff):
                self.quit("restarted on its update")
                return
            on_failure(f"{exe} did not come up within {HANDOFF_SECONDS}s")
            if self._hand_over(Path(sys.executable), page, visible, handoff):
                self.quit("restarted after its update failed")
                return
            win32.message_box(
                NAME, f"{NAME} could not restart. Open it again.\n\nLog: {serve.log_path()}"
            )
            self.quit("could not restart")
        finally:
            handoff.close()

    def _hand_over(self, exe: Path, page: str, visible: bool, handoff: win32.Signal) -> bool:
        """Whether the app at `exe` came up in this one's place."""
        args = [str(exe), "--replacing", "--open", page]
        if not visible:
            args.append("--background")
        log.info("Handing over to %s", exe)
        process = subprocess.Popen(
            args,
            # One frozen app starting another: that one sets itself up afresh.
            env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        win32.allow_foreground(process.pid)
        # It starts meanwhile, and waits for the port and the claim.
        self.servers.stop("handing over to an update")
        self.servers.join()
        win32.release_single_instance()
        return handoff.wait_unless_exited(process.pid, HANDOFF_SECONDS)

    def quit(self, reason: str) -> None:
        self.quitting = True
        self.quit_reason = reason
        if win32.is_visible(self.hwnd):
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
        if not shell.ready.is_set():
            # Starting: the launch asking waits and asks again.
            raise HTTPException(status_code=503)
        shell.open(body.path)
        return {"ok": True}

    @router.post("/quit")
    def quit_app(request: Request) -> dict:
        local_only(request)
        threading.Thread(
            target=shell.quit, args=("asked to (an installer)",), name="quit", daemon=True
        ).start()
        return {"ok": True}

    return router


def update_router(updater: Updater, shell: Shell) -> APIRouter:
    """The Update button's: what it shows, starting the update, and
    restarting on it once it is staged."""
    from app.ui.views import templates

    router = APIRouter(prefix="/ui/desktop", include_in_schema=False)

    def button(request: Request, state) -> HTMLResponse:  # noqa: ANN001
        return templates.TemplateResponse(
            request, "partials/update_button.html", {"update": state}
        )

    @router.get("/update", response_class=HTMLResponse)
    def show(request: Request) -> HTMLResponse:
        return button(request, updater.state())

    @router.post("/update", response_class=HTMLResponse)
    def start(request: Request) -> HTMLResponse:
        return button(request, updater.start())

    @router.post("/restart", response_class=HTMLResponse)
    def restart(request: Request) -> HTMLResponse:
        state = updater.state()
        exe = updater.staged()
        if state is None or exe is None:
            return button(request, state)

        def failed(why: str) -> None:
            from app import serve

            updater.failed(why, serve.log_path())

        # On a thread of its own: it stops the server answering this.
        threading.Thread(target=shell.restart, args=(exe, failed), name="restart").start()
        return button(request, UpdateState("restarting", state.installed, state.latest))

    return router


def spell_in(storage: Path, languages: list[str]) -> None:
    """The window's spellchecker set to `languages`, in its browser profile's
    preferences, while no browser has it open. WebView2 has no call for it,
    and it prunes the plain dictionaries to its one UI language as it starts;
    forced ones (what Edge's SpellcheckLanguage policy sets) it keeps."""
    prefs_path = storage / "EBWebView" / "Default" / "Preferences"
    try:
        prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prefs = {}
    spellcheck = prefs.setdefault("spellcheck", {})
    if spellcheck.get("forced_dictionaries") == languages:
        return
    spellcheck["forced_dictionaries"] = languages
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(json.dumps(prefs), encoding="utf-8")


def _forward(url: str, path: str | None) -> bool:
    """Whether the running instance took the request to come forward (at
    `path`); False while it is not answering, starting or quitting."""
    win32.allow_any_foreground()
    try:
        httpx.post(f"{url}/desktop/open", json={"path": path}, timeout=5).raise_for_status()
    except httpx.TransportError:
        return False
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 503:
            return False
        log.error("Opening the running app failed: %s", exc)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(prog="personal-calendar-desktop")
    parser.add_argument("--background", action="store_true", help="start in the tray")
    parser.add_argument("--open", metavar="PATH", help="a page to open, e.g. /calendar")
    # From an app restarting on its update (Shell.restart): wait for it to let go.
    parser.add_argument("--replacing", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    page = args.open if args.open and args.open.startswith("/") else None

    settings = get_settings()
    url = f"http://127.0.0.1:{settings.server.port}"
    win32.set_app_id(APP_ID)
    # Already running: that one comes forward. One quitting as this starts
    # leaves the claim to this one.
    deadline = time.monotonic() + 60
    instance = instance_name(settings.server.port)
    while not win32.claim_single_instance(instance):
        if args.replacing:
            if time.monotonic() > deadline:
                # The app restarting carries on.
                return
            time.sleep(0.05)
            continue
        if args.background or _forward(url, page):
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

    shell = Shell(url, settings.db_path.parent / "desktop.json", instance)
    shell.replacing = args.replacing
    app.include_router(control_router(shell))
    updater = Updater.for_installed_app(settings.db_path.parent / "update.json")
    if updater:
        from app.ui.views import templates

        updater.settle()
        templates.env.globals["app_update"] = updater.state
        app.include_router(update_router(updater, shell))
    servers = shell.servers = serve.Servers(app)
    servers.start()
    if not servers.wait_started():
        servers.stop("could not serve")
        win32.message_box(
            NAME,
            f"{NAME} could not serve on {url}: is another copy of it running?\n\n"
            f"Log: {serve.log_path()}",
        )
        return

    storage = settings.db_path.parent / "webview"
    spell_in(storage, SPELLING)
    shell.create_window(page or "/today")
    webview.start(
        shell.started,
        args.background,
        private_mode=False,
        storage_path=str(storage),
        icon=str(ICON),
    )
    servers.stop(f"quit: {shell.quit_reason}")
    servers.join()
    log.info("Stopped")
