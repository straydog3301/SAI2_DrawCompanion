# -*- coding: utf-8 -*-
"""
桌面寵物視窗：逐像素透明、置頂、不出現在工作列；可自由拖曳（移動 ≥ 4 px 才算拖曳，否則算點擊）。
放開後記住位置（依螢幕分別記錄），螢幕變動時拉回可見範圍；可選貼齊螢幕邊緣。
"""

from __future__ import annotations

import json

from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from ui2 import winutil

DRAG_THRESHOLD = 4
SNAP_DISTANCE = 24


def to_pixmap(img: Image.Image) -> QPixmap:
    img = img.convert('RGBA')
    q = QImage(img.tobytes('raw', 'RGBA'), img.width, img.height, img.width * 4, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(q)


class PetWindow(QWidget):
    clicked = Signal()
    menu_requested = Signal(QPoint)
    moved = Signal()

    def __init__(self, positions_file: str = ''):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle('DrawCompanion 寵物')
        self.positions_file = positions_file
        self.snap_edges = False
        self.frames: list[tuple[QPixmap, int]] = []
        self.loop = True
        self.idx = 0
        self._press = None
        self._dragging = False
        self._anim = QTimer(self, singleShot=True, timeout=self._next)
        self._anim.setTimerType(Qt.PreciseTimer)        # 預設精度約 16ms，動畫會被拉慢
        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda *_: QTimer.singleShot(0, self.clamp_to_screens))
        app.screenRemoved.connect(lambda *_: QTimer.singleShot(0, self.clamp_to_screens))

    # ── 動畫 ──
    def set_animation(self, frames: list[tuple[QPixmap, int]], loop: bool = True):
        if not frames:
            return
        size_changed = not self.frames or frames[0][0].size() != self.frames[0][0].size()
        self.frames, self.loop, self.idx = frames, loop, 0
        if size_changed:
            bottom_center = self.geometry().center().x(), self.geometry().bottom()
            self.resize(frames[0][0].size() / frames[0][0].devicePixelRatio())
            if self.isVisible():                         # 換大小時以腳底中心為準
                self.move(bottom_center[0] - self.width() // 2, bottom_center[1] - self.height() + 1)
        self.update()
        self._anim.start(frames[0][1])

    def _next(self):
        if self.idx + 1 >= len(self.frames) and not self.loop:
            return                                       # 只播一次：停在最後一格
        self.idx = (self.idx + 1) % len(self.frames)
        self.update()
        self._anim.start(self.frames[self.idx][1])

    def paintEvent(self, _e):
        if not self.frames:
            return
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawPixmap(self.rect(), self.frames[self.idx][0])

    # ── 拖曳與點擊 ──
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
            self.moved.emit()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._press:
            return
        self._press = None
        if self._dragging:
            self._dragging = False
            if self.snap_edges:
                self.snap_to_edges()
            self.clamp_to_screens()
            self.save_position()
            self.moved.emit()
        else:
            self.clicked.emit()

    def contextMenuEvent(self, e):
        self.menu_requested.emit(e.globalPos())

    # ── 置頂 ──
    def heal_topmost(self):
        if self.isVisible():
            winutil.force_topmost(winutil.hwnd_of(self))

    # ── 位置 ──
    def _screen_key(self) -> str:
        s = self.screen() or QGuiApplication.primaryScreen()
        g = s.geometry()
        return f'{s.name()}@{g.width()}x{g.height()}'

    def _read_positions(self) -> dict:
        try:
            with open(self.positions_file, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_position(self):
        if not self.positions_file:
            return
        data = self._read_positions()
        data[self._screen_key()] = [self.x(), self.y()]
        data['_last'] = self._screen_key()
        with open(self.positions_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)

    def restore_position(self):
        data = self._read_positions()
        try:
            x, y = data[data['_last']]
            self.move(int(x), int(y))
        except (KeyError, TypeError, ValueError):
            g = QGuiApplication.primaryScreen().availableGeometry()
            self.move(g.right() - self.width() - 48, g.bottom() - self.height() - 16)
        self.clamp_to_screens()

    def snap_to_edges(self):
        g = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x, y = self.x(), self.y()
        if abs(x - g.left()) < SNAP_DISTANCE:
            x = g.left()
        elif abs(g.right() - (x + self.width())) < SNAP_DISTANCE:
            x = g.right() - self.width() + 1
        if abs(g.bottom() - (y + self.height())) < SNAP_DISTANCE:
            y = g.bottom() - self.height() + 1
        elif abs(y - g.top()) < SNAP_DISTANCE:
            y = g.top()
        self.move(x, y)

    def clamp_to_screens(self) -> bool:
        """視窗中心不在任何螢幕上時（螢幕拔掉、解析度改變），拉回主螢幕可見範圍"""
        center = self.frameGeometry().center()
        if any(s.availableGeometry().contains(center) for s in QGuiApplication.screens()):
            return False
        g: QRect = QGuiApplication.primaryScreen().availableGeometry()
        self.move(min(max(self.x(), g.left()), g.right() - self.width()),
                  min(max(self.y(), g.top()), g.bottom() - self.height()))
        return True
