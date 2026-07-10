"""
tracker.py - SAI2 繪圖時間追蹤引擎

追蹤邏輯：
  - 開啟時間：SAI2 視窗有開啟此檔案時，持續累計
  - 動筆時間：偵測到滑鼠按鍵按下（含繪圖板筆壓）且 SAI2 在前景時，
              開始計算；無操作超過 idle_timeout 秒後停止計算
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from datetime import datetime

import win32api
import win32gui
from i18n import _tr


# ─── 工具函式 ─────────────────────────────────────────────────────────────

def is_sai2_title(title: str) -> bool:
    t = title.lower()
    return 'painttool sai' in t


def extract_filename(title: str) -> str | None:
    """從 SAI2 視窗標題提取檔案名稱，無檔案時回傳 None。

    支援的 SAI2 標題格式（版本/語言不同可能有差異）：
      artwork.sai2 - PaintTool SAI Ver.2 (64bit)
      PaintTool SAI Ver.2 (64bit) Preview.2023.07.11 - 新增版面1 (*)
      * artwork.sai2 - PaintTool SAI Ver.2
    """
    t = title.strip()
    
    # 判斷程式名稱是否在左側
    t_lower = t.lower()
    is_app_first = t_lower.startswith('painttool') or t_lower.startswith('sai2')
    
    separators = (' - ', ' － ', '－', ' -', '- ')
    idx = -1
    sep_len = 0
    
    if is_app_first:
        # 從左側尋找第一個分隔符號
        for sep in separators:
            curr_idx = t.find(sep)
            if curr_idx != -1 and (idx == -1 or curr_idx < idx):
                idx = curr_idx
                sep_len = len(sep)
    else:
        # 從右側尋找最後一個分隔符號
        for sep in separators:
            curr_idx = t.rfind(sep)
            if curr_idx > idx:
                idx = curr_idx
                sep_len = len(sep)

    if idx <= 0:
        return None   # 沒有找到分隔符號，代表沒有開啟檔案

    part1 = t[:idx].strip()
    part2 = t[idx + sep_len:].strip()

    if is_app_first:
        fname = part2
    else:
        fname = part1

    # 清理檔名開頭與結尾的修改標籤（例如 *, (*), (已修改) 等）
    fname = fname.strip()
    fname = fname.lstrip('*＊ ').strip()

    if fname.endswith('(*)'):
        fname = fname[:-3].strip()
    elif fname.endswith('(* )'):
        fname = fname[:-4].strip()
    elif fname.endswith(' (已修改)'):
        fname = fname[:-5].strip()
    elif fname.endswith(' (modified)'):
        fname = fname[:-11].strip()
    elif fname.endswith(' (変更あり)'):
        fname = fname[:-7].strip()

    fname = fname.strip('*＊ ')

    # 最終防錯：檔名不能是空字串，也不能只是程式名
    if not fname or 'painttool' in fname.lower():
        return None

    # 遇到斜線或反斜線用 _ 取代，且移除磁碟機代號 (如 D:)
    if len(fname) > 1 and fname[1] == ':':
        fname = fname[2:]
    fname = fname.lstrip('/\\')
    fname = fname.replace('/', '_').replace('\\', '_')

    return fname


def is_saved_filename(name: str | None) -> bool:
    """判斷檔名是否為已儲存的檔案（有副檔名），若是新建未存檔的畫布則回傳 False"""
    if not name:
        return False
    lower_name = name.lower()
    extensions = ('.sai2', '.sai', '.psd', '.psb', '.png', '.jpg', '.jpeg', '.tga', '.bmp')
    return lower_name.endswith(extensions)


def fmt_seconds(secs: float) -> str:
    """將秒數格式化為 h:mm:ss 或 mm:ss"""
    s = max(0, int(secs))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f'{h}:{m:02d}:{sec:02d}'
    return f'{m:02d}:{sec:02d}'


def _new_record() -> dict:
    return {
        'open_seconds': 0.0,
        'draw_seconds': 0.0,
        'sessions': 0,
        'last_seen': '',
    }


def _scan_sai2() -> tuple[str | None, bool, str, bool]:
    """
    掃描所有可見視窗，判定 PaintTool SAI 是否正在執行，以及是否在前景。
    
    Returns:
        (detected_filename, is_foreground, raw_title, is_running)
    """
    import win32process
    import os
    try:
        my_pid = os.getpid()
    except Exception:
        my_pid = -1

    try:
        fg_hwnd = win32gui.GetForegroundWindow()
        if fg_hwnd:
            _, fg_pid = win32process.GetWindowThreadProcessId(fg_hwnd)
        else:
            fg_pid = -1
    except Exception:
        fg_pid = -1

    sai_windows = []
    
    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == my_pid:
                return True  # 排除本計時器本身的進程視窗
            title = win32gui.GetWindowText(hwnd)
            if title and 'painttool sai' in title.lower():
                sai_windows.append((hwnd, title, pid))
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass

    if not sai_windows:
        # PaintTool SAI 完全沒有執行
        return None, False, "", False

    # PaintTool SAI 正在執行中！
    is_running = True
    
    # 檢查前景進程是否屬於 PaintTool SAI 的任一進程
    is_foreground = False
    if fg_pid != -1:
        is_foreground = any(pid == fg_pid for _, _, pid in sai_windows)

    # 從所有 PaintTool SAI 視窗中找第一個能解析出檔名的
    filename = None
    raw_title = ""
    for hwnd, title, pid in sai_windows:
        f = extract_filename(title)
        if f:
            filename = f
            raw_title = title
            break

    # 如果沒有找到有檔名的視窗，就拿第一個視窗的標題作為 raw_title
    if not raw_title and sai_windows:
        raw_title = sai_windows[0][1]

    return filename, is_foreground, raw_title, is_running


def _mouse_pressed() -> bool:
    """偵測是否有滑鼠鍵（左/右/中）或繪圖板筆壓（映射到左鍵）按下。"""
    try:
        # GetAsyncKeyState < 0 代表當前鍵被按下
        return any(win32api.GetAsyncKeyState(vk) < 0 for vk in (0x01, 0x02, 0x04))
    except Exception:
        return False


# ─── 追蹤引擎 ─────────────────────────────────────────────────────────────

class DrawTracker:
    """
    背景執行緒追蹤 SAI2 繪圖時間。

    取得目前狀態：呼叫 get_state()，每秒由 UI 輪詢即可。
    """

    POLL     = 0.015  # 輪詢間隔（秒）：高頻輪詢以保證動筆時間的精確度 (與錄影引擎對齊)
    AUTOSAVE = 60.0   # 自動存檔間隔（秒）

    def __init__(self, data_path: str, idle_timeout: float = 10.0):
        self.data_path    = data_path
        self.idle_timeout = idle_timeout

        self._lock    = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

        # 視窗掃描快取
        self._last_win_scan = 0.0
        self._cached_fg_hwnd = None
        self._cached_filename = None
        self._cached_is_foreground = False
        self._cached_raw_title = ""
        self._cached_is_running = False

        # 持久化資料
        self._persist: dict = self._load_json()
        self.locked_file: str | None = None

        # 目前工作階段狀態（由 _loop 修改，_lock 保護讀取）
        self._cur_file:               str | None = None
        self._sai2_active:            bool  = False
        self._sai2_running:           bool  = False
        self._last_raw_title:         str   = ""

        # 基礎時間（讀取自資料庫，不隨目前工作階段變動）
        self._base_open:              float = 0.0
        self._base_draw:              float = 0.0

        # 本次工作階段累計時間
        self._session_open_accum:     float = 0.0   # 累計已確認的開啟秒數
        self._session_open_seg_start: float = 0.0   # 當前開啟區段開始，0 = 處於背景
        self._session_draw_accum:     float = 0.0   # 累計已確認的動筆秒數
        self._session_draw_seg_start: float = 0.0   # 當前動筆區段開始，0 = 不在動筆
        self._session_last_mouse:     float = 0.0   # 最後一次滑鼠按下時間
        self._session_draw_flushed:   float = 0.0   # 本次工作階段已寫入每日統計的秒數

        # UI 讀取的快照（由 _loop 更新）
        self._state: dict = {
            'sai2_active':  False,
            'sai2_running':  False,
            'current_file': None,
            'session_open': 0.0,
            'session_draw': 0.0,
            'files':        {},
            'raw_title':    '',
        }

    # ── 持久化 ────────────────────────────────────────────────────────────

    def _load_json(self) -> dict:
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                    # 相容舊格式
                    if 'files' not in d:
                        d = {'files': {}}
                    if 'daily_history' not in d:
                        d['daily_history'] = {}
                    if 'aliases' not in d:
                        d['aliases'] = {}
                    # 啟動時清理所有未存檔圖檔的暫存紀錄，避免留在歷史清單中
                    cleaned_files = {}
                    for fname, rec in d['files'].items():
                        if is_saved_filename(fname):
                            cleaned_files[fname] = rec
                    d['files'] = cleaned_files
                    # 清理失效的別名
                    valid_aliases = {}
                    for k, v in d['aliases'].items():
                        if v in cleaned_files:
                            valid_aliases[k] = v
                    d['aliases'] = valid_aliases
                    return d
            except Exception:
                pass
        return {'files': {}, 'daily_history': {}, 'aliases': {}}

    def _save_json(self, data: dict):
        try:
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def save(self):
        """將目前工作階段合併後存檔（可從任意執行緒呼叫）。"""
        with self._lock:
            self._flush_session()
            data_copy = json.loads(json.dumps(self._persist))
        self._save_json(data_copy)

    def _flush_session(self):
        """把目前工作階段累計至 _persist（需在 lock 內呼叫）。"""
        now = time.monotonic()
        f   = self._cur_file
        if not f:
            return

        session_open = self._current_session_open(now)
        session_draw = self._current_session_draw(now)

        if f not in self._persist['files']:
            self._persist['files'][f] = _new_record()
        rec = self._persist['files'][f]
        rec['open_seconds'] = self._base_open + session_open
        rec['draw_seconds'] = self._base_draw + session_draw
        rec['last_seen']     = datetime.now().isoformat(timespec='seconds')

        # 更新每日統計
        delta_draw = session_draw - self._session_draw_flushed
        if delta_draw > 0.0:
            today = datetime.now().strftime('%Y-%m-%d')
            if 'daily_history' not in self._persist:
                self._persist['daily_history'] = {}
            self._persist['daily_history'][today] = self._persist['daily_history'].get(today, 0.0) + delta_draw
            self._session_draw_flushed = session_draw

    def _current_session_open(self, now: float) -> float:
        """計算當前工作階段的開啟時間（僅在前景時累計）。"""
        return self._session_open_accum

    def _current_session_draw(self, now: float) -> float:
        """計算當前工作階段的動筆時間（包含目前仍在進行的動筆區段）。"""
        return self._session_draw_accum

    # ── 執行緒 ────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.save()

    def _loop(self):
        last_autosave = time.monotonic()
        last_cursor_pos = None
        last_loop_time = time.monotonic()
        last_active_time = time.monotonic()

        while self._running:
            try:
                now = time.monotonic()
                dt = now - last_loop_time
                last_loop_time = now

                # ── 掃描視窗 (快取優化以避免高頻率 EnumWindows 導致 CPU 暴增) ──
                import win32gui
                fg_hwnd = win32gui.GetForegroundWindow()
                if now - self._last_win_scan > 1.0 or fg_hwnd != self._cached_fg_hwnd:
                    self._last_win_scan = now
                    self._cached_fg_hwnd = fg_hwnd
                    filename, sai_foreground, raw_title, sai_running = _scan_sai2()
                    self._cached_filename = filename
                    self._cached_is_foreground = sai_foreground
                    self._cached_raw_title = raw_title
                    self._cached_is_running = sai_running
                else:
                    filename = self._cached_filename
                    sai_foreground = self._cached_is_foreground
                    raw_title = self._cached_raw_title
                    sai_running = self._cached_is_running

                # ── 解析別名與鎖定處理 ──
                raw_detected_file = filename
                
                # 1. 優先透過 aliases 將別名解析為對應的主圖檔
                if filename and 'aliases' in self._persist:
                    if filename in self._persist['aliases']:
                        filename = self._persist['aliases'][filename]
                
                # 2. 如果設定了鎖定，強制將 filename 覆寫為鎖定圖檔
                if self.locked_file is not None:
                    # 只有在 SAI 仍在執行，且偵測到的 filename 不是 None 時才套用鎖定
                    # （若 filename 為 None，代表所有圖檔皆已關閉，此時解鎖）
                    if sai_running and filename is not None:
                        filename = self.locked_file
                    else:
                        self.locked_file = None

                with self._lock:
                    self._last_raw_title = raw_title
                    self._sai2_active = sai_foreground
                    self._sai2_running = sai_running
                    self._raw_cur_file = raw_detected_file

                    if not sai_running:
                        # PaintTool SAI 沒開 → 切換為 None（結束當前 session）
                        if self._cur_file is not None:
                            self._switch_file(None, now)
                        self.locked_file = None
                    else:
                        # PaintTool SAI 有開
                        if filename is None:
                            # 沒有偵測到開啟的檔案（可能是關閉了所有畫布）
                            if self._cur_file is not None:
                                self._switch_file(None, now)
                        else:
                            # 有偵測到檔案
                            if filename != self._cur_file:
                                # 切換檔案（開啟新工作階段）
                                self._switch_file(filename, now)
                                last_active_time = now
                            
                            # 在同一個檔案下：
                            # ── 前景開啟計時 ─────────────────────────────
                            if sai_foreground:
                                self._session_open_accum += dt

                                # ── 前景動筆偵測 ─────────────────────────────
                                try:
                                    curr_pos = win32gui.GetCursorPos()
                                except Exception:
                                    curr_pos = None

                                cursor_moved = False
                                if curr_pos and last_cursor_pos:
                                    if curr_pos != last_cursor_pos:
                                        cursor_moved = True
                                if curr_pos:
                                    last_cursor_pos = curr_pos

                                # 偵測是否正在動筆（與錄影判定方式完全一致，包含閒置緩衝時間）
                                if self.idle_timeout <= 0.0:
                                    # 僅在滑鼠/繪圖板點擊按住時才算作動筆，不使用緩衝，無筆壓/無按壓時不累計
                                    is_active = _mouse_pressed()
                                    is_drawing = is_active
                                else:
                                    is_active = _mouse_pressed() or cursor_moved
                                    if is_active:
                                        last_active_time = now
                                    is_drawing = (now - last_active_time) <= self.idle_timeout

                                if is_drawing:
                                    self._session_draw_accum += dt

                    # ── 更新 UI 快照 ─────────────────────────────────────
                    self._update_state(now)

                # ── 自動存檔 ─────────────────────────────────────────────
                if now - last_autosave >= self.AUTOSAVE:
                    self.save()
                    last_autosave = time.monotonic()

            except Exception as e:
                # 避免背景執行緒因為任何未預期例外而中斷
                pass

            time.sleep(self.POLL)

    def _switch_file(self, new_file: str | None, now: float):
        """處理檔案切換（在 lock 內呼叫）。"""
        old = self._cur_file

        # 1. 估算舊檔案在此工作階段的最終時間，並寫入/更新舊檔案的紀錄
        if old:
            session_open = self._current_session_open(now)
            session_draw = self._current_session_draw(now)

            total_old_open = self._base_open + session_open
            total_old_draw = self._base_draw + session_draw

            is_rename = (not is_saved_filename(old) and is_saved_filename(new_file))

            if is_rename:
                # 重新命名：把舊的未存檔紀錄從 persist 中移除，準備合併至新檔
                old_rec = self._persist['files'].pop(old, None)
                accum_open = total_old_open
                accum_draw = total_old_draw
                accum_sessions = old_rec.get('sessions', 1) if old_rec else 1

                # 讀取新檔案的既有歷史紀錄
                if new_file in self._persist['files']:
                    dest_rec = self._persist['files'][new_file]
                    db_new_open = dest_rec['open_seconds']
                    db_new_draw = dest_rec['draw_seconds']
                    db_new_sessions = dest_rec['sessions']
                else:
                    db_new_open = 0.0
                    db_new_draw = 0.0
                    db_new_sessions = 0

                new_db_open = db_new_open + accum_open
                new_db_draw = db_new_draw + accum_draw
                new_db_sessions = db_new_sessions + 1  # 合併算一個新工作階段

                if new_file not in self._persist['files']:
                    self._persist['files'][new_file] = _new_record()
                rec = self._persist['files'][new_file]
                rec['open_seconds'] = new_db_open
                rec['draw_seconds'] = new_db_draw
                rec['sessions'] = new_db_sessions
                rec['last_seen'] = datetime.now().isoformat(timespec='seconds')

                # 設定新的 base，使得後續在同一個工作階段中，
                # base + session 依然等於新合併總時間 + 重新命名後的增量時間
                self._base_open = new_db_open - session_open
                self._base_draw = new_db_draw - session_draw

                # 因為是重新命名，我們不需要重置工作階段變數，
                # 這樣 UI 上的本次工作階段時間就不會跳變/歸零！
            else:
                # 一般切換：將舊檔案存回 persist
                if old not in self._persist['files']:
                    self._persist['files'][old] = _new_record()
                rec = self._persist['files'][old]
                rec['open_seconds'] = total_old_open
                rec['draw_seconds'] = total_old_draw
                rec['last_seen'] = datetime.now().isoformat(timespec='seconds')

        # 2. 切換至新檔案
        self._cur_file = new_file

        is_rename = (old and not is_saved_filename(old) and is_saved_filename(new_file))

        if not is_rename:
            # 如果不是重新命名，這是一個全新的檔案工作階段
            if new_file:
                # 讀取新檔案的既有歷史紀錄作為 base
                if new_file in self._persist['files']:
                    rec = self._persist['files'][new_file]
                    self._base_open = rec['open_seconds']
                    self._base_draw = rec['draw_seconds']
                    rec['sessions'] += 1  # 進入新工作階段，次數加 1
                    rec['last_seen'] = datetime.now().isoformat(timespec='seconds')
                else:
                    self._persist['files'][new_file] = _new_record()
                    rec = self._persist['files'][new_file]
                    rec['sessions'] = 1
                    rec['last_seen'] = datetime.now().isoformat(timespec='seconds')
                    self._base_open = 0.0
                    self._base_draw = 0.0
            else:
                self._base_open = 0.0
                self._base_draw = 0.0

            self._session_open_accum     = 0.0
            self._session_open_seg_start = now if (new_file and self._sai2_active) else 0.0
            self._session_draw_accum     = 0.0
            self._session_draw_seg_start = 0.0
            self._session_last_mouse     = 0.0
            self._session_draw_flushed   = 0.0

    def _update_state(self, now: float):
        """更新 UI 快照（在 lock 內呼叫）。"""
        f = self._cur_file
        if f:
            session_open_s = self._current_session_open(now)
            session_draw_s = self._current_session_draw(now)
            session_draw_s = min(max(0.0, session_draw_s), session_open_s)
        else:
            session_open_s = session_draw_s = 0.0

        # 合併持久化 + 本次工作階段
        all_files: dict[str, dict] = {}
        for fname, rec in self._persist['files'].items():
            all_files[fname] = {
                'open_seconds': rec['open_seconds'],
                'draw_seconds': rec['draw_seconds'],
                'sessions':     rec['sessions'],
                'last_seen':    rec['last_seen'],
            }
        # 如果當前有開啟檔案，且尚未寫入 persist，或者 persist 中的值落後，我們提供最新的總值給 UI 顯示
        if f:
            if f not in all_files:
                all_files[f] = _new_record()
            all_files[f]['open_seconds'] = self._base_open + session_open_s
            all_files[f]['draw_seconds'] = self._base_draw + session_draw_s

        self._state = {
            'sai2_active':  self._sai2_active,
            'sai2_running':  self._sai2_running,
            'current_file': f,
            'raw_current_file': getattr(self, '_raw_cur_file', None),
            'session_open': session_open_s,
            'session_draw': session_draw_s,
            'files':        all_files,
            'raw_title':    self._last_raw_title,
        }

    def get_state(self) -> dict:
        """取得目前快照（供 UI 輪詢）。"""
        with self._lock:
            return dict(self._state)

    # ── 匯出 / 重置 ───────────────────────────────────────────────────────

    def export_csv(self, csv_path: str):
        """將目前資料匯出為 CSV。"""
        state = self.get_state()
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow([
                _tr('tracker.csv.header.file'),
                _tr('tracker.csv.header.open_seconds'),
                _tr('tracker.csv.header.draw_seconds'),
                _tr('tracker.csv.header.open_time'),
                _tr('tracker.csv.header.draw_time'),
                _tr('tracker.csv.header.efficiency'),
                _tr('tracker.csv.header.sessions'),
                _tr('tracker.csv.header.last_use')
            ])
            for fname, rec in sorted(state['files'].items()):
                op  = rec['open_seconds']
                dr  = rec['draw_seconds']
                eff = int(dr / op * 100) if op > 0 else 0
                w.writerow([
                    fname,
                    round(op, 1), round(dr, 1),
                    fmt_seconds(op), fmt_seconds(dr),
                    eff,
                    rec.get('sessions', 0),
                    rec.get('last_seen', ''),
                ])

    def delete_file(self, filename: str):
        """刪除特定檔案的記錄。"""
        with self._lock:
            self._persist['files'].pop(filename, None)
            # 清理指向它的別名
            if 'aliases' in self._persist:
                targets_to_remove = [k for k, v in self._persist['aliases'].items() if v == filename]
                for k in targets_to_remove:
                    self._persist['aliases'].pop(k, None)
            # 若是目前追蹤中的檔案，也重置工作階段
            if self._cur_file == filename:
                self._cur_file               = None
                self._session_open_accum     = 0.0
                self._session_open_seg_start = 0.0
                self._session_draw_accum     = 0.0
                self._session_draw_seg_start = 0.0
                self._session_last_mouse     = 0.0
                self._base_open              = 0.0
                self._base_draw              = 0.0
            if self.locked_file == filename:
                self.locked_file = None
        self.save()

    def reset_all(self):
        """清空全部記錄。"""
        with self._lock:
            self._persist = {'files': {}, 'aliases': {}}
            self._cur_file               = None
            self._session_open_accum     = 0.0
            self._session_open_seg_start = 0.0
            self._session_draw_accum     = 0.0
            self._session_draw_seg_start = 0.0
            self._session_last_mouse     = 0.0
            self._base_open              = 0.0
            self._base_draw              = 0.0
            self.locked_file             = None
        self.save()

    def add_alias(self, alias_name: str, target_name: str):
        """新增別名，並合併現有的計時紀錄。"""
        with self._lock:
            if 'aliases' not in self._persist:
                self._persist['aliases'] = {}
            self._persist['aliases'][alias_name] = target_name
            
            # 合併別名的計時紀錄至主圖檔
            if alias_name in self._persist['files']:
                alias_rec = self._persist['files'].pop(alias_name)
                if target_name not in self._persist['files']:
                    self._persist['files'][target_name] = _new_record()
                target_rec = self._persist['files'][target_name]
                
                target_rec['open_seconds'] += alias_rec.get('open_seconds', 0.0)
                target_rec['draw_seconds'] += alias_rec.get('draw_seconds', 0.0)
                target_rec['sessions'] += alias_rec.get('sessions', 0)
                
                t_seen = target_rec.get('last_seen', '')
                a_seen = alias_rec.get('last_seen', '')
                if a_seen and t_seen:
                    target_rec['last_seen'] = max(t_seen, a_seen)
                elif a_seen:
                    target_rec['last_seen'] = a_seen

            # 若當前正在追蹤的檔案是別名，無縫切換主圖檔的 session
            if self._cur_file == alias_name:
                self._cur_file = target_name
                if target_name in self._persist['files']:
                    self._base_open = self._persist['files'][target_name]['open_seconds'] - self._session_open_accum
                    self._base_draw = self._persist['files'][target_name]['draw_seconds'] - self._session_draw_accum
                else:
                    self._base_open = 0.0
                    self._base_draw = 0.0

            # 若處於鎖定狀態且被鎖定的是別名，將鎖定圖檔更新為主圖檔
            if self.locked_file == alias_name:
                self.locked_file = target_name
                
        self.save()

    def remove_alias(self, alias_name: str):
        """移除別名。"""
        with self._lock:
            if 'aliases' in self._persist:
                self._persist['aliases'].pop(alias_name, None)
        self.save()
