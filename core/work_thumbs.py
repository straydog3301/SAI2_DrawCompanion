# -*- coding: utf-8 -*-
"""
work_thumbs.py - 作品縮圖（不含 UI）

關檔之後畫布已經不在畫面上，擷取不到，所以改在「關檔之前、畫面能代表進度」的時機擷取：
- 存檔：SAI2 標題的修改記號（*）消失
- 停筆：畫了一段時間後停下來 PAUSE_SEC 秒
- 長時間連續作畫：每 PERIODIC_SEC 秒的動筆補一張
- 還沒有縮圖的檔案：開啟 FIRST_SEC 秒後先擷取一張（只開來看、沒有畫也有預覽）
同一個檔案至少間隔 MIN_GAP_SEC，最新的一張就是關檔前的樣子。

縮圖存在 APP_DIR/work_thumbs/<key 的雜湊>.jpg（紀錄的 key 含路徑，不能直接當檔名）。
"""

from __future__ import annotations

import hashlib
import os

THUMBS_DIR = 'work_thumbs'
MAX_SIDE = 480
MIN_GAP_SEC = 60.0          # 同一個檔案兩張縮圖的最短間隔
PAUSE_SEC = 20.0            # 停筆多久算「停下來」
MIN_DRAW_SEC = 60.0         # 上一張之後至少畫了這麼久，停筆時才補一張
PERIODIC_SEC = 600.0        # 一直在畫：每畫這麼久補一張
FIRST_SEC = 5.0             # 沒有縮圖的檔案：開啟多久後先擷取一張（等 SAI2 畫面穩定）


def thumbs_dir(app_dir: str) -> str:
    return os.path.join(app_dir, THUMBS_DIR)


def path_for(app_dir: str, key: str) -> str:
    h = hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]
    return os.path.join(thumbs_dir(app_dir), f'{h}.jpg')


def find(app_dir: str, key: str, aliases: list[str] | tuple = ()) -> str | None:
    """作品的縮圖路徑（合併過的舊名稱也找）；沒有時回傳 None"""
    for k in (key, *aliases):
        p = path_for(app_dir, k)
        if os.path.isfile(p):
            return p
    return None


def looks_blank(img) -> bool:
    """幾乎只有一種顏色（例如 SAI2 縮到最小時擷取到的空白畫面）：不要拿來蓋掉原本的縮圖"""
    small = img.convert('L').resize((32, 32))
    lo, hi = small.getextrema()
    return hi - lo < 6


def save(app_dir: str, key: str, img) -> str:
    """存成 JPEG（先寫暫存檔再取代，畫面讀到的不會是寫到一半的檔案）"""
    from PIL import Image
    p = path_for(app_dir, key)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    thumb = img.convert('RGB')
    thumb.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    tmp = p + '.tmp'
    thumb.save(tmp, format='JPEG', quality=85)
    os.replace(tmp, p)
    return p


def delete(app_dir: str, key: str):
    try:
        os.remove(path_for(app_dir, key))
    except OSError:
        pass


def move(app_dir: str, old: str, new: str):
    """合併紀錄時：新名稱還沒有縮圖就沿用舊的"""
    src, dst = path_for(app_dir, old), path_for(app_dir, new)
    if os.path.isfile(src) and not os.path.isfile(dst):
        try:
            os.replace(src, dst)
        except OSError:
            pass


def title_modified(raw_title: str | None) -> bool | None:
    """SAI2 標題是否帶修改記號；沒有標題回傳 None"""
    if not raw_title:
        return None
    t = raw_title.strip()
    return '(*)' in t or t.startswith(('*', '＊')) or ' * ' in t


class ThumbPolicy:
    """每秒餵入目前狀態，回傳這一刻要擷取縮圖的檔案 key（不需要時 None）"""

    def __init__(self):
        self._file = None
        self._modified = None
        self._last_shot: dict[str, float] = {}
        self._drawn_since_shot = 0.0
        self._idle = 0.0
        self._periodic = 0.0
        self._opened = 0.0

    def update(self, now: float, current_file: str | None, drawing: bool, modified: bool | None,
               dt: float = 1.0, missing: bool = False) -> str | None:
        """missing：這個檔案還沒有縮圖"""
        if current_file != self._file:                 # 換檔：重新計算
            self._file, self._modified = current_file, modified
            self._drawn_since_shot = self._idle = self._periodic = self._opened = 0.0
            return None
        if not current_file:
            return None
        self._opened += dt
        saved = self._modified is True and modified is False
        self._modified = modified
        if drawing:
            self._drawn_since_shot += dt
            self._periodic += dt
            self._idle = 0.0
        else:
            self._idle += dt
        reason = None
        if missing and self._opened >= FIRST_SEC:
            reason = 'first'
        elif saved and self._drawn_since_shot > 0:
            reason = 'saved'
        elif not drawing and self._idle >= PAUSE_SEC and self._drawn_since_shot >= MIN_DRAW_SEC:
            reason = 'pause'
        elif self._periodic >= PERIODIC_SEC:
            reason = 'periodic'
        if reason is None or now - self._last_shot.get(current_file, -1e9) < MIN_GAP_SEC:
            return None
        self._last_shot[current_file] = now
        self._drawn_since_shot = self._periodic = 0.0
        return current_file

    def force(self, key: str, now: float):
        """手動擷取後也算一次（避免馬上又自動擷取）"""
        self._last_shot[key] = now
        if key == self._file:
            self._drawn_since_shot = self._periodic = 0.0
