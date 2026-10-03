import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.desktop import control_router, tray, win32


class FakeShell:
    def __init__(self) -> None:
        self.opened: list[str | None] = []
        self.quit_called = False

    def open(self, path: str | None = None) -> None:
        self.opened.append(path)

    def quit(self) -> None:
        self.quit_called = True


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


def test_only_a_page_of_the_app_opens() -> None:
    shell = FakeShell()
    assert client(shell).post("/desktop/open", json={"path": "https://x.test"}).status_code == 422
    assert shell.opened == []


def test_the_window_answers_this_machine_only() -> None:
    shell = FakeShell()
    phone = client(shell, host="100.64.0.2")
    assert phone.post("/desktop/open", json={"path": "/today"}).status_code == 403
    assert phone.post("/desktop/quit").status_code == 403
    assert shell.opened == [] and not shell.quit_called


def test_the_installer_can_ask_it_to_quit() -> None:
    shell = FakeShell()
    assert client(shell).post("/desktop/quit").status_code == 200
    # On a thread of its own, so the answer goes out before the server stops.
    for _ in range(100):
        if shell.quit_called:
            break
        time.sleep(0.01)
    assert shell.quit_called


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


def test_title_bar_colours_are_windows_colorrefs() -> None:
    assert win32._colorref("#14111e") == 0x1E1114
    assert win32._colorref("#fff") == 0xFFFFFF
