# -*- coding: utf-8 -*-
"""
pet_builtin.py - 內建角色「墨墨」的影格（以 Pillow 繪製，不需要圖檔）

只是預設角色；使用者可以在 pets/ 放自己的角色包取代（見 pet_pack.py）。
以 120×120 的設計座標繪製，先畫 4 倍大再縮小，邊緣有半透明的抗鋸齒。
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw

BODY = (109, 91, 208, 255)
BODY_OFFLINE = (122, 118, 140, 255)
INK = (27, 26, 34, 255)
CHEEK = (255, 143, 163, 140)
FRAME_MS = 60
COUNTS = {'idle': 24, 'drawing': 16, 'cheer': 18, 'rest': 24, 'remind': 16, 'sleep': 30, 'offline': 30}


class _Pen:
    def __init__(self, size: int):
        self.k = size * 4 / 120.0
        self.img = Image.new('RGBA', (size * 4, size * 4), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def p(self, *xy):
        return [v * self.k for v in xy]

    def ellipse(self, cx, cy, rx, ry, fill):
        self.d.ellipse(self.p(cx - rx, cy - ry, cx + rx, cy + ry), fill=fill)

    def line(self, pts, fill, w):
        self.d.line(self.p(*[v for pt in pts for v in pt]), fill=fill, width=max(1, int(w * self.k)), joint='curve')
        for x, y in (pts[0], pts[-1]):     # 圓頭
            self.ellipse(x, y, w / 2, w / 2, fill)

    def polygon(self, pts, fill):
        self.d.polygon(self.p(*[v for pt in pts for v in pt]), fill=fill)

    def arc(self, cx, cy, r, start, end, fill, w):
        self.d.arc(self.p(cx - r, cy - r, cx + r, cy + r), start, end, fill=fill, width=max(1, int(w * self.k)))

    def done(self, size: int) -> Image.Image:
        return self.img.resize((size, size), Image.LANCZOS)


def _body(pen: _Pen, dx: float, dy: float, color, squash: float = 0.0):
    pen.ellipse(60, 108, 30 - dy * 0.6, 5, (0, 0, 0, 60))                      # 影子（跳起來時變小）
    pen.ellipse(60 + dx, 68 + dy, 40 + squash, 37 - squash, color)
    pen.polygon([(56 + dx, 34 + dy), (66 + dx, 18 + dy), (80 + dx, 15 + dy), (72 + dx, 24 + dy), (70 + dx, 34 + dy)], color)
    pen.arc(56 + dx, 66 + dy, 26, 200, 260, (255, 255, 255, 90), 4)           # 反光
    pen.ellipse(40 + dx, 78 + dy, 7, 4, CHEEK)
    pen.ellipse(80 + dx, 78 + dy, 7, 4, CHEEK)


def _eyes_open(pen, dx, dy):
    for x in (48, 72):
        pen.ellipse(x + dx, 66 + dy, 5, 6.5, INK)
        pen.ellipse(x + 2 + dx, 63.5 + dy, 1.8, 1.8, (255, 255, 255, 255))


def _eyes_closed(pen, dx, dy):
    for x in (48, 72):
        pen.arc(x + dx, 64 + dy, 6, 20, 160, INK, 3)


def _mouth_smile(pen, dx, dy):
    pen.arc(60 + dx, 76 + dy, 5, 20, 160, INK, 3)


def frame(state: str, i: int, size: int, body=BODY) -> Image.Image:
    n = COUNTS[state]
    t = i / n
    pen = _Pen(size)
    if state == 'idle':
        dy = 2 * math.sin(t * 2 * math.pi)
        _body(pen, 0, dy, body)
        (_eyes_closed if i in (18, 19) else _eyes_open)(pen, 0, dy)
        _mouth_smile(pen, 0, dy)
    elif state == 'drawing':
        dy = math.sin(t * 4 * math.pi)
        _body(pen, 0, dy, body)
        for x, s in ((48, 1), (72, -1)):
            pen.line([(x - 5 * s, 63 + dy), (x + 4 * s, 66 + dy), (x - 5 * s, 69 + dy)], INK, 3)
        pen.line([(56, 80 + dy), (64, 80 + dy)], INK, 3)
        swing = 6 * math.sin(t * 2 * math.pi)
        pen.line([(88, 86 + dy), (106 + swing, 54 + dy)], (201, 138, 90, 255), 5)
        pen.line([(106 + swing, 54 + dy), (110 + swing * 1.2, 46 + dy)], (124, 58, 237, 255), 6)
    elif state == 'cheer':
        dy = -12 * abs(math.sin(t * 2 * math.pi))
        squash = 3 if i in (0, n // 2) else 0
        for s in (-1, 1):
            pen.line([(60 + 32 * s, 70 + dy), (60 + 46 * s, 48 + dy)], body, 7)
        _body(pen, 0, dy, body, squash)
        for x in (48, 72):
            pen.arc(x, 70 + dy, 6, 200, 340, INK, 3)
        pen.polygon([(53, 78 + dy), (67, 78 + dy), (60, 88 + dy)], INK)
        if (i // 3) % 2 == 0:
            for sx, sy, r in ((14, 26, 6), (104, 18, 4), (100, 46, 3)):
                pen.polygon([(sx, sy - r), (sx + r * 0.35, sy - r * 0.35), (sx + r, sy), (sx + r * 0.35, sy + r * 0.35),
                             (sx, sy + r), (sx - r * 0.35, sy + r * 0.35), (sx - r, sy), (sx - r * 0.35, sy - r * 0.35)],
                            (255, 210, 122, 255))
    elif state == 'rest':
        dy = 1.5 * math.sin(t * 2 * math.pi)
        _body(pen, 0, dy, body)
        _eyes_closed(pen, 0, dy)
        _mouth_smile(pen, 0, dy)
        pen.polygon([(90, 86), (108, 86), (106, 100), (92, 100)], (242, 239, 232, 255))
        pen.arc(108, 92, 4, 270, 90, (242, 239, 232, 255), 3)
        rise = (t * 10) % 10
        for x in (96, 102):
            pen.line([(x, 80 - rise), (x - 2, 74 - rise)], (201, 199, 214, int(200 * (1 - rise / 10))), 2)
    elif state == 'remind':
        dx = 3 * math.sin(t * 6 * math.pi) * (1 - t)
        _body(pen, dx, 0, body)
        _eyes_open(pen, dx, 0)
        pen.line([(56 + dx, 80), (64 + dx, 80)], INK, 3)
        pen.ellipse(96, 24, 12, 12, (255, 176, 32, 255))
        pen.line([(96, 18), (96, 25)], INK, 3.4)
        pen.ellipse(96, 30, 1.8, 1.8, INK)
    else:   # sleep / offline
        color = BODY_OFFLINE if state == 'offline' else body
        breathe = 1.5 * math.sin(t * 2 * math.pi)
        _body(pen, 0, 2, color, squash=breathe)
        _eyes_closed(pen, 0, 4)
        pen.line([(57, 82), (63, 82)], INK, 3)
        for k, (zx, zy) in enumerate(((88, 34), (100, 20))):
            phase = (t + k * 0.5) % 1.0
            a = int(255 * (1 - phase))
            y = zy - phase * 8
            r = 5 if k == 0 else 4
            pen.line([(zx - r, y - r), (zx + r, y - r), (zx - r, y + r), (zx + r, y + r)], (196, 181, 253, a), 2.4)
    return pen.done(size)


def parse_color(value) -> tuple:
    """'#7a52d5' 或 (r, g, b[, a]) → RGBA tuple；None 用預設紫"""
    if not value:
        return BODY
    if isinstance(value, str):
        v = value.lstrip('#')
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16), 255)
    return tuple(value) + ((255,) if len(value) == 3 else ())


@lru_cache(maxsize=64)
def _cached(state: str, size: int, body: tuple = BODY) -> tuple:
    return tuple((frame(state, i, size, body), FRAME_MS) for i in range(COUNTS[state]))


def frames(state: str, size: int, body=None) -> list[tuple[Image.Image, int]]:
    """body：身體顏色（跟隨主題色時傳入），None = 預設紫"""
    state = state if state in COUNTS else 'idle'
    return list(_cached(state, int(size), parse_color(body)))