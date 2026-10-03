"""The Windows calls the desktop app makes, through ctypes: one instance at a
time, its taskbar identity, its title bar's colours, the number on its taskbar
button, and no console windows for the programs it runs."""

from __future__ import annotations

import ctypes
import subprocess
import tempfile
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi
ole32 = ctypes.windll.ole32
shell32 = ctypes.windll.shell32

ERROR_ALREADY_EXISTS = 183
ASFW_ANY = -1
SW_HIDE, SW_SHOWNORMAL, SW_SHOWMAXIMIZED, SW_RESTORE = 0, 1, 3, 9
MB_ICONERROR = 0x10
CREATE_NO_WINDOW = 0x08000000
SM_SHUTTINGDOWN = 0x2000

_mutex = None


def claim_single_instance(name: str) -> bool:
    """Whether this is the only instance running; the claim lasts as long as
    the process does. One that is not lets go at once, so the mutex never
    outlives the instance that holds it."""
    global _mutex
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, name)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _mutex = handle
    return True


def allow_any_foreground() -> None:
    """Let the running instance take the foreground this one has, as the user
    launched it."""
    user32.AllowSetForegroundWindow(ASFW_ANY)


def set_app_id(app_id: str) -> None:
    """The taskbar groups the windows by this id, the one its Start menu
    shortcut carries, so a pinned icon is the running app's."""
    shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


def session_ending() -> bool:
    """Whether Windows is signing out or shutting down."""
    return bool(user32.GetSystemMetrics(SM_SHUTTINGDOWN))


def message_box(title: str, text: str) -> None:
    user32.MessageBoxW(None, text, title, MB_ICONERROR)


def no_console_windows() -> None:
    """A windowed app's console programs (Claude Code, for the chats) would
    each open a console window; they run without one."""
    original = subprocess.Popen.__init__

    def __init__(self, *args, creationflags: int = 0, **kwargs) -> None:  # noqa: ANN001, N807
        original(self, *args, creationflags=creationflags | CREATE_NO_WINDOW, **kwargs)

    subprocess.Popen.__init__ = __init__


# ---- the window -------------------------------------------------------------

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def _colorref(hex_color: str) -> int:
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return r | (g << 8) | (b << 16)


def paint_title_bar(hwnd: int, paper: str, ink: str, dark: bool) -> None:
    """The title bar in the page's paper and ink, its buttons drawn for a dark
    or light bar (Windows 11)."""

    def put(attribute: int, value: int) -> None:
        data = ctypes.c_int(value)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), attribute, ctypes.byref(data), ctypes.sizeof(data)
        )

    put(DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark))
    put(DWMWA_CAPTION_COLOR, _colorref(paper))
    put(DWMWA_TEXT_COLOR, _colorref(ink))


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


def get_placement(hwnd: int) -> dict:
    """Where the window is, restored, and whether it is maximized."""
    placement = WINDOWPLACEMENT(length=ctypes.sizeof(WINDOWPLACEMENT))
    user32.GetWindowPlacement(wintypes.HWND(hwnd), ctypes.byref(placement))
    rect = placement.rcNormalPosition
    return {
        "rect": [rect.left, rect.top, rect.right, rect.bottom],
        "maximized": bool(user32.IsZoomed(wintypes.HWND(hwnd))),
    }


def set_placement(hwnd: int, saved: dict) -> None:
    """The window back where get_placement found it, still hidden, so long as
    that is on a screen now."""
    left, top, right, bottom = saved["rect"]
    if not user32.MonitorFromRect(ctypes.byref(wintypes.RECT(left, top, right, bottom)), 0):
        return
    placement = WINDOWPLACEMENT(length=ctypes.sizeof(WINDOWPLACEMENT))
    user32.GetWindowPlacement(wintypes.HWND(hwnd), ctypes.byref(placement))
    placement.rcNormalPosition = wintypes.RECT(left, top, right, bottom)
    placement.showCmd = SW_HIDE
    user32.SetWindowPlacement(wintypes.HWND(hwnd), ctypes.byref(placement))


def show(hwnd: int, maximized: bool = False) -> None:
    """The window shown (restored if minimized, maximized if asked) and in front."""
    window = wintypes.HWND(hwnd)
    if not user32.IsWindowVisible(window):
        user32.ShowWindow(window, SW_SHOWMAXIMIZED if maximized else SW_SHOWNORMAL)
    # A program's first window takes the show state its launcher asked for,
    # minimized from an installer or a script; opening it means open.
    if user32.IsIconic(window):
        user32.ShowWindow(window, SW_SHOWMAXIMIZED if maximized else SW_RESTORE)
    user32.SetForegroundWindow(window)


def dpi_scale(hwnd: int) -> float:
    return user32.GetDpiForWindow(wintypes.HWND(hwnd)) / 96 or 1.0


# ---- the number on the taskbar button ----------------------------------------

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, text: str) -> GUID:
        guid = cls()
        ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid))
        return guid


CLSID_TASKBAR_LIST = GUID.parse("{56FDF344-FD6D-11d0-958A-006097C9A090}")
IID_ITASKBAR_LIST3 = GUID.parse("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")
CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 2
# ITaskbarList3's vtable: IUnknown (3), ITaskbarList (5), ITaskbarList2 (1),
# then SetProgressValue, SetProgressState, RegisterTab, UnregisterTab,
# SetTabOrder, SetTabActive, ThumbBarAddButtons, ThumbBarUpdateButtons,
# ThumbBarSetImageList, SetOverlayIcon.
HR_INIT, SET_OVERLAY_ICON = 3, 18
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10

SPARK = (229, 0, 110)


class TaskbarBadge:
    """The count of nudges waiting, drawn over the window's taskbar button.
    Every call from the one thread that made it (a COM apartment of its own)."""

    def __init__(self) -> None:
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        self._list = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_TASKBAR_LIST),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(IID_ITASKBAR_LIST3),
            ctypes.byref(self._list),
        )
        if hr != 0:
            raise OSError(f"ITaskbarList3 unavailable ({hr:#x})")
        self._method(HR_INIT, ctypes.HRESULT)(self._list)
        self._icons: dict[tuple[int, int], int] = {}

    def _method(self, index: int, restype, *argtypes):  # noqa: ANN001, ANN202
        vtable = ctypes.cast(self._list, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return prototype(vtable[index])

    def _icon(self, count: int, size: int) -> int:
        key = (min(count, 10), size)
        if key not in self._icons:
            path = Path(tempfile.gettempdir()) / f"personal-calendar-badge-{key[0]}-{size}.ico"
            badge_image(count, size).save(path, format="ICO", sizes=[(size, size)])
            user32.LoadImageW.restype = wintypes.HANDLE
            self._icons[key] = user32.LoadImageW(
                None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE
            )
        return self._icons[key]

    def show(self, hwnd: int, count: int) -> None:
        set_overlay = self._method(
            SET_OVERLAY_ICON, ctypes.HRESULT, wintypes.HWND, wintypes.HANDLE, wintypes.LPCWSTR
        )
        if count:
            size = round(16 * dpi_scale(hwnd))
            label = f"{count} nudge{'s' if count != 1 else ''} waiting"
            set_overlay(self._list, hwnd, self._icon(count, size), label)
        else:
            set_overlay(self._list, hwnd, None, None)


def badge_image(count: int, size: int) -> Image.Image:
    """A spark disc with the count in white, "9+" past nine. Drawn four times
    over and scaled down, for clean edges."""
    scale = 4
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 0, big - 1, big - 1), fill=SPARK)
    text = str(count) if count < 10 else "9+"
    font_size = big * (0.72 if len(text) == 1 else 0.56)
    try:
        font = ImageFont.truetype("segoeuib.ttf", round(font_size))
    except OSError:
        font = ImageFont.load_default(round(font_size))
    draw.text((big / 2, big / 2), text, fill="white", font=font, anchor="mm")
    return image.resize((size, size), Image.Resampling.LANCZOS)
