# -*- coding: utf-8 -*-
"""
sai2_launcher.py - 在 SAI2 開啟檔案的統一流程（不含 UI）

1.x 直接執行 `sai2.exe <檔案>`：SAI2 未開啟時，帶檔案參數啟動的介面與直接開 sai2.exe 不同。
2.0 一律走同一條流程：
  1. 找 SAI2 行程（名稱完全比對，不用子字串）
  2. 未執行 → 單獨啟動 sai2.exe，等主視窗出現且可接受輸入
  3. 把檔案交給現有的 SAI2（drop：對主視窗送出拖放檔案訊息〔預設〕；cmdline：再執行一次 sai2.exe <檔案>）
     兩種方式在 SAI2 Ver.2 (64bit) Preview.2023.07.11 實測都會開在既有視窗、不會多出第二個 SAI2；
     drop 不需要另外啟動行程，SAI2 已開啟時也不必知道執行檔路徑
  4. 確認 SAI2 視窗標題出現該檔名
同一時間只處理一個開檔要求，避免連點造成重複開檔。

Win32 呼叫集中在 Win32Backend，流程類別 Sai2Opener 可注入假的 backend 做測試。
"""

from __future__ import annotations

import os
import ctypes
import ctypes.wintypes as wt
import threading
import subprocess
import time
from dataclasses import dataclass, field

from core.tracker import extract_filename, is_sai2_title

SAI2_EXE_NAMES = ('sai2.exe', 'sai2demo.exe')


def is_sai2_exe_name(name: str, extra: tuple[str, ...] = ()) -> bool:
    """行程名稱完全比對（不分大小寫）；extra 為設定中的執行檔名稱"""
    n = (name or '').lower()
    return n in SAI2_EXE_NAMES or n in tuple(e.lower() for e in extra if e)


def title_has_file(title: str, path: str) -> bool:
    """SAI2 視窗標題是否顯示指定檔案（未存檔標記 * 不影響）。
    SAI2 會把路徑顯示成「使用者 / AppData / … / 檔名.psd」，只比對最後一段。
    （tracker.extract_filename 會把斜線換成底線以當作紀錄名稱，這裡需要原始的最後一段，所以不沿用）"""
    if not extract_filename(title or ''):
        return False
    t = title.strip()
    low = t.lower()
    if low.startswith('painttool') or low.startswith('sai2'):
        part = t.split(' - ', 1)[1] if ' - ' in t else ''
    else:
        part = t.rsplit(' - ', 1)[0]
    name = part.replace('\\', '/').split('/')[-1].strip()
    for mark in ('(*)', '(已修改)', '(modified)', '(変更あり)'):
        if name.endswith(mark):
            name = name[:-len(mark)]
    name = name.strip('*＊ ').lower()
    base = os.path.basename(path).lower()
    stem = os.path.splitext(base)[0]
    return name == base or name == stem


# ─── Win32 ──────────────────────────────────────────────────────────────

_user32 = ctypes.WinDLL('user32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_shell32 = ctypes.WinDLL('shell32', use_last_error=True)
_WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wt.LPARAM]
_user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
_user32.GetWindow.restype = wt.HWND
_user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
_user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.WaitForInputIdle.argtypes = [wt.HANDLE, wt.DWORD]
_user32.WaitForInputIdle.restype = wt.DWORD
_kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_kernel32.OpenProcess.restype = wt.HANDLE
_kernel32.CloseHandle.argtypes = [wt.HANDLE]
_kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = wt.HGLOBAL
_kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
_kernel32.GlobalFree.argtypes = [wt.HGLOBAL]

GW_OWNER = 4
WM_DROPFILES = 0x0233
GHND = 0x0042
SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000


class _DROPFILES(ctypes.Structure):
    _fields_ = [('pFiles', wt.DWORD), ('pt', wt.POINT), ('fNC', wt.BOOL), ('fWide', wt.BOOL)]


def _window_text(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    _user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def windows_of(pid: int) -> list[tuple[int, str, bool]]:
    """行程的可見頂層視窗：(hwnd, 標題, 是否有 owner)"""
    out = []

    def _cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd):
            p = wt.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid:
                out.append((hwnd, _window_text(hwnd), bool(_user32.GetWindow(hwnd, GW_OWNER))))
        return True
    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return out


class Win32Backend:
    """真正的 Windows 實作"""

    def find_processes(self, extra_names: tuple[str, ...] = ()) -> list[tuple[int, str]]:
        import psutil
        found = []
        for p in psutil.process_iter(['pid', 'name', 'exe']):
            if is_sai2_exe_name(p.info.get('name') or '', extra_names):
                found.append((p.info['pid'], p.info.get('exe') or ''))
        return found

    def main_window(self, pid: int) -> int:
        """無 owner 的 SAI2 視窗；找不到時取面積最大的無 owner 視窗"""
        best, best_area = 0, -1
        for hwnd, title, owned in windows_of(pid):
            if owned:
                continue
            if is_sai2_title(title):
                return hwnd
            r = wt.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(r))
            area = (r.right - r.left) * (r.bottom - r.top)
            if area > best_area:
                best, best_area = hwnd, area
        return best

    def titles(self, pid: int) -> list[str]:
        return [t for _, t, _ in windows_of(pid)]

    def spawn(self, args: list[str]) -> int:
        return subprocess.Popen(args, cwd=os.path.dirname(args[0]) or None).pid

    def wait_input_idle(self, pid: int, timeout_ms: int) -> bool:
        h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not h:
            return False
        try:
            return _user32.WaitForInputIdle(h, timeout_ms) == 0
        finally:
            _kernel32.CloseHandle(h)

    def drop_files(self, hwnd: int, paths: list[str]) -> bool:
        """對視窗送出 WM_DROPFILES（等同從檔案總管拖放）"""
        files = ('\0'.join(os.path.abspath(p) for p in paths) + '\0\0').encode('utf-16-le')
        head = ctypes.sizeof(_DROPFILES)
        hglobal = _kernel32.GlobalAlloc(GHND, head + len(files))
        if not hglobal:
            return False
        ptr = _kernel32.GlobalLock(hglobal)
        df = _DROPFILES(pFiles=head, pt=wt.POINT(0, 0), fNC=False, fWide=True)
        ctypes.memmove(ptr, ctypes.byref(df), head)
        ctypes.memmove(ptr + head, files, len(files))
        _kernel32.GlobalUnlock(hglobal)
        if not _user32.PostMessageW(hwnd, WM_DROPFILES, hglobal, 0):
            _kernel32.GlobalFree(hglobal)
            return False
        return True       # 送出成功後記憶體由接收端（DragFinish）釋放

    def focus(self, hwnd: int):
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, SW_RESTORE)
        _user32.SetForegroundWindow(hwnd)


# ─── 流程 ────────────────────────────────────────────────────────────────

@dataclass
class OpenResult:
    ok: bool
    status: str                  # opened / need_exe / not_found / launch_timeout / handoff_failed / verify_timeout / busy
    detail: str = ''
    launched: bool = False       # 這次有先啟動 SAI2
    exe_path: str = ''           # 找到或使用的 sai2.exe（呼叫端可存入設定）
    extra_instances: int = 0     # 開檔後多出來的 SAI2 行程數（應為 0）
    steps: list[str] = field(default_factory=list)


class Sai2Opener:
    def __init__(self, backend=None, exe_path: str = '', method: str = 'drop',
                 launch_timeout: float = 30.0, verify_timeout: float = 15.0, settle: float = 1.5,
                 poll: float = 0.25, clock=time.monotonic, sleep=time.sleep, isfile=os.path.isfile):
        self.backend = backend or Win32Backend()
        self.exe_path = exe_path
        self.method = method
        self.launch_timeout = launch_timeout
        self.verify_timeout = verify_timeout
        self.settle = settle
        self.poll = poll
        self._clock, self._sleep, self._isfile = clock, sleep, isfile
        self._lock = threading.Lock()

    def _extra_names(self) -> tuple[str, ...]:
        return (os.path.basename(self.exe_path),) if self.exe_path else ()

    def _wait(self, cond, timeout: float):
        end = self._clock() + timeout
        while True:
            v = cond()
            if v or self._clock() >= end:
                return v
            self._sleep(self.poll)

    def open(self, path: str) -> OpenResult:
        if not self._lock.acquire(blocking=False):
            return OpenResult(False, 'busy')
        try:
            return self._open(path)
        finally:
            self._lock.release()

    def _open(self, path: str) -> OpenResult:
        res = OpenResult(False, '')
        if not self._isfile(path):
            res.status, res.detail = 'not_found', path
            return res
        b = self.backend
        procs = b.find_processes(self._extra_names())
        if procs:
            pid, exe = procs[0]
            if exe:
                self.exe_path = exe
            res.steps.append(f'running pid={pid}')
        else:
            if not self.exe_path or not self._isfile(self.exe_path):
                res.status = 'need_exe'
                return res
            pid = b.spawn([self.exe_path])
            res.launched = True
            res.steps.append(f'launched pid={pid}')
            if not self._wait(lambda: b.main_window(pid), self.launch_timeout):
                res.status = 'launch_timeout'
                return res
            b.wait_input_idle(pid, int(self.launch_timeout * 1000))
            self._sleep(self.settle)      # 主視窗出現後 SAI2 還會載入面板，稍等再交檔
            res.steps.append('ready')
        res.exe_path = self.exe_path
        hwnd = b.main_window(pid)
        if not hwnd:
            res.status = 'launch_timeout'
            return res

        if any(title_has_file(t, path) for t in b.titles(pid)):
            res.steps.append('already open')
        else:
            if self.method == 'drop':
                if not b.drop_files(hwnd, [path]):
                    res.status = 'handoff_failed'
                    return res
            else:
                b.spawn([self.exe_path, path])
            res.steps.append(f'handoff {self.method}')
            if not self._wait(lambda: any(title_has_file(t, path) for t in b.titles(pid)), self.verify_timeout):
                res.status = 'verify_timeout'
                res.extra_instances = max(0, len(b.find_processes(self._extra_names())) - 1)
                return res
        # cmdline 交檔的第二個 sai2.exe 應把檔案轉交後自行結束，稍等它退場再計算
        self._wait(lambda: len(b.find_processes(self._extra_names())) <= 1, 5.0)
        res.extra_instances = max(0, len(b.find_processes(self._extra_names())) - 1)
        b.focus(hwnd)
        res.ok, res.status = True, 'opened'
        return res
