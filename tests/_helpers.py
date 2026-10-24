# -*- coding: utf-8 -*-
"""
測試共用工具。每個測試檔都是可獨立執行的腳本（python tests/core/test_xxx.py），
失敗時以 AssertionError 結束、程序回傳非 0；全部通過時最後印出「OK」。

規則：
- 只使用暫存目錄，不讀寫使用者的真實資料檔（sai2_draw_time.json、daily_quests.json…）
- 預設不連網；需要連網的測試放在 tests/network/，由 run_tests.py --network 執行
- 1.x（Tk 版）不再維護，也不再測試
"""

from __future__ import annotations

import os
import sys
import random
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

_count = 0


def check(cond, msg: str = ''):
    """斷言並計數（結尾以 done() 印出通過的檢查數）"""
    global _count
    assert cond, msg
    _count += 1


def done(name: str = ''):
    print(f'OK {_count} checks' + (f' ({name})' if name else ''))


def tmpdir() -> str:
    return tempfile.mkdtemp(prefix='sai2dc_test_')


def block_tk():
    """讓任何 import tkinter 的動作失敗：用來確認 core/ 不依賴 Tk"""
    for m in ('tkinter', 'tkinter.ttk', 'PIL.ImageTk', '_tkinter'):
        sys.modules[m] = None


def quest_manager(seed: int = 1, path: str | None = None):
    from core.daily_quests import QuestManager
    return QuestManager(path or os.path.join(tmpdir(), 'daily_quests.json'), rng=random.Random(seed))
