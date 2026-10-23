# -*- coding: utf-8 -*-
"""
參考小窗：速寫與臨摹研究共用（docs/UI_2.0_PLAN.md §7）
- 平常只有參考圖＋一行進度；滑鼠停留才浮出工具列與動作；點進度列展開步驟（研究）
- 穿透模式（半透明、點擊落到 SAI2）、按住快捷鍵比對 SAI2 畫布、縮成膠囊貼在寵物旁
- 打卡在小窗內側滑完成（自評、心得、畫布快照）
模式邏輯在 StudyMode / SketchMode，共用外框在 RefWindow。
"""

from __future__ import annotations

import os
import random
import threading
import webbrowser

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizeGrip, QVBoxLayout, QWidget)

from core import data_text as DT
from core import sketch_source as SK, study_lessons, study_refs, study_tools as ST
from core.daily_quests import PASS_RATING, QuestManager
from ui2 import theme, winutil
from ui2.icons import icon
from ui2.pet_window import to_pixmap

INFO_H = 30
OPACITY_STEPS = (1.0, 0.85, 0.7, 0.55)
GUIDE_COLOR = QColor(*ST.GUIDE_COLOR)
RATINGS = [(1, '還差很多'), (2, '有些抓到'), (3, '大致做到'), (4, '做得不錯'), (5, '非常接近')]


def _btn(text='', ic=None, tip='', primary=False, flat=True):
    b = QPushButton(text)
    if ic:
        b.setIcon(icon(ic, '#f2f1f6', 17))
        b.setIconSize(QSize(17, 17))
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    if primary:
        b.setProperty('primary', True)
    elif flat:
        b.setStyleSheet('QPushButton{background:transparent;border:none;border-radius:8px;padding:5px 8px;color:#f2f1f6;}'
                        'QPushButton:hover{background:#3b2f5c;}QPushButton:checked{background:#3b2f5c;color:#ddd6fe;}'
                        'QPushButton:disabled{color:#6b6979;}')
        if ic and not text:
            b.setFixedSize(28, 28)          # 只有圖示的按鈕固定大小，小窗才不會被工具列撐寬
    return b


# ─── 圖片區 ──────────────────────────────────────────────────────────────

class ImageView(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.pm = None
        self.compare = None
        self.guide = 'none'
        self.message = ''
        self._drag = None
        self.setMouseTracking(True)

    def image_rect(self) -> QRect:
        if self.pm is None:
            return self.rect()
        s = self.pm.size() / self.pm.devicePixelRatio()
        s.scale(self.size(), Qt.KeepAspectRatio)
        return QRect((self.width() - s.width()) // 2, (self.height() - s.height()) // 2, s.width(), s.height())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor('#15151b'))
        if self.pm is None:
            p.setPen(QColor('#a3a1b3'))
            p.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignCenter | Qt.TextWordWrap, self.message or '載入中…')
            return
        r = self.image_rect()
        p.drawPixmap(r, self.pm)
        if self.compare is not None:
            half = QRect(r.x() + r.width() // 2, r.y(), r.width() - r.width() // 2, r.height())
            src = self.compare.rect()
            p.drawPixmap(half, self.compare, QRect(src.width() // 2, 0, src.width() - src.width() // 2, src.height()))
            p.fillRect(QRect(half.x() - 1, r.y(), 2, r.height()), QColor('white'))
        if self.guide != 'none':
            p.setPen(QPen(GUIDE_COLOR, 1))
            for x1, y1, x2, y2 in ST.guide_lines(self.guide, r.width(), r.height()):
                p.drawLine(int(r.x() + x1), int(r.y() + y1), int(r.x() + x2), int(r.y() + y2))

    # 拖曳移動整個小窗
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.win.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        if self._drag is not None:
            self._drag = None
            self.win.save_geometry()

    def mouseDoubleClickEvent(self, _e):
        self.win.toggle_expand()


class InfoBar(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setFixedHeight(INFO_H)
        self.setCursor(Qt.PointingHandCursor)
        self.left = ''
        self.right = ''
        self.ratio = 0.0
        self.warn = False
        self.flash = False
        self.hint = ''                   # 滑過工具按鈕時的說明（優先顯示）
        self.setToolTip('點一下展開／收合步驟')

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#3b2f5c' if self.flash else '#15151b'))
        p.fillRect(QRect(0, 0, self.width(), 3), QColor('#2c2b35'))
        p.fillRect(QRect(0, 0, int(self.width() * max(0.0, min(1.0, self.ratio))), 3), QColor(theme.ACCENT))
        f = p.font()
        f.setPixelSize(12)
        p.setFont(f)
        if self.hint:
            p.setPen(QColor('#c4b5fd'))
            p.drawText(QRect(10, 3, self.width() - 20, INFO_H - 3), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(self.hint, Qt.ElideRight, self.width() - 20))
            return
        p.setPen(QColor('#fbbf6a' if self.warn else '#f2f1f6'))       # 資訊列固定深色底
        p.drawText(QRect(10, 3, self.width() - 80, INFO_H - 3), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(self.left, Qt.ElideRight, self.width() - 90))
        p.setPen(QColor('#c4b5fd'))
        p.drawText(QRect(self.width() - 80, 3, 70, INFO_H - 3), Qt.AlignVCenter | Qt.AlignRight, self.right)

    def mouseReleaseEvent(self, _e):
        self.win.toggle_expand()


class Capsule(QWidget):
    """縮小後貼在寵物旁的膠囊：階段名＋剩餘時間，點一下還原"""
    def __init__(self, win):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.win = win
        self.text = ''
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('點一下還原參考小窗')

    def set_text(self, text):
        self.text = text
        w = self.fontMetrics().horizontalAdvance(text) + 40
        self.resize(max(90, w), 36)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#15151b'))
        p.drawRoundedRect(QRectF(self.rect()), 18, 18)
        p.setBrush(QColor('#4ade80'))
        p.drawEllipse(QRectF(14, 14, 8, 8))
        p.setPen(QColor(theme.TEXT))
        p.drawText(self.rect().adjusted(30, 0, -12, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text)

    def mouseReleaseEvent(self, _e):
        self.win.restore_from_capsule()


# ─── 選項面板（小窗內的設定，取代彈出選單：彈出選單會被置頂的小窗蓋住）──────

class OptionsSheet(QFrame):
    def __init__(self, win):
        super().__init__(win)
        self.setObjectName('opts')
        self.setStyleSheet(f'QFrame#opts{{background:{theme.SURFACE};}}')
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(10)
        self.hide()

    def reset(self, title: str) -> QVBoxLayout:
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                _drop_layout(it.layout())
        head = QLabel(title)
        head.setProperty('h2', True)
        self.lay.addWidget(head)
        return self.lay


def _drop_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _drop_layout(it.layout())


# ─── 打卡側滑面板 ────────────────────────────────────────────────────────

class CheckinSheet(QFrame):
    finished = Signal(object, str)       # (rating 或 None, 心得)
    cancelled = Signal()

    def __init__(self, win):
        super().__init__(win)
        self.setObjectName('sheet')
        self.setStyleSheet(f'QFrame#sheet{{background:{theme.SURFACE};border-left:1px solid {theme.BORDER};}}')
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(10)
        self.rating = None
        self.hide()

    def open(self, task: dict, lesson: dict | None, snapshot_pm, self_report: bool):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                while it.layout().count():
                    w = it.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()
        self.rating = None
        head = QLabel(f'打卡：{task["name"]}')
        head.setProperty('h2', True)
        head.setWordWrap(True)
        self.lay.addWidget(head)
        if self_report:
            w = QLabel('尚未達標，這次是自行回報（例如在程式外完成）')
            w.setProperty('warn', True)
            w.setWordWrap(True)
            self.lay.addWidget(w)
        self.ok = QPushButton('完成打卡')
        self.ok.setProperty('primary', True)
        if lesson:
            focus = QLabel(f'本次專注：{lesson["focus"]}')
            focus.setWordWrap(True)
            focus.setStyleSheet(f'color:{theme.WARNING};')
            self.lay.addWidget(focus)
            for c in lesson['checks']:
                lb = QLabel(f'・{c}')
                lb.setWordWrap(True)
                lb.setProperty('muted', True)
                self.lay.addWidget(lb)
            row = QHBoxLayout()
            row.setSpacing(4)
            self._rbtns = []
            for v, label in RATINGS:
                b = QPushButton(f'{v}\n{label}')
                b.setCheckable(True)
                b.setMinimumHeight(48)
                b.setStyleSheet('QPushButton{font-size:11px;padding:4px 2px;}QPushButton:checked{background:#7c3aed;border:none;color:white;}')
                b.clicked.connect(lambda _=False, x=v: self._pick(x))
                row.addWidget(b)
                self._rbtns.append(b)
            self.lay.addLayout(row)
            hint = QLabel(f'{PASS_RATING} 分以上進入下一課；低於 {PASS_RATING} 分下次換一張圖再練。')
            hint.setProperty('muted', True)
            hint.setWordWrap(True)
            self.lay.addWidget(hint)
            self.ok.setEnabled(False)
        self.note = QLineEdit()
        self.note.setPlaceholderText('留一句心得（可留白）')
        self.lay.addWidget(self.note)
        if snapshot_pm is not None:
            snap = QLabel()
            snap.setPixmap(snapshot_pm.scaled(QSize(120, 90), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            cap = QLabel('畫布快照（會出現在成長頁的單日明細）')
            cap.setProperty('muted', True)
            cap.setWordWrap(True)
            row2 = QHBoxLayout()
            row2.addWidget(snap)
            row2.addWidget(cap, 1)
            self.lay.addLayout(row2)
        self.lay.addStretch(1)
        btns = QHBoxLayout()
        back = QPushButton('再練一下')
        back.clicked.connect(self.cancelled.emit)
        self.ok.clicked.connect(lambda: self.finished.emit(self.rating, self.note.text().strip()))
        btns.addWidget(back)
        btns.addWidget(self.ok, 1)
        self.lay.addLayout(btns)
        self.show()
        self.raise_()
        self.note.setFocus()

    def _pick(self, v):
        self.rating = v
        for i, b in enumerate(self._rbtns, 1):
            b.setChecked(i == v)
        self.ok.setEnabled(True)


# ─── 外框 ────────────────────────────────────────────────────────────────

class RefWindow(QWidget):
    closed = Signal(object)

    def __init__(self, ctl, mode: str):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(theme.QSS + 'QWidget{background:transparent;}')
        self.setWindowTitle('DrawCompanion 參考小窗')
        self.ctl = ctl
        self.kind = mode
        self.mode = None
        self.base = None                 # 原始參考圖（PIL）
        self.tools = {'flip': False, 'gray': False, 'value_levels': 0, 'guide': 'none', 'palette': False}
        self.click_through = False
        self.opacity_idx = 0
        self.expanded = False
        self._hold_vk = None
        self._normal_size = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.view = ImageView(self)
        self.info = InfoBar(self)
        from PySide6.QtWidgets import QScrollArea
        self.steps = QScrollArea(self)
        self.steps.setWidgetResizable(True)
        self.steps.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QFrame()
        inner.setObjectName('steps')
        inner.setStyleSheet(f'QFrame#steps{{background:{theme.SURFACE};}}')
        self.steps_lay = QVBoxLayout(inner)
        self.steps_lay.setContentsMargins(12, 10, 12, 12)
        self.steps_lay.setSpacing(6)
        self.steps.setWidget(inner)
        self.steps.hide()
        lay.addWidget(self.view, 1)
        lay.addWidget(self.info)
        lay.addWidget(self.steps)

        self.top = QFrame(self)
        self.top.setObjectName('ov')
        self.top.setStyleSheet('QFrame#ov{background:rgba(18,18,24,215);border-radius:10px;}')
        self.top_lay = QHBoxLayout(self.top)
        self.top_lay.setContentsMargins(4, 2, 4, 2)
        self.top_lay.setSpacing(1)
        self.bottom = QFrame(self)
        self.bottom.setObjectName('ov')
        self.bottom.setStyleSheet('QFrame#ov{background:rgba(18,18,24,215);border-radius:10px;}')
        self.bottom_lay = QHBoxLayout(self.bottom)
        self.bottom_lay.setContentsMargins(4, 2, 4, 2)
        self.bottom_lay.setSpacing(2)
        self.top.hide()
        self.bottom.hide()
        self.grip = QSizeGrip(self)
        self.grip.resize(14, 14)
        self.sheet = CheckinSheet(self)
        self.sheet.finished.connect(lambda r, n: self._checkin_done(*self._checkin_ctx, r, n))
        self.sheet.cancelled.connect(self._close_sheet)
        self._checkin_ctx = (None, False)
        self.options = OptionsSheet(self)
        self.capsule = Capsule(self)
        self._timer = QTimer(self, interval=1000, timeout=self._tick)
        self._flash = QTimer(self, singleShot=True, timeout=self._unflash)

    # ── 建構與工具 ──
    def set_mode(self, mode):
        self.mode = mode
        self._build_toolbar()
        self._build_actions()
        self._restore_geometry()
        self._fit_min_width()
        self._timer.start()
        self._tick()

    def _build_toolbar(self):
        self.tool_btns = {}
        spec = [('flip', 'flip', '水平翻轉（檢查比例與構圖）'), ('gray', 'gray', '灰階'),
                ('value_levels', 'value', '明度分階：原圖 → 3 階 → 5 階'), ('guide', 'grid', '構圖輔助線：三分法 → 格線 → 對角線')]
        for key, ic, tip in spec:
            b = _btn(ic=ic, tip=tip)
            self._hint_on_hover(b, tip)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self._toggle_tool(k))
            self.top_lay.addWidget(b)
            self.tool_btns[key] = b
        self.top_lay.addStretch(1)
        sep = QFrame()
        sep.setFixedSize(1, 18)
        sep.setStyleSheet('background:#4b4a5a;')
        self.top_lay.addWidget(sep)
        for ic, tip, fn in (('compare', '比對我的畫布（再按一次結束）', self.toggle_compare_sticky),
                            ('through', '穿透模式：點擊會落到 SAI2，用快捷鍵切回', lambda: self.set_click_through(True)),
                            ('opacity', '透明度：100% → 85% → 70% → 55%', self.cycle_opacity),
                            ('minimize', '縮成膠囊（研究繼續計時）', self.to_capsule),
                            ('close', '關閉', self.close)):
            b = _btn(ic=ic, tip=tip)
            b.clicked.connect(fn)
            self._hint_on_hover(b, tip)
            self.top_lay.addWidget(b)
        self._sync_tool_buttons()

    def _build_actions(self):
        while self.bottom_lay.count():
            w = self.bottom_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.action_btns = {}
        for ic, text, tip, fn, primary in self.mode.actions():
            b = _btn(text, ic=ic or None, tip=tip, primary=primary)
            b.clicked.connect(fn)
            self._hint_on_hover(b, tip)
            self.bottom_lay.addWidget(b)
            self.action_btns[ic or text] = b
        self.bottom_lay.insertStretch(max(0, self.bottom_lay.count() - 1), 1)

    def _hint_on_hover(self, btn, tip):
        """小窗不搶焦點時系統提示常不出現，改在下方資訊列顯示按鈕說明"""
        btn.setProperty('hint', tip)
        btn.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Enter and obj.property('hint'):
            self.info.hint = obj.property('hint')
            self.info.update()
        elif ev.type() == QEvent.Leave and obj.property('hint'):
            self.info.hint = ''
            self.info.update()
        return False

    def _fit_min_width(self):
        need = max(self.top.sizeHint().width(), self.bottom.sizeHint().width()) + 12
        self.setMinimumWidth(need)
        if self.width() < need:
            self.resize(need, self.height())

    def _toggle_tool(self, key):
        t = self.tools
        if key == 'value_levels':
            t[key] = ST.VALUE_STEPS[(ST.VALUE_STEPS.index(t[key]) + 1) % len(ST.VALUE_STEPS)]
        elif key == 'guide':
            keys = [k for k, _ in ST.GUIDES]
            t[key] = keys[(keys.index(t[key]) + 1) % len(keys)]
        else:
            t[key] = not t[key]
            if key == 'gray' and t[key]:
                t['value_levels'] = 0
        self._sync_tool_buttons()
        self._render()

    def _sync_tool_buttons(self):
        t = self.tools
        for key, b in self.tool_btns.items():
            b.setChecked(bool(t[key]) and t[key] != 'none')
        self.tool_btns['value_levels'].setToolTip(
            f"明度分階（目前：{'原圖' if not t['value_levels'] else str(t['value_levels']) + ' 階'}）")
        self.tool_btns['guide'].setToolTip(f"構圖輔助線（目前：{dict(ST.GUIDES)[t['guide']]}）")

    def set_image(self, img: Image.Image | None, message: str = ''):
        self.base = img
        self.view.message = message
        if img is not None and not self.expanded:
            self._fit_height(img.width, img.height)
        self._render()

    def _render(self):
        if self.base is None:
            self.view.pm = None
        else:
            img = ST.process(self.base, self.tools['flip'], self.tools['gray'], self.tools['value_levels'])
            self.view.pm = to_pixmap(img)
        self.view.guide = self.tools['guide']
        self.view.update()

    def _fit_height(self, iw, ih):
        w = self.width()
        h = int(w * ih / max(1, iw)) + INFO_H
        g = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        self.resize(w, min(h, int(g.height() * 0.8)))

    # ── 版面 ──
    def resizeEvent(self, _e):
        self.top.setGeometry(6, 6, self.width() - 12, 34)
        bh = 36
        self.bottom.setGeometry(6, self.view.height() - bh - 6, self.width() - 12, bh)
        self.grip.move(self.width() - 14, self.height() - 14)
        self.sheet.setGeometry(0, 0, self.width(), self.height())
        self.options.setGeometry(0, 0, self.width(), self.height())

    def enterEvent(self, _e):
        if not self.click_through and not self.sheet.isVisible() and not self.options.isVisible():
            self.top.show()
            self.bottom.show()
            self.top.raise_()
            self.bottom.raise_()

    def leaveEvent(self, _e):
        self.top.hide()
        self.bottom.hide()

    def _image_height(self) -> int:
        if self.base is None:
            return int(self.width() * 0.75)
        return int(self.width() * self.base.height / max(1, self.base.width))

    def toggle_expand(self):
        if self.mode is None or not self.mode.has_steps():
            return
        self.expanded = not self.expanded
        base_h = self._image_height() + INFO_H
        if self.expanded:
            self.mode.fill_steps(self.steps_lay)
            self.steps.widget().adjustSize()
            steps_h = min(self.steps.widget().sizeHint().height() + 4, 340)
            self.steps.setFixedHeight(steps_h)
            self.steps.show()
            self.resize(self.width(), base_h + steps_h)
        else:
            self.steps.hide()
            self.resize(self.width(), base_h)

    # ── 位置記憶 ──
    def _restore_geometry(self):
        cfg = self.ctl.settings.get(f'ref.{self.kind}', {}) or {}
        w = int(cfg.get('w') or 240)
        self.resize(w, int(w * 0.75) + INFO_H)
        g = QGuiApplication.primaryScreen().availableGeometry()
        x, y = cfg.get('x'), cfg.get('y')
        if x is None or not any(s.availableGeometry().contains(QPoint(int(x) + 20, int(y) + 20))
                                for s in QGuiApplication.screens()):
            x, y = g.right() - w - 40, g.top() + 40
        self.move(int(x), int(y))

    def save_geometry(self):
        self.ctl.settings.set(f'ref.{self.kind}', {'w': self.width(), 'x': self.x(), 'y': self.y()})
        self.ctl.settings.save()

    def showEvent(self, e):
        super().showEvent(e)
        winutil.set_round_corners(winutil.hwnd_of(self))
        winutil.set_frame_colors(winutil.hwnd_of(self), border=theme.ACCENT)

    # ── 穿透、透明度、膠囊 ──
    def set_click_through(self, on: bool):
        self.click_through = on
        self.top.hide()
        self.bottom.hide()
        winutil.set_click_through(winutil.hwnd_of(self), on)
        through = float(self.ctl.settings.get('ref.through_opacity', 0.5))
        self.setWindowOpacity(through if on else OPACITY_STEPS[self.opacity_idx])
        if on:
            keys = self.ctl.settings.get('hotkeys.click_through', '')
            self.ctl.say(f'穿透中：點擊會畫在 SAI2 上。按 {keys or "快捷鍵（設定中指定）"} 切回。', important=False, seconds=4)

    def toggle_click_through(self):
        self.set_click_through(not self.click_through)

    def cycle_opacity(self):
        self.opacity_idx = (self.opacity_idx + 1) % len(OPACITY_STEPS)
        if not self.click_through:
            self.setWindowOpacity(OPACITY_STEPS[self.opacity_idx])

    def to_capsule(self):
        self.save_geometry()
        self.hide()
        self._place_capsule()
        self.capsule.show()

    def _place_capsule(self):
        pet = self.ctl.pet
        a = pet.frameGeometry()
        g = (pet.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = a.left() - self.capsule.width() - 4
        if x < g.left():
            x = a.right() + 4
        self.capsule.move(x, a.center().y() - 18)

    def restore_from_capsule(self):
        self.capsule.hide()
        self.show()

    def is_shown(self) -> bool:
        return self.isVisible() or self.capsule.isVisible()

    def toggle_visible(self):
        if self.capsule.isVisible():
            self.restore_from_capsule()
        elif self.isVisible():
            self.to_capsule()
        else:
            self.show()

    # ── 比對 ──
    def _capture(self):
        from core.snapshots import capture_sai2_canvas
        try:
            return capture_sai2_canvas()
        except Exception:
            return None

    def toggle_compare_sticky(self):
        if self.view.compare is not None:
            self.end_compare()
            return
        self._start_compare()

    def _start_compare(self) -> bool:
        img = self._capture()
        if img is None:
            self.ctl.say('找不到 SAI2 畫布，請先在 SAI2 開啟畫布。')
            return False
        if self.tools['flip']:
            img = ST.process(img, flip=True)
        self.view.compare = to_pixmap(img)
        self.view.update()
        self.info.left, self.info.right = '左：參考　右：我的畫布', ''
        self.info.update()
        return True

    def begin_hold_compare(self, vk: int):
        if self.click_through or not self.isVisible():
            return
        if self._start_compare():
            self._hold_vk = vk
            self._hold = QTimer(self, interval=30, timeout=self._poll_hold)
            self._hold.start()

    def _poll_hold(self):
        if not winutil.key_down(self._hold_vk):
            self._hold.stop()
            self.end_compare()

    def end_compare(self):
        self.view.compare = None
        self.view.update()
        self._tick()

    # ── 打卡 ──
    def open_checkin(self, task: dict, lesson: dict | None, self_report: bool):
        snap = self._capture()
        self._checkin_snapshot = snap
        self._enlarge(340, 460)
        self.sheet.setGeometry(0, 0, self.width(), self.height())
        self._checkin_ctx = (task['uid'], self_report)
        self.sheet.open(task, lesson, to_pixmap(snap) if snap is not None else None, self_report)
        self.activateWindow()

    def _enlarge(self, min_w: int, min_h: int):
        """面板需要的空間比小窗大時暫時放大，關閉面板後還原"""
        if self._normal_size is None and (self.width() < min_w or self.height() < min_h):
            self._normal_size = self.size()
            self.resize(max(min_w, self.width()), max(min_h, self.height()))
        self.top.hide()
        self.bottom.hide()

    def open_options(self):
        self._enlarge(300, 330)
        self.options.setGeometry(0, 0, self.width(), self.height())
        self.options.show()
        self.options.raise_()
        self.activateWindow()

    def _close_sheet(self):
        self.sheet.hide()
        self.options.hide()
        if self._normal_size is not None:
            self.resize(self._normal_size)
            self._normal_size = None

    def _checkin_done(self, uid, self_report, rating, note):
        svc = self.ctl.service
        err = svc.check_in(uid, note, rating=rating, self_report=self_report)
        if err:
            self.ctl.say(err)
            return
        svc.save_checkin_snapshot(uid, getattr(self, '_checkin_snapshot', None))
        self._close_sheet()
        self.ctl.on_checked_in(uid)
        self.mode.after_checkin(uid)

    # ── 計時 ──
    def _tick(self):
        if self.mode is None:
            return
        left, right, ratio, warn = self.mode.info()
        if self.view.compare is None:
            self.info.left, self.info.right, self.info.ratio, self.info.warn = left, right, ratio, warn
            self.info.update()
        self.capsule.set_text(f'{left.split("（")[0]}　{right}'.strip())
        if self.capsule.isVisible():
            self._place_capsule()

    def flash_info(self):
        self.info.flash = True
        self.info.update()
        self._flash.start(1500)

    def _unflash(self):
        self.info.flash = False
        self.info.update()

    def heal_topmost(self):
        if self.isVisible():
            winutil.force_topmost(winutil.hwnd_of(self))
        if self.capsule.isVisible():
            winutil.force_topmost(winutil.hwnd_of(self.capsule))

    def closeEvent(self, e):
        self.save_geometry()
        self._timer.stop()
        self.capsule.hide()
        if self.mode is not None:
            self.mode.on_close()
        self.closed.emit(self)
        super().closeEvent(e)


def _section(lay, title, items, color=None):
    h = QLabel(title)
    h.setProperty('section', True)
    lay.addWidget(h)
    for text in items:
        lb = QLabel(text)
        lb.setWordWrap(True)
        if color:
            lb.setStyleSheet(f'color:{color};font-size:12px;')
        else:
            lb.setProperty('muted', True)
        lay.addWidget(lb)


# ─── 研究模式 ────────────────────────────────────────────────────────────

class StudyMode:
    def __init__(self, win: RefWindow, uid: str):
        self.win = win
        self.ctl = win.ctl
        self.q = self.ctl.service.quests
        self.uid = uid
        task = self.q.task(uid)
        self.lesson = study_lessons.lesson(task['params'].get('lesson_id', '')) if task else None
        win.tools.update(ST.default_tools(self.lesson))
        self.loading = False
        self.last_phase = None
        self.ref_meta = (task or {}).get('ref') or {}
        self.cache_dir = os.path.join(self.ctl.settings.app_dir, 'study_refs_cache')

    def task(self):
        return self.q.task(self.uid)

    def actions(self):
        return [('refresh', '', '換一張參考圖', self.next_reference, False),
                ('image', '', '自選圖檔當參考圖', self.choose_file, False),
                ('canvas', '', '練習畫布：建立同比例、依課程命名的 PSD 並在 SAI2 開啟（尺寸在設定）', self.canvas_action, False),
                ('link', '', '開啟參考圖出處', self.open_source, False),
                ('', '打卡', '完成打卡', self.checkin, True)]

    def start(self):
        if self.q.active_study != self.uid:
            self.q.start_study(self.uid)
            self.q.save(force=True)
        cache = self.ref_meta.get('cache')
        if cache and os.path.isfile(cache):
            try:
                with Image.open(cache) as im:
                    self.win.set_image(im.convert('RGB'))
                return
            except OSError:
                pass
        self.fetch()

    def fetch(self):
        if self.loading:
            return
        if not self.lesson:
            self.win.set_image(None, '這個任務沒有對應的課程，可以按「自選」用自己的圖')
            return
        self.loading = True
        self.win.set_image(None, '正在尋找參考圖…')
        exclude = self.q.seen_refs(self.lesson['id'])
        settings = self.ctl.settings.refs_settings()
        lesson = self.lesson

        def run():
            try:
                img, meta = study_refs.fetch_reference(lesson, settings, exclude, random.Random())
                self.ctl.work_done.emit(lambda: self._set_reference(img, meta))
            except Exception as e:
                self.ctl.work_done.emit(lambda err=str(e): self._fail(err))
        threading.Thread(target=run, daemon=True).start()

    def _fail(self, err):
        self.loading = False
        self.win.set_image(None, f'{err}\n\n可以按「自選」用自己的圖，或到設定填入圖庫 API 金鑰、本機圖庫。')

    def _set_reference(self, img, meta):
        self.loading = False
        if self.lesson:
            n = len(self.q.seen_refs(self.lesson['id']))
            try:
                meta['cache'] = study_refs.save_cache(img, self.cache_dir, f'{self.uid}_{n}')
            except OSError:
                pass
        self.q.set_task_ref(self.uid, meta)
        self.q.save(force=True)
        self.ref_meta = meta
        self.win.set_image(img.convert('RGB'))
        if self.win.expanded:
            self.fill_steps(self.win.steps_lay)

    def next_reference(self):
        self.fetch()

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(None, '選擇參考圖', '', '圖片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if not path:
            return
        try:
            img, meta = study_refs.load_local_file(path)
        except Exception as e:
            self.ctl.say(f'無法開啟圖片：{e}')
            return
        meta['why'] = self.lesson.get('look_for', '') if self.lesson else ''
        self._set_reference(img, meta)

    def open_source(self):
        url = self.ref_meta.get('url') or ''
        if url.startswith('http'):
            webbrowser.open(url)
        elif url and os.path.isfile(url):
            os.startfile(os.path.dirname(url))
        else:
            self.ctl.say('這張參考圖沒有出處連結。', important=False)

    def canvas_action(self):
        """這次已建立過練習畫布就直接開啟；沒有就依設定的尺寸建立（同比例、依課程命名）"""
        t = self.task() or {}
        if t.get('canvas') and os.path.isfile(t['canvas']):
            self.ctl.say(f'開啟這次的練習畫布：{os.path.basename(t["canvas"])}', important=False)
            self.ctl.open_path(t['canvas'])
            return
        self.create_canvas(int(self.ctl.settings.get('study.canvas_side', 2000)))

    def create_canvas(self, side: int):
        skill = self.q.skill(self.lesson['skill']) if self.lesson else None
        sname = skill['name'] if skill else None
        t = self.task() or {}
        folder = ST.canvas_dir(self.ctl.settings.get('study.canvas_dir', ''), sname)
        try:
            path, w, h = ST.create_canvas(folder, ST.canvas_stem(self.lesson, sname, t.get('name', '')),
                                          self.win.base.size if self.win.base is not None else None, side)
        except OSError as e:
            self.ctl.say(f'無法建立練習畫布：{e}')
            return
        if t:
            t['canvas'] = path
            self.q.mark_dirty()
            self.q.save(force=True)
        self.ctl.say(f'已建立 {w}×{h} 練習畫布，畫完記得 Ctrl+S 存回。', important=False)
        self.ctl.open_path(path)

    def checkin(self):
        t = self.task()
        if not t:
            return
        if t['status'] == 'done':
            self.ctl.say('這項任務已經打卡了。')
            return
        self.win.open_checkin(t, self.lesson, self_report=t['status'] != 'ready')

    def after_checkin(self, uid):
        self.win.close()

    # 步驟
    def has_steps(self):
        return True

    def fill_steps(self, lay):
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        les = self.lesson
        t = self.task() or {}
        if les:
            _section(lay, '學習重點', [les['focus']], theme.WARNING)
            idx, _left = ST.phase_at(les, t.get('progress', 0))
            items = []
            for i, ph in enumerate(les['phases']):
                mark = '✓' if i < (idx or 0) else ('▶' if i == idx else '○')
                items.append(f"{mark} {i + 1}. {ph['name']}（{ph['minutes']} 分）" + (f"\n　{ph['tip']}" if i == idx else ''))
            _section(lay, '分段步驟', items)
            _section(lay, '常見錯誤', les['mistakes'], theme.DANGER)
            _section(lay, '完成檢查', les['checks'])
        meta = self.ref_meta
        if meta:
            who = '，'.join(x for x in (meta.get('artist'), meta.get('date')) if x)
            src = ' · '.join(x for x in (meta.get('source'), meta.get('license')) if x)
            _section(lay, '參考圖', [x for x in (meta.get('title'), who, src) if x])

    # 狀態
    def info(self):
        t = self.task()
        if not t:
            return '任務已不存在', '', 0.0, True
        phase, tail = ST.phase_text(self.lesson, t['progress'])
        idx, _ = ST.phase_at(self.lesson, t['progress'])
        if self.last_phase is not None and idx is not None and idx != self.last_phase:
            ph = self.lesson['phases'][idx]
            self.ctl.say(f"進入「{ph['name']}」：{ph['tip']}", important=True, seconds=8)
            self.win.flash_info()
            if self.win.expanded:
                self.fill_steps(self.win.steps_lay)
        self.last_phase = idx
        st = self.ctl.last_status
        studying = self.q.active_study == self.uid
        if st is not None and st.unsaved_file and studying:
            return '畫布尚未存檔，動筆不會計時（按「畫布」建立練習畫布）', '', QuestManager.progress_ratio(t), True
        if t['status'] == 'ready':
            return f'{phase}（已達標，可以打卡）', f"{int(t['progress'] // 60)}/{t['target'] // 60} 分", 1.0, False
        if not studying:
            return f'{phase}（計時暫停）', f"{int(t['progress'] // 60)}/{t['target'] // 60} 分", QuestManager.progress_ratio(t), False
        return f'{phase}（{tail}）' if tail else phase, f"{int(t['progress'] // 60)}/{t['target'] // 60} 分", \
            QuestManager.progress_ratio(t), False

    def on_close(self):
        # 關閉參考小窗 = 結束這次研究，避免之後的一般繪圖被算進研究時間（縮成膠囊則繼續計時）
        if self.q.active_study == self.uid:
            self.q.stop_study()
            self.q.save(force=True)

    def next(self):
        pass

    def toggle_pause(self):
        if self.q.active_study == self.uid:
            self.q.stop_study()
        else:
            self.q.start_study(self.uid)
        self.q.save(force=True)
        self.win._tick()


# ─── 速寫模式 ────────────────────────────────────────────────────────────

class SketchMode:
    def __init__(self, win: RefWindow, uid: str | None):
        self.win = win
        self.ctl = win.ctl
        self.q = self.ctl.service.quests
        self.uid = uid
        self.opts = self.ctl.settings.sketch_opts()
        task = self.q.task(uid) if uid else None
        self.note = ''
        if task:
            res = SK.resolve_quest_topic(task['params'].get('topic', 'pose'), self.opts)
            self.note = res.pop('note')
            self.opts.update(res)
            self.opts['interval'] = int(task['params'].get('interval', self.opts.get('interval', 60)))
            self.topic = task['params'].get('topic', 'pose')
        else:
            self.topic = SK.topic_key(self.opts)
        self.session = SK.SketchSession(int(self.opts.get('interval', 60)))
        self.source = SK.SketchSource()
        win.tools['gray'] = bool(self.opts.get('grayscale'))
        self.loading = False
        self.status = ''
        self._retry = QTimer(win, singleShot=True, timeout=self.load_new)

    def actions(self):
        return [('prev', '', '上一張', self.back, False),
                ('pause', '', '暫停／繼續倒數', self.toggle_pause, False),
                ('next', '', '換下一張（提早換不計入張數）', self.next, False),
                ('settings', '', '設定：題目、間隔、圖源', self.settings_menu, False),
                ('', '結束', '結束這輪速寫', self.finish, True)]

    def start(self):
        if self.note:
            self.ctl.say(self.note, important=False)
        self.load_new()

    def load_new(self):
        if self.loading:
            return
        self.loading = True
        opts = dict(self.opts)
        if self.win.base is None:
            self.win.set_image(None, '正在抓圖…')

        def run():
            try:
                img, cap = self.source.next_image(opts)
                self.ctl.work_done.emit(lambda: self._loaded(img, cap))
            except SK.SketchError as e:
                self.ctl.work_done.emit(lambda err=e: self._failed(err))
            except Exception as e:
                self.ctl.work_done.emit(lambda err=SK.SketchError(str(e), SK.RETRY_SEC): self._failed(err))
        threading.Thread(target=run, daemon=True).start()

    def _loaded(self, img, cap):
        self.loading = False
        shown = self.session.push(img)
        self.status = cap
        self.win.set_image(shown)

    def _failed(self, err: SK.SketchError):
        self.loading = False
        if err.need_setup:
            msg = {'local_dir': '還沒有設定本機參考圖資料夾。', 'unsplash_key': '還沒有填 Unsplash 金鑰。',
                   'pexels_key': '還沒有填 Pexels 金鑰。'}.get(err.need_setup, str(err))
            self.ctl.say(msg + '設定一次之後就會記住。', actions=[('設定圖源', lambda: self.ctl.open_settings('參考圖來源'))])
            self.win.set_image(None, f'{err}\n\n到 設定 → 參考圖來源 設定本機資料夾或圖庫金鑰')
        elif err.retry_after and not self.session.paused:
            self.status = f'{err}（{err.retry_after} 秒後重試）'
            self._retry.start(err.retry_after * 1000)
            if self.win.base is None:
                self.win.set_image(None, self.status)
        else:
            self.status = str(err)
            if self.win.base is None:
                self.win.set_image(None, str(err))

    def _record(self, seconds):
        ready = self.ctl.service.record_sketch(self.topic, seconds, self.uid, self.session.interval or None)
        self.ctl.on_ready(ready)

    def tick(self):
        if self.session.tick(1.0):
            self._record(self.session.interval)
            self.next(auto=True)

    def next(self, auto=False):
        """換下一張：歷史裡有下一張就直接顯示，否則抓新圖。手動換頁只有不限時模式可能計入一張"""
        if self.session.can_forward():
            counted = self.session.forward()
            if counted and not auto:
                self._record(counted)
            self.win.set_image(self.session.current)
            return
        if not auto:
            counted = self.session.forward()
            if counted:
                self._record(counted)
        self.load_new()

    def back(self):
        if self.session.back():
            self.win.set_image(self.session.current)

    def toggle_pause(self):
        self.session.paused = not self.session.paused
        b = self.win.action_btns.get('pause')
        if b is not None:
            b.setIcon(icon('play' if self.session.paused else 'pause', '#f2f1f6', 17))
        self.win._tick()

    def settings_menu(self):
        """在小窗內展開速寫設定（題目、間隔、圖源、灰階），按「套用」才生效"""
        lay = self.win.options.reset('速寫設定')
        src = QComboBox()
        for k, label in SK.SOURCES:
            src.addItem(label, k)
        src.setCurrentIndex(max(0, src.findData(self.opts.get('source', 'local'))))
        topic = QComboBox()
        interval = QComboBox()
        for label, secs in SK.INTERVALS:
            interval.addItem(label, secs)
        interval.setCurrentIndex(max(0, interval.findData(self.session.interval)))
        gray = QCheckBox('灰階顯示')
        gray.setChecked(bool(self.win.tools['gray']))
        warn = QLabel()
        warn.setWordWrap(True)
        warn.setProperty('warn', True)

        def fill_topics():
            topic.clear()
            if src.currentData() == 'local':
                topic.addItem('全部', '')
                for sub in SK.local_subdirs(self.opts.get('local_dir', '')):
                    topic.addItem(sub, sub)
                topic.setCurrentIndex(max(0, topic.findData(self.opts.get('local_category', ''))))
                missing = not self.opts.get('local_dir')
                warn.setText('還沒有設定本機參考圖資料夾' if missing else '')
            else:
                for k, label, _q in SK.CATEGORIES:
                    if k != 'custom':
                        topic.addItem(label, k)
                topic.setCurrentIndex(max(0, topic.findData(self.opts.get('category', 'pose'))))
                missing = not self.opts.get(f'{src.currentData()}_key')
                warn.setText(f'還沒有填 {src.currentText()} 金鑰' if missing else '')
            warn.setVisible(bool(warn.text()))
        fill_topics()
        src.currentIndexChanged.connect(lambda *_: fill_topics())
        form = QGridLayout()
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)
        for r, (label, w) in enumerate((('圖源', src), ('題目', topic), ('間隔', interval))):
            lb = QLabel(label)
            lb.setProperty('muted', True)
            form.addWidget(lb, r, 0)
            form.addWidget(w, r, 1)
        lay.addLayout(form)
        lay.addWidget(gray)
        lay.addWidget(warn)
        if self.uid:
            note = QLabel('改了題目或間隔，之後的張數就不算進目前的任務。')
            note.setWordWrap(True)
            note.setProperty('muted', True)
            lay.addWidget(note)
        lay.addStretch(1)
        link = QPushButton('圖源設定…')
        link.clicked.connect(lambda: (self.win._close_sheet(), self.ctl.open_settings('參考圖來源')))
        lay.addWidget(link)
        btns = QHBoxLayout()
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.win._close_sheet)
        ok = QPushButton('套用')
        ok.setProperty('primary', True)

        def apply():
            changes = {}
            if src.currentData() != self.opts.get('source'):
                changes['source'] = src.currentData()
            key = 'local_category' if src.currentData() == 'local' else 'category'
            if (topic.currentData() or '') != (self.opts.get(key) or ''):
                changes[key] = topic.currentData() or ''
            if interval.currentData() != self.session.interval:
                changes['interval'] = interval.currentData()
            if gray.isChecked() != bool(self.win.tools['gray']):
                self.win.tools['gray'] = gray.isChecked()
                if gray.isChecked():
                    self.win.tools['value_levels'] = 0
                self.ctl.settings.set('sketch.grayscale', gray.isChecked())
                self.ctl.settings.save()
                self.win._sync_tool_buttons()
                self.win._render()
            self.win._close_sheet()
            if changes:
                self._change(**changes)
        ok.clicked.connect(apply)
        btns.addWidget(cancel)
        btns.addWidget(ok, 1)
        lay.addLayout(btns)
        self.win.open_options()

    def _change(self, **kw):
        """改了題目 / 間隔 / 圖源：之後的張數不再計入原本的任務（與 1.x 規則相同），並記住設定"""
        self.opts.update(kw)
        for k, v in kw.items():
            self.ctl.settings.set(f'sketch.{k}', v)
        self.ctl.settings.save()
        if self.uid:
            self.uid = None
            self.ctl.say('已改變題目或間隔，之後的張數不計入原本的任務。', important=False)
        self.topic = SK.topic_key(self.opts)
        if 'interval' in kw:
            self.session.interval = int(kw['interval'])
            self.session.restart()
        if set(kw) - {'interval'}:
            self.load_new()

    def finish(self):
        t = self.q.task(self.uid) if self.uid else None
        if t and t['status'] == 'ready':
            self.win.open_checkin(t, None, self_report=False)
        else:
            self.win.close()

    def after_checkin(self, uid):
        self.win.close()

    def has_steps(self):
        return False

    def fill_steps(self, lay):
        pass

    def info(self):
        s = self.session
        t = self.q.task(self.uid) if self.uid else None
        left = f"{DT.task_name(t)}　{QuestManager.progress_text(t)}" if t else f'本輪 {s.completed} 張'
        if t and t['status'] == 'ready':
            left += '　已達標'
        if s.paused:
            left += '（暫停）'
        if self.status and self.win.base is None:
            left = self.status
        if s.interval <= 0:
            return left, '不限時', 0.0, False
        right = f'{int(s.remaining)} 秒' if s.current is not None else ''
        return left, right, (s.remaining / s.interval) if s.current is not None else 0.0, False

    def on_close(self):
        self._retry.stop()
