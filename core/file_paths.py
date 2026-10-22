# -*- coding: utf-8 -*-
"""
file_paths.py - 由追蹤紀錄的檔案 key 反推實際路徑（不含 UI；自 1.x main.py 移入並補上使用者資料夾格式）

SAI2 標題會顯示路徑，tracker 把斜線換成「 _ 」當作 key，常見兩種：
  「本機磁碟 (D:) _ 2026 _ 0621.sai2」 → D:\\2026\\0621.sai2
  「Artist _ AppData _ Local _ Temp _ x.psd」（使用者資料夾底下）→ C:\\Users\\Artist\\AppData\\Local\\Temp\\x.psd
都找不到時，退回舊格式（底線分隔）在各磁碟與常用資料夾窮舉。可能耗時，請在背景執行緒呼叫。
"""

from __future__ import annotations

import itertools
import os
import re
import string


def _users_root() -> str:
    home = os.path.expanduser('~')
    return os.path.dirname(home)


def candidates_from_key(key: str, users_root: str | None = None) -> list[str]:
    """依 ' _ ' 格式推出的候選路徑（不檢查是否存在）"""
    if ' _ ' not in key:
        return []
    parts = key.split(' _ ')
    out = []
    m = re.search(r'\(([A-Za-z]:)\)', parts[0])
    if m and len(parts) > 1:
        out.append(m.group(1).upper() + '\\' + '\\'.join(parts[1:]))
    root = users_root or _users_root()
    out.append(os.path.join(root, *parts))
    return out


def resolve_file_key(key: str, users_root: str | None = None, search_roots: list[str] | None = None,
                     isfile=os.path.isfile) -> str | None:
    for p in candidates_from_key(key, users_root):
        if isfile(p):
            return p
    # 舊格式：以 '_' 拆分並窮舉哪些底線其實是路徑分隔
    if search_roots is None:
        search_roots = [f'{d}:\\' for d in string.ascii_uppercase if os.path.exists(f'{d}:\\')]
        home = os.path.expanduser('~')
        for sub in ('Documents', 'Desktop', 'Pictures', 'Downloads', '圖片', '桌面', '文件'):
            p = os.path.join(home, sub)
            if os.path.isdir(p):
                search_roots.append(p)
    parts = key.split('_')
    n = min(len(parts) - 1, 12)
    for combo in itertools.product([False, True], repeat=n):
        comps, cur = [], parts[0]
        for i, is_sep in enumerate(combo):
            if is_sep:
                comps.append(cur)
                cur = parts[i + 1]
            else:
                cur = cur + '_' + parts[i + 1]
        comps.append(cur)
        rel = os.path.join(*comps)
        for root in search_roots:
            full = os.path.join(root, rel)
            if isfile(full):
                return full
    return None


def display_name(key: str) -> str:
    """清單顯示用：只取最後一段檔名"""
    return key.split(' _ ')[-1] if ' _ ' in key else key
