# -*- coding: utf-8 -*-
"""
snapshots.py - SAI2 畫布擷取與打卡快照（不含 UI）

- capture_sai2_canvas：擷取 SAI2 畫布視窗並只留下畫紙（研究視窗比對、打卡快照、作品縮圖共用）
- save_snapshot：把擷取結果縮成縮圖存檔，作為打卡時的作品紀錄
"""

from __future__ import annotations

import os

from PIL import Image

SNAPSHOT_MAX_SIDE = 720       # 快照縮圖最長邊（足夠回顧，又不會讓資料夾膨脹）


def trim_workspace(img: Image.Image) -> Image.Image:
    """只留下畫紙：去掉 SAI2 畫布視窗的外框、捲軸與畫紙以外的工作區（暗色系、白色系都適用）。
    畫紙放大到填滿畫面時保留整個畫面；細節見 core/canvas_crop.py"""
    from core.canvas_crop import crop_paper
    return crop_paper(img)


def capture_sai2_canvas() -> Image.Image | None:
    """擷取 SAI2 畫布視窗（沿用縮時錄影的視窗尋找與 GDI 擷取）；找不到畫布時回傳 None"""
    from core.timelapse import find_canvas_hwnd, capture_window_gdi
    hwnd = find_canvas_hwnd(os.getpid())
    if not hwnd:
        return None
    img = capture_window_gdi(hwnd)
    return trim_workspace(img) if img is not None else None


def save_snapshot(img: Image.Image, folder: str, stem: str, max_side: int = SNAPSHOT_MAX_SIDE) -> str:
    """存成 JPEG 縮圖並回傳路徑"""
    os.makedirs(folder, exist_ok=True)
    thumb = img.convert('RGB')
    thumb.thumbnail((max_side, max_side), Image.LANCZOS)
    path = os.path.join(folder, f'{stem}.jpg')
    thumb.save(path, format='JPEG', quality=85)
    return path
