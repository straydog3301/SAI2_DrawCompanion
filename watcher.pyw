"""
watcher.pyw - SAI2 繪圖時間記錄器「自動啟動監視器」

使用方式：
  以 pythonw.exe 執行（無視窗），或加入 Windows 開機啟動。
  - 偵測到 SAI2 進程時，自動開啟計時器（--auto-close 模式）
  - SAI2 關閉後，計時器會自動倒數並關閉

不需手動啟動或關閉，完全自動。
"""

import os
import sys
import time
import subprocess

# ─── 找到計時器的執行檔 ───────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 優先使用同目錄下已打包的 .exe，否則使用 Python 腳本
_candidates = [
    os.path.join(SCRIPT_DIR, 'SAI2_DrawTimer.exe'),           # 打包後放同目錄
    os.path.join(SCRIPT_DIR, 'dist', 'SAI2_DrawTimer.exe'),   # build.bat 預設輸出
    os.path.join(SCRIPT_DIR, 'main.py'),                       # 開發環境
]
_exe  = next((p for p in _candidates if p.endswith('.exe') and os.path.exists(p)), None)
_main = os.path.join(SCRIPT_DIR, 'main.py')


def _launch_cmd() -> list | None:
    """取得啟動計時器的指令"""
    if _exe:
        return [_exe, '--auto-close']
    if os.path.exists(_main):
        # 用 pythonw.exe 執行 main.py（有視窗的 GUI 用 pythonw 也可）
        py = sys.executable
        # 嘗試換成 pythonw.exe（避免多一個 cmd 視窗）
        pythonw = os.path.join(os.path.dirname(py), 'pythonw.exe')
        interp  = pythonw if os.path.exists(pythonw) else py
        return [interp, _main, '--auto-close']
    return None


# ─── 進程偵測 ────────────────────────────────────────────────────────────
def _is_sai2_running() -> bool:
    """偵測 PaintTool SAI (sai.exe 或 sai2.exe) 是否在執行中，排除本計時器"""
    try:
        import psutil
        return any(
            'sai' in (p.info.get('name') or '').lower()
            and 'drawtimer' not in (p.info.get('name') or '').lower()
            and 'lsaiso' not in (p.info.get('name') or '').lower()
            for p in psutil.process_iter(['name'])
        )
    except Exception:
        pass
    # 備用：tasklist 指令
    try:
        r = subprocess.run(
            'tasklist /NH',
            capture_output=True, text=True, shell=True, timeout=4
        )
        lines = r.stdout.lower().splitlines()
        return any(
            ('sai.exe' in line or 'sai2.exe' in line) and 'drawtimer' not in line
            for line in lines
        )
    except Exception:
        return False


def _timer_alive(proc: subprocess.Popen | None) -> bool:
    """檢查計時器進程是否仍在執行"""
    if proc is None:
        return False
    return proc.poll() is None


# ─── 主迴圈 ──────────────────────────────────────────────────────────────
POLL_INTERVAL = 4   # 秒：偵測間隔

timer_proc: subprocess.Popen | None = None

while True:
    sai2_up = _is_sai2_running()
    timer_up = _timer_alive(timer_proc)

    if sai2_up and not timer_up:
        # SAI2 開啟，計時器尚未執行 → 啟動計時器
        cmd = _launch_cmd()
        if cmd:
            try:
                timer_proc = subprocess.Popen(
                    cmd,
                    cwd=SCRIPT_DIR,
                    creationflags=0x00000008  # DETACHED_PROCESS，避免綁定此進程
                )
            except Exception:
                pass   # 啟動失敗則等下次重試

    time.sleep(POLL_INTERVAL)
