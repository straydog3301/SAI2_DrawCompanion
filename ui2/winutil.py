# -*- coding: utf-8 -*-
"""2.0 介面用的 Win32 小工具：置頂、滑鼠穿透、Z 順序、全域快捷鍵、前景視窗監聽（自階段 0 驗證沿用）"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtWidgets import QWidget

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetWindow.restype = wt.HWND
user32.WindowFromPoint.argtypes = [wt.POINT]
user32.WindowFromPoint.restype = wt.HWND
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetAncestor.restype = wt.HWND
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

HWND_TOPMOST = wt.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_LAYERED = 0x8, 0x20, 0x80000
GW_HWNDPREV = 3
GA_ROOT = 2
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000


def hwnd_of(w: QWidget) -> int:
    return int(w.winId())


def ex_style(hwnd: int) -> int:
    return user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)


def force_topmost(hwnd: int):
    """重新放到最上層（不搶焦點）：被其他置頂視窗或全螢幕程式蓋過時用來自我修復"""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def set_click_through(hwnd: int, on: bool):
    """滑鼠穿透：WS_EX_TRANSPARENT（需搭配 WS_EX_LAYERED）"""
    style = ex_style(hwnd)
    style = (style | WS_EX_LAYERED | WS_EX_TRANSPARENT) if on else (style & ~WS_EX_TRANSPARENT)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)


def root_at(x: int, y: int) -> int:
    """螢幕座標下方實際接收滑鼠的頂層視窗"""
    h = user32.WindowFromPoint(wt.POINT(x, y))
    return user32.GetAncestor(h, GA_ROOT) or 0


def is_above(a: int, b: int) -> bool:
    """a 是否在 b 之上（沿 Z 順序往上找）"""
    h = b
    for _ in range(5000):
        h = user32.GetWindow(h, GW_HWNDPREV)
        if not h:
            return False
        if h == a:
            return True
    return False


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class HotkeyHub(QObject, QAbstractNativeEventFilter):
    """RegisterHotKey 到一個隱藏的原生視窗，從 Qt 的原生事件過濾器收 WM_HOTKEY"""
    triggered = Signal(int)

    def __init__(self, app):
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self._host = QWidget()
        self._host.setAttribute(Qt.WA_DontShowOnScreen)
        self.hwnd = hwnd_of(self._host)
        self._ids: list[int] = []
        self._app = app
        app.installNativeEventFilter(self)

    def register(self, hid: int, mods: int, vk: int) -> bool:
        ok = bool(user32.RegisterHotKey(self.hwnd, hid, mods | MOD_NOREPEAT, vk))
        if ok:
            self._ids.append(hid)
        return ok

    def unregister_all(self):
        for hid in self._ids:
            user32.UnregisterHotKey(self.hwnd, hid)
        self._ids.clear()

    def close(self):
        """結束前呼叫：取消註冊並移除事件過濾器（否則 Python 物件回收後 Qt 仍會呼叫它而當機）"""
        self.unregister_all()
        if self._app is not None:
            self._app.removeNativeEventFilter(self)
            self._app = None

    def nativeEventFilter(self, event_type, message):
        if event_type == b'windows_generic_MSG' or event_type == 'windows_generic_MSG':
            msg = wt.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.hWnd == self.hwnd:
                self.triggered.emit(int(msg.wParam))
                return True, 0
        return False, 0


class ForegroundWatcher(QObject):
    """EVENT_SYSTEM_FOREGROUND：前景視窗一換就通知（不用輪詢）"""
    changed = Signal(int, str)
    _PROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)

    def __init__(self):
        super().__init__()
        user32.SetWinEventHook.restype = wt.HANDLE
        user32.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, self._PROC, wt.DWORD, wt.DWORD, wt.DWORD]
        self._cb = self._PROC(self._on_event)
        self._hook = user32.SetWinEventHook(0x0003, 0x0003, None, self._cb, 0, 0, 0)   # OUTOFCONTEXT

    def _on_event(self, _hook, _event, hwnd, _obj, _child, _thread, _time):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        self.changed.emit(int(hwnd or 0), buf.value)

    def close(self):
        if self._hook:
            user32.UnhookWinEvent(self._hook)
            self._hook = None


def set_round_corners(hwnd: int, on: bool = True):
    """Windows 11 的圓角視窗（DWMWA_WINDOW_CORNER_PREFERENCE）；舊版 Windows 會忽略"""
    try:
        pref = ctypes.c_int(2 if on else 1)          # DWMWCP_ROUND / DWMWCP_DONOTROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wt.HWND(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except (OSError, AttributeError):
        pass


def set_dark_titlebar(hwnd: int, on: bool = True):
    """深色標題列（DWMWA_USE_IMMERSIVE_DARK_MODE），與深色介面一致"""
    try:
        val = ctypes.c_int(1 if on else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wt.HWND(hwnd), 20, ctypes.byref(val), ctypes.sizeof(val))
    except (OSError, AttributeError):
        pass
