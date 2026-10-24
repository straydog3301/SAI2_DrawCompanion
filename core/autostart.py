# -*- coding: utf-8 -*-
"""
autostart.py - 開機啟動與舊版監視器（不含 UI）

- 2.0 的開機啟動寫在 HKCU\\...\\Run（只影響目前使用者），以 --background 啟動主程式
- 1.x 的監視器捷徑（SAI2_DrawCompanion_Watcher.lnk）會在 SAI2 開啟時另外啟動 1.x，2.0 會提示移除
登錄檔存取經由 backend，測試時可換成假的。
"""

from __future__ import annotations

import os
import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'SAI2DrawCompanion2'
LEGACY_LINK = 'SAI2_DrawCompanion_Watcher.lnk'


class WinregBackend:
    def get(self, name: str) -> str | None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None

    def set(self, name: str, value: str):
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except OSError:
            pass


def launch_command(script: str | None = None) -> str:
    """開機時執行的指令：打包版直接執行 exe；原始碼版用 pythonw 執行入口腳本"""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" --background'
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), 'pythonw.exe')
    return f'"{pyw if os.path.isfile(pyw) else py}" "{script}" --background'


def is_enabled(backend=None) -> bool:
    return bool((backend or WinregBackend()).get(VALUE_NAME))


def set_enabled(on: bool, command: str, backend=None):
    b = backend or WinregBackend()
    if on:
        b.set(VALUE_NAME, command)
    else:
        b.delete(VALUE_NAME)


def startup_dir() -> str:
    return os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')


def legacy_watcher_link(folder: str | None = None) -> str:
    """1.x 監視器的開機捷徑路徑；不存在回傳空字串"""
    p = os.path.join(folder or startup_dir(), LEGACY_LINK)
    return p if os.path.isfile(p) else ''


def legacy_watcher_pids() -> list[int]:
    """執行中的 1.x 監視器（pythonw watcher.pyw）"""
    import psutil
    out = []
    for p in psutil.process_iter(['pid', 'cmdline']):
        try:
            if any(str(a).lower().endswith('watcher.pyw') for a in (p.info.get('cmdline') or [])):
                out.append(p.info['pid'])
        except (psutil.Error, TypeError):
            pass
    return out


def remove_legacy_watcher(link: str) -> list[str]:
    """移除開機捷徑並結束執行中的監視器（使用者在提示中按「移除」時才呼叫）。回傳做了什麼"""
    import psutil
    done = []
    if link and os.path.isfile(link):
        os.remove(link)
        done.append('removed_link')
    for pid in legacy_watcher_pids():
        try:
            psutil.Process(pid).terminate()
            done.append(f'stopped_{pid}')
        except psutil.Error:
            pass
    return done
