# -*- coding: utf-8 -*-
"""
測試共用工具。每個測試檔都是可獨立執行的腳本（python tests/core/test_xxx.py），
失敗時以 AssertionError 結束、程序回傳非 0；全部通過時最後印出「OK」。

規則：
- 只使用暫存目錄，不讀寫使用者的真實資料檔（sai2_draw_time.json、daily_quests.json…）
- 預設不連網；需要連網的測試放在 tests/network/，由 run_tests.py --network 執行
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


# ─── 介面測試用 ───────────────────────────────────────────────────────────
def headless_main(tmp: str | None = None, language: str | None = None):
    """匯入 main 並把所有資料路徑、全域快捷鍵、錄影執行緒改成測試用，回傳 (main 模組, 暫存目錄)。
    會開出真正的 Tk 視窗（需要桌面環境），但不碰使用者資料、不註冊全域快捷鍵。"""
    tmp = tmp or tmpdir()
    import main as M
    sys.excepthook = sys.__excepthook__          # 主程式的例外對話框會卡住自動測試
    M._SETTINGS_PATH = os.path.join(tmp, 'settings.json')
    M._DEFAULT_DATA = os.path.join(tmp, 'draw_time.json')
    M._QUESTS_PATH = os.path.join(tmp, 'daily_quests.json')
    M._STUDY_CACHE_DIR = os.path.join(tmp, 'study_refs_cache')
    M._SNAPSHOT_DIR = os.path.join(tmp, 'checkin_snapshots')
    M._save_settings = lambda s: None
    M.App._setup_system_hotkey = lambda self: None
    M.TimelapseRecorder.start = lambda self: None
    if language:
        with open(M._SETTINGS_PATH, 'w', encoding='utf-8') as f:
            f.write('{"language": "%s"}' % language)
    return M, tmp


def make_app(M):
    """建立完整主程式（測試結束請呼叫 close_app）"""
    import tkinter as tk
    root = tk.Tk()
    app = M.App(root)
    root.update()
    return root, app


def close_app(root, app):
    app._closing = True
    app.tracker.stop()
    try:
        for job in root.tk.call('after', 'info'):
            root.after_cancel(job)
    except Exception:
        pass
    root.destroy()


def run_mainloop(root, ms: int = 300):
    """讓 after() 排程與背景執行緒的回呼有機會執行"""
    root.after(ms, root.quit)
    root.mainloop()
    root.update()
