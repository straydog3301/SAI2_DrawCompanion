# -*- coding: utf-8 -*-
"""
主視窗（需要時才開）：控制中心與設定合在同一個視窗，左側欄切換。
- 練習區：今日、練習（課程、成長、作品、工具在第三階段加入）
- 設定區：一般、寵物、參考圖來源、快捷鍵
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from core import data_text as DT
from core import growth, pet_pack, sketch_source as SK
from core.daily_quests import MODES
from ui2 import theme, winutil
from ui2.pet_window import to_pixmap
from ui2.quick_panel import QuestList
from ui2.widgets import Card, Chip, NavButton, PageHeader, ProgressBar, StatTile, button, label

LATER = '即將推出'
NAV_MAIN = [('今日', 'home', ''), ('練習', 'sketch', ''), ('課程', 'study', ''), ('成長', 'flame', ''),
            ('作品', 'works', ''), ('工具', 'record', '')]
NAV_SETTINGS = [('一般', 'settings'), ('寵物', 'play'), ('快捷面板', 'canvas'), ('每日任務', 'check'), ('規則', 'refresh'),
                ('外觀', 'opacity'), ('參考圖來源', 'image'), ('快捷鍵', 'grid')]
SETTINGS_ALIASES = {'設定': '一般'}
CONTENT_MAX_W = 1080


def _fmt_min(sec: float) -> str:
    m = int(sec // 60)
    return f'{m // 60} 時 {m % 60} 分' if m >= 60 else f'{m} 分'


class WeekBars(QWidget):
    def __init__(self, days):
        super().__init__()
        self.setMinimumHeight(130)
        self.days = days

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.days:
            return
        top = max([s for _d, s in self.days] + [60 * 60])
        cw = self.width() / len(self.days)
        today = datetime.now().strftime('%Y-%m-%d')
        f = p.font()
        f.setPixelSize(11)
        p.setFont(f)
        for i, (d, sec) in enumerate(self.days):
            h = max(6, int((self.height() - 26) * sec / top))
            bw = min(28, cw * 0.5)
            x = int(i * cw + cw / 2 - bw / 2)
            color = theme.ACCENT if d == today else (theme.BAR if sec > 0 else theme.TRACK)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRect(x, self.height() - 22 - h, int(bw), h), 6, 6)
            p.setPen(QColor(theme.TEXT if d == today else theme.MUTED))
            p.drawText(QRect(int(i * cw), self.height() - 18, int(cw), 18), Qt.AlignCenter,
                       '今天' if d == today else '一二三四五六日'[i])


class MainWindow(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.setObjectName('window')
        self.setWindowTitle('DrawCompanion')
        self.resize(1180, 760)
        self.setMinimumSize(900, 560)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.pages: dict[str, QWidget] = {}
        self.page_index: dict[str, int] = {}
        for name in [n for n, _i, _b in NAV_MAIN] + [n for n, _i in NAV_SETTINGS]:
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.viewport().setObjectName('vp')
            sc.viewport().setStyleSheet(f'QWidget#vp{{background:{theme.BG};}}')
            holder = QWidget()
            holder.setObjectName('page')
            outer = QHBoxLayout(holder)
            outer.setContentsMargins(40, 36, 40, 40)
            inner = QWidget()
            inner.setObjectName('page')
            inner.setMaximumWidth(CONTENT_MAX_W)
            outer.addWidget(inner)
            sc.setWidget(holder)
            self.page_index[name] = self.stack.addWidget(sc)
            self.pages[name] = inner
        self._built: set[str] = set()
        self.current = None
        self._timer = QTimer(self, interval=5000, timeout=self._live)
        from PySide6.QtGui import QKeySequence, QShortcut
        for seq, step in (('Ctrl+Tab', 1), ('Ctrl+Shift+Tab', -1), ('Ctrl+PgDown', 1), ('Ctrl+PgUp', -1)):
            QShortcut(QKeySequence(seq), self, activated=lambda s=step: self.cycle_page(s))

    # ── 側欄 ──
    def _sidebar(self) -> QWidget:
        outer = QWidget()
        outer.setObjectName('sidebar')
        outer.setFixedWidth(236)
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.viewport().setObjectName('svp')
        sc.viewport().setStyleSheet(f'QWidget#svp{{background:{theme.SIDEBAR};}}')
        side = QWidget()
        side.setObjectName('svp')
        side.setStyleSheet(f'QWidget#svp{{background:{theme.SIDEBAR};}}')
        sc.setWidget(side)
        ol.addWidget(sc, 1)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 20, 14, 16)
        lay.setSpacing(4)
        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 14)
        logo = QLabel()
        pack = getattr(self.ctl, '_pack', None)
        if pack is None or pack.builtin:
            pack = pet_pack.builtin_pack(self.ctl.pet_tint() if hasattr(self.ctl, 'pet_tint') else None)
        try:
            img = pack.frames('idle', 72)[0][0]           # 側欄圖示用目前的角色（內建角色會跟隨主題色）
        except Exception:
            img = pet_pack.builtin_pack().frames('idle', 72)[0][0]
        pm = to_pixmap(img)
        pm.setDevicePixelRatio(2)
        logo.setPixmap(pm)
        brand.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label('DrawCompanion', 'h2', wrap=False))
        col.addWidget(label('2.0 開發版', 'caption', wrap=False))
        brand.addLayout(col, 1)
        lay.addLayout(brand)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav: dict[str, NavButton] = {}
        for name, ic, badge in NAV_MAIN:
            self._add_nav(lay, name, ic, badge)
        lay.addSpacing(14)
        lay.addWidget(label('設定', 'section'))
        lay.addSpacing(4)
        for name, ic in NAV_SETTINGS:
            self._add_nav(lay, name, ic, '')
        lay.addStretch(1)
        self.status_chip = Chip('', 'neutral')
        self.status_chip.setWordWrap(True)
        foot = QVBoxLayout()
        foot.setContentsMargins(14, 8, 14, 14)
        foot.addWidget(self.status_chip)
        ol.addLayout(foot)
        return outer

    def _add_nav(self, lay, name, ic, badge):
        b = NavButton(f'  {name}', ic, badge)
        b.setAccessibleName(name)
        b.installEventFilter(self)                   # 上下鍵在側欄移動
        b.clicked.connect(lambda _=False, n=name: self.show_page(n))
        self.nav_group.addButton(b)
        self.nav[name] = b
        lay.addWidget(b)

    def _nav_order(self) -> list[str]:
        return [n for n in self.page_index if self.nav[n].isEnabled()]

    def cycle_page(self, step: int, focus_nav: bool = False):
        order = self._nav_order()
        i = order.index(self.current) if self.current in order else 0
        name = order[(i + step) % len(order)]
        self.show_page(name)
        if focus_nav:
            self.nav[name].setFocus(Qt.TabFocusReason)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.KeyPress and isinstance(obj, NavButton) and ev.key() in (Qt.Key_Up, Qt.Key_Down):
            self.cycle_page(-1 if ev.key() == Qt.Key_Up else 1, focus_nav=True)
            return True
        return super().eventFilter(obj, ev)

    def _update_status_chip(self):
        st = self.ctl.last_status
        if st is None:
            text, kind = '啟動中…', 'neutral'
        elif not st.tracking:
            text, kind = '1.x 執行中，暫停記錄', 'warn'
        elif st.sai2_running:
            text, kind = ('● SAI2 動筆中' if st.drawing else '● SAI2 已連線'), 'ok'
        else:
            text, kind = '○ SAI2 未開啟', 'neutral'
        self.status_chip.setText(text)
        self.status_chip.setProperty('chip', kind)
        self.status_chip.style().unpolish(self.status_chip)
        self.status_chip.style().polish(self.status_chip)

    # ── 換頁 ──
    def show_page(self, name='今日'):
        if not isinstance(name, str):
            name = '今日'
        name = SETTINGS_ALIASES.get(name, name)
        if name not in self.page_index:
            name = '今日'
        self.current = name
        self.nav[name].setChecked(True)
        self._build(name)
        self.stack.setCurrentIndex(self.page_index[name])
        self._update_status_chip()
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        self._timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        self.apply_frame()

    def apply_frame(self):
        """視窗外框用主色、標題列用側欄底色，讓主題色在視窗邊緣就看得到"""
        hwnd = winutil.hwnd_of(self)
        winutil.set_dark_titlebar(hwnd, not theme.IS_LIGHT)
        winutil.set_frame_colors(hwnd, border=theme.ACCENT, caption=theme.SIDEBAR, text=theme.TEXT)

    def _build(self, name):
        dynamic = name in ('今日', '練習', '課程', '成長', '作品', '工具')
        if name in self._built and not dynamic:
            return
        holder = self.pages[name]
        old = holder.layout()
        if old is not None:
            QWidget().setLayout(old)          # 舊版面連同子元件移走丟棄
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        from ui2 import pages_more as PM, quests_page as QP, settings_pages as SP
        builders = {'今日': self._today, '練習': self._practice,
                    '課程': lambda l: l.addWidget(PM.CoursesPage(self.ctl)),
                    '成長': lambda l: l.addWidget(PM.GrowthPage(self.ctl)),
                    '作品': lambda l: l.addWidget(PM.WorksPage(self.ctl)),
                    '工具': lambda l: l.addWidget(self._tools_page(PM)),
                    '一般': lambda l: l.addWidget(SP.general_page(self.ctl)),
                    '寵物': lambda l: l.addWidget(SP.PetPage(self.ctl)),
                    '快捷面板': lambda l: l.addWidget(SP.PanelPage(self.ctl)),
                    '每日任務': lambda l: l.addWidget(QP.QuestsPage(self.ctl)),
                    '規則': lambda l: l.addWidget(SP.RulesPage(self.ctl)),
                    '外觀': lambda l: l.addWidget(SP.appearance_page(self.ctl)),
                    '參考圖來源': lambda l: l.addWidget(SP.sources_page(self.ctl)),
                    '快捷鍵': lambda l: l.addWidget(SP.HotkeysPage(self.ctl))}
        builders.get(name, lambda l: l.addWidget(label(LATER, 'muted')))(lay)
        self._built.add(name)

    def _tools_page(self, PM):
        self.tools_page = PM.ToolsPage(self.ctl)
        return self.tools_page

    def page_widget(self, name: str, cls_name: str):
        """測試與其他元件取得某頁的主要元件"""
        return next((w for w in self.pages[name].findChildren(QWidget) if type(w).__name__ == cls_name), None)

    def _live(self):
        if not self.isVisible():
            self._timer.stop()
            return
        self._update_status_chip()
        if self.current == '今日' and getattr(self, '_status_card', None) is not None:
            self._fill_status()
        if self.current == '工具' and getattr(self, 'tools_page', None) is not None:
            try:
                self.tools_page.refresh()
            except RuntimeError:
                self.tools_page = None

    def closeEvent(self, e):
        self._timer.stop()
        super().closeEvent(e)

    # ── 今日 ──
    def _today(self, lay):
        svc = self.ctl.service
        q = svc.quests
        st = self.ctl.last_status
        hour = datetime.now().hour
        hello = '早安' if hour < 11 else ('午安' if hour < 18 else '晚安')
        week = '一二三四五六日'[datetime.now().weekday()]
        head = PageHeader(f'{hello}！', datetime.now().strftime(f'%m 月 %d 日・星期{week}'))
        if q is not None:
            key = q.day_key()
            if q.is_rest(key):
                b = button('取消今天請假', ic='close')
                b.clicked.connect(lambda: (q.cancel_rest(key), q.save(force=True), self._rebuild('今日')))
            else:
                b = button('今天請假', ic='hide', tip=f'連續天數不中斷；每週可請 {q.rest_quota()} 天')
                b.clicked.connect(lambda: self._take_rest(key))
            head.actions.addWidget(b)
        lay.addWidget(head)
        if svc.paused:
            lay.addWidget(label('偵測到 1.x 正在執行，2.0 暫停記錄。關閉 1.x 後會自動繼續。', 'warn'))

        # 數字
        tiles = QHBoxLayout()
        tiles.setSpacing(16)
        budget = int(st.budget_minutes) if st else 60
        today_min = int((st.today_draw if st else 0) // 60)
        tasks = svc.today_tasks()
        done = sum(1 for t in tasks if t['status'] == 'done')
        week_days = svc.week_draw()
        t1 = StatTile('今天動筆', f'{today_min} 分', f'目標 {budget} 分', 'open_sai2')
        bar = ProgressBar(today_min / max(1, budget))
        t1.layout().addWidget(bar)
        tiles.addWidget(t1)
        done_ratio = done / max(1, len(tasks))
        for cap, val, sub, ic, ratio in (('連續天數', f'{st.streak if st else 0} 天', '請假不會中斷', 'flame', None),
                                         ('今日任務', f'{done} / {len(tasks)}', '已打卡 / 全部', 'check', done_ratio),
                                         ('本週動筆', _fmt_min(sum(s for _d, s in week_days)), '週一到今天', 'record', None)):
            tile = StatTile(cap, val, sub, ic)
            if ratio is None:
                spacer = QWidget()
                spacer.setFixedHeight(6)        # 與有進度條的卡片等高
                tile.layout().addWidget(spacer)
            else:
                tile.layout().addWidget(ProgressBar(ratio, theme.SUCCESS))
            tiles.addWidget(tile)
        lay.addLayout(tiles)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        tasks_card = Card('今日任務', '先熱身、再主練，最後補弱項')
        add = button('加入任務', 'ghost', ic='canvas')
        tasks_card.head.addWidget(add)
        ql = QuestList(self.ctl, show_section=False)
        add.clicked.connect(lambda: self._add_menu(add, ql))
        tasks_card.lay.addWidget(ql)
        tasks_card.lay.addStretch(1)
        grid.addWidget(tasks_card, 0, 0, 2, 1)

        self._status_card = Card('SAI2')
        self._status_box = QVBoxLayout()
        self._status_box.setSpacing(8)
        self._status_card.lay.addLayout(self._status_box)
        self._fill_status()
        grid.addWidget(self._status_card, 0, 1)

        quick = Card('快速開始')
        qs = QGridLayout()
        qs.setSpacing(8)
        for i, (key, text, ic) in enumerate((('sketch', '速寫', 'sketch'), ('study', '臨摹研究', 'study'),
                                             ('open_sai2', '開啟 SAI2', 'open_sai2'), ('snapshot', '畫布快照', 'snapshot'))):
            b = button(text, ic=ic)
            b.setMinimumHeight(44)
            b.clicked.connect(lambda _=False, k=key: self.ctl.run_slot(k))
            qs.addWidget(b, i // 2, i % 2)
        quick.lay.addLayout(qs)
        grid.addWidget(quick, 1, 1)

        week_card = Card('本週動筆', '每天在 SAI2 實際下筆的時間')
        week_card.lay.addWidget(WeekBars(week_days))
        grid.addWidget(week_card, 2, 0)

        skill_card = Card('技能動態', '近 30 天投入與太久沒練的技能')
        if q is not None:
            cards = growth.skill_cards(q)
            active = sorted([c for c in cards if c['recent_seconds'] > 0], key=lambda c: -c['recent_seconds'])[:3]
            top = max([c['recent_seconds'] for c in active] + [1])
            for c in active:
                row = QHBoxLayout()
                row.addWidget(label(c['name'], 'body', wrap=False))
                row.addStretch(1)
                row.addWidget(label(growth.fmt_hours(c['recent_seconds']), 'caption', wrap=False))
                skill_card.lay.addLayout(row)
                skill_card.lay.addWidget(ProgressBar(c['recent_seconds'] / top, height=4))
            for c in [c for c in cards if c['idle'] and c['idle_days'] is not None][:2]:
                row = QHBoxLayout()
                row.addWidget(label(c['name'], 'body', wrap=False))
                row.addStretch(1)
                row.addWidget(Chip(f"{c['idle_days']} 天沒練", 'warn'))
                skill_card.lay.addLayout(row)
            if not active and not any(c['idle'] and c['idle_days'] is not None for c in cards):
                skill_card.lay.addWidget(label('打卡後這裡會顯示各技能的投入。', 'muted'))
        skill_card.lay.addStretch(1)
        grid.addWidget(skill_card, 2, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        lay.addLayout(grid)
        lay.addStretch(1)

    def _fill_status(self):
        box = self._status_box
        while box.count():
            it = box.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
            elif it.layout():
                while it.layout().count():
                    x = it.layout().takeAt(0).widget()
                    if x:
                        x.deleteLater()
        st = self.ctl.last_status
        if st is None or not st.tracking:
            box.addWidget(Chip('暫停記錄（1.x 執行中）' if st else '啟動中…', 'warn'))
            return
        if not st.sai2_running:
            box.addWidget(Chip('○ 未開啟', 'neutral'), 0, Qt.AlignLeft)
            box.addWidget(label('開啟 SAI2 後會自動開始記錄。', 'muted'))
            return
        box.addWidget(Chip('● 動筆中' if st.drawing else '● 已連線', 'ok' if st.drawing else 'accent'), 0, Qt.AlignLeft)
        name = (st.current_file or st.unsaved_file or '').split(' _ ')[-1]
        if name:
            box.addWidget(label(name, 'h2'))
        if st.unsaved_file:
            box.addWidget(label('這張畫布還沒存檔，存檔後才會記錄時間', 'warn'))
        box.addWidget(label(f'本次動筆 {_fmt_min(st.session_draw)}　今天 {_fmt_min(st.today_draw)}', 'caption'))

    def on_tracking_changed(self):
        """1.x 開啟 / 關閉：每日任務頁的唯讀狀態跟著更新（顯示中就重建，否則下次打開時重建）"""
        if self.current == '每日任務':
            self._rebuild('每日任務')
        else:
            self._built.discard('每日任務')

    def _rebuild(self, name):
        self._built.discard(name)
        self._build(name)

    def _take_rest(self, key):
        q = self.ctl.service.quests
        err = q.take_rest(key)
        if err:
            self.ctl.say(err)
        else:
            q.save(force=True)
            self.ctl.say('今天請假，好好休息！連續天數不會中斷。')
        self._rebuild('今日')

    def _add_menu(self, btn, ql):
        q = self.ctl.service.quests
        m = QMenu(self)
        for tpl in q.addable_templates():
            mode = MODES.get(tpl['mode'], {})
            m.addAction(f"{DT.template_name(tpl)}　（{DT.mode_name(tpl['mode'])}）",
                        lambda tid=tpl['id']: (q.add_today(tid), q.save(force=True), ql.refresh()))
        if m.isEmpty():
            m.addAction('沒有可加入的任務').setEnabled(False)
        m.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    # ── 練習 ──
    def _practice(self, lay):
        lay.addWidget(PageHeader('練習', '不一定要從每日任務開始：在這裡自選練習，時間一樣會記入技能'))
        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(self._sketch_card(), 3)
        top.addWidget(self._log_card(), 2)
        lay.addLayout(top)
        lay.addWidget(label('臨摹研究・學習路徑', 'section'))
        grid = QGridLayout()
        grid.setSpacing(16)
        q = self.ctl.service.quests
        i = 0
        for sk in (q.data['skills'] if q else []):
            prog = growth.path_progress(q, sk['id'])
            if not prog:
                continue
            grid.addWidget(self._path_card(sk, prog), i // 3, i % 3)
            i += 1
        lay.addLayout(grid)
        lay.addWidget(label('「練這一課」會加入今天的任務並開啟參考小窗；自評 3 分以上進入下一課。', 'caption'))
        lay.addStretch(1)

    def _path_card(self, sk, prog):
        c = Card(padding=18, spacing=8)
        c.lay.addWidget(label(DT.skill_name(sk), 'h2'))
        if prog['completed']:
            c.lay.addWidget(Chip('全部完成', 'ok'), 0, Qt.AlignLeft)
        else:
            c.lay.addWidget(label(f"Lv{prog['current_level']}　{prog['current_name']}", 'muted'))
        c.lay.addWidget(ProgressBar(prog['passed'] / max(1, prog['total']), height=4))
        row = QHBoxLayout()
        row.addWidget(label(f"{prog['passed']} / {prog['total']} 課", 'caption', wrap=False))
        row.addStretch(1)
        b = button('練這一課', 'link', ic='play')
        b.clicked.connect(lambda _=False, sid=sk['id']: self._study_path(sid))
        row.addWidget(b)
        c.lay.addLayout(row)
        return c

    def _sketch_card(self):
        card = Card('速寫', '倒數自然歸零才算一張；題目與間隔會記住')
        s = self.ctl.settings
        opts = s.sketch_opts()
        src = QComboBox()
        for k, text in SK.SOURCES:
            src.addItem(text, k)
        src.setCurrentIndex(max(0, src.findData(opts.get('source', 'local'))))
        topic = QComboBox()
        interval = QComboBox()
        for text, secs in SK.INTERVALS:
            interval.addItem(text, secs)
        interval.setCurrentIndex(max(0, interval.findData(int(opts.get('interval', 60)))))
        gray = QCheckBox('灰階顯示')
        gray.setChecked(bool(opts.get('grayscale')))
        note = label('', 'warn')

        def fill_topics():
            topic.clear()
            if src.currentData() == 'local':
                topic.addItem('全部', '')
                for sub in SK.local_subdirs(s.get('sources.local_dir', '')):
                    topic.addItem(sub, sub)
                topic.setCurrentIndex(max(0, topic.findData(s.get('sketch.local_category', ''))))
                note.setText('' if s.get('sources.local_dir') else '還沒有設定本機參考圖資料夾')
            else:
                for k, text, _q in SK.CATEGORIES:
                    if k != 'custom':
                        topic.addItem(text, k)
                topic.setCurrentIndex(max(0, topic.findData(s.get('sketch.category', 'pose'))))
                note.setText('' if s.get(f'sources.{src.currentData()}_key') else f'還沒有填 {src.currentText()} 金鑰')
            note.setVisible(bool(note.text()))
        fill_topics()
        src.currentIndexChanged.connect(lambda *_: fill_topics())
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        for col, (text, w) in enumerate((('圖源', src), ('題目', topic), ('間隔', interval))):
            form.addWidget(label(text, 'caption'), 0, col)
            form.addWidget(w, 1, col)
        card.lay.addLayout(form)
        card.lay.addWidget(gray)
        card.lay.addWidget(note)
        row = QHBoxLayout()
        setup = button('圖源設定', 'ghost', ic='settings')
        setup.clicked.connect(lambda: self.show_page('參考圖來源'))
        go = button('開始速寫', 'primary', ic='play')

        def start():
            s.set('sketch.source', src.currentData())
            if src.currentData() == 'local':
                s.set('sketch.local_category', topic.currentData() or '')
            else:
                s.set('sketch.category', topic.currentData())
            s.set('sketch.interval', interval.currentData())
            s.set('sketch.grayscale', gray.isChecked())
            s.save()
            self.ctl.open_ref('sketch', None)
        go.clicked.connect(start)
        row.addWidget(setup)
        row.addStretch(1)
        row.addWidget(go)
        card.lay.addLayout(row)
        return card

    def _study_path(self, skill):
        svc = self.ctl.service
        if svc.paused:
            self.ctl.say('1.x 正在執行，2.0 暫停記錄中。')
            return
        uid = svc.study_task_for_path(skill)
        if not uid:
            self.ctl.say('找不到這條學習路徑的任務範本。')
            return
        action, msg = svc.go(uid)
        if action == 'open_study':
            self.ctl.open_ref('study', uid)
            self.ctl.say(msg, important=False)

    def _log_card(self):
        card = Card('今天的練習')
        q = self.ctl.service.quests
        if q is None:
            return card
        detail = growth.day_detail(q, q.day_key())
        items = [t for t in detail['tasks'] if t['status'] in ('done', 'ready') or not t['progress'].startswith('0/')]
        for t in items[:6]:
            row = QHBoxLayout()
            row.addWidget(label(t['name'], 'body'), 1)
            if t['status'] == 'done':
                row.addWidget(Chip('已打卡' + (f"・{t['rating']} 分" if t['rating'] else ''), 'ok'))
            else:
                row.addWidget(label(t['progress'], 'caption', wrap=False))
            card.lay.addLayout(row)
        if not items:
            card.lay.addWidget(label('今天還沒有練習紀錄。', 'muted'))
        card.lay.addStretch(1)
        card.lay.addWidget(label(f"今天練習合計 {_fmt_min(detail['practice_seconds'])}", 'caption'))
        return card
