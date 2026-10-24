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


FRAME_ZONE = 64               # 視窗外框、捲軸只會出現在離邊緣這麼近的範圍內（px）


def _workspace_color(rgb: Image.Image) -> tuple[int, int, int]:
    """工作區顏色＝縮圖中出現最多的顏色（畫布沒佔滿視窗時，工作區面積最大）"""
    small = rgb.resize((min(200, rgb.size[0]), min(150, rgb.size[1])), Image.NEAREST)
    return max(small.getcolors(200 * 150), key=lambda c: c[0])[1]


def _inner_frame(mask: Image.Image) -> tuple[int, int, int, int]:
    """找出四邊最內側的「整條線」（外框、捲軸邊線），回傳線內的範圍；線外的捲軸箭頭等都會被排除"""
    w, h = mask.size
    px = mask.load()
    zone = min(FRAME_ZONE, w // 4, h // 4)

    def full_col(x):
        ys = range(0, h, 4)
        return sum(1 for y in ys if px[x, y]) >= 0.9 * len(ys)

    def full_row(y):
        xs = range(0, w, 4)
        return sum(1 for x in xs if px[x, y]) >= 0.9 * len(xs)
    left = max([x + 1 for x in range(zone) if full_col(x)], default=0)
    right = min([x for x in range(w - zone, w) if full_col(x)], default=w)
    top = max([y + 1 for y in range(zone) if full_row(y)], default=0)
    bottom = min([y for y in range(h - zone, h) if full_row(y)], default=h)
    return left, top, right, bottom


def trim_workspace(img: Image.Image) -> Image.Image:
    """裁掉 SAI2 畫布視窗四周的單色工作區。
    視窗邊緣有外框與捲軸（顏色和工作區很接近），先以四邊最內側的整條線為界去掉它們，再找畫布範圍"""
    rgb = img.convert('RGB')
    bg = _workspace_color(rgb)
    mask = ImageChops.difference(rgb, Image.new('RGB', rgb.size, bg)).convert('L').point(lambda v: 255 if v > 18 else 0)
    l, t, r, b = _inner_frame(mask)
    box = mask.crop((l, t, r, b)).getbbox()
    if not box:
        return rgb
    bw, bh = box[2] - box[0], box[3] - box[1]
    if bw * bh < rgb.size[0] * rgb.size[1] * 0.05:
        return rgb   # 裁切結果過小，多半是誤判，保留原圖
    return rgb.crop((box[0] + l, box[1] + t, box[2] + l, box[3] + t))


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
