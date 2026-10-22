# -*- coding: utf-8 -*-
"""
single_instance.py - 同時只允許一份程式執行（不含 UI）

以具名 Mutex 判斷是否已有一份在執行；取得失敗的第二份應把參數交給第一份後立即結束
（交接通道由介面層負責，例如 Qt 的 QLocalServer，名稱用 channel_name()）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes

ERROR_ALREADY_EXISTS = 183
DEFAULT_NAME = 'SAI2DrawCompanion'

_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
_kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]


def channel_name(name: str = DEFAULT_NAME) -> str:
    """第一份程式接收參數用的本機通道名稱（依 Windows 使用者區分，避免多使用者互相干擾）"""
    import getpass
    return f'{name}-{getpass.getuser()}'


class SingleInstance:
    """with SingleInstance() as inst: if not inst.acquired: 交接參數後結束"""

    def __init__(self, name: str = DEFAULT_NAME):
        # Local\ = 只在目前的登入工作階段內唯一（不同使用者各自可以執行一份）
        self.mutex_name = 'Local\\' + name
        self._handle = None
        self.acquired = False

    def acquire(self) -> bool:
        if self._handle:
            return self.acquired
        handle = _kernel32.CreateMutexW(None, False, self.mutex_name)
        err = ctypes.get_last_error()
        if not handle:
            raise OSError(err, f'CreateMutexW failed: {self.mutex_name}')
        self._handle = handle
        self.acquired = err != ERROR_ALREADY_EXISTS
        return self.acquired

    def release(self):
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None
        self.acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
