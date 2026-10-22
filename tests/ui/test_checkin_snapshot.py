# -*- coding: utf-8 -*-
"""打卡快照：擷取畫布並存縮圖、SAI2 未開或設定關閉時略過、成長頁單日明細顯示縮圖"""
import os
import sys
import tkinter as tk
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, headless_main, make_app, close_app  # noqa: E402

M, tmp = headless_main()
from tkinter import simpledialog  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from core import snapshots as SN  # noqa: E402

fake = Image.new('RGB', (1400, 1000), (90, 90, 90))
art = Image.new('RGB', (600, 800), (240, 230, 210))
ImageDraw.Draw(art).ellipse([100, 100, 500, 700], fill=(150, 80, 60))
fake.paste(art, (400, 100))
simpledialog.askstring = lambda *a, **k: ''

root, app = make_app(M)
q = app.quests
M.capture_sai2_canvas = lambda: SN.trim_workspace(fake)
t = q.add_today('t_dt_30')
t['status'] = 'ready'
app._quest_checkin(t['uid'])
check(t.get('snapshot') and os.path.isfile(t['snapshot']), 'snapshot saved')
check(Image.open(t['snapshot']).size == (540, 720), 'workspace trimmed + thumbnail 720px')
check('快照' in app.var_status.get(), 'status mentions snapshot')

M.capture_sai2_canvas = lambda: None                     # SAI2 沒開
t2 = q.add_today('t_dt_60')
t2['status'] = 'ready'
app._quest_checkin(t2['uid'])
check(not t2.get('snapshot') and t2['status'] == 'done', 'no SAI2: check-in without snapshot')

q.settings['snapshot_on_checkin'] = False
M.capture_sai2_canvas = lambda: SN.trim_workspace(fake)
t3 = q.add_today('t_sk_pose')
t3['status'] = 'ready'
app._quest_checkin(t3['uid'])
check(not t3.get('snapshot'), 'setting off: no snapshot')

app._switch_tab('growth')
app.growth_view._show_day(q.data['current_day'])
root.update()
pop = [w for w in app.growth_view.winfo_children() if isinstance(w, tk.Toplevel)][-1]
check(len(getattr(pop, '_photos', [])) == 1, 'day detail shows the snapshot thumbnail')
close_app(root, app)
done()
