# -*- coding: utf-8 -*-
"""
寵物下方的小膠囊：本次動筆時間＋縮時錄影開關（取代 1.x 精簡模式的計時器與錄影按鈕）
- 只在 SAI2 開著時出現；1.x 執行中（2.0 暫停記錄）時顯示「暫停」且錄影按鈕停用
- 點時間 → 開快捷面板；點紅點 → 開始／停止錄影
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui2 import theme

H = 30


def fmt_clock(sec: float) -> str:
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


class StatusCapsule(QWidget):
    open_panel = Signal()
    toggle_record = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.text = '00:00'
        self.drawing = False
        self.recording = False      # 錄影開著
        self.rec_active = False     # 正在錄某個檔案
        self.paused = False
        self._hover_rec = False
        self.anchor = None
        self.resize(118, H)

    def set_status(self, st):
        self.paused = not st.tracking
        self.drawing = st.drawing
        self.recording = st.recording
        self.rec_active = bool(st.rec_file)
        self.text = '暫停（1.x）' if self.paused else fmt_clock(st.session_draw)
        w = self.fontMetrics().horizontalAdvance(self.text) + 76
        if w != self.width():
            self.resize(w, H)
            self.reposition()
        tip = ('1.x 正在執行，2.0 暫停記錄' if self.paused else
               f'本次動筆 {fmt_clock(st.session_draw)}　今天 {int(st.today_draw // 60)} 分（點一下開快捷面板）')
        self.setToolTip(tip)
        self.update()

    def _rec_rect(self) -> QRectF:
        return QRectF(self.width() - 34, 3, 28, H - 6)

    def reposition(self):
        if self.anchor is None:
            return
        a = self.anchor.frameGeometry()
        g = (self.anchor.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = a.center().x() - self.width() // 2
        y = a.bottom() + 2
        if y + self.height() > g.bottom():
            y = a.top() - self.height() - 2
        self.move(max(g.left(), min(x, g.right() - self.width())), y)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(21, 21, 27, 225))
        p.drawRoundedRect(QRectF(self.rect()), H / 2, H / 2)
        dot = QColor('#4ade80') if self.drawing else QColor(theme.SUBTLE)
        if self.paused:
            dot = QColor(theme.WARNING)
        p.setBrush(dot)
        p.drawEllipse(QRectF(12, H / 2 - 4, 8, 8))
        p.setPen(QColor('#f2f1f6'))
        f = p.font()
        f.setPixelSize(theme.px(13))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(26, 0, self.width() - 64, H), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        p.setPen(QPen(QColor('#3a3946'), 1))
        p.drawLine(int(self.width() - 38), 7, int(self.width() - 38), H - 7)
        r = self._rec_rect()
        if self._hover_rec and not self.paused:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#2e2d38'))
            p.drawRoundedRect(r, 8, 8)
        c = r.center()
        if self.recording:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#ef4444' if self.rec_active else '#b45353'))
            p.drawEllipse(c, 6, 6)
        else:
            p.setPen(QPen(QColor(theme.SUBTLE if self.paused else '#d6d4e2'), 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, 5.5, 5.5)

    def mouseMoveEvent(self, e):
        hover = self._rec_rect().contains(e.position())
        if hover != self._hover_rec:
            self._hover_rec = hover
            self.setToolTip('停止縮時錄影' if self.recording else '開始縮時錄影') if hover else None
            self.update()

    def leaveEvent(self, _e):
        self._hover_rec = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._rec_rect().contains(e.position()):
            if not self.paused:
                self.toggle_record.emit()
        else:
            self.open_panel.emit()
