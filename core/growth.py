# -*- coding: utf-8 -*-
"""
growth.py - 成長統計（技能卡、里程碑、月曆、單日明細），唯讀、不含 UI

所有數字都由 QuestManager 的 practice_log 與每日任務紀錄即時計算，不另存資料。
日期一律使用「任務日」（依換日時間切分，見 QuestManager.day_key）。
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from core import study_lessons
from core.daily_quests import QuestManager, MODES

# 投入時數里程碑（小時）：入門 → 基礎 → 進階 → 熟練 → 精通
MILESTONES = [(0, '起步'), (10, '入門'), (30, '基礎'), (100, '進階'), (300, '熟練'), (1000, '精通')]
RECENT_DAYS = 30          # 「近期投入」的天數
SERIES_DAYS = 14          # 技能卡趨勢圖的天數
IDLE_WARN_DAYS = 14       # 超過幾天沒練，技能卡標示為冷落
RATING_HISTORY = 8        # 技能卡顯示最近幾次自評


def _d(key: str) -> datetime:
    return datetime.strptime(key, '%Y-%m-%d')


def _k(d: datetime) -> str:
    return d.strftime('%Y-%m-%d')


def milestone(seconds: float) -> dict:
    """投入時數 → 目前等級與到下一級的進度"""
    hours = seconds / 3600.0
    level = 0
    for i, (h, _name) in enumerate(MILESTONES):
        if hours >= h:
            level = i
    floor_h, name = MILESTONES[level]
    if level + 1 < len(MILESTONES):
        ceil_h, next_name = MILESTONES[level + 1]
        progress = (hours - floor_h) / (ceil_h - floor_h)
    else:
        ceil_h, next_name, progress = None, None, 1.0
    return {'level': level, 'name': name, 'hours': hours, 'floor': floor_h, 'ceil': ceil_h,
            'next_name': next_name, 'progress': max(0.0, min(1.0, progress))}


def _weighted(entry: dict) -> dict[str, float]:
    """一筆練習紀錄依技能權重分配到各技能的秒數"""
    skills = entry.get('skills') or {}
    total_w = sum(skills.values()) or 1.0
    return {sid: entry['seconds'] * w / total_w for sid, w in skills.items()}


def skill_daily(m: QuestManager, end_key: str, days: int) -> dict[str, list[float]]:
    """各技能最近 days 天（含 end_key）每天的投入秒數，舊 → 新"""
    end = _d(end_key)
    keys = [_k(end - timedelta(days=days - 1 - i)) for i in range(days)]
    index = {k: i for i, k in enumerate(keys)}
    out: dict[str, list[float]] = {}
    for day, entries in m.data['practice_log'].items():
        i = index.get(day)
        if i is None:
            continue
        for e in entries:
            for sid, sec in _weighted(e).items():
                out.setdefault(sid, [0.0] * days)[i] += sec
    return out


def _ratings_by_skill(m: QuestManager) -> dict[str, list[tuple[str, int]]]:
    """已打卡且有自評的臨摹研究，依課程所屬技能分組（舊 → 新）"""
    out: dict[str, list[tuple[str, int]]] = {}
    for day in sorted(m.data['days']):
        for t in m.data['days'][day].get('tasks', []):
            if t.get('status') != 'done' or t.get('rating') is None:
                continue
            les = study_lessons.lesson(t.get('params', {}).get('lesson_id', ''))
            if les:
                out.setdefault(les['skill'], []).append((day, int(t['rating'])))
    return out


def path_progress(m: QuestManager, skill: str) -> dict | None:
    lessons = study_lessons.path(skill)
    if not lessons:
        return None
    st = m.path_state(skill)
    idx = min(st['index'], len(lessons) - 1)
    cur = lessons[idx]
    return {'index': idx, 'total': len(lessons), 'passed': len(set(st['passed'])),
            'current_id': cur['id'], 'current_name': cur['name'], 'current_level': cur['level'],
            'completed': len(set(st['passed']) & {l['id'] for l in lessons}) == len(lessons)}


def skill_cards(m: QuestManager, now: datetime | None = None) -> list[dict]:
    """技能卡資料：依內建順序列出所有技能（含尚未練過的）"""
    today = m.day_key(now)
    totals = m.skill_seconds()
    recent_from = _k(_d(today) - timedelta(days=RECENT_DAYS - 1))
    recent = m.skill_seconds(since_day=recent_from)
    series = skill_daily(m, today, SERIES_DAYS)
    last_day: dict[str, str] = {}
    for day in sorted(m.data['practice_log']):
        for e in m.data['practice_log'][day]:
            for sid in (e.get('skills') or {}):
                last_day[sid] = day
    ratings = _ratings_by_skill(m)
    cards = []
    for s in m.data['skills']:
        sid = s['id']
        last = last_day.get(sid)
        idle = (_d(today) - _d(last)).days if last else None
        cards.append({
            'id': sid, 'name': s['name'], 'icon': s.get('icon', ''),
            'total_seconds': totals.get(sid, 0.0),
            'recent_seconds': recent.get(sid, 0.0),
            'series': series.get(sid, [0.0] * SERIES_DAYS),
            'milestone': milestone(totals.get(sid, 0.0)),
            'last_day': last, 'idle_days': idle,
            'idle': idle is None or idle >= IDLE_WARN_DAYS,
            'path': path_progress(m, sid),
            'ratings': [r for _d_, r in ratings.get(sid, [])][-RATING_HISTORY:],
            'focus': m.settings.get('weekly_focus') == sid,
        })
    return cards


def day_summary(m: QuestManager, key: str) -> dict:
    day = m.data['days'].get(key, {})
    tasks = day.get('tasks', [])
    seconds = sum(e['seconds'] for e in m.data['practice_log'].get(key, []))
    return {'key': key, 'done': sum(1 for t in tasks if t.get('status') == 'done'),
            'total': len(tasks), 'rest': bool(day.get('rest')), 'practice_seconds': seconds,
            'has_record': key in m.data['days'] or key in m.data['practice_log']}


def month_calendar(m: QuestManager, year: int, month: int, now: datetime | None = None) -> dict:
    """月曆：以週為列（週一起始），每格為該任務日的摘要；不屬於本月的格子為 None"""
    today = m.day_key(now)
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        row = []
        for d in week:
            if d == 0:
                row.append(None)
                continue
            key = f'{year:04d}-{month:02d}-{d:02d}'
            cell = day_summary(m, key)
            cell.update({'day': d, 'today': key == today, 'future': key > today})
            row.append(cell)
        weeks.append(row)
    cells = [c for w in weeks for c in w if c]
    return {'year': year, 'month': month, 'weeks': weeks,
            'done_days': sum(1 for c in cells if c['done']),
            'rest_days': sum(1 for c in cells if c['rest']),
            'practice_seconds': sum(c['practice_seconds'] for c in cells)}


def day_detail(m: QuestManager, key: str) -> dict:
    """單日明細：每項任務的狀態、進度、自評、心得與參考圖"""
    day = m.data['days'].get(key, {})
    items = []
    for t in day.get('tasks', []):
        mode = MODES.get(t.get('mode'), {})
        ref = t.get('ref') or {}
        items.append({
            'name': t.get('name', ''), 'icon': mode.get('icon', ''), 'status': t.get('status'),
            'progress': QuestManager.progress_text(t) if t.get('mode') in MODES else '',
            'skills': m.skill_label(t.get('skills') or {}),
            'rating': t.get('rating'), 'note': t.get('note') or '',
            'self_reported': bool(t.get('self_reported')),
            'ref_title': ' / '.join(x for x in (ref.get('title'), ref.get('artist')) if x),
            'canvas': t.get('canvas') or '',
        })
    summary = day_summary(m, key)
    by_skill: dict[str, float] = {}
    for e in m.data['practice_log'].get(key, []):
        for sid, sec in _weighted(e).items():
            by_skill[sid] = by_skill.get(sid, 0.0) + sec
    summary.update({'tasks': items, 'skill_seconds': by_skill})
    return summary


def fmt_hours(seconds: float) -> str:
    """秒 → 「3.5 小時」/「42 分」"""
    if seconds >= 3600:
        return f'{seconds / 3600:.1f} 小時'
    return f'{int(round(seconds / 60))} 分'
