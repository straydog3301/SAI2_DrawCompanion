# -*- coding: utf-8 -*-
"""SAI2 視窗相關的 Win32 小工具（不含 UI）"""

import ctypes
import ctypes.wintypes

user32 = ctypes.windll.user32


def find_sai2_hwnd():
    """找出標題含「PaintTool SAI」的頂層視窗；找不到回傳 0"""
    hwnd_out = [0]
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def _cb(hwnd, lparam):
        buf_size = 512
        buf = ctypes.create_unicode_buffer(buf_size)
        user32.GetWindowTextW(hwnd, buf, buf_size)
        title = buf.value.lower()
        if "painttool sai" in title:
            hwnd_out[0] = hwnd
            return False
        return True
    cb_func = WNDENUMPROC(_cb)
    user32.EnumWindows(cb_func, 0)
    return hwnd_out[0]
