# -*- coding: utf-8 -*-
"""成長頁籤：頁籤切換、請假 / 取消、單日明細、換月、技能卡主修切換（以模擬的六週紀錄）"""
import os
import sys
import json
import random
import tkinter as tk
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, headless_main, make_app, close_app  # noqa: E402

M, tmp = headless_main()
rng = random.Random(7)
qday = datetime.now() - timedelta(hours=4)          # 預設換日時間 04:00
days, log = {}, {}
for back in range(1, 45):
    k = (qday - timedelta(days=back)).strftime('%Y-%m-%d')
    if back in (9, 10, 24):
        continue
    if back == 16:
        days[k] = {'tasks': [], 'rest': True}
        continue
    n = rng.randint(1, 3)
    days[k] = {'tasks': [{'uid': f'{k}-{i}', 'name': f'練習 {i + 1}', 'mode': 'sketch', 'status': 'done' if i < n else 'expired',
                          'progress': 8, 'target': 8, 'params': {}, 'skills': {}} for i in range(n)]}
    log[k] = [{'source': 'sketch', 'skills': {'figure': 1.0}, 'seconds': 1200, 'count': 0}]
json.dump({'days': days, 'practice_log': log}, open(M._QUESTS_PATH, 'w', encoding='utf-8'), ensure_ascii=False)

root, app = make_app(M)
q = app.quests
app._switch_tab('growth')
root.update()
check(app._current_tab == 'growth' and app.growth_view.winfo_ismapped(), 'growth tab shown')
check(q.streak() >= 1 and q.longest_streak() >= 15, f'streak {q.streak()} longest {q.longest_streak()}')

today = q.day_key()
before = q.streak()
app.growth_view._take_rest(today)
check(q.is_rest(today) and q.streak() == before, 'rest today keeps streak')
check(q.can_rest(today) == '這天已經是休息日', 'already rest')
app.growth_view._cancel_rest(today)
check(not q.is_rest(today), 'cancel rest')

day = (qday - timedelta(days=2)).strftime('%Y-%m-%d')
app.growth_view._show_day(day)
root.update()
pops = [w for w in app.growth_view.winfo_children() if isinstance(w, tk.Toplevel)]
check(pops and day in pops[-1].title(), 'day detail popup')
pops[-1].destroy()

y, m = app.growth_view.year, app.growth_view.month
app.growth_view._shift_month(-1)
check((app.growth_view.year, app.growth_view.month) == ((y, m - 1) if m > 1 else (y - 1, 12)), 'previous month')
app.growth_view._shift_month(1)

app.growth_view._toggle_focus('perspective')
check(q.settings['weekly_focus'] == 'perspective', 'set weekly focus')
app.growth_view._toggle_focus('perspective')
check(q.settings['weekly_focus'] == '', 'unset weekly focus')

app._switch_tab('stats')
app._switch_tab('tracker')
root.update()
check([k for k, t in app._tabs.items() if t['view'].winfo_ismapped()] == ['tracker'], 'only one tab view mapped')
close_app(root, app)
done()
