# -*- coding: utf-8 -*-
"""
unsaved.py - 未存檔的畫布：暫時的紀錄名稱，以及「存檔的那一刻」的判斷（不含 UI）

SAI2 對未存檔的畫布只顯示「新增畫布1」這類名稱，每次重開 SAI2 都從 1 重新編號。
未存檔時先記在暫時的名稱底下（動筆時間、縮時錄影照常），存檔時再併到正式作品：

  暫時名稱：「未存檔 _ 1028-1750 _ 新增畫布1」（中間是這次 SAI2 開始執行的時間；沒有副檔名，不會出現在作品清單）

存檔的判斷（2026-10 實機觀察）：
  - 存檔／另存新檔時，SAI2 先跳出存檔視窗（主視窗被停用），按下儲存後標題直接從「新增畫布1 (*)」變成「暫存 / 新增畫布1.sai2」
  - 切換分頁只會換標題，不會有對話視窗
  - 開啟檔案也有對話視窗，但會多一個文件視窗；存檔不會
  所以：「未存檔 X 時出現過對話視窗」→ 標題直接變成這次執行還沒出現過的已存檔 Y → 文件視窗沒有變多 ＝ X 存成了 Y
  文件視窗數量取不到時不猜，交給使用者確認。
"""

from __future__ import annotations

from datetime import datetime

PREFIX = '未存檔'
SEP = ' _ '
VIDEO_FOLDER = '未存檔的畫布'         # 最後都沒存檔的縮時錄影放這裡


def session_tag(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime('%m%d-%H%M')


def temp_key(name: str, session: str) -> str:
    return f'{PREFIX}{SEP}{session}{SEP}{name}'


def is_temp(key: str | None) -> bool:
    return bool(key) and key.startswith(PREFIX + SEP)


def temp_name(key: str) -> str:
    """暫時名稱裡的畫布名稱（「新增畫布1」）"""
    return key.split(SEP)[-1] if is_temp(key) else key


class SaveWatcher:
    """依序餵入每次掃描的結果，回報存檔事件：
    ('adopt', 暫時名稱, 正式名稱)   未存檔的畫布存成了檔案 → 時間、錄影、縮圖併過去
    ('ask', 暫時名稱, 正式名稱)     看起來是存檔，但無法確定 → 問使用者
    ('saveas', 舊檔名, 新檔名)      已存檔的作品另存新檔 → 錄影接著錄（時間照舊分開，可在作品頁合併）
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """SAI2 重新啟動時呼叫"""
        self.prev: str | None = None
        self.dialog_seen = False
        self.docs_before: int | None = None
        self.seen: set[str] = set()          # 這次執行中出現過的已存檔檔名

    def observe(self, key: str | None, dialog: bool, docs=lambda: None):
        """key：目前的紀錄名稱（未存檔為暫時名稱）；dialog：SAI2 有對話視窗開著；docs()：目前的文件視窗數量"""
        event = None
        if dialog and self.prev and not self.dialog_seen:
            self.dialog_seen = True
            self.docs_before = docs()
        if key is not None and key != self.prev:
            if self.prev and self.dialog_seen and not is_temp(key) and key not in self.seen:
                after = docs()
                if after is not None and self.docs_before is not None and after > self.docs_before:
                    event = None                     # 多了一個文件：是開啟檔案，不是存檔
                elif is_temp(self.prev):
                    event = ('adopt' if after is not None and self.docs_before is not None else 'ask', self.prev, key)
                else:
                    event = ('saveas', self.prev, key)
            self.dialog_seen = False
            self.docs_before = None
            self.prev = key
        if key is not None and not is_temp(key):
            self.seen.add(key)
        return event
