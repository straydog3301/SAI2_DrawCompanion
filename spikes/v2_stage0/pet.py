# -*- coding: utf-8 -*-
"""
驗證 1：桌面寵物視窗
- 逐像素透明、無邊框、置頂、不出現在工作列
- 自由拖曳（移動 ≥ 4 px 才算拖曳，否則算點擊），放開記住位置（依螢幕分別記錄），螢幕變動時拉回可見範圍
- 影格以 Pillow 解碼（PNG / GIF / APNG / WebP / 橫排精靈圖），依每格時間播放
- 定時重新置頂（被其他置頂視窗或全螢幕程式蓋過時自我修復）
"""

from __future__ import annotations

import json
import os
import time

from PIL import Image, ImageDraw, ImageSequence
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

import winutil

DRAG_THRESHOLD = 4


# ─── 影格 ───────────────────────────────────────────────────────────────

def load_frames(path: str, size: int, frames: int | None = None, fps: float | None = None) -> list[tuple[QPixmap, int]]:
    """解碼成 [(QPixmap, 毫秒)]；frames 有值時視為橫排精靈圖。載入時就縮到顯示大小，記憶體不隨原圖暴增"""
    im = Image.open(path)
    out = []
    if frames:
        w = im.width // frames
        raw = [im.crop((i * w, 0, (i + 1) * w, im.height)) for i in range(frames)]
        durs = [int(1000 / (fps or 12))] * frames
    else:
        raw, durs = [], []
        for fr in ImageSequence.Iterator(im):
            raw.append(fr.convert('RGBA'))
            durs.append(int(fr.info.get('duration') or im.info.get('duration') or 100))
    for fr, ms in zip(raw, durs):
        fr = fr.convert('RGBA')
        fr.thumbnail((size, size), Image.LANCZOS)
        canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        canvas.paste(fr, ((size - fr.width) // 2, size - fr.height))          # 腳底置中
        data = canvas.tobytes('raw', 'RGBA')
        qimg = QImage(data, size, size, size * 4, QImage.Format_RGBA8888).copy()
        out.append((QPixmap.fromImage(qimg), max(16, ms)))
    return out


def make_demo_assets(folder: str, n: int = 24, side: int = 512) -> dict[str, str]:
    """產生測試用角色（半透明邊緣的跳動墨團）：APNG、GIF、WebP、橫排精靈圖"""
    os.makedirs(folder, exist_ok=True)
    frames = []
    for i in range(n):
        big = Image.new('RGBA', (side * 2, side * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        import math
        bob = int(60 * abs(math.sin(i / n * math.pi * 2)))
        cx, cy, r = side, side + 200 - bob, 330
        d.ellipse((cx - r - 40, side * 2 - 120, cx + r + 40, side * 2 - 60), fill=(0, 0, 0, 70))   # 半透明影子
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(109, 91, 208, 255))
        d.ellipse((cx - 130, cy - 60, cx - 70, cy + 20), fill=(27, 26, 34, 255))
        d.ellipse((cx + 70, cy - 60, cx + 130, cy + 20), fill=(27, 26, 34, 255))
        frames.append(big.resize((side, side), Image.LANCZOS))
    paths = {
        'apng': os.path.join(folder, 'demo.apng'),
        'gif': os.path.join(folder, 'demo.gif'),
        'webp': os.path.join(folder, 'demo.webp'),
        'sprite': os.path.join(folder, 'demo_sprite.png'),
    }
    frames[0].save(paths['apng'], format='PNG', save_all=True, append_images=frames[1:], duration=42, loop=0)
    frames[0].save(paths['gif'], save_all=True, append_images=frames[1:], duration=42, loop=0, disposal=2)
    frames[0].save(paths['webp'], save_all=True, append_images=frames[1:], duration=42, loop=0, lossless=True)
    sheet = Image.new('RGBA', (side * n, side), (0, 0, 0, 0))
    for i, fr in enumerate(frames):
        sheet.paste(fr, (i * side, 0))
    sheet.save(paths['sprite'])
    return paths


# ─── 視窗 ───────────────────────────────────────────────────────────────

class PetWindow(QWidget):
    clicked = Signal()
    dragged = Signal(QPoint)

    def __init__(self, frames: list[tuple[QPixmap, int]], state_file: str = '', heal_ms: int = 2000):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.state_file = state_file
        self.frames = frames
        self.idx = 0
        self.painted = 0
        self._press = None
        self._dragging = False
        size = frames[0][0].size()
        self.resize(size)
        self._anim = QTimer(self, singleShot=True, timeout=self._next)
        self._anim.setTimerType(Qt.PreciseTimer)      # 預設計時器精度約 16ms，42ms 一格會被拉長成 47ms
        self._heal = QTimer(self, interval=heal_ms, timeout=self.heal_topmost)
        screens = QGuiApplication.instance()
        screens.screenAdded.connect(lambda *_: self.clamp_to_screens())
        screens.screenRemoved.connect(lambda *_: QTimer.singleShot(0, self.clamp_to_screens))
        self.restore_position()

    # 動畫
    def start(self):
        self.show()
        self._anim.start(self.frames[0][1])
        self._heal.start()

    def set_frames(self, frames):
        self.frames, self.idx = frames, 0
        self.resize(frames[0][0].size())
        self.update()

    def _next(self):
        self.idx = (self.idx + 1) % len(self.frames)
        self.update()
        self._anim.start(self.frames[self.idx][1])

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawPixmap(0, 0, self.frames[self.idx][0])
        self.painted += 1

    # 拖曳與點擊
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = (e.globalPosition().toPoint(), self.pos())
            self._dragging = False

    def mouseMoveEvent(self, e):
        if not self._press:
            return
        start, origin = self._press
        delta = e.globalPosition().toPoint() - start
        if not self._dragging and delta.manhattanLength() >= DRAG_THRESHOLD:
            self._dragging = True
        if self._dragging:
            self.move(origin + delta)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._press:
            return
        self._press = None
        if self._dragging:
            self._dragging = False
            self.save_position()
            self.dragged.emit(self.pos())
        else:
            self.clicked.emit()

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction('控制中心（驗證版未實作）')
        m.addAction('隱藏 30 分（驗證版未實作）')
        m.addSeparator()
        m.addAction('結束', QGuiApplication.instance().quit)
        m.exec(e.globalPos())

    # 置頂自我修復
    def heal_topmost(self):
        if self.isVisible():
            winutil.force_topmost(winutil.hwnd_of(self))

    # 位置記憶
    def _screen_key(self) -> str:
        s = self.screen()
        g = s.geometry()
        return f'{s.name()}@{g.width()}x{g.height()}'

    def save_position(self):
        if not self.state_file:
            return
        data = {}
        try:
            with open(self.state_file, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            pass
        data[self._screen_key()] = [self.x(), self.y()]
        data['_last'] = self._screen_key()
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)

    def restore_position(self):
        try:
            with open(self.state_file, encoding='utf-8') as f:
                data = json.load(f)
            x, y = data[data['_last']]
            self.move(x, y)
        except (OSError, ValueError, KeyError, TypeError):
            g = QGuiApplication.primaryScreen().availableGeometry()
            self.move(g.right() - self.width() - 40, g.bottom() - self.height() - 20)
        self.clamp_to_screens()

    def clamp_to_screens(self):
        """視窗中心不在任何螢幕上時（螢幕拔掉、解析度改變），拉回主螢幕可見範圍"""
        center = self.frameGeometry().center()
        for s in QGuiApplication.screens():
            if s.availableGeometry().contains(center):
                return False
        g: QRect = QGuiApplication.primaryScreen().availableGeometry()
        self.move(min(max(self.x(), g.left()), g.right() - self.width()),
                  min(max(self.y(), g.top()), g.bottom() - self.height()))
        return True


def measure_fps(pet: PetWindow, seconds: float, app) -> float:
    """實際畫面更新次數 / 秒（用來確認動畫不掉格）"""
    start, t0 = pet.painted, time.perf_counter()
    end = t0 + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)
    return (pet.painted - start) / (time.perf_counter() - t0)
