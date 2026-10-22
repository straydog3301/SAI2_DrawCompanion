# -*- coding: utf-8 -*-
"""主畫面任務卡：創作時長累計與打卡、反覆練習回報、速寫任務帶入本機同名資料夾與有效張數、精簡模式 🎯"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, headless_main, make_app, close_app  # noqa: E402

M, tmp = headless_main()
from tkinter import simpledialog  # noqa: E402
from PIL import Image  # noqa: E402

lib = os.path.join(tmp, 'refs', '手部')
os.makedirs(lib)
for i in range(4):
    Image.new('RGB', (300, 200), (i * 40, 80, 120)).save(os.path.join(lib, f'h{i}.png'))

root, app = make_app(M)
q = app.quests
app._settings.update({'sketch_local_dir': os.path.join(tmp, 'refs'), 'sketch_source_mode': 'local', 'sketch_topmost': False})
for t in q.data['templates']:
    t['enabled'] = False
for tid in ('t_sk_hands', 't_dr_boxes', 't_dt_30'):
    q.add_today(tid)
app._quest_render(force=True)
root.update()
by_mode = {t['mode']: t for t in q.today_tasks() if t['template_id'] in ('t_sk_hands', 't_dr_boxes', 't_dt_30')}
check(len(app.quest_rows.winfo_children()) == len(q.today_tasks()), 'one row per task')

# 創作時長：追蹤器動筆計數的差值 → 達標 → 打卡（含心得）
counter = {'v': 0.0}
app.tracker.get_draw_counter = lambda: counter['v']
app._quest_last_counter = None
app._quest_tick()
counter['v'] = 1800.0
app._quest_tick()
dt = by_mode['draw_time']
check(dt['status'] == 'ready' and '已達標' in app.var_status.get(), f"draw_time {dt['status']}")
simpledialog.askstring = lambda *a, **k: '今天狀態不錯'
app._quest_checkin(dt['uid'])
check(dt['status'] == 'done' and dt['note'] == '今天狀態不錯', 'check-in with note')
check('🔥' in app.var_quest_streak.get(), 'streak label')
check(' | 🎯 1/' in app._quest_mini_suffix(), f'mini suffix {app._quest_mini_suffix()}')

# 反覆練習：前往 → 回報次數
simpledialog.askinteger = lambda *a, **k: 30
app._quest_go(by_mode['drill']['uid'])
check(by_mode['drill']['progress'] == 30 and by_mode['drill']['status'] == 'ready', 'drill report')

# 速寫：沒有 API 金鑰 → 本機「手部」子資料夾；倒數歸零才算一張
sk = by_mode['sketch']
app._quest_go(sk['uid'])
win = app._sketch_win
root.update()
check((win._source_key(), win.var_cat.get(), win._interval_secs()) == ('local', '手部', 90), 'sketch preset')
for _ in range(3):
    win._remaining = 1
    win._tick()
root.update()
check(sk['progress'] == 3 and '3/8' in win.var_quest.get(), f"timeouts counted {sk['progress']}")
win.next_image()
check(sk['progress'] == 3, 'manual skip does not count')
win.var_interval.set('60 秒')
win._on_interval_change()
check('不計入任務' in win.var_quest.get(), 'banner warns after changing interval')
win._remaining = 1
win._tick()
check(sk['progress'] == 3, 'changed settings not counted')
win.var_interval.set('90 秒')
win._on_interval_change()
for _ in range(5):
    win._remaining = 1
    win._tick()
check(sk['status'] == 'ready' and '已達標' in win.var_quest.get(), 'sketch reaches goal')
win._on_close()

# 狀態列：手動提示不會在下一次輪詢被同樣的自動訊息蓋掉
app.var_status.set('手動提示')
app._update_ui(app.tracker.get_state())
check(app.var_status.get() == '手動提示', 'status message survives polling')
close_app(root, app)
done()
