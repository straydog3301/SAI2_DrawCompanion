# -*- coding: utf-8 -*-
"""
growth_view.py - 主視窗「🎯 成長」頁籤（Tk 介面，1.x 的簡單版本）

顯示連續天數與休息日、月曆熱度圖、技能卡（里程碑、近期投入、14 天趨勢、課程進度、自評）。
所有數字來自 core/growth.py；這裡只負責畫面。配色沿用主視窗主題（由 theme 傳入）。
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime

from core import growth as G
from ui_kit import ScrollFrame, blend, px

WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']
STATUS_TEXT = {'done': '✓ 已打卡', 'ready': '可打卡', 'active': '未完成', 'expired': '已過期'}


class GrowthView(tk.Frame):
    """app 需提供：quests（QuestManager）、var_status、_quest_render；
    theme：主視窗的色彩與字型（BG/CARD/CARD2/TEXT/TEXTD/ACCENT/ACCH/GREEN/YELLOW/BORDER、FH/FB/FS/FT）；
    btn：主視窗的按鈕工廠 _btn；draw_seconds(days)：最近幾天的 SAI2 繪圖秒數。"""

    def __init__(self, parent, app, theme: dict, btn, draw_seconds=None):
        self.t = theme
        super().__init__(parent, bg=theme['BG'])
        self.app = app
        self.btn = btn
        self.draw_seconds = draw_seconds
        now = datetime.now()
        self.year, self.month = now.year, now.month
        self.scroll = ScrollFrame(self, bg=theme['BG'])
        self.scroll.pack(fill='both', expand=True)
        self.body = tk.Frame(self.scroll.inner, bg=theme['BG'])
        self.body.pack(fill='both', expand=True, padx=px(self, 14), pady=px(self, 10))

    # ── 共用 ──────────────────────────────────────────────────────────
    def _card(self, title: str | None = None) -> tk.Frame:
        t = self.t
        c = tk.Frame(self.body, bg=t['CARD'], highlightthickness=1, highlightbackground=t['BORDER'],
                     padx=px(self, 12), pady=px(self, 10))
        c.pack(fill='x', pady=(0, px(self, 8)))
        if title:
            tk.Label(c, text=title, font=t['FH'], fg=t['TEXT'], bg=t['CARD'], anchor='w').pack(fill='x')
        return c

    def _bar(self, parent, ratio: float, color: str, height: int = 6) -> tk.Canvas:
        c = tk.Canvas(parent, height=px(self, height), bg=self.t['BORDER'], highlightthickness=0)

        def draw(e, r=max(0.0, min(1.0, ratio))):
            c.delete('all')
            if r > 0:
                c.create_rectangle(0, 0, max(2, int(e.width * r)), e.height, fill=color, width=0)
        c.bind('<Configure>', draw)
        return c

    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        try:
            self._build_header()
            self._build_calendar()
            self._build_skills()
        except Exception as e:      # 統計出錯不應讓整個頁籤空白
            tk.Label(self.body, text=f'⚠ 成長資料讀取失敗：{e}', font=self.t['FB'], fg=self.t['YELLOW'],
                     bg=self.t['BG']).pack(anchor='w')
            print(f'[Growth] refresh error: {e}')

    # ── 連續天數與休息日 ──────────────────────────────────────────────
    def _build_header(self):
        t, q = self.t, self.app.quests
        c = self._card()
        top = tk.Frame(c, bg=t['CARD'])
        top.pack(fill='x')
        left = tk.Frame(top, bg=t['CARD'])
        left.pack(side='left', fill='x', expand=True)
        streak = q.streak()
        tk.Label(left, text=f'🔥 連續 {streak} 天', font=t['FT'], fg=t['YELLOW'] if streak else t['TEXT'],
                 bg=t['CARD'], anchor='w').pack(fill='x')
        parts = [f'最長 {q.longest_streak()} 天', f'近 30 天練習 {G.fmt_hours(self._recent_practice_seconds())}']
        if self.draw_seconds:
            try:
                parts.append(f'繪圖 {G.fmt_hours(self.draw_seconds(30))}')
            except Exception:
                pass
        tk.Label(left, text='　·　'.join(parts), font=t['FS'], fg=t['TEXTD'], bg=t['CARD'],
                 anchor='w').pack(fill='x', pady=(2, 0))

        right = tk.Frame(top, bg=t['CARD'])
        right.pack(side='right', anchor='n')
        today = q.day_key()
        quota, used = q.rest_quota(), q.rest_used_in_week(today)
        if q.is_rest(today):
            self.btn(right, '↩ 取消今天請假', t['CARD2'], t['ACCH'], lambda: self._cancel_rest(today),
                     font=t['FS'], pady=2).pack(anchor='e')
        else:
            err = q.can_rest(today)
            b = self.btn(right, f'💤 今天請假（本週剩 {max(0, quota - used)} 天）', t['CARD2'], t['ACCH'],
                         lambda: self._take_rest(today), font=t['FS'], pady=2)
            b.pack(anchor='e')
            if err:
                b.config(state='disabled', text='💤 ' + err)
        tk.Label(right, text='請假日不會中斷連續天數', font=t['FS'], fg=t['TEXTD'], bg=t['CARD']).pack(anchor='e')

    def _recent_practice_seconds(self) -> float:
        cards = G.skill_cards(self.app.quests)
        # 各技能近期秒數是依權重拆分後的值，加總即為近期練習總秒數
        return sum(c['recent_seconds'] for c in cards)

    def _take_rest(self, key):
        err = self.app.quests.take_rest(key)
        if err:
            self.app.var_status.set(f'⚠ {err}')
        else:
            self.app.quests.save(force=True)
            self.app.var_status.set('💤 今天設為休息日，連續天數不會中斷')
        self._after_change()

    def _cancel_rest(self, key):
        if self.app.quests.cancel_rest(key):
            self.app.quests.save(force=True)
            self.app.var_status.set('已取消休息日')
        self._after_change()

    def _after_change(self):
        try:
            self.app._quest_render(force=True)
        except Exception:
            pass
        self.refresh()

    # ── 月曆熱度圖 ────────────────────────────────────────────────────
    def _build_calendar(self):
        t = self.t
        cal = G.month_calendar(self.app.quests, self.year, self.month)
        c = self._card()
        hdr = tk.Frame(c, bg=t['CARD'])
        hdr.pack(fill='x')
        tk.Label(hdr, text=f'📅 {self.year} 年 {self.month} 月', font=t['FH'], fg=t['TEXT'],
                 bg=t['CARD']).pack(side='left')
        self.btn(hdr, '▶', t['CARD2'], t['ACCH'], lambda: self._shift_month(1), font=t['FS'], pady=1
                 ).pack(side='right')
        self.btn(hdr, '◀', t['CARD2'], t['ACCH'], lambda: self._shift_month(-1), font=t['FS'], pady=1
                 ).pack(side='right', padx=(0, 4))

        grid = tk.Frame(c, bg=t['CARD'])
        grid.pack(pady=(px(self, 8), px(self, 4)))
        cell = px(self, 34)
        for i, wd in enumerate(WEEKDAYS):
            tk.Label(grid, text=wd, font=t['FS'], fg=t['TEXTD'], bg=t['CARD'], width=4).grid(row=0, column=i)
        for r, week in enumerate(cal['weeks'], start=1):
            for col, d in enumerate(week):
                f = tk.Frame(grid, width=cell, height=cell, bg=t['CARD'])
                f.grid(row=r, column=col, padx=1, pady=1)
                f.pack_propagate(False)
                if d is None:
                    continue
                self._day_cell(f, d)

        legend = tk.Frame(c, bg=t['CARD'])
        legend.pack(fill='x')
        tk.Label(legend, text='少', font=t['FS'], fg=t['TEXTD'], bg=t['CARD']).pack(side='left')
        for n in range(4):
            tk.Frame(legend, width=px(self, 12), height=px(self, 12), bg=self._heat(n)).pack(side='left', padx=1)
        tk.Label(legend, text='多　💤 休息日', font=t['FS'], fg=t['TEXTD'], bg=t['CARD']).pack(side='left')
        tk.Label(legend, text=f"本月打卡 {cal['done_days']} 天 · 休息 {cal['rest_days']} 天 · "
                              f"練習 {G.fmt_hours(cal['practice_seconds'])}",
                 font=t['FS'], fg=t['TEXTD'], bg=t['CARD']).pack(side='right')

    def _heat(self, done: int) -> str:
        t = self.t
        if done <= 0:
            return t['CARD2']
        try:
            return blend(t['CARD2'], t['ACCENT'], (0.35, 0.65, 1.0)[min(done, 3) - 1])
        except Exception:
            return t['ACCENT']

    def _day_cell(self, frame, d: dict):
        t = self.t
        bg = self._heat(d['done'])
        fg = t['TEXTD'] if d['future'] else ('white' if d['done'] >= 2 else t['TEXT'])
        text = f"{d['day']}\n💤" if d['rest'] and not d['done'] else str(d['day'])
        lbl = tk.Label(frame, text=text, font=t['FS'], bg=bg, fg=fg, cursor='hand2',
                       highlightthickness=2 if d['today'] else 0, highlightbackground=t['YELLOW'],
                       highlightcolor=t['YELLOW'])
        lbl.pack(fill='both', expand=True)
        if not d['future']:
            lbl.bind('<Button-1>', lambda _e, k=d['key']: self._show_day(k))

    def _shift_month(self, delta: int):
        m = self.month + delta
        self.year += (m - 1) // 12
        self.month = (m - 1) % 12 + 1
        self.refresh()

    def _show_day(self, key: str):
        t, q = self.t, self.app.quests
        det = G.day_detail(q, key)
        win = tk.Toplevel(self)
        win.title(f'{key} 的練習')
        win.configure(bg=t['CARD'], padx=px(self, 16), pady=px(self, 12))
        win.transient(self.winfo_toplevel())
        head = f"📅 {key}"
        if det['rest']:
            head += '　💤 休息日'
        tk.Label(win, text=head, font=t['FH'], fg=t['TEXT'], bg=t['CARD'], anchor='w').pack(fill='x')
        tk.Label(win, text=f"打卡 {det['done']}/{det['total']} 項 · 練習 {G.fmt_hours(det['practice_seconds'])}",
                 font=t['FS'], fg=t['TEXTD'], bg=t['CARD'], anchor='w').pack(fill='x', pady=(2, 8))
        if not det['tasks']:
            tk.Label(win, text='這天沒有任務紀錄', font=t['FB'], fg=t['TEXTD'], bg=t['CARD']).pack(anchor='w')
        for it in det['tasks']:
            row = tk.Frame(win, bg=t['CARD2'], padx=px(self, 8), pady=px(self, 5))
            row.pack(fill='x', pady=(0, 4))
            status = STATUS_TEXT.get(it['status'], it['status'] or '')
            if it['self_reported']:
                status += '（自行回報）'
            tk.Label(row, text=f"{it['icon']} {it['name']}", font=t['FB'], fg=t['TEXT'], bg=t['CARD2'],
                     anchor='w').pack(fill='x')
            line = '　'.join(x for x in (it['skills'], it['progress'], status,
                                         f"自評 {it['rating']}/5" if it['rating'] else '') if x)
            tk.Label(row, text=line, font=t['FS'], fg=t['GREEN'] if it['status'] == 'done' else t['TEXTD'],
                     bg=t['CARD2'], anchor='w').pack(fill='x')
            for extra in (f"💬 {it['note']}" if it['note'] else '', f"🖼 {it['ref_title']}" if it['ref_title'] else ''):
                if extra:
                    tk.Label(row, text=extra, font=t['FS'], fg=t['TEXT'], bg=t['CARD2'], anchor='w',
                             justify='left', wraplength=px(self, 380)).pack(fill='x')
        actions = tk.Frame(win, bg=t['CARD'])
        actions.pack(fill='x', pady=(8, 0))
        if det['rest']:
            self.btn(actions, '↩ 取消休息日', t['CARD2'], t['ACCH'],
                     lambda: (self._cancel_rest(key), win.destroy()), font=t['FS'], pady=2).pack(side='left')
        elif q.can_rest(key) is None:
            self.btn(actions, '💤 補請這天休息', t['CARD2'], t['ACCH'],
                     lambda: (self._take_rest(key), win.destroy()), font=t['FS'], pady=2).pack(side='left')
        self.btn(actions, '關閉', t['CARD2'], t['BORDER'], win.destroy, font=t['FS'], pady=2).pack(side='right')
        win.update_idletasks()
        top = self.winfo_toplevel()
        win.geometry(f'+{top.winfo_rootx() + px(self, 30)}+{top.winfo_rooty() + px(self, 80)}')

    # ── 技能卡 ────────────────────────────────────────────────────────
    def _build_skills(self):
        t = self.t
        cards = G.skill_cards(self.app.quests)
        c = self._card('🎨 技能卡')
        tk.Label(c, text='依實際投入時數升級：入門 10h → 基礎 30h → 進階 100h → 熟練 300h → 精通 1000h',
                 font=t['FS'], fg=t['TEXTD'], bg=t['CARD'], anchor='w', justify='left',
                 wraplength=px(self, 480)).pack(fill='x', pady=(2, 6))
        for card in cards:
            self._skill_card(c, card)

    def _skill_card(self, parent, card: dict):
        t = self.t
        ms = card['milestone']
        row = tk.Frame(parent, bg=t['CARD2'], padx=px(self, 10), pady=px(self, 7))
        row.pack(fill='x', pady=(0, px(self, 5)))

        line1 = tk.Frame(row, bg=t['CARD2'])
        line1.pack(fill='x')
        title_fg = t['TEXTD'] if card['idle'] and not card['total_seconds'] else t['TEXT']
        tk.Label(line1, text=f"{card['icon']} {card['name']}", font=t['FB'], fg=title_fg,
                 bg=t['CARD2']).pack(side='left')
        tk.Label(line1, text=f" {ms['name']} ", font=t['FS'], fg='white',
                 bg=t['ACCENT'] if ms['level'] else t['BORDER']).pack(side='left', padx=(6, 0))
        if card['focus']:
            tk.Label(line1, text='⭐ 本週主修', font=t['FS'], fg=t['YELLOW'], bg=t['CARD2']).pack(side='left', padx=6)
        focus_txt = '取消主修' if card['focus'] else '☆ 設為主修'
        self.btn(line1, focus_txt, t['CARD2'], t['ACCH'], lambda sid=card['id']: self._toggle_focus(sid),
                 font=t['FS'], pady=0, padx=4).pack(side='right')
        tk.Label(line1, text=f"累積 {G.fmt_hours(card['total_seconds'])}", font=t['FS'], fg=t['TEXT'],
                 bg=t['CARD2']).pack(side='right', padx=(0, 8))

        self._bar(row, ms['progress'], t['ACCENT']).pack(fill='x', pady=(px(self, 4), px(self, 2)))
        if ms['next_name']:
            left_h = max(0.0, ms['ceil'] - ms['hours'])
            goal = f"距「{ms['next_name']}」還差 {left_h:.1f} 小時"
        else:
            goal = '已達最高等級'
        line2 = tk.Frame(row, bg=t['CARD2'])
        line2.pack(fill='x')
        tk.Label(line2, text=goal, font=t['FS'], fg=t['TEXTD'], bg=t['CARD2']).pack(side='left')
        self._sparkline(line2, card['series']).pack(side='right')
        tk.Label(line2, text=f"近 30 天 {G.fmt_hours(card['recent_seconds'])}　近 14 天：", font=t['FS'],
                 fg=t['TEXTD'], bg=t['CARD2']).pack(side='right')

        info = []
        p = card['path']
        if p:
            info.append(f"📘 課程 {p['index'] + 1}/{p['total']}：Lv{p['current_level']} {p['current_name']}"
                        + ('（已全數通過）' if p['completed'] else ''))
        else:
            info.append('📘 以反覆練習為主')
        if card['ratings']:
            info.append('自評 ' + ' '.join(str(r) for r in card['ratings']))
        if card['idle_days'] is None:
            info.append('尚未開始')
        elif card['idle']:
            info.append(f"⚠ {card['idle_days']} 天未練")
        tk.Label(row, text='　·　'.join(info), font=t['FS'],
                 fg=t['YELLOW'] if card['idle'] and card['idle_days'] is not None else t['TEXTD'],
                 bg=t['CARD2'], anchor='w', justify='left', wraplength=px(self, 470)).pack(fill='x', pady=(2, 0))

    def _sparkline(self, parent, series: list[float]) -> tk.Canvas:
        t = self.t
        w, h = px(self, 98), px(self, 18)
        c = tk.Canvas(parent, width=w, height=h, bg=t['CARD2'], highlightthickness=0)
        peak = max(series) if series else 0
        n = len(series) or 1
        bw = w / n
        for i, v in enumerate(series):
            if v <= 0:
                c.create_line(i * bw + 1, h - 1, (i + 1) * bw - 1, h - 1, fill=t['BORDER'])
                continue
            bh = max(2, int((h - 2) * v / peak))
            c.create_rectangle(i * bw + 1, h - bh, (i + 1) * bw - 1, h, fill=t['ACCENT'], width=0)
        return c

    def _toggle_focus(self, sid: str):
        q = self.app.quests
        q.settings['weekly_focus'] = '' if q.settings.get('weekly_focus') == sid else sid
        q.mark_dirty()
        q.save(force=True)
        skill = q.skill(sid)
        if q.settings['weekly_focus']:
            self.app.var_status.set(f"⭐ 本週主修：{skill['name'] if skill else sid}（之後的課表會優先排這項技能）")
        else:
            self.app.var_status.set('已取消本週主修')
        self.refresh()
