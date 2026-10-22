"""Where Oscar's attention is, as Windows tells it: the program whose window
is in front, and how long since he last used the keyboard or mouse. Read for
the work in herdr (app/services/work_log.py): he is at a pane while herdr's
screen is in front and he is not away. Elsewhere than Windows, nothing is
known: he is taken as not there."""

from __future__ import annotations

import os
from pathlib import Path


def _program_of(hwnd: int) -> str:
    """The file name of the program a window is of, lower case; "" when it
    cannot be told."""
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return Path(buffer.value).name.lower()
    finally:
        kernel32.CloseHandle(handle)


def foreground_program() -> str:
    """The file name of the program whose window is in front (wezterm-gui.exe),
    lower case; "" when none is, or it cannot be told."""
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    return _program_of(hwnd) if hwnd else ""


def idle_seconds() -> float:
    """How long since the keyboard or mouse was last used; 0 when it cannot
    be told."""
    if os.name != "nt":
        return 0.0
    import ctypes
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LastInput()
    info.cbSize = ctypes.sizeof(LastInput)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # Both wrap every 49.7 days; their difference, taken as unsigned, does not.
    ticks = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((ticks - info.dwTime) & 0xFFFFFFFF) / 1000.0


def at_terminal(terminals: list[str], away_minutes: float) -> bool:
    """Whether Oscar is at one of the terminals named (their programs' file
    names), in front and not left for away_minutes."""
    if os.name != "nt":
        return False
    names = {t.lower() for t in terminals}
    return foreground_program() in names and idle_seconds() < away_minutes * 60


def bring_forward(programs: list[str]) -> bool:
    """The first window of one of `programs` (their file names) brought to
    the front, restored when minimized; whether one was there. Windows lets
    the app do so while it is the window in front, as when Oscar clicks it."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    names = {p.lower() for p in programs}
    found: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(hwnd: int, _: int) -> bool:
        shown = user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd)
        if shown and _program_of(hwnd) in names:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc(each), 0)
    if not found:
        return False
    hwnd = found[0]
    sw_restore = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, sw_restore)
    user32.SetForegroundWindow(hwnd)
    return True
