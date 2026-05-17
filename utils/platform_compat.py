import platform

IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"


def get_active_window_title() -> str:
    if IS_MACOS:
        return _get_active_window_title_mac()
    elif IS_WINDOWS:
        return _get_active_window_title_windows()
    return ""


def _get_active_window_title_windows() -> str:
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        return win.title if win else ""
    except Exception:
        return ""


def _get_active_window_title_mac() -> str:
    try:
        from AppKit import NSWorkspace
        workspace = NSWorkspace.sharedWorkspace()
        app = workspace.frontmostApplication()
        return app.localizedName() or ""
    except Exception:
        return ""


def is_fullscreen() -> bool:
    if IS_MACOS:
        return _is_fullscreen_mac()
    elif IS_WINDOWS:
        return _is_fullscreen_windows()
    return False


def _is_fullscreen_windows() -> bool:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if hwnd == 0:
            return False

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

        monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(monitor, ctypes.byref(mi))

        window_w = rect.right - rect.left
        window_h = rect.bottom - rect.top
        monitor_w = mi.rcMonitor.right - mi.rcMonitor.left
        monitor_h = mi.rcMonitor.bottom - mi.rcMonitor.top

        return window_w >= monitor_w and window_h >= monitor_h
    except Exception:
        return False


def _is_fullscreen_mac() -> bool:
    try:
        from AppKit import NSWorkspace, NSScreen
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
        )

        workspace = NSWorkspace.sharedWorkspace()
        app = workspace.frontmostApplication()
        if app is None:
            return False

        app_name = app.localizedName()
        if not app_name:
            return False

        screen = NSScreen.mainScreen()
        if screen is None:
            return False

        screen_frame = screen.frame()
        screen_w = int(screen_frame.size.width)
        screen_h = int(screen_frame.size.height)

        windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        )
        for win in windows:
            owner = win.get("kCGWindowOwnerName", "")
            bounds = win.get("kCGWindowBounds", {})
            layer = win.get("kCGWindowLayer", 999)
            if owner == app_name and layer == 0:
                w = int(bounds.get("Width", 0))
                h = int(bounds.get("Height", 0))
                if w >= screen_w and h >= screen_h:
                    return True
        return False
    except Exception:
        return False


def get_monitors():
    from PySide6.QtGui import QGuiApplication

    screens = QGuiApplication.screens()
    result = []
    for i, screen in enumerate(screens):
        geo = screen.geometry()
        result.append(
            {
                "index": i,
                "name": screen.name(),
                "x": geo.x(),
                "y": geo.y(),
                "width": geo.width(),
                "height": geo.height(),
            }
        )
    return result
