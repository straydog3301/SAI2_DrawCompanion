# -*- coding: utf-8 -*-
"""任務管理視窗（範本新增 / 驗證 / 編輯 / 啟用切換 / 刪除、技能新增刪除）、作品技能標籤對話框、設定頁「每日任務」區塊"""
import os
import sys
import json
import tkinter as tk
from tkinter import messagebox
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, headless_main, make_app, close_app  # noqa: E402

M, tmp = headless_main()
import quest_manager_window as QW  # noqa: E402
warnings = []
messagebox.showwarning = lambda title, msg, **k: warnings.append(msg)
messagebox.askyesno = lambda *a, **k: True

root, app = make_app(M)
q = app.quests

# ── 管理視窗 ──
app._open_quest_manager()
root.update()
mw = app._quest_mgr_win
check(len(mw.tree.get_children()) == len(q.data['templates']), 'all templates listed')
ed = QW.TemplateEditor(mw, None)
ed.var_name.set('龍的速寫')
ed.var_topic.set('自訂關鍵字')
ed.var_kw.set('dragon')
ed.skill_vars['form'].set(True)
ed.skill_vars['figure'].set(True)
ed.var_count.set(12)
ed.var_interval.set('90 秒')
ed._save()
new = next(t for t in q.data['templates'] if t['name'] == '龍的速寫')
check(new['params'] == {'topic': 'kw:dragon', 'count': 12, 'interval': 90}, f"params {new['params']}")
check(new['skills'] == {'form': 0.5, 'figure': 0.5} and mw.tree.exists(new['id']), 'skills + listed')

ed = QW.TemplateEditor(mw, None)
ed.var_name.set('')
ed._save()
check(warnings[-1] == '請輸入名稱' and ed.winfo_exists(), 'validation keeps editor open')
ed.destroy()

ed = QW.TemplateEditor(mw, new['id'])
ed.var_mode.set('🖌️ 臨摹研究')
ed._show_params()
ed.var_path.set('不使用（自訂分鐘數）')
ed.var_minutes.set(25)
ed._save()
check(q.template(new['id'])['mode'] == 'study' and q.template(new['id'])['params'] == {'minutes': 25}, 'edit to study')

mw.tree.selection_set(new['id'])
mw._toggle()
check(q.template(new['id'])['enabled'] is False, 'toggle disables')
mw.tree.selection_set('t_sk_pose')
mw._delete()
check(warnings[-1].startswith('內建範本無法刪除') and q.template('t_sk_pose'), 'builtin delete refused')
mw.tree.selection_set(new['id'])
mw._delete()
check(q.template(new['id']) is None, 'custom template deleted')

mw._show('skills')
mw.var_skill.set('場景設計')
mw.var_icon.set('🏙')
mw._add_skill()
sid = next(s['id'] for s in q.data['skills'] if s['name'] == '場景設計')
mw._delete_skill(sid)
check(q.skill(sid) is None, 'custom skill added + deleted')
saved = json.load(open(M._QUESTS_PATH, encoding='utf-8'))
check(len(saved['templates']) == len(q.data['templates']), 'changes persisted')
mw.destroy()

# ── 作品技能標籤對話框 ──
fname = '本機磁碟 (D:) _ 立繪 _ L1.png'
app._file_skill_tags_dialog(fname)
root.update()
dlg = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == '技能標籤'][-1]
cbs = [w for f in dlg.winfo_children() for w in ([f] + list(f.winfo_children())) if isinstance(w, tk.Checkbutton)]
cbs[4].invoke()     # 色彩
cbs[7].invoke()     # 質感描繪
ok_btn = next(w for f in dlg.winfo_children() if isinstance(f, tk.Frame) for w in f.winfo_children()
              if isinstance(w, tk.Button) and w.cget('text') == '確定')
ok_btn.invoke()
check(q.file_tags(fname) == {'color': 0.5, 'rendering': 0.5}, f'file tags {q.file_tags(fname)}')

# ── 設定頁「每日任務」區塊（對話框為阻塞式，以延遲動作操作）──
log = []


def find_dialog():
    return next(w for w in root.winfo_children() if isinstance(w, M.SettingsDialog))


def step1():
    d = find_dialog()
    d.var_q_min.set(4)
    d.var_q_max.set(2)
    d._apply()
    log.append(d.winfo_exists())
    log.append(d.winfo_width() >= d.minsize()[0])
    d.var_q_min.set(2)
    d.var_q_max.set(3)
    d.var_q_budget.set(90)
    d.var_q_reset.set(5)
    d.var_q_rest.set(2)
    d.var_q_snap.set(False)
    d.var_q_enabled.set(False)
    d._apply()


root.after(600, step1)
app._open_settings()
root.update()
check(log == [1, True] and '超出範圍' in warnings[-1], 'invalid range keeps dialog open')
qs = json.load(open(M._QUESTS_PATH, encoding='utf-8'))['settings']
check((qs['enabled'], qs['count_min'], qs['count_max'], qs['budget_minutes'], qs['reset_hour'],
       qs['rest_days_per_week'], qs['snapshot_on_checkin']) == (False, 2, 3, 90, 5, 2, False), f'saved {qs}')
check(not app.quest_card.winfo_ismapped(), 'card hidden when disabled')


def step2():
    find_dialog().var_q_enabled.set(True)
    find_dialog()._apply()


root.after(600, step2)
app._open_settings()
root.update()
check(app.quest_card.winfo_ismapped() and app.quest_card.master.pack_slaves().index(app.quest_card) == 1,
      'card re-shown right after status card')
close_app(root, app)
done()
