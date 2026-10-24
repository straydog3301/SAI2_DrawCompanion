# -*- coding: utf-8 -*-
"""寵物的對話泡泡：取代 1.x 的狀態列訊息與系統訊息框。可附 1～2 個按鈕，逾時自動收起。
外觀可以換成使用者的圖（九宮格，core/bubble_skin.py）"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core import bubble_skin
from ui2 import theme

PAPER = QColor('#f6f4ef')
INK = '#1b1a22'
MARGIN = 8
PAD = 4                              # 自訂外觀：文字範圍內再留一點空間


class BubbleBody(QWidget):
    """泡泡本體（文字＋按鈕＋外觀）。視窗版 Bubble 與設定頁的預覽共用"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.lay = QVBoxLayout(self)
        self.lay.setSpacing(8)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(260)
        self.lay.addWidget(self.label)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        self.lay.addLayout(self.buttons)
        self.skin = bubble_skin.normalize(None)
        self.pix: QPixmap | None = None
        self.set_skin(None, None)

    def set_skin(self, skin, image_path: str | None):
        """skin：pet.bubble_skin；image_path：圖片完整路徑（None = 內建外觀）"""
        self.skin = bubble_skin.normalize(skin)
        pix = QPixmap(image_path) if image_path else None
        self.pix = pix if pix is not None and not pix.isNull() else None
        if self.pix is None:
            self.ink = INK
            self.lay.setContentsMargins(MARGIN + 12, MARGIN + 10, MARGIN + 12, MARGIN + 10)
        else:
            self.ink = self.skin['color']
            k = self.skin['scale']
            l, t, r, b = self.margins()
            self.lay.setContentsMargins(*(int(round(v * k)) + PAD for v in (l, t, r, b)))
        self.label.setStyleSheet(f'color:{self.ink};font-size:13px;background:transparent;')
        if self.isVisible():                       # 看不見時不先量大小：第一次量文字會載入字型，別拖慢啟動
            self.adjustSize()
        self.update()

    def margins(self) -> tuple[int, int, int, int]:
        return bubble_skin.margins(self.skin['text'], self.pix.width(), self.pix.height())

    def set_message(self, text: str, actions=(), on_click=None):
        self.label.setText(text)
        longest = max((self.label.fontMetrics().horizontalAdvance(x) for x in text.splitlines()), default=0)
        self.label.setMinimumWidth(min(longest + 2, 220))     # 長句子不要被擠成很窄的一條
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        for i, (text_, fn) in enumerate(actions):
            b = QPushButton(text_)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                'QPushButton{border:none;border-radius:8px;padding:5px 12px;font-size:12px;'
                + (f'background:{theme.ACCENT_BTN};color:white;}}' if i == 0 else f'background:#e4e1d8;color:{INK};}}'))
            b.clicked.connect(lambda _=False, f=fn: (on_click() if on_click else None, f()))
            self.buttons.addWidget(b)
        self.buttons.addStretch(1)
        self.adjustSize()

    def minimumSizeHint(self):
        s = super().minimumSizeHint()
        if self.pix is not None:              # 至少放得下四個角
            l, t, r, b = self.margins()
            k = self.skin['scale']
            s.setWidth(max(s.width(), int((l + r) * k) + 2))
            s.setHeight(max(s.height(), int((t + b) * k) + 2))
        return s

    def sizeHint(self):
        return super().sizeHint().expandedTo(self.minimumSizeHint())

    def fit(self):
        """嵌在版面裡（預覽）時依文字重新算大小；自動換行的文字要靠 adjustSize 才算得對"""
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.adjustSize()
        self.setFixedSize(self.size())

    def _compose(self) -> QImage:
        """以實際像素拼出九宮格，避免高 DPI 下格子之間出現細縫"""
        dpr = self.devicePixelRatioF()
        w, h = max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr))
        key = (w, h, self.skin['scale'], tuple(self.margins()), self.pix.cacheKey())
        if getattr(self, '_cache_key', None) == key:
            return self._cache
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.SmoothPixmapTransform)
        for s, d in bubble_skin.slices(self.pix.width(), self.pix.height(), self.margins(), w, h,
                                       self.skin['scale'] * dpr):
            q.drawPixmap(QRect(*d), self.pix, QRect(*s))
        q.end()
        self._cache_key, self._cache = key, img
        return img

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.pix is not None:
            p.drawImage(self.rect(), self._compose())
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN), 12, 12)
        p.setPen(Qt.NoPen)
        for i in range(MARGIN, 0, -2):                          # 柔和陰影
            p.setBrush(QColor(0, 0, 0, 6))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(MARGIN - i, MARGIN - i + 2, -MARGIN + i, -MARGIN + i + 2), 14, 14)
        p.setBrush(PAPER)
        p.drawPath(path)


class Bubble(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.body = BubbleBody(self)
        lay.addWidget(self.body)
        self.label = self.body.label
        self.buttons = self.body.buttons
        self._hide = QTimer(self, singleShot=True, timeout=self.hide)
        self.anchor = None                 # 寵物視窗
        self.key = ''

    def set_skin(self, skin, image_path: str | None):
        self.body.set_skin(skin, image_path)
        if self.isVisible():
            self.adjustSize()
            self.reposition()

    def show_message(self, text: str, actions=(), seconds: float = 6.0, key: str = ''):
        """actions: [(按鈕文字, callable)]；有按鈕時預設停留久一點"""
        self.key = key
        self.body.set_message(text, actions, on_click=self.hide)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._hide.start(int((seconds if not actions else max(seconds, 15)) * 1000))

    def reposition(self):
        if self.anchor is None:
            return
        a = self.anchor.frameGeometry()
        g = (self.anchor.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = a.center().x() - self.width() + 24                 # 預設在寵物左上方
        if x < g.left():
            x = a.center().x() - 24
        y = a.top() - self.height() + 6
        if y < g.top():
            y = a.bottom() - 6
        self.move(QPoint(max(g.left(), min(x, g.right() - self.width())), y))
