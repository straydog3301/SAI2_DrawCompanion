# -*- coding: utf-8 -*-
"""
bubble_skin.py - 對話泡泡的自訂外觀（九宮格，不含 UI）

使用者提供一張圖，圈出「文字範圍」。文字範圍以外的四個角固定不縮放，上下兩邊只左右延伸、
左右兩邊只上下延伸、中間兩個方向都延伸，所以一張圖可以撐出任何大小的泡泡。

設定（settings2 的 pet.bubble_skin）：
    {'image': 檔名（存在 APP_DIR/bubbles）, 'text': [x, y, w, h] 原圖像素, 'color': 文字顏色, 'scale': 顯示倍率}
image 空白 = 內建泡泡。
"""

from __future__ import annotations

import os
import shutil
import uuid

BUBBLES_DIR = 'bubbles'
MIN_TEXT = 4                       # 文字範圍最小邊長（原圖像素）
MAX_SIDE = 2048                    # 匯入圖片的長邊上限
SCALES = (0.25, 3.0)
DEFAULT = {'image': '', 'text': None, 'color': '#1b1a22', 'scale': 1.0}


def default_text_rect(w: int, h: int) -> list[int]:
    """還沒圈選時的預設文字範圍：四周各留 30%"""
    mx, my = int(w * 0.3), int(h * 0.3)
    return [mx, my, max(MIN_TEXT, w - 2 * mx), max(MIN_TEXT, h - 2 * my)]


def clamp_rect(rect, w: int, h: int) -> list[int]:
    """把文字範圍限制在圖片內、至少 MIN_TEXT 大小"""
    if not rect or len(rect) != 4:
        return default_text_rect(w, h)
    x, y, rw, rh = (int(round(float(v))) for v in rect)
    if rw < 0:
        x, rw = x + rw, -rw
    if rh < 0:
        y, rh = y + rh, -rh
    mw, mh = min(MIN_TEXT, w), min(MIN_TEXT, h)
    rw = max(mw, min(rw, w))
    rh = max(mh, min(rh, h))
    x = max(0, min(x, w - rw))
    y = max(0, min(y, h - rh))
    return [x, y, rw, rh]


def margins(rect, w: int, h: int) -> tuple[int, int, int, int]:
    """文字範圍 → 九宮格四邊寬度 (左, 上, 右, 下)"""
    x, y, rw, rh = clamp_rect(rect, w, h)
    return x, y, w - x - rw, h - y - rh


def _split(total: int, a: int, b: int) -> tuple[int, int]:
    """目標比兩邊加起來還小時，兩邊依比例縮小"""
    if a + b <= total:
        return a, b
    if a + b == 0:
        return 0, 0
    na = int(total * a / (a + b))
    return na, total - na


def slices(src_w: int, src_h: int, m, dst_w: int, dst_h: int, scale: float = 1.0) -> list[tuple[tuple, tuple]]:
    """九宮格對應：[(來源 (x, y, w, h), 目標 (x, y, w, h)), …]，略過大小為 0 的格子。
    m：四邊寬度（原圖像素）；scale：四角在畫面上的倍率"""
    l, t, r, b = m
    dl, dr = _split(dst_w, int(round(l * scale)), int(round(r * scale)))
    dt, db = _split(dst_h, int(round(t * scale)), int(round(b * scale)))
    sx = (0, l, src_w - r, src_w)
    sy = (0, t, src_h - b, src_h)
    dx = (0, dl, dst_w - dr, dst_w)
    dy = (0, dt, dst_h - db, dst_h)
    out = []
    for j in range(3):
        for i in range(3):
            s = (sx[i], sy[j], sx[i + 1] - sx[i], sy[j + 1] - sy[j])
            d = (dx[i], dy[j], dx[i + 1] - dx[i], dy[j + 1] - dy[j])
            if s[2] > 0 and s[3] > 0 and d[2] > 0 and d[3] > 0:
                out.append((s, d))
    return out


def normalize(skin) -> dict:
    out = dict(DEFAULT)
    if isinstance(skin, dict):
        out.update({k: skin[k] for k in DEFAULT if k in skin})
    try:
        out['scale'] = max(SCALES[0], min(SCALES[1], float(out['scale'])))
    except (TypeError, ValueError):
        out['scale'] = 1.0
    if not isinstance(out['color'], str) or not out['color'].startswith('#'):
        out['color'] = DEFAULT['color']
    return out


def image_path(app_dir: str, skin) -> str | None:
    """自訂圖片的完整路徑；沒有設定或檔案不見了回傳 None"""
    name = normalize(skin)['image']
    if not name:
        return None
    p = os.path.join(app_dir, BUBBLES_DIR, os.path.basename(name))
    return p if os.path.isfile(p) else None


def import_image(app_dir: str, src: str) -> tuple[str, int, int]:
    """把圖片複製到 APP_DIR/bubbles（過大時等比縮小），回傳 (檔名, 寬, 高)。不是圖片時丟 ValueError"""
    from PIL import Image
    try:
        with Image.open(src) as im:
            im.load()
            img = im.convert('RGBA')
    except Exception as e:                      # noqa: BLE001 - PIL 會丟各種例外
        raise ValueError('無法讀取這張圖片') from e
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    d = os.path.join(app_dir, BUBBLES_DIR)
    os.makedirs(d, exist_ok=True)
    name = f'bubble_{uuid.uuid4().hex[:8]}.png'
    img.save(os.path.join(d, name))
    return name, img.size[0], img.size[1]


def remove_unused(app_dir: str, keep: str = ''):
    """刪掉沒在用的泡泡圖（換圖或還原預設後）"""
    d = os.path.join(app_dir, BUBBLES_DIR)
    if not os.path.isdir(d):
        return
    for n in os.listdir(d):
        if n != keep and n.startswith('bubble_'):
            p = os.path.join(d, n)
            try:
                os.remove(p) if os.path.isfile(p) else shutil.rmtree(p)
            except OSError:
                pass
