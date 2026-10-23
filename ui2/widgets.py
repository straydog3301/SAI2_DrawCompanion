# -*- coding: utf-8 -*-
"""
共用設計元件（主視窗、設定、快捷面板都用這一套，樣式只在 theme.QSS 定義一次）
- ToggleSwitch：開關（取代核取方塊）
- SettingGroup / SettingRow：Windows 11 設定風格的分組設定列（左邊標題＋說明，右邊控制項）
- Card、StatTile、PageHeader、Chip、ProgressBar、NavButton
"""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from ui2 import theme
from ui2.icons import icon

_pixmaps: dict = {}           # 圖檔路徑 → (修改時間, QPixmap)：縮圖會被覆寫，依修改時間判斷要不要重讀


def load_pixmap(path: str | None) -> QPixmap | None:
    import os
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _pixmaps.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    pm = QPixmap(path)
    if pm.isNull():
        return None
    if len(_pixmaps) > 200:
        _pixmaps.clear()
    _pixmaps[path] = (mtime, pm)
    return pm


def rounded_thumb(pm: QPixmap, w: int, h: int, radius: float, dpr: float = 1.0) -> QPixmap:
    """置中裁成 w×h（邏輯 px）的圓角縮圖"""
    size = QSize(int(w * dpr), int(h * dpr))
    scaled = pm.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x, y = (scaled.width() - size.width()) // 2, (scaled.height() - size.height()) // 2
    crop = scaled.copy(x, y, size.width(), size.height())
    out = QPixmap(size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius * dpr, radius * dpr)
    p.setClipPath(path)
    p.drawPixmap(0, 0, crop)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


def label(text: str = '', role: str = '', wrap: bool = True) -> QLabel:
    """role：title / h2 / body / muted / caption / warn / ok / accent"""
    lb = QLabel(text)
    lb.setWordWrap(wrap)
    if role:
        lb.setProperty('role', role)
    return lb


def button(text: str = '', kind: str = 'secondary', ic: str | None = None, tip: str = '') -> QPushButton:
    """kind：primary / secondary / ghost / link"""
    b = QPushButton(text)
    b.setProperty('kind', kind)
    b.setCursor(Qt.PointingHandCursor)
    if ic:
        color = '#ffffff' if kind == 'primary' else (theme.ACCENT_TEXT if kind == 'link' else theme.ICON)
        b.setIcon(icon(ic, color, 18))
        b.setIconSize(QSize(18, 18))
    if tip:
        b.setToolTip(tip)
    return b


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b'knob', self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get(self):
        return self._pos

    def _set(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get, _set)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setDuration(140 if theme.MOTION else 0)
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def sizeHint(self):
        return QSize(44, 24)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = QColor(theme.ACCENT_BTN)
        off = QColor(theme.TRACK if theme.IS_LIGHT else '#3a3946')
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos))
        if not self.isEnabled():
            track = QColor(theme.TRACK)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 2, 44, 20), 10, 10)
        p.setBrush(QColor('#ffffff'))
        x = 3 + self._pos * 20
        p.drawEllipse(QRectF(x, 5, 14, 14))
        if self.hasFocus():                          # 鍵盤焦點框
            p.setPen(QPen(QColor(theme.ACCENT_TEXT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, 42, 22), 11, 11)


class Card(QFrame):
    def __init__(self, title: str = '', subtitle: str = '', padding: int = 20, spacing: int = 12):
        super().__init__()
        self.setProperty('card', True)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding - 2, padding, padding)
        self.lay.setSpacing(spacing)
        if title or subtitle:
            head = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(2)
            if title:
                col.addWidget(label(title, 'h2'))
            if subtitle:
                col.addWidget(label(subtitle, 'caption'))
            head.addLayout(col, 1)
            self.head = head
            self.lay.addLayout(head)


class SettingRow(QWidget):
    """一列設定：左邊標題與說明，右邊控制項"""
    def __init__(self, title: str, desc: str = '', control: QWidget | None = None, stack: bool = False):
        super().__init__()
        self.setProperty('settingRow', True)
        lay = QVBoxLayout(self) if stack else QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10 if stack else 24)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(label(title, 'body'))
        if desc:
            text.addWidget(label(desc, 'caption'))
        lay.addLayout(text, 1)
        self.note = label('', 'warn')
        self.note.hide()
        if control is not None:
            if stack:
                lay.addWidget(control)
            else:
                lay.addWidget(control, 0, Qt.AlignVCenter | Qt.AlignRight)
        text.addWidget(self.note)

    def set_note(self, text: str):
        self.note.setText(text)
        self.note.setVisible(bool(text))


class SettingGroup(QWidget):
    """分組標題＋一張卡片，卡片內的設定列以細線分隔"""
    def __init__(self, title: str = '', desc: str = ''):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        if title:
            outer.addWidget(label(title, 'section'))
        if desc:
            outer.addWidget(label(desc, 'caption'))
        self.card = QFrame()
        self.card.setProperty('card', True)
        self.inner = QVBoxLayout(self.card)
        self.inner.setContentsMargins(0, 2, 0, 2)
        self.inner.setSpacing(0)
        outer.addWidget(self.card)
        self._rows = 0

    def add(self, row: QWidget) -> QWidget:
        if self._rows:
            line = QFrame()
            line.setProperty('divider', True)
            line.setFixedHeight(1)
            self.inner.addWidget(line)
        self.inner.addWidget(row)
        self._rows += 1
        return row

    def row(self, title: str, desc: str = '', control: QWidget | None = None, stack: bool = False) -> SettingRow:
        return self.add(SettingRow(title, desc, control, stack))


class StatTile(QFrame):
    def __init__(self, caption: str, value: str = '', sub: str = '', ic: str | None = None):
        super().__init__()
        self.setProperty('card', True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(4)
        top = QHBoxLayout()
        if ic:
            i = QLabel()
            i.setPixmap(icon(ic, theme.ACCENT_TEXT, 16).pixmap(16, 16))
            top.addWidget(i)
        top.addWidget(label(caption, 'caption'), 1)
        lay.addLayout(top)
        self.value = label(value, 'stat', wrap=False)
        lay.addWidget(self.value)
        self.sub = label(sub, 'caption')
        lay.addWidget(self.sub)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class ProgressBar(QWidget):
    def __init__(self, ratio: float = 0.0, color: str | None = None, height: int = 6):
        super().__init__()
        self.ratio = ratio
        self.color = color or theme.ACCENT
        self.setFixedHeight(height)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.TRACK))
        p.drawRoundedRect(QRectF(self.rect()), r, r)
        w = self.width() * max(0.0, min(1.0, self.ratio))
        if w > 0:
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(QRectF(0, 0, max(w, self.height()), self.height()), r, r)


class Chip(QLabel):
    def __init__(self, text: str, kind: str = 'neutral'):
        super().__init__(text)
        self.setProperty('chip', kind)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = ''):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(label(title, 'title', wrap=False))
        if subtitle:
            col.addWidget(label(subtitle, 'muted'))
        lay.addLayout(col, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        lay.addLayout(self.actions)


class NavButton(QPushButton):
    """側欄項目：圖示＋文字，可附「即將推出」標記"""
    def __init__(self, text: str, ic: str, badge: str = ''):
        super().__init__(text)
        self.setProperty('nav', True)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIcon(icon(ic, theme.NAV_TEXT, 18))
        self.setIconSize(QSize(18, 18))
        self.badge = badge
        if badge:
            self.setEnabled(False)
            self.setToolTip(badge)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.badge:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            f = p.font()
            f.setPixelSize(10)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(self.badge) + 12
            r = QRectF(self.width() - w - 10, (self.height() - 18) / 2, w, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.SURFACE3))
            p.drawRoundedRect(r, 9, 9)
            p.setPen(QColor(theme.SUBTLE))
            p.drawText(r, Qt.AlignCenter, self.badge)


class Segmented(QWidget):
    """分段選擇（2～4 個選項）"""
    changed = Signal(object)

    def __init__(self, options: list[tuple[object, str]], current=None):
        super().__init__()
        self.setProperty('segmented', True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.buttons = {}
        for value, text in options:
            b = QPushButton(text)
            b.setProperty('seg', True)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=value: self.set_value(v, emit=True))
            lay.addWidget(b)
            self.buttons[value] = b
        self.value = None
        self.set_value(current if current in self.buttons else options[0][0])

    def set_value(self, value, emit: bool = False):
        self.value = value
        for v, b in self.buttons.items():
            b.setChecked(v == value)
        if emit:
            self.changed.emit(value)


class Stepper(QWidget):
    """「－ 數值 ＋」：包住 QSpinBox（仍可直接輸入），取代樣式化後看不見的原生上下箭頭"""
    def __init__(self, spin, width: int = 150):
        super().__init__()
        from PySide6.QtWidgets import QAbstractSpinBox
        self.spin = spin
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setAlignment(Qt.AlignCenter)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        minus = QPushButton('－')
        plus = QPushButton('＋')
        for b, fn in ((minus, spin.stepDown), (plus, spin.stepUp)):
            b.setProperty('kind', 'ghost')
            b.setStyleSheet('QPushButton{padding:0;font-size:16px;}')     # 預設左右內距會把符號擠掉
            b.setFixedSize(34, 34)
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoRepeat(True)
            b.clicked.connect(fn)
        lay.addWidget(minus)
        lay.addWidget(spin, 1)
        lay.addWidget(plus)
        self.setFixedWidth(width)
