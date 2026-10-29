# -*- coding: utf-8 -*-
"""
點寵物出現的快捷面板：今日進度、每日任務、最近開啟、快捷按鈕。
打卡、回報次數都在面板內完成（行內展開），不跳系統對話框。點面板外面或按 Esc 收起。
"""

from __future__ import annotations

import os
import time
from datetime import datetime

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QPushButton, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from core import data_text as DT
from core import onboarding, slots
from core.daily_quests import QuestManager
from ui2 import theme
from ui2.icons import icon
from ui2.widgets import ProgressBar, Stepper, load_pixmap, rounded_thumb

PANEL_W = 380
RECENT_COLS = 4               # 最近開啟：每列幾格縮圖
RECENT_GAP = 6
RECENT_W = (PANEL_W - 36 - RECENT_GAP * (RECENT_COLS - 1)) // RECENT_COLS
RECENT_H = RECENT_W * 3 // 4
SHADOW = 18



def _label(text, **props):
    lb = QLabel(text)
    for k, v in props.items():
        lb.setProperty(k, v)
    return lb


def _rel_time(iso: str) -> str:
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return ''
    d = (datetime.now().date() - t.date()).days
    if d <= 0:
        return t.strftime('%H:%M')
    return '昨天' if d == 1 else f'{d} 天前'


class PracticeCard(QFrame):
    """第一次打開面板時的「30 秒調整你的練習」（§16）：每天想練多久、想加強什麼，可略過"""

    def __init__(self, ctl, done):
        super().__init__()
        from ui2.widgets import Segmented
        self.ctl = ctl
        self._done = done
        q = ctl.service.quests
        self.setObjectName('practiceCard')
        self.setStyleSheet(f'QFrame#practiceCard{{background:{theme.SURFACE2};border:1px solid {theme.ACCENT};'
                           f'border-radius:14px;}}')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(_label('30 秒調整你的練習', h2=True))
        tip = _label('決定每天排多少任務；之後隨時可以在設定改', muted=True)
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addWidget(_label('每天想練多久', section=True))
        cur = onboarding._nearest(float(q.settings.get('budget_minutes', 60)))
        self.minutes = Segmented([(str(m), f'{m} 分') for m in onboarding.PRACTICE_MINUTES], str(cur))
        self.minutes.setAccessibleName('每天想練多久')
        lay.addWidget(self.minutes)
        lay.addWidget(_label('想加強什麼', section=True))
        self.focus = QComboBox()
        self.focus.setAccessibleName('想加強的技能')
        for sid, name in onboarding.focus_choices(q):
            self.focus.addItem(name, sid)
        self.focus.setCurrentIndex(max(0, self.focus.findData(q.settings.get('weekly_focus', ''))))
        lay.addWidget(self.focus)
        row = QHBoxLayout()
        row.addStretch(1)
        skip = QPushButton('略過')
        skip.setProperty('kind', 'ghost')
        skip.setCursor(Qt.PointingHandCursor)
        skip.clicked.connect(lambda: self._done(False, False))
        ok = QPushButton('套用')
        ok.setProperty('kind', 'primary')
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self._apply)
        row.addWidget(skip)
        row.addWidget(ok)
        lay.addLayout(row)

    def _apply(self):
        q = self.ctl.service.quests
        regen = onboarding.apply_practice(q, int(self.minutes.value), self.focus.currentData() or '')
        self._done(True, regen)


class ProgressRing(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(56, 56)
        self.ratio = 0.0
        self.text = ''

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(4, 4, 48, 48)
        p.setPen(QPen(QColor(theme.BORDER), 6))
        p.drawEllipse(r)
        p.setPen(QPen(QColor(theme.ACCENT), 6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 90 * 16, -int(360 * 16 * max(0.0, min(1.0, self.ratio))))
        p.setPen(QColor(theme.TEXT))
        f = p.font()
        f.setPixelSize(theme.px(13))
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, self.text)


class QuickPanel(QWidget):
    def __init__(self, ctl):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.ctl = ctl                       # CompanionApp：提供服務與動作
        self.quest_list = None
        self.hidden_at = 0.0          # 點面板外面（例如點寵物）會先自動收起，記下時間避免馬上又被打開
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        self.card = QFrame()
        self.card.setObjectName('card')
        self.card.setStyleSheet(f'QFrame#card{{background:{theme.SURFACE};border:1px solid {theme.BORDER};border-radius:18px;}}')
        self.card.setFixedWidth(theme.size(PANEL_W))
        fx = QGraphicsDropShadowEffect(self.card)
        fx.setBlurRadius(36)
        fx.setOffset(0, 10)
        fx.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(fx)
        outer.addWidget(self.card)
        self.card_lay = QVBoxLayout(self.card)
        self.card_lay.setContentsMargins(0, 0, 0, 0)
        self.content = None
        self.body = None

    # ── 建構 ──
    def _clear(self):
        """每次重繪換一個新的內容元件，舊的整個丟掉（逐一拆版面容易殘留子元件）"""
        if self.content is not None:
            self.content.hide()
            self.content.setParent(None)
            self.content.deleteLater()
        self.content = QWidget()
        self.content.setObjectName('content')
        self.content.setStyleSheet('QWidget#content{background:transparent;}')     # 有選擇器才不會蓋掉子元件樣式
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(18, 18, 18, 14)
        self.body.setSpacing(14)
        self.card_lay.addWidget(self.content)

    def refresh(self):
        # 每次重繪都重設外框顏色，換主題後才會跟著變
        self.card.setStyleSheet(f'QFrame#card{{background:{theme.SURFACE};border:1px solid {theme.BORDER};border-radius:18px;}}')
        self._clear()
        svc = self.ctl.service
        st = self.ctl.last_status
        blocks = slots.normalize_blocks(self.ctl.settings.get('panel.blocks', []))
        self.quest_list = None
        if svc.paused:
            warn = _label('偵測到 1.x 正在執行，2.0 暫停記錄（避免重複計時）。關閉 1.x 後會自動繼續。', warn=True)
            warn.setWordWrap(True)
            self.body.addWidget(warn)
        elif onboarding.show_practice_card(self.ctl.settings, svc.quests):
            self.body.addWidget(PracticeCard(self.ctl, self._practice_done))
        for block in blocks:                  # 依設定的順序排列
            if block == 'progress':
                self.body.addLayout(self._header(st))
            elif block == 'quests' and svc.quests is not None and svc.quests.settings.get('enabled', True):
                self.quest_list = QuestList(self.ctl)
                self.quest_list.changed.connect(self._relayout)
                self.quest_list.request_hide.connect(self.hide)
                self.body.addWidget(self.quest_list)
            elif block == 'recent':
                self.body.addLayout(self._recent())
            elif block == 'slots':
                self.body.addLayout(self._slots())
        self.body.addWidget(self._footer())
        self.card.adjustSize()
        self.adjustSize()

    def _practice_done(self, applied: bool, regenerated: bool):
        s = self.ctl.settings
        s.mark_prompted(onboarding.KEY_PRACTICE)
        s.save()
        if applied:
            self.ctl.say('好，今天的任務已經照你的選擇排好了。' if regenerated
                         else '記下了，明天起的任務會照你的選擇排。', important=False)
        else:
            self.ctl.say('之後想調整，可以到 設定 → 每日任務。', important=False)
        self.refresh()

    def _header(self, st):
        row = QHBoxLayout()
        row.setSpacing(14)
        ring = ProgressRing()
        done_min = int(st.today_draw // 60)
        ring.ratio = st.today_draw / 60 / max(1.0, st.budget_minutes)
        ring.text = f'{done_min}′'
        row.addWidget(ring)
        col = QVBoxLayout()
        col.setSpacing(2)
        hour = datetime.now().hour
        hello = '早安' if hour < 11 else ('午安' if hour < 18 else '晚安')
        col.addWidget(_label(f'{hello}，今天 {done_min} / {int(st.budget_minutes)} 分', h2=True))
        sub = f'連續 {st.streak} 天' + ('　今天請假' if st.rest_day else '')
        if st.sai2_running and st.current_file:
            sub += f'　正在畫：{st.current_file.split(" _ ")[-1]}'
        elif st.sai2_running and getattr(st, 'excluded_file', None):
            sub += f'　{st.excluded_file.split(" _ ")[-1]}（不記錄的資料夾）'
        elif not st.sai2_running and st.tracking:
            sub += '　SAI2 未開啟'
        if st.recording:
            sub += '　● 錄影中' if st.rec_file else '　錄影待命'
        s = _label(sub, muted=True)
        s.setWordWrap(True)
        col.addWidget(s)
        row.addLayout(col, 1)
        return row

    def _section(self, title, link_text='', link_fn=None):
        row = QHBoxLayout()
        row.addWidget(_label(title, section=True))
        row.addStretch(1)
        if link_text:
            b = QPushButton(link_text)
            b.setProperty('flat', True)
            b.setStyleSheet(theme.scale_css(f'color:{theme.ACCENT_TEXT};padding:2px 6px;font-size:12px;'))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(link_fn)
            row.addWidget(b)
        return row

    def _recent(self):
        lay = QVBoxLayout()
        lay.setSpacing(8)
        lay.addLayout(self._section('最近開啟'))
        rows = self.ctl.service.recent_files(int(self.ctl.settings.get('panel.recent_count', 4)))
        if not rows:
            lay.addWidget(_label('還沒有紀錄。在 SAI2 開檔畫圖後會出現在這裡。', muted=True))
            return lay
        grid = QGridLayout()
        grid.setSpacing(RECENT_GAP)
        for i, r in enumerate(rows):
            grid.addWidget(self._recent_tile(r), i // RECENT_COLS, i % RECENT_COLS)
        lay.addLayout(grid)
        return lay

    def _recent_tile(self, r) -> QPushButton:
        """作品縮圖格（名稱與時間放在提示文字）；還沒有縮圖的作品顯示圖示與簡短檔名"""
        b = QPushButton()
        b.setObjectName('recentTile')
        b.setFixedSize(RECENT_W, RECENT_H)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(f'{r["name"]}　{_rel_time(r["last_seen"])}\n點一下在 SAI2 開啟')
        b.setAccessibleName(f'在 SAI2 開啟 {r["name"]}')
        b.setStyleSheet(theme.scale_css(f'QPushButton#recentTile{{background:{theme.SURFACE2};border:none;border-radius:10px;padding:0;'
                        f'font-size:11px;color:{theme.MUTED};}}'
                        f'QPushButton#recentTile:hover{{border:2px solid {theme.ACCENT_BORDER};}}'))
        pm = load_pixmap(self.ctl.service.thumb_of(r['key']))
        if pm is not None:
            b.setIcon(QIcon(rounded_thumb(pm, RECENT_W, RECENT_H, 10, b.devicePixelRatioF() or 1.0)))
            b.setIconSize(QSize(RECENT_W, RECENT_H))
        else:
            stem = os.path.splitext(r['name'])[0]
            b.setText(stem if len(stem) <= 6 else stem[:5] + '…')
            b.setIcon(icon('file', theme.ACCENT_TEXT))
            b.setIconSize(QSize(18, 18))
        b.clicked.connect(lambda _=False, k=r['key']: (self.hide(), self.ctl.open_recent(k)))
        return b

    def _slots(self):
        lay = QVBoxLayout()
        lay.setSpacing(8)
        lay.addLayout(self._section('快捷'))
        row = QHBoxLayout()
        row.setSpacing(6)
        for key in slots.normalize_slots(self.ctl.settings.get('panel.slots', [])):
            if key is None:
                continue
            name, ic, tip = slots.describe(key)
            b = QToolButton()
            b.setText(name)
            b.setProperty('slot', True)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)      # 圖示在上、文字在下，窄按鈕也不擠
            on = key == 'record' and bool(self.ctl.settings.get('timelapse.enabled'))
            b.setIcon(icon(ic, theme.DANGER if on else theme.ICON))
            if on:
                b.setText('錄影中')
            b.setIconSize(QSize(20, 20))
            b.setFixedHeight(theme.size(60))
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: (self.hide(), self.ctl.run_slot(k)))
            row.addWidget(b)
        lay.addLayout(row)
        return lay

    def _footer(self):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 4, 0, 0)
        for text, ic, fn, enabled, tip in (
                ('控制中心', 'home', self.ctl.open_control_center, True, ''),
                ('設定', 'settings', self.ctl.open_settings, True, ''),
                ('隱藏 30 分', 'hide', self.ctl.hide_for_a_while, True, '')):
            b = QPushButton(text)
            b.setProperty('flat', True)
            b.setIcon(icon(ic, theme.NAV_TEXT, 16))
            b.setEnabled(enabled)
            b.setToolTip(tip)
            if fn:
                b.clicked.connect(lambda _=False, f=fn: (self.hide(), f()))
            row.addWidget(b, 1)
        return w

    # ── 動作 ──
    def place(self):
        pet = self.ctl.pet
        a = pet.frameGeometry()
        g = (pet.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        w, h = self.width(), self.height()
        x = a.right() - w + SHADOW
        if x < g.left():
            x = a.left() - SHADOW
        y = a.top() - h + SHADOW // 2                       # 優先開在寵物上方
        if y < g.top():
            y = a.bottom() - SHADOW // 2
        self.move(max(g.left() - SHADOW, min(x, g.right() - w + SHADOW)),
                  max(g.top() - SHADOW, min(y, g.bottom() - h + SHADOW)))

    def _relayout(self):
        if self.isVisible():
            QTimer.singleShot(0, lambda: (self.card.adjustSize(), self.adjustSize(), self.place()))

    def hideEvent(self, e):
        self.hidden_at = time.monotonic()
        super().hideEvent(e)

    def popup(self):
        self.refresh()
        self.place()
        self.show()
        self.activateWindow()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)


class QuestList(QWidget):
    """今日任務清單：開始 / 繼續 / 打卡 / 回報次數 / 換任務，打卡與回報在清單內展開（快捷面板與控制中心共用）"""
    changed = Signal()            # 內容高度改變（外層要重新排版）
    request_hide = Signal()       # 開了參考小窗，外層的彈出面板可以收起

    def __init__(self, ctl, show_section: bool = True):
        super().__init__()
        self.ctl = ctl
        self.show_section = show_section
        self._inline = None
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._box = None
        self.refresh()

    def refresh(self):
        if self._box is not None:
            self._box.hide()
            self._box.setParent(None)
            self._box.deleteLater()
        self._box = QWidget()
        self._box.setObjectName('ql')
        self._box.setStyleSheet('QWidget#ql{background:transparent;}')
        self._lay = QVBoxLayout(self._box)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(6)
        self._build()
        self._outer.addWidget(self._box)
        self.changed.emit()

    def _section(self, title, link_text='', link_fn=None):
        row = QHBoxLayout()
        row.addWidget(_label(title, section=True))
        row.addStretch(1)
        if link_text:
            b = QPushButton(link_text)
            b.setProperty('flat', True)
            b.setStyleSheet(theme.scale_css(f'color:{theme.ACCENT_TEXT};padding:2px 6px;font-size:12px;'))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(link_fn)
            row.addWidget(b)
        return row

    def _build(self):
        lay = self._lay
        lay.setSpacing(6)
        svc = self.ctl.service
        left = svc.quests.rerolls_left() if svc.quests else 0
        if self.show_section:
            lay.addLayout(self._section('每日任務', f'換一個（剩 {left}）' if left else '', self._reroll_menu))
        tasks = [t for t in svc.today_tasks() if t['status'] != 'expired']
        if not tasks:
            lay.addWidget(_label('今天沒有任務，好好休息！', muted=True))
        for t in tasks:
            lay.addWidget(self._quest_row(t))
            if self._inline and self._inline[0] == t['uid']:
                lay.addWidget(self._inline_editor(t))

    MODE_ICONS = {'sketch': 'sketch', 'study': 'study', 'drill': 'refresh', 'thumbnail': 'grid', 'draw_time': 'open_sai2'}

    def _quest_row(self, t):
        w = QFrame()
        w.setObjectName('qrow')
        doing = t['status'] in ('active', 'ready') and (t['progress'] > 0 or self.ctl.service.quests.active_study == t['uid'])
        done = t['status'] == 'done'
        w.setStyleSheet(f'QFrame#qrow{{background:{theme.ACCENT_SOFT if doing else theme.SURFACE2};border-radius:14px;}}')
        row = QHBoxLayout(w)
        row.setContentsMargins(10, 10, 8, 10)
        row.setSpacing(12)
        tile = QLabel()
        tile.setFixedSize(36, 36)
        tile.setAlignment(Qt.AlignCenter)
        color = theme.SUCCESS if done else (theme.ACCENT_TEXT if doing or t['status'] == 'ready' else theme.MUTED)
        tile.setPixmap(icon(self.MODE_ICONS.get(t['mode'], 'check') if not done else 'check', color, 18).pixmap(18, 18))
        tile.setStyleSheet(f'background:{theme.OK_SOFT if done else theme.SURFACE3};border-radius:10px;')
        row.addWidget(tile)
        col = QVBoxLayout()
        col.setSpacing(4)
        name = _label(DT.task_name(t))
        name.setWordWrap(True)                     # 長的課程名稱、放大文字或較長的語言時換行，不被截斷
        name.setStyleSheet(theme.scale_css('font-size:13px;font-weight:600;' if not done else f'font-size:13px;color:{theme.MUTED};'))
        col.addWidget(name)
        line = QHBoxLayout()
        line.setSpacing(8)
        bar = ProgressBar(QuestManager.progress_ratio(t), theme.SUCCESS if done else theme.ACCENT, 4)
        bar.setMinimumWidth(theme.size(60))
        line.addWidget(bar, 1)
        prog = _label(QuestManager.progress_text(t), muted=True)
        line.addWidget(prog)
        col.addLayout(line)
        row.addLayout(col, 1)
        if done:
            row.addWidget(_label('已打卡', ok=True))
            row.addSpacing(6)
        else:
            if t['status'] == 'ready':
                b = QPushButton('打卡')
                b.setProperty('primary', True)
                b.clicked.connect(lambda _=False, u=t['uid']: self._open_inline(u, 'checkin'))
            else:
                b = QPushButton('繼續' if doing else '開始')
                if doing:
                    b.setProperty('primary', True)
                b.clicked.connect(lambda _=False, u=t['uid']: self._go(u))
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(theme.size(34))
            b.setMinimumWidth(theme.size(64))
            row.addWidget(b)
            more = QPushButton()
            more.setIcon(icon('more'))
            more.setProperty('flat', True)
            more.setFixedSize(theme.size(30), theme.size(34))
            more.setToolTip('更多')
            more.clicked.connect(lambda _=False, tt=t, bb=more: self._more_menu(tt, bb))
            row.addWidget(more)
        return w

    def _inline_editor(self, t):
        uid, kind = self._inline
        w = QFrame()
        w.setStyleSheet(f'QFrame{{background:{theme.SURFACE3};border-radius:12px;}}')
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        if kind == 'count':
            row = QHBoxLayout()
            unit = '張' if t['mode'] == 'thumbnail' else '個'
            row.addWidget(_label(f'這次完成了幾{unit}？'))
            spin = QSpinBox()
            spin.setRange(1, 999)
            spin.setValue(max(1, t['target'] - int(t['progress'])))
            row.addWidget(Stepper(spin, 130))
            ok = QPushButton('記錄')
            ok.setProperty('primary', True)
            ok.clicked.connect(lambda: self._commit_count(uid, spin.value()))
            row.addWidget(ok)
            lay.addLayout(row)
        else:
            self._rating = None
            lesson = t['mode'] == 'study' and t['params'].get('lesson_id')
            if lesson:
                lay.addWidget(_label('對照完成檢查，替自己打分（3 分以上進入下一課）'))
                stars = QHBoxLayout()
                self._star_btns = []
                for n in range(1, 6):
                    b = QPushButton(str(n))
                    b.setFixedSize(theme.size(44), theme.size(36))
                    b.setCheckable(True)
                    b.clicked.connect(lambda _=False, v=n: self._pick_rating(v))
                    self._star_btns.append(b)
                    stars.addWidget(b)
                lay.addLayout(stars)
            note = QLineEdit()
            note.setPlaceholderText('留一句心得（可留白）')
            lay.addWidget(note)
            row = QHBoxLayout()
            if t['status'] != 'ready':
                row.addWidget(_label('尚未達標：這次是自行回報', warn=True))
            row.addStretch(1)
            cancel = QPushButton('取消')
            cancel.setProperty('flat', True)
            cancel.clicked.connect(lambda: self._open_inline(None, None))
            ok = QPushButton('完成打卡')
            ok.setProperty('primary', True)
            ok.clicked.connect(lambda: self._commit_checkin(uid, note.text(), bool(lesson), t['status'] != 'ready'))
            row.addWidget(cancel)
            row.addWidget(ok)
            lay.addLayout(row)
            self._checkin_ok = ok
            if lesson:
                ok.setEnabled(False)
        return w

    def _go(self, uid):
        action, msg = self.ctl.service.go(uid)
        if action == 'need_count':
            self._open_inline(uid, 'count')
            return
        if action in ('open_study', 'open_sketch'):
            self.request_hide.emit()
            self.ctl.open_ref('study' if action == 'open_study' else 'sketch', uid)
            self.ctl.say(msg, important=False)
            return
        self.ctl.say(msg, important=action != 'started')
        if action == 'started':
            self.ctl.focus_sai2()
        self.refresh()

    def _open_inline(self, uid, kind):
        self._inline = (uid, kind) if uid else None
        self.refresh()

    def _commit_count(self, uid, n):
        ready = self.ctl.service.add_count(uid, n)
        self._inline = None
        self.ctl.on_ready(ready)
        self.refresh()

    def _pick_rating(self, v):
        self._rating = v
        for i, b in enumerate(self._star_btns, 1):
            b.setChecked(i <= v)
            b.setProperty('primary', i <= v)
            b.style().unpolish(b)
            b.style().polish(b)
        self._checkin_ok.setEnabled(True)

    def _commit_checkin(self, uid, note, need_rating, self_report):
        err = self.ctl.service.check_in(uid, note, rating=self._rating if need_rating else None, self_report=self_report)
        self._inline = None
        if err:
            self.ctl.say(err)
        else:
            self.ctl.on_checked_in(uid)
        self.refresh()

    def _more_menu(self, t, btn):
        m = QMenu(self)
        q = self.ctl.service.quests
        a = m.addAction('換成別的任務')
        a.setEnabled(q.rerolls_left() > 0 and t['progress'] == 0)
        a.triggered.connect(lambda: self._reroll(t['uid']))
        b = m.addAction('自行回報打卡（在程式外完成）')
        b.triggered.connect(lambda: self._open_inline(t['uid'], 'checkin'))
        if q.active_study == t['uid']:
            c = m.addAction('停止研究計時')
            c.triggered.connect(lambda: (q.stop_study(), q.save(force=True), self.refresh()))
        m.exec(btn.mapToGlobal(QPoint(0, btn.height())))

    def _reroll_menu(self):
        tasks = [t for t in self.ctl.service.today_tasks() if t['status'] == 'active' and t['progress'] == 0]
        m = QMenu(self)
        for t in tasks:
            m.addAction(DT.task_name(t)).triggered.connect(lambda _=False, u=t['uid']: self._reroll(u))
        if not tasks:
            m.addAction('沒有可以換的任務（已開始的不能換）').setEnabled(False)
        m.exec(self.cursor().pos())

    def _reroll(self, uid):
        new = self.ctl.service.reroll(uid)
        if not new:
            self.ctl.say('沒有其他可以換的任務了')
        self.refresh()
