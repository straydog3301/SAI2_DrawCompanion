# -*- coding: utf-8 -*-
"""
brush_assets.py - SAI2 筆刷素材、紋理、紙張材質與自訂工具的讀寫（不含 UI）

由 brush_studio.py 拆出：SAI2 settings 檔案的安全改寫（嚴格 UTF-8、備份、原子寫入）、
名稱驗證、素材 / 工具註冊、影像轉換（筆刷形狀、無縫紋理），以及 SAI2 運行中的待寫入佇列。
"""

from __future__ import annotations

import os
import glob
import time
import json
import math
import uuid
import shutil
import contextlib
import ctypes
import ctypes.wintypes

from PIL import Image, ImageOps, ImageChops, ImageStat

from core.paths import APP_DIR as _APP_DIR
from core.sai2_win import find_sai2_hwnd


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
