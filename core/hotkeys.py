# -*- coding: utf-8 -*-
"""
hotkeys.py - 全域快捷鍵字串的解析與檢查（不含 UI）

字串格式：「Ctrl+Alt+D」「Ctrl+Shift+F9」；修飾鍵順序不拘、不分大小寫。
"""

from __future__ import annotations

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
_MODS = {'ctrl': MOD_CONTROL, 'control': MOD_CONTROL, 'alt': MOD_ALT, 'shift': MOD_SHIFT, 'win': MOD_WIN}
_MOD_ORDER = ((MOD_CONTROL, 'Ctrl'), (MOD_ALT, 'Alt'), (MOD_SHIFT, 'Shift'), (MOD_WIN, 'Win'))

_KEYS: dict[str, int] = {chr(c): c for c in range(ord('A'), ord('Z') + 1)}
_KEYS.update({str(d): 0x30 + d for d in range(10)})
_KEYS.update({f'F{i}': 0x6F + i for i in range(1, 25)})
_KEYS.update({'Space': 0x20, 'Tab': 0x09, 'Enter': 0x0D, 'Esc': 0x1B, 'Backspace': 0x08, 'Insert': 0x2D,
              'Delete': 0x2E, 'Home': 0x24, 'End': 0x23, 'PageUp': 0x21, 'PageDown': 0x22,
              'Left': 0x25, 'Up': 0x26, 'Right': 0x27, 'Down': 0x28, 'Pause': 0x13,
              '`': 0xC0, '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, ';': 0xBA, "'": 0xDE,
              ',': 0xBC, '.': 0xBE, '/': 0xBF, '\\': 0xDC})
_KEYS_LOWER = {k.lower(): (k, v) for k, v in _KEYS.items()}
_VK_NAME = {v: k for k, v in _KEYS.items()}

# 2.0 的動作與預設快捷鍵。避開 1.x 的組合（過渡期兩版會同時執行）與 SAI2 常用的 Space 系列視圖操作
ACTIONS = {
    'panel':      ('打開／關閉快捷面板', 'Ctrl+Alt+D'),
    'toggle_pet': ('顯示／隱藏寵物', 'Ctrl+Alt+H'),
    'open_sai2':  ('開啟或切到 SAI2', ''),
    'snapshot':   ('擷取 SAI2 畫布快照', ''),
    'ref_toggle': ('顯示／隱藏參考小窗', 'Ctrl+Alt+R'),
    'click_through': ('參考小窗穿透模式（切換）', 'Ctrl+Alt+X'),
    'compare':    ('按住比對我的畫布', 'Ctrl+Alt+C'),
    'sketch_next': ('速寫：下一張', 'Ctrl+Alt+N'),
    'sketch_pause': ('速寫：暫停／繼續', 'Ctrl+Alt+P'),
    'record_toggle': ('縮時錄影：開始／停止', ''),
}

# 1.x 會註冊的快捷鍵（預設值），設定頁提示衝突用
LEGACY_1X = {
    'Ctrl+Alt+T': '1.x 精簡模式',
    'F10': '1.x 縮時錄影',
    'Ctrl+Alt+L': '1.x 液化',
    'Ctrl+Alt+K': '1.x 速寫',
    'Ctrl+Alt+B': '1.x 筆刷工坊',
}


def parse(text: str) -> tuple[int, int]:
    """'Ctrl+Alt+D' → (mods, vk)；格式錯誤丟 ValueError"""
    parts = [p.strip() for p in (text or '').replace(' ', '').split('+') if p.strip()]
    if not parts:
        raise ValueError('空白的快捷鍵')
    mods = 0
    for p in parts[:-1]:
        m = _MODS.get(p.lower())
        if m is None:
            raise ValueError(f'不認得的修飾鍵：{p}')
        mods |= m
    key = _KEYS_LOWER.get(parts[-1].lower())
    if key is None:
        raise ValueError(f'不認得的按鍵：{parts[-1]}')
    vk = key[1]
    if mods == 0 and not (0x70 <= vk <= 0x87):
        raise ValueError('需要搭配 Ctrl / Alt / Shift / Win（F1～F24 除外）')
    return mods, vk


def format_hotkey(mods: int, vk: int) -> str:
    names = [n for m, n in _MOD_ORDER if mods & m]
    names.append(_VK_NAME.get(vk, f'VK{vk:02X}'))
    return '+'.join(names)


def normalize(text: str) -> str:
    return format_hotkey(*parse(text))


_MOD_VK = ((MOD_CONTROL, 0x11), (MOD_ALT, 0x12), (MOD_SHIFT, 0x10), (MOD_WIN, 0x5B))


def key_sequence(text: str) -> list[int]:
    """模擬按鍵用：'Ctrl+Alt+N' → [Ctrl, Alt, N] 的虛擬鍵碼（依序按下、反序放開）"""
    mods, vk = parse(text)
    return [code for m, code in _MOD_VK if mods & m] + [vk]


def clash(text: str, bindings: dict[str, str]) -> str | None:
    """text 和 2.0 自己的哪個快捷鍵相同（相同時 2.0 會先攔走，送不到 SAI2）；回傳動作名稱"""
    try:
        norm = normalize(text)
    except ValueError:
        return None
    for action, other in (bindings or {}).items():
        try:
            if other and normalize(other) == norm:
                return ACTIONS.get(action, (action,))[0]
        except ValueError:
            continue
    return None


def conflicts(bindings: dict[str, str]) -> dict[str, str]:
    """回傳 {動作: 說明}：同一組合被兩個動作使用、或和 1.x 預設相同"""
    out: dict[str, str] = {}
    seen: dict[str, str] = {}
    for action, text in bindings.items():
        if not text:
            continue
        try:
            norm = normalize(text)
        except ValueError as e:
            out[action] = str(e)
            continue
        if norm in seen:
            out[action] = f'和「{ACTIONS.get(seen[norm], (seen[norm],))[0]}」重複'
        elif norm in LEGACY_1X:
            out[action] = f'和 {LEGACY_1X[norm]} 相同，兩版同時執行時只有一邊有效'
        seen.setdefault(norm, action)
    return out
