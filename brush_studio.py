# -*- coding: utf-8 -*-
"""
brush_studio.py - SAI2 筆刷、紋理與材質製作工坊 (Brush & Texture Studio)
提供便利的畫布選區/剪貼簿一鍵製作 SAI2 筆刷工具、無縫紋理 (brushtex) 與紙張材質 (papertex)。
包含無縫平鋪融合、對比微調、3x3 平鋪即時預覽、動態自適應試畫畫布與參數數值持久記憶。
"""

from __future__ import annotations

import os
import sys
import glob
import time
import json
import math
import uuid
import random
import shutil
import contextlib
import ctypes
import ctypes.wintypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageOps, ImageGrab, ImageChops, ImageStat

from i18n import _tr
from liquify_helper import read_image_from_clipboard, find_sai2_hwnd


def is_text_input_widget(widget) -> bool:
    """事件來源是否為可輸入文字的元件（Entry / 可編輯 Combobox / Text / Spinbox）。
    綁在整個視窗上的單鍵快捷鍵（空白、方向鍵、Ctrl+V）遇到這類元件時應讓出，避免打字時誤觸。"""
    if not isinstance(widget, (tk.Entry, ttk.Entry, tk.Text, tk.Spinbox, ttk.Spinbox)):
        return False
    try:
        return str(widget.cget('state')) not in ('readonly', 'disabled')
    except Exception:
        return True

# ─── 色彩 / 樣式常數 ─────────────────────────────────────────────────────────
BG     = '#111111'
CARD   = '#1e1e1e'
CARD2  = '#282828'
CARD3  = '#333333'
ACCENT = '#7c3aed'
ACCH   = '#6d28d9'
TEXT   = '#f0f0f0'
TEXTD  = '#888888'
GREEN  = '#22c55e'
YELLOW = '#f59e0b'
RED    = '#ef4444'
BORDER = '#3a3a3a'

FT_TITLE = ('Microsoft JhengHei', 13, 'bold')
FT_HEAD  = ('Microsoft JhengHei', 11, 'bold')
FT_NORM  = ('Microsoft JhengHei', 9)
FT_BOLD  = ('Microsoft JhengHei', 9, 'bold')
FT_SMALL = ('Microsoft JhengHei', 8)


# ─── 參數持久化記憶管理 ────────────────────────────────────────────────────────

# 取得程式運行所在的實際目錄（相容 PyInstaller 打包，與 main.py 的 _APP_DIR 規則一致）
# 注意：onefile 打包時 __file__ 指向暫存的 _MEIxxxx 目錄，程式結束即被刪除，不能用來存放資料
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    if os.path.basename(_exe_dir).lower() == 'dist':
        _APP_DIR = os.path.dirname(_exe_dir)
    else:
        _APP_DIR = _exe_dir
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(_APP_DIR, 'brush_studio_settings.json')

class BrushStudioSettings:
    """負責儲存與還原筆刷工坊的各項調動數值，記憶使用者最後設定"""

    DEFAULT_SETTINGS = {
        'main_mode': 'scatter',
        'preview_view': 'single',
        'target_group': '',
        'size': 60,
        'spacing': 35,
        'scattering': 30,
        'angle_ctl': 0,
        'angle': 0,
        'angle_jitter': 20,
        'size_jitter': 30,
        'pen_pressure': True,
        'convert_mode': 'alpha',
        'autocrop': True,
        'seamless_mode': 'crossfade',
        'blend_margin': 25,
        'tex_res': 256,
        'contrast': 1.0,
        'brightness': 0.0,
        'invert': False,
        'create_texture_brush': True,
        'pad_bg_mode': 'dark',
    }

    @classmethod
    def load(cls) -> dict:
        d = dict(cls.DEFAULT_SETTINGS)
        if os.path.isfile(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    d.update(saved)
            except Exception as e:
                print(f"[BrushStudioSettings] Load warning: {e}")
        return d

    @classmethod
    def save(cls, settings: dict):
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[BrushStudioSettings] Save warning: {e}")


# ─── 強健多格式剪貼簿讀取 ──────────────────────────────────────────────────────

def read_clipboard_safely() -> Image.Image | None:
    """
    多重備援剪貼簿圖像讀取：
    1. 優先透過 Win32 讀取 CF_DIBV5 (32-bit RGBA，SAI2 複製時攜帶的透明度)
    2. 嘗試 PNG 剪貼簿格式
    3. 嘗試 ImageGrab.grabclipboard() 讀取常規點陣圖或截圖
    4. 支援檔案清單：若使用者在檔案總管按 Ctrl+C 複製圖檔，自動解析開啟該圖片
    """
    # 1. 嘗試 Win32 原生透明通道
    try:
        img = read_image_from_clipboard()
        if img is not None and isinstance(img, Image.Image):
            return img
    except Exception as e:
        print(f"[BrushStudio] Win32 clipboard failed: {e}")

    # 2. 嘗試 PIL ImageGrab
    try:
        grabbed = ImageGrab.grabclipboard()
        if isinstance(grabbed, Image.Image):
            return grabbed
        elif isinstance(grabbed, list):
            for item in grabbed:
                if isinstance(item, str) and os.path.isfile(item):
                    ext = os.path.splitext(item)[1].lower()
                    if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.gif', '.tif'):
                        try:
                            f_img = Image.open(item)
                            f_img.load()
                            return ImageOps.exif_transpose(f_img)
                        except Exception:
                            pass
    except Exception as e:
        print(f"[BrushStudio] ImageGrab failed: {e}")

    return None


# ─── SAI2 設定檔安全讀寫 ──────────────────────────────────────────────────────
# 所有會「改寫」SAI2 settings 內既有檔案的操作都必須經過這裡：
#   1. 以嚴格 UTF-8 解碼，無法解碼即中止改寫（避免 errors='ignore' 默默刪除位元組）
#   2. 每次寫入作業（sai2_write_session）中，每個檔案第一次被改寫前先備份到
#      sai2_settings_backup/<時間>/；不在作業內的單次改寫則每次都備份
#   3. 以暫存檔 + os.replace 原子寫入，避免寫到一半中斷造成檔案損毀
# 備份以「作業」而非「程式執行」為單位：程式常駐一整天時，兩次寫入之間 SAI2 可能已改過檔案，
# 每次作業都要留下改寫前的狀態。

BACKUP_ROOT = os.path.join(_APP_DIR, 'sai2_settings_backup')
BACKUP_KEEP = 30                       # 只保留最近幾次作業的備份資料夾
_BACKUP_SESSION: str | None = None     # 目前作業的備份資料夾名稱（None = 不在作業中）
_backed_up_files: set[str] = set()


def _new_backup_session_name() -> str:
    # 含毫秒，確保名稱排序 = 時間順序（_prune_backups 依名稱判斷新舊）
    now = time.time()
    return f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(now))}_{int(now * 1000) % 1000:03d}_{uuid.uuid4().hex[:4]}"


def _prune_backups(keep: int = BACKUP_KEEP):
    """刪除較舊的備份資料夾，只留最近 keep 份（只動本程式產生、名稱符合格式的資料夾）"""
    try:
        names = sorted(n for n in os.listdir(BACKUP_ROOT)
                       if len(n) >= 15 and n[:8].isdigit() and n[8] == '_'
                       and os.path.isdir(os.path.join(BACKUP_ROOT, n)))
    except OSError:
        return
    for n in names[:-keep] if keep > 0 else names:
        shutil.rmtree(os.path.join(BACKUP_ROOT, n), ignore_errors=True)


@contextlib.contextmanager
def sai2_write_session():
    """一次完整寫入作業（素材 + 工具、或一批佇列任務）。可巢狀，內層沿用外層的備份資料夾。"""
    global _BACKUP_SESSION, _backed_up_files
    if _BACKUP_SESSION is not None:
        yield
        return
    _BACKUP_SESSION = _new_backup_session_name()
    _backed_up_files = set()
    try:
        yield
    finally:
        _BACKUP_SESSION = None
        _backed_up_files = set()
        _prune_backups()


class SAI2FileEncodingError(Exception):
    """SAI2 設定檔不是有效的 UTF-8，為避免資料遺失而拒絕改寫"""


def _read_sai2_text(path: str) -> str:
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError as e:
        raise SAI2FileEncodingError(
            f"{path} 不是有效的 UTF-8 編碼，為避免資料遺失已停止改寫此檔案") from e


def _backup_relpath(path: str) -> str:
    """回傳相對於 SAI2 settings 目錄的路徑（找不到 settings 時僅用檔名）"""
    parts = os.path.normpath(os.path.abspath(path)).split(os.sep)
    lower = [p.lower() for p in parts]
    if 'settings' in lower:
        idx = len(lower) - 1 - lower[::-1].index('settings')
        if idx + 1 < len(parts):
            return os.path.join(*parts[idx + 1:])
    return os.path.basename(path)


def _backup_sai2_file(path: str):
    """在本次作業中第一次改寫某檔案前備份它；備份失敗會拋出例外以中止寫入"""
    key = os.path.normcase(os.path.abspath(path))
    if key in _backed_up_files or not os.path.isfile(path):
        return
    session = _BACKUP_SESSION or _new_backup_session_name()
    dst = os.path.join(BACKUP_ROOT, session, _backup_relpath(path))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(path, dst)
    if _BACKUP_SESSION is not None:
        _backed_up_files.add(key)


def _write_sai2_file(path: str, data: bytes):
    """備份後以原子方式寫入 SAI2 設定檔"""
    _backup_sai2_file(path)
    tmp = path + '.companion_tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


# ─── 素材 / 工具名稱驗證 ──────────────────────────────────────────────────────

_INVALID_NAME_CHARS = '\\/:*?"<>|,'   # Windows 檔名禁用字元 + SAI2 素材標籤分隔字元 ','
_RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL',
                   *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
MAX_NAME_LEN = 64


def validate_asset_name(name: str) -> str | None:
    """檢查素材/工具名稱是否可安全作為檔名與 SAI2 設定值；合法回傳 None，否則回傳錯誤訊息"""
    if not name or not name.strip():
        return "請輸入名稱！"
    if name != name.strip():
        return "名稱前後不能有空白。"
    if len(name) > MAX_NAME_LEN:
        return f"名稱過長（最多 {MAX_NAME_LEN} 個字元）。"
    for ch in name:
        if ord(ch) < 32 or ch == '\x7f':
            return "名稱不能包含換行或控制字元。"
        if ch in _INVALID_NAME_CHARS:
            return f"名稱不能包含特殊字元：{ch}"
    if name.endswith('.'):
        return "名稱結尾不能是「.」。"
    if name in ('.', '..') or name.split('.')[0].upper() in _RESERVED_NAMES:
        return f"「{name}」是 Windows 保留名稱，請換一個名稱。"
    return None


def _require_valid_name(name: str):
    err = validate_asset_name(name)
    if err:
        raise ValueError(err)


def _safe_child_path(base_dir: str, filename: str) -> str:
    """組合路徑並確認結果仍位於 base_dir 之內（防止路徑穿越）"""
    base = os.path.abspath(base_dir)
    path = os.path.abspath(os.path.join(base, filename))
    if os.path.dirname(path) != base:
        raise ValueError(f"不合法的檔案名稱：{filename}")
    return path


# ─── SAI2 目錄與素材/工具管理 ──────────────────────────────────────────────────

class SAI2SettingsManager:
    """負責偵測與管理 SAI2 settings 目錄下的筆刷形狀、紋理、紙張材質與自訂工具"""

    SAI2_EXE_NAMES = ('sai2.exe', 'sai2demo.exe')

    @staticmethod
    def _documents_dir() -> str:
        """實際的「文件」資料夾：被 OneDrive 或使用者重新導向時，~/Documents 不一定是它"""
        try:
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5（我的文件）, SHGFP_TYPE_CURRENT = 0
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return buf.value
        except Exception:
            pass
        return os.path.expanduser('~/Documents')

    @classmethod
    def _running_sai2_dirs(cls) -> list[str]:
        """執行中的 SAI2 程式所在資料夾（免安裝版的 settings 位於 exe 旁）"""
        dirs = []
        try:
            import psutil
            for p in psutil.process_iter(['name', 'exe']):
                if (p.info.get('name') or '').lower() in cls.SAI2_EXE_NAMES and p.info.get('exe'):
                    dirs.append(os.path.dirname(p.info['exe']))
        except Exception:
            pass
        return dirs

    @classmethod
    def get_settings_dir(cls) -> str | None:
        cands = [os.path.join(cls._documents_dir(), 'SYSTEMAX Software Development', 'SAIv2', 'settings'),
                 os.path.expanduser('~/Documents/SYSTEMAX Software Development/SAIv2/settings')]
        cands += [os.path.join(d, 'settings') for d in cls._running_sai2_dirs()]
        cands.append(os.path.join(_APP_DIR, '..', 'settings'))   # 本工具放在 SAI2 資料夾內時
        for cand in cands:
            if os.path.isdir(cand):
                return os.path.abspath(cand)
        return None

    @classmethod
    def is_sai2_running(cls) -> bool:
        # 以行程名稱判斷為準：視窗標題比對（find_sai2_hwnd）也會命中標題含「PaintTool SAI」的
        # 瀏覽器分頁或資料夾視窗而誤判。只有 psutil 無法使用時才退回標題比對。
        try:
            import psutil
        except ImportError:
            psutil = None
        if psutil is not None:
            try:
                return any((p.info.get('name') or '').lower() in cls.SAI2_EXE_NAMES
                           for p in psutil.process_iter(['name']))
            except Exception:
                pass
        try:
            return find_sai2_hwnd() != 0
        except Exception:
            return False

    @classmethod
    def get_tool_groups(cls, settings_dir: str | None = None) -> list[dict]:
        if not settings_dir:
            settings_dir = cls.get_settings_dir()
        if not settings_dir:
            return []

        custool_dir = os.path.join(settings_dir, 'custool', 'nrm')
        if not os.path.isdir(custool_dir):
            return []

        set_file = os.path.join(custool_dir, '_0.saitset')
        groups = []
        if os.path.isfile(set_file):
            try:
                grp_ids = cls._read_saitset_group_ids(custool_dir)
                for gid in grp_ids:
                    grp_file = os.path.join(custool_dir, f'_{gid}.saitgrp')
                    name = f"Group {gid}"
                    if os.path.isfile(grp_file):
                        with open(grp_file, 'r', encoding='utf-8', errors='ignore') as gf:
                            for gl in gf:
                                if gl.startswith('name=U:'):
                                    name = gl.strip().split(':', 1)[1]
                                    break
                    groups.append({'id': gid, 'name': name})
            except Exception as e:
                print(f"[SAI2SettingsManager] Read tool groups failed: {e}")

        if not groups:
            groups = [
                {'id': 1, 'name': '基本'},
                {'id': 2, 'name': '二值'},
                {'id': 5, 'name': '效果'},
            ]
        return groups

    @staticmethod
    def _read_group_name(path: str) -> str | None:
        try:
            with open(path, 'rb') as f:
                text = f.read().decode('utf-8', errors='ignore')
        except OSError:
            return None
        for line in text.splitlines():
            if line.startswith('name=U:'):
                return line.split(':', 1)[1].strip()
        return None

    @classmethod
    def _resolve_group_id(cls, folder: str, ext: str, listed_ids: list[int],
                          name: str, fallback_id: int = 0) -> int:
        """
        於「寫入當下」依磁碟內容決定群組 ID（工具分頁 .saitgrp / 素材分類 .saiagrp 共用）：
          1. 依名稱找既有群組（清單順序優先，與 UI 選單一致）
          2. 找不到但呼叫端指定了既有 ID（fallback_id > 0）→ 沿用
          3. 否則配發新 ID：大於清單與磁碟上所有既有 ID
        不在 UI 端預先算 max+1，避免清單過期或多筆佇列任務算出相同 ID 而互相覆蓋。
        """
        disk_ids: list[int] = []
        if os.path.isdir(folder):
            for fname in os.listdir(folder):
                if fname.startswith('_') and fname.endswith(ext):
                    stem = fname[1:-len(ext)]
                    if stem.isdigit():
                        disk_ids.append(int(stem))
        name = (name or '').strip()
        if name:
            for gid in list(listed_ids) + sorted(disk_ids):
                if cls._read_group_name(os.path.join(folder, f'_{gid}{ext}')) == name:
                    return gid
        if fallback_id > 0:
            return fallback_id
        return max([0, *listed_ids, *disk_ids]) + 1

    @staticmethod
    def _read_saitset_group_ids(custool_dir: str) -> list[int]:
        set_file = os.path.join(custool_dir, '_0.saitset')
        if not os.path.isfile(set_file):
            return []
        with open(set_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        grp_ids = []
        in_list = False
        for line in lines:
            line = line.strip()
            if line == '.':
                in_list = not in_list
                continue
            if in_list and '=' in line:
                parts = line.split('=', 1)
                if parts[1].strip().isdigit():
                    grp_ids.append(int(parts[1].strip()))
        return grp_ids

    @classmethod
    def get_next_tool_id(cls, settings_dir: str | None = None) -> int:
        if not settings_dir:
            settings_dir = cls.get_settings_dir()
        if not settings_dir:
            return 100

        custool_dir = os.path.join(settings_dir, 'custool', 'nrm')
        if not os.path.isdir(custool_dir):
            return 100

        max_id = 0
        for f in glob.glob(os.path.join(custool_dir, '*.*')):
            b = os.path.basename(f)
            stem, ext = os.path.splitext(b)
            if stem.isdigit() and ext in ('.saitdat', '.saitlnk'):
                val = int(stem)
                if val > max_id:
                    max_id = val
        return max_id + 1

    @classmethod
    def write_material(cls, name: str, pil_img: Image.Image, brush_type: str,
                       params: dict | None = None, settings_dir: str | None = None) -> tuple[str, str]:
        if not settings_dir:
            settings_dir = cls.get_settings_dir()
        if not settings_dir:
            raise FileNotFoundError("無法找到 SAI2 設定資料夾 (settings)")
        _require_valid_name(name)

        if brush_type == 'scatter':
            mat_dir = os.path.join(settings_dir, 'scatter')
        else:
            mat_dir = os.path.join(settings_dir, 'brushfom', 'brshape')
        os.makedirs(mat_dir, exist_ok=True)

        bmp_path = _safe_child_path(mat_dir, f"{name}.bmp")
        ini_path = _safe_child_path(mat_dir, f"{name}.ini")

        gray_img = pil_img.convert('L')
        _backup_sai2_file(bmp_path)
        gray_img.save(bmp_path, format='BMP')

        p = params or {}
        angle_ctl = p.get('angle_control', 0)
        angle = p.get('angle', 0)
        angle_jitter = p.get('angle_jitter', 0)
        scaling = p.get('scaling', 100)
        size_jitter = p.get('size_jitter', 0)
        spacing = p.get('spacing', 25)
        scattering = p.get('scattering', 0)

        if brush_type == 'scatter':
            ini_content = f""";
; Initial Parameters (Generated by SAI2 DrawCompanion)
;
[Parameters]
	AngleControl = {angle_ctl}
	Angle = {angle:+d}
	AngleJitter = {angle_jitter}
	Scaling = {scaling}
	ShapeSize = 50
	SizeJitter = {size_jitter}
	Spacing = {spacing}
	Scattering = {scattering}
	WxHRatio = 100:100
	WxHJitter = 0
	Count = 1
	CountJitter = 0
	AllDirScattering = 0
	GaussianDistribution = 0
	AbsoluteSize = 0
	IntegerPosition = 0
	HighQualitySampling = 1
	ColJitter = 0
	HueJitter = 0
	SaturationJitter = 0
	BrightnessJitter = 0
	ApplyToEachShape = 0
"""
        else:
            ini_content = f""";
; Initial Parameters (Generated by SAI2 DrawCompanion)
;
[Parameters]
	Density = 100
	AngleControl = {angle_ctl}
	Angle = {angle:+d}
	AngleJitter = {angle_jitter}
	Scaling = {scaling}
	SizeJitter = {size_jitter}
	Spacing = {spacing}
	Scattering = {scattering}
	HighQualitySampling = 1
"""
        # 維持既有行為：.ini 以 Windows 文字模式 (CRLF) 寫出
        _write_sai2_file(ini_path, ini_content.replace('\n', '\r\n').encode('utf-8'))

        asset_grp_id = p.get('asset_group_id', 0)
        asset_grp_name = p.get('asset_group_name', '')
        gid = cls._register_material_in_saiaset(settings_dir, brush_type, name, asset_grp_id, asset_grp_name)
        return bmp_path, ini_path, gid

    @classmethod
    def write_texture(cls, name: str, pil_img: Image.Image, tex_type: str,
                      settings_dir: str | None = None,
                      asset_group_id: int = 0, asset_group_name: str = '') -> tuple[str, int]:
        if not settings_dir:
            settings_dir = cls.get_settings_dir()
        if not settings_dir:
            raise FileNotFoundError("無法找到 SAI2 設定資料夾 (settings)")
        _require_valid_name(name)

        target_dir = os.path.join(settings_dir, tex_type)
        os.makedirs(target_dir, exist_ok=True)

        bmp_path = _safe_child_path(target_dir, f"{name}.bmp")

        gray_img = pil_img.convert('L')
        _backup_sai2_file(bmp_path)
        gray_img.save(bmp_path, format='BMP')

        gid = cls._register_texture_in_saiaset(settings_dir, tex_type, name, asset_group_id, asset_group_name)
        return bmp_path, gid

    @classmethod
    def _parse_saiaset_content(cls, text: str) -> tuple[list[str], list[int], list[str]]:
        """
        解析 _0.saiaset 的三段結構：
        .
        <0=gid 群組順序列表>
        .
        <scat,xxx 未分類項目列表>
        .
        --EOF--
        同時自動救援曾因舊版 bug 被插在第 3 個 '.' 之後的項目。
        """
        raw_lines = [l.strip() for l in text.splitlines()]
        header_lines: list[str] = []
        group_ids: list[int] = []
        item_lines: list[str] = []

        dot_count = 0
        for l in raw_lines:
            if not l or l == '--EOF--':
                continue
            if l == '.':
                dot_count += 1
                continue
            if dot_count == 0:
                header_lines.append(l)
            elif dot_count == 1:
                if '=' in l:
                    parts = l.split('=', 1)
                    if parts[0].strip().isdigit() and parts[1].strip().isdigit():
                        gid = int(parts[1].strip())
                        if gid not in group_ids:
                            group_ids.append(gid)
            else:
                # dot_count == 2 (正常未分類區) 或 dot_count >= 3 (舊版誤插在第3個 '.' 後的項目)
                if ',' in l and l not in item_lines:
                    item_lines.append(l)

        return header_lines, group_ids, item_lines

    @classmethod
    def _repair_saiaset_in_folder(cls, folder_path: str) -> bool:
        """
        檢查並修復指定素材資料夾 (scatter, brushfom, brushtex, papertex) 下的 _0.saiaset：
        1. 確保所有換行符號為純 LF ('\\n')，消除會導致 SAI2 解析失敗的 CRLF ('\\r\\n')
        2. 確保所有未分類素材項目位於第 2 個與第 3 個 '.' 之間（而非第 3 個 '.' 與 '--EOF--' 之間）
        3. 若該資料夾下存在 _N.saiagrp 分類檔但未列入 _0.saiaset，自動參考 bak/_0.saiaset 與磁碟檔案補齊分類順序
        """
        if not os.path.isdir(folder_path):
            return False
        set_path = os.path.join(folder_path, '_0.saiaset')
        if not os.path.isfile(set_path):
            return False

        try:
            with open(set_path, 'rb') as f:
                orig_bytes = f.read()
            # 嚴格解碼：無法解碼即放棄修復，避免改寫時遺失位元組
            text = _read_sai2_text(set_path)
            header_lines, group_ids, item_lines = cls._parse_saiaset_content(text)

            # 掃描磁碟上實際存在的 _N.saiagrp 分類檔
            disk_gids: list[int] = []
            for fname in os.listdir(folder_path):
                if fname.startswith('_') and fname.endswith('.saiagrp'):
                    stem = fname[1:-8]
                    if stem.isdigit():
                        disk_gids.append(int(stem))
            disk_gids.sort()

            # 若有遺失的分類 ID，優先參考 bak/_0.saiaset 的順序補回
            if any(dg not in group_ids for dg in disk_gids):
                bak_path = os.path.join(folder_path, 'bak', '_0.saiaset')
                if os.path.isfile(bak_path):
                    try:
                        with open(bak_path, 'rb') as bf:
                            _, bak_gids, _ = cls._parse_saiaset_content(bf.read().decode('utf-8', errors='ignore'))
                        for bg in bak_gids:
                            if bg in disk_gids and bg not in group_ids:
                                group_ids.append(bg)
                    except Exception:
                        pass
                for dg in disk_gids:
                    if dg not in group_ids:
                        group_ids.append(dg)

            # 移除已經存在於任何 _N.saiagrp 內的重複項目（避免 SAI2 報 Asitem Key conflicted）
            # 先完整讀取所有分類檔（任何一個無法解碼就整個放棄修復），再進行寫入
            categorized_items: set[str] = set()
            grp_fixes: list[tuple[str, bytes]] = []
            for dg in disk_gids:
                gpath = os.path.join(folder_path, f'_{dg}.saiagrp')
                if not os.path.isfile(gpath):
                    continue
                with open(gpath, 'rb') as gf:
                    g_raw = gf.read()
                g_text = _read_sai2_text(gpath)
                g_lines = [gl.strip() for gl in g_text.splitlines() if gl.strip()]
                for gl in g_lines:
                    if ',' in gl and not gl.startswith('name='):
                        categorized_items.add(gl)
                # 若 _N.saiagrp 含有 \r 也一併修復為純 LF
                if b'\r' in g_raw:
                    grp_fixes.append((gpath, ('\n'.join(g_lines) + '\n').encode('utf-8')))

            item_lines = [it for it in item_lines if it not in categorized_items]

            out_lines: list[str] = list(header_lines)
            out_lines.append('.')
            for idx, gid in enumerate(group_ids):
                out_lines.append(f"{idx}={gid}")
            out_lines.append('.')
            out_lines.extend(item_lines)
            out_lines.append('.')
            out_lines.append('--EOF--')

            changed = False
            for gpath, clean_g in grp_fixes:
                _write_sai2_file(gpath, clean_g)
                changed = True

            new_bytes = ('\n'.join(out_lines) + '\n').encode('utf-8')
            if new_bytes != orig_bytes:
                _write_sai2_file(set_path, new_bytes)
                changed = True
            return changed
        except Exception as e:
            print(f"[SAI2SettingsManager] Repair saiaset warning ({folder_path}): {e}")
        return False

    @classmethod
    def repair_all_saiaset_files(cls, settings_dir: str | None = None):
        """自動巡檢並修復 scatter, brushfom, brushtex, papertex 下的 _0.saiaset。
        SAI2 運行中一律跳過（SAI2 關閉時會以記憶體內容覆寫，且同時改寫有衝突風險）。"""
        if cls.is_sai2_running():
            return
        if not settings_dir:
            settings_dir = cls.get_settings_dir()
        if not settings_dir or not os.path.isdir(settings_dir):
            return
        for sub in ('scatter', 'brushfom', 'brushtex', 'papertex'):
            cls._repair_saiaset_in_folder(os.path.join(settings_dir, sub))

    @classmethod
    def get_asset_groups(cls, mode_type: str, settings_dir: str | None = None) -> list[dict]:
        """讀取指定素材類型 (scatter, brshape/blotmap->brushfom, brushtex, papertex) 的分類清單"""
        if not settings_dir:
            settings_dir = cls.get_settings_dir()
        groups = [{'id': 0, 'name': '(未分類)'}]
        if not settings_dir:
            return groups

        sub_map = {
            'scatter': 'scatter',
            'brshape': 'brushfom',
            'blotmap': 'brushfom',
            'brush': 'brushfom',      # UI「印章/形狀 (Shape)」模式的值為 'brush'
            'brushtex': 'brushtex',
            'papertex': 'papertex',
        }
        sub = sub_map.get(mode_type, 'scatter')
        folder = os.path.join(settings_dir, sub)
        if not os.path.isdir(folder):
            return groups

        # 只讀不寫：列出清單不應改動 SAI2 的檔案（_parse_saiaset_content 本身可容錯解析）。
        # 格式修復只在實際寫入素材時（_register_asset_in_folder / 佇列處理）進行，且會先備份。
        set_path = os.path.join(folder, '_0.saiaset')
        if not os.path.isfile(set_path):
            return groups

        try:
            with open(set_path, 'rb') as f:
                _, group_ids, _ = cls._parse_saiaset_content(f.read().decode('utf-8', errors='ignore'))
            for gid in group_ids:
                gpath = os.path.join(folder, f'_{gid}.saiagrp')
                gname = f"分類 {gid}"
                if os.path.isfile(gpath):
                    with open(gpath, 'rb') as gf:
                        for gl in gf.read().decode('utf-8', errors='ignore').splitlines():
                            if gl.startswith('name=U:'):
                                gname = gl.split(':', 1)[1].strip()
                                break
                groups.append({'id': gid, 'name': gname})
        except Exception as e:
            print(f"[SAI2SettingsManager] Read asset groups warning: {e}")
        return groups

    @classmethod
    def _register_asset_in_folder(cls, folder_path: str, tag: str,
                                  asset_group_id: int = 0, asset_group_name: str = '') -> int:
        """
        將素材標籤 (如 scat,xxx / bshp,xxx / btex,xxx / ptex,xxx) 註冊至指定的分類 (_N.saiagrp) 或未分類 (_0.saiaset)。
        嚴格遵守 SAI2 格式：
        - 未分類項目必須插入於 _0.saiaset 的第 2 個與第 3 個 '.' 之間
        - 分類項目必須插入於 _N.saiagrp 的第 1 個與第 2 個 '.' 之間
        - 統一使用純 LF ('\\n') 結尾，且確保同一 tag 不會在多個分類重複出現
        回傳最終實際歸屬的 asset_group_id (0 代表未分類)。
        """
        os.makedirs(folder_path, exist_ok=True)
        cls._repair_saiaset_in_folder(folder_path)
        set_path = os.path.join(folder_path, '_0.saiaset')
        # 分類名稱寫入 name=U: 單行欄位，移除換行等控制字元避免破壞檔案格式
        asset_group_name = ''.join(ch for ch in (asset_group_name or '') if ord(ch) >= 32).strip()

        # 先從所有現有 _N.saiagrp 移除同名舊 tag（避免切換分類時發生 Asitem Key conflicted）
        # 嚴格解碼：任何分類檔無法解碼即拋出例外中止註冊，不做有損改寫
        for fname in os.listdir(folder_path):
            if fname.startswith('_') and fname.endswith('.saiagrp'):
                gpath = os.path.join(folder_path, fname)
                g_lines = [gl.strip() for gl in _read_sai2_text(gpath).splitlines() if gl.strip()]
                if tag in g_lines:
                    g_lines = [gl for gl in g_lines if gl != tag]
                    _write_sai2_file(gpath, ('\n'.join(g_lines) + '\n').encode('utf-8'))

        # 讀取或初始化 _0.saiaset
        if os.path.isfile(set_path):
            header_lines, group_ids, item_lines = cls._parse_saiaset_content(_read_sai2_text(set_path))
        else:
            header_lines, group_ids, item_lines = [], [], []

        # 先從未分類移除同名舊 tag
        item_lines = [it for it in item_lines if it != tag]

        if asset_group_id > 0 or asset_group_name:
            asset_group_id = cls._resolve_group_id(
                folder_path, '.saiagrp', group_ids, asset_group_name, asset_group_id)
            gpath = os.path.join(folder_path, f'_{asset_group_id}.saiagrp')
            if os.path.isfile(gpath):
                raw_glines = [gl.strip() for gl in _read_sai2_text(gpath).splitlines() if gl.strip()]
                g_hdr: list[str] = []
                g_items: list[str] = []
                dots = 0
                for gl in raw_glines:
                    if gl == '--EOF--':
                        continue
                    if gl == '.':
                        dots += 1
                        continue
                    if dots == 0:
                        g_hdr.append(gl)
                    else:
                        if gl not in g_items:
                            g_items.append(gl)
                if tag not in g_items:
                    g_items.append(tag)
                if not g_hdr:
                    g_hdr = [f"name=U:{asset_group_name or f'分類 {asset_group_id}'}"]
                g_out = g_hdr + ['.'] + g_items + ['.', '--EOF--']
                _write_sai2_file(gpath, ('\n'.join(g_out) + '\n').encode('utf-8'))
            else:
                gname = asset_group_name or f"分類 {asset_group_id}"
                g_out = [f"name=U:{gname}", '.', tag, '.', '--EOF--']
                _write_sai2_file(gpath, ('\n'.join(g_out) + '\n').encode('utf-8'))
            if asset_group_id not in group_ids:
                group_ids.append(asset_group_id)
        else:
            # 放入未分類 (位於 _0.saiaset 的第 2 個與第 3 個 '.' 之間)
            if tag not in item_lines:
                item_lines.append(tag)

        # 寫回 _0.saiaset (純 LF)
        out_lines: list[str] = list(header_lines)
        out_lines.append('.')
        for idx, gid in enumerate(group_ids):
            out_lines.append(f"{idx}={gid}")
        out_lines.append('.')
        out_lines.extend(item_lines)
        out_lines.append('.')
        out_lines.append('--EOF--')
        _write_sai2_file(set_path, ('\n'.join(out_lines) + '\n').encode('utf-8'))

        return asset_group_id

    # 註冊失敗時直接拋出例外，讓呼叫端（UI / 佇列）得知失敗，
    # 避免「圖檔已寫入但未註冊」卻顯示成功的情況
    @classmethod
    def _register_material_in_saiaset(cls, settings_dir: str, brush_type: str, mat_name: str,
                                      asset_group_id: int = 0, asset_group_name: str = ''):
        if brush_type == 'scatter':
            folder = os.path.join(settings_dir, 'scatter')
            tag = f"scat,{mat_name}"
        else:
            folder = os.path.join(settings_dir, 'brushfom')
            tag = f"bshp,{mat_name}"
        return cls._register_asset_in_folder(folder, tag, asset_group_id, asset_group_name)

    @classmethod
    def _register_texture_in_saiaset(cls, settings_dir: str, tex_type: str, tex_name: str,
                                     asset_group_id: int = 0, asset_group_name: str = ''):
        folder = os.path.join(settings_dir, tex_type)
        tag = f"btex,{tex_name}" if tex_type == 'brushtex' else f"ptex,{tex_name}"
        return cls._register_asset_in_folder(folder, tag, asset_group_id, asset_group_name)

    @classmethod
    def write_tool(cls, tool_name: str, brush_type: str, material_name: str,
                   target_group_id: int, params: dict | None = None,
                   settings_dir: str | None = None, target_group_name: str = '') -> int:
        if not settings_dir:
            settings_dir = cls.get_settings_dir()
        if not settings_dir:
            raise FileNotFoundError("無法找到 SAI2 設定資料夾 (settings)")
        _require_valid_name(tool_name)
        _require_valid_name(material_name)

        custool_dir = os.path.join(settings_dir, 'custool', 'nrm')
        os.makedirs(custool_dir, exist_ok=True)

        tool_id = cls.get_next_tool_id(settings_dir)
        dat_path = os.path.join(custool_dir, f"{tool_id}.saitdat")

        p = params or {}
        brush_size = p.get('size', 60)
        spacing = p.get('spacing', 25)
        scattering = p.get('scattering', 0)
        angle_ctl = p.get('angle_control', 0)
        angle = p.get('angle', 0)
        angle_jitter = p.get('angle_jitter', 0)
        size_jitter = p.get('size_jitter', 0)
        pen_pressure = 1 if p.get('pen_pressure', True) else 0
        asset_group_id = p.get('asset_group_id', 0)

        if brush_type == 'scatter':
            dat_content = f"""tidstr=S:scatter
xidstr=S:
vkc=I:0
tabflt=I:0
tfmode=I:0
bzintf=I:1
name=U:{tool_name}
addt=U:
.
modstr=I:1836216174
wavno=I:4
curszscl=I:1
cursize=I:{brush_size * 10}
minsize=I:50
curdens=I:100
mindens=I:0
fomgid=I:{asset_group_id}
fomcat=I:4
fomnam=U:{material_name}
scathard=I:100
scatden=I:100
scatanc=I:{angle_ctl}
scatang=I:{angle}
scatanj=I:{angle_jitter}
scatscl=I:100
scatsiz=I:50
scatszscl=I:1
scatszj=I:{size_jitter}
scatspc=I:{spacing}
scatsct=I:{scattering}
scatwth=I:0
scatwhj=I:0
scatcnt=I:1
scatcnj=I:0
scataldf=I:0
scatgauf=I:0
scatabsf=I:0
scatintf=I:0
scathqsf=I:1
scatcolj=I:0
scathuej=I:0
scatsatj=I:0
scatbrij=I:0
scataesf=I:0
texgid=I:0
texcat=I:0
texnam=U:
texval=I:95
texscl=I:100
texscr=I:0
texinvf=I:0
texivtf=I:1
szprsf=I:{pen_pressure}
dnprsf=I:{pen_pressure}
szsens=I:100
dnsens=I:100
sbpos_patlist=I:0
previewbg=I:0
showf_scat=I:1
showf_scatcol=I:1
showf_tex=I:0
.
.
.
--EOF--
"""
        elif brush_type == 'texture_brush':
            dat_content = f"""tidstr=S:brush
xidstr=S:
vkc=I:0
tabflt=I:0
tfmode=I:0
bzintf=I:1
name=U:{tool_name}
addt=U:
.
modstr=I:1836216174
wavno=I:4
curszscl=I:1
cursize=I:{brush_size * 10}
minsize=I:50
curdens=I:100
mindens=I:0
fomgid=I:0
fomcat=I:0
fomnam=U:
blotval=I:50
blotscl=I:100
blotinvf=I:0
blotivtf=I:1
blotsharpf=I:0
brslmin=I:0
brslsiz=I:50
brslrnd=I:0
brsldir=I:1
brslturnf=I:1
scatden=I:100
scatanc=I:0
scatang=I:0
scatanj=I:0
scatscl=I:100
scatszj=I:0
scatspc=I:15
scatsct=I:0
scathqsf=I:1
texgid=I:{asset_group_id}
texcat=I:2
texnam=U:{material_name}
texval=I:70
texscl=I:100
texscr=I:0
texinvf=I:0
texivtf=I:1
blend=I:30
dilution=I:0
persist=I:80
keepaf=I:0
blurthres=I:50
hardness=I:80
densamp=I:0
v1dnprsf=I:0
flattenf=I:1
szprsf=I:{pen_pressure}
dnprsf=I:{pen_pressure}
blprsf=I:0
dlprsf=I:0
szsens=I:100
dnsens=I:100
blsens=I:100
sbpos_patlist=I:0
previewbg=I:1
showf_fom=I:0
showf_tex=I:1
.
.
.
--EOF--
"""
        else:  # brush (brshape)
            dat_content = f"""tidstr=S:brush
xidstr=S:
vkc=I:0
tabflt=I:0
tfmode=I:0
bzintf=I:1
name=U:{tool_name}
addt=U:
.
modstr=I:1836216174
wavno=I:4
curszscl=I:1
cursize=I:{brush_size * 10}
minsize=I:50
curdens=I:100
mindens=I:0
fomgid=I:{asset_group_id}
fomcat=I:3
fomnam=U:{material_name}
blotval=I:50
blotscl=I:100
blotinvf=I:0
blotivtf=I:1
blotsharpf=I:0
brslmin=I:0
brslsiz=I:50
brslrnd=I:0
brsldir=I:1
brslturnf=I:1
scatden=I:100
scatanc=I:{angle_ctl}
scatang=I:{angle}
scatanj=I:{angle_jitter}
scatscl=I:100
scatszj=I:{size_jitter}
scatspc=I:{spacing}
scatsct=I:{scattering}
scathqsf=I:1
texgid=I:0
texcat=I:0
texnam=U:
texval=I:95
texscl=I:100
texscr=I:0
texinvf=I:0
texivtf=I:1
blend=I:0
dilution=I:0
persist=I:100
keepaf=I:0
blurthres=I:50
hardness=I:100
densamp=I:0
v1dnprsf=I:0
flattenf=I:1
szprsf=I:{pen_pressure}
dnprsf=I:{pen_pressure}
blprsf=I:0
dlprsf=I:0
szsens=I:100
dnsens=I:100
blsens=I:100
sbpos_patlist=I:0
previewbg=I:1
showf_fom=I:1
showf_tex=I:0
.
.
.
--EOF--
"""
        # 分頁名稱寫入 name=U: 單行欄位，移除換行等控制字元
        target_group_name = ''.join(ch for ch in (target_group_name or '') if ord(ch) >= 32).strip()
        grp_id = cls._resolve_group_id(
            custool_dir, '.saitgrp', cls._read_saitset_group_ids(custool_dir),
            target_group_name, target_group_id)

        _write_sai2_file(dat_path, dat_content.encode('utf-8'))

        cls._add_tool_to_group(custool_dir, grp_id, tool_id, target_group_name)
        return tool_id

    @classmethod
    def _add_tool_to_group(cls, custool_dir: str, grp_id: int, tool_id: int, group_name: str = ''):
        grp_file = os.path.join(custool_dir, f'_{grp_id}.saitgrp')
        if not os.path.isfile(grp_file):
            content = f"vsbpos=I:0\nname=U:{group_name or '自製筆刷'}\ncsrbid0=I:0\ncsrbid1=I:0\ncsrbid2=I:0\nvkc=I:0\nprvbid0=I:0\nprvbid1=I:0\nprvbid2=I:0\n.\n0={tool_id}\n.\n--EOF--\n"
            _write_sai2_file(grp_file, content.encode('utf-8'))
            cls._register_group_in_saitset(custool_dir, grp_id)
            return

        # 嚴格解碼（無法解碼即拋出例外中止），並統一為 LF 以維持原本文字模式讀取的行為
        lines = _read_sai2_text(grp_file).replace('\r\n', '\n').splitlines(keepends=True)

        in_item_section = False
        items = []
        pre_lines = []
        post_lines = []
        period_count = 0

        for line in lines:
            trimmed = line.strip()
            if trimmed == '.':
                period_count += 1
                if period_count == 1:
                    pre_lines.append(line)
                    in_item_section = True
                    continue
                elif period_count == 2:
                    in_item_section = False
                    post_lines.append(line)
                    continue

            if in_item_section:
                if '=' in trimmed:
                    parts = trimmed.split('=', 1)
                    if parts[0].isdigit():
                        items.append((int(parts[0]), parts[1]))
            elif period_count < 1:
                pre_lines.append(line)
            else:
                post_lines.append(line)

        next_idx = max([it[0] for it in items], default=-1) + 1
        items.append((next_idx, str(tool_id)))

        new_content = "".join(pre_lines)
        for idx, tid in items:
            new_content += f"{idx}={tid}\n"
        new_content += "".join(post_lines)

        _write_sai2_file(grp_file, new_content.encode('utf-8'))

    @classmethod
    def _register_group_in_saitset(cls, custool_dir: str, grp_id: int):
        set_file = os.path.join(custool_dir, '_0.saitset')
        if not os.path.isfile(set_file):
            return
        try:
            lines = _read_sai2_text(set_file).replace('\r\n', '\n').splitlines(keepends=True)

            in_list = False
            g_items = []
            pre = []
            post = []
            p_count = 0
            for l in lines:
                tr = l.strip()
                if tr == '.':
                    p_count += 1
                    if p_count == 1:
                        pre.append(l)
                        in_list = True
                        continue
                    elif p_count == 2:
                        in_list = False
                        post.append(l)
                        continue
                if in_list and '=' in tr:
                    parts = tr.split('=', 1)
                    if parts[0].isdigit() and parts[1].isdigit():
                        g_items.append((int(parts[0]), int(parts[1])))
                elif p_count < 1:
                    pre.append(l)
                else:
                    post.append(l)

            if not any(g[1] == grp_id for g in g_items):
                next_gidx = max([g[0] for g in g_items], default=-1) + 1
                g_items.append((next_gidx, grp_id))

            out = "".join(pre)
            for gi, gval in g_items:
                out += f"{gi}={gval}\n"
            out += "".join(post)

            _write_sai2_file(set_file, out.encode('utf-8'))
        except Exception as e:
            print(f"[SAI2SettingsManager] Register group warning: {e}")


# ─── 圖像轉換與無縫處理演算法 ──────────────────────────────────────────────────

class BrushImageProcessor:
    """處理原始圖像，生成標準正方形 8-bit 灰階筆刷素材、紋理或紙張材質"""

    MODE_ALPHA      = 'alpha'       # 透明度為準
    MODE_WHITE_BG   = 'white_bg'    # 白底轉透明 (255 - 亮度)
    MODE_BLACK_BG   = 'black_bg'    # 黑底白線 (發光/原亮)
    MODE_SILHOUETTE = 'silhouette'  # 純實心形狀剪影

    @staticmethod
    def _masked_mean(gray: Image.Image, alpha: Image.Image, threshold: int,
                     default: float = 128.0) -> float:
        """alpha > threshold 區域的平均亮度（ImageStat 於 C 層計算）；沒有任何像素時回傳 default"""
        sel = alpha.point(lambda v: 255 if v > threshold else 0)
        if sel.getbbox() is None:
            return default
        return ImageStat.Stat(gray, sel).mean[0]

    @classmethod
    def process(cls, src_img: Image.Image, mode: str = 'alpha',
                autocrop: bool = True, padding_ratio: float = 0.08,
                target_size: int = 512, contrast_boost: float = 1.0) -> Image.Image:
        """筆刷形狀 / 散布圖案處理：輸出 255=筆觸、0=透明的 8-bit 灰階影像"""
        if src_img.mode != 'RGBA':
            src_img = src_img.convert('RGBA')

        w, h = src_img.size
        a = src_img.getchannel('A')

        if mode == cls.MODE_ALPHA:
            a_ext = a.getextrema()
            if a_ext[0] < 250:
                gray = ImageOps.grayscale(src_img)
                inv_gray = ImageOps.invert(gray)
                avg_l = cls._masked_mean(gray, a, 20)
                base_mask = inv_gray if avg_l < 128 else gray
                mask = Image.composite(base_mask, Image.new('L', (w, h), 0), a)
            else:
                gray = ImageOps.grayscale(src_img)
                mask = ImageOps.invert(gray)

        elif mode == cls.MODE_WHITE_BG:
            gray = ImageOps.grayscale(src_img)
            mask = ImageOps.invert(gray)

        elif mode == cls.MODE_BLACK_BG:
            mask = ImageOps.grayscale(src_img)

        elif mode == cls.MODE_SILHOUETTE:
            gray = ImageOps.grayscale(src_img)
            opaque = a.point(lambda v: 255 if v > 25 else 0)
            not_white = gray.point(lambda v: 255 if v < 250 else 0)
            mask = ImageChops.darker(opaque, not_white)   # 兩者皆成立才為 255（逐像素 AND）
        else:
            mask = a

        if contrast_boost != 1.0:
            mask = mask.point(lambda p: min(255, int(((p / 255.0) ** (1.0 / max(contrast_boost, 0.1))) * 255)))

        if autocrop:
            bbox = mask.getbbox()
            if bbox:
                mask = mask.crop(bbox)

        cur_w, cur_h = mask.size
        if cur_w == 0 or cur_h == 0:
            return Image.new('L', (target_size, target_size), 0)

        avail_size = int(target_size * (1.0 - padding_ratio * 2))
        scale = min(avail_size / cur_w, avail_size / cur_h)
        new_w = max(1, int(cur_w * scale))
        new_h = max(1, int(cur_h * scale))

        resized = mask.resize((new_w, new_h), Image.Resampling.LANCZOS)
        final_img = Image.new('L', (target_size, target_size), 0)
        paste_x = (target_size - new_w) // 2
        paste_y = (target_size - new_h) // 2
        final_img.paste(resized, (paste_x, paste_y))
        return final_img

    @classmethod
    def process_texture(cls, src_img: Image.Image, seamless_mode: str = 'crossfade',
                        blend_ratio: float = 0.25, contrast: float = 1.0,
                        brightness: float = 0.0, invert: bool = False,
                        target_size: int = 512, convert_mode: str = 'alpha') -> Image.Image:
        """
        將輸入影像處理為標準無縫平鋪的灰階紋理/紙張材質 (Mode: L)。
        完整保留並智慧處理 Alpha 透明度，避免手繪線條轉黑導致整張變黑。
        """
        if src_img.mode != 'RGBA':
            src_img = src_img.convert('RGBA')

        w, h = src_img.size
        # 1. 置中正方形裁切
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        sq_img = src_img.crop((left, top, left + side, top + side))
        sq_img = sq_img.resize((target_size, target_size), Image.Resampling.LANCZOS)

        a = sq_img.getchannel('A')
        a_ext = a.getextrema()
        has_alpha = a_ext[0] < 250

        if has_alpha:
            gray_raw = ImageOps.grayscale(sq_img)
            avg_l = cls._masked_mean(gray_raw, a, 20)

            if convert_mode == 'white_bg' or (convert_mode == 'alpha' and avg_l < 128):
                inv_gray = ImageOps.invert(gray_raw)
                gray = Image.composite(inv_gray, Image.new('L', sq_img.size, 0), a)
            else:
                gray = Image.composite(gray_raw, Image.new('L', sq_img.size, 0), a)
        else:
            gray_raw = ImageOps.grayscale(sq_img)
            if convert_mode == 'white_bg':
                gray = ImageOps.invert(gray_raw)
            else:
                gray = gray_raw

        # 2. 反轉明暗
        if invert:
            gray = ImageOps.invert(gray)

        # 3. 對比度與明暗微調
        if brightness != 0.0 or contrast != 1.0:
            b_offset = brightness * 128.0
            def _adjust(p):
                val = (p + b_offset - 128.0) * contrast + 128.0
                return max(0, min(255, int(val)))
            gray = gray.point(_adjust)

        # 4. 無縫處理
        if seamless_mode == 'crossfade':
            gray = cls._make_seamless_crossfade(gray, blend_ratio)
        elif seamless_mode == 'mirror':
            gray = cls._make_mirror_tile(gray)

        return gray

    @staticmethod
    def _make_seamless_crossfade(img: Image.Image, blend_ratio: float = 0.25) -> Image.Image:
        w, h = img.size
        ox, oy = w // 2, h // 2
        wrapped = Image.new('L', (w, h))
        wrapped.paste(img.crop((ox, oy, w, h)), (0, 0))
        wrapped.paste(img.crop((0, oy, ox, h)), (w - ox, 0))
        wrapped.paste(img.crop((ox, 0, w, oy)), (0, h - oy))
        wrapped.paste(img.crop((0, 0, ox, oy)), (w - ox, h - oy))

        bw_x = max(2, int(w * blend_ratio))
        bw_y = max(2, int(h * blend_ratio))

        def _weights(n: int, bw: int) -> list[int]:
            c = n / 2.0
            out = []
            for i in range(n):
                d = abs(i - c)
                wgt = (0.5 - 0.5 * math.cos((1.0 - d / bw) * math.pi)) if d < bw else 0.0
                out.append(int(round(wgt * 255)))
            return out

        # 權重可分離為 x、y 兩條一維曲線：只算 w + h 個值，再拉伸成整張並做飽和加法
        # （= min(1, wx + wy)），取代原本 w×h 次的 Python 逐像素迴圈
        row = Image.new('L', (w, 1))
        row.putdata(_weights(w, bw_x))
        col = Image.new('L', (1, h))
        col.putdata(_weights(h, bw_y))
        mask = ImageChops.add(row.resize((w, h), Image.Resampling.NEAREST),
                              col.resize((w, h), Image.Resampling.NEAREST))
        return Image.composite(img, wrapped, mask)

    @staticmethod
    def _make_mirror_tile(img: Image.Image) -> Image.Image:
        w, h = img.size
        half_w, half_h = w // 2, h // 2
        sub = img.resize((half_w, half_h), Image.Resampling.LANCZOS)
        sub_h = ImageOps.mirror(sub)
        sub_v = ImageOps.flip(sub)
        sub_hv = ImageOps.flip(sub_h)

        res = Image.new('L', (w, h))
        res.paste(sub, (0, 0))
        res.paste(sub_h, (half_w, 0))
        res.paste(sub_v, (0, half_h))
        res.paste(sub_hv, (half_w, half_h))
        return res


# ─── 待套用筆刷背景佇列 ────────────────────────────────────────────────────────

PENDING_QUEUE_FILE = os.path.join(_APP_DIR, 'sai2_pending_brushes.json')
PENDING_ASSET_DIR = os.path.join(_APP_DIR, 'sai2_pending_assets')
FAILED_QUEUE_FILE = os.path.join(_APP_DIR, 'sai2_pending_brushes_failed.json')

class PendingBrushQueue:
    """
    管理在 SAI2 運行時排隊、待 SAI2 關閉時自動寫入的佇列。

    任務格式：
        {
          'tool_name', 'brush_type', 'material_name', 'target_group_id', 'params',
          'create_tool': bool,            # 是否建立工具（舊版任務無此欄位，視為 True）
          'asset': {                      # 選填：素材本身也延後寫入（舊版任務無此欄位）
              'kind': 'material' | 'texture',
              'type': 'scatter' | 'brush' | 'brushtex' | 'papertex',
              'image': <暫存 PNG 路徑>,
              'asset_group_id', 'asset_group_name',
              'done': bool,               # 素材已寫入（工具寫入失敗重試時不重複處理）
          },
        }
    """

    MAX_ATTEMPTS = 5   # 可重試錯誤的最大嘗試次數（每次間隔約 15 秒）

    @classmethod
    def load_tasks(cls) -> list[dict]:
        if not os.path.isfile(PENDING_QUEUE_FILE):
            return []
        try:
            with open(PENDING_QUEUE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            # 檔案毀損時保留原檔供人工救援，避免下次 save_tasks 直接覆蓋掉
            print(f"[PendingBrushQueue] Load error: {e}")
            try:
                os.replace(PENDING_QUEUE_FILE, PENDING_QUEUE_FILE + f'.corrupt_{int(time.time())}')
            except Exception:
                pass
            return []

    @classmethod
    def save_tasks(cls, tasks: list[dict]):
        try:
            if not tasks:
                if os.path.isfile(PENDING_QUEUE_FILE):
                    os.remove(PENDING_QUEUE_FILE)
                return
            tmp = PENDING_QUEUE_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(tasks, f, ensure_ascii=False, indent=2)
            os.replace(tmp, PENDING_QUEUE_FILE)
        except Exception as e:
            print(f"[PendingBrushQueue] Save error: {e}")

    @classmethod
    def add_task(cls, task: dict):
        tasks = cls.load_tasks()
        tasks.append(task)
        cls.save_tasks(tasks)

    @classmethod
    def add_deploy_task(cls, name: str, mode: str, image: Image.Image | None,
                        params: dict, target_group_id: int, create_tool: bool,
                        tool_type: str, target_group_name: str = ''):
        """
        將「素材 + (選擇性) 工具」整組排入佇列。素材圖檔先存到 sai2_pending_assets/，
        待 SAI2 關閉後才寫入 SAI2 settings 並註冊，SAI2 運行期間完全不碰其設定檔。
        """
        _require_valid_name(name)
        if image is None:
            raise ValueError("沒有可儲存的圖像")
        os.makedirs(PENDING_ASSET_DIR, exist_ok=True)
        img_path = os.path.join(PENDING_ASSET_DIR, f"{uuid.uuid4().hex}.png")
        image.save(img_path, format='PNG')
        cls.add_task({
            'tool_name': name,
            'brush_type': tool_type,
            'material_name': name,
            'target_group_id': target_group_id,
            'target_group_name': target_group_name,   # 寫入時依名稱解析 ID（見 _resolve_group_id）
            'params': params,
            'create_tool': bool(create_tool),
            'asset': {
                'kind': 'texture' if mode in ('brushtex', 'papertex') else 'material',
                'type': mode,
                'image': img_path,
                'asset_group_id': params.get('asset_group_id', 0),
                'asset_group_name': params.get('asset_group_name', ''),
                'done': False,
            },
            'created_at': time.time(),
        })

    @classmethod
    def has_tasks(cls) -> bool:
        return bool(cls.load_tasks())

    @classmethod
    def _run_task(cls, t: dict):
        name = t['tool_name']
        params = t.get('params', {}) or {}
        asset = t.get('asset')
        if asset and not asset.get('done'):
            with Image.open(asset['image']) as img:
                img.load()
                if asset['kind'] == 'texture':
                    _, gid = SAI2SettingsManager.write_texture(
                        t['material_name'], img, asset['type'],
                        asset_group_id=asset.get('asset_group_id', 0),
                        asset_group_name=asset.get('asset_group_name', ''))
                else:
                    _, _, gid = SAI2SettingsManager.write_material(
                        t['material_name'], img, asset['type'], params)
            asset['resolved_group_id'] = gid
            asset['done'] = True   # 即使後續工具寫入失敗，重試時也不重複寫素材
        if asset and 'resolved_group_id' in asset:
            # 工具的 fomgid / texgid 必須指向素材實際被放入的分類
            params = dict(params, asset_group_id=asset['resolved_group_id'])
        if t.get('create_tool', True):
            SAI2SettingsManager.write_tool(
                name, t['brush_type'], t['material_name'], t['target_group_id'], params,
                target_group_name=t.get('target_group_name', ''))
        if asset:
            try:
                os.remove(asset['image'])
            except Exception:
                pass

    @staticmethod
    def _is_permanent_failure(t: dict, err: Exception) -> bool:
        """重試也不可能成功的錯誤：暫存素材圖檔已遺失，或名稱 / 路徑不合法"""
        asset = t.get('asset')
        if asset and not asset.get('done') and not os.path.isfile(asset.get('image', '')):
            return True
        return isinstance(err, ValueError)

    @classmethod
    def _archive_failed(cls, t: dict):
        """放棄重試的任務移到 FAILED_QUEUE_FILE 保存（暫存圖檔保留不刪），供使用者手動處理"""
        t['failed_at'] = time.time()
        failed = []
        if os.path.isfile(FAILED_QUEUE_FILE):
            try:
                with open(FAILED_QUEUE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    failed = data
            except Exception as e:
                print(f"[PendingBrushQueue] Load failed-list error: {e}")
        failed.append(t)
        try:
            tmp = FAILED_QUEUE_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(failed, f, ensure_ascii=False, indent=2)
            os.replace(tmp, FAILED_QUEUE_FILE)
        except Exception as e:
            print(f"[PendingBrushQueue] Save failed-list error: {e}")

    @classmethod
    def process_all_if_closed(cls) -> tuple[list[str], list[dict]]:
        """
        若 SAI2 已完全結束，將佇列中所有素材 / 筆刷寫入 SAI2 設定。
        呼叫端應在 SAI2 關閉後等待數秒再呼叫（讓 SAI2 先把自身快取寫回磁碟）。
        失敗的任務留在佇列中供下次重試；超過 MAX_ATTEMPTS 次或屬於無法重試的錯誤時，
        移到 FAILED_QUEUE_FILE 不再重試。

        回傳 (成功的名稱清單, 失敗清單)，失敗項目為
        {'name', 'error', 'attempts', 'gave_up'}，供呼叫端通知使用者。
        """
        tasks = cls.load_tasks()
        if not tasks:
            return [], []

        if SAI2SettingsManager.is_sai2_running():
            return [], []

        with sai2_write_session():
            return cls._process_tasks(tasks)

    @classmethod
    def _process_tasks(cls, tasks: list[dict]) -> tuple[list[str], list[dict]]:
        SAI2SettingsManager.repair_all_saiaset_files()

        succeeded = []
        failures = []
        remaining = []
        for t in tasks:
            try:
                cls._run_task(t)
                succeeded.append(t['tool_name'])
            except Exception as e:
                print(f"[PendingBrushQueue] Process failed for {t.get('tool_name')}: {e}")
                t['attempts'] = t.get('attempts', 0) + 1
                t['last_error'] = str(e)
                gave_up = cls._is_permanent_failure(t, e) or t['attempts'] >= cls.MAX_ATTEMPTS
                if gave_up:
                    cls._archive_failed(t)
                else:
                    remaining.append(t)   # 含已更新的 asset['done'] 狀態
                failures.append({'name': t.get('tool_name', '?'), 'error': str(e),
                                 'attempts': t['attempts'], 'gave_up': gave_up})

        cls.save_tasks(remaining)
        return succeeded, failures


# ─── 動態自適應試畫畫布 (Auto-resizing Scratchpad) ────────────────────────────

class ScratchpadCanvas(tk.Canvas):
    """
    供使用者用滑鼠/繪圖筆即時試畫塗抹筆刷與紋理效果的測試畫布。
    支援視窗縮放動態自適應，徹底解決框線內右側與下方無法繪製之問題。
    """

    def __init__(self, parent, width=320, height=280, **kwargs):
        super().__init__(parent, width=width, height=height, bg='#222222',
                         highlightthickness=1, highlightbackground=BORDER, **kwargs)
        self.w = max(10, width)
        self.h = max(10, height)

        self.brush_stamp_img: Image.Image | None = None
        self._stamp_cache: dict[int, Image.Image] = {}   # 尺寸 → 已縮放的印章，避免每個印章點都從 512px 重新縮放
        self.texture_img: Image.Image | None = None
        self.brush_type = 'scatter'
        self.brush_size = 50
        self.spacing = 25
        self.scattering = 0
        self.angle_ctl = 0
        self.angle = 0
        self.angle_jitter = 0
        self.size_jitter = 0
        self.ink_color = (240, 240, 240)
        self.bg_color = (34, 34, 34)

        self._buf_img = Image.new('RGB', (self.w, self.h), self.bg_color)
        self._buf_photo = None
        self._last_pt = None
        self._dist_accum = 0.0

        self.bind('<ButtonPress-1>', self._on_down)
        self.bind('<B1-Motion>', self._on_drag)
        self.bind('<ButtonRelease-1>', self._on_up)
        # 動態監聽畫布大小改變
        self.bind('<Configure>', self._on_canvas_resize)
        self._refresh_canvas()

    def _on_canvas_resize(self, event):
        """當畫布容器被使用者拉大或縮小時，自動將緩衝區影像等比拓展"""
        new_w = max(10, event.width)
        new_h = max(10, event.height)
        if new_w == self.w and new_h == self.h:
            return

        new_buf = Image.new('RGB', (new_w, new_h), self.bg_color)
        # 將原有內容無損貼到新尺寸的左上角
        new_buf.paste(self._buf_img, (0, 0))
        self._buf_img = new_buf
        self.w = new_w
        self.h = new_h
        self._refresh_canvas()

    def set_brush_params(self, stamp: Image.Image | None, brush_type: str,
                         size: int, spacing: int, scattering: int,
                         angle_ctl: int, angle: int, angle_jitter: int, size_jitter: int,
                         texture: Image.Image | None = None):
        if stamp is not self.brush_stamp_img:
            self._stamp_cache.clear()
        self.brush_stamp_img = stamp
        self.texture_img = texture
        self.brush_type = brush_type
        self.brush_size = max(4, size)
        self.spacing = max(1, spacing)
        self.scattering = scattering
        self.angle_ctl = angle_ctl
        self.angle = angle
        self.angle_jitter = angle_jitter
        self.size_jitter = size_jitter

    def clear(self):
        self._buf_img = Image.new('RGB', (self.w, self.h), self.bg_color)
        self._refresh_canvas()

    def set_bg_mode(self, mode: str):
        self.current_bg_mode = mode
        if mode == 'dark':
            self.bg_color = (30, 30, 30)
            self.ink_color = (240, 240, 240)
        elif mode == 'light':
            self.bg_color = (245, 245, 245)
            self.ink_color = (30, 30, 30)
        elif mode == 'accent':
            self.bg_color = (24, 24, 27)
            self.ink_color = (192, 132, 252)
        self.clear()

    def _on_down(self, event):
        self._last_pt = (event.x, event.y)
        self._dist_accum = 0.0
        self._draw_stamp(event.x, event.y, 0.0)
        self._refresh_canvas()

    def _on_drag(self, event):
        if not self._last_pt:
            self._last_pt = (event.x, event.y)
            return

        x0, y0 = self._last_pt
        x1, y1 = event.x, event.y
        dx = x1 - x0
        dy = y1 - y0
        seg_len = math.hypot(dx, dy)
        if seg_len < 1:
            return

        step_dist = max(2.0, (self.brush_size * (self.spacing / 100.0)))
        angle_rad = math.atan2(dy, dx)
        stroke_angle_deg = math.degrees(angle_rad)

        dist = self._dist_accum
        while dist < seg_len:
            t = dist / seg_len
            px = x0 + dx * t
            py = y0 + dy * t
            self._draw_stamp(px, py, stroke_angle_deg)
            dist += step_dist

        self._dist_accum = dist - seg_len
        self._last_pt = (x1, y1)
        self._refresh_canvas()

    def _on_up(self, event):
        self._last_pt = None
        self._dist_accum = 0.0

    def _draw_stamp(self, x: float, y: float, stroke_angle: float):
        if self.brush_type in ('brushtex', 'papertex'):
            draw = ImageDraw.Draw(self._buf_img)
            r = self.brush_size / 2.0
            draw.ellipse([x - r, y - r, x + r, y + r], fill=self.ink_color)
            return

        if not self.brush_stamp_img:
            draw = ImageDraw.Draw(self._buf_img)
            r = self.brush_size / 2.0
            draw.ellipse([x - r, y - r, x + r, y + r], fill=self.ink_color)
            return

        cur_sz = self.brush_size
        if self.size_jitter > 0:
            scale_mod = 1.0 + (random.random() * 2 - 1) * (self.size_jitter / 100.0) * 0.7
            cur_sz = max(4, int(cur_sz * max(0.1, scale_mod)))

        cx, cy = x, y
        if self.scattering > 0:
            offset_max = self.brush_size * (self.scattering / 100.0) * 1.5
            cx += (random.random() * 2 - 1) * offset_max
            cy += (random.random() * 2 - 1) * offset_max

        cur_ang = self.angle
        if self.angle_ctl == 2:
            cur_ang += stroke_angle
        elif self.angle_ctl == 1:
            cur_ang += (time.time() * 100) % 360

        if self.angle_jitter > 0:
            cur_ang += (random.random() * 2 - 1) * 180 * (self.angle_jitter / 100.0)

        stamp = self.brush_stamp_img
        if stamp.size != (cur_sz, cur_sz):
            cached = self._stamp_cache.get(cur_sz)
            if cached is None:
                if len(self._stamp_cache) >= 64:
                    self._stamp_cache.clear()
                cached = stamp.resize((cur_sz, cur_sz), Image.Resampling.BILINEAR)
                self._stamp_cache[cur_sz] = cached
            stamp = cached

        if abs(cur_ang % 360) > 0.5:
            stamp = stamp.rotate(-cur_ang, resample=Image.Resampling.BILINEAR, expand=True)

        sw, sh = stamp.size
        left = int(cx - sw / 2.0)
        top = int(cy - sh / 2.0)

        tinted = Image.new('RGB', (sw, sh), self.ink_color)
        self._buf_img.paste(tinted, (left, top), mask=stamp)

    def _refresh_canvas(self):
        photo = self._buf_photo
        if photo is not None and (photo.width(), photo.height()) == self._buf_img.size:
            # 尺寸未變：直接更新既有 Tk 影像，避免每個拖曳事件都重建 PhotoImage 與 canvas 物件
            photo.paste(self._buf_img)
            return
        self._buf_photo = ImageTk.PhotoImage(self._buf_img)
        self.delete('all')
        self.create_image(0, 0, image=self._buf_photo, anchor='nw')


# ─── 筆刷與紋理工作台主視窗 (Brush & Texture Studio) ───────────────────────────

class BrushStudioWindow(tk.Toplevel):
    """SAI2 筆刷、紋理與材質製作工坊主視窗"""

    def __init__(self, parent, on_brush_created_callback=None):
        super().__init__(parent)
        self.parent = parent
        self.on_brush_created_callback = on_brush_created_callback

        self.title(_tr('ui.brush_studio.title', "🖌️ SAI2 筆刷與紋理製作工坊 (Brush & Texture Studio)"))
        self.configure(bg=BG)
        self.geometry("980x680")
        self.minsize(880, 600)

        # 不設 transient：transient 視窗會跟著主視窗最小化而隱藏，主視窗縮小時用快捷鍵叫出會看不到
        self.focus_force()

        # 讀取使用者上次設定
        self._saved_cfg = BrushStudioSettings.load()

        # 內部狀態
        self._raw_image: Image.Image | None = None       # 原始全解析度來源（最終寫入時使用）
        self._preview_src: Image.Image | None = None     # 縮小後的 RGBA 工作副本（即時預覽用）
        self._update_job = None                          # 延遲重算的 after() 排程
        self._processed_stamp: Image.Image | None = None
        self._processed_texture: Image.Image | None = None
        self._settings_dir = SAI2SettingsManager.get_settings_dir()
        self._tool_groups = SAI2SettingsManager.get_tool_groups(self._settings_dir)
        self._asset_groups = SAI2SettingsManager.get_asset_groups(
            self._saved_cfg.get('main_mode', 'scatter'), self._settings_dir
        )

        # 核心分類模式
        self.var_main_mode = tk.StringVar(value=self._saved_cfg.get('main_mode', 'scatter'))

        # 預覽檢視模式
        self.var_preview_view = tk.StringVar(value=self._saved_cfg.get('preview_view', 'single'))

        # UI 綁定變數
        self.var_brush_name = tk.StringVar(value=f"自製筆刷_{random.randint(10, 99)}")
        self.var_convert_mode = tk.StringVar(value=self._saved_cfg.get('convert_mode', 'alpha'))
        self.var_autocrop = tk.BooleanVar(value=self._saved_cfg.get('autocrop', True))
        self.var_target_group = tk.StringVar()
        saved_grp = self._saved_cfg.get('target_group', '')
        if saved_grp and any(g['name'] == saved_grp for g in self._tool_groups):
            self.var_target_group.set(saved_grp)
        elif self._tool_groups:
            pref = next((g['name'] for g in self._tool_groups if '效果' in g['name'] or '基本' in g['name']), self._tool_groups[0]['name'])
            self.var_target_group.set(pref)

        self.var_asset_group = tk.StringVar(value=self._saved_cfg.get('asset_group', '(未分類)'))

        # 筆刷專用參數 (從上次設定還原)
        self.var_size = tk.IntVar(value=self._saved_cfg.get('size', 60))
        self.var_spacing = tk.IntVar(value=self._saved_cfg.get('spacing', 35))
        self.var_scattering = tk.IntVar(value=self._saved_cfg.get('scattering', 30))
        self.var_angle_ctl = tk.IntVar(value=self._saved_cfg.get('angle_ctl', 0))
        self.var_angle = tk.IntVar(value=self._saved_cfg.get('angle', 0))
        self.var_angle_jitter = tk.IntVar(value=self._saved_cfg.get('angle_jitter', 20))
        self.var_size_jitter = tk.IntVar(value=self._saved_cfg.get('size_jitter', 30))
        self.var_pen_pressure = tk.BooleanVar(value=self._saved_cfg.get('pen_pressure', True))

        # 紋理/材質專用參數 (從上次設定還原)
        self.var_seamless_mode = tk.StringVar(value=self._saved_cfg.get('seamless_mode', 'crossfade'))
        self.var_blend_margin = tk.IntVar(value=self._saved_cfg.get('blend_margin', 25))
        self.var_tex_res = tk.IntVar(value=self._saved_cfg.get('tex_res', 256))
        self.var_contrast = tk.DoubleVar(value=self._saved_cfg.get('contrast', 1.0))
        self.var_brightness = tk.DoubleVar(value=self._saved_cfg.get('brightness', 0.0))
        self.var_invert = tk.BooleanVar(value=self._saved_cfg.get('invert', False))
        self.var_create_texture_brush = tk.BooleanVar(value=self._saved_cfg.get('create_texture_brush', True))

        self._build_ui()

        # 綁定全域貼上快捷鍵 Ctrl+V
        self.bind('<Control-v>', self._on_ctrl_v)
        self.bind('<Control-V>', self._on_ctrl_v)

        # 視窗關閉時自動儲存所有參數設定
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # 還原畫布底色
        pad_bg = self._saved_cfg.get('pad_bg_mode', 'dark')
        self.pad.set_bg_mode(pad_bg)

        self._load_from_clipboard_silent()
        self._on_mode_switched()
        self._update_sai2_status()

    def _on_window_close(self):
        """關閉視窗前持久化所有參數"""
        self._save_current_settings()
        self.destroy()

    def destroy(self):
        # 取消所有排程：視窗銷毀後仍觸發會對已不存在的元件操作而拋出 TclError
        for attr in ('_update_job', '_status_job'):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, attr, None)
        super().destroy()

    def _save_current_settings(self):
        """將當前視窗的所有選項保存到設定檔"""
        cfg = {
            'main_mode': self.var_main_mode.get(),
            'preview_view': self.var_preview_view.get(),
            'target_group': self.var_target_group.get(),
            'asset_group': self.var_asset_group.get(),
            'size': self.var_size.get(),
            'spacing': self.var_spacing.get(),
            'scattering': self.var_scattering.get(),
            'angle_ctl': self.var_angle_ctl.get(),
            'angle': self.var_angle.get(),
            'angle_jitter': self.var_angle_jitter.get(),
            'size_jitter': self.var_size_jitter.get(),
            'pen_pressure': self.var_pen_pressure.get(),
            'convert_mode': self.var_convert_mode.get(),
            'autocrop': self.var_autocrop.get(),
            'seamless_mode': self.var_seamless_mode.get(),
            'blend_margin': self.var_blend_margin.get(),
            'tex_res': self.var_tex_res.get(),
            'contrast': self.var_contrast.get(),
            'brightness': self.var_brightness.get(),
            'invert': self.var_invert.get(),
            'create_texture_brush': self.var_create_texture_brush.get(),
            'pad_bg_mode': getattr(self.pad, 'current_bg_mode', 'dark'),
        }
        BrushStudioSettings.save(cfg)

    def _build_ui(self):
        # ── 頂部標題與主分類切換列 ───────────────────────────────────────────
        hdr = tk.Frame(self, bg=CARD, padx=16, pady=8)
        hdr.pack(fill='x')

        left_hdr = tk.Frame(hdr, bg=CARD)
        left_hdr.pack(side='left')
        tk.Label(left_hdr, text=_tr('ui.brush_studio.hdr_title', "🖌️ SAI2 筆刷與紋理工坊"),
                 font=FT_TITLE, fg=TEXT, bg=CARD).pack(anchor='w')
        tk.Label(left_hdr, text="支援剪貼簿快捷鍵 Ctrl+V 貼上圖像 | 自動無縫紋理平鋪 | 自動記憶數值",
                 font=FT_SMALL, fg=TEXTD, bg=CARD).pack(anchor='w')

        self.lbl_sai_status = tk.Label(hdr, text="偵測中...", font=FT_NORM, bg=CARD)
        self.lbl_sai_status.pack(side='right', padx=(10, 0))

        # 類別切換標籤列
        cat_bar = tk.Frame(self, bg=CARD2, padx=14, pady=5)
        cat_bar.pack(fill='x')

        modes = [
            ("✨ 散布筆刷 (Scatter)", "scatter"),
            ("🖌️ 印章/形狀 (Shape)", "brush"),
            ("🧶 筆刷紋理 (BrushTex)", "brushtex"),
            ("📜 紙張材質 (PaperTex)", "papertex"),
        ]
        self._mode_radios = []
        for text, val in modes:
            r = tk.Radiobutton(cat_bar, text=text, variable=self.var_main_mode, value=val,
                               font=FT_HEAD, fg=TEXT, bg=CARD2, selectcolor=ACCENT,
                               activebackground=CARD2, activeforeground='white',
                               indicatoron=0, padx=14, pady=4, cursor='hand2',
                               command=self._on_mode_switched)
            r.pack(side='left', padx=3)
            self._mode_radios.append(r)

        # ── 主內容區域 ───────────────────────────────────────────────────────
        content = tk.Frame(self, bg=BG, padx=12, pady=10)
        content.pack(fill='both', expand=True)
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=4)
        content.columnconfigure(2, weight=4)
        content.rowconfigure(0, weight=1)

        # ── 欄位 1：圖案來源與預覽 ─────────────────────────────────────────────
        col1 = tk.Frame(content, bg=CARD, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
        col1.grid(row=0, column=0, sticky='nsew', padx=(0, 6))

        tk.Label(col1, text="1. 圖案來源與預覽", font=FT_HEAD, fg=TEXT, bg=CARD).pack(anchor='w', pady=(0, 6))

        # 縮圖預覽框
        self.canvas_preview = tk.Canvas(col1, width=190, height=190, bg='#1a1a1a',
                                        highlightthickness=1, highlightbackground=BORDER)
        self.canvas_preview.pack(pady=2)

        # 預覽檢視切換按鈕
        self.prev_toggle_box = tk.Frame(col1, bg=CARD)
        self.prev_toggle_box.pack(fill='x', pady=3)
        tk.Radiobutton(self.prev_toggle_box, text="單圖檢視", variable=self.var_preview_view, value="single",
                       font=FT_SMALL, fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=self._render_preview).pack(side='left', padx=2)
        tk.Radiobutton(self.prev_toggle_box, text="3×3 平鋪預覽", variable=self.var_preview_view, value="tiled",
                       font=FT_SMALL, fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=self._render_preview).pack(side='left', padx=4)

        # 來源按鈕 (支援點擊與提示 Ctrl+V)
        btn_box = tk.Frame(col1, bg=CARD)
        btn_box.pack(fill='x', pady=4)
        self._create_btn(btn_box, "📋 剪貼簿貼上 (Ctrl+V)", self._on_click_clip).pack(side='left', fill='x', expand=True, padx=(0, 3))
        self._create_btn(btn_box, "📁 開啟圖片", self._on_click_file).pack(side='right', fill='x', expand=True, padx=(3, 0))

        # 去背與形狀模式 (通用於筆刷與紋理)
        self.frame_src_common = tk.Frame(col1, bg=CARD)
        self.frame_src_common.pack(fill='x', pady=(6, 0))

        tk.Label(self.frame_src_common, text="色彩與去背模式：", font=FT_BOLD, fg=TEXT, bg=CARD).pack(anchor='w', pady=(2, 2))
        brush_modes = [
            ("透明背景 (Alpha形狀/保留線條)", "alpha"),
            ("白底黑線 (亮度轉透明/反轉)", "white_bg"),
            ("黑底白線 (發光/原亮)", "black_bg"),
            ("實心剪影 (填滿不透明)", "silhouette"),
        ]
        for text, val in brush_modes:
            tk.Radiobutton(self.frame_src_common, text=text, variable=self.var_convert_mode, value=val,
                           font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                           command=self._on_param_changed).pack(anchor='w', pady=1)

        self.chk_autocrop = tk.Checkbutton(
            self.frame_src_common, text="自動裁切多餘邊界 (Autocrop)",
            variable=self.var_autocrop, font=FT_NORM,
            fg=TEXT, bg=CARD, selectcolor=CARD2,
            command=self._on_param_changed
        )
        self.chk_autocrop.pack(anchor='w', pady=(4, 0))

        # 紋理專用無縫選項框架
        self.frame_src_texture = tk.Frame(col1, bg=CARD)
        tk.Label(self.frame_src_texture, text="無縫接縫平鋪處理 (Seamless)：", font=FT_BOLD, fg=TEXT, bg=CARD).pack(anchor='w', pady=(2, 2))
        tex_modes = [
            ("無縫平滑融合 (Cross-fade 推薦)", "crossfade"),
            ("2×2 鏡像對稱平鋪 (Mirror)", "mirror"),
            ("保持原樣 (不進行接縫處理)", "none"),
        ]
        for text, val in tex_modes:
            tk.Radiobutton(self.frame_src_texture, text=text, variable=self.var_seamless_mode, value=val,
                           font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                           command=self._on_param_changed).pack(anchor='w', pady=1)

        # ── 欄位 2：參數配置 ──────────────────────────────────────────────────
        col2 = tk.Frame(content, bg=CARD, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
        col2.grid(row=0, column=1, sticky='nsew', padx=3)

        tk.Label(col2, text="2. 名稱與參數設定", font=FT_HEAD, fg=TEXT, bg=CARD).pack(anchor='w', pady=(0, 6))

        # 名稱輸入
        self.lbl_name_prompt = tk.Label(col2, text="筆刷名稱：", font=FT_NORM, fg=TEXT, bg=CARD)
        self.lbl_name_prompt.pack(anchor='w')
        ent_name = tk.Entry(col2, textvariable=self.var_brush_name, font=FT_NORM,
                            bg=CARD2, fg=TEXT, insertbackground=TEXT, relief='flat',
                            highlightthickness=1, highlightbackground=BORDER)
        ent_name.pack(fill='x', pady=(2, 6), ipady=3)

        # 目標分頁與素材分類
        self.frame_group_sel = tk.Frame(col2, bg=CARD)
        self.frame_group_sel.pack(fill='x', pady=(0, 4))
        tk.Label(self.frame_group_sel, text="加入 SAI2 工具分頁 (群組)：", font=FT_NORM, fg=TEXT, bg=CARD).pack(anchor='w')
        grp_names = [g['name'] for g in self._tool_groups] or ["基本", "二值", "效果"]
        self.cbo_group = ttk.Combobox(self.frame_group_sel, textvariable=self.var_target_group, values=grp_names, font=FT_NORM)
        self.cbo_group.pack(fill='x', pady=(2, 0))

        self.frame_asset_grp_sel = tk.Frame(col2, bg=CARD)
        self.frame_asset_grp_sel.pack(fill='x', pady=(0, 6))
        tk.Label(self.frame_asset_grp_sel, text="存入素材庫分類：", font=FT_NORM, fg=TEXT, bg=CARD).pack(anchor='w')
        asset_grp_names = [g['name'] for g in self._asset_groups] or ["(未分類)"]
        self.cbo_asset_group = ttk.Combobox(self.frame_asset_grp_sel, textvariable=self.var_asset_group, values=asset_grp_names, font=FT_NORM)
        self.cbo_asset_group.pack(fill='x', pady=(2, 0))

        # 筆刷參數容器
        self.box_brush_params = tk.Frame(col2, bg=CARD)
        self.box_brush_params.pack(fill='both', expand=True)

        # 以下參數只影響試畫區的筆觸模擬，不改變素材圖像本身 → 不需重算圖像
        brush_cb = self._on_brush_param_changed
        self._add_slider(self.box_brush_params, "間距 (Spacing %):", self.var_spacing, 1, 300, brush_cb)
        self._add_slider(self.box_brush_params, "散布幅度 (Scattering %):", self.var_scattering, 0, 200, brush_cb)
        self._add_slider(self.box_brush_params, "尺寸大小 (Size px):", self.var_size, 10, 500, brush_cb)
        self._add_slider(self.box_brush_params, "尺寸抖動 (Size Jitter %):", self.var_size_jitter, 0, 100, brush_cb)
        self._add_slider(self.box_brush_params, "角度抖動 (Angle Jitter %):", self.var_angle_jitter, 0, 100, brush_cb)

        ang_box = tk.Frame(self.box_brush_params, bg=CARD)
        ang_box.pack(fill='x', pady=3)
        tk.Label(ang_box, text="角度控制：", font=FT_NORM, fg=TEXT, bg=CARD).pack(side='left')
        tk.Radiobutton(ang_box, text="無", variable=self.var_angle_ctl, value=0,
                       font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=brush_cb).pack(side='left')
        tk.Radiobutton(ang_box, text="隨筆向", variable=self.var_angle_ctl, value=2,
                       font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=brush_cb).pack(side='left', padx=4)
        tk.Radiobutton(ang_box, text="自動", variable=self.var_angle_ctl, value=1,
                       font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=brush_cb).pack(side='left')

        tk.Checkbutton(self.box_brush_params, text="啟用繪圖板筆壓 (感應大小與濃度)",
                       variable=self.var_pen_pressure, font=FT_NORM,
                       fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=brush_cb).pack(anchor='w', pady=(3, 0))

        # 紋理與材質專用參數容器
        self.box_texture_params = tk.Frame(col2, bg=CARD)

        self._add_slider(self.box_texture_params, "融合過渡比例 (%):", self.var_blend_margin, 10, 50)

        res_frame = tk.Frame(self.box_texture_params, bg=CARD)
        res_frame.pack(fill='x', pady=3)
        tk.Label(res_frame, text="材質輸出尺寸：", font=FT_NORM, fg=TEXT, bg=CARD).pack(side='left')
        for r_val, r_text in [(256, "256×256"), (512, "512×512"), (1024, "1024×1024")]:
            tk.Radiobutton(res_frame, text=r_text, variable=self.var_tex_res, value=r_val,
                           font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                           command=self._on_param_changed).pack(side='left', padx=2)

        f_cnt = tk.Frame(self.box_texture_params, bg=CARD)
        f_cnt.pack(fill='x', pady=2)
        self.lbl_contrast = tk.Label(f_cnt, text=f"對比度增強: {self.var_contrast.get():.2f}x", font=FT_NORM, fg=TEXT, bg=CARD)
        self.lbl_contrast.pack(side='top', anchor='w')
        def _on_cnt_slide(val):
            self.lbl_contrast.config(text=f"對比度增強: {float(val):.2f}x")
            self._on_param_changed()
        ttk.Scale(f_cnt, from_=0.3, to=3.0, variable=self.var_contrast, command=_on_cnt_slide).pack(side='top', fill='x')

        f_brt = tk.Frame(self.box_texture_params, bg=CARD)
        f_brt.pack(fill='x', pady=2)
        self.lbl_bright = tk.Label(f_brt, text=f"亮度偏移: {int(self.var_brightness.get()*100)}%", font=FT_NORM, fg=TEXT, bg=CARD)
        self.lbl_bright.pack(side='top', anchor='w')
        def _on_brt_slide(val):
            self.lbl_bright.config(text=f"亮度偏移: {int(float(val)*100)}%")
            self._on_param_changed()
        ttk.Scale(f_brt, from_=-0.5, to=0.5, variable=self.var_brightness, command=_on_brt_slide).pack(side='top', fill='x')

        tk.Checkbutton(self.box_texture_params, text="反轉黑白明暗 (Invert Lightness)",
                       variable=self.var_invert, font=FT_NORM,
                       fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=self._on_param_changed).pack(anchor='w', pady=(3, 0))

        self.chk_create_tex_brush = tk.Checkbutton(
            self.box_texture_params, text="✨ 同時在 SAI2 工具面板建立「質感筆刷」",
            variable=self.var_create_texture_brush, font=FT_NORM,
            fg=YELLOW, bg=CARD, selectcolor=CARD2, activebackground=CARD, activeforeground=YELLOW
        )
        self.chk_create_tex_brush.pack(anchor='w', pady=(4, 0))

        # ── 欄位 3：試畫區與操作按鈕 ─────────────────────────────────────────
        col3 = tk.Frame(content, bg=CARD, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
        col3.grid(row=0, column=2, sticky='nsew', padx=(6, 0))

        pad_hdr = tk.Frame(col3, bg=CARD)
        pad_hdr.pack(fill='x', pady=(0, 4))
        self.lbl_pad_title = tk.Label(pad_hdr, text="3. 即時手感試畫區", font=FT_HEAD, fg=TEXT, bg=CARD)
        self.lbl_pad_title.pack(side='left')

        self._create_btn(pad_hdr, "🧹 清除", self._on_clear_pad, pad=(6, 1)).pack(side='right')

        bg_btn_box = tk.Frame(col3, bg=CARD)
        bg_btn_box.pack(fill='x', pady=(0, 4))
        tk.Label(bg_btn_box, text="底色：", font=FT_SMALL, fg=TEXTD, bg=CARD).pack(side='left')
        self._create_btn(bg_btn_box, "深黑", lambda: self.pad.set_bg_mode('dark'), pad=(4, 1)).pack(side='left', padx=2)
        self._create_btn(bg_btn_box, "純白", lambda: self.pad.set_bg_mode('light'), pad=(4, 1)).pack(side='left', padx=2)
        self._create_btn(bg_btn_box, "羅蘭", lambda: self.pad.set_bg_mode('accent'), pad=(4, 1)).pack(side='left', padx=2)

        # 動態自適應畫布
        self.pad = ScratchpadCanvas(col3, width=280, height=260)
        self.pad.pack(fill='both', expand=True, pady=4)

        self.lbl_pad_tip = tk.Label(col3, text="※ 在上方試畫區拖曳即可即時模擬筆觸軌跡 (支援視窗自由縮放)",
                                    font=FT_SMALL, fg=TEXTD, bg=CARD)
        self.lbl_pad_tip.pack(anchor='w', pady=(2, 6))

        # 底部執行動作按鈕
        act_box = tk.Frame(col3, bg=CARD)
        act_box.pack(fill='x', side='bottom')

        self.btn_deploy = tk.Button(
            act_box, text="🚀 一鍵建立並加入 SAI2",
            font=FT_HEAD, bg=ACCENT, fg='white', activebackground=ACCH,
            activeforeground='white', relief='flat', cursor='hand2',
            command=self._on_click_deploy, pady=7
        )
        self.btn_deploy.pack(fill='x', pady=(0, 4))

        self.btn_mat_only = tk.Button(
            act_box, text="💾 僅儲存素材到素材庫",
            font=FT_NORM, bg=CARD2, fg=TEXT, activebackground=CARD3,
            activeforeground=TEXT, relief='flat', cursor='hand2',
            command=self._on_click_save_material_only, pady=4
        )
        self.btn_mat_only.pack(fill='x')

    def _create_btn(self, parent, text, cmd, pad=(8, 3)):
        b = tk.Button(parent, text=text, font=FT_NORM, bg=CARD2, fg=TEXT,
                      activebackground=ACCENT, activeforeground='white',
                      relief='flat', cursor='hand2', padx=pad[0], pady=pad[1], command=cmd)
        b.bind('<Enter>', lambda e: b.config(bg=CARD3))
        b.bind('<Leave>', lambda e: b.config(bg=CARD2))
        return b

    def _add_slider(self, parent, label_text, var, min_v, max_v, on_change=None):
        on_change = on_change or self._on_param_changed
        f = tk.Frame(parent, bg=CARD)
        f.pack(fill='x', pady=2)
        lbl = tk.Label(f, text=f"{label_text} {var.get()}", font=FT_NORM, fg=TEXT, bg=CARD)
        lbl.pack(side='top', anchor='w')

        def _on_slide(val):
            lbl.config(text=f"{label_text} {int(float(val))}")
            on_change()

        s = ttk.Scale(f, from_=min_v, to=max_v, variable=var, command=_on_slide)
        s.pack(side='top', fill='x')

    def _on_mode_switched(self):
        m = self.var_main_mode.get()
        is_texture_mode = m in ('brushtex', 'papertex')

        # 動態更新該模式對應的素材分類清單
        self._asset_groups = SAI2SettingsManager.get_asset_groups(m, self._settings_dir)
        asset_names = [g['name'] for g in self._asset_groups] or ["(未分類)"]
        self.cbo_asset_group.config(values=asset_names)
        if self.var_asset_group.get() not in asset_names:
            self.var_asset_group.set("(未分類)")

        if is_texture_mode:
            self.chk_autocrop.pack_forget()
            self.frame_src_texture.pack(fill='x', pady=(6, 0))
            self.var_preview_view.set("tiled")
        else:
            self.frame_src_texture.pack_forget()
            self.chk_autocrop.pack(anchor='w', pady=(4, 0))
            self.var_preview_view.set("single")

        if is_texture_mode:
            self.box_brush_params.pack_forget()
            self.box_texture_params.pack(fill='both', expand=True)
            if m == 'brushtex':
                self.lbl_name_prompt.config(text="紋理名稱 (BrushTex)：")
                self.chk_create_tex_brush.pack(anchor='w', pady=(4, 0))
                self.frame_group_sel.pack(fill='x', pady=(0, 4), before=self.frame_asset_grp_sel)
                self.btn_deploy.config(text="🚀 儲存紋理並建立質感筆刷")
                self.btn_mat_only.config(text="💾 僅將紋理存入 brushtex 目錄")
            else:  # papertex
                self.lbl_name_prompt.config(text="材質名稱 (PaperTex)：")
                self.chk_create_tex_brush.pack_forget()
                self.frame_group_sel.pack_forget()
                self.btn_deploy.config(text="🚀 儲存至 SAI2 紙張材質庫")
                self.btn_mat_only.config(text="💾 僅將材質存入 papertex 目錄")
        else:
            self.box_texture_params.pack_forget()
            self.box_brush_params.pack(fill='both', expand=True)
            self.frame_group_sel.pack(fill='x', pady=(0, 4), before=self.frame_asset_grp_sel)
            self.lbl_name_prompt.config(text="筆刷名稱：")
            self.btn_deploy.config(text="🚀 一鍵建立並加入 SAI2")
            self.btn_mat_only.config(text="💾 僅儲存素材到素材庫")

        self._update_processed_output()

    def _update_sai2_status(self):
        is_running = SAI2SettingsManager.is_sai2_running()
        if is_running:
            self.lbl_sai_status.config(
                text="🟡 SAI2 運行中 (提供安全防覆蓋寫入)",
                fg=YELLOW
            )
        else:
            self.lbl_sai_status.config(
                text="🟢 SAI2 未運行 (可直接寫入並立即生效)",
                fg=GREEN
            )
        self._status_job = self.after(2000, self._update_sai2_status)

    # 預覽時的來源長邊上限；最終寫入仍以全解析度原圖重新處理，品質不受影響
    PREVIEW_MAX_SIDE = 1024
    # 參數變動後的重算延遲：拖曳滑桿時每秒會觸發數十次，合併成停手後的一次重算
    UPDATE_DELAY_MS = 120

    def _set_source_image(self, img: Image.Image):
        self._raw_image = img
        work = img.convert('RGBA')   # convert 一律回傳新影像，下方 thumbnail 不會改到原圖
        work.thumbnail((self.PREVIEW_MAX_SIDE, self.PREVIEW_MAX_SIDE), Image.Resampling.LANCZOS)
        self._preview_src = work

    def _load_from_clipboard_silent(self):
        try:
            img = read_clipboard_safely()
            if img:
                self._set_source_image(img)
        except Exception:
            pass

    def _on_ctrl_v(self, event):
        # 在名稱 / 分類輸入框內 Ctrl+V 是貼上文字，交給輸入框自己處理，不去讀剪貼簿圖像
        if is_text_input_widget(event.widget):
            return
        self._on_click_clip()

    def _on_click_clip(self):
        img = read_clipboard_safely()
        if not img:
            messagebox.showwarning(
                "筆刷工坊",
                "剪貼簿中未偵測到有效圖像！\n\n"
                "• 若在 SAI2 中：請先選取圖樣並按下 Ctrl+C 複製\n"
                "• 若在檔案總管中：選取圖片檔案按下 Ctrl+C 即可貼上\n"
                "• 亦可直接在工作台視窗中按下 Ctrl+V 貼上",
                parent=self
            )
            return
        self._set_source_image(img)
        self.lbl_pad_tip.config(text=f"✅ 已成功從剪貼簿讀取圖像 ({img.size[0]}×{img.size[1]})！", fg=GREEN)
        self._update_processed_output()

    def _on_click_file(self):
        fpath = filedialog.askopenfilename(
            title="選擇圖片素材",
            filetypes=[("圖片檔案", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"), ("所有檔案", "*.*")],
            parent=self
        )
        if not fpath or not os.path.isfile(fpath):
            return
        try:
            img = Image.open(fpath)
            img.load()
            self._set_source_image(ImageOps.exif_transpose(img))
            base_name = os.path.splitext(os.path.basename(fpath))[0]
            self.var_brush_name.set(base_name)
            self._update_processed_output()
        except Exception as e:
            messagebox.showerror("載入失敗", f"無法開啟圖片檔案：{e}", parent=self)

    def _on_clear_pad(self):
        self.pad.clear()

    def _on_param_changed(self, *args):
        """會改變輸出圖像的參數：延遲合併後再重算"""
        if self._update_job is not None:
            self.after_cancel(self._update_job)
        self._update_job = self.after(self.UPDATE_DELAY_MS, self._update_processed_output)

    def _on_brush_param_changed(self, *args):
        """只影響試畫筆觸的參數：直接更新試畫區，不重算圖像"""
        self._sync_pad_params()

    def _flush_processed_output(self):
        """若還有尚未執行的延遲重算，立即執行（寫入前確保圖像對應目前參數）"""
        if self._update_job is not None:
            self._update_processed_output()

    @staticmethod
    def _default_source(is_texture_mode: bool) -> Image.Image:
        if is_texture_mode:
            base_im = Image.new('L', (256, 256), 180)
            d = ImageDraw.Draw(base_im)
            for _ in range(300):
                x, y = random.randint(0, 255), random.randint(0, 255)
                d.point((x, y), fill=random.randint(60, 220))
            return base_im
        default_im = Image.new('L', (512, 512), 0)
        d = ImageDraw.Draw(default_im)
        pts = []
        cx, cy, r_out, r_in = 256, 256, 200, 90
        for i in range(10):
            ang = i * math.pi / 5 - math.pi / 2
            r = r_out if i % 2 == 0 else r_in
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        d.polygon(pts, fill=255)
        return default_im

    def _process_image(self, src: Image.Image) -> Image.Image:
        """依目前模式與參數處理來源影像（預覽與最終寫入共用）"""
        mode = self.var_convert_mode.get()
        if self.var_main_mode.get() in ('brushtex', 'papertex'):
            return BrushImageProcessor.process_texture(
                src, seamless_mode=self.var_seamless_mode.get(),
                blend_ratio=self.var_blend_margin.get() / 100.0,
                contrast=self.var_contrast.get(), brightness=self.var_brightness.get(),
                invert=self.var_invert.get(), target_size=self.var_tex_res.get(),
                convert_mode=mode
            )
        return BrushImageProcessor.process(
            src, mode=mode, autocrop=self.var_autocrop.get(), target_size=512
        )

    def _final_output_image(self) -> Image.Image | None:
        """寫入用的圖像：有使用者來源時以全解析度原圖重新處理，否則沿用預覽結果"""
        self._flush_processed_output()
        is_texture = self.var_main_mode.get() in ('brushtex', 'papertex')
        preview = self._processed_texture if is_texture else self._processed_stamp
        if self._raw_image is None or preview is None:
            return preview
        return self._process_image(self._raw_image)

    def _update_processed_output(self):
        if self._update_job is not None:
            try:
                self.after_cancel(self._update_job)
            except Exception:
                pass
            self._update_job = None

        is_texture_mode = self.var_main_mode.get() in ('brushtex', 'papertex')
        src = self._preview_src if self._preview_src is not None else self._default_source(is_texture_mode)
        out = self._process_image(src)
        if is_texture_mode:
            self._processed_texture = out
        else:
            self._processed_stamp = out

        self._render_preview()
        self._sync_pad_params()

    def _sync_pad_params(self):
        self.pad.set_brush_params(
            stamp=self._processed_stamp,
            brush_type=self.var_main_mode.get(),
            size=self.var_size.get(),
            spacing=self.var_spacing.get(),
            scattering=self.var_scattering.get(),
            angle_ctl=self.var_angle_ctl.get(),
            angle=self.var_angle.get(),
            angle_jitter=self.var_angle_jitter.get(),
            size_jitter=self.var_size_jitter.get(),
            texture=self._processed_texture
        )

    def _render_preview(self):
        m = self.var_main_mode.get()
        is_texture_mode = m in ('brushtex', 'papertex')
        img_to_show = self._processed_texture if is_texture_mode else self._processed_stamp
        if not img_to_show:
            return

        cw = self.canvas_preview.winfo_width()
        ch = self.canvas_preview.winfo_height()
        if cw <= 1 or ch <= 1:
            cw, ch = 190, 190

        pw, ph = cw - 4, ch - 4
        is_tiled = (self.var_preview_view.get() == "tiled")

        if is_tiled or is_texture_mode:
            tile_w, tile_h = max(10, pw // 3), max(10, ph // 3)
            sub = img_to_show.resize((tile_w, tile_h), Image.Resampling.BILINEAR)
            tiled_img = Image.new('L', (pw, ph))
            for ty in range(3):
                for tx in range(3):
                    tiled_img.paste(sub, (tx * tile_w, ty * tile_h))
            prev_img = tiled_img.convert('RGBA')
        else:
            prev_img = Image.new('RGBA', (pw, ph), (25, 25, 25, 255))
            draw = ImageDraw.Draw(prev_img)
            grid_s = 10
            for y in range(0, ph, grid_s):
                for x in range(0, pw, grid_s):
                    if ((x // grid_s) + (y // grid_s)) % 2 == 0:
                        draw.rectangle([x, y, x + grid_s, y + grid_s], fill=(40, 40, 40, 255))

            thumb = img_to_show.resize((pw, ph), Image.Resampling.LANCZOS)
            fg_white = Image.new('RGBA', (pw, ph), (255, 255, 255, 255))
            prev_img.paste(fg_white, (0, 0), mask=thumb)

        self._preview_photo = ImageTk.PhotoImage(prev_img)
        self.canvas_preview.delete('all')
        self.canvas_preview.create_image(2, 2, image=self._preview_photo, anchor='nw')

    # 新群組（清單中沒有的名稱）一律回傳 ID 0，實際 ID 由 SAI2SettingsManager 在寫入當下
    # 依磁碟內容配發；不在這裡算 max+1，否則清單過期或連續排入佇列時會算出重複的 ID。
    def _get_target_group_info(self) -> tuple[int, str]:
        chosen_name = self.var_target_group.get().strip()
        for g in self._tool_groups:
            if g['name'] == chosen_name:
                return g['id'], chosen_name
        return 0, chosen_name

    def _get_asset_group_info(self) -> tuple[int, str]:
        chosen_name = self.var_asset_group.get().strip()
        if not chosen_name or chosen_name == '(未分類)':
            return 0, ''
        for g in self._asset_groups:
            if g['name'] == chosen_name:
                return g['id'], g['name']
        return 0, chosen_name

    def _reload_groups(self):
        """寫入後重新讀取分頁與分類清單，讓剛建立的群組出現在選單中"""
        self._tool_groups = SAI2SettingsManager.get_tool_groups(self._settings_dir)
        self.cbo_group.config(values=[g['name'] for g in self._tool_groups] or ["基本", "二值", "效果"])
        self._asset_groups = SAI2SettingsManager.get_asset_groups(self.var_main_mode.get(), self._settings_dir)
        self.cbo_asset_group.config(values=[g['name'] for g in self._asset_groups] or ["(未分類)"])

    def _gather_params(self) -> dict:
        ag_id, ag_name = self._get_asset_group_info()
        return {
            'size': self.var_size.get(),
            'spacing': self.var_spacing.get(),
            'scattering': self.var_scattering.get(),
            'angle_control': self.var_angle_ctl.get(),
            'angle': self.var_angle.get(),
            'angle_jitter': self.var_angle_jitter.get(),
            'size_jitter': self.var_size_jitter.get(),
            'pen_pressure': self.var_pen_pressure.get(),
            'asset_group_id': ag_id,
            'asset_group_name': ag_name,
        }

    # ── 寫入流程 ──────────────────────────────────────────────────────────

    def _validated_name(self) -> str | None:
        """讀取並驗證名稱（兩個寫入按鈕共用）；不合法時顯示錯誤並回傳 None"""
        name = self.var_brush_name.get().strip()
        err = validate_asset_name(name)
        if err:
            messagebox.showerror("名稱不合法", err, parent=self)
            return None
        return name

    def _asset_exists(self, name: str, mode: str) -> bool:
        if not self._settings_dir:
            return False
        if mode == 'scatter':
            folder = os.path.join(self._settings_dir, 'scatter')
        elif mode in ('brushtex', 'papertex'):
            folder = os.path.join(self._settings_dir, mode)
        else:
            folder = os.path.join(self._settings_dir, 'brushfom', 'brshape')
        return os.path.isfile(os.path.join(folder, f"{name}.bmp"))

    def _ask_write_strategy(self, what: str) -> str | None:
        """
        決定寫入方式：
          'direct' — SAI2 未運行，直接寫入
          'queue'  — SAI2 運行中，排入佇列，待 SAI2 關閉後才寫入（不碰任何 SAI2 設定檔）
          'force'  — SAI2 運行中，使用者選擇立刻強制寫入
          None     — 使用者取消
        """
        if not SAI2SettingsManager.is_sai2_running():
            return 'direct'
        choice = messagebox.askyesnocancel(
            "SAI2 正在運行中",
            f"PaintTool SAI2 正在運行中。\n\n"
            f"SAI2 關閉時會以記憶體中的內容覆寫自己的設定檔，若現在寫入{what}，"
            f"素材清單或工具面板的變更可能會被覆蓋而消失。\n\n"
            f"• 【是 (Yes)】：排入背景佇列，待您關閉 SAI2 後自動安全寫入 (推薦)\n"
            f"• 【否 (No)】：立刻強制寫入 (之後需重新啟動 SAI2)\n"
            f"• 【取消 (Cancel)】：不寫入任何檔案",
            parent=self,
        )
        if choice is True:
            return 'queue'
        if choice is False:
            return 'force'
        return None

    def _finish_success(self, name: str, close: bool):
        if not close:
            return  # 「僅儲存素材」維持原行為：不關閉視窗，方便連續製作
        if self.on_brush_created_callback:
            self.on_brush_created_callback(name)
        self.destroy()

    def _write_asset_now(self, name: str, mode: str, image: Image.Image,
                         params: dict) -> tuple[str, int]:
        """立即寫入素材 / 紋理並註冊，回傳 (BMP 路徑, 實際歸屬的素材分類 ID)"""
        if mode in ('brushtex', 'papertex'):
            return SAI2SettingsManager.write_texture(
                name, image, mode, self._settings_dir,
                asset_group_id=params.get('asset_group_id', 0),
                asset_group_name=params.get('asset_group_name', ''))
        bmp_p, _, gid = SAI2SettingsManager.write_material(
            name, image, mode, params, self._settings_dir)
        return bmp_p, gid

    def _run_write(self, create_tool_requested: bool):
        self._save_current_settings()
        name = self._validated_name()
        if name is None:
            return

        m = self.var_main_mode.get()
        try:
            image = self._final_output_image()
        except Exception as e:
            messagebox.showerror("錯誤", f"處理圖像時發生錯誤：{e}", parent=self)
            return
        if image is None:
            messagebox.showerror("錯誤", "尚未產生可儲存的圖像。", parent=self)
            return

        # 紙張材質沒有對應工具；筆刷紋理依勾選決定是否建立質感筆刷
        create_tool = create_tool_requested and m != 'papertex'
        if m == 'brushtex':
            create_tool = create_tool and self.var_create_texture_brush.get()
        tool_type = 'texture_brush' if m == 'brushtex' else m

        if self._asset_exists(name, m) and not messagebox.askyesno(
                "名稱已存在",
                f"素材「{name}」已存在，繼續將會覆蓋原檔案（原檔會先備份）。\n\n確定要覆蓋嗎？",
                icon='warning', parent=self):
            return

        params = self._gather_params()
        grp_id, grp_name = self._get_target_group_info()
        what = "素材與工具" if create_tool else "素材"

        strategy = self._ask_write_strategy(what)
        if strategy is None:
            return

        try:
            if strategy == 'queue':
                PendingBrushQueue.add_deploy_task(
                    name, m, image, params, grp_id, create_tool, tool_type, grp_name)
                messagebox.showinfo(
                    "已排入自動儲存佇列",
                    f"已將 [{name}] 的{what}加入佇列！\n"
                    f"SAI2 運行期間不會修改其任何設定檔；DrawCompanion 會在您關閉 SAI2 後自動寫入。\n"
                    f"下次開啟 SAI2 即可看見。",
                    parent=self)
                self._finish_success(name, close=create_tool_requested)
                return

            with sai2_write_session():
                bmp_p, asset_gid = self._write_asset_now(name, m, image, params)
                tid = None
                if create_tool:
                    # 工具的 fomgid / texgid 必須指向素材實際被放入的分類
                    tool_params = dict(params, asset_group_id=asset_gid)
                    tid = SAI2SettingsManager.write_tool(
                        name, tool_type, name, grp_id, tool_params, self._settings_dir,
                        target_group_name=grp_name)
        except Exception as e:
            messagebox.showerror("寫入失敗", f"發生錯誤：{e}", parent=self)
            return
        finally:
            # 無論成功或部分失敗，磁碟上的群組都可能已變動；「僅儲存素材」不關視窗，需重新整理選單
            try:
                self._reload_groups()
            except Exception:
                pass

        restart_hint = "\n\n⚠️ SAI2 目前仍在運行，請重新啟動 SAI2 後才會看見變更。" if strategy == 'force' else ""
        if m == 'papertex':
            messagebox.showinfo(
                "紙張材質建立成功 🎉",
                f"畫布/紙張材質 [{name}] 已成功加入 SAI2！\n\n"
                f"• 存放位置：{bmp_p}\n\n"
                f"於 PaintTool SAI2 的圖層效果「紙張材質」下拉選單中即可選用。{restart_hint}",
                parent=self)
        elif tid is None:
            type_desc = {"brushtex": "筆刷紋理 (brushtex)", "scatter": "散布筆刷素材",
                         "brush": "筆刷形狀素材"}.get(m, "素材")
            messagebox.showinfo(
                "儲存成功",
                f"{type_desc} [{name}] 已成功儲存並註冊至 SAI2 素材清單！\n\n"
                f"路徑：\n{bmp_p}{restart_hint}",
                parent=self)
        else:
            messagebox.showinfo(
                "建立成功 🎉",
                f"工具 [{name}] 已成功建立！\n\n"
                f"• 工具編號：{tid}\n"
                f"• 目標分頁：{self.var_target_group.get()}\n"
                f"• 工具類型：{tool_type}\n\n"
                f"啟動 PaintTool SAI2 即可在工具面板中看見此工具。{restart_hint}",
                parent=self)
        self._finish_success(name, close=create_tool_requested)

    def _on_click_save_material_only(self):
        self._run_write(create_tool_requested=False)

    def _on_click_deploy(self):
        self._run_write(create_tool_requested=True)
