# -*- coding: utf-8 -*-
"""
rules.py - 「如果…就…」規則（不含 UI；docs/UI_2.0_PLAN.md §9）

規則：{'id', 'enabled', 'trigger': {'type', 'value'}, 'actions': [{'type', 'value'}, …]}
一條規則可以有多個動作（例如寵物說話＋做動作），依序執行；舊格式的單一 'action' 會自動轉換。
觸發條件與動作都是固定清單，不開放任意程式碼。每條規則各自記住觸發狀態，避免同一件事重複觸發：
- 連續動筆 N 分：每段連續動筆只觸發一次（停筆超過 5 分鐘重新計算）
- 開啟符合名稱的檔案：換到符合的檔案時觸發一次
- 晚上幾點後還在畫：每天一次
- SAI2 開啟：從沒開到開啟時
- 任務達標 / 任務打卡：每次發生
"""

from __future__ import annotations

import fnmatch
import time
import uuid
from datetime import datetime

BREAK_RESET_SEC = 5 * 60

TRIGGERS = {
    'draw_minutes': ('連續動筆超過', '分鐘', 'int'),
    'open_file': ('開啟名稱符合的檔案', '例如 *_練習*.psd', 'text'),
    'after_time': ('晚上這個時間後還在畫', '例如 23:00', 'time'),
    'sai2_start': ('SAI2 開啟時', '', None),
    'quest_ready': ('任務達標時', '', None),
    'checkin': ('任務打卡時', '', None),
}
ACTIONS = {
    'bubble': ('寵物說一句話', '要說的話', 'text'),
    'pet': ('寵物做動作', '', 'choice'),
    'open_sketch': ('開啟速寫小窗', '', None),
    'open_study': ('開啟今天的研究', '', None),
    'record_on': ('開始縮時錄影', '', None),
    'record_off': ('停止縮時錄影', '', None),
    'snapshot': ('存一張畫布快照', '', None),
    'open_url': ('開啟網址', 'https://…', 'text'),
    'open_path': ('開啟檔案或資料夾', '路徑', 'text'),
}
PET_ACTIONS = {'cheer': '歡呼', 'remind': '提醒', 'rest': '休息', 'sleep': '睡覺'}

EXAMPLES = [
    {'trigger': {'type': 'draw_minutes', 'value': 90},
     'actions': [{'type': 'bubble', 'value': '畫了一個半小時了，看看遠方、伸伸懶腰吧'}, {'type': 'pet', 'value': 'rest'}]},
    {'trigger': {'type': 'open_file', 'value': '*練習*'}, 'actions': [{'type': 'open_study', 'value': ''}]},
    {'trigger': {'type': 'after_time', 'value': '23:00'},
     'actions': [{'type': 'bubble', 'value': '已經很晚了，記得存檔，早點休息'}, {'type': 'pet', 'value': 'sleep'}]},
    {'trigger': {'type': 'checkin', 'value': ''}, 'actions': [{'type': 'snapshot', 'value': ''}, {'type': 'pet', 'value': 'cheer'}]},
]


def actions_of(rule: dict) -> list[dict]:
    """規則的動作清單（相容舊格式的單一 'action'）"""
    acts = rule.get('actions')
    if acts is None and rule.get('action'):
        acts = [rule['action']]
    return [dict(a) for a in (acts or [])]


def normalize(rule: dict) -> dict:
    r = dict(rule)
    r['actions'] = actions_of(rule)
    r.pop('action', None)
    return r


def new_rule(trigger: dict | None = None, actions=None, enabled: bool = True) -> dict:
    """actions：動作清單，或單一動作 dict"""
    if isinstance(actions, dict):
        actions = [actions]
    return {'id': uuid.uuid4().hex[:8], 'enabled': enabled,
            'trigger': dict(trigger or {'type': 'draw_minutes', 'value': 60}),
            'actions': [dict(a) for a in (actions or [{'type': 'bubble', 'value': ''}])]}


def validate_action(a: dict) -> str | None:
    if a.get('type') not in ACTIONS:
        return '不認得的動作'
    av = a.get('value')
    if a['type'] == 'bubble' and not str(av or '').strip():
        return '請填入要說的話'
    if a['type'] == 'pet' and av not in PET_ACTIONS:
        return '請選擇寵物動作'
    if a['type'] == 'open_url' and not str(av or '').lower().startswith(('http://', 'https://')):
        return '網址需要以 http:// 或 https:// 開頭'
    if a['type'] == 'open_path' and not str(av or '').strip():
        return '請填入路徑'
    return None


def validate(rule: dict) -> str | None:
    t = rule.get('trigger') or {}
    if t.get('type') not in TRIGGERS:
        return '不認得的觸發條件'
    acts = actions_of(rule)
    if not acts:
        return '至少要有一個動作'
    tv = t.get('value')
    if t['type'] == 'draw_minutes':
        try:
            if int(tv) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return '分鐘數要大於 0'
    if t['type'] == 'open_file' and not str(tv or '').strip():
        return '請填入檔名條件'
    if t['type'] == 'after_time' and _parse_hm(tv) is None:
        return '時間格式請用 23:00'
    for i, a in enumerate(acts, 1):
        err = validate_action(a)
        if err:
            return f'動作 {i}：{err}' if len(acts) > 1 else err
    return None


def _parse_hm(v):
    try:
        h, m = str(v).strip().split(':')
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except (ValueError, AttributeError):
        pass
    return None


def describe(rule: dict) -> str:
    t = rule['trigger']
    tl, unit, _k = TRIGGERS.get(t['type'], ('?', '', None))
    tv = f" {t['value']}{' ' + unit if t['type'] == 'draw_minutes' else ''}" if t.get('value') not in (None, '') else ''
    parts = []
    for a in actions_of(rule):
        al = ACTIONS.get(a['type'], ('?', '', None))[0]
        av = PET_ACTIONS.get(a.get('value'), a.get('value') or '')
        parts.append(al + (f"：{av}" if av else ''))
    return f"如果{tl}{tv}，就" + '、'.join(parts)


class RuleEngine:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._state: dict[str, dict] = {}
        self._prev_running = None
        self._streak_start = None
        self._last_draw = None
        self._prev_file = None

    def evaluate(self, rules: list[dict], ctx: dict) -> list[dict]:
        """ctx：{'now', 'sai2_running', 'drawing', 'current_file', 'events'}；回傳要執行的動作（含 rule_id）"""
        t = self._clock()
        now = ctx.get('now') or datetime.now()
        drawing = bool(ctx.get('drawing'))
        if drawing:
            if self._last_draw is None or t - self._last_draw > BREAK_RESET_SEC:
                self._streak_start = t
                for st in self._state.values():
                    st.pop('streak_fired', None)
            self._last_draw = t
        elif self._last_draw is not None and t - self._last_draw > BREAK_RESET_SEC:
            self._streak_start = None
        cont = (self._last_draw - self._streak_start) if self._streak_start is not None and self._last_draw else 0.0
        running = bool(ctx.get('sai2_running'))
        started = self._prev_running is False and running
        self._prev_running = running
        cur = ctx.get('current_file')
        file_changed = cur != self._prev_file
        self._prev_file = cur
        events = set(ctx.get('events') or ())
        out = []
        for rule in rules or []:
            if not rule.get('enabled', True) or validate(rule):
                continue
            st = self._state.setdefault(rule['id'], {})
            tt, tv = rule['trigger']['type'], rule['trigger'].get('value')
            fire = False
            if tt == 'draw_minutes':
                if cont >= int(tv) * 60 and not st.get('streak_fired'):
                    st['streak_fired'] = True
                    fire = True
            elif tt == 'open_file':
                name = (cur or '').split(' _ ')[-1].lower()
                fire = bool(cur) and file_changed and fnmatch.fnmatch(name, str(tv).strip().lower())
            elif tt == 'after_time':
                h, m = _parse_hm(tv)
                day = now.strftime('%Y-%m-%d')
                late = (now.hour, now.minute) >= (h, m) or now.hour < 5
                if drawing and late and st.get('day') != day:
                    st['day'] = day
                    fire = True
            elif tt == 'sai2_start':
                fire = started
            elif tt in ('quest_ready', 'checkin'):
                fire = tt in events
            if fire:
                out.extend(dict(a, rule_id=rule['id']) for a in actions_of(rule))
        return out
