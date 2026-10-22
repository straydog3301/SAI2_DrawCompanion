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

SETTINGS_VERSION = 2

DEFAULTS: dict = {
    'version': SETTINGS_VERSION,
    'language': 'zh_tw',
    'autostart': False,
    'sai2_exe': '',                       # SAI2 執行時自動記下
    'data_path': '',                      # 空白 = APP_DIR/sai2_draw_time.json
    'idle_timeout': 10.0,
    'track_unsaved': False,
    'pet': {
        'pack': '',                       # 空白 = 內建角色
        'size': 128,                      # 顯示大小（邏輯 px）
        'opacity': 1.0,
        'snap_edges': False,
        'fade_when_drawing': True,        # 動筆時變半透明
        'drawing_opacity': 0.55,
        'rest_minutes': 50,               # 連續動筆多久提醒休息（0 = 不提醒）
        'bubbles': 'important',           # all / important / off
        'night_sleep': False,             # 夜間（23～6 點）顯示睡覺
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
               'interval': 60, 'grayscale': False},
    'study': {'canvas_dir': '', 'canvas_side': 2000},   # canvas_side：練習畫布長邊（px）          # 空白 = 文件\SAI2 練習
    'ref': {                              # 參考小窗：位置與寬度依模式分別記住
        'sketch': {'w': 240, 'x': None, 'y': None},
        'study': {'w': 260, 'x': None, 'y': None},
        'through_opacity': 0.5,
    },
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
}


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
                # 新版本加入的設定（例如參考圖來源）若是空的，從 1.x 補帶入
                self._import_legacy(only_missing=True, keys=[k for k in _LEGACY_KEYS if '.' in _LEGACY_KEYS[k]])
                self.data['version'] = SETTINGS_VERSION
                self.save()

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
            if only_missing and self.get(dst) not in (None, '', DEFAULTS_FLAT.get(dst)):
                continue
            self.set(dst, old[k])

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
