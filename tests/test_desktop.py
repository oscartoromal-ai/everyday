import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.desktop import control_router, spell_in, tray, win32


class FakeShell:
    def __init__(self) -> None:
        self.opened: list[str | None] = []
        self.quit_reason: str | None = None
        self.ready = threading.Event()
        self.ready.set()

    def open(self, path: str | None = None) -> None:
        self.opened.append(path)

    def quit(self, reason: str) -> None:
        self.quit_reason = reason


def client(shell: FakeShell, host: str = "127.0.0.1") -> TestClient:
    app = FastAPI()
    app.include_router(control_router(shell))
    return TestClient(app, client=(host, 50000))


def test_another_launch_brings_the_window_forward_at_its_page() -> None:
    shell = FakeShell()
    c = client(shell)
    assert c.post("/desktop/open", json={"path": "/calendar"}).status_code == 200
    assert c.post("/desktop/open", json={"path": None}).status_code == 200
    assert shell.opened == ["/calendar", None]


def test_a_launch_while_the_window_is_still_coming_up_is_asked_to_wait() -> None:
    shell = FakeShell()
    shell.ready.clear()
    assert client(shell).post("/desktop/open", json={"path": None}).status_code == 503
    assert shell.opened == []


def test_only_a_page_of_the_app_opens() -> None:
    shell = FakeShell()
    assert client(shell).post("/desktop/open", json={"path": "https://x.test"}).status_code == 422
    assert shell.opened == []


def test_the_window_answers_this_machine_only() -> None:
    shell = FakeShell()
    phone = client(shell, host="100.64.0.2")
    assert phone.post("/desktop/open", json={"path": "/today"}).status_code == 403
    assert phone.post("/desktop/quit").status_code == 403
    assert shell.opened == [] and shell.quit_reason is None


def test_the_installer_can_ask_it_to_quit() -> None:
    shell = FakeShell()
    assert client(shell).post("/desktop/quit").status_code == 200
    # On a thread of its own, so the answer goes out before the server stops.
    for _ in range(100):
        if shell.quit_reason:
            break
        time.sleep(0.01)
    assert shell.quit_reason == "asked to (an installer)"


def test_a_version_up_confirms_its_migration_and_outlives_a_failed_take_over(monkeypatch) -> None:
    # The app it replaced is going by now: failing to take over the install
    # must not take this one down too.
    import app.desktop as desktop
    from app import migrate

    did: list[str] = []
    monkeypatch.setattr(migrate, "confirm", lambda path: did.append("confirmed"))
    monkeypatch.setattr(desktop.update, "build_info", lambda: {"commit": "2222222"})

    def held(exe: Path, version: str) -> None:
        raise PermissionError(13, "The process cannot access the file", "current.txt")

    monkeypatch.setattr(desktop.update, "take_over", held)

    desktop.Shell._settle_in(object.__new__(desktop.Shell))

    assert did == ["confirmed"]


def test_a_start_that_fails_puts_the_database_back(monkeypatch) -> None:
    import app.desktop as desktop
    from app import migrate
    from app.config import get_settings

    put_back: list[Path] = []
    monkeypatch.setattr(migrate, "go_back", lambda path: put_back.append(path) or True)
    desktop._put_back()
    assert put_back == [get_settings().db_path]

    # Nor does one that cannot put it back take the start's failure further.
    def locked(path: Path) -> bool:
        raise PermissionError(13, "The process cannot access the file", str(path))

    monkeypatch.setattr(migrate, "go_back", locked)
    desktop._put_back()


def test_a_start_that_fails_lets_go_of_its_claim_before_any_message(monkeypatch) -> None:
    # On 2026-10-08 an update that could not migrate held the claim behind
    # its message, so the version it replaced could not start again, and
    # the app was down until the message was answered.
    import app.desktop as desktop

    did: list[str] = []
    monkeypatch.setattr(desktop.win32, "release_single_instance", lambda: did.append("let go"))
    monkeypatch.setattr(desktop.win32, "message_box", lambda title, text: did.append("told"))

    def failing(replacing: bool) -> desktop.Shell:
        shell = object.__new__(desktop.Shell)
        shell.waiting, shell.replacing = None, replacing
        shell.window = SimpleNamespace(events=SimpleNamespace(shown=threading.Event()))
        shell.window.events.shown.set()
        shell.quit = lambda reason: did.append(reason)
        return shell

    failing(replacing=False)._fail("It could not start.")
    assert did == ["let go", "told", "could not start"]

    # Started by the version restarting on it, which carries on and tells.
    did.clear()
    failing(replacing=True)._fail("It could not start.")
    assert did == ["let go", "could not start"]


def test_the_taskbar_badge_counts_to_nine_then_nine_plus() -> None:
    for count in (1, 9, 10, 99):
        image = win32.badge_image(count, 24)
        assert image.size == (24, 24)
        # A disc: spark at its middle, clear at its corners.
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((12, 3))[:3] == win32.SPARK


def test_the_tray_icon_takes_a_dot_and_keeps_its_drawing() -> None:
    base = Image.new("RGBA", (24, 24), (255, 255, 255, 255))
    dotted = tray.with_dot(base)
    assert dotted.size == base.size
    assert dotted.getpixel((18, 6))[:3] == win32.SPARK  # the dot's middle
    assert dotted.getpixel((2, 20)) == base.getpixel((2, 20))


def test_the_handoff_signal_is_seen_by_the_app_waiting_on_it() -> None:
    name = f"Local\\PersonalCalendarTest.{uuid.uuid4()}"
    waiting, setting = win32.Signal(name), win32.Signal(name)
    try:
        assert not waiting.wait_unless_exited(os.getpid(), timeout=0.05)
        threading.Timer(0.1, setting.set).start()
        assert waiting.wait_unless_exited(os.getpid(), timeout=5)
        waiting.reset()
        assert not waiting.wait_unless_exited(os.getpid(), timeout=0.05)
    finally:
        waiting.close()
        setting.close()


def test_the_handoff_wait_ends_when_the_new_app_exits_without_signalling() -> None:
    signal = win32.Signal(f"Local\\PersonalCalendarTest.{uuid.uuid4()}")
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        started = time.monotonic()
        assert not signal.wait_unless_exited(process.pid, timeout=30)
        assert time.monotonic() - started < 15
    finally:
        process.wait()
        signal.close()


def test_the_page_reports_to_the_window_without_an_answer_to_miss(monkeypatch) -> None:
    # Whatever the window evaluates lands in the page open then: an answer
    # to a js_api call made from Today, arriving as Calendar opens, threw
    # there (error:413a7f47bf31). The page's reports are pywebview's state,
    # through its own bridge, which answers nothing back.
    from webview.errors import JavascriptException
    from webview.state import State
    from webview.util import js_bridge_call

    from app import desktop

    evaluated: list[str] = []

    class Window:
        events = SimpleNamespace(loaded=threading.Event())

        def run_js(self, script: str) -> None:
            evaluated.append(script)

        def evaluate_js(self, script: str) -> None:
            evaluated.append(script)
            raise JavascriptException({"message": "the page has gone"})

    shell = object.__new__(desktop.Shell)
    shell.badge_due = threading.Event()
    painted = threading.Event()
    calls: list[tuple] = []

    def paint(*args) -> None:
        calls.append(args)
        painted.set()

    monkeypatch.setattr(shell, "paint_title_bar", paint)
    window = Window()
    window.state = State(window)
    window.state += shell._on_page_report

    bar = {"paper": "#14111e", "ink": "#ece6f5", "dark": True, "title": "Calendar"}
    js_bridge_call(window, "pywebviewStateUpdate", {"key": "titleBar", "value": bar}, "1")
    js_bridge_call(window, "pywebviewStateUpdate", {"key": "nudgeDismissed", "value": 1}, "2")
    assert painted.wait(5)
    assert shell.badge_due.wait(5)
    assert calls == [("#14111e", "#ece6f5", True, "Calendar")]
    assert evaluated == []


def test_title_bar_colours_are_windows_colorrefs() -> None:
    assert win32._colorref("#14111e") == 0x1E1114
    assert win32._colorref("#fff") == 0xFFFFFF


def test_the_window_spells_in_english_and_spanish_and_keeps_its_other_preferences(
    tmp_path: Path,
) -> None:
    prefs = tmp_path / "EBWebView" / "Default" / "Preferences"
    spell_in(tmp_path, ["en-US", "es-ES"])  # a first start: no profile yet
    spelling = json.loads(prefs.read_text())["spellcheck"]
    assert spelling["forced_dictionaries"] == ["en-US", "es-ES"]

    prefs.write_text(json.dumps({"spellcheck": {"dictionaries": ["en-US"]}, "zoom": 1}))
    spell_in(tmp_path, ["en-US", "es-ES"])
    assert json.loads(prefs.read_text()) == {
        "spellcheck": {"dictionaries": ["en-US"], "forced_dictionaries": ["en-US", "es-ES"]},
        "zoom": 1,
    }
