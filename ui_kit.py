# -*- coding: utf-8 -*-
"""
ui_kit.py - Tk 版面共用工具（1.x 的最小版本）

程式宣告了 DPI 感知，字型會跟著 Windows 顯示縮放放大，但寫死的像素尺寸不會，
在 4K / 150% 這類環境下內容就會被裁切。這裡提供：
- scale_factor / px：把「100% 縮放下的設計尺寸」換算成實際像素
- fit_window：視窗至少容得下內容（以實際需要的尺寸為初始大小與最小尺寸），並限制在螢幕內
- bind_wraplength：文字換行寬度跟著元件寬度走，取代寫死的 wraplength

完整的可換行工具列、統一主題等留給 2.0（見 docs/DAILY_QUESTS.md 與重構規劃）。
"""

from __future__ import annotations

import tkinter as tk

BASE_DPI = 96.0          # Windows 100% 縮放
SCREEN_MAX_RATIO = 0.92  # 視窗最大佔螢幕比例（保留工作列）


def scale_factor(widget: tk.Misc) -> float:
    """目前的顯示縮放倍率（100% = 1.0、150% = 1.5）；不會小於 1"""
    try:
        return max(1.0, widget.winfo_fpixels('1i') / BASE_DPI)
    except Exception:
        return 1.0


def px(widget: tk.Misc, value: float) -> int:
    """把 100% 縮放下的設計像素換算成實際像素"""
    return int(round(value * scale_factor(widget)))


def fit_window(win: tk.Misc, base_w: int, base_h: int, *, center: bool = True,
               set_minsize: bool = True, min_height: int | None = None,
               position: tuple[int, int] | None = None) -> tuple[int, int]:
    """依「設計尺寸 × 縮放倍率」與「內容實際需要的尺寸」取較大者決定視窗大小。

    set_minsize=True 時，最小尺寸設為內容需要的尺寸，避免使用者縮小視窗後按鈕被裁切。
    min_height：100% 縮放下的最小高度；內容含可捲動清單（可縮短）時用它取代內容高度。
    回傳 (寬, 高)。
    """
    win.update_idletasks()
    f = scale_factor(win)
    req_w, req_h = win.winfo_reqwidth(), win.winfo_reqheight()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    max_w, max_h = int(sw * SCREEN_MAX_RATIO), int(sh * SCREEN_MAX_RATIO)
    w = min(max(int(base_w * f), req_w), max_w)
    h = min(max(int(base_h * f), req_h), max_h)
    if set_minsize:
        mh = req_h if min_height is None else int(min_height * f)
        win.minsize(min(req_w, max_w), min(mh, max_h))
    if position is not None:
        x, y = position
    elif center:
        x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 2)
    else:
        win.geometry(f'{w}x{h}')
        return w, h
    win.geometry(f'{w}x{h}+{x}+{y}')
    return w, h


def bind_wraplength(label: tk.Label, pad: int = 4, minimum: int = 80):
    """讓 Label 的換行寬度等於自身寬度（版面變寬變窄時自動重新換行）"""
    def _on_configure(e):
        wl = max(minimum, e.width - pad)
        if int(label.cget('wraplength') or 0) != wl:
            label.config(wraplength=wl)
    label.bind('<Configure>', _on_configure, add='+')
