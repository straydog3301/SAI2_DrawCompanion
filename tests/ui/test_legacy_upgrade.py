# -*- coding: utf-8 -*-
"""課程化之前（第一階段）產生的今日研究任務：載入時接上目前課程、名稱更新；前往會開研究視窗（含無課程的自訂研究）"""
import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, headless_main, make_app, close_app  # noqa: E402

M, tmp = headless_main()
from core.daily_quests import QuestManager  # noqa: E402

# 模擬第一階段的資料：內建範本沒有 path、今日研究任務沒有 lesson_id
probe = QuestManager(os.path.join(tmp, 'probe.json'))
today = probe.day_key()
legacy = {
    'current_day': today,
    'templates': [{'id': 't_st_value', 'mode': 'study', 'name': '明度研究', 'enabled': True, 'weight': 1.0,
                   'skills': {'value': 1.0}, 'params': {'minutes': 30}}],
    'days': {today: {'rerolls_used': 0, 'tasks': [
        {'uid': 'legacy01', 'template_id': 't_st_value', 'mode': 'study', 'name': '明度研究', 'skills': {'value': 1.0},
         'params': {'minutes': 30}, 'progress': 120, 'target': 1800, 'status': 'active', 'self_reported': False,
         'checked_at': None, 'note': ''}]}},
}
json.dump(legacy, open(M._QUESTS_PATH, 'w', encoding='utf-8'), ensure_ascii=False)

M.App._focus_sai2 = lambda self: False
root, app = make_app(M)
q = app.quests
t = q.task('legacy01')
check(t['params'].get('lesson_id') == 'value_1' and t['progress'] == 120, f"upgraded {t['params']}")
check(t['name'] == '明暗研究｜Lv1 三階明度' and q.template('t_st_value')['name'] == '明暗研究', 'renamed')
q.save(force=True)
check(not QuestManager(M._QUESTS_PATH)._upgrade_study_tasks(), 'upgrade is idempotent')

app._quest_go('legacy01')
root.update()
check(app._study_win is not None and app._study_win.lesson['id'] == 'value_1', 'go opens study window')
app._study_win.close(stop_timer=False)

tid, err = q.add_template({'mode': 'study', 'name': '自訂研究', 'skills': {'color': 1.0}, 'params': {'minutes': 20}})
custom = q.add_today(tid)
app._quest_go(custom['uid'])
root.update()
win = app._study_win
check(win is not None and win.lesson is None and '自選圖檔' in win.img_label.cget('text'),
      'custom study (no lesson) still opens a window')
win.close()
close_app(root, app)
done()
