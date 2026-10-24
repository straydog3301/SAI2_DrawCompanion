# -*- coding: utf-8 -*-
"""
data_text.py - 內建資料的顯示文字（docs/UI_2.0_PLAN.md §14，不含 UI）

內建的技能、任務範本、練習方式、課程以 id 對應翻譯表；資料檔裡存的仍是原文（繁中）。
- 翻譯表放在 locales/data_<語言>.json，格式：
      {"skill": {"color": {"name": "Color"}},
       "template": {"t_sk_pose": {"name": "Gesture sketch"}},
       "mode": {"sketch": {"name": "Timed sketch"}},
       "lesson": {"value_1": {"name": "...", "goal": "...", "focus": "...", "look_for": "...",
                              "phases": [{"name": "...", "tip": "..."}], "mistakes": [...], "checks": [...]}}}
- 使用者自建的項目、或改過名稱的內建項目，一律顯示使用者寫的文字
- 繁中（預設）不需要翻譯表；2.0 介面目前只有繁中，之後加語言只要補表並呼叫 set_language
"""

from __future__ import annotations

import copy
import json
import os

from core.paths import APP_DIR

DEFAULT_LANG = 'zh_tw'
_lang = DEFAULT_LANG
_tables: dict[str, dict] = {}
LESSON_FIELDS = ('name', 'goal', 'focus', 'look_for')
LESSON_LISTS = ('mistakes', 'checks')


def locales_dirs() -> list[str]:
    import sys
    dirs = [os.path.join(APP_DIR, 'locales')]
    base = getattr(sys, '_MEIPASS', None)          # 打包後的內建翻譯
    if base:
        dirs.append(os.path.join(base, 'locales'))
    return dirs


def set_language(lang: str):
    global _lang
    _lang = lang or DEFAULT_LANG


def language() -> str:
    return _lang


def _table(lang: str) -> dict:
    if lang == DEFAULT_LANG:
        return {}
    if lang not in _tables:
        data = {}
        for d in locales_dirs():
            p = os.path.join(d, f'data_{lang}.json')
            try:
                with open(p, encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
                    break
            except (OSError, ValueError):
                continue
        _tables[lang] = data
    return _tables[lang]


def load_table(lang: str, table: dict):
    """測試或外掛直接提供翻譯表"""
    _tables[lang] = table


def _entry(kind: str, item_id: str) -> dict:
    e = _table(_lang).get(kind, {}).get(item_id)
    return e if isinstance(e, dict) else {}


# ── 內建原文（判斷使用者是否改過名稱）──
def _originals() -> dict:
    from core import daily_quests as DQ
    return {
        'skill': {s['id']: s['name'] for s in DQ.DEFAULT_SKILLS},
        'template': {t['id']: t['name'] for t in DQ.DEFAULT_TEMPLATES},
        'mode': {k: v['name'] for k, v in DQ.MODES.items()},
    }


_ORIG: dict | None = None


def original(kind: str, item_id: str) -> str | None:
    global _ORIG
    if _ORIG is None:
        _ORIG = _originals()
    return _ORIG.get(kind, {}).get(item_id)


def name(kind: str, item_id: str, stored: str) -> str:
    """kind：skill / template / mode；stored：資料裡存的名稱。自建或改過名稱的項目回傳 stored"""
    orig = original(kind, item_id)
    if orig is None or stored != orig:
        return stored
    return _entry(kind, item_id).get('name') or stored


def skill_name(skill: dict | None) -> str:
    return name('skill', skill.get('id', ''), skill.get('name', '')) if skill else ''


def template_name(tpl: dict) -> str:
    return name('template', tpl.get('id', ''), tpl.get('name', ''))


def task_name(task: dict) -> str:
    """今日任務：名稱是排課表當下從範本複製的"""
    return name('template', task.get('template_id', ''), task.get('name', ''))


def mode_name(mode: str) -> str:
    from core.daily_quests import MODES
    return name('mode', mode, MODES.get(mode, {}).get('name', mode))


def lesson(les: dict | None) -> dict | None:
    """課程內容（study_lessons 的資料）換成目前語言；沒有翻譯時原樣回傳"""
    if not les:
        return les
    e = _entry('lesson', les['id'])
    if not e:
        return les
    out = copy.deepcopy(les)
    for k in LESSON_FIELDS:
        if e.get(k):
            out[k] = e[k]
    for k in LESSON_LISTS:
        if isinstance(e.get(k), list) and len(e[k]) == len(les[k]):
            out[k] = list(e[k])
    phases = e.get('phases')
    if isinstance(phases, list) and len(phases) == len(les['phases']):
        for ph, tr in zip(out['phases'], phases):
            if isinstance(tr, dict):
                ph['name'] = tr.get('name') or ph['name']
                ph['tip'] = tr.get('tip') or ph['tip']
    return out


def coverage(lang: str) -> dict:
    """翻譯表缺了哪些內建項目（補翻譯時檢查用）：{kind: [id…]}"""
    from core import study_lessons
    t = _table(lang)
    global _ORIG
    if _ORIG is None:
        _ORIG = _originals()
    missing = {k: [i for i in ids if i not in t.get(k, {})] for k, ids in _ORIG.items()}
    missing['lesson'] = [l['id'] for l in study_lessons.LESSONS if l['id'] not in t.get('lesson', {})]
    return missing
