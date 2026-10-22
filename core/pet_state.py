# -*- coding: utf-8 -*-
"""
pet_state.py - 決定寵物現在要顯示哪個狀態、何時說話（不含 UI）

優先順序：一次性動畫（歡呼 / 提醒）＞ 1.x 執行中（睡覺）＞ 未連結 SAI2 ＞ 睡覺（請假日、夜間）＞ 休息 ＞ 一起畫 ＞ 待命
連續動筆達設定分鐘數時提醒休息一次；停筆超過 BREAK_RESET_SEC 才重新計算連續時間。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

BREAK_RESET_SEC = 5 * 60
REST_SHOW_SEC = 30
ONE_SHOT_SEC = {'cheer': 2.5, 'remind': 2.0}


@dataclass
class PetInputs:
    sai2_running: bool
    drawing: bool
    rest_day: bool = False
    legacy_running: bool = False


@dataclass
class Bubble:
    key: str
    text: str
    important: bool = True


class PetBrain:
    def __init__(self, rest_minutes: float = 50, night_sleep: bool = False, clock=time.monotonic):
        self.rest_minutes = rest_minutes
        self.night_sleep = night_sleep
        self._clock = clock
        self._override: tuple[str, float] | None = None
        self._streak_start: float | None = None
        self._last_draw: float | None = None
        self._rest_notified = False
        self._rest_until = 0.0
        self.state = 'offline'

    def trigger(self, state: str, seconds: float | None = None):
        """一次性動畫（打卡歡呼、未存檔提醒…）"""
        self._override = (state, self._clock() + (seconds or ONE_SHOT_SEC.get(state, 2.0)))

    def continuous_draw_seconds(self) -> float:
        if self._streak_start is None or self._last_draw is None:
            return 0.0
        return self._last_draw - self._streak_start

    def update(self, inp: PetInputs, now: datetime | None = None) -> tuple[str, list[Bubble]]:
        t = self._clock()
        bubbles: list[Bubble] = []
        if inp.drawing:
            if self._last_draw is None or t - self._last_draw > BREAK_RESET_SEC:
                self._streak_start = t
                self._rest_notified = False
            self._last_draw = t
        elif self._last_draw is not None and t - self._last_draw > BREAK_RESET_SEC:
            self._streak_start = None
            self._rest_notified = False

        if (self.rest_minutes and not self._rest_notified
                and self.continuous_draw_seconds() >= self.rest_minutes * 60):
            self._rest_notified = True
            self._rest_until = t + REST_SHOW_SEC
            bubbles.append(Bubble('rest', f'已經連續畫了 {int(self.rest_minutes)} 分鐘，起來喝口水、動一動吧'))

        hour = (now or datetime.now()).hour
        if self._override and t < self._override[1]:
            state = self._override[0]
        elif inp.legacy_running:
            state = 'sleep'                 # 1.x 執行中、2.0 暫停記錄：不知道 SAI2 的狀態
        elif not inp.sai2_running:
            state = 'offline'
        elif inp.rest_day or (self.night_sleep and (hour >= 23 or hour < 6)):
            state = 'sleep'
        elif t < self._rest_until:
            state = 'rest'
        elif inp.drawing:
            state = 'drawing'
        else:
            state = 'idle'
        if self._override and t >= self._override[1]:
            self._override = None
        self.state = state
        return state, bubbles
