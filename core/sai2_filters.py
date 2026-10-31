# -*- coding: utf-8 -*-
"""
sai2_filters.py - SAI2 原生濾鏡擴充模組管理與影像濾鏡核心（不含 UI）

負責管理 SAI2 原生濾鏡擴充 DLL（native/sai2mod/mscms.dll）與設定檔（sai2_filters_mod.ini）：
- 所有「濾鏡 → 效果 → 二值化 / 色調分離 …」的選單注入、對話框、16-bit 即時預覽與圖層寫入（含 Ctrl+Z 復原），
  以及圖層面板「特殊效果 → 筆畫」，皆由 C 原生模組（sai2mod.c 編譯之 mscms.dll）直接在 SAI2 行程內執行。
- SAI2_DrawCompanion 僅負責功能開關與設定檔同步（設定後於下次啟動 SAI2 生效）。
- 代理 DLL 固定用 mscms.dll：舊版會另外放 dwmapi.dll，會讓漢化模組跳出警告；同步時會清掉我們自己舊放的
  dwmapi.dll（只刪確認是本模組的檔案，別的模組的同名 DLL 不動）。
"""

from __future__ import annotations

import configparser
import ctypes
import ctypes.wintypes as wt
import os
import shutil
import sys
from PIL import Image

from core.paths import APP_DIR
from core.sai2_win import find_sai2_hwnd as find_sai2_window

# ── SAI2 內部與擴充選單常數 ──────────────────────────────────────────────

MENU_ID_FILTER = 0x0002006B          # SAI2 頂層「濾鏡 (Filter)」選單 ID
MENU_ID_EFFECT_SEP = 0x00028FFF      # 「效果」上方的分隔線 ID
MENU_ID_EFFECT_SUBMENU = 0x00029000  # 「效果」子選單 ID
MENU_ID_BINARIZE = 0x00029001        # 「二值化(&B) ...」
MENU_ID_POSTERIZE = 0x00029002       # 「色調分離(&P) ...」
MENU_ID_PIXELATE = 0x00029003        # 「像素化(&X) ...」
MENU_ID_SHARPEN = 0x00029004         # 「銳化(&S) ...」

MOD_DLL_FILENAME = 'mscms.dll'
MOD_DLL_LEGACY = 'dwmapi.dll'        # 舊版另外部署的代理 DLL；只用來清理
MOD_INI_FILENAME = 'sai2_filters_mod.ini'
# 本模組 DLL 一定含有設定檔名稱（UTF-16）：用來確認 SAI2 資料夾裡的同名 DLL 是不是我們的
MOD_DLL_MARKER = MOD_INI_FILENAME.encode('utf-16-le')

FILTERS: dict[str, dict] = {
    'binarize': {
        'id': MENU_ID_BINARIZE,
        'name': '二值化',
        'menu_label': '二值化(&B) ...',
        'desc': '依亮度臨界值（1～255）將圖層轉為黑白，並支援「將白色轉為透明（提取線稿）」。',
    },
    'posterize': {
        'id': MENU_ID_POSTERIZE,
        'name': '色調分離',
        'menu_label': '色調分離(&P) ...',
        'desc': '將圖層各色版量化為指定色階數（2～64 階），保留原圖層透明度與選取範圍。',
    },
    'pixelate': {
        'id': MENU_ID_PIXELATE,
        'name': '像素化',
        'menu_label': '像素化(&X) ...',
        'desc': '把圖層打成馬賽克方塊，強度 1～5 對應區塊大小 2～32 像素。',
    },
    'sharpen': {
        'id': MENU_ID_SHARPEN,
        'name': '銳化',
        'menu_label': '銳化(&S) ...',
        'desc': '強化邊緣細節（3×3 遮罩），強度 1～10；強度高時可能有輕微區塊接縫。',
    },
}

ID_TO_FILTER: dict[int, str] = {v['id']: k for k, v in FILTERS.items()}

# 圖層面板「特殊效果」下拉選單的項目（只支援 SAI2 2026 版）
LAYER_EFFECTS: dict[str, dict] = {
    'fx_stroke': {
        'name': '筆畫',
        'desc': '圖層面板「特殊效果」新增「筆畫」：沿圖形內側描邊，可調寬度（2～30 像素）、強度與紅綠藍顏色，'
                '畫圖時即時更新（僅 SAI2 2026 版）。',
    },
}

# ini 裡每個可開關的項目（濾鏡 + 圖層效果）
MOD_FEATURES: dict[str, dict] = {**FILTERS, **LAYER_EFFECTS}


# ── 純影像濾鏡演算法（供單元測試與離線處理使用） ───────────────────────────

def binarize_lut(threshold: int) -> list[int]:
    """產生 256 階二值化查找表（0..threshold-1 為 0，threshold..255 為 255）"""
    t = max(0, min(255, int(threshold)))
    return [0 if i < t else 255 for i in range(256)]


def posterize_lut(levels: int) -> list[int]:
    """產生 256 階色調分離查找表（levels: 2..64）"""
    lv = max(2, min(64, int(levels)))
    step = 255.0 / (lv - 1)
    return [min(255, max(0, int(round(round(i / step) * step)))) for i in range(256)]


def apply_binarize(img: Image.Image, threshold: int = 128, transparent_white: bool = False) -> Image.Image:
    """二值化濾鏡：將影像依亮度臨界值（0～255）轉為黑白，保留原圖層透明度。
    若 transparent_white=True，白色區域會轉為透明（適合提取線稿）。"""
    lut = binarize_lut(threshold)
    has_alpha = img.mode == 'RGBA' or 'A' in img.getbands()
    rgba = img.convert('RGBA') if has_alpha else None
    gray = (rgba if rgba is not None else img).convert('L')
    bw = gray.point(lut)
    if transparent_white:
        inv_mask = bw.point([255 - i for i in range(256)])
        if rgba is not None:
            orig_a = rgba.getchannel('A')
            from PIL import ImageChops
            new_a = ImageChops.darker(orig_a, inv_mask)
        else:
            new_a = inv_mask
        return Image.merge('RGBA', (bw, bw, bw, new_a))
    if rgba is not None:
        return Image.merge('RGBA', (bw, bw, bw, rgba.getchannel('A')))
    return Image.merge('RGB', (bw, bw, bw))


def apply_posterize(img: Image.Image, levels: int = 4) -> Image.Image:
    """色調分離濾鏡：將 RGB 各色版量化為指定色階數（2～64），保留原圖層透明度。"""
    lut = posterize_lut(levels)
    if img.mode == 'RGBA' or 'A' in img.getbands():
        rgba = img.convert('RGBA')
        r, g, b, a = rgba.split()
        return Image.merge('RGBA', (r.point(lut), g.point(lut), b.point(lut), a))
    rgb = img.convert('RGB')
    return rgb.point(lut * 3)


def apply_filter(img: Image.Image, filter_key: str, **params) -> Image.Image:
    """依濾鏡代碼套用對應濾鏡"""
    if filter_key == 'binarize':
        return apply_binarize(
            img,
            threshold=int(params.get('threshold', 128)),
            transparent_white=bool(params.get('transparent_white', False)),
        )
    if filter_key == 'posterize':
        return apply_posterize(img, levels=int(params.get('levels', 4)))
    raise ValueError(f'Unknown filter_key: {filter_key}')


# ── SAI2 原生濾鏡擴充模組（mscms.dll + sai2_filters_mod.ini）管理 ─────────

def get_mod_dll_source_path(filename: str = MOD_DLL_FILENAME) -> str:
    """取得內建編譯好的 SAI2 原生擴充 DLL 來源路徑（支援 PyInstaller 打包與開發環境）"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        mei_path = os.path.join(sys._MEIPASS, 'native', 'sai2mod', filename)
        if os.path.isfile(mei_path):
            return mei_path
    p = os.path.join(APP_DIR, 'native', 'sai2mod', filename)
    if os.path.isfile(p):
        return p
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        for base in (exe_dir, os.path.dirname(exe_dir)):
            p2 = os.path.join(base, 'native', 'sai2mod', filename)
            if os.path.isfile(p2):
                return p2
    return p


def _query_running_sai2_exe() -> str:
    """若 SAI2 正在執行中，透過 Win32 QueryFullProcessImageNameW 取得其 sai2.exe 路徑"""
    hwnd = find_sai2_window()
    if not hwnd:
        return ''
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        pid = wt.DWORD(0)
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ''
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        hproc = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not hproc:
            return ''
        try:
            buf = ctypes.create_unicode_buffer(1024)
            sz = wt.DWORD(1024)
            if k32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(sz)):
                return buf.value
        finally:
            k32.CloseHandle(hproc)
    except Exception:
        pass
    return ''


def resolve_sai2_dir(sai2_exe_or_dir: str = '') -> str:
    """解析目標 SAI2 資料夾路徑：
    1. 優先使用傳入的 sai2_exe 或資料夾設定
    2. 其次偵測正在執行的 sai2.exe 位置
    3. 最後檢查 SAI2_DrawCompanion 上層資料夾是否包含 sai2.exe
    """
    candidates: list[str] = []
    if sai2_exe_or_dir:
        p = os.path.abspath(sai2_exe_or_dir)
        if os.path.isfile(p):
            candidates.append(os.path.dirname(p))
        elif os.path.isdir(p):
            candidates.append(p)

    running_exe = _query_running_sai2_exe()
    if running_exe and os.path.isfile(running_exe):
        candidates.append(os.path.dirname(running_exe))

    parent_dir = os.path.dirname(os.path.abspath(APP_DIR))
    candidates.append(parent_dir)

    for d in candidates:
        if d and os.path.isfile(os.path.join(d, 'sai2.exe')):
            return d
    return ''


def _filter_states(filters: dict | None = None, **legacy) -> dict:
    """把 filters 字典與個別關鍵字（binarize=.../fx_stroke=... 向後相容）併成完整的開關表，預設全開"""
    states = {k: True for k in MOD_FEATURES}
    if filters:
        states.update({k: bool(v) for k, v in filters.items() if k in MOD_FEATURES})
    states.update({k: bool(v) for k, v in legacy.items() if k in MOD_FEATURES})
    return states


def is_own_mod_dll(path: str) -> bool:
    """檔案是不是本模組編出來的 DLL（含 sai2_filters_mod.ini 字串）。讀不到就當不是，避免誤刪別人的檔案"""
    try:
        with open(path, 'rb') as f:
            return MOD_DLL_MARKER in f.read()
    except OSError:
        return False


def _remove_own_dll(path: str) -> None:
    """刪除本模組的 DLL；別的模組的同名檔案、或 SAI2 執行中被鎖住的檔案就留著"""
    if os.path.isfile(path) and is_own_mod_dll(path):
        try:
            os.remove(path)
        except OSError:
            pass


def read_mod_ini(sai2_dir: str) -> dict:
    """讀取目標 SAI2 資料夾中的 sai2_filters_mod.ini 設定"""
    res = {'enabled': True, 'debug': False, 'fx_stroke_color': ''}
    res.update({k: True for k in MOD_FEATURES})
    if not sai2_dir:
        return res
    ini_path = os.path.join(sai2_dir, MOD_INI_FILENAME)
    if not os.path.isfile(ini_path):
        return res
    try:
        cp = configparser.ConfigParser()
        cp.read(ini_path, encoding='utf-8')
        if cp.has_section('FiltersMod'):
            res['enabled'] = cp.getint('FiltersMod', 'enabled', fallback=1) != 0
            res['debug'] = cp.getint('FiltersMod', 'debug', fallback=0) != 0
            for k in MOD_FEATURES:
                res[k] = cp.getint('FiltersMod', k, fallback=1) != 0
            res['fx_stroke_color'] = cp.get('FiltersMod', 'fx_stroke_color', fallback='').strip()
    except Exception:
        pass
    return res


def write_mod_ini(
    sai2_dir: str,
    enabled: bool,
    filters: dict | None = None,
    debug: bool = False,
    **legacy,
) -> bool:
    """寫入 sai2_filters_mod.ini 至目標 SAI2 資料夾（UTF-8 無 BOM / ASCII 相容，供 Win32 GetPrivateProfileIntW 讀取）。
    fx_stroke_color 是模組自己寫回的「最近一次用過的筆畫顏色」，保留原值。"""
    if not sai2_dir or not os.path.isdir(sai2_dir):
        return False
    states = _filter_states(filters, **legacy)
    color = read_mod_ini(sai2_dir).get('fx_stroke_color', '')
    lines = ['[FiltersMod]', f'enabled={1 if enabled else 0}']
    lines += [f'{k}={1 if states[k] else 0}' for k in MOD_FEATURES]
    lines.append(f'debug={1 if debug else 0}')
    if color and all(c in '#0123456789abcdefABCDEF' for c in color):
        lines.append(f'fx_stroke_color={color}')
    content = '\r\n'.join(lines) + '\r\n'
    try:
        with open(ini_path := os.path.join(sai2_dir, MOD_INI_FILENAME), 'w', encoding='ascii') as f:
            f.write(content)
        return True
    except Exception:
        return False


def get_mod_status(sai2_exe_or_dir: str = '') -> dict:
    """取得 SAI2 原生濾鏡擴充模組的目前安裝狀態與設定"""
    sai2_dir = resolve_sai2_dir(sai2_exe_or_dir)
    src_dll = get_mod_dll_source_path(MOD_DLL_FILENAME)
    dll_source_exists = os.path.isfile(src_dll)
    if not sai2_dir:
        res = {
            'sai2_dir': '',
            'sai2_exe': '',
            'dll_source_exists': dll_source_exists,
            'dll_installed': False,
            'ini_exists': False,
            'enabled': False,
            'sai2_running': bool(find_sai2_window()),
        }
        res.update({k: True for k in MOD_FEATURES})
        return res

    dst_dll = os.path.join(sai2_dir, MOD_DLL_FILENAME)
    ini_path = os.path.join(sai2_dir, MOD_INI_FILENAME)
    dll_installed = os.path.isfile(dst_dll) and is_own_mod_dll(dst_dll)
    ini_exists = os.path.isfile(ini_path)
    ini_cfg = read_mod_ini(sai2_dir)
    res = {
        'sai2_dir': sai2_dir,
        'sai2_exe': os.path.join(sai2_dir, 'sai2.exe'),
        'dll_source_exists': dll_source_exists,
        'dll_installed': dll_installed,
        'ini_exists': ini_exists,
        'enabled': bool(dll_installed and ini_cfg['enabled']),
        'sai2_running': bool(find_sai2_window()),
    }
    res['dll_conflict'] = os.path.isfile(dst_dll) and not dll_installed     # 別的模組占用了 mscms.dll
    res.update({k: bool(ini_cfg[k]) for k in MOD_FEATURES})
    return res


def sync_filters_mod(
    sai2_exe_or_dir: str = '',
    enabled: bool = False,
    filters: dict | None = None,
    **legacy,
) -> tuple[bool, str]:
    """將濾鏡擴充模組開關與個別項目設定同步至目標 SAI2 資料夾（下次啟動 SAI2 生效）。
    個別項目可用 filters 字典或關鍵字（binarize=/posterize=/pixelate=/sharpen=/fx_stroke=）指定，預設全開。"""
    sai2_dir = resolve_sai2_dir(sai2_exe_or_dir)
    if not sai2_dir:
        return False, '找不到 SAI2 安裝資料夾（請先開啟一次 SAI2 或於設定中指定 sai2.exe 位置）。'

    states = _filter_states(filters, **legacy)
    effective_enabled = bool(enabled and any(states.values()))
    if not write_mod_ini(sai2_dir, effective_enabled, states):
        return False, f'無法寫入設定檔至 {sai2_dir}。'

    # 舊版另外放的 dwmapi.dll（只刪我們自己的）
    _remove_own_dll(os.path.join(sai2_dir, MOD_DLL_LEGACY))

    dst = os.path.join(sai2_dir, MOD_DLL_FILENAME)
    if effective_enabled:
        src = get_mod_dll_source_path(MOD_DLL_FILENAME)
        if not os.path.isfile(src):
            return False, f'找不到內建模組檔案：{src}'
        if os.path.isfile(dst) and not is_own_mod_dll(dst):
            return False, f'SAI2 資料夾已有其他模組的 {MOD_DLL_FILENAME}，為避免覆蓋，未部署濾鏡擴充模組。'
        try:
            shutil.copy2(src, dst)
        except PermissionError:
            # SAI2 執行中已載入該 DLL → 檔案被鎖定；舊版已在位且 ini 已更新，下次重啟 SAI2 再更新即可
            if not os.path.isfile(dst):
                return False, f'部署模組檔案 {MOD_DLL_FILENAME} 失敗：檔案被鎖定。'
        except Exception as e:
            return False, f'部署模組檔案 {MOD_DLL_FILENAME} 失敗：{e}'
        return True, '已啟用並更新 SAI2 內建濾鏡擴充模組（將於下次啟動 SAI2 時生效）。'
    _remove_own_dll(dst)
    return True, '已停用 SAI2 內建濾鏡擴充模組（將於下次啟動 SAI2 時生效）。'
