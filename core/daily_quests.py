# -*- coding: utf-8 -*-
"""
daily_quests.py - 每日任務與繪圖技能體系（不含 UI）

兩個維度：技能（練什麼：透視、色彩…）× 練習方式（怎麼練：速寫、臨摹研究…）。
每日依「平衡課表」抽出 1~3 項任務，進度達標後打卡；所有練習都寫入 practice_log，
技能卡等統計一律由 practice_log 即時計算。完整規格見 docs/DAILY_QUESTS.md。

UI 與主程式透過 QuestManager 的公開方法操作；時間（now）與亂數（rng）皆可注入以利測試。
"""

from __future__ import annotations

import os
import json
import time
import uuid
import copy
import random
from datetime import datetime, timedelta

from core import study_lessons

SCHEMA_VERSION = 1
PASS_RATING = 3   # 臨摹研究自評達此分數才推進到下一課

# ─── 內建技能 ─────────────────────────────────────────────────────────────
DEFAULT_SKILLS = [
    {'id': 'perspective', 'name': '透視', 'icon': '📐',
     'subtopics': ['一/二/三點透視', '圓與橢圓', '室內場景', '人物置入場景']},
    {'id': 'form', 'name': '形體結構', 'icon': '🧊',
     'subtopics': ['基本幾何體', '穿插與結構線', '物體簡化']},
    {'id': 'figure', 'name': '人體與動態', 'icon': '🧍',
     'subtopics': ['姿勢速寫', '解剖', '手腳', '臉部', '服裝皺褶']},
    {'id': 'value', 'name': '明暗光影', 'icon': '◐',
     'subtopics': ['明度分級', '光源與投影', '反光', '材質受光']},
    {'id': 'color', 'name': '色彩', 'icon': '🎨',
     'subtopics': ['色彩臨摹', '色彩關係', '氛圍光色', '限色練習']},
    {'id': 'composition', 'name': '構成', 'icon': '🖼️',
     'subtopics': ['縮圖構圖', '視線引導', '黑白灰配置', '景深層次']},
    {'id': 'line', 'name': '線條筆觸', 'icon': '✒️',
     'subtopics': ['控線', '線條輕重', '筆刷運用']},
    {'id': 'rendering', 'name': '質感描繪', 'icon': '🔍',
     'subtopics': ['金屬', '布料', '毛髮', '自然物']},
]

# ─── 練習方式 ─────────────────────────────────────────────────────────────
# unit: 'count' = 進度以次數計；'seconds' = 進度以秒計（目標以分鐘設定）
MODES = {
    'sketch':    {'icon': '⚡', 'name': '計時速寫', 'unit': 'count'},
    'study':     {'icon': '🖌️', 'name': '臨摹研究', 'unit': 'seconds'},
    'drill':     {'icon': '🔁', 'name': '反覆練習', 'unit': 'count'},
    'thumbnail': {'icon': '🗂️', 'name': '縮圖構成', 'unit': 'count'},
    'draw_time': {'icon': '⏱️', 'name': '創作時長', 'unit': 'seconds'},
}

# 非任務速寫依題目歸屬的技能（速寫題目 key 與 main.SKETCH_CATEGORIES 一致）
SKETCH_TOPIC_SKILLS = {
    'portrait':     {'figure': 1.0},
    'pose':         {'figure': 1.0},
    'hands':        {'figure': 1.0},
    'feet':         {'figure': 1.0},
    'animal':       {'form': 0.6, 'figure': 0.4},
    'still':        {'form': 0.5, 'value': 0.5},
    'landscape':    {'composition': 0.6, 'perspective': 0.4},
    'architecture': {'perspective': 0.8, 'composition': 0.2},
}

# ─── 內建任務範本 ─────────────────────────────────────────────────────────
# sketch.params: topic（速寫題目 key / 'local:<子資料夾>' / 'kw:<關鍵字>'）、count、interval（秒）
# study / draw_time.params: minutes；drill / thumbnail.params: count、est_minutes（預估時間）
DEFAULT_TEMPLATES = [
    {'id': 't_sk_pose', 'mode': 'sketch', 'name': '姿勢速寫', 'enabled': True, 'weight': 1.0,
     'skills': {'figure': 1.0}, 'params': {'topic': 'pose', 'count': 15, 'interval': 30}},
    {'id': 't_sk_portrait', 'mode': 'sketch', 'name': '人像速寫', 'enabled': True, 'weight': 1.0,
     'skills': {'figure': 1.0}, 'params': {'topic': 'portrait', 'count': 10, 'interval': 60}},
    {'id': 't_sk_hands', 'mode': 'sketch', 'name': '手部速寫', 'enabled': True, 'weight': 1.0,
     'skills': {'figure': 1.0}, 'params': {'topic': 'hands', 'count': 8, 'interval': 90}},
    {'id': 't_sk_animal', 'mode': 'sketch', 'name': '動物速寫', 'enabled': True, 'weight': 0.8,
     'skills': {'form': 0.6, 'figure': 0.4}, 'params': {'topic': 'animal', 'count': 10, 'interval': 60}},
    {'id': 't_sk_landscape', 'mode': 'sketch', 'name': '風景速寫', 'enabled': True, 'weight': 0.8,
     'skills': {'composition': 0.6, 'perspective': 0.4},
     'params': {'topic': 'landscape', 'count': 6, 'interval': 120}},
    # 臨摹研究依技能的學習路徑排課（params.path），名稱與時間由當前課程決定（見 study_lessons.py）
    {'id': 't_st_color', 'mode': 'study', 'name': '色彩研究', 'enabled': True, 'weight': 1.0,
     'skills': {'color': 0.7, 'value': 0.3}, 'params': {'path': 'color', 'minutes': 45}},
    {'id': 't_st_value', 'mode': 'study', 'name': '明暗研究', 'enabled': True, 'weight': 1.0,
     'skills': {'value': 1.0}, 'params': {'path': 'value', 'minutes': 30}},
    {'id': 't_st_render', 'mode': 'study', 'name': '質感研究', 'enabled': True, 'weight': 0.8,
     'skills': {'rendering': 0.6, 'value': 0.4}, 'params': {'path': 'rendering', 'minutes': 45}},
    {'id': 't_st_comp', 'mode': 'study', 'name': '構成研究', 'enabled': True, 'weight': 0.9,
     'skills': {'composition': 0.8, 'value': 0.2}, 'params': {'path': 'composition', 'minutes': 30}},
    {'id': 't_st_persp', 'mode': 'study', 'name': '透視研究', 'enabled': True, 'weight': 0.9,
     'skills': {'perspective': 1.0}, 'params': {'path': 'perspective', 'minutes': 30}},
    {'id': 't_st_form', 'mode': 'study', 'name': '形體研究', 'enabled': True, 'weight': 0.9,
     'skills': {'form': 1.0}, 'params': {'path': 'form', 'minutes': 30}},
    {'id': 't_st_figure', 'mode': 'study', 'name': '人體研究', 'enabled': True, 'weight': 0.9,
     'skills': {'figure': 1.0}, 'params': {'path': 'figure', 'minutes': 30}},
    {'id': 't_dr_boxes', 'mode': 'drill', 'name': '透視方塊 30 個', 'enabled': True, 'weight': 1.0,
     'skills': {'perspective': 0.8, 'form': 0.2}, 'params': {'count': 30, 'est_minutes': 20}},
    {'id': 't_dr_lines', 'mode': 'drill', 'name': '控線與橢圓 3 頁', 'enabled': True, 'weight': 0.8,
     'skills': {'line': 1.0}, 'params': {'count': 3, 'est_minutes': 15}},
    {'id': 't_th_comp', 'mode': 'thumbnail', 'name': '構圖縮圖 6 張', 'enabled': True, 'weight': 1.0,
     'skills': {'composition': 0.7, 'value': 0.3}, 'params': {'count': 6, 'est_minutes': 20}},
    {'id': 't_dt_30', 'mode': 'draw_time', 'name': '創作 30 分鐘', 'enabled': True, 'weight': 1.0,
     'skills': {}, 'params': {'minutes': 30}},
    {'id': 't_dt_60', 'mode': 'draw_time', 'name': '創作 60 分鐘', 'enabled': False, 'weight': 1.0,
     'skills': {}, 'params': {'minutes': 60}},
]

DEFAULT_SETTINGS = {
    'enabled': True,
    'count_min': 1,
    'count_max': 3,
    'budget_minutes': 60,     # 每日時間預算：抽出任務的預估時間合計上限
    'reset_hour': 4,          # 換日時間（0~23）
    'rerolls_per_day': 1,
    'weekly_focus': '',       # 本週主修技能 id（'' = 無）
    'rest_days_per_week': 1,  # 每週可請假（不中斷連續天數）的天數
    'snapshot_on_checkin': True,  # 打卡時擷取 SAI2 畫布縮圖，作為作品紀錄
}

WARMUP_MAX_MINUTES = 15           # 熱身：≤15 分的速寫
NEGLECT_FULL_DAYS = 14            # 冷落加權在 14 天未練時達上限
NEGLECT_MAX_FACTOR = 3.0
FOCUS_FACTOR = 2.0
REPEAT_YESTERDAY_FACTOR = 0.3
UNLIMITED_SKETCH_MIN_SECONDS = 30  # 不限時速寫：停留滿 30 秒才算一張
SKETCH_ALLOWED_INTERVALS = (30, 60, 90, 120, 300, 600)   # 與速寫視窗的間隔選項一致（任務不用「不限時」）
MAX_TEMPLATE_NAME = 40


def est_minutes(tpl: dict) -> float:
    """範本 / 任務的預估投入時間（分鐘），用於每日時間預算"""
    p = tpl.get('params', {})
    mode = tpl.get('mode')
    if mode == 'sketch':
        interval = p.get('interval', 60) or UNLIMITED_SKETCH_MIN_SECONDS
        return p.get('count', 1) * interval / 60.0
    if mode in ('study', 'draw_time'):
        return float(p.get('minutes', 30))
    return float(p.get('est_minutes', 15))


def target_of(tpl: dict) -> int:
    """進度目標：count 型為次數，seconds 型為秒數"""
    p = tpl.get('params', {})
    if MODES.get(tpl.get('mode'), {}).get('unit') == 'seconds':
        return int(p.get('minutes', 30) * 60)
    return int(p.get('count', 1))


class QuestManager:
    """每日任務的狀態與規則。所有會改變狀態的方法都會標記需存檔，呼叫端定期呼叫 save()。"""

    SAVE_INTERVAL_SEC = 15.0   # 進度累加（每秒）時的存檔節流

    def __init__(self, path: str, rng: random.Random | None = None):
        self.path = path
        self.rng = rng or random.Random()
        self.data: dict = {}
        self._dirty = False
        self._last_save = 0.0
        self.load()

    # ── 載入 / 存檔 ───────────────────────────────────────────────────────
    def load(self):
        data = None
        if os.path.isfile(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError('根節點不是物件')
            except Exception as e:
                # 損毀時保留原檔供人工救援，避免下次存檔直接覆蓋
                print(f'[QuestManager] Load error: {e}')
                try:
                    os.replace(self.path, self.path + f'.corrupt_{int(time.time())}')
                except Exception:
                    pass
                data = None
        self.data = self._migrate(data or {})
        if data is None:
            self._dirty = True
        if self._upgrade_study_tasks():
            self._dirty = True

    def reload(self):
        """重新讀取檔案（例如 1.x 剛改過），沿用同一個物件，持有這個物件的畫面不會變成改到舊資料"""
        self._dirty = False
        self.load()

    # 舊版內建範本名稱 → 新名稱（使用者沒改過名稱時才更新）
    _RENAMED_BUILTINS = {'t_st_color': ('色彩臨摹', '色彩研究'), 't_st_value': ('明度研究', '明暗研究')}

    def _upgrade_study_tasks(self) -> bool:
        """讓課程化之前產生的今日臨摹研究任務也對應到課程：補上目前課程、名稱與目標時間，保留已累計的進度。
        （不升級的話，這類任務按「前往」只會默默開始計時，不會開啟研究視窗）"""
        changed = False
        for tpl in self.data['templates']:
            old_new = self._RENAMED_BUILTINS.get(tpl.get('id'))
            if old_new and tpl.get('name') == old_new[0]:
                tpl['name'] = old_new[1]
                changed = True
        day = self.data['days'].get(self.data.get('current_day') or '')
        for t in (day or {}).get('tasks', []):
            if t.get('mode') != 'study' or t.get('status') not in ('active', 'ready') \
                    or t.get('params', {}).get('lesson_id'):
                continue
            tpl = self.template(t.get('template_id', ''))
            if not tpl or not tpl.get('params', {}).get('path'):
                continue
            eff = self._effective(tpl)
            if 'lesson_id' not in eff['params']:
                continue
            t['name'] = eff['name']
            t['params'] = copy.deepcopy(eff['params'])
            t['skills'] = copy.deepcopy(eff.get('skills', t.get('skills', {})))
            t['target'] = target_of(eff)
            if t['status'] == 'ready' and t['progress'] < t['target']:
                t['status'] = 'active'
            elif t['status'] == 'active' and t['progress'] >= t['target']:
                t['status'] = 'ready'
            changed = True
        return changed

    def _migrate(self, d: dict) -> dict:
        """補齊缺少的欄位；內建技能 / 範本依 id 合併，保留使用者的修改與自建項目"""
        d.setdefault('schema', SCHEMA_VERSION)
        settings = d.setdefault('settings', {})
        for k, v in DEFAULT_SETTINGS.items():
            settings.setdefault(k, v)

        skills = d.setdefault('skills', [])
        have = {s.get('id') for s in skills}
        for s in DEFAULT_SKILLS:
            if s['id'] not in have:
                skills.append(dict(copy.deepcopy(s), builtin=True))

        templates = d.setdefault('templates', [])
        have = {t.get('id') for t in templates}
        if not templates:
            templates.extend(copy.deepcopy(DEFAULT_TEMPLATES))
        else:
            # 新版本新增的內建範本才補上（以停用狀態加入，不打亂使用者已調整的課表）
            seen_builtin = set(d.setdefault('builtin_templates_seen', []))
            for t in DEFAULT_TEMPLATES:
                if t['id'] not in have and t['id'] not in seen_builtin:
                    templates.append(dict(copy.deepcopy(t), enabled=False))
        d['builtin_templates_seen'] = sorted({t['id'] for t in DEFAULT_TEMPLATES}
                                             | set(d.get('builtin_templates_seen', [])))

        # 內建臨摹研究範本改為依學習路徑排課（舊資料沒有 path 時補上）
        builtin_paths = {t['id']: t['params']['path'] for t in DEFAULT_TEMPLATES if 'path' in t['params']}
        for t in templates:
            if t.get('id') in builtin_paths and 'path' not in t.get('params', {}):
                t.setdefault('params', {})['path'] = builtin_paths[t['id']]

        d.setdefault('days', {})
        d.setdefault('practice_log', {})
        d.setdefault('active_study', None)
        d.setdefault('current_day', None)
        d.setdefault('lesson_progress', {})
        d.setdefault('file_tags', {})     # 作品檔案 key → 技能權重
        return d

    def mark_dirty(self):
        self._dirty = True

    def save(self, force: bool = False):
        if not self._dirty:
            return
        now = time.monotonic()
        if not force and now - self._last_save < self.SAVE_INTERVAL_SEC:
            return
        try:
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            self._dirty = False
            self._last_save = now
        except Exception as e:
            print(f'[QuestManager] Save error: {e}')

    # ── 基本查詢 ──────────────────────────────────────────────────────────
    @property
    def settings(self) -> dict:
        return self.data['settings']

    def skill(self, sid: str) -> dict | None:
        return next((s for s in self.data['skills'] if s.get('id') == sid), None)

    def template(self, tid: str) -> dict | None:
        return next((t for t in self.data['templates'] if t.get('id') == tid), None)

    def day_key(self, now: datetime | None = None) -> str:
        """任務日：以換日時間切分（reset_hour=4 時，凌晨 3:59 仍屬前一天）"""
        now = now or datetime.now()
        return (now - timedelta(hours=int(self.settings.get('reset_hour', 4)))).strftime('%Y-%m-%d')

    def today(self) -> dict | None:
        key = self.data.get('current_day')
        return self.data['days'].get(key) if key else None

    def today_tasks(self) -> list[dict]:
        day = self.today()
        return day['tasks'] if day else []

    def task(self, uid: str) -> dict | None:
        return next((t for t in self.today_tasks() if t['uid'] == uid), None)

    def skill_label(self, skills: dict) -> str:
        """技能權重 → 顯示用文字（依權重由大到小，例：「色彩·明暗光影」）"""
        from core.data_text import skill_name
        names = []
        for sid, _w in sorted(skills.items(), key=lambda kv: -kv[1]):
            s = self.skill(sid)
            if s:
                names.append(skill_name(s))
        return '·'.join(names)

    # ── 換日與課表產生 ────────────────────────────────────────────────────
    def ensure_today(self, now: datetime | None = None) -> bool:
        """確認目前任務日的課表存在；換日時結算前一天並產生新課表。回傳是否有變動。"""
        if not self.settings.get('enabled', True):
            return False
        key = self.day_key(now)
        if self.data.get('current_day') == key and key in self.data['days']:
            return False
        prev = self.data.get('current_day')
        if prev and prev != key and prev in self.data['days']:
            self._finalize_day(prev)
        self.data['current_day'] = key
        if key not in self.data['days']:
            self.data['days'][key] = {'rerolls_used': 0, 'tasks': self._generate(key)}
        self.mark_dirty()
        return True

    def regenerate_today(self, now: datetime | None = None) -> bool:
        """依目前設定重排今天的課表（例如剛調整每日練習時間）。今天已經開始練習時不動，回傳是否重排"""
        if not self.settings.get('enabled', True):
            return False
        self.ensure_today(now)
        key = self.day_key(now)
        day = self.data['days'].get(key)
        if day is None or any(t.get('progress') or t['status'] != 'active' for t in day['tasks']):
            return False
        if self.data.get('active_study') in {t['uid'] for t in day['tasks']}:
            return False
        day['tasks'] = self._generate(key)
        self.mark_dirty()
        return True

    def _finalize_day(self, key: str):
        """結算：未打卡的任務標記過期，並把已投入的部分寫入練習紀錄"""
        for t in self.data['days'][key]['tasks']:
            if t['status'] in ('active', 'ready'):
                t['status'] = 'expired'
                self._log_task_effort(t, key)
        self.data['active_study'] = None

    def _last_practiced(self) -> dict[str, str]:
        """各技能最後一次有練習紀錄的任務日"""
        last: dict[str, str] = {}
        for day in sorted(self.data['practice_log']):
            for e in self.data['practice_log'][day]:
                for sid in e.get('skills', {}):
                    last[sid] = day
        return last

    def _weight(self, tpl: dict, day_key: str, last: dict[str, str], yesterday_tids: set[str]) -> float:
        w = float(tpl.get('weight', 1.0))
        skills = tpl.get('skills', {})
        if skills:
            today = datetime.strptime(day_key, '%Y-%m-%d')
            gaps = []
            for sid in skills:
                if sid in last:
                    gaps.append((today - datetime.strptime(last[sid], '%Y-%m-%d')).days)
                else:
                    gaps.append(NEGLECT_FULL_DAYS)   # 從未練過視同冷落已久
            gap = max(gaps)
            w *= 1.0 + (NEGLECT_MAX_FACTOR - 1.0) * min(gap, NEGLECT_FULL_DAYS) / NEGLECT_FULL_DAYS
        focus = self.settings.get('weekly_focus', '')
        if focus and focus in skills:
            w *= FOCUS_FACTOR
        if tpl['id'] in yesterday_tids:
            w *= REPEAT_YESTERDAY_FACTOR
        return max(w, 0.0)

    # ── 學習路徑 ──────────────────────────────────────────────────────────
    def path_state(self, skill: str) -> dict:
        st = self.data['lesson_progress'].setdefault(skill, {})
        st.setdefault('index', 0)
        st.setdefault('passed', [])
        st.setdefault('attempts', {})
        st.setdefault('seen_refs', {})
        return st

    def current_lesson(self, skill: str) -> dict | None:
        """該技能路徑上目前要上的課（全部通過後停在最後一課，可反覆練習）"""
        lessons = study_lessons.path(skill)
        if not lessons:
            return None
        return lessons[min(self.path_state(skill)['index'], len(lessons) - 1)]

    def _effective(self, tpl: dict) -> dict:
        """依學習路徑展開臨摹研究範本：名稱、時間與課程 id 由目前課程決定"""
        skill = tpl.get('params', {}).get('path')
        if tpl.get('mode') != 'study' or not skill:
            return tpl
        les = self.current_lesson(skill)
        if not les:
            return tpl
        eff = copy.deepcopy(tpl)
        eff['name'] = f"{tpl['name']}｜Lv{les['level']} {les['name']}"
        eff['params'].update({'lesson_id': les['id'], 'minutes': les['minutes']})
        return eff

    def _enabled_templates(self, exclude_tids: set[str] | None = None) -> list[dict]:
        return [self._effective(t) for t in self.data['templates']
                if t.get('enabled') and t.get('mode') in MODES and t['id'] not in (exclude_tids or set())]

    def seen_refs(self, lesson_id: str) -> set[str]:
        les = study_lessons.lesson(lesson_id)
        if not les:
            return set()
        return set(self.path_state(les['skill'])['seen_refs'].get(lesson_id, []))

    def set_task_ref(self, uid: str, meta: dict):
        """記錄任務使用的參考圖，並加入該課的「看過」清單（重練同一課時換不同作品）"""
        t = self.task(uid)
        if not t:
            return
        t['ref'] = meta
        les = study_lessons.lesson(t['params'].get('lesson_id', ''))
        if les and meta.get('id'):
            seen = self.path_state(les['skill'])['seen_refs'].setdefault(les['id'], [])
            if meta['id'] not in seen:
                seen.append(meta['id'])
                del seen[:-30]   # 只記最近 30 張
        self.mark_dirty()

    def set_task_snapshot(self, uid: str, path: str, day_key: str | None = None):
        """記錄打卡快照路徑（day_key 省略時為今天的任務）"""
        tasks = self.data['days'].get(day_key, {}).get('tasks', []) if day_key else self.today_tasks()
        t = next((x for x in tasks if x['uid'] == uid), None)
        if t is not None:
            t['snapshot'] = path
            self.mark_dirty()

    def _advance_lesson(self, t: dict, rating: int | None) -> str | None:
        """打卡後依自評推進學習路徑；回傳下一課 id（未推進時回傳 None）"""
        les = study_lessons.lesson(t['params'].get('lesson_id', ''))
        if not les:
            return None
        st = self.path_state(les['skill'])
        st['attempts'][les['id']] = st['attempts'].get(les['id'], 0) + 1
        if rating is None or rating < PASS_RATING:
            return None
        if les['id'] not in st['passed']:
            st['passed'].append(les['id'])
        lessons = study_lessons.path(les['skill'])
        idx = next((i for i, l in enumerate(lessons) if l['id'] == les['id']), None)
        if idx is None or idx != min(st['index'], len(lessons) - 1) or idx + 1 >= len(lessons):
            return None   # 不是目前進度的那一課（例如重練舊課）或已是最後一課
        st['index'] = idx + 1
        return lessons[idx + 1]['id']

    def _pick(self, pool: list[dict], weights: list[float]) -> dict | None:
        if not pool or sum(weights) <= 0:
            return None
        return self.rng.choices(pool, weights=weights, k=1)[0]

    def _generate(self, day_key: str, exclude_tids: set[str] | None = None,
                  count: int | None = None, budget: float | None = None) -> list[dict]:
        s = self.settings
        enabled = self._enabled_templates(exclude_tids)
        if not enabled:
            return []
        lo, hi = int(s.get('count_min', 1)), int(s.get('count_max', 3))
        n = count if count is not None else self.rng.randint(max(1, min(lo, hi)), max(1, lo, hi))
        remaining = float(budget if budget is not None else s.get('budget_minutes', 60))

        yesterday = (datetime.strptime(day_key, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        y_tids = {t.get('template_id') for t in self.data['days'].get(yesterday, {}).get('tasks', [])}
        last = self._last_practiced()

        chosen: list[dict] = []
        for slot in range(n):
            pool = [t for t in enabled if t not in chosen]
            if any(c['mode'] == 'draw_time' for c in chosen):
                pool = [t for t in pool if t['mode'] != 'draw_time']   # 創作時長一天最多一項
            fits = [t for t in pool if est_minutes(t) <= remaining]
            if slot == 0 and n >= 2:
                # 多項課表時第一項優先排熱身（短時間速寫）
                warm = [t for t in fits if t['mode'] == 'sketch' and est_minutes(t) <= WARMUP_MAX_MINUTES]
                if warm:
                    fits = warm
            if not fits:
                if chosen:
                    break
                # 預算內沒有任何範本可選時，至少排一項最短的，避免當天沒有任務
                fits = [min(pool, key=est_minutes)] if pool else []
            pick = self._pick(fits, [self._weight(t, day_key, last, y_tids) for t in fits])
            if pick is None:
                break
            chosen.append(pick)
            remaining -= est_minutes(pick)
        return [self._make_task(t) for t in chosen]

    @staticmethod
    def _make_task(tpl: dict) -> dict:
        return {
            'uid': uuid.uuid4().hex[:12],
            'template_id': tpl['id'],
            'mode': tpl['mode'],
            'name': tpl['name'],
            'skills': copy.deepcopy(tpl.get('skills', {})),
            'params': copy.deepcopy(tpl.get('params', {})),
            'progress': 0,
            'target': target_of(tpl),
            'status': 'active',
            'self_reported': False,
            'checked_at': None,
            'note': '',
            'logged_seconds': 0,      # 已寫入練習紀錄的秒數（避免重複記錄）
        }

    # ── 課表調整 ──────────────────────────────────────────────────────────
    def rerolls_left(self) -> int:
        day = self.today()
        if not day:
            return 0
        return max(0, int(self.settings.get('rerolls_per_day', 1)) - day.get('rerolls_used', 0))

    def reroll(self, uid: str) -> str | None:
        """把一項尚未開始的任務換成另一項；成功回傳 None，失敗回傳原因"""
        day = self.today()
        t = self.task(uid)
        if not day or not t:
            return '找不到任務'
        if t['status'] != 'active' or t['progress'] > 0:
            return '已開始或已完成的任務不能更換'
        if self.rerolls_left() <= 0:
            return '今天的更換次數已用完'
        others = [o for o in day['tasks'] if o is not t]
        used = sum(est_minutes(o) for o in others)
        budget = max(est_minutes(t), float(self.settings.get('budget_minutes', 60)) - used)
        exclude = {o['template_id'] for o in day['tasks']}
        if any(o['mode'] == 'draw_time' for o in others):
            exclude |= {tp['id'] for tp in self.data['templates'] if tp.get('mode') == 'draw_time'}
        new = self._generate(self.data['current_day'], exclude_tids=exclude, count=1, budget=budget)
        if not new:
            return '沒有其他可替換的任務範本'
        if self.data.get('active_study') == uid:
            self.data['active_study'] = None
        day['tasks'][day['tasks'].index(t)] = new[0]
        day['rerolls_used'] = day.get('rerolls_used', 0) + 1
        self.mark_dirty()
        return None

    def addable_templates(self) -> list[dict]:
        """可手動加入今日的範本（已啟用且今天尚未出現）"""
        return self._enabled_templates({t['template_id'] for t in self.today_tasks()})

    def add_today(self, tid: str) -> dict | None:
        day = self.today()
        tpl = self.template(tid)
        if not day or not tpl:
            return None
        task = self._make_task(self._effective(tpl))
        day['tasks'].append(task)
        self.mark_dirty()
        return task

    # ── 進度 ──────────────────────────────────────────────────────────────
    def _set_progress(self, t: dict, value) -> bool:
        """更新進度；回傳是否剛達標（active → ready）"""
        t['progress'] = value
        self.mark_dirty()
        if t['status'] == 'active' and t['progress'] >= t['target']:
            t['status'] = 'ready'
            return True
        return False

    def tick(self, draw_delta: float, now: datetime | None = None,
             current_file: str | None = None) -> list[dict]:
        """主程式每秒呼叫：draw_delta = 這段期間 SAI2 的動筆秒數；current_file = 追蹤器目前的檔案。
        回傳剛達標的任務。"""
        self.ensure_today(now)
        if draw_delta <= 0:
            return []
        ready = []
        study_uid = self.data.get('active_study')
        tags = self.file_tags(current_file) if current_file else {}
        if tags and not study_uid:
            # 平常畫已標記技能的作品：動筆時間計入技能。研究計時中略過，那段時間打卡時已算進研究任務
            self._log(self.day_key(now), source='file', task_uid=None, topic=current_file,
                      skills=tags, seconds=draw_delta, count=0)
        for t in self.today_tasks():
            if t['status'] not in ('active', 'ready'):
                continue
            if t['mode'] == 'draw_time' or (t['mode'] == 'study' and t['uid'] == study_uid):
                if self._set_progress(t, t['progress'] + draw_delta):
                    ready.append(t)
        return ready

    def record_sketch(self, topic: str, seconds: float, quest_uid: str | None = None,
                      interval: int | None = None, now: datetime | None = None) -> list[dict]:
        """速寫視窗每完成一張有效圖時呼叫。

        quest_uid：從任務「前往」開啟且題目設定未被改動時傳入，進度直接計入該任務；
        否則計入第一個題目與間隔都相符的速寫任務。非任務練習仍會依題目記入技能。
        now：判斷任務日用的時間（預設為現在，測試時可指定）
        """
        self.ensure_today(now)
        task = None
        if quest_uid:
            t = self.task(quest_uid)
            if t and t['mode'] == 'sketch' and t['status'] in ('active', 'ready'):
                task = t
        if task is None:
            for t in self.today_tasks():
                p = t['params']
                if (t['mode'] == 'sketch' and t['status'] in ('active', 'ready')
                        and p.get('topic') == topic and (interval is None or p.get('interval') == interval)):
                    task = t
                    break
        if task is not None:
            skills = task['skills']
        else:
            skills = SKETCH_TOPIC_SKILLS.get(topic, {})
        self._log(self.data['current_day'], source='sketch', task_uid=task['uid'] if task else None,
                  topic=topic, skills=skills, seconds=seconds, count=1)
        if task is not None:
            task['logged_seconds'] = task.get('logged_seconds', 0) + seconds
            if self._set_progress(task, task['progress'] + 1):
                return [task]
        return []

    def add_count(self, uid: str, n: int) -> list[dict]:
        """反覆練習 / 縮圖：自行回報本次完成數"""
        t = self.task(uid)
        if not t or t['status'] not in ('active', 'ready') or n <= 0:
            return []
        return [t] if self._set_progress(t, t['progress'] + int(n)) else []

    # ── 範本與技能管理 ────────────────────────────────────────────────────
    def is_builtin_template(self, tid: str) -> bool:
        return any(t['id'] == tid for t in DEFAULT_TEMPLATES)

    def validate_template(self, tpl: dict) -> str | None:
        """檢查範本內容；合法回傳 None，否則回傳原因"""
        name = (tpl.get('name') or '').strip()
        if not name:
            return '請輸入名稱'
        if len(name) > MAX_TEMPLATE_NAME:
            return f'名稱最多 {MAX_TEMPLATE_NAME} 個字'
        mode = tpl.get('mode')
        if mode not in MODES:
            return '請選擇練習方式'
        skills = tpl.get('skills') or {}
        if any(not self.skill(sid) for sid in skills) or any(w <= 0 for w in skills.values()):
            return '技能設定不正確'
        try:
            if not 0.1 <= float(tpl.get('weight', 1.0)) <= 5:
                return '權重需介於 0.1～5'
        except (TypeError, ValueError):
            return '權重需介於 0.1～5'
        p = tpl.get('params') or {}

        def rng(key, lo, hi, label):
            v = p.get(key)
            if not isinstance(v, (int, float)) or not lo <= v <= hi:
                return f'{label}需介於 {lo}～{hi}'
            return None

        if mode == 'sketch':
            if not (p.get('topic') or '').strip():
                return '請選擇速寫題目'
            if p.get('interval') not in SKETCH_ALLOWED_INTERVALS:
                return '每張秒數不正確'
            return rng('count', 1, 200, '張數')
        if mode == 'study':
            if p.get('path'):
                return None if study_lessons.path(p['path']) else '學習路徑不存在'
            return rng('minutes', 5, 240, '分鐘數')
        if mode in ('drill', 'thumbnail'):
            return rng('count', 1, 999, '次數') or rng('est_minutes', 1, 240, '預估分鐘')
        if mode == 'draw_time':
            return rng('minutes', 5, 600, '分鐘數')
        return None

    def _clean_template(self, tpl: dict) -> dict:
        keep = {'sketch': ('topic', 'count', 'interval'), 'study': ('path', 'minutes'),
                'drill': ('count', 'est_minutes'), 'thumbnail': ('count', 'est_minutes'),
                'draw_time': ('minutes',)}[tpl['mode']]
        params = {k: v for k, v in (tpl.get('params') or {}).items() if k in keep and v not in (None, '')}
        return {'mode': tpl['mode'], 'name': tpl['name'].strip(), 'skills': dict(tpl.get('skills') or {}),
                'params': params, 'weight': float(tpl.get('weight', 1.0)),
                'enabled': bool(tpl.get('enabled', True))}

    def add_template(self, tpl: dict) -> tuple[str | None, str | None]:
        """新增自訂範本，回傳 (id, 錯誤)"""
        err = self.validate_template(tpl)
        if err:
            return None, err
        new = self._clean_template(tpl)
        new['id'] = 'u_' + uuid.uuid4().hex[:8]
        self.data['templates'].append(new)
        self.mark_dirty()
        return new['id'], None

    def update_template(self, tid: str, tpl: dict) -> str | None:
        cur = self.template(tid)
        if not cur:
            return '找不到範本'
        err = self.validate_template(tpl)
        if err:
            return err
        cur.update(self._clean_template(tpl))
        self.mark_dirty()
        return None

    def set_template_enabled(self, tid: str, on: bool):
        t = self.template(tid)
        if t:
            t['enabled'] = bool(on)
            self.mark_dirty()

    def delete_template(self, tid: str) -> str | None:
        """刪除自訂範本；內建範本只能停用（刪了下次啟動也會依版本規則補回）"""
        if self.is_builtin_template(tid):
            return '內建範本無法刪除，可以改為停用'
        before = len(self.data['templates'])
        self.data['templates'] = [t for t in self.data['templates'] if t.get('id') != tid]
        if len(self.data['templates']) == before:
            return '找不到範本'
        self.mark_dirty()
        return None

    def add_skill(self, name: str, icon: str = '⭐') -> tuple[str | None, str | None]:
        name = (name or '').strip()
        if not name:
            return None, '請輸入技能名稱'
        if len(name) > 12:
            return None, '技能名稱最多 12 個字'
        if any(s['name'] == name for s in self.data['skills']):
            return None, '已有同名技能'
        sid = 'u_' + uuid.uuid4().hex[:8]
        self.data['skills'].append({'id': sid, 'name': name, 'icon': (icon or '⭐').strip()[:2],
                                    'subtopics': [], 'builtin': False})
        self.mark_dirty()
        return sid, None

    def delete_skill(self, sid: str) -> str | None:
        s = self.skill(sid)
        if not s:
            return '找不到技能'
        if s.get('builtin') or any(d['id'] == sid for d in DEFAULT_SKILLS):
            return '內建技能無法刪除'
        users = [t['name'] for t in self.data['templates'] if sid in (t.get('skills') or {})]
        if users:
            return '仍有任務範本使用此技能：' + '、'.join(users[:3])
        self.data['skills'] = [x for x in self.data['skills'] if x['id'] != sid]
        for key in [k for k, v in self.data['file_tags'].items() if sid in v]:
            self.set_file_tags(key, [x for x in self.data['file_tags'][key] if x != sid])
        if self.settings.get('weekly_focus') == sid:
            self.settings['weekly_focus'] = ''
        self.mark_dirty()
        return None

    # ── 作品檔案技能標籤 ──────────────────────────────────────────────────
    def file_tags(self, file_key: str) -> dict[str, float]:
        return dict(self.data['file_tags'].get(file_key, {}))

    def set_file_tags(self, file_key: str, skill_ids: list[str]):
        """設定作品檔案的技能標籤（平均分配權重）；清空即移除"""
        valid = [sid for sid in dict.fromkeys(skill_ids) if self.skill(sid)]
        if valid:
            self.data['file_tags'][file_key] = {sid: round(1.0 / len(valid), 4) for sid in valid}
        else:
            self.data['file_tags'].pop(file_key, None)
        self.mark_dirty()

    def start_study(self, uid: str) -> bool:
        t = self.task(uid)
        if not t or t['mode'] != 'study' or t['status'] not in ('active', 'ready'):
            return False
        self.data['active_study'] = uid
        self.mark_dirty()
        return True

    def stop_study(self):
        if self.data.get('active_study'):
            self.data['active_study'] = None
            self.mark_dirty()

    @property
    def active_study(self) -> str | None:
        return self.data.get('active_study')

    # ── 打卡 ──────────────────────────────────────────────────────────────
    def check_in(self, uid: str, note: str = '', self_report: bool = False,
                 rating: int | None = None, ai_review: dict | None = None) -> str | None:
        """打卡；未達標時需 self_report=True（自行回報）。成功回傳 None，失敗回傳原因。
        rating：臨摹研究的評分 1~5（自評，或 AI 評鑑的分數）；≥PASS_RATING 時推進學習路徑，結果記於 task['advanced_to']。
        ai_review：AI 評鑑結果（分數、簡評；使用者改了分數時 overridden=True），記於 task['ai_review']。"""
        t = self.task(uid)
        if not t:
            return '找不到任務'
        if t['status'] == 'done':
            return '這項任務已經打卡'
        if t['status'] == 'expired':
            return '這項任務已過期'
        if t['status'] != 'ready' and not self_report:
            return '尚未達標'
        t['status'] = 'done'
        t['self_reported'] = t['progress'] < t['target']
        t['checked_at'] = datetime.now().isoformat(timespec='seconds')
        t['note'] = (note or '').strip()
        if rating is not None:
            t['rating'] = max(1, min(5, int(rating)))
        if ai_review:
            t['ai_review'] = dict(ai_review, overridden=t.get('rating') != ai_review.get('score'))
        t['advanced_to'] = self._advance_lesson(t, t.get('rating'))
        if self.data.get('active_study') == uid:
            self.data['active_study'] = None
        self._log_task_effort(t, self.data['current_day'])
        self.mark_dirty()
        return None

    # ── 練習紀錄 ──────────────────────────────────────────────────────────
    def _task_effort_seconds(self, t: dict) -> float:
        """任務的實際投入秒數（速寫已逐張記錄，不在此計算）"""
        mode = t['mode']
        if mode in ('study', 'draw_time'):
            return float(t['progress'])
        if mode in ('drill', 'thumbnail'):
            ratio = min(1.0, t['progress'] / max(1, t['target']))
            return est_minutes(t) * 60.0 * ratio
        return 0.0

    def _log_task_effort(self, t: dict, day_key: str):
        if t['mode'] == 'sketch':
            return
        if t['mode'] == 'draw_time' and not t['skills']:
            return   # 未標記技能的創作時長已在追蹤器的每日統計中，不重複計入技能
        seconds = self._task_effort_seconds(t) - t.get('logged_seconds', 0)
        if seconds <= 0:
            return
        self._log(day_key, source=t['mode'], task_uid=t['uid'], topic=None, skills=t['skills'],
                  seconds=seconds, count=t['progress'] if MODES[t['mode']]['unit'] == 'count' else 0)
        t['logged_seconds'] = t.get('logged_seconds', 0) + seconds

    def _log(self, day_key: str, source: str, task_uid, topic, skills: dict, seconds: float, count: int):
        """寫入練習紀錄；同一天、同來源、同任務、同題目的紀錄合併成一筆，避免逐張速寫讓檔案暴增"""
        entries = self.data['practice_log'].setdefault(day_key, [])
        for e in entries:
            if (e['source'] == source and e.get('task_uid') == task_uid and e.get('topic') == topic
                    and e.get('skills') == skills):
                e['seconds'] += seconds
                e['count'] += count
                break
        else:
            entries.append({'source': source, 'task_uid': task_uid, 'topic': topic,
                            'skills': copy.deepcopy(skills), 'seconds': seconds, 'count': count})
        self.mark_dirty()

    def skill_seconds(self, since_day: str | None = None) -> dict[str, float]:
        """各技能累積投入秒數（依權重分配）；since_day 指定時只計該日（含）之後"""
        out: dict[str, float] = {}
        for day, entries in self.data['practice_log'].items():
            if since_day and day < since_day:
                continue
            for e in entries:
                skills = e.get('skills') or {}
                total_w = sum(skills.values()) or 1.0
                for sid, w in skills.items():
                    out[sid] = out.get(sid, 0.0) + e['seconds'] * w / total_w
        return out

    # ── 連續天數 ──────────────────────────────────────────────────────────
    def day_done(self, key: str) -> bool:
        return any(t.get('status') == 'done' for t in self.data['days'].get(key, {}).get('tasks', []))

    def is_rest(self, key: str) -> bool:
        return bool(self.data['days'].get(key, {}).get('rest'))

    def streak(self, now: datetime | None = None) -> int:
        """連續打卡天數：任務日至少打卡 1 項即延續（+1）；休息日延續但不加天數；
        今天尚未打卡也未請假時從昨天起算，不中斷"""
        cur = datetime.strptime(self.day_key(now), '%Y-%m-%d')
        today = cur.strftime('%Y-%m-%d')
        if not self.day_done(today) and not self.is_rest(today):
            cur -= timedelta(days=1)
        n = 0
        while True:
            key = cur.strftime('%Y-%m-%d')
            if self.day_done(key):
                n += 1
            elif not self.is_rest(key):
                break
            cur -= timedelta(days=1)
        return n

    def longest_streak(self) -> int:
        """歷史最長連續打卡天數（規則同 streak）"""
        keys = sorted(k for k in self.data['days'] if self.day_done(k) or self.is_rest(k))
        best = run = 0
        prev = None
        for k in keys:
            d = datetime.strptime(k, '%Y-%m-%d')
            if prev is None or (d - prev).days != 1:
                run = 0
            run += 1 if self.day_done(k) else 0
            best = max(best, run)
            prev = d
        return best

    # ── 休息日 ────────────────────────────────────────────────────────────
    @staticmethod
    def _week_keys(key: str) -> list[str]:
        """同一週（週一到週日）的任務日 key"""
        d = datetime.strptime(key, '%Y-%m-%d')
        monday = d - timedelta(days=d.weekday())
        return [(monday + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]

    def rest_used_in_week(self, key: str) -> int:
        return sum(1 for k in self._week_keys(key) if self.is_rest(k))

    def rest_quota(self) -> int:
        return max(0, int(self.settings.get('rest_days_per_week', 1)))

    def can_rest(self, key: str, now: datetime | None = None) -> str | None:
        """可否把 key 這天設為休息日；可以回傳 None，否則回傳原因。
        只允許今天或昨天（忘了請假時可補請昨天），且受每週次數限制。"""
        today = datetime.strptime(self.day_key(now), '%Y-%m-%d')
        d = datetime.strptime(key, '%Y-%m-%d')
        if (today - d).days not in (0, 1):
            return '只能將今天或昨天設為休息日'
        if self.is_rest(key):
            return '這天已經是休息日'
        if self.day_done(key):
            return '這天已有打卡，不需要請假'
        quota = self.rest_quota()
        if self.rest_used_in_week(key) >= quota:
            return f'本週的休息日已用完（每週 {quota} 天）'
        return None

    def take_rest(self, key: str, now: datetime | None = None) -> str | None:
        """設為休息日：連續天數不中斷。今天請假後任務仍可照常完成打卡。"""
        err = self.can_rest(key, now)
        if err:
            return err
        day = self.data['days'].setdefault(key, {'rerolls_used': 0, 'tasks': []})
        day['rest'] = True
        self.mark_dirty()
        return None

    def cancel_rest(self, key: str) -> bool:
        day = self.data['days'].get(key)
        if not day or not day.get('rest'):
            return False
        day.pop('rest', None)
        self.mark_dirty()
        return True

    # ── 顯示輔助 ──────────────────────────────────────────────────────────
    @staticmethod
    def progress_text(t: dict) -> str:
        unit = MODES[t['mode']]['unit']
        if unit == 'seconds':
            return f"{int(t['progress'] // 60)}/{t['target'] // 60} 分"
        suffix = '張' if t['mode'] in ('sketch', 'thumbnail') else '個'
        return f"{int(t['progress'])}/{t['target']} {suffix}"

    @staticmethod
    def progress_ratio(t: dict) -> float:
        return max(0.0, min(1.0, t['progress'] / max(1, t['target'])))
