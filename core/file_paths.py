# -*- coding: utf-8 -*-
"""
file_paths.py - SAI2 標題路徑 ↔ 追蹤紀錄的檔案 key ↔ 實際路徑（不含 UI）

SAI2 標題顯示的是「在 SAI2 檔案瀏覽器裡走到這個檔案的路徑」（Windows 殼層的顯示名稱，例如「下載」「使用者」），
不是實際路徑；tracker 把「/」換成「 _ 」當作 key。同一個檔案依開啟方式、SAI2 版本會有不同寫法：

  舊版 SAI2（既有紀錄的寫法，視為標準）        2026-10 起的 SAI2
  SSD磁碟區 (E:) _ CR _ a.png                本機 _ SSD磁碟區 (E:) _ CR _ a.png
  Auer0807 _ 下載 _ b.png                    本機 _ Windows (C:) _ 使用者 _ auer0807 _ 下載 _ b.png
  桌面 _ c.png（桌面上的檔案）                c.png
  暫存 _ d.sai2（桌面上的資料夾）              暫存 _ d.sai2，或 本機 _ … _ auer0807 _ 桌面 _ 暫存 _ d.sai2

canonical_key 把各種寫法換成標準寫法（同一個檔案只有一筆紀錄）；resolve_file_key 由 key 找出實際檔案
（顯示名稱與實際資料夾名稱不同時，例如「下載」→ Downloads，用 Windows 的顯示名稱比對）。
"""

from __future__ import annotations

import itertools
import os
import re
import string

SEP = ' _ '
_DRIVE = re.compile(r'\(([A-Za-z]:)\)')
_NAMES: dict | None = None


# ─── Windows 殼層的顯示名稱 ──
def shell_display_name(path: str) -> str | None:
    """檔案總管顯示的名稱（例如 C:\\Users → 「使用者」、Downloads → 「下載」）"""
    try:
        import ctypes
        from ctypes import wintypes

        class SHFILEINFOW(ctypes.Structure):
            _fields_ = [('hIcon', wintypes.HICON), ('iIcon', ctypes.c_int), ('dwAttributes', wintypes.DWORD),
                        ('szDisplayName', wintypes.WCHAR * 260), ('szTypeName', wintypes.WCHAR * 80)]
        info = SHFILEINFOW()
        if ctypes.windll.shell32.SHGetFileInfoW(path, 0, ctypes.byref(info), ctypes.sizeof(info), 0x200):   # SHGFI_DISPLAYNAME
            return info.szDisplayName or None
    except Exception:
        pass
    return None


def _desktop_dir() -> str:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:   # CSIDL_DESKTOPDIRECTORY
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser('~'), 'Desktop')


def shell_names() -> dict:
    """本機的資料夾與顯示名稱（啟動後快取）"""
    global _NAMES
    if _NAMES is None:
        home = os.path.expanduser('~')
        users = os.path.dirname(home)
        desktop = _desktop_dir()
        _NAMES = {
            'home': home, 'users_root': users, 'desktop_dir': desktop,
            'user': os.path.basename(home),
            'user_label': os.path.basename(home),          # 標準 key 裡使用者資料夾的寫法（companion 依既有紀錄調整大小寫）
            'users': {n.casefold() for n in (os.path.basename(users), shell_display_name(users), 'Users') if n},
            'desktop': shell_display_name(desktop) or '桌面',
        }
    return _NAMES


def set_user_label(label: str):
    """既有紀錄裡使用者資料夾的寫法（舊版 SAI2 顯示「Auer0807」，新版顯示「auer0807」）"""
    if label:
        shell_names()['user_label'] = label


# ─── 標準 key ──
def canonical_key(key: str, names: dict | None = None, bare_is_desktop: bool = True) -> str:
    """把新版 SAI2 的各種路徑寫法換成舊版的寫法（見檔頭的對照表）；不會碰檔案系統。
    bare_is_desktop：只有檔名時當作桌面上的檔案（新版的標題）；很舊的 SAI2 標題本來就只有檔名，不能這樣解讀"""
    if not key:
        return key
    n = names or shell_names()
    parts = [p for p in key.split(SEP)] if SEP in key else [key]
    # 1.「本機 _ 標籤 (X:) _ …」→「標籤 (X:) _ …」
    if len(parts) > 2 and not _DRIVE.search(parts[0]) and _DRIVE.search(parts[1]):
        parts = parts[1:]
    # 2.「標籤 (C:) _ 使用者 _ 帳號 _ …」→「帳號 _ …」（目前登入的使用者）
    if (len(parts) > 3 and _DRIVE.search(parts[0]) and parts[1].casefold() in n['users']
            and parts[2].casefold() == n['user'].casefold()):
        parts = [n['user_label']] + parts[3:]
    # 3.「帳號 _ 桌面 _ …」→ 桌面上的檔案「桌面 _ 檔名」、桌面上的資料夾「資料夾 _ …」
    if len(parts) > 2 and parts[0].casefold() == n['user'].casefold() and parts[1] == n['desktop']:
        rest = parts[2:]
        parts = [n['desktop']] + rest if len(rest) == 1 else rest
    # 4. 新版只顯示檔名的，是桌面上的檔案（沒有副檔名的是未存檔的新畫布，不動）
    if bare_is_desktop and len(parts) == 1 and os.path.splitext(parts[0])[1]:
        parts = [n['desktop'], parts[0]]
    return SEP.join(parts)


# ─── key → 實際路徑 ──
def _walk(base: str, segs: list[str], isdir, listdir, display) -> str | None:
    """從 base 依顯示名稱一層層找下去：資料夾名稱不同時（「下載」→ Downloads）比對子資料夾的顯示名稱；
    都找不到就照字面接上（最後由呼叫端檢查檔案是否存在）"""
    if not segs:
        return None
    cur = base
    for seg in segs[:-1]:
        nxt = os.path.join(cur, seg)
        if not isdir(nxt) and isdir(cur):
            try:
                children = listdir(cur)
            except OSError:
                children = []
            for name in children:
                p = os.path.join(cur, name)
                if isdir(p) and (display(p) or '') == seg:
                    nxt = p
                    break
        cur = nxt
    return os.path.join(cur, segs[-1])


def candidates_from_key(key: str, users_root: str | None = None, names: dict | None = None,
                        isdir=os.path.isdir, listdir=os.listdir, display=shell_display_name) -> list[str]:
    """依 key 推出的候選路徑（不檢查最後的檔案是否存在）"""
    n = dict(names or shell_names())
    if users_root:
        n['users_root'] = users_root
    parts = canonical_key(key, n).split(SEP)
    out = []

    def add(base, segs):
        p = _walk(base, segs, isdir, listdir, display)
        if p and p not in out:
            out.append(p)
    m = _DRIVE.search(parts[0])
    if m and len(parts) > 1:
        add(m.group(1).upper() + '\\', parts[1:])
    if parts[0].casefold() == n['user'].casefold() and len(parts) > 1:
        add(n['home'], parts[1:])
    if parts[0] == n['desktop'] and len(parts) > 1:
        add(n['desktop_dir'], parts[1:])
    add(n['desktop_dir'], parts)                       # 桌面上的資料夾（「暫存 _ d.sai2」）
    add(n['users_root'], parts)                        # 其他使用者資料夾（「Artist _ AppData _ …」）
    return out


def resolve_file_key(key: str, users_root: str | None = None, search_roots: list[str] | None = None,
                     isfile=os.path.isfile, names: dict | None = None, isdir=os.path.isdir, listdir=os.listdir,
                     display=shell_display_name) -> str | None:
    for p in candidates_from_key(key, users_root, names, isdir, listdir, display):
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
    return key.split(SEP)[-1] if SEP in key else key
