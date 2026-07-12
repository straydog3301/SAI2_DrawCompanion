"""
timelapse.py - PaintTool SAI 縮時錄影背景擷取與影片合成引擎
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
import win32api
import win32gui
import win32process
import ctypes
from ctypes import wintypes
from PIL import Image
import queue
from i18n import _tr


def file_key_to_subdir(key: str) -> str:
    """
    將儲存的圖檔 key 轉換為影片子目錄名稱。
    格式：「本機磁碟 (D:) _ 2026 _ test_2.sai2」
    結果：　2026_test_2（去除磁碟標籤段、副檔名，段間以 _ 連接）
    """
    if ' _ ' in key:
        parts = key.split(' _ ')
        import re
        # 最前段若包含磁碟代號（如 (D:)）則跳過
        if parts and re.search(r'\([A-Za-z]:\)', parts[0]):
            parts = parts[1:]
        if parts:
            # 去除最後一段的副檔名
            last = parts[-1]
            last_no_ext, _ = os.path.splitext(last)
            parts = parts[:-1] + [last_no_ext]
            subdir = '_'.join(parts)
        else:
            subdir = os.path.splitext(key)[0]
    else:
        subdir = os.path.splitext(key)[0]

    # 清理非法路徑字元
    for c in r'<>:"/\|?* ':
        subdir = subdir.replace(c, '_')
    return subdir or 'unknown'

# DPI 感知設定，確保在高 DPI 螢幕上取得正確視窗解析度
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# GDI API 宣告
gdi32 = ctypes.windll.gdi32
user32 = ctypes.windll.user32

user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

try:
    user32.IsHungAppWindow.argtypes = [wintypes.HWND]
    user32.IsHungAppWindow.restype = wintypes.BOOL
except Exception:
    pass

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC

gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP

gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ

gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.BitBlt.restype = wintypes.BOOL

gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL

gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL

user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

try:
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
except Exception:
    pass

try:
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
except Exception:
    pass


# 擷取用 GDI 資源快取 (點陣圖 + 像素緩衝區)，避免每一影格重新配置
_capture_cache_lock = threading.Lock()
_capture_cache = {'size': None, 'bitmap': None, 'buffer': None}


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', wintypes.LONG),
        ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD)
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ('bmiHeader', BITMAPINFOHEADER),
        ('bmiColors', wintypes.DWORD * 3)
    ]

def capture_window_gdi(hwnd, prefer_printwindow: bool = False) -> Image.Image | None:
    """
    使用 Windows GDI / PrintWindow API 抓取指定視窗。
    只抓取該視窗的內容，即使被遮擋也能正常錄製，且不錄製旁邊的桌面。

    prefer_printwindow: 優先使用 PrintWindow (PW_RENDERFULLCONTENT)。
    對於移到螢幕外的視窗 (canvas_float 隱形錄製模式)，BitBlt 從視窗 DC
    複製可能得到黑畫面/舊內容，PrintWindow 則會要求 DWM 重新渲染完整內容。
    """
    if hwnd == 0:
        hwnd = user32.GetDesktopWindow()

    if not user32.IsWindow(hwnd):
        return None

    # 確保視窗沒有最小化且是可見的
    if user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
        return None

    # 額外安全檢查：如果視窗處於停用狀態（例如彈出了模態對話框），
    # 為避免 PrintWindow 導致的執行緒阻塞死鎖，我們直接跳過擷取。
    if hwnd != user32.GetDesktopWindow():
        try:
            if not win32gui.IsWindowEnabled(hwnd):
                return None
        except Exception:
            pass

    # 防止目標視窗無回應（當機）時導致 PrintWindow 永久阻塞錄影執行緒
    try:
        if hasattr(user32, 'IsHungAppWindow') and user32.IsHungAppWindow(hwnd):
            return None
    except Exception:
        pass

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None

    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None

    hwndDC = None
    saveDC = None
    hOldSel = None
    # 快取的 GDI 點陣圖與像素緩衝區在鎖內使用
    _capture_cache_lock.acquire()
    try:
        hwndDC = user32.GetWindowDC(hwnd)
        if not hwndDC:
            return None
        saveDC = gdi32.CreateCompatibleDC(hwndDC)
        if not saveDC:
            return None

        # 重複使用快取的點陣圖與緩衝區 (高倍率 1x 錄製時每秒可省下數百 MB 的配置量)
        if _capture_cache['size'] != (w, h):
            if _capture_cache['bitmap']:
                try:
                    gdi32.DeleteObject(_capture_cache['bitmap'])
                except Exception:
                    pass
            _capture_cache['bitmap'] = gdi32.CreateCompatibleBitmap(hwndDC, w, h)
            _capture_cache['buffer'] = ctypes.create_string_buffer(w * h * 4)
            _capture_cache['size'] = (w, h) if _capture_cache['bitmap'] else None
        saveBitMap = _capture_cache['bitmap']
        buffer = _capture_cache['buffer']
        if not saveBitMap:
            return None
        hOldSel = gdi32.SelectObject(saveDC, saveBitMap)

        copied = False

        if prefer_printwindow and hwnd != user32.GetDesktopWindow():
            # 螢幕外視窗：直接要求 DWM 渲染完整內容
            try:
                if user32.PrintWindow(hwnd, saveDC, 2):  # PW_RENDERFULLCONTENT
                    copied = True
            except Exception:
                pass

        # 在前景作畫時，為了絕對避免 PrintWindow 同步發送訊息導致的繪圖卡頓，
        # 我們優先使用超高速的 BitBlt (直接從 DWM 重導向表面複製，耗時 < 1ms且不卡主執行緒)
        if not copied:
            try:
                if gdi32.BitBlt(saveDC, 0, 0, w, h, hwndDC, 0, 0, 0x00CC0020): # SRCCOPY
                    copied = True
            except Exception:
                pass

        # 如果 BitBlt 失敗，才使用 PrintWindow 作為後備
        if not copied and hwnd != user32.GetDesktopWindow():
            try:
                # 優先使用 PrintWindow 旗標 2 (PW_RENDERFULLCONTENT)，能完美避開遮擋物
                if user32.PrintWindow(hwnd, saveDC, 2):
                    copied = True
                elif user32.PrintWindow(hwnd, saveDC, 0):
                    copied = True
            except Exception:
                pass

        bmpinfo = BITMAPINFO()
        bmpinfo.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmpinfo.bmiHeader.biWidth = w
        bmpinfo.bmiHeader.biHeight = -h  # 負值代表 Top-Down DIB
        bmpinfo.bmiHeader.biPlanes = 1
        bmpinfo.bmiHeader.biBitCount = 32
        bmpinfo.bmiHeader.biCompression = 0 # BI_RGB

        gdi32.GetDIBits(saveDC, saveBitMap, 0, h, buffer, ctypes.byref(bmpinfo), 0)

        # 直接以 BGRX 原始模式解碼為 RGB：一次複製完成 (舊寫法 RGBA→convert('RGB')
        # 需要兩次全幅複製)。frombuffer 對 RGB/BGRX 組合會立即解碼複製，
        # 與快取 buffer 分離，因此離開鎖後 buffer 被覆寫也不影響已回傳的影像。
        return Image.frombuffer('RGB', (w, h), buffer, 'raw', 'BGRX', 0, 1)
    except Exception:
        return None
    finally:
        if saveDC and hOldSel:
            gdi32.SelectObject(saveDC, hOldSel)
        if saveDC:
            gdi32.DeleteDC(saveDC)
        if hwndDC:
            user32.ReleaseDC(hwnd, hwndDC)
        _capture_cache_lock.release()


def make_even_dimensions(img: Image.Image) -> Image.Image:
    """
    確保圖片的寬與高都是偶數。
    因為 FFmpeg yuv420p 格式轉碼嚴格要求影像寬高皆須能被 2 整除。
    """
    w, h = img.size
    if w % 2 == 0 and h % 2 == 0:
        return img
    new_w = w - (w % 2)
    new_h = h - (h % 2)
    return img.crop((0, 0, new_w, new_h))


def find_ffmpeg() -> bool:
    """檢查系統 PATH 中是否存在 ffmpeg 執行檔"""
    return shutil.which('ffmpeg') is not None


def _mouse_pressed() -> bool:
    """偵測滑鼠鍵（左/右/中）或繪圖板筆壓（映射到左鍵）是否按下"""
    try:
        return any(win32api.GetAsyncKeyState(vk) < 0 for vk in (0x01, 0x02, 0x04))
    except Exception:
        return False


def _press_keys(vks: list[int]):
    """依序按下再反序放開一組虛擬鍵 (用於對 SAI2 送出快捷鍵)"""
    for vk in vks:
        win32api.keybd_event(vk, 0, 0, 0)
        time.sleep(0.02)
    time.sleep(0.05)
    for vk in reversed(vks):
        win32api.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
        time.sleep(0.02)


def _enum_pid_toplevel_windows(sai_pid: int) -> dict[int, tuple[str, str, int]]:
    """列舉屬於 SAI 進程的所有可見頂層視窗 {hwnd: (class_name, title, area)}"""
    result: dict[int, tuple[str, str, int]] = {}
    def _cb(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == sai_pid and win32gui.IsWindowVisible(hwnd):
                cls = win32gui.GetClassName(hwnd)
                title = win32gui.GetWindowText(hwnd)
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                result[hwnd] = (cls, title, max(0, r - l) * max(0, b - t))
        except Exception:
            pass
        return True
    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return result


def scan_sai_windows(my_pid: int) -> tuple[tuple[int, str] | None, list[tuple[int, str]]]:
    """
    列舉所有頂層視窗，找出 PaintTool SAI 主視窗與其附屬的浮動視窗。
    完全不使用 psutil 進程掃描，效率提升數千倍，極低 CPU 消耗。
    
    Returns:
        (main_window_tuple, list_of_floating_canvas_windows)
        格式：( (hwnd, title) , [ (hwnd1, title1), (hwnd2, title2), ... ] )
    """
    all_wins = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == my_pid:
                return True
            title = win32gui.GetWindowText(hwnd)
            if title:
                all_wins.append((hwnd, title, pid))
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass

    # 尋找主視窗與其 PID。
    # 主視窗 = 無 owner 的 SAI 視窗；浮動畫布/參考圖視窗都是 owned window。
    # EnumWindows 依 Z 順序列舉，若浮動視窗在最上層，舊邏輯 (取第一個) 會把
    # 浮動視窗誤認為主視窗，導致畫布偵測與錄影目標全部跟著錯。
    GW_OWNER = 4
    main_win = None
    target_pid = -1
    fallback_win = None
    fallback_pid = -1
    for hwnd, title, pid in all_wins:
        if 'painttool sai' in title.lower():
            if fallback_win is None:
                fallback_win = (hwnd, title)
                fallback_pid = pid
            try:
                owner = win32gui.GetWindow(hwnd, GW_OWNER)
            except Exception:
                owner = 0
            if not owner:
                main_win = (hwnd, title)
                target_pid = pid
                break
    if main_win is None and fallback_win is not None:
        main_win = fallback_win
        target_pid = fallback_pid

    # 尋找浮動視窗 (相同 PID，但非主視窗)
    floating_windows = []
    if target_pid != -1:
        for hwnd, title, pid in all_wins:
            if pid == target_pid and hwnd != main_win[0]:
                floating_windows.append((hwnd, title))

    return main_win, floating_windows


def find_canvas_hwnd(my_pid: int, main_hwnd: int | None = None,
                     title_matcher=None) -> int | None:
    """
    動態尋找 PaintTool SAI 2 的畫布視窗。
    1. 優先尋找頂層的浮動畫布視窗（面積最大且為 sflRootWindow 的頂層視窗）。
       若提供 title_matcher(title) -> bool，僅接受標題與目前錄製圖檔相符的
       浮動視窗，避免錄到其他圖檔（參考圖）的浮動視窗。
    2. 若無浮動畫布視窗，則尋找主視窗底下面積最大的 sflChildWindow 子視窗作為畫布。
    """
    if not main_hwnd:
        main_win, _ = scan_sai_windows(my_pid)
        if not main_win:
            return None
        main_hwnd = main_win[0]

    # 1. 尋找頂層浮動視窗
    top_wins = []
    def _enum_top(hwnd, _):
        if hwnd != main_hwnd and win32gui.IsWindowVisible(hwnd):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == win32process.GetWindowThreadProcessId(main_hwnd)[1]:
                    cls = win32gui.GetClassName(hwnd)
                    if cls == "sflRootWindow":
                        if title_matcher is not None:
                            # 檔名驗證：只接受屬於目前錄製圖檔的浮動視窗
                            try:
                                title = win32gui.GetWindowText(hwnd)
                            except Exception:
                                title = ""
                            if not title_matcher(title):
                                return True
                        rect = win32gui.GetWindowRect(hwnd)
                        w = rect[2] - rect[0]
                        h = rect[3] - rect[1]
                        if w > 0 and h > 0:
                            top_wins.append((hwnd, w * h))
            except Exception:
                pass
        return True

    try:
        win32gui.EnumWindows(_enum_top, None)
    except Exception:
        pass

    if top_wins:
        top_wins.sort(key=lambda x: x[1], reverse=True)
        if top_wins[0][1] > 100000:
            return top_wins[0][0]

    # 2. 尋找子視窗中最大的 sflChildWindow
    child_wins = []
    def _enum_child(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            try:
                cls = win32gui.GetClassName(hwnd)
                if cls == "sflChildWindow":
                    rect = win32gui.GetWindowRect(hwnd)
                    w = rect[2] - rect[0]
                    h = rect[3] - rect[1]
                    if w > 0 and h > 0:
                        child_wins.append((hwnd, w * h))
            except Exception:
                pass
        return True

    try:
        win32gui.EnumChildWindows(main_hwnd, _enum_child, None)
    except Exception:
        pass

    if child_wins:
        child_wins.sort(key=lambda x: x[1], reverse=True)
        return child_wins[0][0]

    return main_hwnd



class TimelapseRecorder:
    """負責背景定時擷取並呼叫 ffmpeg 合成縮時影片"""

    def __init__(self, output_dir: str, fps: int = 30):
        self.output_dir = output_dir
        self.fps = fps
        self.enabled = False
        self.multiplier = 5
        # "canvas" (優先浮動視窗，無則主視窗), "canvas_float" (自動開浮動視窗隱形錄製),
        # "window" (主視窗), "screen" (整個螢幕)
        self.target_mode = "canvas"
        self.quality_preset = "standard"  # "compact", "standard", "high", "lossless"
        self.idle_timeout = 10.0
        
        self.active_file: str | None = None
        self.temp_dir: str | None = None
        self.frame_count = 0
        self.total_recorded_duration = 0.0
        self.is_actively_recording = False  # 是否正在「動筆擷取中」
        
        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        
        # 視窗緩存（大幅減少 EnumWindows 頻率）
        self.sai_pid = -1
        self.sai_main_hwnd = None
        self._cached_canvas_hwnd = None
        self._last_canvas_scan = 0.0
        self.needs_thumbnail = True

        # 檔名比對回呼：file_matcher(window_title) -> 解析後的圖檔 key (或 None)。
        # 由主程式設定 (含別名解析)，用於驗證錄製目標視窗是否屬於目前圖檔。
        self.file_matcher = None

        # canvas_float 模式狀態：自動建立的隱藏浮動視窗
        self._float_hwnd = None
        self._float_last_attempt = 0.0
        self._float_fail_count = 0
        self._float_given_up = False
        
        # 導出執行緒註冊表
        self.export_threads: list[threading.Thread] = []
        
        # 外部 UI 回呼
        self.on_frame_captured = None  # callback(frame_count: int, thumb: Image.Image, msg: str)
        self.on_status_msg = None      # callback(message: str)
        self.on_export_progress = None # callback(pct: int, msg: str)
        
        # 非同步寫入佇列與背景執行緒
        self._write_queue = queue.Queue(maxsize=100)
        self._writer_thread: threading.Thread | None = None

    def _writer_loop(self):
        """背景寫入佇列處理迴圈，消除磁碟寫入對錄影主執行緒造成的阻塞"""
        while True:
            item = self._write_queue.get()
            if item is None:
                self._write_queue.task_done()
                break
            
            img, path, quality_val = item
            try:
                if path.lower().endswith('.png'):
                    img.save(path, format='PNG')
                else:
                    img.save(path, format='JPEG', quality=quality_val)
            except Exception:
                pass
            finally:
                self._write_queue.task_done()

    def start(self):
        """啟動錄製監控執行緒"""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._paused = False
            
            # 清空舊佇列
            self._write_queue = queue.Queue(maxsize=100)
            
            # 啟動非同步磁碟寫入執行緒
            self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
            self._writer_thread.start()
            
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self):
        """停止監控，並將剩餘尚未合成的圖檔進行合成導出"""
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            
        # 停止寫入執行緒，確保所有佇列中的幀圖都已寫入磁碟後才結束
        if self._writer_thread and self._writer_thread.is_alive():
            try:
                self._write_queue.put(None, timeout=1.0)
                self._writer_thread.join(timeout=5.0)
            except Exception:
                pass
        
        # 停止時若有正在進行的檔案，觸發最終導出
        if self.active_file:
            self.switch_file(None)
        else:
            self._close_float_window()

    def set_paused(self, paused: bool):
        """暫停/繼續擷取"""
        with self._lock:
            self._paused = paused

    def switch_file(self, new_file: str | None):
        """當 active 畫布檔案變更或關閉時被呼叫"""
        with self._lock:
            should_be_recording = self.enabled and (new_file is not None)
            is_currently_recording = (self.active_file is not None) and (self.temp_dir is not None)

            if is_currently_recording and (not should_be_recording or self.active_file != new_file):
                # 停止目前的錄製並匯出
                if self.frame_count > 0:
                    self._trigger_export(self.active_file, self.temp_dir, self.frame_count)
                else:
                    shutil.rmtree(self.temp_dir, ignore_errors=True)

                self.active_file = None
                self.temp_dir = None
                self.frame_count = 0
                self.is_actively_recording = False
                # 關閉 canvas_float 模式自動建立的浮動視窗
                self._close_float_window()

            if should_be_recording and (self.active_file != new_file or self.temp_dir is None):
                # 開始錄製新檔案
                self.active_file = new_file
                self.frame_count = 0
                self.total_recorded_duration = 0.0
                self.is_actively_recording = False
                # 重置 canvas_float 模式的失敗狀態，新圖檔重新嘗試建立浮動檢視
                self._float_fail_count = 0
                self._float_given_up = False
                self._float_last_attempt = 0.0
                
                # 計算該圖檔對應的影片子目錄
                file_subdir = file_key_to_subdir(new_file)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                temp_name = f"{file_subdir}_{timestamp}"
                self.temp_dir = os.path.join(self.output_dir, "temp", temp_name)
                # 記錄目前影片子目錄，導出時使用
                self._current_subdir = file_subdir
                try:
                    os.makedirs(self.temp_dir, exist_ok=True)
                except Exception:
                    self.temp_dir = None

    def _title_matches_file(self, title: str, active_file: str | None) -> bool:
        """以主程式提供的 file_matcher 驗證視窗標題是否屬於目前錄製的圖檔。
        未設定 matcher 或無 active_file 時放行 (維持舊行為)。"""
        if not self.file_matcher or not active_file:
            return True
        try:
            return self.file_matcher(title) == active_file
        except Exception:
            return True

    def _close_float_window(self):
        """關閉 canvas_float 模式自動建立的浮動視窗 (WM_CLOSE 只關閉檢視，不影響畫布)"""
        hwnd = self._float_hwnd
        self._float_hwnd = None
        if hwnd:
            try:
                if win32gui.IsWindow(hwnd):
                    win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            except Exception:
                pass

    def _ensure_float_window(self, main_hwnd, active_file) -> int | None:
        """
        canvas_float 模式：確保存在一個「移到螢幕外」的浮動檢視視窗供隱形錄製。
        不存在時自動對 SAI2 送出 Ctrl+Alt+N 建立目前畫布的新浮動檢視，
        並將其移出虛擬螢幕範圍，使用者完全無感。

        認領策略：以「按鍵前後的視窗差集」為準——我們送出的按鍵所產生的新視窗
        就是目標，不強制要求標題與圖檔 key 完全一致 (浮動檢視標題可能帶有
        檢視編號後綴)。標題/類別只作為多個新視窗時的偏好排序。
        連續失敗 3 次後放棄 (直到切換圖檔)，避免不斷對 SAI2 送按鍵開出一堆視窗。
        """
        # 既有視窗仍有效 → 直接使用 (視窗是我們建立並認領的，不重複驗證標題)
        if self._float_hwnd:
            try:
                if win32gui.IsWindow(self._float_hwnd):
                    return self._float_hwnd
            except Exception:
                pass
            self._float_hwnd = None

        if not main_hwnd or self._float_given_up:
            return None
        # 建立需要模擬按鍵：使用者按著筆/滑鼠時避開，且限制重試頻率
        now = time.time()
        if now - self._float_last_attempt < 10.0 or _mouse_pressed():
            return None
        self._float_last_attempt = now

        try:
            before = set(_enum_pid_toplevel_windows(self.sai_pid).keys())

            # 需要 SAI2 在前景才能接收快捷鍵；記住原前景視窗以便還原
            prev_fg = win32gui.GetForegroundWindow()
            _, prev_pid = win32process.GetWindowThreadProcessId(prev_fg) if prev_fg else (0, -1)
            if prev_pid != self.sai_pid:
                try:
                    win32gui.SetForegroundWindow(main_hwnd)
                    time.sleep(0.15)
                except Exception:
                    return None

            _press_keys([0x11, 0x12, 0x4E])  # Ctrl + Alt + N (開新浮動檢視)

            # 等待新視窗出現 (最多 2.5 秒)，出現後再等一小段讓視窗完成初始化
            new_wins: dict[int, tuple[str, str, int]] = {}
            deadline = time.time() + 2.5
            while time.time() < deadline:
                time.sleep(0.1)
                wins = _enum_pid_toplevel_windows(self.sai_pid)
                new_wins = {h: v for h, v in wins.items() if h not in before}
                if new_wins:
                    time.sleep(0.2)
                    wins = _enum_pid_toplevel_windows(self.sai_pid)
                    new_wins = {h: v for h, v in wins.items() if h not in before}
                    break

            # 把前景還給使用者原本的視窗 (通常是 SAI2 主視窗，本來就在前景)
            if prev_fg and prev_pid != self.sai_pid:
                try:
                    win32gui.SetForegroundWindow(prev_fg)
                except Exception:
                    pass

            if not new_wins:
                self._float_fail_count += 1
                if self._float_fail_count >= 3:
                    self._float_given_up = True
                    if self.on_status_msg:
                        self.on_status_msg(_tr(
                            "timelapse.status.float_failed",
                            "⚠️ 無法建立浮動檢視（請確認 SAI2 的 Ctrl+Alt+N 為「新增檢視視窗」），已改用一般畫布模式錄製"))
                return None

            # 從新視窗中挑選目標：sflRootWindow > 標題含目前圖檔名 > 面積最大
            disp_name = active_file.split(' _ ')[-1].lower() if active_file else ''
            def _score(item):
                _h, (cls, title, area) = item
                s = 0
                if cls == "sflRootWindow":
                    s += 2_000_000_000
                if disp_name and disp_name in title.lower():
                    s += 1_000_000_000
                return s + area
            new_hwnd = max(new_wins.items(), key=_score)[0]

            # 同一次按鍵若意外產生多個視窗，關閉未認領的多餘視窗
            for h in new_wins:
                if h != new_hwnd:
                    try:
                        win32gui.PostMessage(h, 0x0010, 0, 0)  # WM_CLOSE
                    except Exception:
                        pass

            # 移出虛擬螢幕範圍 (右側之外)，SWP_NOSIZE|SWP_NOZORDER|SWP_NOACTIVATE
            SM_XVIRTUALSCREEN, SM_CXVIRTUALSCREEN = 76, 78
            off_x = (win32api.GetSystemMetrics(SM_XVIRTUALSCREEN)
                     + win32api.GetSystemMetrics(SM_CXVIRTUALSCREEN) + 80)
            moved = False
            try:
                win32gui.SetWindowPos(new_hwnd, 0, off_x, 60, 0, 0, 0x0001 | 0x0004 | 0x0010)
                l, t, r, b = win32gui.GetWindowRect(new_hwnd)
                moved = (l >= off_x - 5)
                if not moved:
                    # SetWindowPos 被鎖回螢幕內 → 改用 MoveWindow 再試一次
                    win32gui.MoveWindow(new_hwnd, off_x, 60, r - l, b - t, True)
                    l2, _, _, _ = win32gui.GetWindowRect(new_hwnd)
                    moved = (l2 >= off_x - 5)
            except Exception:
                pass

            self._float_hwnd = new_hwnd
            self._float_fail_count = 0
            if self.on_status_msg:
                if moved:
                    self.on_status_msg(_tr(
                        "timelapse.status.float_ready",
                        "📹 已建立隱藏浮動檢視，鎖定錄製中"))
                else:
                    self.on_status_msg(_tr(
                        "timelapse.status.float_onscreen",
                        "📹 已建立浮動檢視並鎖定錄製（無法移出螢幕，視窗仍在畫面上）"))
            return new_hwnd
        except Exception:
            self._float_fail_count += 1
            return None

    def _loop(self):
        """擷取背景迴圈，高精度偵測動筆狀態與計時"""
        try:
            my_pid = os.getpid()
        except Exception:
            my_pid = -1

        self._last_pid_scan = 0.0
        last_cursor_pos = None
        last_loop_time = time.perf_counter()
        active_draw_accum = 0.0
        last_active_time = time.perf_counter() # 用於 1.5 秒動筆緩衝時間

        # 自適應輪詢間隔：動筆錄製中維持 15ms 精度以支援 1x 30FPS；
        # 閒置/暫停/SAI 不在前景時降頻，將背景 CPU 消耗降到接近零
        poll_delay = 0.015
        while self._running:
            time.sleep(poll_delay)
            poll_delay = 0.015  # 預設高精度，以下各閒置分支會調高

            now_perf = time.perf_counter()
            dt = now_perf - last_loop_time
            last_loop_time = now_perf

            # 1. 快速在鎖內讀取當前設定與狀態，儘速釋放鎖，避免阻塞 UI 執行緒
            with self._lock:
                enabled = self.enabled
                active_file = self.active_file
                paused = self._paused
                temp_dir = self.temp_dir
                target_mode = self.target_mode
                multiplier = self.multiplier
                frame_count = self.frame_count
                idle_timeout = getattr(self, 'idle_timeout', 10.0)

            if not enabled or not active_file or paused or not temp_dir:
                self.is_actively_recording = False
                active_draw_accum = 0.0
                poll_delay = 0.25
                continue

            # 2. 快速取得最頂層前景視窗與其 PID (不列舉所有視窗，極低 CPU 消耗)
            try:
                fg_hwnd = win32gui.GetForegroundWindow()
                if not fg_hwnd:
                    self.is_actively_recording = False
                    poll_delay = 0.1
                    continue

                # 如果前景視窗是系統對話框（例如儲存/另存新檔），不進行錄影以避開彈窗
                fg_class = win32gui.GetClassName(fg_hwnd)
                if fg_class == "#32770":
                    self.is_actively_recording = False
                    poll_delay = 0.1
                    continue

                _, fg_pid = win32process.GetWindowThreadProcessId(fg_hwnd)
            except Exception:
                self.is_actively_recording = False
                poll_delay = 0.1
                continue

            # 檢查並更新 PID 緩存與最上層狀態
            is_sai = False
            now_time = time.time()
            
            # 如果緩存的主視窗控制代碼已經失效，重設緩存
            if self.sai_pid != -1 and self.sai_main_hwnd:
                if not win32gui.IsWindow(self.sai_main_hwnd):
                    self.sai_pid = -1
                    self.sai_main_hwnd = None

            if self.sai_pid != -1 and fg_pid == self.sai_pid:
                is_sai = True
            else:
                # 嘗試從最上層視窗標題直接判定
                try:
                    title = win32gui.GetWindowText(fg_hwnd).lower()
                    if 'painttool sai' in title:
                        self.sai_pid = fg_pid
                        self.sai_main_hwnd = fg_hwnd
                        is_sai = True
                except Exception:
                    pass

                # 若還是判定不是，且距離上次掃描超過 2 秒，列舉一次視窗找出正確的 PID
                if not is_sai and now_time - self._last_pid_scan > 2.0:
                    self._last_pid_scan = now_time
                    main_win, _ = scan_sai_windows(my_pid)
                    if main_win:
                        try:
                            _, pid = win32process.GetWindowThreadProcessId(main_win[0])
                            self.sai_pid = pid
                            self.sai_main_hwnd = main_win[0]
                            if fg_pid == pid:
                                is_sai = True
                        except Exception:
                            pass

            if not is_sai:
                self.is_actively_recording = False
                poll_delay = 0.1
                continue

            # 偵測是否正在動筆（根據閒置逾時設定決定是否過濾非點擊操作）
            if idle_timeout <= 0.0:
                # 僅在滑鼠/繪圖板點擊按住時才算作動筆，不使用緩衝，無筆壓/無按壓時不錄製
                is_recording_active = _mouse_pressed()
            else:
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

                is_active = _mouse_pressed() or cursor_moved
                if is_active:
                    last_active_time = now_perf

                # 直接使用使用者設定的閒置逾時時間作為緩衝時間，不使用額外的硬編碼冷卻時間
                is_recording_active = (now_perf - last_active_time) <= idle_timeout

            if not is_recording_active:
                self.is_actively_recording = False
                poll_delay = 0.05
                continue

            # 正在動筆中（或處於緩衝期內）！
            self.is_actively_recording = True
            
            # 累計動筆時間
            active_draw_accum += dt
            
            with self._lock:
                self.total_recorded_duration += dt
            
            # 計算擷取門檻：倍速 multiplier / fps
            fps_val = max(1, self.fps)
            target_interval = multiplier / fps_val
            
            if active_draw_accum < target_interval:
                continue
                
            # 達到擷取間隔門檻，扣除一個間隔，並保留剩餘的微小時間差
            active_draw_accum = active_draw_accum % target_interval

            # 3. 在鎖外執行擷取與儲存，以最快速度完成磁碟 I/O，不佔用任何 UI 資源
            target_hwnd = None
            fallback_msg = ""
            img = None

            # 預先獲取 main_hwnd，儘量避免重複掃描
            main_hwnd = self.sai_main_hwnd
            if not main_hwnd or not win32gui.IsWindow(main_hwnd):
                main_win, _ = scan_sai_windows(my_pid)
                main_hwnd = main_win[0] if main_win else None
                if main_hwnd:
                    self.sai_main_hwnd = main_hwnd
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(main_hwnd)
                        self.sai_pid = pid
                    except Exception:
                        pass

            # canvas_float 模式：優先錄製自動建立的「螢幕外浮動視窗」，
            # 使用者在主視窗的任何分頁切換/參考圖操作都不會影響錄製內容
            if target_mode == "canvas_float":
                float_hwnd = self._ensure_float_window(main_hwnd, active_file)
                if float_hwnd:
                    img = capture_window_gdi(float_hwnd, prefer_printwindow=True)
                    if img:
                        try:
                            rect = win32gui.GetWindowRect(float_hwnd)
                            client_rect = win32gui.GetClientRect(float_hwnd)
                            client_left, client_top = win32gui.ClientToScreen(float_hwnd, (0, 0))
                            offset_x = client_left - rect[0]
                            offset_y = client_top - rect[1]
                            client_w = client_rect[2]
                            client_h = client_rect[3]
                            if client_w > 0 and client_h > 0:
                                img = img.crop((offset_x, offset_y, offset_x + client_w, offset_y + client_h))
                        except Exception:
                            pass
                if img is None and not self._float_given_up:
                    # 浮動視窗尚未建立成功 → 本影格暫時退回一般畫布邏輯
                    fallback_msg = " " + _tr("timelapse.status.float_pending", "(浮動視窗準備中)")

            if target_mode == "canvas" or (target_mode == "canvas_float" and img is None):
                canvas_hwnd = None
                now_t = time.time()

                # 快速確認快取控制代碼是否仍然有效 (含浮動視窗的檔名驗證)
                if self._cached_canvas_hwnd:
                    hwnd_ok = False
                    try:
                        if win32gui.IsWindow(self._cached_canvas_hwnd) and win32gui.IsWindowVisible(self._cached_canvas_hwnd):
                            _, w_pid = win32process.GetWindowThreadProcessId(self._cached_canvas_hwnd)
                            if w_pid == self.sai_pid:
                                cls = win32gui.GetClassName(self._cached_canvas_hwnd)
                                if cls in ("sflChildWindow", "sflRootWindow"):
                                    if cls == "sflRootWindow":
                                        # 浮動畫布視窗：驗證標題屬於目前錄製的圖檔
                                        hwnd_ok = self._title_matches_file(
                                            win32gui.GetWindowText(self._cached_canvas_hwnd), active_file)
                                    else:
                                        hwnd_ok = True
                    except Exception:
                        hwnd_ok = False

                    if hwnd_ok:
                        canvas_hwnd = self._cached_canvas_hwnd

                # 若無快取或時間到期，重新尋找畫布視窗 (僅接受屬於目前圖檔的浮動視窗)
                if not canvas_hwnd or (now_t - self._last_canvas_scan > 1.0):
                    self._last_canvas_scan = now_t
                    canvas_hwnd = find_canvas_hwnd(
                        my_pid, main_hwnd,
                        title_matcher=lambda t: self._title_matches_file(t, active_file))
                    self._cached_canvas_hwnd = canvas_hwnd

                if canvas_hwnd:
                    is_child = False
                    if main_hwnd and canvas_hwnd != main_hwnd:
                        try:
                            # 判斷是否為子視窗（分頁模式）
                            is_child = win32gui.IsChild(main_hwnd, canvas_hwnd)
                        except Exception:
                            is_child = False

                    if is_child and main_hwnd:
                        # 分頁畫布子視窗：主視窗標題必須仍是目前錄製的圖檔，
                        # 否則代表使用者切到其他分頁 (例如參考圖)，跳過此影格
                        try:
                            main_title_ok = self._title_matches_file(
                                win32gui.GetWindowText(main_hwnd), active_file)
                        except Exception:
                            main_title_ok = True
                        if not main_title_ok:
                            continue
                        # 分頁畫布子視窗：擷取主視窗再進行裁剪，可避開彈窗且解決子視窗 GDI 擷取空白的問題
                        img = capture_window_gdi(main_hwnd)
                        if img:
                            try:
                                main_rect = win32gui.GetWindowRect(main_hwnd)
                                canvas_rect = win32gui.GetWindowRect(canvas_hwnd)
                                
                                rel_left = canvas_rect[0] - main_rect[0]
                                rel_top = canvas_rect[1] - main_rect[1]
                                rel_right = canvas_rect[2] - main_rect[0]
                                rel_bottom = canvas_rect[3] - main_rect[1]
                                
                                # 確保裁剪邊界合法
                                rel_left = max(0, rel_left)
                                rel_top = max(0, rel_top)
                                rel_right = min(img.width, rel_right)
                                rel_bottom = min(img.height, rel_bottom)
                                
                                if rel_right > rel_left and rel_bottom > rel_top:
                                    img = img.crop((rel_left, rel_top, rel_right, rel_bottom))
                                else:
                                    img = None
                            except Exception:
                                img = None
                    else:
                        # 頂層浮動視窗：直接擷取該視窗，並裁剪掉非客戶區（邊框、標題列）
                        img = capture_window_gdi(canvas_hwnd)
                        if img:
                            try:
                                rect = win32gui.GetWindowRect(canvas_hwnd)
                                client_rect = win32gui.GetClientRect(canvas_hwnd)
                                client_left, client_top = win32gui.ClientToScreen(canvas_hwnd, (0, 0))
                                
                                offset_x = client_left - rect[0]
                                offset_y = client_top - rect[1]
                                
                                client_w = client_rect[2]
                                client_h = client_rect[3]
                                
                                if client_w > 0 and client_h > 0:
                                    img = img.crop((offset_x, offset_y, offset_x + client_w, offset_y + client_h))
                            except Exception:
                                pass
                else:
                    # 找不到畫布視窗 → 退回主視窗，但同樣驗證主視窗標題屬於目前圖檔
                    target_hwnd = main_hwnd
                    fallback_msg = " " + _tr("timelapse.status.canvas_missing")
                    if target_hwnd:
                        try:
                            if not self._title_matches_file(
                                    win32gui.GetWindowText(target_hwnd), active_file):
                                continue
                        except Exception:
                            pass
                        img = capture_window_gdi(target_hwnd)
            elif target_mode in ("window", "screen"):
                if target_mode == "window":
                    target_hwnd = main_hwnd
                else:
                    target_hwnd = 0  # 螢幕模式

                if target_hwnd is not None:
                    try:
                        img = capture_window_gdi(target_hwnd)
                    except Exception:
                        img = None

            if img:
                # 確保寬高為偶數，避免 FFmpeg 因 yuv420p 要求寬高必為偶數而合成失敗
                img = make_even_dimensions(img)
                
                ext = "png" if self.quality_preset == "lossless" else "jpg"
                frame_path = os.path.join(temp_dir, f"frame_{frame_count:06d}.{ext}")
                
                quality_val = 90
                if self.quality_preset == "compact":
                    quality_val = 75
                elif self.quality_preset == "high":
                    quality_val = 98
                
                # 將圖片放入非同步寫入佇列，避免磁碟寫入阻塞主錄影執行緒
                try:
                    self._write_queue.put((img, frame_path, quality_val), block=False)
                except Exception:
                    # 佇列滿了則同步寫入以防丟幀
                    try:
                        if ext == "png":
                            img.save(frame_path, format='PNG')
                        else:
                            img.save(frame_path, format='JPEG', quality=quality_val)
                    except Exception:
                        pass
                
                # 在背景執行緒生成縮圖，減輕 UI 執行緒的負擔
                thumb = None
                if getattr(self, 'needs_thumbnail', True):
                    # 降頻生成：每 0.2 秒最多生成一次預覽縮圖
                    now_ts = time.time()
                    if not hasattr(self, '_last_thumb_time') or now_ts - self._last_thumb_time > 0.2:
                        self._last_thumb_time = now_ts
                        try:
                            # 直接 resize 產生縮圖 (thumbnail() 需先整幅 copy，較浪費)
                            ratio = min(160 / img.width, 90 / img.height, 1.0)
                            tw = max(1, int(img.width * ratio))
                            th = max(1, int(img.height * ratio))
                            thumb = img.resize((tw, th), Image.BILINEAR)
                        except Exception:
                            pass
                
                with self._lock:
                    self.frame_count += 1
                    current_count = self.frame_count
                
                if self.on_frame_captured:
                    try:
                        # 傳送預先生成好的縮圖 (thumb) 而非高解析度的 img 檔案給 UI 回呼
                        self.on_frame_captured(current_count, thumb, fallback_msg)
                    except Exception:
                        pass

    def _trigger_export(self, filename: str, temp_dir: str, frame_count: int):
        """啟動背景執行緒，將暫存圖檔合成影片"""
        t = threading.Thread(
            target=self._export_worker_wrapper,
            args=(filename, temp_dir, frame_count),
            daemon=True
        )
        with self._lock:
            self.export_threads.append(t)
        t.start()

    def _export_worker_wrapper(self, filename: str, temp_dir: str, frame_count: int):
        try:
            self._export_worker(filename, temp_dir, frame_count)
        finally:
            with self._lock:
                if threading.current_thread() in self.export_threads:
                    self.export_threads.remove(threading.current_thread())


    def _export_worker(self, filename: str, temp_dir: str, frame_count: int):
        """ffmpeg 合成背景工作程序"""
        ext = "png" if self.quality_preset == "lossless" else "jpg"

        # 等待所有佇列中的影格檔案完全寫入磁碟，確保不丟影格，防範 shutil.rmtree 造成的競態衝突
        if frame_count > 0:
            last_frame_name = f"frame_{frame_count-1:06d}.{ext}"
            last_frame_path = os.path.join(temp_dir, last_frame_name)
            
            # 最多等待 15 秒安全逾時，以免無限期阻塞
            wait_start = time.perf_counter()
            while not os.path.exists(last_frame_path):
                if time.perf_counter() - wait_start > 15.0:
                    break
                time.sleep(0.05)

        if not find_ffmpeg():
            if self.on_status_msg:
                self.on_status_msg(_tr("timelapse.status.ffmpeg_missing"))
            shutil.rmtree(temp_dir, ignore_errors=True)
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 出輸到該圖檔對應的子目錄
        with self._lock:
            subdir = getattr(self, '_current_subdir', None) or file_key_to_subdir(filename)
        video_dir = os.path.join(self.output_dir, subdir)
        os.makedirs(video_dir, exist_ok=True)
        output_filename = f"{timestamp}.mp4"
        output_path = os.path.join(video_dir, output_filename)

        with self._lock:
            total_dur = self.total_recorded_duration
            multiplier = self.multiplier

        # 計算適合的輸入影格率以維持設定的播放倍速
        if total_dur > 0.1 and frame_count > 0:
            input_fps = (frame_count / total_dur) * multiplier
            input_fps = min(120.0, max(1.0, input_fps))
        else:
            input_fps = self.fps

        if self.on_status_msg:
            self.on_status_msg(_tr("timelapse.status.ffmpeg_exporting", name=output_filename, count=frame_count))

        ext = "png" if self.quality_preset == "lossless" else "jpg"
        input_pattern = os.path.join(temp_dir, f'frame_%06d.{ext}')
        
        crf_val = '22'
        if self.quality_preset == 'compact':
            crf_val = '26'
        elif self.quality_preset == 'high':
            crf_val = '18'
        elif self.quality_preset == 'lossless':
            # 使用 CRF 1 代替 0。因為 CRF 0 (H.264 Lossless) 會強制使用 High 4:2:0 Predictive Profile，
            # 導致 Windows 內建「媒體播放器」無法解碼播放。CRF 1 具備極致的近無損畫質且 100% 相容。
            crf_val = '1'

        # libx264, preset fast (兼顧速度)，並輸出 progress 資訊
        cmd = [
            'ffmpeg', '-y',
            '-framerate', f"{input_fps:.3f}",
            '-i', input_pattern,
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', crf_val,
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            '-r', str(self.fps),
            '-progress', '-',
            output_path
        ]

        process = None
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=0x08000000 | 0x00004000  # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
            )
            
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith('frame='):
                    try:
                        parts = line.split('=')
                        if len(parts) >= 2:
                            curr_frame = int(parts[1].strip())
                            pct = int(curr_frame / frame_count * 100)
                            pct = min(100, max(0, pct))
                            if self.on_export_progress:
                                self.on_export_progress(pct, _tr("timelapse.status.ffmpeg_progress", name=output_filename, pct=pct))
                    except Exception:
                        pass
            
            process.wait(timeout=30)
            if process.returncode == 0:
                if self.on_export_progress:
                    self.on_export_progress(100, _tr("timelapse.status.ffmpeg_success", path=output_path))
            else:
                if self.on_export_progress:
                    self.on_export_progress(0, _tr("timelapse.status.ffmpeg_failed", code=process.returncode))
        except Exception as e:
            if process:
                try:
                    process.kill()
                except Exception:
                    pass
            if self.on_export_progress:
                self.on_export_progress(0, _tr("timelapse.status.ffmpeg_error", err=str(e)))
        finally:
            # 影片匯出完成（或失敗）後，將最後一幀存為 last_frame.jpg 小圖
            self._save_last_frame(temp_dir, video_dir)
            # 清理暫存資料夾
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _save_last_frame(self, temp_dir: str, video_dir: str):
        """將暫存區中編號最大的一幀複製為 last_frame.jpg，供 hover 縮圖預覽使用"""
        try:
            import glob
            ext = "png" if self.quality_preset == "lossless" else "jpg"
            frames = sorted(glob.glob(os.path.join(temp_dir, f'frame_*.{ext}')))
            if not frames:
                return
            last_frame_src = frames[-1]
            dest = os.path.join(video_dir, 'last_frame.jpg')
            if ext == 'png':
                with Image.open(last_frame_src) as img:
                    img.convert('RGB').save(dest, 'JPEG', quality=90)
            else:
                shutil.copy2(last_frame_src, dest)
        except Exception:
            pass
