# -*- coding: utf-8 -*-
"""
quest_manager_window.py - 每日任務的範本與技能管理（Tk 介面，1.x 的簡單版本）

範本：清單檢視、新增 / 編輯 / 啟用切換 / 刪除（內建範本只能停用）。
技能：新增 / 刪除自建技能（內建技能不可刪）。規則與驗證都在 core/daily_quests.py。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from core import study_lessons
from core.daily_quests import MODES, est_minutes
from core.i18n import _tr
from ui_kit import px, fit_window

MODE_ORDER = ['sketch', 'study', 'drill', 'thumbnail', 'draw_time']


class QuestManagerWindow(tk.Toplevel):
    """app 需提供 quests、var_status、_quest_render；theme / btn 同成長頁；
    sketch_topics：[(key, 顯示名稱)]；sketch_intervals：[(顯示名稱, 秒數)]（不含「不限時」）"""

    def __init__(self, parent, app, theme: dict, btn, sketch_topics, sketch_intervals):
        super().__init__(parent)
        self.app, self.t, self.btn = app, theme, btn
        self.topics, self.intervals = sketch_topics, sketch_intervals
        t = theme
        self.title(_tr('ui.qm.title', '⚙ 每日任務管理'))
        self.configure(bg=t['BG'])

        bar = tk.Frame(self, bg=t['BG'])
        bar.pack(fill='x', padx=px(self, 12), pady=(px(self, 10), 0))
        self._pages = {}
        for key, title in (('templates', _tr('ui.qm.tab_templates', '📋 任務範本')),
                           ('skills', _tr('ui.qm.tab_skills', '🎨 技能'))):
            b = btn(bar, title, t['CARD2'], t['ACCH'], lambda k=key: self._show(k), font=t['FB'])
            b.pack(side='left', padx=(0, 4))
            self._pages[key] = {'btn': b}
        self.body = tk.Frame(self, bg=t['BG'])
        self.body.pack(fill='both', expand=True, padx=px(self, 12), pady=px(self, 10))
        self._pages['templates']['frame'] = self._build_templates()
        self._pages['skills']['frame'] = self._build_skills()
        self._show('templates')
        fit_window(self, 640, 520)

    # ── 共用 ──────────────────────────────────────────────────────────
    def _show(self, key):
        for k, p in self._pages.items():
            p['frame'].pack_forget()
            p['btn'].config(bg=self.t['ACCENT'] if k == key else self.t['CARD2'])
            p['btn']._bg = self.t['ACCENT'] if k == key else self.t['CARD2']
        self._pages[key]['frame'].pack(fill='both', expand=True)

    def _changed(self, msg: str = ''):
        q = self.app.quests
        q.save(force=True)
        try:
            self.app._quest_render(force=True)
        except Exception:
            pass
        if msg:
            self.app.var_status.set(msg)
        self._reload_templates()
        self._reload_skills()

    # ── 範本 ──────────────────────────────────────────────────────────
    def _build_templates(self):
        t = self.t
        f = tk.Frame(self.body, bg=t['BG'])
        cols = ('on', 'name', 'mode', 'skills', 'time')
        self.tree = ttk.Treeview(f, columns=cols, show='headings', selectmode='browse', height=14)
        for c, title, w in (('on', '啟用', 50), ('name', '名稱', 220), ('mode', '練習方式', 90),
                            ('skills', '技能', 140), ('time', '預估', 70)):
            self.tree.heading(c, text=_tr(f'ui.qm.col_{c}', title))
            self.tree.column(c, width=px(self, w), anchor='w' if c in ('name', 'skills') else 'center')
        sb = ttk.Scrollbar(f, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        btns = tk.Frame(f, bg=t['BG'])
        btns.pack(side='bottom', fill='x', pady=(px(self, 8), 0))
        sb.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda _e: self._edit())
        for text, cmd, color in ((_tr('ui.qm.add', '＋ 新增'), self._add, t['ACCENT']),
                                 (_tr('ui.qm.edit', '✎ 編輯'), self._edit, t['CARD2']),
                                 (_tr('ui.qm.toggle', '⏯ 啟用 / 停用'), self._toggle, t['CARD2']),
                                 (_tr('ui.qm.delete', '🗑 刪除'), self._delete, t['CARD2'])):
            self.btn(btns, text, color, t['ACCH'], cmd, font=t['FS']).pack(side='left', padx=(0, 4))
        tk.Label(btns, text=_tr('ui.qm.hint', '停用的範本不會被抽到；內建範本只能停用'), font=t['FS'],
                 fg=t['TEXTD'], bg=t['BG']).pack(side='right')
        self._reload_templates()
        return f

    def _reload_templates(self):
        q = self.app.quests
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for tpl in q.data['templates']:
            if tpl.get('mode') not in MODES:
                continue
            eff = q._effective(tpl)
            mode = MODES[tpl['mode']]
            name = tpl['name'] + ('' if q.is_builtin_template(tpl['id']) else '　（自訂）')
            self.tree.insert('', 'end', iid=tpl['id'], values=(
                '✓' if tpl.get('enabled') else '—', name, f"{mode['icon']} {mode['name']}",
                q.skill_label(tpl.get('skills') or {}) or '—', f'{int(round(est_minutes(eff)))} 分'))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])

    def _selected(self) -> str | None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(self.title(), _tr('ui.qm.pick', '請先選擇一個範本'), parent=self)
            return None
        return sel[0]

    def _add(self):
        TemplateEditor(self, None)

    def _edit(self):
        tid = self._selected()
        if tid:
            TemplateEditor(self, tid)

    def _toggle(self):
        tid = self._selected()
        if not tid:
            return
        tpl = self.app.quests.template(tid)
        self.app.quests.set_template_enabled(tid, not tpl.get('enabled'))
        self._changed()

    def _delete(self):
        tid = self._selected()
        if not tid:
            return
        tpl = self.app.quests.template(tid)
        if not messagebox.askyesno(self.title(), _tr('ui.qm.confirm_delete', '確定要刪除「{name}」？', name=tpl['name']),
                                   parent=self):
            return
        err = self.app.quests.delete_template(tid)
        if err:
            messagebox.showwarning(self.title(), err, parent=self)
            return
        self._changed(_tr('ui.qm.deleted', '已刪除範本「{name}」', name=tpl['name']))

    # ── 技能 ──────────────────────────────────────────────────────────
    def _build_skills(self):
        t = self.t
        f = tk.Frame(self.body, bg=t['BG'])
        self.skill_list = tk.Frame(f, bg=t['BG'])
        self.skill_list.pack(fill='both', expand=True)
        add = tk.Frame(f, bg=t['CARD'], padx=px(self, 10), pady=px(self, 8))
        add.pack(fill='x', pady=(px(self, 8), 0))
        tk.Label(add, text=_tr('ui.qm.new_skill', '新增技能：'), font=t['FB'], fg=t['TEXT'], bg=t['CARD']).pack(side='left')
        self.var_icon = tk.StringVar(value='⭐')
        tk.Entry(add, textvariable=self.var_icon, width=3, font=t['FB'], bg=t['CARD2'], fg=t['TEXT'],
                 insertbackground=t['TEXT'], relief='flat').pack(side='left', padx=(0, 4))
        self.var_skill = tk.StringVar()
        tk.Entry(add, textvariable=self.var_skill, width=16, font=t['FB'], bg=t['CARD2'], fg=t['TEXT'],
                 insertbackground=t['TEXT'], relief='flat').pack(side='left', padx=(0, 6))
        self.btn(add, _tr('ui.qm.add', '＋ 新增'), t['ACCENT'], t['ACCH'], self._add_skill, font=t['FS']).pack(side='left')
        self._reload_skills()
        return f

    def _reload_skills(self):
        t, q = self.t, self.app.quests
        for w in self.skill_list.winfo_children():
            w.destroy()
        for s in q.data['skills']:
            row = tk.Frame(self.skill_list, bg=t['CARD2'], padx=px(self, 10), pady=px(self, 4))
            row.pack(fill='x', pady=(0, 3))
            builtin = s.get('builtin', False)
            tk.Label(row, text=f"{s.get('icon', '')} {s['name']}", font=t['FB'], fg=t['TEXT'],
                     bg=t['CARD2']).pack(side='left')
            path = study_lessons.path(s['id'])
            info = _tr('ui.qm.builtin', '內建') if builtin else _tr('ui.qm.custom', '自訂')
            if path:
                info += f'　·　{len(path)} 堂課程'
            tk.Label(row, text=info, font=t['FS'], fg=t['TEXTD'], bg=t['CARD2']).pack(side='left', padx=8)
            if not builtin:
                self.btn(row, _tr('ui.qm.delete', '🗑 刪除'), t['CARD2'], t['ACCH'],
                         lambda sid=s['id']: self._delete_skill(sid), font=t['FS'], pady=0).pack(side='right')

    def _add_skill(self):
        sid, err = self.app.quests.add_skill(self.var_skill.get(), self.var_icon.get())
        if err:
            messagebox.showwarning(self.title(), err, parent=self)
            return
        self.var_skill.set('')
        self._changed(_tr('ui.qm.skill_added', '已新增技能「{name}」', name=self.app.quests.skill(sid)['name']))

    def _delete_skill(self, sid):
        err = self.app.quests.delete_skill(sid)
        if err:
            messagebox.showwarning(self.title(), err, parent=self)
            return
        self._changed()


class TemplateEditor(tk.Toplevel):
    """新增 / 編輯單一範本；欄位依練習方式切換"""

    def __init__(self, mgr: QuestManagerWindow, tid: str | None):
        super().__init__(mgr)
        self.mgr, self.tid = mgr, tid
        q, t = mgr.app.quests, mgr.t
        self.t = t
        tpl = q.template(tid) if tid else {'mode': 'sketch', 'name': '', 'skills': {}, 'weight': 1.0,
                                           'params': {'topic': mgr.topics[0][0], 'count': 10, 'interval': 60}}
        p = tpl.get('params', {})
        self.title(_tr('ui.qm.edit_title', '編輯範本') if tid else _tr('ui.qm.add_title', '新增範本'))
        self.configure(bg=t['CARD'], padx=px(self, 16), pady=px(self, 12))
        self.transient(mgr)

        def row(label):
            f = tk.Frame(self, bg=t['CARD'])
            f.pack(fill='x', pady=3)
            tk.Label(f, text=label, font=t['FB'], fg=t['TEXT'], bg=t['CARD'], width=10, anchor='w').pack(side='left')
            return f

        self.var_name = tk.StringVar(value=tpl.get('name', ''))
        tk.Entry(row(_tr('ui.qm.f_name', '名稱')), textvariable=self.var_name, font=t['FB'], bg=t['CARD2'], fg=t['TEXT'],
                 insertbackground=t['TEXT'], relief='flat', width=30).pack(side='left', fill='x', expand=True)

        self.mode_labels = {f"{MODES[m]['icon']} {MODES[m]['name']}": m for m in MODE_ORDER}
        self.var_mode = tk.StringVar(value=next(k for k, v in self.mode_labels.items() if v == tpl['mode']))
        cb = ttk.Combobox(row(_tr('ui.qm.f_mode', '練習方式')), textvariable=self.var_mode, state='readonly',
                          values=list(self.mode_labels), width=16, font=t['FB'])
        cb.pack(side='left')
        cb.bind('<<ComboboxSelected>>', lambda _e: self._show_params())

        sk = row(_tr('ui.qm.f_skills', '技能'))
        grid = tk.Frame(sk, bg=t['CARD'])
        grid.pack(side='left')
        self.skill_vars = {}
        for i, s in enumerate(q.data['skills']):
            v = tk.BooleanVar(value=s['id'] in (tpl.get('skills') or {}))
            self.skill_vars[s['id']] = v
            tk.Checkbutton(grid, text=f"{s.get('icon', '')}{s['name']}", variable=v, font=t['FS'], fg=t['TEXT'],
                           bg=t['CARD'], selectcolor=t['CARD2'], activebackground=t['CARD'],
                           activeforeground=t['TEXT']).grid(row=i // 3, column=i % 3, sticky='w')

        # 各練習方式的參數
        self.params = tk.Frame(self, bg=t['CARD'])
        self.params.pack(fill='x', pady=(6, 0))
        topic_val = p.get('topic', mgr.topics[0][0])
        self.topic_labels = {label: key for key, label in mgr.topics}
        is_kw = isinstance(topic_val, str) and topic_val.startswith('kw:')
        self.var_topic = tk.StringVar(value=_tr('ui.qm.custom_kw', '自訂關鍵字') if is_kw else
                                      next((l for l, k in self.topic_labels.items() if k == topic_val),
                                           list(self.topic_labels)[0]))
        self.var_kw = tk.StringVar(value=topic_val[3:] if is_kw else '')
        self.var_count = tk.IntVar(value=int(p.get('count', 10)))
        self.int_labels = {label: secs for label, secs in mgr.intervals}
        self.var_interval = tk.StringVar(value=next((l for l, s in self.int_labels.items() if s == p.get('interval')),
                                                    list(self.int_labels)[1]))
        self.path_labels = {_tr('ui.qm.no_path', '不使用（自訂分鐘數）'): ''}
        for s in q.data['skills']:
            if study_lessons.path(s['id']):
                self.path_labels[f"{s.get('icon', '')} {s['name']}（{len(study_lessons.path(s['id']))} 堂）"] = s['id']
        self.var_path = tk.StringVar(value=next((l for l, k in self.path_labels.items() if k == p.get('path', '')),
                                                list(self.path_labels)[0]))
        self.var_minutes = tk.IntVar(value=int(p.get('minutes', 30)))
        self.var_est = tk.IntVar(value=int(p.get('est_minutes', 15)))
        self.var_weight = tk.DoubleVar(value=float(tpl.get('weight', 1.0)))

        wrow = row(_tr('ui.qm.f_weight', '抽中權重'))
        tk.Spinbox(wrow, from_=0.1, to=5, increment=0.1, textvariable=self.var_weight, width=6, font=t['FB'],
                   **self._spin_style()).pack(side='left')
        tk.Label(wrow, text=_tr('ui.qm.weight_hint', '越大越常被抽到（1 = 一般）'), font=t['FS'], fg=t['TEXTD'],
                 bg=t['CARD']).pack(side='left', padx=6)

        btns = tk.Frame(self, bg=t['CARD'])
        btns.pack(fill='x', pady=(10, 0))
        mgr.btn(btns, _tr('dialog.btn_cancel', '取消'), t['CARD2'], t['BORDER'], self.destroy, font=t['FS']).pack(side='right')
        mgr.btn(btns, _tr('ui.qm.save', '💾 儲存'), t['ACCENT'], t['ACCH'], self._save, font=t['FS']).pack(side='right', padx=(0, 6))
        self._show_params()
        self.update_idletasks()
        self.geometry(f'+{mgr.winfo_rootx() + px(self, 40)}+{mgr.winfo_rooty() + px(self, 40)}')
        self.grab_set()

    def _spin_style(self) -> dict:
        t = self.t
        return {'bg': t['CARD2'], 'fg': t['TEXT'], 'buttonbackground': t['CARD2'], 'insertbackground': t['TEXT'],
                'relief': 'flat', 'highlightthickness': 0}

    def _mode(self) -> str:
        return self.mode_labels[self.var_mode.get()]

    def _show_params(self):
        t = self.t
        for w in self.params.winfo_children():
            w.destroy()
        mode = self._mode()

        def prow(label):
            f = tk.Frame(self.params, bg=t['CARD'])
            f.pack(fill='x', pady=3)
            tk.Label(f, text=label, font=t['FB'], fg=t['TEXT'], bg=t['CARD'], width=10, anchor='w').pack(side='left')
            return f

        def spin(parent, var, lo, hi):
            tk.Spinbox(parent, from_=lo, to=hi, textvariable=var, width=6, font=t['FB'],
                       **self._spin_style()).pack(side='left')

        if mode == 'sketch':
            f = prow(_tr('ui.qm.f_topic', '速寫題目'))
            values = list(self.topic_labels) + [_tr('ui.qm.custom_kw', '自訂關鍵字')]
            ttk.Combobox(f, textvariable=self.var_topic, values=values, state='readonly', width=14,
                         font=t['FB']).pack(side='left')
            tk.Entry(f, textvariable=self.var_kw, width=14, font=t['FB'], bg=t['CARD2'], fg=t['TEXT'],
                     insertbackground=t['TEXT'], relief='flat').pack(side='left', padx=6)
            spin(prow(_tr('ui.qm.f_count', '張數')), self.var_count, 1, 200)
            ttk.Combobox(prow(_tr('ui.qm.f_interval', '每張時間')), textvariable=self.var_interval, state='readonly',
                         values=list(self.int_labels), width=8, font=t['FB']).pack(side='left')
        elif mode == 'study':
            ttk.Combobox(prow(_tr('ui.qm.f_path', '學習路徑')), textvariable=self.var_path, state='readonly',
                         values=list(self.path_labels), width=24, font=t['FB']).pack(side='left')
            spin(prow(_tr('ui.qm.f_minutes', '分鐘（無路徑時）')), self.var_minutes, 5, 240)
        elif mode in ('drill', 'thumbnail'):
            spin(prow(_tr('ui.qm.f_count', '次數')), self.var_count, 1, 999)
            spin(prow(_tr('ui.qm.f_est', '預估分鐘')), self.var_est, 1, 240)
        else:
            spin(prow(_tr('ui.qm.f_minutes', '分鐘')), self.var_minutes, 5, 600)

    def _collect(self) -> dict:
        mode = self._mode()
        picked = [sid for sid, v in self.skill_vars.items() if v.get()]
        skills = {sid: round(1.0 / len(picked), 4) for sid in picked}

        def num(var, default):
            try:
                return var.get()
            except (tk.TclError, ValueError):
                return default
        if mode == 'sketch':
            label = self.var_topic.get()
            topic = 'kw:' + self.var_kw.get().strip() if label not in self.topic_labels else self.topic_labels[label]
            if topic == 'kw:':
                topic = ''
            params = {'topic': topic, 'count': num(self.var_count, 0), 'interval': self.int_labels.get(self.var_interval.get())}
        elif mode == 'study':
            path = self.path_labels.get(self.var_path.get(), '')
            params = {'path': path} if path else {'minutes': num(self.var_minutes, 0)}
            if path:
                params['minutes'] = num(self.var_minutes, 30)
        elif mode in ('drill', 'thumbnail'):
            params = {'count': num(self.var_count, 0), 'est_minutes': num(self.var_est, 0)}
        else:
            params = {'minutes': num(self.var_minutes, 0)}
        tpl = {'mode': mode, 'name': self.var_name.get(), 'skills': skills, 'params': params,
               'weight': num(self.var_weight, 1.0)}
        if self.tid:
            tpl['enabled'] = self.mgr.app.quests.template(self.tid).get('enabled', True)
        return tpl

    def _save(self):
        q = self.mgr.app.quests
        tpl = self._collect()
        if self.tid:
            err = q.update_template(self.tid, tpl)
        else:
            _tid, err = q.add_template(tpl)
        if err:
            messagebox.showwarning(self.title(), err, parent=self)
            return
        self.destroy()
        self.mgr._changed(_tr('ui.qm.saved', '已儲存範本「{name}」', name=tpl['name'].strip()))
