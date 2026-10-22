# -*- coding: utf-8 -*-
"""寵物的對話泡泡：取代 1.x 的狀態列訊息與系統訊息框。可附 1～2 個按鈕，逾時自動收起"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

PAPER = QColor('#f6f4ef')
INK = '#1b1a22'
MARGIN = 8


class Bubble(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGIN + 12, MARGIN + 10, MARGIN + 12, MARGIN + 10)
        lay.setSpacing(8)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(260)
        self.label.setStyleSheet(f'color:{INK};font-size:13px;')
        lay.addWidget(self.label)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        lay.addLayout(self.buttons)
        self._hide = QTimer(self, singleShot=True, timeout=self.hide)
        self.anchor = None                 # 寵物視窗
        self.key = ''

    def show_message(self, text: str, actions=(), seconds: float = 6.0, key: str = ''):
        """actions: [(按鈕文字, callable)]；有按鈕時預設停留久一點"""
        self.key = key
        self.label.setText(text)
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, (label, fn) in enumerate(actions):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                'QPushButton{border:none;border-radius:8px;padding:5px 12px;font-size:12px;'
                + ('background:#7c3aed;color:white;}' if i == 0 else f'background:#e4e1d8;color:{INK};}}'))
            b.clicked.connect(lambda _=False, f=fn: (self.hide(), f()))
            self.buttons.addWidget(b)
        self.buttons.addStretch(1)
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

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN), 12, 12)
        p.setPen(Qt.NoPen)
        for i in range(MARGIN, 0, -2):                          # 柔和陰影
            p.setBrush(QColor(0, 0, 0, 6))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(MARGIN - i, MARGIN - i + 2, -MARGIN + i, -MARGIN + i + 2), 14, 14)
        p.setBrush(PAPER)
        p.drawPath(path)
