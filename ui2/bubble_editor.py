# -*- coding: utf-8 -*-
"""對話泡泡外觀：在圖片上圈出文字範圍（九宮格的中間格），旁邊即時預覽撐開後的泡泡"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget

from core import bubble_skin
from ui2 import theme
from ui2.bubble import BubbleBody
from ui2.widgets import button, label

SAMPLE = '已經連續畫了 50 分鐘，起來喝口水、動一動吧'
GRAB = 8                         # 邊線可拖曳的距離（畫面 px）


class RangeCanvas(QWidget):
    """顯示圖片，拖曳畫出 / 移動 / 調整文字範圍"""
    changed = Signal(list)

    def __init__(self, pix: QPixmap, rect, box=QSize(480, 360)):
        super().__init__()
        self.pix = pix
        w, h = pix.width(), pix.height()
        self.k = min(box.width() / w, box.height() / h, 4.0)
        self.setFixedSize(max(1, int(w * self.k)), max(1, int(h * self.k)))
        self.rect_px = bubble_skin.clamp_rect(rect, w, h)
        self._drag = None                    # ('new', 起點) / ('move', 起點, 原範圍) / ('edges', {l,t,r,b})
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    def set_rect(self, rect):
        self.rect_px = bubble_skin.clamp_rect(rect, self.pix.width(), self.pix.height())
        self.update()
        self.changed.emit(list(self.rect_px))

    def _view(self) -> QRectF:
        x, y, w, h = self.rect_px
        return QRectF(x * self.k, y * self.k, w * self.k, h * self.k)

    def _to_img(self, p: QPointF) -> tuple[float, float]:
        return p.x() / self.k, p.y() / self.k

    def _edges_at(self, p: QPointF) -> set:
        r = self._view()
        near_x = r.top() - GRAB <= p.y() <= r.bottom() + GRAB
        near_y = r.left() - GRAB <= p.x() <= r.right() + GRAB
        out = set()
        if near_x and abs(p.x() - r.left()) <= GRAB:
            out.add('l')
        if near_x and abs(p.x() - r.right()) <= GRAB:
            out.add('r')
        if near_y and abs(p.y() - r.top()) <= GRAB:
            out.add('t')
        if near_y and abs(p.y() - r.bottom()) <= GRAB:
            out.add('b')
        return out

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        p = e.position()
        edges = self._edges_at(p)
        if edges:
            self._drag = ('edges', edges)
        elif self._view().contains(p):
            self._drag = ('move', self._to_img(p), list(self.rect_px))
        else:
            self._drag = ('new', self._to_img(p))

    def mouseMoveEvent(self, e):
        p = e.position()
        if not self._drag:
            edges = self._edges_at(p)
            if edges in ({'l'}, {'r'}):
                self.setCursor(Qt.SizeHorCursor)
            elif edges in ({'t'}, {'b'}):
                self.setCursor(Qt.SizeVerCursor)
            elif edges in ({'l', 't'}, {'r', 'b'}):
                self.setCursor(Qt.SizeFDiagCursor)
            elif edges:
                self.setCursor(Qt.SizeBDiagCursor)
            else:
                self.setCursor(Qt.SizeAllCursor if self._view().contains(p) else Qt.CrossCursor)
            return
        x, y = self._to_img(p)
        kind = self._drag[0]
        if kind == 'new':
            x0, y0 = self._drag[1]
            rect = [min(x0, x), min(y0, y), abs(x - x0), abs(y - y0)]
        elif kind == 'move':
            (x0, y0), (rx, ry, rw, rh) = self._drag[1], self._drag[2]
            rect = [rx + x - x0, ry + y - y0, rw, rh]
        else:
            rx, ry, rw, rh = self.rect_px
            l, t, r, b = rx, ry, rx + rw, ry + rh
            edges = self._drag[1]
            if 'l' in edges:
                l = min(x, r - bubble_skin.MIN_TEXT)
            if 'r' in edges:
                r = max(x, l + bubble_skin.MIN_TEXT)
            if 't' in edges:
                t = min(y, b - bubble_skin.MIN_TEXT)
            if 'b' in edges:
                b = max(y, t + bubble_skin.MIN_TEXT)
            rect = [l, t, r - l, b - t]
        self.set_rect(rect)

    def mouseReleaseEvent(self, _e):
        self._drag = None

    def paintEvent(self, _e):
        p = QPainter(self)
        cell = 10                                   # 棋盤格底，看得出透明的地方
        for yy in range(0, self.height(), cell):
            for xx in range(0, self.width(), cell):
                p.fillRect(xx, yy, cell, cell, QColor('#d9d9de') if (xx // cell + yy // cell) % 2 else QColor('#f2f2f5'))
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(self.rect(), self.pix)
        r = self._view()
        shade = QColor(0, 0, 0, 90)                 # 文字範圍以外調暗
        p.fillRect(QRectF(0, 0, self.width(), r.top()), shade)
        p.fillRect(QRectF(0, r.bottom(), self.width(), self.height() - r.bottom()), shade)
        p.fillRect(QRectF(0, r.top(), r.left(), r.height()), shade)
        p.fillRect(QRectF(r.right(), r.top(), self.width() - r.right(), r.height()), shade)
        pen = QPen(QColor(255, 255, 255, 200), 1, Qt.DashLine)   # 九宮格切線延伸到整張圖
        p.setPen(pen)
        for xx in (r.left(), r.right()):
            p.drawLine(QPointF(xx, 0), QPointF(xx, self.height()))
        for yy in (r.top(), r.bottom()):
            p.drawLine(QPointF(0, yy), QPointF(self.width(), yy))
        p.setPen(QPen(QColor(theme.ACCENT), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        p.setBrush(QColor(theme.ACCENT))
        p.setPen(QPen(QColor('white'), 1))
        for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
            p.drawEllipse(c, 4.5, 4.5)


class TextRangeDialog(QDialog):
    def __init__(self, parent, image_path: str, skin: dict):
        super().__init__(parent)
        self.setWindowTitle('圈選文字範圍')
        self.skin = bubble_skin.normalize(skin)
        pix = QPixmap(image_path)
        self.image_path = image_path
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)
        lay.addWidget(label('在圖上拖曳，框出要放文字的地方', 'h2'))
        lay.addWidget(label('框外的四個角不會變形；上下兩邊只會左右拉長、左右兩邊只會上下拉長，'
                            '所以框要避開圖案上的花紋與尾巴。可以拖曳框的邊線微調，或在框內拖曳移動。', 'muted'))
        body = QHBoxLayout()
        body.setSpacing(20)
        self.canvas = RangeCanvas(pix, self.skin['text'])
        body.addWidget(self.canvas, 0, Qt.AlignTop)
        side = QVBoxLayout()
        side.addWidget(label('預覽', 'caption'))
        self.short = BubbleBody()
        self.long = BubbleBody()
        side.addWidget(self.short, 0, Qt.AlignLeft)
        side.addWidget(self.long, 0, Qt.AlignLeft)
        side.addStretch(1)
        body.addLayout(side, 1)
        lay.addLayout(body)
        foot = QHBoxLayout()
        reset = button('重設範圍', 'ghost')
        reset.clicked.connect(lambda: self.canvas.set_rect(None))
        foot.addWidget(reset)
        foot.addStretch(1)
        cancel = button('取消')
        cancel.clicked.connect(self.reject)
        ok = button('確定', 'primary')
        ok.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        lay.addLayout(foot)
        self.canvas.changed.connect(self._preview)
        self._preview(self.canvas.rect_px)

    def _preview(self, rect):
        self.skin['text'] = list(rect)
        for body, text in ((self.short, '畫得好！'), (self.long, SAMPLE)):
            body.set_skin(self.skin, self.image_path)
            body.set_message(text)
            body.fit()

    def result_rect(self) -> list[int]:
        return list(self.canvas.rect_px)
