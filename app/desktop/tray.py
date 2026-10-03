"""The desktop app's tray icon: where it lives while its window is closed.

A click opens the window; the menu goes straight to a page or a new task, or
quits the app. A spark dot on the icon, and its tooltip, tell of nudges
waiting.
"""

from __future__ import annotations

import ctypes
import threading
from typing import TYPE_CHECKING

import pystray
from PIL import Image, ImageDraw
from pystray._util import serialized_image
from pystray._util import win32 as pystray_win32

if TYPE_CHECKING:
    from app.desktop import Shell

SM_CXSMICON = 49


class _Icon(pystray.Icon):
    # pystray loads its icon at the large size (32 pixels at 100%) for the
    # tray to shrink; this loads the image as drawn, at the tray's own size.
    def _assert_icon_handle(self) -> None:
        if self._icon_handle:
            return
        size = self.icon.width
        with serialized_image(self.icon, "ICO") as path:
            self._icon_handle = pystray_win32.LoadImage(
                None, path, pystray_win32.IMAGE_ICON, size, size, pystray_win32.LR_LOADFROMFILE
            )


class Tray:
    def __init__(self, shell: Shell) -> None:
        from app.desktop import ICON, NAME

        self.shell = shell
        self.name = NAME
        self.count = 0
        size = ctypes.windll.user32.GetSystemMetrics(SM_CXSMICON) or 16
        with Image.open(ICON) as ico:
            # The icon as drawn at the tray's size, else the next one up.
            sizes = sorted(ico.info["sizes"])
            ico.size = next((s for s in sizes if s[0] >= size), sizes[-1])
            self.base = ico.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        menu = pystray.Menu(
            pystray.MenuItem(f"Open {NAME}", lambda: shell.open(), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Today", lambda: shell.open("/today")),
            pystray.MenuItem("Calendar", lambda: shell.open("/calendar")),
            pystray.MenuItem("Projects", lambda: shell.open("/projects")),
            pystray.MenuItem("New task", lambda: shell.new_task()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Quit {NAME}", lambda: shell.quit("from the tray")),
        )
        self.icon = _Icon("personal-calendar", self.base, NAME, menu)

    def start(self) -> None:
        threading.Thread(target=self.icon.run, name="tray", daemon=True).start()

    def stop(self) -> None:
        self.icon.stop()

    def notify(self, message: str) -> None:
        self.icon.notify(message, self.name)

    def show_count(self, count: int) -> None:
        if count == self.count:
            return
        self.count = count
        self.icon.icon = with_dot(self.base) if count else self.base
        waiting = f"{count} nudge{'s' if count != 1 else ''} waiting"
        self.icon.title = f"{self.name}: {waiting}" if count else self.name


def with_dot(base: Image.Image) -> Image.Image:
    """The icon with a spark dot at its top right, ringed in white to stand
    clear of its strokes. The dot is drawn four times over and scaled down,
    for clean edges; the icon under it stays as drawn."""
    from app.desktop.win32 import SPARK

    scale = 4
    size = base.width * scale
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    d = size * 0.5
    ring = size * 0.07
    draw.ellipse((size - d, 0, size - 1, d - 1), fill="white")
    draw.ellipse((size - d + ring, ring, size - 1 - ring, d - 1 - ring), fill=SPARK)
    layer = layer.resize(base.size, Image.Resampling.LANCZOS)
    return Image.alpha_composite(base, layer)
