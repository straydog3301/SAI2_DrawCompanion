# -*- coding: utf-8 -*-
"""
snapshots.py - SAI2 畫布擷取與打卡快照（不含 UI）

- capture_sai2_canvas：擷取 SAI2 畫布視窗並裁掉四周的單色工作區（研究視窗比對、打卡快照共用）
- save_snapshot：把擷取結果縮成縮圖存檔，作為打卡時的作品紀錄
"""

from __future__ import annotations

import os

from PIL import Image, ImageChops

SNAPSHOT_MAX_SIDE = 720       # 快照縮圖最長邊（足夠回顧，又不會讓資料夾膨脹）


def trim_workspace(img: Image.Image) -> Image.Image:
    """裁掉 SAI2 畫布視窗四周的單色工作區（以左上角顏色為背景）"""
    rgb = img.convert('RGB')
    bg = rgb.getpixel((2, 2))
    diff = ImageChops.difference(rgb, Image.new('RGB', rgb.size, bg)).convert('L')
    box = diff.point(lambda v: 255 if v > 18 else 0).getbbox()
    if not box:
        return rgb
    bw, bh = box[2] - box[0], box[3] - box[1]
    if bw * bh < rgb.size[0] * rgb.size[1] * 0.05:
        return rgb   # 裁切結果過小，多半是誤判，保留原圖
    return rgb.crop(box)


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
