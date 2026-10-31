# -*- coding: utf-8 -*-
"""主視窗的成長、課程、作品、工具頁（階段三）"""

from __future__ import annotations

import os
import subprocess
import threading
from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from core import data_text as DT
from core import exclusions, growth, stats, study_lessons, works
from core.daily_quests import QuestManager
from ui2 import theme
from ui2.charts import BarChart, MonthGrid, Sparkline
from ui2.icons import icon
from ui2.widgets import (Card, Chip, PageHeader, ProgressBar, Segmented, SettingGroup, StatTile, ToggleSwitch, button,
                         label, load_pixmap, rounded_thumb)

STATUS_CHIP = {'done': ('已打卡', 'ok'), 'ready': ('已達標', 'accent'), 'active': ('進行中', 'neutral'),
               'expired': ('未完成', 'warn')}


def _clear(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            w = it.widget()
            w.hide()
            w.setParent(None)        # 立刻脫離畫面，不必等 deleteLater
            w.deleteLater()
        elif it.layout():
            _clear(it.layout())


def _thumb(path: str, size: int = 96) -> QLabel:
    lb = QLabel()
    pm = QPixmap(path)
    if not pm.isNull():
        lb.setPixmap(pm.scaled(QSize(size, size), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lb.setCursor(Qt.PointingHandCursor)
        lb.setToolTip('開啟圖片')
        lb.mouseReleaseEvent = lambda _e, p=path: os.startfile(p)
    return lb


class ClickFrame(QFrame):
    """可點擊的整列（QPushButton 不會依內部版面撐高，列表的列改用這個）"""
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


# ─── 成長 ────────────────────────────────────────────────────────────────

class GrowthPage(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.q = ctl.service.quests
        now = datetime.now()
        self.year, self.month = now.year, now.month
        self.selected = self.q.day_key() if self.q else ''
        self.period = 'month'
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        q = self.q
        lay.addWidget(PageHeader('成長', '每天的投入都會累積在這裡'))
        if q is None:
            return
        cards = growth.skill_cards(q)
        recent = sum(c['recent_seconds'] for c in cards)
        cal = growth.month_calendar(q, self.year, self.month)
        tiles = QHBoxLayout()
        tiles.setSpacing(16)
        tiles.addWidget(StatTile('連續天數', f'{q.streak()} 天', '請假不會中斷', 'flame'))
        tiles.addWidget(StatTile('最長紀錄', f'{q.longest_streak()} 天', '目前為止', 'check'))
        tiles.addWidget(StatTile('本月打卡', f"{cal['done_days']} 天", f"請假 {cal['rest_days']} 天", 'grid'))
        tiles.addWidget(StatTile('近 30 天練習', growth.fmt_hours(recent), '各技能合計', 'study'))
        lay.addLayout(tiles)

        row = QHBoxLayout()
        row.setSpacing(16)
        cal_card = Card('練習月曆', '顏色越深，當天打卡的任務越多；點日期看明細')
        nav = QHBoxLayout()
        self.month_label = label('', 'h2', wrap=False)
        prev = button('', 'ghost', ic='prev', tip='上個月')
        nxt = button('', 'ghost', ic='next', tip='下個月')
        prev.clicked.connect(lambda: self._shift(-1))
        nxt.clicked.connect(lambda: self._shift(1))
        nav.addWidget(prev)
        nav.addWidget(self.month_label)
        nav.addWidget(nxt)
        nav.addStretch(1)
        cal_card.lay.addLayout(nav)
        self.grid = MonthGrid()
        self.grid.picked.connect(self._pick)
        cal_card.lay.addWidget(self.grid)
        row.addWidget(cal_card, 3)
        self.day_card = Card('')
        self.day_card.setMinimumWidth(theme.size(320))
        row.addWidget(self.day_card, 2)
        lay.addLayout(row)

        chart_card = Card('動筆時間統計', '在 SAI2 實際下筆的時間（不含只開著沒畫）')
        seg = Segmented(stats.PERIODS, self.period)
        seg.changed.connect(self._set_period)
        chart_card.head.addWidget(seg)
        self.summary = label('', 'muted')
        chart_card.lay.addWidget(self.summary)
        self.chart = BarChart()
        chart_card.lay.addWidget(self.chart)
        lay.addWidget(chart_card)

        lay.addWidget(label('技能', 'section'))
        sk = QGridLayout()
        sk.setSpacing(16)
        for i, c in enumerate(cards):
            sk.addWidget(self._skill_card(c), i // 2, i % 2)
        lay.addLayout(sk)
        lay.addStretch(1)
        self._refresh_calendar()
        self._show_day(self.selected)
        self._set_period(self.period)

    # 月曆
    def _shift(self, delta):
        m = self.month + delta
        self.year += (m - 1) // 12
        self.month = (m - 1) % 12 + 1
        self._refresh_calendar()

    def _refresh_calendar(self):
        self.month_label.setText(f'{self.year} 年 {self.month} 月')
        self.grid.set_month(growth.month_calendar(self.q, self.year, self.month), self.selected)

    def _pick(self, key):
        self.selected = key
        self._show_day(key)

    def _show_day(self, key):
        lay = self.day_card.lay
        _clear(lay)
        d = growth.day_detail(self.q, key)
        dt = datetime.strptime(key, '%Y-%m-%d')
        lay.addWidget(label(f"{dt.month} 月 {dt.day} 日・星期{'一二三四五六日'[dt.weekday()]}", 'h2'))
        meta = f"打卡 {d['done']} / {d['total']}　練習 {stats.fmt_duration(d['practice_seconds'])}"
        lay.addWidget(label(meta + ('　請假日' if d['rest'] else ''), 'caption'))
        if not d['tasks']:
            lay.addWidget(label('這天沒有任務紀錄。', 'muted'))
        for t in d['tasks']:
            box = QFrame()
            box.setObjectName('dt')
            box.setStyleSheet(f'QFrame#dt{{background:{theme.SURFACE2};border-radius:12px;}}')
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 10, 12, 10)
            bl.setSpacing(4)
            top = QHBoxLayout()
            top.addWidget(label(t['name'], 'body'), 1)
            text, kind = STATUS_CHIP.get(t['status'], ('', 'neutral'))
            ai = t.get('ai_review')
            if t['status'] == 'done' and t['rating']:
                text += f"・{'AI ' if ai and not ai.get('overridden') else ''}{t['rating']} 分"
            top.addWidget(Chip(text, kind))
            bl.addLayout(top)
            if ai:
                extra = f"（AI 評 {ai['score']} 分，已手動修改）" if ai.get('overridden') else ''
                if ai.get('summary') or extra:
                    bl.addWidget(label(f"AI 簡評：{ai.get('summary', '')}{extra}", 'caption'))
            sub = '　'.join(x for x in (t['progress'], t['skills']) if x)
            if sub:
                bl.addWidget(label(sub, 'caption'))
            if t['note']:
                bl.addWidget(label(f"「{t['note']}」", 'muted'))
            if t['ref_title']:
                bl.addWidget(label(f"參考：{t['ref_title']}", 'caption'))
            if t['snapshot'] and os.path.isfile(t['snapshot']):
                bl.addWidget(_thumb(t['snapshot'], 120))
            lay.addWidget(box)
        lay.addStretch(1)

    # 統計
    def _set_period(self, period):
        self.period = period
        bars = stats.chart_bars(self.ctl.service.daily_history(), period)
        sm = stats.summary(bars, period)
        peak = f"　單{'日' if sm['unit'] == '天' else sm['unit']}最高 {sm['peak_tip']}" if sm['peak_tip'] else ''
        self.summary.setText(f"合計 {stats.fmt_duration(sm['total'])}　每日平均 {stats.fmt_duration(sm['avg_day'])}{peak}")
        self.chart.set_bars(bars)

    # 技能卡
    def _skill_card(self, c):
        card = Card(padding=18, spacing=8)
        ms = c['milestone']
        top = QHBoxLayout()
        top.addWidget(label(f"{c['icon']} {c['name']}", 'h2', wrap=False))
        top.addWidget(Chip(ms['name'], 'accent' if ms['level'] else 'neutral'))
        top.addStretch(1)
        star = button('本週主修' if c['focus'] else '設為主修', 'link' if not c['focus'] else 'ghost',
                      tip='之後的每日課表會優先排這項技能')
        if c['focus']:
            star.setStyleSheet(f'color:{theme.WARNING};')
        star.clicked.connect(lambda _=False, sid=c['id']: self._toggle_focus(sid))
        top.addWidget(star)
        card.lay.addLayout(top)
        line = QHBoxLayout()
        line.addWidget(label(f"累積 {growth.fmt_hours(c['total_seconds'])}", 'body', wrap=False))
        line.addStretch(1)
        line.addWidget(label(f"近 30 天 {growth.fmt_hours(c['recent_seconds'])}", 'caption', wrap=False))
        line.addWidget(Sparkline(c['series']))
        card.lay.addLayout(line)
        card.lay.addWidget(ProgressBar(ms['progress'], height=5))
        if ms['next_name']:
            goal = f"距「{ms['next_name']}」還差 {max(0.0, ms['ceil'] - ms['hours']):.1f} 小時"
        else:
            goal = '已達最高等級'
        info = [goal]
        p = c['path']
        if p:
            info.append(f"課程 {p['index'] + 1}/{p['total']}：Lv{p['current_level']} {p['current_name']}"
                        + ('（全部通過）' if p['completed'] else ''))
        if c['ratings']:
            info.append('自評 ' + ' '.join(str(r) for r in c['ratings']))
        card.lay.addWidget(label('　·　'.join(info), 'caption'))
        if c['idle_days'] is None:
            card.lay.addWidget(Chip('尚未開始', 'neutral'), 0, Qt.AlignLeft)
        elif c['idle']:
            card.lay.addWidget(Chip(f"{c['idle_days']} 天沒練", 'warn'), 0, Qt.AlignLeft)
        return card

    def _toggle_focus(self, sid):
        q = self.q
        q.settings['weekly_focus'] = '' if q.settings.get('weekly_focus') == sid else sid
        q.mark_dirty()
        q.save(force=True)
        skill = q.skill(sid)
        self.ctl.say(f"本週主修：{DT.skill_name(skill)}，之後的課表會優先排這項技能" if q.settings['weekly_focus']
                     else '已取消本週主修', important=False)
        self.ctl.open_main('成長')


# ─── 課程 ────────────────────────────────────────────────────────────────

class CoursesPage(QWidget):
    def __init__(self, ctl, skill: str = ''):
        super().__init__()
        self.ctl = ctl
        self.q = ctl.service.quests
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        lay.addWidget(PageHeader('課程', '7 條學習路徑，每堂課都有目標、重點、分段步驟與完成檢查；自評 3 分以上進入下一課'))
        if self.q is None:
            return
        self.paths = [s for s in self.q.data['skills'] if study_lessons.path(s['id'])]
        self.skill = skill or (self.paths[0]['id'] if self.paths else '')
        body = QHBoxLayout()
        body.setSpacing(20)
        side = QVBoxLayout()
        side.setSpacing(8)
        self.path_btns = {}
        for s in self.paths:
            prog = growth.path_progress(self.q, s['id'])
            b = QPushButton(f"{DT.skill_name(s)}\n{prog['passed']}/{prog['total']} 課")
            b.setProperty('kind', 'ghost')
            b.setCheckable(True)
            b.setStyleSheet('QPushButton{text-align:left;padding:10px 14px;border-radius:12px;}'
                            f'QPushButton:checked{{background:{theme.ACCENT_SOFT};color:{theme.STRONG_TEXT};}}')
            b.clicked.connect(lambda _=False, sid=s['id']: self._select(sid))
            side.addWidget(b)
            self.path_btns[s['id']] = b
        side.addStretch(1)
        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(theme.size(200))
        body.addWidget(side_w)
        self.lessons_box = QVBoxLayout()
        self.lessons_box.setSpacing(12)
        body.addLayout(self.lessons_box, 1)
        lay.addLayout(body)
        lay.addStretch(1)
        self._select(self.skill)

    def _select(self, sid):
        self.skill = sid
        for k, b in self.path_btns.items():
            b.setChecked(k == sid)
        _clear(self.lessons_box)
        st = self.q.path_state(sid)
        passed = set(st['passed'])
        cur = self.q.current_lesson(sid)
        for les in study_lessons.path(sid):
            self.lessons_box.addWidget(self._lesson_card(les, les['id'] in passed, cur and cur['id'] == les['id'],
                                                         st['attempts'].get(les['id'], 0)))
        self.lessons_box.addStretch(1)

    def _lesson_card(self, les, passed, current, attempts):
        card = Card(padding=18, spacing=8)
        top = QHBoxLayout()
        top.addWidget(label(f"Lv{les['level']}　{les['name']}", 'h2', wrap=False))
        if current:
            top.addWidget(Chip('目前課程', 'accent'))
        if passed:
            top.addWidget(Chip('已通過', 'ok'))
        top.addStretch(1)
        top.addWidget(label(f"{len(les['phases'])} 段・{les['minutes']} 分" + (f"・練過 {attempts} 次" if attempts else ''),
                            'caption', wrap=False))
        card.lay.addLayout(top)
        card.lay.addWidget(label(les['goal'], 'body'))
        card.lay.addWidget(label(f"本次專注：{les['focus']}", 'accent'))
        details = QWidget()
        dl = QVBoxLayout(details)
        dl.setContentsMargins(0, 6, 0, 0)
        dl.setSpacing(4)
        dl.addWidget(label('分段步驟', 'section'))
        for i, ph in enumerate(les['phases'], 1):
            dl.addWidget(label(f"{i}. {ph['name']}（{ph['minutes']} 分）　{ph['tip']}", 'muted'))
        dl.addWidget(label('常見錯誤', 'section'))
        for m in les['mistakes']:
            dl.addWidget(label(f'・{m}', 'muted'))
        dl.addWidget(label('完成檢查', 'section'))
        for c in les['checks']:
            dl.addWidget(label(f'・{c}', 'muted'))
        tries = works.lesson_attempts(self.q, les['id'])
        if tries:
            dl.addWidget(label('歷次練習', 'section'))
            row = QHBoxLayout()
            row.setSpacing(10)
            for a in tries[:6]:
                col = QVBoxLayout()
                if a['snapshot'] and os.path.isfile(a['snapshot']):
                    col.addWidget(_thumb(a['snapshot'], 96))
                ai = a.get('ai_review')
                txt = a['day'][5:] + (f"・{'AI ' if ai and not ai.get('overridden') else ''}{a['rating']} 分"
                                      if a['rating'] else '')
                cap = label(txt, 'caption', wrap=False)
                if ai and ai.get('summary'):
                    cap.setToolTip(f"AI 簡評：{ai['summary']}")
                col.addWidget(cap)
                row.addLayout(col)
            row.addStretch(1)
            dl.addLayout(row)
        details.hide()
        card.lay.addWidget(details)
        actions = QHBoxLayout()
        more = button('展開內容', 'link')
        more.clicked.connect(lambda: (details.setVisible(not details.isVisible()),
                                      more.setText('收合' if details.isVisible() else '展開內容')))
        actions.addWidget(more)
        actions.addStretch(1)
        if current:
            go = button('練這一課', 'primary', ic='play')
            go.clicked.connect(lambda: self._practice())
            actions.addWidget(go)
        else:
            jump = button('改從這課開始', 'ghost', tip='把這條路徑的目前課程移到這一課')
            jump.clicked.connect(lambda _=False, lid=les['id']: self._jump(lid))
            actions.addWidget(jump)
        card.lay.addLayout(actions)
        return card

    def _jump(self, lesson_id):
        if self.ctl.service.set_current_lesson(self.skill, lesson_id):
            les = study_lessons.lesson(lesson_id)
            self.ctl.say(f"之後的研究任務會從「Lv{les['level']} {les['name']}」開始。", important=False)
            self._select(self.skill)
        else:
            self.ctl.say('1.x 正在執行，暫時不能修改課程進度。')

    def _practice(self):
        main = self.ctl._main
        if main is not None:
            main._study_path(self.skill)


# ─── 作品 ────────────────────────────────────────────────────────────────

class WorksPage(QWidget):
    PAGE = 60

    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.svc = ctl.service
        self.s = ctl.settings
        self.selected = None
        self.limit = self.PAGE
        self._tiles: dict[str, QLabel] = {}
        self._row_widgets: dict[str, QWidget] = {}
        self.select_mode = False
        self.picked: set[str] = set()            # 批次刪除選取的作品
        self.confirm_batch = False
        self.confirm_exclude = None              # 詳細資料裡「不再記錄這個資料夾」等待確認的資料夾
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        head = PageHeader('作品', '在 SAI2 畫過的檔案；動筆時間、技能標籤、縮時影片都在這裡')
        self.select_btn = button('選取', 'ghost', ic='check', tip='選取多個作品，一次刪除紀錄')
        self.select_btn.setCheckable(True)
        self.select_btn.toggled.connect(self._toggle_select)
        excl = button('不記錄的資料夾', 'ghost', ic='hide')
        excl.clicked.connect(lambda: (self.excl_card.setVisible(not self.excl_card.isVisible()), self._fill_exclusions()))
        export = button('匯出 CSV', ic='file')
        export.clicked.connect(self._export)
        head.actions.addWidget(self.select_btn)
        head.actions.addWidget(excl)
        head.actions.addWidget(export)
        lay.addWidget(head)
        self.excl_card = Card('不記錄的資料夾', '這些資料夾裡的檔案不計時、不錄影、不算進每日任務（例如「下載」裡的參考圖）')
        self.excl_box = QVBoxLayout()
        self.excl_box.setSpacing(8)
        self.excl_card.lay.addLayout(self.excl_box)
        self.excl_card.hide()
        lay.addWidget(self.excl_card)
        if self.svc.paused:
            lay.addWidget(label('1.x 正在執行：這裡只能檢視，修改紀錄請等 1.x 關閉後再做。', 'warn'))
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜尋檔名或分組')
        self.search.textChanged.connect(lambda *_: self._fill())
        bar.addWidget(self.search, 1)
        self.group = QComboBox()
        self.group.setMinimumWidth(theme.size(150))
        self.group.currentIndexChanged.connect(lambda *_: self._fill())
        bar.addWidget(self.group)
        self.sort = Segmented(works.SORTS, self.s.get('works.sort', 'recent'))
        self.sort.changed.connect(self._sort_changed)
        bar.addWidget(self.sort)
        lay.addLayout(bar)
        self.sel_bar = QFrame()
        self.sel_bar.setObjectName('selbar')
        self.sel_bar.setStyleSheet(f'QFrame#selbar{{background:{theme.ACCENT_SOFT};border:1px solid {theme.ACCENT_BORDER};'
                                   f'border-radius:12px;}}')
        self.sel_lay = QHBoxLayout(self.sel_bar)
        self.sel_lay.setContentsMargins(14, 8, 10, 8)
        self.sel_bar.hide()
        lay.addWidget(self.sel_bar)
        # 清單與詳細資料各自捲動：清單很長時，點舊作品也看得到右邊的資訊
        body = QHBoxLayout()
        body.setSpacing(16)
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(8)
        self.list_box.setContentsMargins(0, 0, 6, 0)
        lw = QWidget()
        lw.setObjectName('wlist')
        lw.setStyleSheet('QWidget#wlist{background:transparent;}')
        lw.setLayout(self.list_box)
        self.list_scroll = self._scroll(lw)
        body.addWidget(self.list_scroll, 3)
        self.detail = Card('')
        self.detail.setMinimumWidth(theme.size(340))
        dw = QWidget()
        dw.setObjectName('wdetail')
        dw.setStyleSheet('QWidget#wdetail{background:transparent;}')
        dl = QVBoxLayout(dw)
        dl.setContentsMargins(0, 0, 6, 0)
        dl.addWidget(self.detail)
        dl.addStretch(1)
        self.detail_scroll = self._scroll(dw)
        self.detail_scroll.setMinimumWidth(theme.size(360))
        body.addWidget(self.detail_scroll, 2)
        lay.addLayout(body, 1)
        self._load()

    @staticmethod
    def _scroll(inner) -> QScrollArea:
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.viewport().setObjectName('wvp')
        sc.viewport().setStyleSheet('QWidget#wvp{background:transparent;}')
        sc.setMinimumHeight(240)
        sc.setWidget(inner)
        return sc

    def _load(self):
        q = self.svc.quests
        self.rows = works.rows(self.svc.all_files(), self.s.get('works.groups', {}),
                               (lambda k: q.file_tags(k)) if q else None)
        groups = sorted({r['group'] for r in self.rows})
        self.group.blockSignals(True)
        cur = self.group.currentData()
        self.group.clear()
        self.group.addItem('全部分組', '')
        for g in groups:
            self.group.addItem(g, g)
        self.group.setCurrentIndex(max(0, self.group.findData(cur)))
        self.group.blockSignals(False)
        self._fill()
        if self.selected:
            self._show(self.selected)
        elif self.rows:
            self._show(works.sort_rows(self.rows, self.sort.value)[0]['key'])
        else:
            self._empty_detail()

    def _sort_changed(self, v):
        self.s.set('works.sort', v)
        self.s.save()
        self._fill()

    # ── 縮圖 ──
    def _pixmap(self, path: str) -> QPixmap | None:
        return load_pixmap(path)

    def _set_tile(self, tile: QLabel, key: str):
        pm = load_pixmap(self.svc.thumb_of(key))
        if pm is None:
            tile.setPixmap(icon('file', theme.ACCENT_TEXT, 18).pixmap(18, 18))
            return
        tile.setPixmap(rounded_thumb(pm, tile.width(), tile.height(), 8, tile.devicePixelRatioF() or 1.0))

    def thumbs_updated(self, keys):
        """背景剛存好縮圖：更新清單上的小圖與右側預覽"""
        for k in keys:
            tile = self._tiles.get(k)
            if tile is not None:
                try:
                    self._set_tile(tile, k)
                except RuntimeError:                 # 列表已經重建
                    pass
        if self.selected in keys:
            self._show(self.selected)

    def _capture_now(self, key):
        if self.svc.capture_thumb(key, manual=True):
            self.ctl.say('正在擷取畫布…', important=False, seconds=3)
        else:
            self.ctl.say('現在沒辦法擷取：請確認 SAI2 開著這個檔案（1.x 執行中時也無法擷取）。')

    def _fill(self):
        _clear(self.list_box)
        self._tiles = {}
        self._row_widgets = {}
        items = works.sort_rows(works.filter_rows(self.rows, self.search.text(), self.group.currentData() or ''),
                                self.sort.value)
        if not items:
            self.list_box.addWidget(label('沒有符合的作品。在 SAI2 開檔畫圖後會出現在這裡。', 'muted'))
        for r in items[:self.limit]:
            self.list_box.addWidget(self._row(r))
        if len(items) > self.limit:
            more = button(f'顯示更多（還有 {len(items) - self.limit} 個）', 'ghost')
            more.clicked.connect(self._more)
            self.list_box.addWidget(more)
        self.list_box.addStretch(1)

    def _more(self):
        self.limit += self.PAGE
        self._fill()

    def _row(self, r):
        w = ClickFrame()
        w.setObjectName('wrow')
        w.setCursor(Qt.PointingHandCursor)
        self._row_widgets[r['key']] = w
        self._style_row(r['key'])
        w.clicked.connect(lambda k=r['key']: self._row_clicked(k))
        row = QHBoxLayout(w)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)
        if self.select_mode:
            cb = QCheckBox()
            cb.setChecked(r['key'] in self.picked)
            cb.setAccessibleName(f"選取 {r['name']}")
            cb.toggled.connect(lambda on, k=r['key']: self._pick(k, on))
            row.addWidget(cb)
        tile = QLabel()
        tile.setObjectName('wthumb')
        tile.setFixedSize(64, 48)
        tile.setAlignment(Qt.AlignCenter)
        tile.setStyleSheet(f'QLabel#wthumb{{background:{theme.SURFACE2};border-radius:8px;}}')
        self._set_tile(tile, r['key'])
        self._tiles[r['key']] = tile
        row.addWidget(tile)
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addWidget(label(r['name'], 'body', wrap=False))
        col.addWidget(label(f"{r['group']}　·　{r['last_seen'][:10] or '—'}", 'caption', wrap=False))
        row.addLayout(col, 1)
        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(label(stats.fmt_duration(r['draw']), 'body', wrap=False), 0, Qt.AlignRight)
        pb = ProgressBar(r['eff'], height=4)
        pb.setFixedWidth(theme.size(90))
        pb.setToolTip(f"動筆效率 {int(r['eff'] * 100)}%（動筆 / 開啟）")
        right.addWidget(pb, 0, Qt.AlignRight)
        row.addLayout(right)
        return w

    def _preview(self, key, editable) -> QWidget:
        """作品縮圖（存檔、停筆時自動擷取）；SAI2 正開著這個檔案時可以手動更新"""
        from datetime import datetime
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 4, 0, 4)
        bl.setSpacing(6)
        path = self.svc.thumb_of(key)
        pm = self._pixmap(path) if path else None
        if pm is not None:
            img = QLabel()
            dpr = img.devicePixelRatioF() or 1.0
            shown = pm.scaled(QSize(int(320 * dpr), int(220 * dpr)), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            shown.setDevicePixelRatio(dpr)
            img.setPixmap(shown)
            img.setCursor(Qt.PointingHandCursor)
            img.setToolTip('開啟圖片')
            img.mouseReleaseEvent = lambda _e, p=path: os.startfile(p)
            bl.addWidget(img, 0, Qt.AlignLeft)
            when = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%m/%d %H:%M')
            note = f'縮圖更新於 {when}（存檔、停筆時自動擷取）'
        else:
            note = '還沒有縮圖：在 SAI2 開啟這個檔案後會自動擷取。'
        row = QHBoxLayout()
        row.addWidget(label(note, 'caption'), 1)
        st = self.ctl.last_status
        if editable and st is not None and st.current_file == key:
            b = button('擷取目前畫布', 'ghost', ic='snapshot')
            b.clicked.connect(lambda: self._capture_now(key))
            row.addWidget(b)
        bl.addLayout(row)
        return box

    def _style_row(self, key):
        w = self._row_widgets.get(key)
        if w is None:
            return
        sel = key == self.selected or key in self.picked
        try:
            w.setStyleSheet(f"QFrame#wrow{{background:{theme.ACCENT_SOFT if sel else theme.CARD};"
                            f"border:1px solid {theme.ACCENT_BORDER if sel else theme.BORDER};border-radius:12px;}}"
                            f"QFrame#wrow:hover{{background:{theme.SURFACE2};}}")
        except RuntimeError:
            pass

    def _row_clicked(self, key):
        if self.select_mode:
            cb = self._row_widgets[key].findChild(QCheckBox)
            if cb is not None:
                cb.setChecked(not cb.isChecked())
            return
        self._show(key)

    # ── 批次刪除 ──
    def _toggle_select(self, on):
        self.select_mode = on
        self.select_btn.setText('完成選取' if on else '選取')
        self.picked.clear()
        self.confirm_batch = False
        self._fill()
        self._fill_sel_bar()

    def _pick(self, key, on):
        (self.picked.add if on else self.picked.discard)(key)
        self.confirm_batch = False
        self._style_row(key)
        self._fill_sel_bar()

    def _visible_keys(self):
        return [r['key'] for r in works.filter_rows(self.rows, self.search.text(), self.group.currentData() or '')]

    def _fill_sel_bar(self):
        _clear(self.sel_lay)
        self.sel_bar.setVisible(self.select_mode)
        if not self.select_mode:
            return
        n = len(self.picked)
        self.sel_lay.addWidget(label(f'已選 {n} 個作品', 'body', wrap=False))
        if self.confirm_batch and n:
            self.sel_lay.addWidget(label('只刪除計時紀錄與縮圖，不會刪除畫作檔案。', 'caption'), 1)
            ok = button(f'確定刪除 {n} 筆', 'primary')
            ok.setStyleSheet('background:#b91c1c;')
            ok.clicked.connect(self._delete_picked)
            no = button('取消', 'ghost')
            no.clicked.connect(lambda: (setattr(self, 'confirm_batch', False), self._fill_sel_bar()))
            self.sel_lay.addWidget(ok)
            self.sel_lay.addWidget(no)
            return
        self.sel_lay.addStretch(1)
        all_btn = button('全選目前清單', 'ghost')
        all_btn.setToolTip('選取搜尋與分組篩選後的所有作品')
        all_btn.clicked.connect(self._pick_all)
        clear_btn = button('清除選取', 'ghost')
        clear_btn.clicked.connect(lambda: (self.picked.clear(), self._fill(), self._fill_sel_bar()))
        dele = button('刪除選取的紀錄', 'primary')
        dele.setStyleSheet('background:#b91c1c;')
        dele.setEnabled(n > 0 and not self.svc.paused and self.svc.tracker is not None)
        dele.clicked.connect(lambda: (setattr(self, 'confirm_batch', True), self._fill_sel_bar()))
        for b in (all_btn, clear_btn, dele):
            self.sel_lay.addWidget(b)

    def _pick_all(self):
        self.picked = set(self._visible_keys())
        self._fill()
        self._fill_sel_bar()

    def _delete_picked(self):
        keys = sorted(self.picked)
        self.svc.delete_works(keys)
        if self.selected in self.picked:
            self.selected = None
        self.picked.clear()
        self.confirm_batch = False
        self.ctl.say(f'已刪除 {len(keys)} 筆作品紀錄。', important=False)
        self._load()
        self._fill_sel_bar()

    # ── 不記錄的資料夾 ──
    def _rules(self):
        return exclusions.normalize(self.s.get('exclude_folders', []))

    def _set_rules(self, rules):
        self.s.set('exclude_folders', rules)
        self.s.save()

    def _fill_exclusions(self):
        _clear(self.excl_box)
        rules = self._rules()
        if not rules:
            self.excl_box.addWidget(label('目前沒有。可以在下面輸入資料夾名稱，或在作品的詳細資料按「不再記錄這個資料夾」。', 'muted'))
        keys = [r['key'] for r in self.rows]
        for rule in rules:
            row = QHBoxLayout()
            n = len(exclusions.matching(keys, [rule]))
            row.addWidget(label(exclusions.describe(rule), 'body'), 1)
            if n:
                row.addWidget(label(f'有 {n} 筆舊紀錄', 'caption', wrap=False))
            rm = button('', 'ghost', ic='close', tip='恢復記錄這個資料夾')
            rm.clicked.connect(lambda _=False, r=rule: (self._set_rules(exclusions.remove(self._rules(), r)),
                                                        self._fill_exclusions()))
            row.addWidget(rm)
            self.excl_box.addLayout(row)
        add_row = QHBoxLayout()
        ed = QLineEdit()
        ed.setPlaceholderText('資料夾名稱，例如「下載」（路徑中任何一層叫這個名字都不記錄）')
        add = button('加入', 'ghost')

        def do_add():
            name = ed.text().strip().strip('\\/ ')
            if not name:
                return
            self._set_rules(exclusions.add(self._rules(), 'folder', name))
            self._fill_exclusions()
        add.clicked.connect(do_add)
        ed.returnPressed.connect(do_add)
        add_row.addWidget(ed, 1)
        add_row.addWidget(add)
        self.excl_box.addLayout(add_row)
        self.excl_box.addWidget(label('加入後立即生效；已有的紀錄不會自動刪除，可以用「選取」一次刪除。', 'caption'))
        self.excl_edit = ed

    def _exclude_folder(self, folder, delete_existing):
        self._set_rules(exclusions.add(self._rules(), 'prefix', folder))
        self.confirm_exclude = None
        msg = f'之後不再記錄「{exclusions.folder_label(folder)}」裡的檔案。'
        if delete_existing:
            keys = exclusions.matching([r['key'] for r in self.rows], [{'kind': 'prefix', 'value': folder}])
            self.svc.delete_works(keys)
            if self.selected in keys:
                self.selected = None
            msg += f'已刪除 {len(keys)} 筆舊紀錄。'
        self.ctl.say(msg, important=False)
        self._load()
        if self.excl_card.isVisible():
            self._fill_exclusions()

    def _empty_detail(self):
        _clear(self.detail.lay)
        self.detail.lay.addWidget(label('選一個作品看詳細資料。', 'muted'))

    def _video_tools(self, key, lay):
        """合併這個作品的錄影片段、匯出指定長度的縮時（core/video_tools.py；背景執行）"""
        from core import video_tools as V
        folder = works.video_dir(self.s.videos_dir, key)
        segs = V.segments(folder)
        if not segs:
            return
        if not V.available():
            lay.addWidget(label('合併片段、匯出指定長度需要 ffmpeg（加入 PATH）。', 'caption'))
            return
        row = QHBoxLayout()
        merge = button(f'合併 {len(segs)} 段影片', 'secondary')
        merge.setEnabled(len(segs) >= 2)
        merge.setToolTip('依時間接成一部（原始片段保留）；解析度不同時等比例縮放並補邊，不會變形')
        length = QSpinBox()
        length.setRange(5, 600)
        length.setSuffix(' 秒')
        length.setValue(int(self.s.get('works.export_seconds', 60) or 60))
        length.setFixedWidth(theme.size(100))
        export = button('匯出縮時', 'secondary')
        export.setToolTip('把全部片段接起來，等比例加速成指定長度（片段比較短時不放慢）')
        # 兩行：詳細資料欄不寬，放大文字或換成較長的語言時，同一行放不下兩個按鈕
        row.addWidget(merge)
        row.addStretch(1)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(label('匯出長度', 'caption', wrap=False))
        row2.addWidget(length)
        row2.addWidget(export)
        row2.addStretch(1)
        lay.addLayout(row2)
        status = label('', 'caption')
        lay.addWidget(status)

        def run(job, describe):
            merge.setEnabled(False)
            export.setEnabled(False)
            status.setText('處理中… 0%')
            last = [-1]

            def progress(pct):
                if pct != last[0]:
                    last[0] = pct
                    self.ctl.work_done.emit(lambda p=pct: status.setText(f'處理中… {p}%'))

            def work():
                try:
                    res, err = job(progress), None
                except V.VideoError as e:
                    res, err = None, str(e)
                except Exception as e:                  # ffmpeg 不在、檔案被占用…
                    res, err = None, f'處理失敗：{e}'
                self.ctl.work_done.emit(lambda: done(res, err))

            def done(res, err):
                if err:
                    if self.selected == key:
                        status.setText(err)
                        merge.setEnabled(len(segs) >= 2)
                        export.setEnabled(True)
                    self.ctl.say(err)
                    return
                path = res['path']
                self.ctl.say(describe(res), actions=[('播放', lambda: os.startfile(path)),
                                                     ('影片資料夾', lambda: os.startfile(folder))])
                if self.selected == key:
                    self._show(key)
            threading.Thread(target=work, daemon=True).start()

        def length_text(sec):
            return f'{int(round(sec))} 秒' if sec < 60 else stats.fmt_duration(sec)

        def resize_note(res):
            n = len(res['resized'])
            return f'，其中 {n} 段解析度不同，已等比例縮放並補邊' if n else ''

        merge.clicked.connect(lambda: run(
            lambda p: V.merge(folder, p),
            lambda r: f"已把 {r['segments']} 段影片合併成一部（{length_text(r['duration'])}）{resize_note(r)}。"))

        def do_export():
            secs = length.value()
            self.s.set('works.export_seconds', secs)
            self.s.save()
            run(lambda p: V.export_length(folder, secs, p),
                lambda r: (f"已匯出 {int(round(r['duration']))} 秒的縮時影片{resize_note(r)}。" if r['speed'] < 1 else
                           f"影片原本只有 {length_text(r['source_duration'])}，沒有超過 {secs} 秒，所以沒有加速{resize_note(r)}。"))
        export.clicked.connect(do_export)

    def _show(self, key):
        r = next((x for x in self.rows if x['key'] == key), None)
        if r is None:
            self._empty_detail()
            return
        prev, self.selected = self.selected, key
        if prev != key:
            self.confirm_exclude = None
            self._style_row(prev)                # 只重新上色，不重建清單（才不會跳回最上面）
            self._style_row(key)
        lay = self.detail.lay
        _clear(lay)
        editable = not self.svc.paused and self.svc.tracker is not None
        lay.addWidget(label(r['name'], 'h2'))
        lay.addWidget(label(key, 'caption'))
        lay.addWidget(self._preview(key, editable))
        tiles = QGridLayout()
        tiles.setSpacing(8)
        for i, (cap, val) in enumerate((('動筆', stats.fmt_duration(r['draw'])), ('開著', stats.fmt_duration(r['open'])),
                                        ('效率', f"{int(r['eff'] * 100)}%"), ('次數', f"{r['sessions']} 次"))):
            box = QFrame()
            box.setObjectName('mt')
            box.setStyleSheet(f'QFrame#mt{{background:{theme.SURFACE2};border-radius:10px;}}')
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 8, 12, 8)
            bl.addWidget(label(cap, 'caption'))
            bl.addWidget(label(val, 'body', wrap=False))
            tiles.addWidget(box, i // 2, i % 2)
        lay.addLayout(tiles)
        lay.addWidget(label(f"最後使用 {r['last_seen'].replace('T', ' ')[:16] or '—'}", 'caption'))

        acts = QGridLayout()
        acts.setSpacing(8)
        b1 = button('在 SAI2 開啟', 'primary', ic='open_sai2')
        b1.clicked.connect(lambda: self.ctl.open_recent(key))
        b2 = button('開啟資料夾', ic='works')
        b2.clicked.connect(lambda: self._open_folder(key))
        acts.addWidget(b1, 0, 0)
        acts.addWidget(b2, 0, 1)
        lay.addLayout(acts)

        q = self.svc.quests
        if q is not None:
            lay.addWidget(label('技能標籤', 'section'))
            lay.addWidget(label('畫這個檔案的時間會計入勾選的技能', 'caption'))
            grid = QGridLayout()
            grid.setSpacing(6)
            cur = set(q.file_tags(key))
            for i, sk in enumerate(q.data['skills']):
                b = QPushButton(DT.skill_name(sk))
                b.setCheckable(True)
                b.setChecked(sk['id'] in cur)
                b.setEnabled(editable)
                b.setStyleSheet(theme.scale_css('QPushButton{padding:5px 10px;border-radius:14px;font-size:12px;}'
                                f'QPushButton:checked{{background:{theme.ACCENT_SOFT};color:{theme.ACCENT_TEXT};'
                                f'border:1px solid {theme.ACCENT_BORDER};}}'))
                b.toggled.connect(lambda _on, k=key: self._save_tags(k))
                grid.addWidget(b, i // 3, i % 3)
                b.setProperty('sid', sk['id'])
            self._tag_btns = [grid.itemAt(i).widget() for i in range(grid.count())]
            lay.addLayout(grid)

        lay.addWidget(label('分組', 'section'))
        grow = QHBoxLayout()
        ged = QLineEdit(self.s.get('works.groups', {}).get(key, ''))
        ged.setPlaceholderText(f"自動：{works.auto_group(key)}")
        save_g = button('套用', 'ghost')
        save_g.clicked.connect(lambda: self._set_group(key, ged.text().strip()))
        grow.addWidget(ged, 1)
        grow.addWidget(save_g)
        lay.addLayout(grow)

        vids = works.videos(self.s.videos_dir, key)
        lay.addWidget(label(f'縮時影片（{len(vids)}）', 'section'))
        for v in vids[:4]:
            b = button(os.path.basename(v), 'link', ic='record')
            b.clicked.connect(lambda _=False, p=v: os.startfile(p))
            lay.addWidget(b, 0, Qt.AlignLeft)
        if vids:
            vb = button('影片資料夾', 'ghost', ic='works')
            vb.clicked.connect(lambda: os.startfile(works.video_dir(self.s.videos_dir, key)))
            lay.addWidget(vb, 0, Qt.AlignLeft)
            self._video_tools(key, lay)
        else:
            lay.addWidget(label('還沒有影片。在「工具」開啟縮時錄影後，畫這個檔案就會錄下來。', 'caption'))

        if editable:
            lay.addWidget(label('整理紀錄', 'section'))
            aliases = self.svc.aliases_of(key)
            if aliases:
                lay.addWidget(label('已合併：' + '、'.join(a.split(' _ ')[-1] for a in aliases), 'caption'))
            merge_row = QHBoxLayout()
            target = QComboBox()
            target.addItem('合併到其他作品…', '')
            for x in sorted(self.rows, key=lambda x: x['name'].lower()):
                if x['key'] != key:
                    target.addItem(x['name'], x['key'])
            go = button('合併', 'ghost')
            go.setToolTip('另存新檔後想把兩個檔案的時間算在一起時使用')
            go.clicked.connect(lambda: self._merge(key, target.currentData()))
            merge_row.addWidget(target, 1)
            merge_row.addWidget(go)
            lay.addLayout(merge_row)
            self._exclude_row(lay, key)
            self._delete_row(lay, key)
        lay.addStretch(1)

    def _exclude_row(self, lay, key):
        folder = exclusions.folder_of(key)
        if not folder:
            return
        if self.confirm_exclude != folder:
            b = button('不再記錄這個資料夾', 'ghost', ic='hide')
            b.setToolTip(exclusions.folder_label(folder))
            b.clicked.connect(lambda: (setattr(self, 'confirm_exclude', folder), self._show(key)))
            lay.addWidget(b, 0, Qt.AlignLeft)
            return
        same = exclusions.matching([r['key'] for r in self.rows], [{'kind': 'prefix', 'value': folder}])
        lay.addWidget(label(f'「{exclusions.folder_label(folder)}」與底下的子資料夾都不再記錄。'
                            f'這個資料夾目前有 {len(same)} 筆紀錄。', 'caption'))
        row = QHBoxLayout()
        keep = button('只停止記錄', 'primary')
        keep.clicked.connect(lambda: self._exclude_folder(folder, False))
        drop = button(f'停止記錄並刪除 {len(same)} 筆', 'ghost')
        drop.clicked.connect(lambda: self._exclude_folder(folder, True))
        no = button('取消', 'ghost')
        no.clicked.connect(lambda: (setattr(self, 'confirm_exclude', None), self._show(key)))
        for b in (keep, drop, no):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

    def _delete_row(self, lay, key):
        holder = QHBoxLayout()
        delete = button('刪除這筆紀錄', 'ghost')
        delete.setStyleSheet(f'color:{theme.DANGER};')
        confirm = button('確定刪除', 'primary')
        confirm.setStyleSheet('background:#b91c1c;')
        cancel = button('取消', 'ghost')
        confirm.hide()
        cancel.hide()
        note = label('只會刪除計時紀錄，不會刪除畫作檔案。', 'caption')
        note.hide()
        delete.clicked.connect(lambda: (delete.hide(), confirm.show(), cancel.show(), note.show()))
        cancel.clicked.connect(lambda: (delete.show(), confirm.hide(), cancel.hide(), note.hide()))
        confirm.clicked.connect(lambda: self._delete(key))
        holder.addWidget(delete)
        holder.addWidget(confirm)
        holder.addWidget(cancel)
        holder.addStretch(1)
        lay.addLayout(holder)
        lay.addWidget(note)

    def _save_tags(self, key):
        q = self.svc.quests
        ids = [b.property('sid') for b in self._tag_btns if b.isChecked()]
        q.set_file_tags(key, ids)
        q.save(force=True)

    def _set_group(self, key, name):
        groups = dict(self.s.get('works.groups', {}) or {})
        if name:
            groups[key] = name
        else:
            groups.pop(key, None)
        self.s.set('works.groups', groups)
        self.s.save()
        self._load()

    def _merge(self, key, target):
        if not target:
            return
        try:
            self.svc.merge_work(key, target)
        except Exception as e:
            self.ctl.say(f'無法合併：{e}')
            return
        self.ctl.say(f"已把「{key.split(' _ ')[-1]}」合併到「{target.split(' _ ')[-1]}」。", important=False)
        self.selected = target
        self._load()

    def _delete(self, key):
        self.svc.delete_work(key)
        self.selected = None
        self.ctl.say(f"已刪除「{key.split(' _ ')[-1]}」的計時紀錄。", important=False)
        self._load()

    def _open_folder(self, key):
        from core.file_paths import resolve_file_key

        def run():
            path = resolve_file_key(key)
            if path and os.path.exists(os.path.dirname(path)):
                self.ctl.work_done.emit(lambda: subprocess.Popen(['explorer', '/select,', os.path.normpath(path)]))
            else:
                self.ctl.work_done.emit(lambda: self.ctl.say('找不到這個檔案的位置，可能已經移動或改名。'))
        threading.Thread(target=run, daemon=True).start()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, '匯出 CSV', os.path.join(os.path.expanduser('~'), 'Desktop',
                                              f"drawcompanion_{datetime.now():%Y%m%d}.csv"), 'CSV (*.csv)')
        if not path:
            return
        tr = self.svc.tracker
        if tr is None:
            self.ctl.say('1.x 正在執行，請在 1.x 匯出或關閉 1.x 後再試。')
            return
        tr.export_csv(path)
        self.ctl.say('已匯出 CSV。', actions=[('開啟資料夾', lambda: os.startfile(os.path.dirname(path)))])


# ─── 工具 ────────────────────────────────────────────────────────────────

MULTIPLIERS = [(1, '1 倍（每 33 毫秒一張）'), (2, '2 倍'), (5, '5 倍（建議）'), (10, '10 倍'), (20, '20 倍'),
               (50, '50 倍'), (100, '100 倍（長時間作品）')]
TARGETS = [('canvas', '只錄畫紙（建議）'), ('canvas_float', '畫紙（隱藏浮動檢視，不受縮放旋轉影響）'), ('window', '整個 SAI2 視窗'),
           ('screen', '整個螢幕')]
QUALITIES = [('compact', '精簡'), ('standard', '標準'), ('high', '高畫質'), ('lossless', '無損')]


class ToolsPage(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.svc = ctl.service
        self.s = ctl.settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        lay.addWidget(PageHeader('工具', 'SAI2 內建濾鏡擴充與縮時錄影等輔助工具'))

        flt_card = Card('SAI2 內建濾鏡擴充 (Mod)',
                        '將「效果」子選單直接內置於 SAI2 頂部「濾鏡」選單中，所有參數調整、16-bit 即時預覽與圖層套用（含 Ctrl+Z 復原）皆直接於 SAI2 內進行；'
                        '另在圖層面板「特殊效果」加入「筆畫」（設定後於下次啟動 SAI2 生效）')
        self.flt_toggle = ToggleSwitch(bool(self.s.get('filters_mod.enabled', False)))
        self.flt_toggle.toggled.connect(self._toggle_filters_mod)
        flt_card.head.addWidget(self.flt_toggle)
        self.flt_status_box = QVBoxLayout()
        self.flt_status_box.setSpacing(6)
        flt_card.lay.addLayout(self.flt_status_box)
        lay.addWidget(flt_card)

        flt_grp = SettingGroup('內建濾鏡 / 圖層效果項目開關（下次啟動 SAI2 生效）')
        from core.sai2_filters import MOD_FEATURES
        self.flt_toggles = {}
        for key, meta in MOD_FEATURES.items():
            tog = ToggleSwitch(bool(self.s.get(f'filters_mod.{key}', True)))
            tog.toggled.connect(lambda v, k=key: self._toggle_single_filter(k, v))
            self.flt_toggles[key] = tog
            flt_grp.row(meta['name'], meta['desc'], tog)
        lay.addWidget(flt_grp)

        rec = Card('縮時錄影', '只在動筆時擷取，停筆就暫停；畫哪個作品就錄哪個，關閉 SAI2（或所有檔案）時每個作品各自合成影片')
        self.toggle = ToggleSwitch(bool(self.s.get('timelapse.enabled')))
        self.toggle.toggled.connect(self._toggle)
        rec.head.addWidget(self.toggle)
        self.status_box = QVBoxLayout()
        self.status_box.setSpacing(6)
        rec.lay.addLayout(self.status_box)
        self.progress = ProgressBar(0.0)
        self.progress.hide()
        rec.lay.addWidget(self.progress)
        self.progress_label = label('', 'caption')
        self.progress_label.hide()
        rec.lay.addWidget(self.progress_label)
        lay.addWidget(rec)

        g = SettingGroup('錄影設定')
        g.row('倍速', '影片播放速度；倍數越高，擷取間隔越長、影片越短', self._combo('timelapse.multiplier', MULTIPLIERS, int))
        target = self._combo('timelapse.target', TARGETS)
        g.row('錄製範圍', '「畫紙」不含工作區與捲軸；放大畫面時錄看得到的部分', target)
        self.float_row = g.row('SAI2「新增浮動檢視」的快捷鍵',
                               '隱藏浮動檢視模式會替目前的畫布開一個新的浮動檢視，移到螢幕外錄影，你縮放、旋轉、捲動畫面都不影響影片。'
                               'SAI2 預設沒有這個快捷鍵：請先在 SAI2 的快捷鍵設定替「新增浮動檢視」指定一組，再在這裡按下相同的組合',
                               self._float_key_editor(), stack=True)
        target.currentIndexChanged.connect(lambda _i: self._sync_float_row())
        self._sync_float_row()
        g.row('畫質', '無損會佔用較多硬碟空間', self._combo('timelapse.quality', QUALITIES))
        g.row('影片 FPS', '', self._combo('timelapse.fps', [(24, '24'), (30, '30'), (60, '60')], int))
        folder = QWidget()
        fr = QHBoxLayout(folder)
        fr.setContentsMargins(0, 0, 0, 0)
        ed = QLineEdit(self.s.get('timelapse.output_dir', '') or '')
        ed.setPlaceholderText(self.s.videos_dir)
        ed.setMinimumWidth(theme.size(320))
        pick = button('瀏覽…')
        pick.clicked.connect(lambda: self._pick_dir(ed))
        ed.textChanged.connect(lambda v: self._set('timelapse.output_dir', v.strip()))
        openb = button('開啟', 'ghost', ic='works')
        openb.clicked.connect(self._open_videos)
        fr.addWidget(ed, 1)
        fr.addWidget(pick)
        fr.addWidget(openb)
        g.row('影片存放位置', '每個作品一個子資料夾', folder, stack=True)
        lay.addWidget(g)

        self.recover_card = Card('未合成的錄影', '程式意外關閉、斷電或沒有 ffmpeg 時留下的錄影畫面，可以合成影片或捨棄')
        self.recover_box = QVBoxLayout()
        self.recover_box.setSpacing(8)
        self.recover_card.lay.addLayout(self.recover_box)
        self.recover_card.hide()
        lay.addWidget(self.recover_card)
        self._confirm_discard = None
        self._refresh_recover()

        later = Card('與 1.x 並存')
        later.lay.addWidget(label('同時開著 1.x 時，2.0 會自動暫停記錄，避免兩邊重複計時；關閉 1.x 後就會繼續。', 'caption'))
        lay.addWidget(later)
        lay.addStretch(1)
        self.refresh()

    def _float_key_editor(self) -> QWidget:
        from PySide6.QtWidgets import QKeySequenceEdit
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        self.float_key = QKeySequenceEdit(QKeySequence(self.s.get('timelapse.float_hotkey', '') or ''))
        self.float_key.setMaximumSequenceLength(1)
        self.float_key.setFixedWidth(theme.size(200))
        inner = self.float_key.findChild(QLineEdit)
        if inner:
            inner.setPlaceholderText('點這裡後按下快捷鍵')
        self.float_key.editingFinished.connect(self._float_key_changed)
        clear = button('清除', 'ghost')
        clear.clicked.connect(lambda: (self.float_key.clear(), self._float_key_changed()))
        row.addWidget(self.float_key)
        row.addWidget(clear)
        row.addStretch(1)
        return box

    def _float_key_changed(self):
        from core import hotkeys
        text = self.float_key.keySequence().toString(QKeySequence.PortableText)
        try:
            text = hotkeys.normalize(text) if text else ''
        except ValueError as e:
            self.float_row.set_note(str(e))
            return
        self._set('timelapse.float_hotkey', text)
        self._sync_float_row()

    def _sync_float_row(self):
        """只在選了隱藏浮動檢視時顯示；沒設定或和 2.0 自己的快捷鍵相同時提醒"""
        from core import hotkeys
        show = self.s.get('timelapse.target') == 'canvas_float'
        self.float_row.setVisible(show)
        key = self.s.get('timelapse.float_hotkey', '') or ''
        same = hotkeys.clash(key, self.s.get('hotkeys', {})) if key else None
        if not key:
            note = '還沒設定：錄影時會改用「只錄畫紙」'
        elif same:
            note = f'和 2.0 的「{same}」相同，按鍵會被 2.0 攔走、送不到 SAI2；請換一組，或到「設定 › 快捷鍵」改掉 2.0 的'
        else:
            note = ''
        self.float_row.set_note(note)

    def _combo(self, key, options, cast=str):
        cb = QComboBox()
        for v, text in options:
            cb.addItem(text, v)
        cur = self.s.get(key)
        cb.setCurrentIndex(max(0, cb.findData(cast(cur) if cur is not None else options[0][0])))
        cb.setMinimumWidth(theme.size(220))
        cb.currentIndexChanged.connect(lambda _i: self._set(key, cb.currentData()))
        return cb

    def _set(self, key, value):
        self.s.set(key, value)
        self.s.save()
        self.svc.apply_recorder_settings()

    def _pick_dir(self, ed):
        d = QFileDialog.getExistingDirectory(self, '選擇影片存放位置', ed.text() or self.s.videos_dir)
        if d:
            ed.setText(os.path.normpath(d))

    def showEvent(self, e):
        super().showEvent(e)
        self._refresh_recover()

    def _refresh_recover(self):
        """未合成的錄影清單（掃資料夾，只在顯示頁面與操作後更新，不跟著每秒的狀態更新）"""
        from core.timelapse import find_ffmpeg
        _clear(self.recover_box)
        items = self.svc.unexported_recordings()
        self.recover_card.setVisible(bool(items))
        if not items:
            return
        has_ffmpeg = find_ffmpeg()
        if not has_ffmpeg:
            self.recover_box.addWidget(label('找不到 ffmpeg：安裝 ffmpeg 並加入 PATH 後才能合成。', 'warn'))
        for it in items:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            when = datetime.fromtimestamp(it['time']).strftime('%m/%d %H:%M')
            hl.addWidget(label(f"{it['name']}　{it['frames']} 張　{when}", 'body'), 1)
            go = button('合成', 'primary')
            go.setEnabled(has_ffmpeg)
            go.clicked.connect(lambda _c=False, it=it: self._recover([it]))
            confirming = self._confirm_discard == it['dir']
            drop = button('確定捨棄' if confirming else '捨棄', 'secondary' if confirming else 'ghost')
            drop.clicked.connect(lambda _c=False, it=it: self._discard(it))
            hl.addWidget(go)
            hl.addWidget(drop)
            self.recover_box.addWidget(row)

    def _recover(self, items):
        self.ctl.recover_recordings(items)
        self._confirm_discard = None
        self._refresh_recover()
        self.refresh()

    def _discard(self, it):
        if self._confirm_discard != it['dir']:
            self._confirm_discard = it['dir']          # 第一次按：變成「確定捨棄」
        else:
            self._confirm_discard = None
            self.svc.discard_recording(it)
        self._refresh_recover()

    def _open_videos(self):
        os.makedirs(self.s.videos_dir, exist_ok=True)
        os.startfile(self.s.videos_dir)

    def _export_now(self):
        n = self.svc.export_recordings()
        self.ctl.say(f'開始合成 {n} 部影片，完成後會通知你。' if n else '錄到的內容太少（沒有實際下筆），沒有合成。',
                     important=False)
        self.refresh()

    def _toggle(self, on):
        self.ctl.set_recording(on)
        self.refresh()

    def _filters_kw(self) -> dict:
        from core.sai2_filters import MOD_FEATURES
        return {k: bool(self.s.get(f'filters_mod.{k}', True)) for k in MOD_FEATURES}

    def _toggle_filters_mod(self, on):
        from core.sai2_filters import sync_filters_mod
        if hasattr(self.ctl, 'set_filters_mod'):
            self.ctl.set_filters_mod(on)
        else:
            self.s.set('filters_mod.enabled', bool(on))
            self.s.save()
            sync_filters_mod(self.s.get('sai2_exe', '') or '', enabled=bool(on), filters=self._filters_kw())
        self.refresh()

    def _toggle_single_filter(self, filter_key: str, on: bool):
        from core.sai2_filters import sync_filters_mod
        if hasattr(self.ctl, 'set_filters_mod'):
            self.ctl.set_filters_mod(**{filter_key: bool(on)})
        else:
            self.s.set(f'filters_mod.{filter_key}', bool(on))
            self.s.save()
            sync_filters_mod(self.s.get('sai2_exe', '') or '',
                             enabled=bool(self.s.get('filters_mod.enabled', False)), filters=self._filters_kw())
        self.refresh()

    def _refresh_filters_mod(self):
        from core.sai2_filters import get_mod_status, FILTERS, LAYER_EFFECTS, MOD_FEATURES, MOD_DLL_FILENAME
        _clear(self.flt_status_box)
        enabled = bool(self.s.get('filters_mod.enabled', False))
        on = {k: bool(self.s.get(f'filters_mod.{k}', True)) for k in MOD_FEATURES}
        any_on = any(on.values())

        if self.flt_toggle.isChecked() != enabled:
            self.flt_toggle.blockSignals(True)
            self.flt_toggle.setChecked(enabled)
            self.flt_toggle.blockSignals(False)
        for key, tog in self.flt_toggles.items():
            if tog.isChecked() != on[key]:
                tog.blockSignals(True)
                tog.setChecked(on[key])
                tog.blockSignals(False)
            tog.setEnabled(enabled)

        st = get_mod_status(self.s.get('sai2_exe', '') or '')
        sai2_dir = st.get('sai2_dir', '')

        if not enabled or not any_on:
            self.flt_status_box.addWidget(Chip('關閉', 'neutral'), 0, Qt.AlignLeft)
            self.flt_status_box.addWidget(label('開啟開關後，會將原生濾鏡擴充模組部署至 SAI2 資料夾（於下次啟動 SAI2 時生效）。', 'caption'))
            return

        if st.get('dll_conflict'):
            self.flt_status_box.addWidget(Chip('SAI2 資料夾已有其他模組', 'warn'), 0, Qt.AlignLeft)
            self.flt_status_box.addWidget(label(
                f'{sai2_dir} 裡的 {MOD_DLL_FILENAME} 不是本模組，為避免覆蓋其他模組而未部署。', 'caption'))
        elif st.get('dll_installed') and st.get('enabled'):
            self.flt_status_box.addWidget(Chip('● 已啟用（下次啟動 SAI2 生效）', 'ok'), 0, Qt.AlignLeft)
            lines = [f'已部署至：{sai2_dir}']
            flt_names = [meta['name'] for k, meta in FILTERS.items() if on[k]]
            fx_names = [meta['name'] for k, meta in LAYER_EFFECTS.items() if on[k]]
            if flt_names:
                lines.append(f"濾鏡：{'、'.join(flt_names)}（SAI2 頂部選單「濾鏡 → 效果」）")
            if fx_names:
                lines.append(f"圖層效果：{'、'.join(fx_names)}（圖層面板「特殊效果」下拉選單，僅 SAI2 2026 版）")
            self.flt_status_box.addWidget(label('\n'.join(lines), 'caption'))
        elif sai2_dir:
            self.flt_status_box.addWidget(Chip('待同步至 SAI2 資料夾', 'accent'), 0, Qt.AlignLeft)
            self.flt_status_box.addWidget(label(f'目標 SAI2 資料夾：{sai2_dir}（重新切換開關即可立即部署，下次啟動 SAI2 生效）', 'caption'))
        else:
            self.flt_status_box.addWidget(Chip('尚未偵測到 SAI2 路徑', 'warn'), 0, Qt.AlignLeft)
            self.flt_status_box.addWidget(label('請先開啟一次 SAI2，或至「設定 › 一般」指定 sai2.exe 位置。', 'caption'))

    def refresh(self):
        from core.timelapse import find_ffmpeg
        self._refresh_filters_mod()
        _clear(self.status_box)
        info = self.svc.recording_info()
        if self.toggle.isChecked() != info['enabled']:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(info['enabled'])
            self.toggle.blockSignals(False)
        if not find_ffmpeg():
            self.status_box.addWidget(label('找不到 ffmpeg：可以錄製，但無法合成影片。請安裝 ffmpeg 並加入 PATH。', 'warn'))
        if not info['available']:
            self.status_box.addWidget(Chip('1.x 執行中，暫停', 'warn'), 0, Qt.AlignLeft)
        elif not info['enabled']:
            self.status_box.addWidget(Chip('關閉', 'neutral'), 0, Qt.AlignLeft)
        elif info['active_file']:
            self.status_box.addWidget(Chip('● 錄影中', 'warn'), 0, Qt.AlignLeft)
            self.status_box.addWidget(label(info['active_file'].split(' _ ')[-1], 'h2'))
            self.status_box.addWidget(label(f"已擷取 {info['frames']} 張　預估影片 {stats.fmt_duration(info['video_seconds'])}"
                                            if info['video_seconds'] >= 60 else
                                            f"已擷取 {info['frames']} 張　預估影片 {int(info['video_seconds'])} 秒", 'caption'))
        else:
            self.status_box.addWidget(Chip('等待開檔', 'accent'), 0, Qt.AlignLeft)
            self.status_box.addWidget(label('在 SAI2 開啟（已存檔的）作品並動筆就會開始錄。', 'caption'))
        waiting = info.get('waiting') or []
        if waiting:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            names = '、'.join(f.split(' _ ')[-1] for f in waiting[:3]) + (f' 等 {len(waiting)} 個' if len(waiting) > 3 else '')
            hl.addWidget(label(f'也錄了：{names}（關閉 SAI2 時合成）', 'caption'), 1)
            now = button('現在合成', 'ghost')
            now.clicked.connect(self._export_now)
            hl.addWidget(now)
            self.status_box.addWidget(row)
        if info['exporting']:
            self.status_box.addWidget(label(f"有 {info['exporting']} 部影片正在合成", 'caption'))
        pct, msg = getattr(self.ctl, 'export_state', (None, ''))
        show = pct is not None and info['exporting'] > 0
        self.progress.setVisible(show)
        self.progress_label.setVisible(bool(msg))
        if show:
            self.progress.ratio = pct / 100
            self.progress.update()
        self.progress_label.setText(msg)
