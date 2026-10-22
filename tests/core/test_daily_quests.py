# -*- coding: utf-8 -*-
"""每日任務核心：課表規則、換日、進度、打卡、換一個、連續天數、冷落加權、資料檔損毀與遷移"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk  # noqa: E402,F401
import random
import tempfile
from datetime import datetime
from core.daily_quests import QuestManager, est_minutes


def fresh(seed=0):
    p = os.path.join(tempfile.mkdtemp(), 'q.json')
    return QuestManager(p, rng=random.Random(seed)), p




# 1. 課表規則（大量隨機種子）
for seed in range(300):
    m, _ = fresh(seed)
    m.ensure_today(datetime(2026, 10, 21, 12))
    ts = m.today_tasks()
    s = m.settings
    check(s['count_min'] <= len(ts) <= s['count_max'], f'count {len(ts)}')
    total = sum(est_minutes(t) for t in ts)
    check(total <= s['budget_minutes'] or len(ts) == 1, f'budget {total}')
    check(sum(t['mode'] == 'draw_time' for t in ts) <= 1, 'one draw_time')
    check(len({t['template_id'] for t in ts}) == len(ts), 'no dup')
    if len(ts) >= 2:
        check(ts[0]['mode'] == 'sketch' and est_minutes(ts[0]) <= 15, f'warmup {ts[0]["name"]}')
    check(all(m.template(t['template_id'])['enabled'] for t in ts), 'only enabled')

# 2. 換日時間：04:00 前屬前一天；重開不重抽
m, p = fresh(1)
check(m.day_key(datetime(2026, 10, 22, 3, 59)) == '2026-10-21', 'before reset')
check(m.day_key(datetime(2026, 10, 22, 4, 0)) == '2026-10-22', 'after reset')
m.ensure_today(datetime(2026, 10, 21, 20)); m.save(force=True)
first = [t['uid'] for t in m.today_tasks()]
m2 = QuestManager(p); m2.ensure_today(datetime(2026, 10, 22, 2))
check([t['uid'] for t in m2.today_tasks()] == first, 'stable after reload')

# 3. 創作時長 / 研究計時累計 → 達標
m, _ = fresh(2)
m.settings['count_min'] = m.settings['count_max'] = 1
for t in m.data['templates']:
    t['enabled'] = t['id'] in ('t_dt_30', 't_st_value')
m.ensure_today(datetime(2026, 10, 21, 12))
m.add_today('t_st_value' if m.today_tasks()[0]['template_id'] == 't_dt_30' else 't_dt_30')
dt = next(t for t in m.today_tasks() if t['mode'] == 'draw_time')
st = next(t for t in m.today_tasks() if t['mode'] == 'study')
m.tick(600, datetime(2026, 10, 21, 12))
check(dt['progress'] == 600 and st['progress'] == 0, 'study only counts when active')
m.start_study(st['uid'])
ready = m.tick(1200, datetime(2026, 10, 21, 12))
check(dt['status'] == 'ready' and st['progress'] == 1200, f'ready draw {dt["status"]}')
check([r['uid'] for r in ready] == [dt['uid']], 'ready list')
ready = m.tick(600, datetime(2026, 10, 21, 12))
check(st['status'] == 'ready' and ready == [st], 'study ready at 30 min')
check(m.check_in(st['uid'], '明度關係抓得比較準') is None and st['status'] == 'done', 'checkin')
check(m.active_study is None, 'study stops on checkin')
check(abs(m.skill_seconds()['value'] - 1800) < 1e-6, f'study logged {m.skill_seconds()}')
check(m.check_in(st['uid']) == '這項任務已經打卡', 'double checkin rejected')

# 4. 速寫：任務 uid、相符題目、非任務練習
T12 = datetime(2026, 10, 21, 12)
m, _ = fresh(3)
for t in m.data['templates']:
    t['enabled'] = t['id'] == 't_sk_hands'
m.ensure_today(datetime(2026, 10, 21, 12))
sk = m.today_tasks()[0]
for _ in range(3):
    m.record_sketch('hands', 90, sk['uid'], 90, now=T12)
m.record_sketch('hands', 90, None, 90, now=T12)            # 題目、間隔相符 → 計入
m.record_sketch('hands', 60, None, 60, now=T12)            # 間隔不同 → 不計入任務，但記入技能
m.record_sketch('architecture', 60, None, 60, now=T12)     # 非任務 → 依題目對應技能
check(sk['progress'] == 4, f'sketch progress {sk["progress"]}')
sec = m.skill_seconds()
check(abs(sec['figure'] - 420) < 1e-6 and abs(sec['perspective'] - 48) < 1e-6, f'skills {sec}')
check(len(m.data['practice_log'][m.data['current_day']]) == 3, 'log merged per task/topic')
for _ in range(4):
    m.record_sketch('hands', 90, sk['uid'], 90, now=T12)
check(sk['status'] == 'ready', 'sketch ready at 8')
m.check_in(sk['uid'])
check(abs(m.skill_seconds()['figure'] - 420 - 360) < 1e-6, 'sketch not double logged at checkin')

# 5. 反覆練習：回報 + 自行回報打卡 + 過期記錄部分投入
m, _ = fresh(4)
for t in m.data['templates']:
    t['enabled'] = t['id'] in ('t_dr_boxes', 't_th_comp')
m.settings['count_min'] = m.settings['count_max'] = 2
m.ensure_today(datetime(2026, 10, 21, 12))
dr = next(t for t in m.today_tasks() if t['mode'] == 'drill')
th = next(t for t in m.today_tasks() if t['mode'] == 'thumbnail')
m.add_count(dr['uid'], 15)
check(m.check_in(dr['uid']) == '尚未達標', 'not ready')
check(m.check_in(dr['uid'], self_report=True) is None and dr['self_reported'], 'self report')
check(abs(m.skill_seconds()['perspective'] - 20 * 60 * 0.5 * 0.8) < 1e-6, 'drill effort by ratio')
m.add_count(th['uid'], 3)
m.ensure_today(datetime(2026, 10, 22, 12))          # 換日
check(th['status'] == 'expired', 'expired on rollover')
check(abs(m.skill_seconds()['composition'] - 20 * 60 * 0.5 * 0.7) < 1e-6, 'expired partial logged')
check(m.data['current_day'] == '2026-10-22' and m.today_tasks(), 'new day generated')

# 6. 換一個：次數限制、已開始不能換
m, _ = fresh(5)
m.settings['count_min'] = m.settings['count_max'] = 2
m.ensure_today(datetime(2026, 10, 21, 12))
a, b = m.today_tasks()
old_tid = a['template_id']
check(m.reroll(a['uid']) is None, 'reroll ok')
check(m.today_tasks()[0]['template_id'] != old_tid, 'replaced')
check(m.reroll(m.today_tasks()[1]['uid']) == '今天的更換次數已用完', 'limit')
m.settings['rerolls_per_day'] = 5
t0 = m.today_tasks()[0]; t0['progress'] = 1
check(m.reroll(t0['uid']) == '已開始或已完成的任務不能更換', 'started')
today_tids = {x['template_id'] for x in m.today_tasks()}
check(all(t['id'] not in today_tids for t in m.addable_templates()), 'addable excludes today')

# 7. 連續天數：今天未打卡不中斷、斷一天歸零
m, _ = fresh(6)
for day in ['2026-10-18', '2026-10-19', '2026-10-20']:
    m.data['days'][day] = {'tasks': [{'status': 'done'}]}
m.ensure_today(datetime(2026, 10, 21, 12))
check(m.streak(datetime(2026, 10, 21, 12)) == 3, 'streak keeps through today')
m.today_tasks()[0]['status'] = 'ready'; m.check_in(m.today_tasks()[0]['uid'])
check(m.streak(datetime(2026, 10, 21, 12)) == 4, 'streak +1')
check(m.streak(datetime(2026, 10, 23, 12)) == 0, 'gap breaks')

# 8. 冷落加權與本週主修
m, _ = fresh(7)
tpl_v = m.template('t_st_value'); tpl_c = m.template('t_st_color')
m.data['practice_log']['2026-10-20'] = [{'source': 'study', 'skills': {'value': 1.0}, 'seconds': 60, 'count': 0}]
w_recent = m._weight(tpl_v, '2026-10-21', m._last_practiced(), set())
w_never = m._weight(tpl_c, '2026-10-21', m._last_practiced(), set())
check(w_never > w_recent * 2, f'neglect {w_recent} {w_never}')
m.settings['weekly_focus'] = 'value'
check(abs(m._weight(tpl_v, '2026-10-21', m._last_practiced(), set()) - w_recent * 2) < 1e-9, 'focus x2')
check(m._weight(tpl_v, '2026-10-21', m._last_practiced(), {'t_st_value'}) < w_recent, 'yesterday penalty')

# 9. 損毀檔案：保留 .corrupt 並重建；新增內建範本以停用狀態補上
d = tempfile.mkdtemp(); p = os.path.join(d, 'q.json')
open(p, 'w').write('{broken')
m = QuestManager(p)
check(any(f.startswith('q.json.corrupt_') for f in os.listdir(d)) and m.data['templates'], 'corrupt recovered')
m.data['templates'] = [t for t in m.data['templates'] if t['id'] != 't_dt_30']
m.data['builtin_templates_seen'] = [x for x in m.data['builtin_templates_seen'] if x != 't_dt_30']
m.mark_dirty(); m.save(force=True)
m = QuestManager(p)
check(m.template('t_dt_30') and m.template('t_dt_30')['enabled'] is False, 'new builtin added disabled')
m.settings['enabled'] = False
check(m.ensure_today() is False, 'disabled -> no generation')
done()
