# -*- coding: utf-8 -*-
"""主視窗的成長、課程、作品、工具頁（階段三）"""

from __future__ import annotations

import os
import subprocess
import threading
from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from core import data_text as DT
from core import growth, stats, study_lessons, works
from core.daily_quests import QuestManager
from ui2 import theme
from ui2.charts import BarChart, MonthGrid, Sparkline
from ui2.icons import icon
from ui2.widgets import (Card, Chip, PageHeader, ProgressBar, Segmented, SettingGroup, StatTile, ToggleSwitch, button,
                         label)

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
        self.day_card.setMinimumWidth(320)
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
            if t['status'] == 'done' and t['rating']:
                text += f"・{t['rating']} 分"
            top.addWidget(Chip(text, kind))
            bl.addLayout(top)
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
        side_w.setFixedWidth(200)
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
                txt = a['day'][5:] + (f"・{a['rating']} 分" if a['rating'] else '')
                col.addWidget(label(txt, 'caption', wrap=False))
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
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)
        head = PageHeader('作品', '在 SAI2 畫過的檔案；動筆時間、技能標籤、縮時影片都在這裡')
        export = button('匯出 CSV', ic='file')
        export.clicked.connect(self._export)
        head.actions.addWidget(export)
        lay.addWidget(head)
        if self.svc.paused:
            lay.addWidget(label('1.x 正在執行：這裡只能檢視，修改紀錄請等 1.x 關閉後再做。', 'warn'))
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜尋檔名或分組')
        self.search.textChanged.connect(lambda *_: self._fill())
        bar.addWidget(self.search, 1)
        self.group = QComboBox()
        self.group.setMinimumWidth(150)
        self.group.currentIndexChanged.connect(lambda *_: self._fill())
        bar.addWidget(self.group)
        self.sort = Segmented(works.SORTS, self.s.get('works.sort', 'recent'))
        self.sort.changed.connect(self._sort_changed)
        bar.addWidget(self.sort)
        lay.addLayout(bar)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(8)
        lw = QWidget()
        lw.setLayout(self.list_box)
        body.addWidget(lw, 3)
        self.detail = Card('')
        self.detail.setMinimumWidth(360)
        body.addWidget(self.detail, 2, Qt.AlignTop)
        lay.addLayout(body)
        lay.addStretch(1)
        self._load()

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

    def _fill(self):
        _clear(self.list_box)
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
        sel = r['key'] == self.selected
        w.setStyleSheet(f"QFrame#wrow{{background:{theme.ACCENT_SOFT if sel else theme.CARD};"
                        f"border:1px solid {theme.ACCENT_BORDER if sel else theme.BORDER};border-radius:12px;}}"
                        f"QFrame#wrow:hover{{background:{theme.SURFACE2};}}")
        w.clicked.connect(lambda k=r['key']: self._show(k))
        row = QHBoxLayout(w)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)
        tile = QLabel()
        tile.setPixmap(icon('file', theme.ACCENT_TEXT, 18).pixmap(18, 18))
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
        pb.setFixedWidth(90)
        pb.setToolTip(f"動筆效率 {int(r['eff'] * 100)}%（動筆 / 開啟）")
        right.addWidget(pb, 0, Qt.AlignRight)
        row.addLayout(right)
        return w

    def _empty_detail(self):
        _clear(self.detail.lay)
        self.detail.lay.addWidget(label('選一個作品看詳細資料。', 'muted'))

    def _show(self, key):
        r = next((x for x in self.rows if x['key'] == key), None)
        if r is None:
            self._empty_detail()
            return
        prev, self.selected = self.selected, key
        if prev != key:
            self._fill()
        lay = self.detail.lay
        _clear(lay)
        editable = not self.svc.paused and self.svc.tracker is not None
        lay.addWidget(label(r['name'], 'h2'))
        lay.addWidget(label(key, 'caption'))
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
                b.setStyleSheet('QPushButton{padding:5px 10px;border-radius:14px;font-size:12px;}'
                                f'QPushButton:checked{{background:{theme.ACCENT_SOFT};color:{theme.ACCENT_TEXT};'
                                f'border:1px solid {theme.ACCENT_BORDER};}}')
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
            self._delete_row(lay, key)
        lay.addStretch(1)

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
            self.svc.tracker.add_alias(key, target)
        except Exception as e:
            self.ctl.say(f'無法合併：{e}')
            return
        self.ctl.say(f"已把「{key.split(' _ ')[-1]}」合併到「{target.split(' _ ')[-1]}」。", important=False)
        self.selected = target
        self._load()

    def _delete(self, key):
        self.svc.tracker.delete_file(key)
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
TARGETS = [('canvas', '只錄畫布（建議）'), ('canvas_float', '畫布（自動開隱藏浮動視窗）'), ('window', '整個 SAI2 視窗'),
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
        lay.addWidget(PageHeader('工具', '縮時錄影會在背景錄下你畫圖的過程，畫完自動合成影片'))

        rec = Card('縮時錄影', '只在動筆時擷取，停筆就暫停；所有檔案關閉時自動合成影片')
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
        g.row('錄製範圍', '', self._combo('timelapse.target', TARGETS))
        g.row('畫質', '無損會佔用較多硬碟空間', self._combo('timelapse.quality', QUALITIES))
        g.row('影片 FPS', '', self._combo('timelapse.fps', [(24, '24'), (30, '30'), (60, '60')], int))
        folder = QWidget()
        fr = QHBoxLayout(folder)
        fr.setContentsMargins(0, 0, 0, 0)
        ed = QLineEdit(self.s.get('timelapse.output_dir', '') or '')
        ed.setPlaceholderText(self.s.videos_dir)
        ed.setMinimumWidth(320)
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

        later = Card('筆刷工坊、液化', '這兩個功能會在 2.x 重新設計；目前請繼續使用 1.x')
        later.lay.addWidget(label('同時開著 1.x 時，2.0 會自動暫停記錄，避免兩邊重複計時；關閉 1.x 後就會繼續。', 'caption'))
        lay.addWidget(later)
        lay.addStretch(1)
        self.refresh()

    def _combo(self, key, options, cast=str):
        cb = QComboBox()
        for v, text in options:
            cb.addItem(text, v)
        cur = self.s.get(key)
        cb.setCurrentIndex(max(0, cb.findData(cast(cur) if cur is not None else options[0][0])))
        cb.setMinimumWidth(220)
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

    def _open_videos(self):
        os.makedirs(self.s.videos_dir, exist_ok=True)
        os.startfile(self.s.videos_dir)

    def _toggle(self, on):
        self.ctl.set_recording(on)
        self.refresh()

    def refresh(self):
        from core.timelapse import find_ffmpeg
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
