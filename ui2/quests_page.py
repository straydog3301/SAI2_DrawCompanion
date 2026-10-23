# -*- coding: utf-8 -*-
"""設定 → 每日任務：課表設定、任務範本（新增 / 編輯 / 停用 / 刪除）、自建技能（自 1.x 任務管理視窗移入）"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from core import sketch_source as SK, study_lessons
from core.daily_quests import MAX_TEMPLATE_NAME, MODES, SKETCH_ALLOWED_INTERVALS, est_minutes
from ui2 import theme
from ui2.widgets import Chip, PageHeader, Segmented, SettingGroup, Stepper, ToggleSwitch, button, label


def _drop(lay):
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif it.layout():
            _drop(it.layout())


def params_text(tpl: dict) -> str:
    p = tpl.get('params') or {}
    m = tpl['mode']
    if m == 'sketch':
        topic = p.get('topic', '')
        name = SK.category_label(topic) if not topic.startswith(('local:', 'kw:')) else topic.split(':', 1)[1] or '本機全部'
        return f"{name}・{p.get('count', 0)} 張 × {p.get('interval', 0)} 秒"
    if m == 'study':
        if p.get('path'):
            return '依學習路徑排課'
        return f"{p.get('minutes', 0)} 分"
    if m in ('drill', 'thumbnail'):
        return f"{p.get('count', 0)} {'張' if m == 'thumbnail' else '個'}・約 {p.get('est_minutes', 0)} 分"
    return f"{p.get('minutes', 0)} 分"


class QuestsPage(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.q = ctl.service.quests
        self.filter = 'all'
        self.editing = None            # 正在編輯的範本 id；'new' = 新增
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        head = PageHeader('每日任務', '課表怎麼排、有哪些任務範本，以及自己的技能分類')
        add = button('新增範本', 'primary', ic='canvas')
        add.clicked.connect(lambda: self._edit('new'))
        head.actions.addWidget(add)
        lay.addWidget(head)
        self.readonly = ctl.service.paused or self.q is None
        if self.readonly:
            lay.addWidget(label('1.x 正在執行：這裡只能檢視，修改請等 1.x 關閉後再做（避免兩邊同時改寫任務資料）。', 'warn'))
        if self.q is None:
            return
        lay.addWidget(self._schedule_group())
        self.editor_box = QVBoxLayout()
        lay.addLayout(self.editor_box)
        tpl_head = QHBoxLayout()
        tpl_head.addWidget(label('任務範本', 'section'))
        tpl_head.addStretch(1)
        seg = Segmented([('all', '全部')] + [(k, v['name']) for k, v in MODES.items()], 'all')
        seg.changed.connect(self._set_filter)
        tpl_head.addWidget(seg)
        lay.addLayout(tpl_head)
        self.tpl_group = SettingGroup()
        lay.addWidget(self.tpl_group)
        self.skill_group = SettingGroup('技能', '任務與作品標籤用的技能分類；內建技能不能刪除')
        lay.addWidget(self.skill_group)
        lay.addStretch(1)
        self._fill_templates()
        self._fill_skills()

    def _save(self):
        self.q.mark_dirty()
        self.q.save(force=True)

    # ── 課表 ──
    def _schedule_group(self):
        s = self.q.settings
        g = SettingGroup('課表')

        def toggle(key):
            t = ToggleSwitch(bool(s.get(key, True)))
            t.setEnabled(not self.readonly)
            t.toggled.connect(lambda v: (s.__setitem__(key, v), self._save()))
            return t

        def stepper(key, lo, hi, suffix, width=150):
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setSuffix(suffix)
            sp.setValue(int(s.get(key, lo)))
            sp.setEnabled(not self.readonly)
            sp.valueChanged.connect(lambda v: (s.__setitem__(key, v), self._clamp_counts(key), self._save()))
            return Stepper(sp, width)
        g.row('啟用每日任務', '關閉後快捷面板與今日頁不顯示任務', toggle('enabled'))
        g.row('每日練習時間', '抽任務時，預估時間的合計上限', stepper('budget_minutes', 10, 300, ' 分'))
        g.row('每天最少幾個任務', '', stepper('count_min', 1, 6, ' 個'))
        g.row('每天最多幾個任務', '', stepper('count_max', 1, 8, ' 個'))
        g.row('每天可以換幾次任務', '', stepper('rerolls_per_day', 0, 5, ' 次'))
        g.row('換日時間', '這個時間之前畫的算前一天（熬夜也不會斷）', stepper('reset_hour', 0, 23, ' 點'))
        g.row('每週可以請假', '請假日不會中斷連續天數', stepper('rest_days_per_week', 0, 3, ' 天'))
        g.row('打卡時擷取畫布快照', '作為作品紀錄，會出現在成長頁的單日明細', toggle('snapshot_on_checkin'))
        return g

    def _clamp_counts(self, key):
        s = self.q.settings
        if s.get('count_min', 1) > s.get('count_max', 3):
            if key == 'count_min':
                s['count_max'] = s['count_min']
            else:
                s['count_min'] = s['count_max']

    # ── 範本 ──
    def _set_filter(self, v):
        self.filter = v
        self._fill_templates()

    def _clear_group(self, g):
        _drop(g.inner)
        g._rows = 0

    def _fill_templates(self):
        g = self.tpl_group
        self._clear_group(g)
        tpls = [t for t in self.q.data['templates'] if self.filter == 'all' or t['mode'] == self.filter]
        if not tpls:
            empty = QWidget()
            el = QVBoxLayout(empty)
            el.setContentsMargins(18, 16, 18, 16)
            el.addWidget(label('這個分類還沒有範本。', 'muted'))
            g.add(empty)
        for t in tpls:
            g.add(self._tpl_row(t))

    def _tpl_row(self, t):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(14)
        on = ToggleSwitch(bool(t.get('enabled', True)))
        on.setEnabled(not self.readonly)
        on.setToolTip('停用的範本不會被排進課表')
        on.toggled.connect(lambda v, tid=t['id']: (self.q.set_template_enabled(tid, v), self._save()))
        lay.addWidget(on)
        col = QVBoxLayout()
        col.setSpacing(3)
        top = QHBoxLayout()
        top.addWidget(label(t['name'], 'body', wrap=False))
        top.addWidget(Chip(MODES[t['mode']]['name'], 'accent'))
        if not self.q.is_builtin_template(t['id']):
            top.addWidget(Chip('自訂', 'neutral'))
        top.addStretch(1)
        col.addLayout(top)
        sk = self.q.skill_label(t.get('skills') or {})
        col.addWidget(label('　·　'.join(x for x in (params_text(t), sk) if x), 'caption'))
        lay.addLayout(col, 1)
        edit = button('編輯', 'ghost')
        edit.setEnabled(not self.readonly)
        edit.clicked.connect(lambda _=False, tid=t['id']: self._edit(tid))
        lay.addWidget(edit)
        if not self.q.is_builtin_template(t['id']):
            delete = button('刪除', 'ghost')
            delete.setStyleSheet(f'color:{theme.DANGER};')
            delete.setEnabled(not self.readonly)
            confirm = button('確定', 'primary')
            confirm.setStyleSheet('background:#b91c1c;')
            confirm.hide()
            delete.clicked.connect(lambda: (delete.hide(), confirm.show()))
            confirm.clicked.connect(lambda _=False, tid=t['id']: self._delete(tid))
            lay.addWidget(delete)
            lay.addWidget(confirm)
        return w

    def _delete(self, tid):
        err = self.q.delete_template(tid)
        if err:
            self.ctl.say(err)
        else:
            self._save()
        self._fill_templates()

    # ── 範本編輯 ──
    def _edit(self, tid):
        if self.readonly:
            return
        self.editing = tid
        _drop(self.editor_box)
        tpl = (dict(self.q.template(tid)) if tid != 'new' else
               {'mode': 'drill', 'name': '', 'skills': {}, 'params': {'count': 10, 'est_minutes': 15}, 'weight': 1.0,
                'enabled': True})
        tpl['params'] = dict(tpl.get('params') or {})
        card = QFrame()
        card.setProperty('card', True)
        card.setStyleSheet(f'QFrame[card="true"]{{border:1px solid {theme.ACCENT_BORDER};}}')
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.setSpacing(12)
        cl.addWidget(label('新增範本' if tid == 'new' else f"編輯「{tpl['name']}」", 'h2'))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        name = QLineEdit(tpl['name'])
        name.setMaxLength(MAX_TEMPLATE_NAME)
        name.setPlaceholderText('例如「手部速寫 20 張」')
        mode = QComboBox()
        for k, v in MODES.items():
            mode.addItem(v['name'], k)
        mode.setCurrentIndex(max(0, mode.findData(tpl['mode'])))
        mode.setEnabled(tid == 'new')
        weight = QDoubleSpinBox()
        weight.setRange(0.1, 5.0)
        weight.setSingleStep(0.1)
        weight.setValue(float(tpl.get('weight', 1.0)))
        weight.setToolTip('數字越大，越常被排進課表')
        grid.addWidget(label('名稱', 'caption'), 0, 0)
        grid.addWidget(name, 0, 1, 1, 3)
        grid.addWidget(label('練習方式', 'caption'), 1, 0)
        grid.addWidget(mode, 1, 1)
        grid.addWidget(label('出現頻率', 'caption'), 1, 2)
        grid.addWidget(weight, 1, 3)
        cl.addLayout(grid)
        params_box = QGridLayout()
        params_box.setHorizontalSpacing(14)
        params_box.setVerticalSpacing(10)
        cl.addLayout(params_box)
        cl.addWidget(label('練到的技能', 'caption'))
        chips = QGridLayout()
        chips.setSpacing(6)
        skill_btns = []
        for i, sk in enumerate(self.q.data['skills']):
            b = QPushButton(sk['name'])
            b.setCheckable(True)
            b.setChecked(sk['id'] in (tpl.get('skills') or {}))
            b.setProperty('sid', sk['id'])
            b.setStyleSheet('QPushButton{padding:5px 10px;border-radius:14px;font-size:12px;}'
                            f'QPushButton:checked{{background:{theme.ACCENT_SOFT};color:{theme.ACCENT_TEXT};'
                            f'border:1px solid {theme.ACCENT_BORDER};}}')
            chips.addWidget(b, i // 4, i % 4)
            skill_btns.append(b)
        cl.addLayout(chips)
        err = label('', 'warn')
        err.hide()
        cl.addWidget(err)
        getters = {}

        def build_params():
            _drop(params_box)
            getters.clear()
            m = mode.currentData()
            p = tpl['params'] if m == tpl['mode'] else {}

            def spin(key, lo, hi, val, suffix, col):
                sp = QSpinBox()
                sp.setRange(lo, hi)
                sp.setValue(int(p.get(key, val)))
                sp.setSuffix(suffix)
                params_box.addWidget(label({'count': '數量', 'interval': '每張', 'minutes': '時間',
                                            'est_minutes': '預估時間'}[key], 'caption'), 0, col)
                params_box.addWidget(sp, 0, col + 1)
                getters[key] = sp.value
            if m == 'sketch':
                topic = QComboBox()
                for k, text, _q in SK.CATEGORIES:
                    if k != 'custom':
                        topic.addItem(text, k)
                for sub in SK.local_subdirs(self.ctl.settings.get('sources.local_dir', '')):
                    topic.addItem(f'本機：{sub}', f'local:{sub}')
                topic.addItem('本機全部', 'local:')
                cur = p.get('topic', 'pose')
                if topic.findData(cur) < 0:
                    topic.addItem(cur, cur)
                topic.setCurrentIndex(max(0, topic.findData(cur)))
                params_box.addWidget(label('題目', 'caption'), 0, 0)
                params_box.addWidget(topic, 0, 1)
                getters['topic'] = topic.currentData
                interval = QComboBox()
                for secs in SKETCH_ALLOWED_INTERVALS:
                    interval.addItem(f'{secs} 秒' if secs < 120 else f'{secs // 60} 分', secs)
                interval.setCurrentIndex(max(0, interval.findData(p.get('interval', 60))))
                params_box.addWidget(label('每張', 'caption'), 1, 0)
                params_box.addWidget(interval, 1, 1)
                getters['interval'] = interval.currentData
                cnt = QSpinBox()
                cnt.setRange(1, 200)
                cnt.setValue(int(p.get('count', 10)))
                cnt.setSuffix(' 張')
                params_box.addWidget(label('數量', 'caption'), 1, 2)
                params_box.addWidget(cnt, 1, 3)
                getters['count'] = cnt.value
            elif m == 'study':
                path = QComboBox()
                path.addItem('不用學習路徑（自選參考圖）', '')
                for sk in self.q.data['skills']:
                    if study_lessons.path(sk['id']):
                        path.addItem(f"學習路徑：{sk['name']}", sk['id'])
                path.setCurrentIndex(max(0, path.findData(p.get('path', ''))))
                params_box.addWidget(label('課程', 'caption'), 0, 0)
                params_box.addWidget(path, 0, 1)
                getters['path'] = path.currentData
                mins = QSpinBox()
                mins.setRange(5, 240)
                mins.setValue(int(p.get('minutes', 30)))
                mins.setSuffix(' 分')
                mins.setToolTip('有學習路徑時，時間依課程決定')
                params_box.addWidget(label('時間', 'caption'), 0, 2)
                params_box.addWidget(mins, 0, 3)
                getters['minutes'] = mins.value
            elif m in ('drill', 'thumbnail'):
                spin('count', 1, 999, 10, ' 張' if m == 'thumbnail' else ' 個', 0)
                spin('est_minutes', 1, 240, 15, ' 分', 2)
            else:
                spin('minutes', 5, 600, 30, ' 分', 0)
        build_params()
        mode.currentIndexChanged.connect(lambda _i: build_params())

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button('取消', 'ghost')
        cancel.clicked.connect(lambda: (_drop(self.editor_box), setattr(self, 'editing', None)))
        ok = button('儲存', 'primary')

        def save():
            chosen = [b.property('sid') for b in skill_btns if b.isChecked()]
            new = {'mode': mode.currentData(), 'name': name.text().strip(), 'weight': weight.value(),
                   'enabled': tpl.get('enabled', True),
                   'skills': {sid: round(1.0 / len(chosen), 4) for sid in chosen} if chosen else {},
                   'params': {k: g() for k, g in getters.items()}}
            if new['mode'] == 'study' and new['params'].get('path'):
                new['params'].pop('minutes', None)
            if tid == 'new':
                _new_id, e = self.q.add_template(new)
            else:
                e = self.q.update_template(tid, new)
            if e:
                err.setText(e)
                err.show()
                return
            self._save()
            _drop(self.editor_box)
            self.editing = None
            self.ctl.say(f"已儲存「{new['name']}」（約 {est_minutes(new):.0f} 分）。", important=False)
            self._fill_templates()
        ok.clicked.connect(save)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        cl.addLayout(btns)
        self.editor_box.addWidget(card)

    # ── 技能 ──
    def _fill_skills(self):
        g = self.skill_group
        self._clear_group(g)
        for sk in self.q.data['skills']:
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(18, 10, 18, 10)
            lay.addWidget(label(f"{sk.get('icon', '')} {sk['name']}", 'body', wrap=False))
            if sk.get('builtin', True) and not sk['id'].startswith('u_'):
                lay.addWidget(Chip('內建', 'neutral'))
            lay.addStretch(1)
            if sk['id'].startswith('u_'):
                delete = button('刪除', 'ghost')
                delete.setStyleSheet(f'color:{theme.DANGER};')
                delete.setEnabled(not self.readonly)
                delete.clicked.connect(lambda _=False, sid=sk['id']: self._delete_skill(sid))
                lay.addWidget(delete)
            g.add(w)
        add = QWidget()
        al = QHBoxLayout(add)
        al.setContentsMargins(18, 12, 18, 12)
        ic = QLineEdit()
        ic.setPlaceholderText('圖示')
        ic.setMaxLength(2)
        ic.setFixedWidth(70)
        nm = QLineEdit()
        nm.setPlaceholderText('新技能名稱（最多 12 字）')
        nm.setMaxLength(12)
        b = button('新增技能', 'ghost', ic='canvas')
        b.setEnabled(not self.readonly)
        b.clicked.connect(lambda: self._add_skill(nm.text(), ic.text()))
        al.addWidget(ic)
        al.addWidget(nm, 1)
        al.addWidget(b)
        g.add(add)

    def _add_skill(self, name, ic):
        _sid, err = self.q.add_skill(name, ic or '⭐')
        if err:
            self.ctl.say(err)
            return
        self._save()
        self._fill_skills()

    def _delete_skill(self, sid):
        err = self.q.delete_skill(sid)
        if err:
            self.ctl.say(err)
            return
        self._save()
        self._fill_skills()
