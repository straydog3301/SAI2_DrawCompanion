# -*- coding: utf-8 -*-
"""
study_tools.py - 臨摹研究的影像工具、分段計時與練習畫布（不含 UI；自 1.x study_window.py 移入）
"""

from __future__ import annotations

import math
import os
import time

from PIL import Image, ImageDraw, ImageOps

from core.psd_writer import write_blank_psd

GUIDES = [('none', '無'), ('thirds', '三分法'), ('grid', '格線'), ('diagonal', '對角線')]
VALUE_STEPS = [0, 3, 5]                  # 0 = 原圖
CANVAS_SIDES = (1500, 2000, 3000)
PALETTE_SIZE = 6
GUIDE_COLOR = (34, 211, 238)
_BAD = '\\/:*?"<>|'


def safe_filename(name: str) -> str:
    out = ''.join('_' if c in _BAD else c for c in name).strip().rstrip('.')
    return out or 'untitled'


def documents_dir() -> str:
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser('~'), 'Documents')


def posterize_value(img: Image.Image, levels: int) -> Image.Image:
    """依明度分成 levels 階（灰階輸出），用來看清大明暗分組"""
    gray = img.convert('L')
    step = 255.0 / (levels - 1)
    lut = [int(round(round(v / step) * step)) for v in range(256)]
    return gray.point(lut).convert('RGB')


def extract_palette(img: Image.Image, n: int = PALETTE_SIZE) -> list[tuple[int, int, int]]:
    small = img.convert('RGB').copy()
    small.thumbnail((160, 160))
    q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    counts = sorted(q.getcolors() or [], reverse=True)
    return [tuple(pal[i * 3:i * 3 + 3]) for _c, i in counts][:n]


def process(img: Image.Image, flip=False, gray=False, value_levels=0) -> Image.Image:
    img = img.convert('RGB')
    if flip:
        img = ImageOps.mirror(img)
    if value_levels:
        img = posterize_value(img, value_levels)
    elif gray:
        img = img.convert('L').convert('RGB')
    return img


def guide_lines(kind: str, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """構圖輔助線（x1, y1, x2, y2），由介面依顯示大小繪製"""
    if kind in ('thirds', 'grid'):
        n = 3 if kind == 'thirds' else 4
        return ([(w * i / n, 0, w * i / n, h) for i in range(1, n)]
                + [(0, h * i / n, w, h * i / n) for i in range(1, n)])
    if kind == 'diagonal':
        return [(0, 0, w, h), (w, 0, 0, h)]
    return []


def default_tools(lesson: dict | None) -> dict:
    tools = set(lesson['tools']) if lesson else set()
    return {'flip': False, 'gray': 'gray' in tools,
            'value_levels': 3 if 'value3' in tools else 5 if 'value5' in tools else 0,
            'guide': next((g for g in ('thirds', 'grid', 'diagonal') if g in tools), 'none'),
            'palette': 'palette' in tools}


def phase_at(lesson: dict | None, seconds: float) -> tuple[int | None, float]:
    """依實際動筆秒數回傳 (階段索引, 本階段剩餘秒數)；超過總時間時停在最後一階段、剩 0"""
    phases = lesson['phases'] if lesson else []
    acc = 0
    for i, ph in enumerate(phases):
        acc += ph['minutes'] * 60
        if seconds < acc:
            return i, acc - seconds
    return (len(phases) - 1, 0.0) if phases else (None, 0.0)


def phase_text(lesson: dict | None, seconds: float) -> tuple[str, str]:
    """(「2/4 大色塊」, 「剩 7 分」/「可以比對修正後打卡」)"""
    idx, left = phase_at(lesson, seconds)
    if idx is None:
        return '研究計時', ''
    ph = lesson['phases'][idx]
    tail = '可以比對修正後打卡' if left <= 0 else f'剩 {math.ceil(left / 60)} 分'
    return f"{idx + 1}/{len(lesson['phases'])} {ph['name']}", tail


def canvas_dir(base: str, skill_name: str | None) -> str:
    base = base or os.path.join(documents_dir(), 'SAI2 練習')
    return os.path.join(base, safe_filename(skill_name)) if skill_name else base


def canvas_stem(lesson: dict | None, skill_name: str | None, task_name: str, day: str | None = None) -> str:
    day = day or time.strftime('%Y%m%d')
    if lesson:
        stem = f"{skill_name or ''}_Lv{lesson['level']}_{lesson['name']}"
    else:
        stem = task_name or '臨摹研究'
    return safe_filename(f'{stem}_{day}')


# 速寫畫布尺寸（300 dpi）：key → (名稱, 寬, 高)；'custom' 用設定裡的 canvas_w / canvas_h
SKETCH_CANVAS = {
    'a4_land': ('A4 橫向', 3508, 2480), 'a4_port': ('A4 直向', 2480, 3508),
    'a3_land': ('A3 橫向', 4961, 3508), 'b5_land': ('B5 橫向', 3035, 2150),
    'square': ('正方形', 2480, 2480), 'wide': ('16:9 橫向', 3840, 2160), 'custom': ('自訂', 0, 0),
}
CANVAS_MIN, CANVAS_MAX = 256, 10000


def sketch_canvas_size(opts: dict) -> tuple[int, int]:
    """速寫設定 → 畫布寬高（px）"""
    key = opts.get('canvas', 'a4_land')
    if key == 'custom':
        w, h = int(opts.get('canvas_w') or 3508), int(opts.get('canvas_h') or 2480)
        return (max(CANVAS_MIN, min(CANVAS_MAX, w)), max(CANVAS_MIN, min(CANVAS_MAX, h)))
    _name, w, h = SKETCH_CANVAS.get(key, SKETCH_CANVAS['a4_land'])
    return w, h


def create_canvas(folder: str, stem: str, ref_size: tuple[int, int] | None, long_side: int,
                  size: tuple[int, int] | None = None) -> tuple[str, int, int]:
    """空白 PSD（同名時加 _2、_3），回傳 (路徑, 寬, 高)。size 指定寬高；否則與參考圖同比例、長邊 long_side"""
    if size:
        w, h = int(size[0]), int(size[1])
    else:
        rw, rh = ref_size or (3, 4)
        scale = long_side / max(rw, rh)
        w, h = max(1, round(rw * scale)), max(1, round(rh * scale))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'{stem}.psd')
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f'{stem}_{n}.psd')
        n += 1
    write_blank_psd(path, w, h)
    return path, w, h
