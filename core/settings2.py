# -*- coding: utf-8 -*-
"""
settings2.py - 2.0 的設定檔（不含 UI）

存在 drawcompanion2_settings.json，與 1.x 的 sai2_timer_settings.json 分開，兩版同時存在時不會互相覆蓋。
第一次建立時從 1.x 設定帶入共用的值（紀錄檔位置、閒置秒數、語言…）。
"""

from __future__ import annotations

import copy
import json
import os

from core import hotkeys

SETTINGS_FILE = 'drawcompanion2_settings.json'
LEGACY_SETTINGS_FILE = 'sai2_timer_settings.json'

SETTINGS_VERSION = 4

DEFAULTS: dict = {
    'version': SETTINGS_VERSION,
    'language': 'zh_tw',
    'autostart': False,
    'sai2_exe': '',                       # SAI2 執行時自動記下
    'data_path': '',                      # 空白 = APP_DIR/sai2_draw_time.json
    'idle_timeout': 10.0,
    'track_unsaved': False,
    'exclude_folders': [],                # 不記錄的資料夾（core/exclusions.py）
    'pet': {
        'pack': '',                       # 空白 = 內建角色
        'size': 128,                      # 顯示大小（邏輯 px）
        'opacity': 1.0,
        'snap_edges': False,
        'fade_when_drawing': True,        # 動筆時變半透明
        'drawing_opacity': 0.55,
        'bubbles': 'important',           # all / important / off
        'bubble_skin': {'image': '', 'text': None, 'color': '#1b1a22', 'scale': 1.0},   # core/bubble_skin.py
        'show_timer': True,               # 寵物下方顯示本次動筆時間與錄影開關
        'tint_builtin': True,             # 內建角色「墨墨」跟隨主題色
    },
    'panel': {
        'blocks': ['progress', 'quests', 'recent', 'slots'],
        'recent_count': 4,
        'slots': ['sketch', 'study', 'snapshot', 'record', 'works', 'open_sai2'],
    },
    'hotkeys': {k: v[1] for k, v in hotkeys.ACTIONS.items()},
    'sources': {                          # 參考圖來源（速寫與研究共用）
        'unsplash_key': '',
        'pexels_key': '',
        'local_dir': '',
    },
    'sketch': {'source': 'local', 'category': 'pose', 'custom_query': '', 'local_category': '',
               'interval': 60, 'grayscale': False,
               'count_mode': 'draw',          # draw：在 SAI2 下筆時才倒數；clock：一直倒數
               'auto_canvas': True,           # 開始一輪速寫時建立畫布並在 SAI2 開啟（一輪一張）
               'canvas': 'a4_land', 'canvas_w': 3508, 'canvas_h': 2480},   # 畫布尺寸（core/study_tools.SKETCH_CANVAS）
    'study': {'canvas_dir': '', 'canvas_side': 2000},   # canvas_dir 空白 = 文件\SAI2 練習；canvas_side：長邊 px
    'timelapse': {'enabled': False, 'multiplier': 5, 'target': 'canvas', 'quality': 'standard', 'fps': 30,
                  'output_dir': ''},      # output_dir 空白 = APP_DIR/videos
    'works': {'groups': {}, 'sort': 'recent', 'thumbnails': True},   # thumbnails：存檔、停筆時自動擷取作品縮圖
    'ref': {                              # 參考小窗：位置與寬度依模式分別記住
        'sketch': {'w': 240, 'x': None, 'y': None},
        'study': {'w': 260, 'x': None, 'y': None},
        'through_opacity': 0.5,
    },
    'rules': [                            # 「如果…就…」規則（core/rules.py）；休息提醒也是一條規則
        {'id': 'rest', 'enabled': True, 'trigger': {'type': 'draw_minutes', 'value': 50},
         'actions': [{'type': 'bubble', 'value': '已經連續畫了 50 分鐘，起來喝口水、動一動吧'},
                     {'type': 'pet', 'value': 'rest'}]},
    ],
    'theme': {'accent': 'purple', 'mode': 'dark', 'reduce_motion': False},
    'prompted': {},                       # 一次性提醒是否已出現過
    'first_run_at': '',
}

# 1.x 設定中與 2.0 共用的鍵：1.x 鍵名 → 2.0 路徑
_LEGACY_KEYS = {
    'language': 'language', 'data_path': 'data_path', 'idle_timeout': 'idle_timeout',
    'track_unsaved': 'track_unsaved',
    'sketch_unsplash_key': 'sources.unsplash_key', 'sketch_pexels_key': 'sources.pexels_key',
    'sketch_local_dir': 'sources.local_dir', 'sketch_source_mode': 'sketch.source',
    'sketch_category': 'sketch.category', 'sketch_custom_query': 'sketch.custom_query',
    'sketch_local_category': 'sketch.local_category', 'sketch_interval': 'sketch.interval',
    'sketch_grayscale': 'sketch.grayscale', 'study_canvas_dir': 'study.canvas_dir',
    'timelapse_multiplier_str': 'timelapse.multiplier', 'timelapse_target_str': 'timelapse.target',
    'timelapse_quality': 'timelapse.quality', 'timelapse_fps': 'timelapse.fps',
    'timelapse_output_dir': 'timelapse.output_dir', 'custom_groups': 'works.groups',
}
TIMELAPSE_TARGETS = ('canvas', 'canvas_float', 'window', 'screen')


def _legacy_value(key: str, value):
    """1.x 的顯示字串轉成 2.0 的值（倍速「5x (167ms)」→ 5、舊版中文錄製範圍 → 代碼）"""
    import re
    if key == 'timelapse_multiplier_str':
        m = re.match(r'^(\d+)x', str(value))
        return int(m.group(1)) if m else 5
    if key == 'timelapse_target_str':
        v = str(value)
        if v in TIMELAPSE_TARGETS:
            return v
        if '浮動' in v or 'float' in v.lower():
            return 'canvas_float'
        if '螢幕' in v or 'screen' in v.lower():
            return 'screen'
        if '視窗' in v or 'window' in v.lower():
            return 'window'
        return 'canvas'
    return value


def _flatten(d: dict, prefix: str = '') -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flatten(v, f'{prefix}{k}.'))
        else:
            out[f'{prefix}{k}'] = v
    return out


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings2:
    def __init__(self, app_dir: str):
        self.app_dir = app_dir
        self.path = os.path.join(app_dir, SETTINGS_FILE)
        self.data: dict = {}
        self.imported_legacy = False
        self.load()

    def load(self):
        raw = None
        try:
            with open(self.path, encoding='utf-8') as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raw = None
        except (OSError, ValueError):
            raw = None
        if raw is None:
            self.data = copy.deepcopy(DEFAULTS)
            self._import_legacy(only_missing=False)
            self.save()
        else:
            self.data = _merge(DEFAULTS, raw)
            if int(raw.get('version', 1)) < SETTINGS_VERSION:
                if int(raw.get('version', 1)) < 4:
                    self._reminders_to_rules(raw)
                # 新版本加入的設定（例如參考圖來源）若是空的，從 1.x 補帶入
                self._import_legacy(only_missing=True, keys=[k for k in _LEGACY_KEYS if '.' in _LEGACY_KEYS[k]])
                self.data['version'] = SETTINGS_VERSION
                self.save()

    def _reminders_to_rules(self, raw: dict):
        """v3 以前寵物設定裡的「連續動筆提醒休息」「夜間顯示睡覺」改成規則"""
        old = raw.get('pet') if isinstance(raw.get('pet'), dict) else {}
        pet = self.data.get('pet', {})
        pet.pop('rest_minutes', None)
        pet.pop('night_sleep', None)
        rules = list(raw.get('rules') or [])
        add = []
        try:
            rest = int(old.get('rest_minutes', 50))
        except (TypeError, ValueError):
            rest = 50
        if rest > 0 and not any((r.get('trigger') or {}).get('type') == 'draw_minutes' for r in rules):
            add.append({'id': 'rest', 'enabled': True, 'trigger': {'type': 'draw_minutes', 'value': rest},
                        'actions': [{'type': 'bubble', 'value': f'已經連續畫了 {rest} 分鐘，起來喝口水、動一動吧'},
                                    {'type': 'pet', 'value': 'rest'}]})
        if old.get('night_sleep') and not any((r.get('trigger') or {}).get('type') == 'after_time' for r in rules):
            add.append({'id': 'night', 'enabled': True, 'trigger': {'type': 'after_time', 'value': '23:00'},
                        'actions': [{'type': 'pet', 'value': 'sleep'}]})
        self.data['rules'] = add + rules

    @property
    def bubbles_dir(self) -> str:
        return os.path.join(self.app_dir, 'bubbles')

    def _import_legacy(self, only_missing: bool, keys=None):
        try:
            with open(os.path.join(self.app_dir, LEGACY_SETTINGS_FILE), encoding='utf-8') as f:
                old = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(old, dict):
            return
        self.imported_legacy = True
        for k in keys or _LEGACY_KEYS:
            if k not in old:
                continue
            dst = _LEGACY_KEYS[k]
            cur = self.get(dst)
            if only_missing and cur not in (None, '', {}) and cur != DEFAULTS_FLAT.get(dst):
                continue
            self.set(dst, _legacy_value(k, old[k]))

    def save(self):
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # 便利存取
    def get(self, dotted: str, default=None):
        cur = self.data
        for part in dotted.split('.'):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, dotted: str, value):
        parts = dotted.split('.')
        cur = self.data
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    @property
    def data_path(self) -> str:
        return self.data.get('data_path') or os.path.join(self.app_dir, 'sai2_draw_time.json')

    @property
    def quests_path(self) -> str:
        return os.path.join(self.app_dir, 'daily_quests.json')

    @property
    def videos_dir(self) -> str:
        return self.get('timelapse.output_dir') or os.path.join(self.app_dir, 'videos')

    @property
    def pets_dir(self) -> str:
        return os.path.join(self.app_dir, 'pets')

    def sketch_opts(self) -> dict:
        """速寫圖源用的平面設定（core.sketch_source 使用）"""
        sk, src = self.data['sketch'], self.data['sources']
        return {**sk, 'unsplash_key': src.get('unsplash_key', ''), 'pexels_key': src.get('pexels_key', ''),
                'local_dir': src.get('local_dir', '')}

    def refs_settings(self) -> dict:
        """研究參考圖用（core.study_refs 沿用 1.x 的鍵名）"""
        src = self.data['sources']
        return {'sketch_unsplash_key': src.get('unsplash_key', ''), 'sketch_pexels_key': src.get('pexels_key', ''),
                'sketch_local_dir': src.get('local_dir', '')}

    def was_prompted(self, key: str) -> bool:
        return bool(self.data.get('prompted', {}).get(key))

    def mark_prompted(self, key: str):
        self.data.setdefault('prompted', {})[key] = True


DEFAULTS_FLAT = _flatten(DEFAULTS)
