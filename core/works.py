# -*- coding: utf-8 -*-
"""
works.py - 作品清單（不含 UI；分組、顯示名稱、影片資料夾自 1.x main.py 移入）

檔案 key 是追蹤器由 SAI2 標題組成的路徑字串（「本機磁碟 (D:) _ 2026 _ 0621.sai2」）。
"""

from __future__ import annotations

import os
import re

from core.file_paths import display_name
from core.timelapse import file_key_to_subdir

VIDEO_EXTS = ('.mp4', '.gif', '.webm', '.mov')
SORTS = [('recent', '最近'), ('draw', '動筆時數'), ('name', '名稱')]


def auto_group(key: str) -> str:
    """依路徑第一層資料夾自動分組（跳過磁碟機標籤）"""
    if ' _ ' in key:
        parts = key.split(' _ ')
        if parts and re.search(r'\([A-Za-z]:\)', parts[0]):
            parts = parts[1:]
        if len(parts) > 1:
            return parts[0]
    return '根目錄'


def rows(files: dict, groups: dict | None = None, tags=None) -> list[dict]:
    """[{key, name, group, open, draw, eff, sessions, last_seen, tags}]；tags(key) -> {技能: 權重}"""
    out = []
    for key, rec in (files or {}).items():
        op = float(rec.get('open_seconds', 0) or 0)
        dr = float(rec.get('draw_seconds', 0) or 0)
        out.append({'key': key, 'name': display_name(key), 'group': (groups or {}).get(key) or auto_group(key),
                    'open': op, 'draw': dr, 'eff': min(1.0, dr / op) if op > 0 else 0.0,
                    'sessions': int(rec.get('sessions', 0) or 0), 'last_seen': rec.get('last_seen', '') or '',
                    'tags': tags(key) if tags else {}})
    return out


def sort_rows(items: list[dict], by: str = 'recent') -> list[dict]:
    if by == 'draw':
        return sorted(items, key=lambda r: -r['draw'])
    if by == 'name':
        return sorted(items, key=lambda r: r['name'].lower())
    return sorted(items, key=lambda r: r['last_seen'], reverse=True)


def filter_rows(items: list[dict], query: str = '', group: str = '') -> list[dict]:
    q = (query or '').strip().lower()
    return [r for r in items
            if (not q or q in r['name'].lower() or q in r['group'].lower())
            and (not group or r['group'] == group)]


def video_dir(output_dir: str, key: str) -> str:
    return os.path.join(output_dir, file_key_to_subdir(key))


def videos(output_dir: str, key: str) -> list[str]:
    d = video_dir(output_dir, key)
    try:
        files = [os.path.join(d, n) for n in os.listdir(d) if n.lower().endswith(VIDEO_EXTS)]
    except OSError:
        return []
    return sorted(files, key=os.path.getmtime, reverse=True)


def lesson_attempts(quests, lesson_id: str) -> list[dict]:
    """某堂課歷次的研究任務（新到舊）：{day, status, rating, note, snapshot, ref_title}"""
    out = []
    for day in sorted(quests.data.get('days', {}), reverse=True):
        for t in quests.data['days'][day].get('tasks', []):
            if t.get('mode') == 'study' and (t.get('params') or {}).get('lesson_id') == lesson_id:
                ref = t.get('ref') or {}
                out.append({'day': day, 'status': t.get('status'), 'rating': t.get('rating'),
                            'note': t.get('note') or '', 'snapshot': t.get('snapshot') or '',
                            'ref_title': ' / '.join(x for x in (ref.get('title'), ref.get('artist')) if x)})
    return out
