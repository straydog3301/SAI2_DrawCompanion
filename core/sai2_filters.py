# -*- coding: utf-8 -*-
"""
sai2_filters.py - SAI2 原生濾鏡擴充模組管理與影像濾鏡核心（不含 UI）

負責管理 SAI2 原生濾鏡擴充 DLL（native/sai2mod/dwmapi.dll）與設定檔（sai2_filters_mod.ini）：
- 所有「濾鏡 → 效果 → 二值化 / 色調分離」的選單注入、對話框、16-bit 即時預覽與圖層寫入（含 Ctrl+Z 復原）
  皆由 C 原生模組（sai2mod.c 編譯之 dwmapi.dll）直接在 SAI2 行程內執行。
- SAI2_DrawCompanion 僅負責功能開關與設定檔同步（設定後於下次啟動 SAI2 生效）。
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
MOD_DLL_FALLBACK = 'dwmapi.dll'
MOD_INI_FILENAME = 'sai2_filters_mod.ini'

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


# ── SAI2 原生濾鏡擴充模組（dwmapi.dll + sai2_filters_mod.ini）管理 ────────

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
    """把 filters 字典與個別關鍵字（binarize=.../pixelate=... 向後相容）併成完整的開關表，預設全開"""
    states = {k: True for k in FILTERS}
    if filters:
        states.update({k: bool(v) for k, v in filters.items() if k in FILTERS})
    states.update({k: bool(v) for k, v in legacy.items() if k in FILTERS})
    return states


def read_mod_ini(sai2_dir: str) -> dict:
    """讀取目標 SAI2 資料夾中的 sai2_filters_mod.ini 設定"""
    res = {'enabled': True, 'debug': False}
    res.update({k: True for k in FILTERS})
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
            for k in FILTERS:
                res[k] = cp.getint('FiltersMod', k, fallback=1) != 0
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
    """寫入 sai2_filters_mod.ini 至目標 SAI2 資料夾（UTF-8 無 BOM / ASCII 相容，供 Win32 GetPrivateProfileIntW 讀取）"""
    if not sai2_dir or not os.path.isdir(sai2_dir):
        return False
    states = _filter_states(filters, **legacy)
    lines = ['[FiltersMod]', f'enabled={1 if enabled else 0}']
    lines += [f'{k}={1 if states[k] else 0}' for k in FILTERS]
    lines.append(f'debug={1 if debug else 0}')
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
        res.update({k: True for k in FILTERS})
        return res

    dst_dll_primary = os.path.join(sai2_dir, MOD_DLL_FILENAME)
    dst_dll_fallback = os.path.join(sai2_dir, MOD_DLL_FALLBACK)
    ini_path = os.path.join(sai2_dir, MOD_INI_FILENAME)
    dll_installed = os.path.isfile(dst_dll_primary) or os.path.isfile(dst_dll_fallback)
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
    res.update({k: bool(ini_cfg[k]) for k in FILTERS})
    return res


def sync_filters_mod(
    sai2_exe_or_dir: str = '',
    enabled: bool = False,
    filters: dict | None = None,
    **legacy,
) -> tuple[bool, str]:
    """將濾鏡擴充模組開關與個別濾鏡設定同步至目標 SAI2 資料夾（下次啟動 SAI2 生效）。
    個別濾鏡可用 filters 字典或關鍵字（binarize=/posterize=/pixelate=/sharpen=）指定，預設全開。"""
    sai2_dir = resolve_sai2_dir(sai2_exe_or_dir)
    if not sai2_dir:
        return False, '找不到 SAI2 安裝資料夾（請先開啟一次 SAI2 或於設定中指定 sai2.exe 位置）。'

    states = _filter_states(filters, **legacy)
    effective_enabled = bool(enabled and any(states.values()))
    if not write_mod_ini(sai2_dir, effective_enabled, states):
        return False, f'無法寫入設定檔至 {sai2_dir}。'

    target_dlls = [MOD_DLL_FILENAME]
    if os.path.isfile(get_mod_dll_source_path(MOD_DLL_FALLBACK)):
        target_dlls.append(MOD_DLL_FALLBACK)

    if effective_enabled:
        deployed_count = 0
        for dll_name in target_dlls:
            src = get_mod_dll_source_path(dll_name)
            dst = os.path.join(sai2_dir, dll_name)
            if not os.path.isfile(src):
                continue
            try:
                shutil.copy2(src, dst)
                deployed_count += 1
            except PermissionError:
                # 若 SAI2 正在執行中且已載入該 DLL，檔案會被鎖定；
                # 但因為已經在位且 sai2_filters_mod.ini 已更新，下次重啟 SAI2 即可直接生效。
                if os.path.isfile(dst):
                    deployed_count += 1
            except Exception as e:
                return False, f'部署模組檔案 {dll_name} 失敗：{e}'

        if not deployed_count:
            return False, f'找不到內建模組檔案：{get_mod_dll_source_path(MOD_DLL_FILENAME)}'
        return True, '已啟用並更新 SAI2 內建濾鏡擴充模組（將於下次啟動 SAI2 時生效）。'
    else:
        for dll_name in target_dlls:
            dst = os.path.join(sai2_dir, dll_name)
            if os.path.isfile(dst):
                try:
                    os.remove(dst)
                except Exception:
                    pass
        return True, '已停用 SAI2 內建濾鏡擴充模組（將於下次啟動 SAI2 時生效）。'
