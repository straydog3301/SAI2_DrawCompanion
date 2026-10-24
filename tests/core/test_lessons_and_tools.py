# -*- coding: utf-8 -*-
"""臨摹研究課程資料、學習路徑推進與自評、研究視窗的影像工具（明度分階、主色、裁切工作區）"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk  # noqa: E402,F401
import random
import tempfile
from datetime import datetime
from PIL import Image, ImageDraw
from core import study_lessons as L
from core.daily_quests import QuestManager, est_minutes
from core import study_tools as SW
from core import snapshots as SN



# ── 課程資料完整性 ──
for l in L.LESSONS:
    check(l['phases'] and l['refs'] and l['checks'] and l['mistakes'], f"lesson {l['id']} incomplete")
    check(l['minutes'] == sum(p['minutes'] for p in l['phases']), 'minutes sum')
    check(all(r[0] in ('met', 'artic', 'photo') for r in l['refs']), 'ref kinds')
    check(all(len(r) < 4 or r[3] in ('painting', 'drawing', 'print') for r in l['refs']), 'ref type')
    check(set(l['tools']) <= {'gray', 'value3', 'value5', 'palette', 'thirds', 'grid', 'diagonal'}, 'tools')
check(all([x['level'] for x in p] == list(range(1, len(p) + 1)) for p in L.PATHS.values()), 'levels 1..n')
print('lessons:', len(L.LESSONS), {k: len(v) for k, v in L.PATHS.items()})

# ── 範本依路徑展開、自評推進 ──
m = QuestManager(os.path.join(tempfile.mkdtemp(), 'q.json'), rng=random.Random(1))
for t in m.data['templates']:
    t['enabled'] = t['id'] == 't_st_color'
m.settings['count_min'] = m.settings['count_max'] = 1
m.ensure_today(datetime(2026, 10, 21, 12))
t = m.today_tasks()[0]
check(t['params']['lesson_id'] == 'color_1' and t['target'] == 30 * 60, f"first lesson {t['params']}")
check(t['name'] == '色彩研究｜Lv1 灰階對應', t['name'])
check(est_minutes(m.addable_templates()[0] if m.addable_templates() else t) > 0, 'est')
m.set_task_ref(t['uid'], {'id': 'met:1', 'title': 'x'})
check(m.seen_refs('color_1') == {'met:1'}, 'seen refs')
t['status'] = 'ready'
check(m.check_in(t['uid'], 'ok', rating=2) is None and t['advanced_to'] is None, 'rating 2 stays')
check(m.current_lesson('color')['id'] == 'color_1', 'still lesson 1')
check(m.path_state('color')['attempts']['color_1'] == 1, 'attempt counted')
nt = m.add_today('t_st_color')
check(nt['params']['lesson_id'] == 'color_1', 'retry same lesson')
nt['status'] = 'ready'
m.check_in(nt['uid'], rating=4)
check(nt['advanced_to'] == 'color_2' and m.current_lesson('color')['id'] == 'color_2', 'advance on 4')
nt2 = m.add_today('t_st_color')
check(nt2['params']['lesson_id'] == 'color_2' and nt2['target'] == 45 * 60, 'next lesson 45min')
# 最後一課：不再推進
m.path_state('color')['index'] = len(L.path('color')) - 1
last = m.add_today('t_st_color'); last['status'] = 'ready'
m.check_in(last['uid'], rating=5)
check(last['advanced_to'] is None and m.current_lesson('color')['id'] == 'color_5', 'stay at last')
# 重練舊課高分不會跳課
old = m._make_task(m._effective(m.template('t_st_color')))
old['params']['lesson_id'] = 'color_1'; old['status'] = 'ready'
m.today()['tasks'].append(old)
m.check_in(old['uid'], rating=5)
check(m.current_lesson('color')['id'] == 'color_5', 'old lesson does not move index')
# 舊資料（無 path）遷移
m.data['templates'][[x['id'] for x in m.data['templates']].index('t_st_value')]['params'].pop('path')
m2 = QuestManager.__new__(QuestManager); m2.data = m._migrate(m.data)
check(m2.template('t_st_value')['params']['path'] == 'value', 'migrate path')
# 一般課表仍符合預算（研究時間依課程）
for seed in range(150):
    q = QuestManager(os.path.join(tempfile.mkdtemp(), 'q.json'), rng=random.Random(seed))
    q.ensure_today(datetime(2026, 10, 21, 12))
    ts = q.today_tasks()
    check(sum(est_minutes(x) for x in ts) <= q.settings['budget_minutes'] or len(ts) == 1, 'budget')
    for x in ts:
        if x['mode'] == 'study':
            check(x['params'].get('lesson_id', '').endswith('_1'), 'starts at lv1')

# ── 影像工具 ──
img = Image.new('RGB', (200, 100))
d = ImageDraw.Draw(img)
for x in range(200):
    d.line([(x, 0), (x, 100)], fill=(x * 255 // 199,) * 3)
p3 = SW.posterize_value(img, 3)
check(sorted({c for _n, c in p3.convert('L').getcolors()}) == [0, 128, 255], 'value3 levels')
check(len(p3.convert('L').getcolors()) == 3 and len(SW.posterize_value(img, 5).convert('L').getcolors()) == 5, 'levels')
pal_img = Image.new('RGB', (90, 30), (200, 30, 30)); pal_img.paste((30, 30, 200), (60, 0, 90, 30))
pal = SW.extract_palette(pal_img)
check(pal[0] == (200, 30, 30) and (30, 30, 200) in pal, f'palette {pal}')
ws = Image.new('RGB', (400, 300), (96, 96, 96)); ws.paste((240, 230, 220), (100, 50, 300, 250))
check(SN.trim_workspace(ws).size == (200, 200), 'trim workspace')
check(SN.trim_workspace(Image.new('RGB', (50, 50), 'gray')).size == (50, 50), 'trim nothing')
done()
