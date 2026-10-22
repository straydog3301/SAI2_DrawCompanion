# -*- coding: utf-8 -*-
"""成長統計：休息日與連續天數、里程碑、技能卡、月曆、單日明細（core.growth 不得依賴 Tk）"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk  # noqa: E402,F401
import random
import tempfile
from datetime import datetime
block_tk()
from core.daily_quests import QuestManager
from core import growth as G



def fresh():
    m = QuestManager(os.path.join(tempfile.mkdtemp(), 'q.json'), rng=random.Random(1))
    return m


NOW = datetime(2026, 10, 22, 12)   # 週四

# ── 連續天數與休息日 ──
m = fresh()
for k in ('2026-10-17', '2026-10-18', '2026-10-20', '2026-10-21'):
    m.data['days'][k] = {'tasks': [{'status': 'done'}]}
m.ensure_today(NOW)
check(m.streak(NOW) == 2, f'gap on 19th breaks: {m.streak(NOW)}')
m.data['days']['2026-10-19'] = {'tasks': [], 'rest': True}
check(m.streak(NOW) == 4, f'rest bridges without +1: {m.streak(NOW)}')
check(m.longest_streak() == 4, f'longest {m.longest_streak()}')

m = fresh(); m.ensure_today(NOW)
m.data['days']['2026-10-21'] = {'tasks': [{'status': 'done'}]}
check(m.can_rest('2026-10-22', NOW) is None, 'today allowed')
check(m.can_rest('2026-10-20', NOW) == '只能將今天或昨天設為休息日', 'two days ago refused')
check(m.can_rest('2026-10-21', NOW) == '這天已有打卡，不需要請假', 'done day refused')
check(m.take_rest('2026-10-22', NOW) is None and m.is_rest('2026-10-22'), 'take rest today')
check(m.streak(NOW) == 1, 'rest today keeps streak (no +1)')
check(m.can_rest('2026-10-22', NOW) == '這天已經是休息日', 'already rest')
check(m.rest_used_in_week('2026-10-22') == 1, 'week count')
# 同週再請一天 → 超過配額（預設每週 1 天）
check('本週的休息日已用完' in (m.can_rest('2026-10-23', datetime(2026, 10, 23, 12)) or ''), 'quota')
# 下一週（10/26 週一）配額重置
check(m.can_rest('2026-10-26', datetime(2026, 10, 26, 12)) is None, 'quota resets weekly')
check(m.cancel_rest('2026-10-22') and not m.is_rest('2026-10-22'), 'cancel')
check(m.cancel_rest('2026-10-22') is False, 'cancel twice')
# 補請昨天（昨天沒有任何紀錄時會建立紀錄）
m2 = fresh(); m2.ensure_today(NOW)
m2.data['days']['2026-10-20'] = {'tasks': [{'status': 'done'}]}
check(m2.take_rest('2026-10-21', NOW) is None and '2026-10-21' in m2.data['days'], 'retro rest yesterday')
check(m2.streak(NOW) == 1, f'yesterday rest bridges to 20th: {m2.streak(NOW)}')
m2.settings['rest_days_per_week'] = 0
check('已用完' in (m2.can_rest('2026-10-22', NOW) or ''), 'quota 0 disables')

# ── 里程碑 ──
check(G.milestone(0)['name'] == '起步' and G.milestone(0)['next_name'] == '入門', 'start')
ms = G.milestone(20 * 3600)
check(ms['name'] == '入門' and abs(ms['progress'] - 0.5) < 1e-9 and ms['ceil'] == 30, f'mid {ms}')
check(G.milestone(30 * 3600)['name'] == '基礎', 'boundary 30h')
check(G.milestone(5000 * 3600)['name'] == '精通' and G.milestone(5000 * 3600)['progress'] == 1.0, 'max')

# ── 技能統計 ──
m = fresh(); m.ensure_today(NOW)
log = m.data['practice_log']
log['2026-10-22'] = [{'source': 'study', 'skills': {'color': 0.7, 'value': 0.3}, 'seconds': 3600, 'count': 0}]
log['2026-10-10'] = [{'source': 'sketch', 'skills': {'figure': 1.0}, 'seconds': 600, 'count': 10}]
log['2026-08-01'] = [{'source': 'study', 'skills': {'color': 1.0}, 'seconds': 7200, 'count': 0}]
daily = G.skill_daily(m, '2026-10-22', 14)
check(abs(daily['color'][-1] - 2520) < 1e-6 and abs(daily['value'][-1] - 1080) < 1e-6, 'weighted daily')
check(abs(daily['figure'][-13] - 600) < 1e-6 and len(daily['figure']) == 14, 'series position')
check('color' in daily and sum(daily['color']) == 2520, 'old log outside window')
cards = {c['id']: c for c in G.skill_cards(m, NOW)}
check(len(cards) == 8, 'all skills listed')
check(abs(cards['color']['total_seconds'] - 9720) < 1e-6 and abs(cards['color']['recent_seconds'] - 2520) < 1e-6, 'totals/recent')
check(cards['figure']['idle_days'] == 12 and not cards['figure']['idle'], 'idle days')
check(cards['perspective']['idle'] and cards['perspective']['last_day'] is None, 'never practiced = idle')
check(cards['color']['path']['current_name'] == '灰階對應' and cards['color']['path']['total'] == 5, 'path')
check(cards['line']['path'] is None, 'line has no study path')
# 自評趨勢與路徑推進
for i, r in enumerate([2, 4]):
    t = m.add_today('t_st_color'); t['status'] = 'ready'; m.check_in(t['uid'], rating=r)
cards = {c['id']: c for c in G.skill_cards(m, NOW)}
check(cards['color']['ratings'] == [2, 4], f"ratings {cards['color']['ratings']}")
check(cards['color']['path']['current_level'] == 2 and cards['color']['path']['passed'] == 1, 'path advanced')
m.settings['weekly_focus'] = 'color'
check(next(c for c in G.skill_cards(m, NOW) if c['id'] == 'color')['focus'], 'focus flag')

# ── 月曆 ──
m.data['days']['2026-10-05'] = {'tasks': [{'status': 'done'}, {'status': 'expired'}], 'rest': False}
m.data['days']['2026-10-06'] = {'tasks': [], 'rest': True}
cal = G.month_calendar(m, 2026, 10, NOW)
check(len(cal['weeks'][0]) == 7 and cal['weeks'][0][:3] == [None, None, None], 'Oct 2026 starts Thursday')
cells = {c['key']: c for w in cal['weeks'] for c in w if c}
check(len(cells) == 31, '31 days')
check(cells['2026-10-05']['done'] == 1 and cells['2026-10-05']['total'] == 2, 'day summary')
check(cells['2026-10-06']['rest'] and cal['rest_days'] == 1, 'rest in calendar')
check(cells['2026-10-22']['today'] and cells['2026-10-23']['future'], 'today/future')
check(abs(cal['practice_seconds'] - (3600 + 600)) < 1e-6, 'month practice')
det = G.day_detail(m, '2026-10-22')
rated = [x for x in det['tasks'] if x['rating'] is not None]
check(det['done'] == 2 and [x['rating'] for x in rated] == [2, 4] and rated[0]['icon'], f'detail {det["done"]}')
check(abs(det['skill_seconds']['color'] - 2520) < 1e-6, 'detail by skill')
check(G.fmt_hours(5400) == '1.5 小時' and G.fmt_hours(600) == '10 分', 'fmt')
done()
