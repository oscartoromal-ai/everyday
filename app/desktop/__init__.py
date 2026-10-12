"""The desktop app: Personal Calendar as a Windows program of its own.

One process holds everything: the server (serve.py, on 127.0.0.1:8377 as
always, so Claude's MCP and the phone reach it), its scheduler, and the window,
an Edge WebView2 onto the server's pages. Closing the window hides it to the
tray, where the app keeps running; Quit, on the tray icon's menu, ends it. It
starts hidden at sign-in (--background, from the installer's Run entry).

It starts its window first, on a placeholder in the page's paper, and loads
the server's code and starts serving while WebView2 starts, the slowest two
things it does side by side; then it opens the page.

Its data lives in its home (config.py): %LOCALAPPDATA%/Personal Calendar when
installed, the database created and migrated as it starts. Launching it again
while it runs brings its window forward (--open <path> at a page), through
/desktop on the running one's server.

Restarting on an update (update.py) hands over between two processes: the
updated version, started ahead to stand by with its code and window loaded
(standby.py), is told to go; this one stops serving and gives up its claim,
and the new one comes up where this window is, at its page, over it, then
tells this one to go. The window never leaves the screen, and the server is
away only while the new one migrates and binds.

Entry point for the installed app (desktop/personal-calendar.spec) and for
`uv run personal-calendar-desktop` from the repo.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import webview
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.config import REPO_ROOT, get_settings
from app.desktop import update, win32
from app.desktop.standby import Handover, Standby, Waiting
from app.desktop.tray import Tray
from app.desktop.update import Updater, UpdateState

if TYPE_CHECKING:
    from app import serve

log = logging.getLogger(__name__)

NAME = "Personal Calendar"
APP_ID = "Oscar.PersonalCalendar"
MUTEX = "Local\\Oscar.PersonalCalendar"
# How long a version restarted on has to get ready (its code and window
# loaded), and then to come up (its database migrated, its page drawn).
HANDOFF_SECONDS = 90
# How long a version taking over waits for the one it replaces to let go.
CLAIM_SECONDS = 60
ICON = REPO_ROOT / "app" / "static" / "icons" / "app.ico"
# How often the nudges waiting are counted again, besides as they change.
BADGE_SECONDS = 60
# How soon a count the taskbar did not take is shown again: Windows gives up
# on the taskbar when it is slow to answer, as when the PC has just woken.
BADGE_RETRY_SECONDS = 5
# The languages Oscar writes in: a word is spelt right in any of them. WebView2
# checks with Windows' own spellers, so each needs Windows' basic typing
# feature for its language (Language.Basic~~~es-ES~0.0.1.0, as admin).
SPELLING = ["en-US", "es-ES"]
# What the window shows until its page is there.
PLACEHOLDER = '<!doctype html><html style="background:{paper}"><title>{name}</title></html>'


def instance_name(port: int) -> str:
    """What the app serving on `port` goes by, for its one-instance claim and
    its handoff: one app per port. The installed app's, on 8377, is the name
    its installer looks for."""
    return MUTEX if port == 8377 else f"{MUTEX}.{port}"


def claim(instance: str, timeout: float) -> bool:
    """Whether this app got the instance's claim within `timeout` seconds, as
    the one it takes over from lets go."""
    deadline = time.monotonic() + timeout
    while not win32.claim_single_instance(instance):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def _put_back() -> None:
    """A start that failed after migrating the database puts it back as it
    was, for the version before this one to start on (app/migrate.py)."""
    from app import migrate

    try:
        migrate.go_back(get_settings().db_path)
    except Exception:
        log.exception("Could not put the database back as it was before migrating")


class Shell:
    """The window and the tray icon, over the app's server at `url`."""

    def __init__(self, url: str, state_path: Path, instance: str) -> None:
        self.url = url
        self.state_path = state_path
        # The data folder, beside the window's state.
        self.data = state_path.parent
        self.instance = instance
        self.state = self._load_state()
        self.quitting = False
        self.quit_reason = "the window closed"
        self.badge_due = threading.Event()
        self.window: webview.Window | None = None
        self.tray = Tray(self)
        # Set once the window is where it belongs; until then another launch
        # waits to bring it forward.
        self.ready = threading.Event()
        # Started to stand by for the app restarting on it (standby.py).
        self.waiting: Waiting | None = None
        # Started by a version from before standbys, restarting on its update:
        # it waits on the handoff event, and this one waits for its claim.
        self.replacing = False
        self.servers: serve.Servers | None = None
        self.updater: Updater | None = None
        # The version started to stand by for the next restart; a restart
        # under way, which the watch leaves alone; the watch's end.
        self.standby: Standby | None = None
        self._standby_lock = threading.RLock()
        self._standby_failed: Path | None = None
        self.restarting = False
        self.watching = threading.Event()

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
        """The window, hidden, on its placeholder until started() opens the page."""
        paper = self.state.get("title_bar", {}).get("paper", "#ffffff")
        self.window = webview.create_window(
            NAME,
            html=PLACEHOLDER.format(paper=paper, name=NAME),
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
        self.window.state += self._on_page_report
        return self.window

    def started(self, background: bool, page: str) -> None:
        """The app brought up around its window (pywebview's thread, from as
        WebView2 starts): its server, its page, the window back where it was,
        its title bar as it last was, shown unless started at sign-in. A
        standby does it once told to go, where the app it replaces was."""
        try:
            self._bring_up(background, page)
        except Exception as exc:
            log.exception("Could not start")
            self._fail(f"{NAME} could not start.\n\n{exc}")

    def _bring_up(self, background: bool, page: str) -> None:
        if self.waiting:
            handover = self._stand_by()
            if handover is None:
                self.quit("not needed as a standby")
                return
            page, background = handover.page, handover.background
            if not self._serve():
                return
        else:
            served: list[bool] = []
            serving = threading.Thread(
                target=lambda: served.append(self._serve()), name="serve", daemon=True
            )
            serving.start()
            # pywebview shows a hidden window for a moment as it makes it.
            self.window.events.shown.wait()
            if not self.replacing:
                # On screen at once, in the page's paper, while it loads.
                self._place(background)
            serving.join()
            if not served or not served[0]:
                return
        # The placeholder drawn, so that the page's own load is waited on.
        self.window.events.loaded.wait(10)
        self.window.events.loaded.clear()
        self.window.load_url(f"{self.url}{page}")
        if self.waiting or self.replacing:
            # Over the window it replaces, its page drawn already.
            self.window.events.loaded.wait(30)
            self._place(background)
        self.ready.set()
        if self.waiting:
            self.waiting.up()
        if self.replacing:
            handoff = win32.Signal(f"{self.instance}.Handoff")
            handoff.set()
            handoff.close()
        self._settle_in()
        threading.Thread(target=self._count_nudges, name="taskbar-badge", daemon=True).start()
        if self.updater:
            threading.Thread(target=self._watch_updates, name="watch updates", daemon=True).start()
        self.tray.start()

    def _settle_in(self) -> None:
        """Up: the migration this start made, if any, confirmed, then this
        version made the installed one. Neither may take the app down, as
        the one it replaced is going: a failure is logged."""
        from app import migrate

        try:
            migrate.confirm(get_settings().db_path)
        except OSError:
            log.exception("Could not confirm the database's migration")
        info = update.build_info()
        if info:
            try:
                update.take_over(Path(sys.executable), info.get("version", info["commit"]))
            except OSError:
                log.exception("Could not make this version the installed one")

    def _place(self, background: bool) -> None:
        placement = self.state.get("placement")
        if placement:
            win32.set_placement(self.hwnd, placement)
        if "title_bar" in self.state:
            self.paint_title_bar(**self.state["title_bar"])
        if not background:
            self._show(maximized=bool(placement and placement["maximized"]))

    def _stand_by(self) -> Handover | None:
        """As a standby: its code loaded and its window up, Ready said, then
        once told to go, the app's claim taken over. Where to come up; None
        when not needed after all."""
        from app import serve

        serve.configure_logging(serve.log_path().with_name("standby.log"))
        self._load_server_code()
        self._warm()
        self.window.events.loaded.wait()
        log.info("Standing by")
        handover = self.waiting.wait_for_go()
        if handover is None:
            return None
        # The app's own log from now on, and the window's state as the app it
        # replaces left it.
        serve.configure_logging(serve.log_path())
        log.info("Taking over at %s", handover.page)
        self.state = self._load_state()
        if not claim(self.instance, CLAIM_SECONDS):
            log.error("The app restarting did not let go within %ss", CLAIM_SECONDS)
            return None
        return handover

    def _load_server_code(self) -> None:
        """The server's code imported: most of the time a start takes."""
        from app import migrate, serve  # noqa: F401
        from app.ui import views  # noqa: F401

    def _warm(self) -> None:
        """What its first page would do as it draws, done as it stands by:
        the templates compiled, and master's latest commit looked up for the
        Update button."""
        from app.ui.views import templates

        for name in templates.env.list_templates(extensions=["html"]):
            templates.env.get_template(name)
        self.updater = Updater.for_installed_app(get_settings().db_path.parent / "update.json")
        if self.updater:
            self.updater.latest()

    def _serve(self) -> bool:
        """Whether the app is serving: its database migrated, its routes and
        its Update button's added. Should it not, it says why and quits."""
        from app import migrate

        try:
            return self._start_serving()
        except migrate.DatabaseTooNew as exc:
            self._fail(f"This version of {NAME} is older than its data.\n\n{exc}")
        except Exception as exc:
            log.exception("Could not start")
            _put_back()
            self._fail(f"{NAME} could not start.\n\n{exc}")
        return False

    def _start_serving(self) -> bool:
        from app import serve

        self._load_server_code()
        app = serve.prepare()
        app.include_router(control_router(self))
        if self.updater is None:
            path = get_settings().db_path.parent / "update.json"
            self.updater = Updater.for_installed_app(path)
        if self.updater:
            from app.ui.views import templates

            self.updater.settle()
            self.updater.before_build = self._stop_standby
            templates.env.globals["app_update"] = self.updater.state
            templates.env.globals["app_updatable"] = lambda: True
            templates.env.globals["app_update_access"] = self.updater.access
            app.include_router(update_router(self.updater, self))
        self.servers = serve.Servers(app)
        self.servers.start()
        if not self.servers.wait_started():
            self.servers.stop("could not serve")
            self.servers.join(serve.STOP_SECONDS)
            _put_back()
            self._fail(f"{NAME} could not serve on {self.url}: is another copy of it running?")
            return False
        return True

    def _fail(self, message: str) -> None:
        """It cannot come up: lets go of its claim at once, says why, unless
        started for a restart (the app restarting on it carries on, and
        tells), and quits. Held behind the message, the claim kept the app
        restarting from falling back to its own version, and the app was
        down until the message was answered."""
        win32.release_single_instance()
        if not (self.waiting or self.replacing):
            from app import serve

            win32.message_box(NAME, f"{message}\n\nLog: {serve.log_path()}")
        self.window.events.shown.wait()
        self.quit("could not start")

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
        WebView2 was up already (pywebview hides a new window so; a standby
        has its browser running), it would stay blank."""
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

    # ---- updates: the watch, the standby, the restart ----

    def _watch_updates(self) -> None:
        """The updater's watch (update.py), and a standby kept on the version
        it staged, ready for Restart."""
        while not self.quitting:
            if not self.restarting:
                try:
                    self.updater.tick()
                    self._keep_standby(self.updater.staged())
                except Exception:
                    log.exception("Watching for updates failed")
            self.watching.wait(update.WATCH_SECONDS)

    def _keep_standby(self, exe: Path | None) -> None:
        """A standby on the staged version `exe`, none without one. One that
        ended by itself is not started again for the same version: Restart
        then starts it afresh, and says why it failed."""
        with self._standby_lock:
            if self.standby and (self.standby.exe != exe or not self.standby.alive()):
                if not self.standby.alive():
                    log.warning("The standby on %s ended by itself", self.standby.exe)
                    self._standby_failed = self.standby.exe
                self._stop_standby()
            wanted = exe and exe != self._standby_failed
            if wanted and self.standby is None and not (self.quitting or self.restarting):
                self.standby = Standby(exe, self.instance, self.data)

    def _stop_standby(self) -> None:
        with self._standby_lock:
            if self.standby:
                self.standby.stop()
                self.standby = None

    def _standby_on(self, exe: Path) -> Standby:
        """The standby on `exe`, taken for a restart: the one kept, else one
        started now."""
        with self._standby_lock:
            standby = self.standby
            self.standby = None
            if standby and standby.exe == exe and standby.alive():
                return standby
            if standby:
                standby.stop()
            return Standby(exe, self.instance, self.data)

    def restart(self, exe: Path, on_failure: Callable[[str], None]) -> None:
        """This app replaced by the updated one at `exe`, which comes up over
        this window, at its page. Should it not get ready, `on_failure` hears
        why and this one carries on; should it not come up once this one has
        stopped serving, this version starts again the same way."""
        from app import serve

        self.restarting = True
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
        handover = Handover(page, background=not visible)
        standby = self._standby_on(exe)
        if not standby.wait_ready(HANDOFF_SECONDS):
            standby.stop()
            on_failure(f"{exe} did not get ready within {HANDOFF_SECONDS}s")
            # Nothing stopped yet: the page back, its button saying so.
            self.restarting = False
            if self.updater:
                self.updater.release()
            self.window.evaluate_js("location.reload()")
            return
        if self._hand_over(standby, handover):
            self.quit("restarted on its update")
            return
        on_failure(f"{exe} did not come up within {HANDOFF_SECONDS}s")
        again = Standby(Path(sys.executable), self.instance, self.data)
        if again.wait_ready(HANDOFF_SECONDS) and self._hand_over(again, handover):
            self.quit("restarted after its update failed")
            return
        again.stop()
        win32.message_box(
            NAME, f"{NAME} could not restart. Open it again.\n\nLog: {serve.log_path()}"
        )
        self.quit("could not restart")

    def _hand_over(self, standby: Standby, handover: Handover) -> bool:
        """Whether the ready `standby` came up in this one's place; ended,
        should it not."""
        log.info("Handing over to %s", standby.exe)
        standby.go(handover)
        self.servers.stop("handing over to an update")
        self.servers.join()
        win32.release_single_instance()
        if standby.wait_up(HANDOFF_SECONDS):
            return True
        standby.stop()
        return False

    def quit(self, reason: str) -> None:
        self.quitting = True
        self.quit_reason = reason
        self.watching.set()
        self._stop_standby()
        if win32.is_visible(self.hwnd):
            self.state["placement"] = win32.get_placement(self.hwnd)
        if not self.waiting or self.ready.is_set():
            self._save_state()
        self.tray.stop()
        self.window.destroy()

    def _on_page_report(self, kind: str, key: str, value: Any) -> None:
        """What the page reports, setting pywebview's state (shell.js): the
        title bar it wants, and that a nudge was dismissed. The state's
        changes go one way, where a call to a js_api is answered, and an
        answer meant for a page left meanwhile throws in the next one."""
        if kind != "change":
            return
        if key == "titleBar":
            self.paint_title_bar(value["paper"], value["ink"], bool(value["dark"]), value["title"])
        elif key == "nudgeDismissed":
            self.badge_due.set()

    def paint_title_bar(self, paper: str, ink: str, dark: bool, title: str | None = None) -> None:
        win32.paint_title_bar(self.hwnd, paper, ink, dark)
        if title:
            self.window.set_title(title)
        self.state["title_bar"] = {"paper": paper, "ink": ink, "dark": dark}

    # ---- the nudges waiting: a number on the taskbar button, a dot on the tray icon ----

    def _count_nudges(self) -> None:
        try:
            badge = win32.TaskbarBadge()
        except OSError:
            log.exception("No taskbar badge")
            badge = None
        while not self.quitting:
            self.badge_due.wait(self._show_nudges(badge))
            self.badge_due.clear()

    def _show_nudges(self, badge: win32.TaskbarBadge | None) -> float:
        """The nudges waiting counted, on the tray icon and the taskbar
        button, and how long until they are counted again. A taskbar slow to
        answer is asked again soon, the tray icon counting meanwhile."""
        from app.db import get_session_factory
        from app.services import nudges as nudges_svc

        try:
            with get_session_factory()() as db:
                count = len(nudges_svc.on_today(db, date.today()))
            self.tray.show_count(count)
        except Exception:
            log.exception("Counting the nudges failed")
            return BADGE_SECONDS
        if badge:
            try:
                badge.show(self.hwnd, count)
            except OSError as exc:
                log.warning("The taskbar did not take the nudges' count, again in %ss: %s",
                            BADGE_RETRY_SECONDS, exc)
                return BADGE_RETRY_SECONDS
        return BADGE_SECONDS


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

    def check_panel(
        request: Request, state, checked: bool = False, why: str | None = None  # noqa: ANN001
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "partials/update_check.html",
            {"update": state, "checked": checked, "why": why, "oob": checked,
             "access": updater.access()},
        )

    @router.get("/update/check", response_class=HTMLResponse)
    def show_check(request: Request) -> HTMLResponse:
        return check_panel(request, updater.state())

    # Settings' Check for updates: the latest release looked at now and a
    # newer one's update started; the rail's button (swapped out of band)
    # follows it.
    @router.post("/update/check", response_class=HTMLResponse)
    def check(request: Request) -> HTMLResponse:
        state, why = updater.check()
        return check_panel(request, state, checked=True, why=why)

    # A token for GitHub to show the releases to, pasted in Settings, then
    # checked as Check for updates would.
    @router.post("/update/access", response_class=HTMLResponse)
    def access(request: Request, token: str = Form("")) -> HTMLResponse:
        updater.keep_token(token)
        state, why = updater.check()
        return check_panel(request, state, checked=True, why=why)

    @router.post("/restart", response_class=HTMLResponse)
    def restart(request: Request) -> HTMLResponse:
        # Nothing built from now on: a build would replace what it restarts on.
        exe = updater.hold()
        state = updater.state()
        if state is None or exe is None:
            updater.release()
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
    # Only here: the start that serves has no need of it so soon.
    import httpx

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
    # Started ahead of a restart by the app with this process id, by the id
    # it gave it (standby.py).
    parser.add_argument("--standby", nargs=2, metavar=("PID", "ID"), help=argparse.SUPPRESS)
    # From a version before standbys restarting on its update: wait for it to let go.
    parser.add_argument("--replacing", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    opened = args.open if args.open and args.open.startswith("/") else None

    settings = get_settings()
    url = f"http://127.0.0.1:{settings.server.port}"
    win32.set_app_id(APP_ID)
    instance = instance_name(settings.server.port)
    if args.replacing:
        if not claim(instance, CLAIM_SECONDS):
            # The app restarting carries on.
            return
    elif args.standby is None:
        # Already running: that one comes forward. One quitting as this starts
        # leaves the claim to this one.
        deadline = time.monotonic() + 60
        while not win32.claim_single_instance(instance):
            if args.background or _forward(url, opened):
                return
            if time.monotonic() > deadline:
                win32.message_box(NAME, f"{NAME} is running but not answering at {url}.")
                return
            time.sleep(0.5)
    win32.no_console_windows()

    shell = Shell(url, settings.db_path.parent / "desktop.json", instance)
    shell.replacing = args.replacing
    if args.standby is not None:
        parent, standby_id = args.standby
        shell.waiting = Waiting(instance, int(parent), standby_id, shell.data)
    storage = settings.db_path.parent / "webview"
    spell_in(storage, SPELLING)
    shell.create_window()
    webview.start(
        shell.started,
        (args.background, opened or "/today"),
        private_mode=False,
        storage_path=str(storage),
        icon=str(ICON),
    )
    shell.watching.set()
    if shell.servers:
        shell.servers.stop(f"quit: {shell.quit_reason}")
        shell.servers.join()
    log.info("Stopped")
    # Ended now: Python's own exit unloads .NET (pythonnet), which takes 10 to
    # 25 seconds while the claim stays held, so a launch meanwhile, or the
    # installer, would wait for it.
    logging.shutdown()
    os._exit(0)
