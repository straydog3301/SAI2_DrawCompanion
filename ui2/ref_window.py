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
import time
import webbrowser

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizeGrip, QVBoxLayout, QWidget)

from core import data_text as DT
from core import sketch_source as SK, study_lessons, study_refs, study_tools as ST
from core.daily_quests import PASS_RATING, QuestManager
from ui2 import theme, winutil
from ui2.icons import icon
from ui2.pet_window import to_pixmap
from ui2.widgets import set_clipboard

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
        self._pan_drag = None
        self.zoomable = False            # 參照模式：滾輪縮放、拖曳平移、雙擊回到整張
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.picking = False             # 吸色：點一下取得顏色
        self.on_pick = None
        self._pick_img = None
        self.setMouseTracking(True)

    def image_rect(self) -> QRect:
        if self.pm is None:
            return self.rect()
        s = self.pm.size() / self.pm.devicePixelRatio()
        s.scale(self.size(), Qt.KeepAspectRatio)
        w, h = s.width() * self.zoom, s.height() * self.zoom
        cx, cy = self.width() / 2 + self.pan.x(), self.height() / 2 + self.pan.y()
        return QRect(int(cx - w / 2), int(cy - h / 2), int(w), int(h))

    def reset_zoom(self):
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.update()

    def _clamp_pan(self):
        r = self.image_rect()
        mx, my = max(0.0, (r.width() - self.width()) / 2), max(0.0, (r.height() - self.height()) / 2)
        self.pan = QPointF(max(-mx, min(mx, self.pan.x())), max(-my, min(my, self.pan.y())))

    def wheelEvent(self, e):
        if not self.zoomable or self.pm is None:
            return super().wheelEvent(e)
        steps = e.angleDelta().y() / 120
        z0 = self.zoom
        z1 = max(1.0, min(16.0, z0 * (1.25 ** steps)))
        if z1 == 1.0:
            self.reset_zoom()
        else:
            c = QPointF(self.width() / 2, self.height() / 2)
            cur = e.position()
            self.pan = cur - c - (cur - c - self.pan) * (z1 / z0)       # 游標下的那一點縮放後還在游標下
            self.zoom = z1
            self._clamp_pan()
        self.update()
        self.win.info.update()

    def pick_color(self, pos) -> QColor | None:
        """畫面上的一點 → 圖片的顏色（看到的樣子：含灰階、分階）"""
        if self.pm is None:
            return None
        r = self.image_rect()
        if not r.contains(pos):
            return None
        if self._pick_img is None or self._pick_img[0] is not self.pm:
            self._pick_img = (self.pm, self.pm.toImage())
        img = self._pick_img[1]
        x = int((pos.x() - r.x()) / max(1, r.width()) * img.width())
        y = int((pos.y() - r.y()) / max(1, r.height()) * img.height())
        return img.pixelColor(min(img.width() - 1, max(0, x)), min(img.height() - 1, max(0, y)))

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

    # 拖曳移動整個小窗（參照模式放大時改成平移圖片；吸色時點一下取色）
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.picking:
            color = self.pick_color(e.position().toPoint())
            if color is not None and self.on_pick:
                self.on_pick(color)
            return
        if self.zoomable and self.zoom > 1.0:
            self._pan_drag = (e.position(), QPointF(self.pan))
            return
        self._drag = e.globalPosition().toPoint() - self.win.pos()

    def mouseMoveEvent(self, e):
        if self._pan_drag is not None and e.buttons() & Qt.LeftButton:
            start, pan0 = self._pan_drag
            self.pan = pan0 + (e.position() - start)
            self._clamp_pan()
            self.update()
        elif self._drag is not None and e.buttons() & Qt.LeftButton:
            self.win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._pan_drag = None
        if self._drag is not None:
            self._drag = None
            self.win.save_geometry()

    def mouseDoubleClickEvent(self, _e):
        if self.zoomable:
            self.reset_zoom()
            self.win.info.update()
        else:
            self.win.toggle_expand()


class InfoBar(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setFixedHeight(theme.size(INFO_H))
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
        f.setPixelSize(theme.px(12))
        p.setFont(f)
        if self.hint:
            p.setPen(QColor('#c4b5fd'))
            p.drawText(QRect(10, 3, self.width() - 20, self.height() - 3), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(self.hint, Qt.ElideRight, self.width() - 20))
            return
        p.setPen(QColor('#fbbf6a' if self.warn else '#f2f1f6'))       # 資訊列固定深色底
        p.drawText(QRect(10, 3, self.width() - 80, self.height() - 3), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(self.left, Qt.ElideRight, self.width() - 90))
        p.setPen(QColor('#c4b5fd'))
        p.drawText(QRect(self.width() - 80, 3, 70, self.height() - 3), Qt.AlignVCenter | Qt.AlignRight, self.right)

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
    finished = Signal(object, str, object)   # (rating 或 None, 心得, AI 評鑑結果或 None)
    cancelled = Signal()
    review_requested = Signal(str)           # 請 AI 評鑑（心得）

    def __init__(self, win):
        super().__init__(win)
        self.setObjectName('sheet')
        self.setStyleSheet(f'QFrame#sheet{{background:{theme.SURFACE};border-left:1px solid {theme.BORDER};}}')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(10)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.rating = None
        self.ai_result = None
        self.ai_mode = False
        self._rbtns = []
        self.hide()

    def open(self, task: dict, lesson: dict | None, snapshot_pm, self_report: bool, ai: bool = False):
        _clear_layout(self.lay)
        self.rating = None
        self.ai_result = None
        self.ai_mode = bool(ai and lesson)
        self._rbtns = []
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
        self.rating_box = QWidget()
        rl = QVBoxLayout(self.rating_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
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
            # AI 評鑑的結果（等待中／分數與簡評／錯誤）
            self.ai_box = QVBoxLayout()
            self.ai_box.setSpacing(6)
            self.lay.addLayout(self.ai_box)
            self.rating_title = QLabel('你覺得這次做到了嗎？')
            self.rating_title.setProperty('muted', True)
            rl.addWidget(self.rating_title)
            row = QHBoxLayout()
            row.setSpacing(4)
            for v, label in RATINGS:
                b = QPushButton(f'{v}\n{label}')
                b.setCheckable(True)
                b.setMinimumHeight(48)
                b.setStyleSheet(theme.scale_css('QPushButton{font-size:11px;padding:4px 2px;}QPushButton:checked{background:#7c3aed;border:none;color:white;}'))
                b.clicked.connect(lambda _=False, x=v: self._pick(x))
                row.addWidget(b)
                self._rbtns.append(b)
            rl.addLayout(row)
            self.hint = QLabel(f'{PASS_RATING} 分以上進入下一課；低於 {PASS_RATING} 分下次換一張圖再練。')
            self.hint.setProperty('muted', True)
            self.hint.setWordWrap(True)
            rl.addWidget(self.hint)
            self.lay.addWidget(self.rating_box)
            if self.ai_mode:
                self.rating_box.hide()
                self.ok.setText('完成打卡並請 AI 評分')
            else:
                self.ok.setEnabled(False)
        self.note = QLineEdit()
        self.note.setPlaceholderText('留一句心得（可留白）')
        self.lay.addWidget(self.note)
        if snapshot_pm is not None:
            snap = QLabel()
            snap.setPixmap(snapshot_pm.scaled(QSize(120, 90), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            cap = QLabel('畫布快照（會出現在成長頁的單日明細）' + ('，也會交給 AI 評分' if self.ai_mode else ''))
            cap.setProperty('muted', True)
            cap.setWordWrap(True)
            row2 = QHBoxLayout()
            row2.addWidget(snap)
            row2.addWidget(cap, 1)
            self.lay.addLayout(row2)
        self.lay.addStretch(1)
        btns = QHBoxLayout()
        self.back = QPushButton('再練一下')
        self.back.clicked.connect(self.cancelled.emit)
        self.ok.clicked.connect(self._ok)
        btns.addWidget(self.back)
        btns.addWidget(self.ok, 1)
        self.lay.addLayout(btns)
        self.show()
        self.raise_()
        self.note.setFocus()

    def _ok(self):
        if self.ai_mode and self.ai_result is None and self.rating is None:
            self.review_requested.emit(self.note.text().strip())
            return
        self.finished.emit(self.rating, self.note.text().strip(), self.ai_result)

    def _pick(self, v):
        self.rating = v
        for i, b in enumerate(self._rbtns, 1):
            b.setChecked(i == v)
        self.ok.setEnabled(True)
        if self.ai_result is not None:
            same = v == self.ai_result['score']
            self.hint.setText(self._pass_text(v) + ('' if same else '（你改了 AI 的分數，紀錄會標示為手動修改）'))

    @staticmethod
    def _pass_text(score: int) -> str:
        return (f'{score} 分：達到 {PASS_RATING} 分，下次進入下一課。' if score >= PASS_RATING
                else f'{score} 分：未達 {PASS_RATING} 分，下次換一張圖再練這一課。')

    # ── AI 評鑑 ──
    def show_waiting(self):
        _clear_layout(self.ai_box)
        lb = QLabel('AI 評鑑中…通常 5～20 秒')
        lb.setStyleSheet(f'color:{theme.ACCENT_TEXT};font-weight:600;')
        self.ai_box.addWidget(lb)
        self.ok.setEnabled(False)
        self.note.setEnabled(False)
        self.back.setText('改用自評')
        try:
            self.back.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.back.clicked.connect(self.use_self_rating)

    def _restore_back(self):
        self.back.setText('再練一下')
        try:
            self.back.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.back.clicked.connect(self.cancelled.emit)
        self.note.setEnabled(True)

    def use_self_rating(self, message: str = ''):
        """不等 AI（或 AI 失敗）：改用自評"""
        self.ai_mode = False
        self.ai_result = None
        _clear_layout(self.ai_box)
        if message:
            lb = QLabel(message)
            lb.setProperty('warn', True)
            lb.setWordWrap(True)
            self.ai_box.addWidget(lb)
        self._restore_back()
        self.rating_title.setText('這次改用自評：你覺得做到了嗎？')
        self.rating_box.show()
        self.ok.setText('完成打卡')
        self.ok.setEnabled(self.rating is not None)

    def show_result(self, res: dict):
        self.ai_result = res
        _clear_layout(self.ai_box)
        score = QLabel(f"AI 評分　{res['score']} 分・{dict(RATINGS).get(res['score'], '')}")
        score.setStyleSheet(theme.scale_css(f'font-size:15px;font-weight:700;color:{theme.ACCENT_TEXT};'))
        self.ai_box.addWidget(score)
        if res.get('summary'):
            s = QLabel(res['summary'])
            s.setWordWrap(True)
            self.ai_box.addWidget(s)
        for title, key in (('做得好', 'strengths'), ('可以改進', 'improve')):
            if res.get(key):
                lb = QLabel(f'{title}：' + ''.join(f'\n・{x}' for x in res[key]))
                lb.setWordWrap(True)
                lb.setProperty('muted', True)
                self.ai_box.addWidget(lb)
        self._restore_back()
        self.rating_title.setText('不同意的話可以改分數：')
        self.rating_box.show()
        self._pick(res['score'])
        self.ok.setText('完成打卡')


def _clear_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().hide()                 # 馬上消失；deleteLater 要等下一輪事件才刪除
            it.widget().deleteLater()
        elif it.layout():
            _clear_layout(it.layout())


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
        self.sheet.finished.connect(lambda r, n, ai: self._checkin_done(*self._checkin_ctx, r, n, ai))
        self.sheet.review_requested.connect(self._request_review)
        self._review_seq = 0
        self.sheet.cancelled.connect(self._close_sheet)
        self._checkin_ctx = (None, False)
        self.options = OptionsSheet(self)
        self.capsule = Capsule(self)
        self._timer = QTimer(self, interval=1000, timeout=self._tick)
        self._flash = QTimer(self, singleShot=True, timeout=self._unflash)
        self.setAcceptDrops(True)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence.Paste, self, activated=lambda: getattr(self.mode, 'paste', None) and self.mode.paste())

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if hasattr(self.mode, 'drop') and (md.hasImage() or md.hasUrls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        if hasattr(self.mode, 'drop'):
            self.mode.drop(e.mimeData())
            e.acceptProposedAction()

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
        ai = bool(lesson) and self.ctl.service.ai_review_ready()
        self._enlarge(340, 560 if ai else 460)
        self.sheet.setGeometry(0, 0, self.width(), self.height())
        self._checkin_ctx = (task['uid'], self_report)
        self._checkin_task, self._checkin_lesson = task, lesson
        self.sheet.open(task, lesson, to_pixmap(snap) if snap is not None else None, self_report, ai=ai)
        self.activateWindow()

    def _request_review(self, note: str):
        """打卡時請 AI 評分（背景執行緒）；按「改用自評」或關閉面板後回來的結果會被忽略"""
        self._review_seq += 1
        seq = self._review_seq
        task, lesson, snap = self._checkin_task, self._checkin_lesson, getattr(self, '_checkin_snapshot', None)
        self.sheet.show_waiting()

        def work():
            from core.ai_review import ReviewError
            try:
                res, err = self.ctl.service.review_checkin(task, lesson, snap, note), None
            except ReviewError as e:
                res, err = None, str(e)
            except Exception as e:                      # 不讓評鑑的意外錯誤卡住打卡
                res, err = None, f'AI 評鑑失敗：{e}'
            self.ctl.work_done.emit(lambda: self._review_done(seq, res, err))
        threading.Thread(target=work, daemon=True).start()

    def _review_done(self, seq, res, err):
        if seq != self._review_seq or not self.sheet.isVisible() or not self.sheet.ai_mode:
            return
        if res is None:
            self.sheet.use_self_rating(f'{err}。這次改用自評。')
        else:
            self.sheet.show_result(res)

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
        self._review_seq += 1
        self.sheet.hide()
        self.options.hide()
        if self._normal_size is not None:
            self.resize(self._normal_size)
            self._normal_size = None

    def _checkin_done(self, uid, self_report, rating, note, ai=None):
        svc = self.ctl.service
        self._review_seq += 1                            # 之後才回來的評鑑結果不再使用
        err = svc.check_in(uid, note, rating=rating, self_report=self_report, ai_review=ai)
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
        tick = getattr(self.mode, 'tick', None)       # 速寫的倒數由這裡每秒推進（研究的進度看實際動筆，由服務計算）
        if tick is not None:
            tick()
            if self.mode is None:                     # 倒數結束後可能已關閉
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
            lb.setStyleSheet(theme.scale_css(f'color:{color};font-size:12px;'))
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
        self._token = 0                     # 每次抓圖的編號：逾時或改設定後，舊的結果直接丟掉
        self._prefetched = None             # 預先抓好的下一張 (圖, 說明)：倒數結束時馬上換，不用等網路
        self._prefetching = False
        self._await_prefetch = False        # 預先抓的還沒好就按了下一張：等它好了直接顯示
        self.load_error = ''                # 上一次抓圖失敗的原因（畫面上已有圖時也要讓使用者看到）
        self._watchdog = QTimer(win, singleShot=True, timeout=self._load_timeout)
        self.count_mode = self.opts.get('count_mode', 'draw')     # draw：下筆才倒數；clock：一直倒數
        self._counter = None                # 上一次讀到的累計動筆秒數
        self.drawing = False
        self.canvas_path = None             # 這一輪的速寫畫布（一輪一張）

    def actions(self):
        return [('prev', '', '上一張', self.back, False),
                ('pause', '', '暫停／繼續倒數', self.toggle_pause, False),
                ('next', '', '換下一張（提早換不計入張數）', self.next, False),
                ('canvas', '', '速寫畫布：在 SAI2 開啟這一輪的畫布（沒有就建立；尺寸在設定）', self.open_canvas, False),
                ('settings', '', '設定：題目、間隔、圖源', self.settings_menu, False),
                ('', '結束', '結束這輪速寫', self.finish, True)]

    def start(self):
        if self.note:
            self.ctl.say(self.note, important=False)
        self.load_new()
        if self.opts.get('auto_canvas', True):
            self.open_canvas()

    # ── 速寫畫布：一輪一張 ──
    def _topic_label(self) -> str:
        if self.opts.get('source') == 'local':
            return self.opts.get('local_category') or '本機圖庫'
        return next((label for k, label, _q in SK.CATEGORIES if k == self.opts.get('category')), '速寫')

    def open_canvas(self):
        if self.canvas_path and os.path.isfile(self.canvas_path):
            self.ctl.open_path(self.canvas_path)
            return
        t = self.q.task(self.uid) if self.uid else None
        name = DT.task_name(t) if t else self._topic_label()
        folder = ST.canvas_dir(self.ctl.settings.get('study.canvas_dir', ''), '速寫')
        stem = ST.safe_filename(f"速寫_{name or '練習'}_{time.strftime('%Y%m%d_%H%M')}")
        size = ST.sketch_canvas_size(self.opts)
        try:
            path, w, h = ST.create_canvas(folder, stem, None, max(size), size=size)
        except OSError as e:
            self.ctl.say(f'無法建立速寫畫布：{e}')
            return
        self.canvas_path = path
        msg = f'已建立 {w}×{h} 速寫畫布，這一輪都畫在這張上。'
        if self.count_mode == 'draw':
            msg += '在畫布上下筆時才會倒數。'
        self.ctl.say(msg, important=False)
        self.ctl.open_path(path)

    LOAD_TIMEOUT_MS = 30000

    def _fetch(self, token, on_done):
        """背景抓一張；結果交回主執行緒（token 不符代表已逾時或改了設定，結果丟掉）"""
        opts = dict(self.opts)

        def run():
            try:
                img, cap = self.source.next_image(opts)
                self.ctl.work_done.emit(lambda: on_done(token, (img, cap), None))
            except SK.SketchError as e:
                self.ctl.work_done.emit(lambda err=e: on_done(token, None, err))
            except Exception as e:                  # noqa: BLE001 - 解碼、網路等各種錯誤都要回報，不能卡住
                from core import diagnostics
                diagnostics.write(self.ctl.settings.app_dir, f'sketch image failed: {type(e).__name__}', str(e))
                self.ctl.work_done.emit(lambda err=SK.SketchError(f'{type(e).__name__}：{e}', SK.RETRY_SEC):
                                        on_done(token, None, err))
        threading.Thread(target=run, daemon=True, name='sketch-fetch').start()

    def load_new(self):
        """換到新的一張：有預先抓好的就馬上用，否則現在抓（期間畫面顯示「載入下一張」）"""
        if self.loading:
            return
        if self._prefetched is not None:
            img, cap = self._prefetched
            self._prefetched = None
            self._show(img, cap)
            return
        self.loading = True
        self._watchdog.start(self.LOAD_TIMEOUT_MS)
        if self.win.base is None:
            self.win.set_image(None, '正在抓圖…')
        self.win._tick()
        if self._prefetching:                       # 已經在抓下一張了，不要再同時抓一張
            self._await_prefetch = True
            return
        self._token += 1
        self._fetch(self._token, self._fetched)

    def _fetched(self, token, result, err):
        if token != self._token or not self.loading:
            return
        self._watchdog.stop()
        self.loading = False
        if err is not None:
            self._failed(err)
        else:
            self._show(*result)

    def _load_timeout(self):
        if not self.loading:
            return
        self._token += 1                            # 之後才回來的結果不用了
        self.loading = False
        self._await_prefetch = False
        self._failed(SK.SketchError('網路太慢，抓圖逾時', SK.RETRY_SEC))

    def _show(self, img, cap):
        shown = self.session.push(img)
        self.status = cap
        self.load_error = ''
        self.win.set_image(shown)
        self.win._tick()
        self._prefetch()

    def _prefetch(self):
        """畫這張的同時先抓好下一張"""
        if self._prefetching or self._prefetched is not None:
            return
        self._prefetching = True
        token = self._token

        def done(tok, result, err):
            self._prefetching = False
            if tok != self._token:
                return
            if self._await_prefetch:                # 使用者正在等這一張
                self._await_prefetch = False
                self._fetched(tok, result, err)
            elif result is not None:
                self._prefetched = result
        self._fetch(token, done)

    def _failed(self, err: SK.SketchError):
        self.loading = False
        self.load_error = str(err)
        if self.win.base is not None and not err.need_setup:
            hint = f'{err.retry_after} 秒後自動重試，也可以按「下一張」' if err.retry_after else '按「下一張」再試一次'
            self.ctl.say(f'下一張參考圖載入失敗：{err}。{hint}。', important=False, seconds=8)
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

    def _elapsed(self) -> float:
        """這一秒要推進幾秒：一直倒數 = 1；下筆才倒數 = 這段期間 SAI2 的動筆秒數（1.x 執行中時退回一直倒數）"""
        if self.count_mode != 'draw':
            return 1.0
        c = self.ctl.service.draw_counter()
        if c is None:
            return 1.0
        last, self._counter = self._counter, c
        return 0.0 if last is None or c < last else min(c - last, 3.0)

    def tick(self):
        dt = self._elapsed()
        self.drawing = dt > 0
        if self.session.tick(dt):
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
        by_draw = QCheckBox('下筆時才倒數（停筆、看參考圖時暫停）')
        by_draw.setChecked(self.count_mode == 'draw')
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
        lay.addWidget(by_draw)
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
            mode = 'draw' if by_draw.isChecked() else 'clock'
            if mode != self.count_mode:
                self.count_mode = mode
                self._counter = None
                self.opts['count_mode'] = mode
                self.ctl.settings.set('sketch.count_mode', mode)
                self.ctl.settings.save()
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
        if set(kw) - {'interval'}:                  # 換了題目或圖源：預先抓的那張不能用了
            self._token += 1
            self._prefetched = None
            self._await_prefetch = False
            self._watchdog.stop()
            self.loading = False
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
        elif self.count_mode == 'draw' and not self.drawing and s.current is not None \
                and self.ctl.service.draw_counter() is not None:
            left += '　下筆開始倒數'
        if self.loading and self.win.base is not None:
            left = '載入下一張…'
        elif self.load_error and self.win.base is not None:
            left = f'下一張載入失敗：{self.load_error}'
        if self.status and self.win.base is None:
            left = self.status
        if s.interval <= 0:
            return left, '不限時', 0.0, False
        right = f'{int(s.remaining)} 秒' if s.current is not None else ''
        return left, right, (s.remaining / s.interval) if s.current is not None else 0.0, False

    def on_close(self):
        self._retry.stop()
        self._watchdog.stop()
        self._token += 1


# ─── 參照：自己放一張圖 ──────────────────────────────────────────────────

REF_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff', '.psd')
REF_MAX_SIDE = 4096                       # 太大的圖縮小後保存（夠放大看細節，切換檢查工具也不會卡）


class ReferenceMode:
    """不在課程中也能用的參考圖：開啟檔案、貼上剪貼簿、拖曳進來；一次一張，關掉後記住。
    可以縮放平移、吸色（點一下複製色碼），檢查工具、穿透、按住比對與速寫和研究相同"""
    uid = None

    def __init__(self, win: RefWindow, uid=None):
        self.win = win
        self.ctl = win.ctl
        self.folder = os.path.join(self.ctl.settings.app_dir, 'reference')
        self.path = os.path.join(self.folder, 'current.png')
        self.name = self.ctl.settings.get('ref.reference_name', '') or ''
        self.copied = ''                  # 剛吸到、已複製的色碼
        self._copied_at = 0.0
        win.view.zoomable = True
        win.view.on_pick = self._picked

    def actions(self):
        return [('file', '', '開啟圖片', self.open_file, False),
                ('paste', '', '貼上剪貼簿的圖片（Ctrl+V），也可以直接把圖片拖進來', self.paste, False),
                ('eyedrop', '', '吸色：點圖片上的顏色，色碼會複製到剪貼簿', self.toggle_pick, False),
                ('trash', '', '清除這張參照圖', self.clear, False)]

    def start(self):
        btn = self.win.action_btns.get('eyedrop')
        if btn is not None:
            btn.setCheckable(True)
        img = None
        if os.path.isfile(self.path):
            try:
                with Image.open(self.path) as im:
                    img = im.copy()
            except OSError:
                img = None
        self._show(img)

    def _show(self, img):
        self.win.view.reset_zoom()
        self.win.set_image(img, '按「開啟」或 Ctrl+V 貼上圖片，也可以把圖片拖進這裡')
        self.win._tick()

    def use(self, img: Image.Image, name: str):
        """換成這張圖（存一份，下次打開還在）"""
        img = img.convert('RGBA') if img.mode in ('RGBA', 'LA', 'P') else img.convert('RGB')
        if max(img.size) > REF_MAX_SIDE:
            img.thumbnail((REF_MAX_SIDE, REF_MAX_SIDE), Image.LANCZOS)
        try:
            os.makedirs(self.folder, exist_ok=True)
            img.save(self.path, format='PNG')
        except OSError as e:
            self.ctl.say(f'無法保存參照圖：{e}')
        self.name = name
        self.ctl.settings.set('ref.reference_name', name)
        self.ctl.settings.save()
        self._show(img)

    def _load_file(self, path: str) -> bool:
        try:
            with Image.open(path) as im:
                im.seek(0)
                img = im.copy()
        except (OSError, ValueError, EOFError):
            self.ctl.say(f'無法開啟「{os.path.basename(path)}」，請換一張圖片。')
            return False
        self.use(img, os.path.basename(path))
        return True

    def open_file(self):
        exts = ' '.join('*' + e for e in REF_EXTS)
        path, _ = QFileDialog.getOpenFileName(self.win, '選擇參照圖', '', f'圖片 ({exts})')
        if path:
            self._load_file(path)

    def _from_mime(self, md) -> bool:
        """剪貼簿或拖曳的內容：圖片檔（從檔案總管複製）或圖片本身（截圖、從瀏覽器複製）"""
        for url in (md.urls() if md.hasUrls() else []):
            local = url.toLocalFile()
            if local and local.lower().endswith(REF_EXTS) and os.path.isfile(local):
                return self._load_file(local)
        if md.hasImage():
            qimg = md.imageData()
            if qimg is not None and not qimg.isNull():
                self.use(_qimage_to_pil(qimg), '貼上的圖片')
                return True
        return False

    def paste(self):
        if not self._from_mime(QGuiApplication.clipboard().mimeData()):
            self.ctl.say('剪貼簿裡沒有圖片。可以先截圖或複製一張圖片，再按貼上。', important=False)

    def drop(self, md):
        if not self._from_mime(md):
            self.ctl.say('只能放入圖片檔。', important=False)

    def toggle_pick(self):
        v = self.win.view
        v.picking = not v.picking
        v.setCursor(Qt.CrossCursor if v.picking else Qt.ArrowCursor)
        btn = self.win.action_btns.get('eyedrop')
        if btn is not None:
            btn.setChecked(v.picking)

    def _picked(self, color):
        code = color.name().upper()
        set_clipboard(text=code)
        self.copied, self._copied_at = code, time.monotonic()
        self.win.flash_info()
        self.win._tick()

    def clear(self):
        try:
            os.remove(self.path)
        except OSError:
            pass
        self.name = ''
        self.ctl.settings.set('ref.reference_name', '')
        self.ctl.settings.save()
        self._show(None)

    def info(self):
        if self.copied and time.monotonic() - self._copied_at < 6:
            left = f'已複製色碼 {self.copied}'
        elif self.win.view.picking:
            left = '吸色：點圖片上的顏色'
        else:
            left = self.name or '開啟、貼上或拖入一張圖片'
        z = self.win.view.zoom
        return left, (f'{int(round(z * 100))}%' if z > 1.0 else ''), 0.0, False

    def has_steps(self):
        return False

    def fill_steps(self, lay):
        pass

    def after_checkin(self, uid):
        pass

    def on_close(self):
        pass


def _qimage_to_pil(qimg) -> Image.Image:
    from PySide6.QtCore import QBuffer, QIODevice
    import io
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    qimg.save(buf, 'PNG')
    return Image.open(io.BytesIO(bytes(buf.data()))).copy()
