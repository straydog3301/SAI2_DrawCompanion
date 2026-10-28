# -*- coding: utf-8 -*-
"""
slots.py - 快捷面板的區塊與 6 格快捷按鈕（不含 UI）

按鈕可以是內建動作（字串，例如 'sketch'），或自訂動作（dict）：
    {'type': 'path',    'label': '參考資料夾', 'target': 'D:\\refs'}          開啟檔案或資料夾
    {'type': 'program', 'label': 'PureRef',   'target': 'C:\\...\\PureRef.exe', 'args': ''}
    {'type': 'url',     'label': 'Pinterest', 'target': 'https://www.pinterest.com'}
None 代表空格。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import webbrowser

SLOT_COUNT = 6
BLOCKS = {'progress': '今日進度與連續天數', 'quests': '每日任務', 'recent': '最近開啟', 'slots': '快捷按鈕'}
BUILTIN = {
    'sketch': ('速寫', 'sketch', '開始一輪速寫（用上次的題目與間隔）'),
    'study': ('研究', 'study', '繼續今天的研究任務'),
    'snapshot': ('快照', 'snapshot', '擷取 SAI2 畫布存成圖片'),
    'record': ('錄影', 'record', '縮時錄影：開始／停止'),
    'works': ('作品', 'works', '打開最近作品所在的資料夾'),
    'open_sai2': ('SAI2', 'open_sai2', '開啟或切換到 SAI2'),
    'new_canvas': ('新畫布', 'canvas', '在 SAI2 開新畫布（SAI2 的新增畫布視窗；不用先存檔也會記錄）'),
    'main': ('主視窗', 'home', '打開主視窗（今日）'),
    'growth': ('成長', 'flame', '打開成長頁'),
}
CUSTOM = {'path': ('開啟檔案或資料夾', 'works'), 'program': ('執行程式', 'play'), 'url': ('開啟網址', 'link')}


def describe(entry) -> tuple[str, str, str]:
    """(按鈕文字, 圖示, 說明)"""
    if isinstance(entry, str):
        return BUILTIN.get(entry, (entry, 'more', ''))
    if isinstance(entry, dict) and entry.get('type') in CUSTOM:
        kind, ic = CUSTOM[entry['type']]
        target = entry.get('target', '')
        text = (entry.get('label') or os.path.basename(target.rstrip('\\/')) or kind)[:6]
        return text, ic, f'{kind}：{target}'
    return '', 'more', ''


def validate(entry) -> str | None:
    if entry is None or isinstance(entry, str):
        return None if entry is None or entry in BUILTIN else f'不認得的動作：{entry}'
    t = entry.get('type')
    target = (entry.get('target') or '').strip()
    if t not in CUSTOM:
        return '不認得的動作類型'
    if not target:
        return '請填入目標'
    if t == 'url' and not target.lower().startswith(('http://', 'https://')):
        return '網址需要以 http:// 或 https:// 開頭'
    if t in ('path', 'program') and not os.path.exists(target):
        return '找不到這個檔案或資料夾'
    return None


def run_custom(entry: dict, startfile=None, popen=None, browser=None) -> str | None:
    """執行自訂動作；失敗回傳原因"""
    err = validate(entry)
    if err:
        return err
    t, target = entry['type'], entry['target'].strip()
    try:
        if t == 'url':
            (browser or webbrowser.open)(target)
        elif t == 'path':
            (startfile or os.startfile)(target)
        else:
            # Windows 風格的參數（posix=False 保留反斜線），再去掉包住參數的引號，交給 Popen 重新加引號
            args = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a
                    for a in shlex.split(entry.get('args') or '', posix=False)]
            (popen or subprocess.Popen)([target] + args, cwd=os.path.dirname(target) or None)
    except OSError as e:
        return str(e)
    return None


def normalize_slots(slots) -> list:
    out = list(slots or [])[:SLOT_COUNT]
    return out + [None] * (SLOT_COUNT - len(out))


def normalize_blocks(blocks) -> list[str]:
    """區塊順序（未列出的區塊視為關閉）"""
    return [b for b in (blocks or []) if b in BLOCKS]
