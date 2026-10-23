# -*- coding: utf-8 -*-
"""圖表元件：長條圖（滑過顯示數值）、迷你走勢、月曆熱度格"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from core import stats
from ui2 import theme


class BarChart(QWidget):
    def __init__(self, bars=None, height: int = 220):
        super().__init__()
        self.bars = bars or []
        self.setMinimumHeight(height)
        self.setMouseTracking(True)
        self._hover = -1
        self._rects: list[QRectF] = []

    def set_bars(self, bars):
        self.bars = bars
        self._hover = -1
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        left, right, top, bottom = 44, 8, 10, 26
        w, h = self.width() - left - right, self.height() - top - bottom
        f = p.font()
        f.setPixelSize(11)
        p.setFont(f)
        if not self.bars:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, '還沒有紀錄')
            return
        ymax = max([b.seconds for b in self.bars] + [3600.0])
        for i in range(5):
            y = top + h * (1 - i / 4)
            p.setPen(QPen(QColor(theme.DIVIDER), 1, Qt.DashLine if i else Qt.SolidLine))
            p.drawLine(left, int(y), left + w, int(y))
            p.setPen(QColor(theme.SUBTLE))
            p.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignRight | Qt.AlignVCenter, stats.fmt_axis(ymax * i / 4))
        n = len(self.bars)
        bw = w / n
        gap = 1 if bw < 6 else (2 if bw < 12 else max(3, bw * 0.25))
        self._rects = []
        for i, b in enumerate(self.bars):
            x = left + i * bw + gap / 2
            bh = h * b.seconds / ymax
            r = QRectF(x, top + h - max(bh, 2), max(1.0, bw - gap), max(bh, 2))
            self._rects.append(QRectF(left + i * bw, top, bw, h))
            color = theme.ACCENT if i == self._hover else (theme.BAR if b.seconds > 0 else theme.TRACK)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(r, min(4, r.width() / 2), min(4, r.width() / 2))
            if b.label:
                p.setPen(QColor(theme.MUTED))
                p.drawText(QRectF(x - 30 + (bw - gap) / 2, top + h + 6, 60, 16), Qt.AlignCenter, b.label)

    def mouseMoveEvent(self, e):
        pos = e.position()
        idx = next((i for i, r in enumerate(self._rects) if r.contains(pos)), -1)
        if idx != self._hover:
            self._hover = idx
            self.update()
            if idx >= 0:
                QToolTip.showText(self.mapToGlobal(QPoint(int(pos.x()), int(pos.y()) - 30)), self.bars[idx].tooltip, self)
            else:
                QToolTip.hideText()

    def leaveEvent(self, _e):
        self._hover = -1
        self.update()


class Sparkline(QWidget):
    def __init__(self, series, width: int = 110, height: int = 26):
        super().__init__()
        self.series = list(series or [])
        self.setFixedSize(width, height)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.series) or 1
        peak = max(self.series) if self.series else 0
        bw = self.width() / n
        for i, v in enumerate(self.series):
            if v <= 0 or peak <= 0:
                p.fillRect(QRectF(i * bw + 1, self.height() - 2, bw - 2, 2), QColor(theme.TRACK))
                continue
            bh = max(3, (self.height() - 2) * v / peak)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(QRectF(i * bw + 1, self.height() - bh, bw - 2, bh), 1.5, 1.5)




class MonthGrid(QWidget):
    """月曆熱度：顏色深淺 = 當天打卡數；請假日標記；點擊選日期"""
    picked = Signal(str)
    WEEKDAYS = '一二三四五六日'

    def __init__(self):
        super().__init__()
        self.cal = None
        self.selected = ''
        self.setMinimumHeight(300)
        self.setMouseTracking(True)
        self._cells: list[tuple[QRectF, dict]] = []

    def set_month(self, cal: dict, selected: str = ''):
        self.cal = cal
        self.selected = selected
        self.update()

    def paintEvent(self, _e):
        if not self.cal:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = p.font()
        f.setPixelSize(11)
        p.setFont(f)
        cols = 7
        head = 22
        rows = len(self.cal['weeks'])
        gap = 6
        cw = (self.width() - gap * (cols - 1)) / cols
        ch = min(cw, (self.height() - head - gap * rows) / rows)
        for i, d in enumerate(self.WEEKDAYS):
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(i * (cw + gap), 0, cw, head), Qt.AlignCenter, d)
        self._cells = []
        f.setPixelSize(13)
        p.setFont(f)
        for r, week in enumerate(self.cal['weeks']):
            for c, cell in enumerate(week):
                if not cell:
                    continue
                rect = QRectF(c * (cw + gap), head + gap + r * (ch + gap), cw, ch)
                self._cells.append((rect, cell))
                level = min(cell['done'], 3)
                color = QColor(theme.HEAT[level]) if not cell['future'] else QColor(theme.BG)
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(rect, 10, 10)
                if cell['key'] == self.selected or cell['today']:
                    p.setPen(QPen(QColor(theme.TEXT if cell['key'] == self.selected else theme.WARNING), 2))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 9, 9)
                p.setPen(QColor(theme.SUBTLE if cell['future'] else ('#ffffff' if level >= 2 else theme.TEXT)))
                p.drawText(rect.adjusted(8, 6, -6, -6), Qt.AlignLeft | Qt.AlignTop, str(cell['day']))
                if cell['rest'] and not cell['done']:
                    p.setPen(QColor(theme.ACCENT_TEXT))
                    p.drawText(rect.adjusted(6, 6, -8, -6), Qt.AlignRight | Qt.AlignBottom, '請假')
                elif cell['done']:
                    p.setPen(QColor('#ffffff' if level >= 2 else theme.ACCENT_TEXT))
                    p.drawText(rect.adjusted(6, 6, -8, -6), Qt.AlignRight | Qt.AlignBottom, f"✓{cell['done']}")

    def mouseReleaseEvent(self, e):
        for rect, cell in self._cells:
            if rect.contains(e.position()) and not cell['future']:
                self.selected = cell['key']
                self.update()
                self.picked.emit(cell['key'])
                return
