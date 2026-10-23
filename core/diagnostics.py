# -*- coding: utf-8 -*-
"""
diagnostics.py - 錯誤記錄與診斷資訊（不含 UI）

打包後的 exe 沒有主控台，未處理的例外原本看不到。install() 之後：
- Python 例外（含 Qt 事件裡的、背景執行緒的）寫進 APP_DIR/drawcompanion2_error.log
- 程式整個當掉（例如原生程式庫崩潰）時，faulthandler 把堆疊寫進同一個檔案
記錄檔超過 MAX_BYTES 時保留後半段。

export_bundle() 產生一個 zip 方便回報問題：版本、系統、設定（不含金鑰與本機路徑）、錯誤記錄。
"""

from __future__ import annotations

import faulthandler
import json
import os
import platform
import sys
import threading
import traceback
import zipfile
from datetime import datetime

from core.version import APP_VERSION

LOG_NAME = 'drawcompanion2_error.log'
MAX_BYTES = 512 * 1024

_state: dict = {}


def log_path(app_dir: str) -> str:
    return os.path.join(app_dir, LOG_NAME)


def has_log(app_dir: str) -> bool:
    """有沒有內容（faulthandler 啟動時就會先建立空檔）"""
    try:
        return os.path.getsize(log_path(app_dir)) > 0
    except OSError:
        return False


def _trim(path: str):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            with open(path, 'rb') as f:
                f.seek(-MAX_BYTES // 2, os.SEEK_END)
                tail = f.read()
            with open(path, 'wb') as f:
                f.write(b'...(older entries removed)\n' + tail)
    except OSError:
        pass


def write(app_dir: str, title: str, text: str = ''):
    """寫一筆記錄（失敗時安靜略過，記錄本身不能讓程式出錯）"""
    path = log_path(app_dir)
    try:
        _trim(path)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.now().isoformat(timespec="seconds")}] {APP_VERSION} {title}\n{text.rstrip()}\n\n')
    except OSError:
        pass


def _format(exc_type, exc, tb) -> str:
    return ''.join(traceback.format_exception(exc_type, exc, tb))


def install(app_dir: str):
    """接管 sys.excepthook / threading.excepthook，並開啟 faulthandler。可重複呼叫（換資料夾時用新的）"""
    uninstall()
    prev_hook, prev_thread_hook = sys.excepthook, threading.excepthook

    def hook(exc_type, exc, tb):
        write(app_dir, f'Unhandled {exc_type.__name__}', _format(exc_type, exc, tb))
        if sys.stderr is not None:                 # 原始碼執行時照常印出
            prev_hook(exc_type, exc, tb)

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else '?'
        write(app_dir, f'Unhandled {args.exc_type.__name__} in thread {name}',
              _format(args.exc_type, args.exc_value, args.exc_traceback))
        if sys.stderr is not None:
            prev_thread_hook(args)

    sys.excepthook, threading.excepthook = hook, thread_hook
    fault = None
    try:
        fault = open(log_path(app_dir), 'a', encoding='utf-8')
        faulthandler.enable(fault)
    except (OSError, RuntimeError):
        fault = None
    _state.update(prev=prev_hook, prev_thread=prev_thread_hook, fault=fault, app_dir=app_dir)


def uninstall():
    if not _state:
        return
    sys.excepthook, threading.excepthook = _state['prev'], _state['prev_thread']
    if _state.get('fault') is not None:
        try:
            faulthandler.disable()
            _state['fault'].close()
        except (OSError, RuntimeError):
            pass
    if not has_log(_state['app_dir']):           # 正常結束且沒有錯誤：不留下空的記錄檔
        try:
            os.remove(log_path(_state['app_dir']))
        except OSError:
            pass
    _state.clear()


def system_info() -> dict:
    info = {'app_version': APP_VERSION, 'python': sys.version.split()[0], 'frozen': bool(getattr(sys, 'frozen', False)),
            'os': platform.platform(), 'machine': platform.machine()}
    try:
        import PySide6
        info['pyside6'] = PySide6.__version__
    except Exception:                               # noqa: BLE001 - 只是附加資訊
        pass
    return info


def export_bundle(settings, path: str, extra: dict | None = None) -> str:
    """診斷資訊 zip：info.json（版本、系統、extra）、settings.json（不含金鑰與本機路徑）、錯誤記錄"""
    from core import backup
    info = dict(system_info(), exported_at=datetime.now().isoformat(timespec='seconds'), **(extra or {}))
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('info.json', json.dumps(info, ensure_ascii=False, indent=2))
        z.writestr('settings.json', json.dumps(backup.shareable(settings.data, include_secrets=False),
                                               ensure_ascii=False, indent=2))
        if has_log(settings.app_dir):
            z.write(log_path(settings.app_dir), LOG_NAME)
    return path
