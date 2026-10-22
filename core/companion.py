# -*- coding: utf-8 -*-
"""
companion.py - 2.0 的常駐服務：繪圖追蹤、每日任務進度、與 1.x 互斥（不含 UI）

介面每秒呼叫 tick()，取得目前狀態與這一秒發生的事件。
1.x 與 2.0 讀寫同一批資料檔（sai2_draw_time.json、daily_quests.json），同時記錄會重複計時或互相覆蓋，
所以偵測到 1.x 正在執行時 2.0 暫停記錄；1.x 結束後重新讀取資料檔再繼續。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime

from core.daily_quests import QuestManager
from core.file_paths import display_name
from core.tracker import DrawTracker

LEGACY_CHECK_SEC = 5.0
EXE_REMEMBER_SEC = 30.0
LEGACY_EXE = 'sai2_drawcompanion.exe'


def legacy_running(my_pid: int | None = None) -> bool:
    """1.x 是否在執行：打包版 SAI2_DrawCompanion.exe，或以 Python 執行的 1.x main.py"""
    import psutil
    my_pid = my_pid or os.getpid()
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if p.info['pid'] == my_pid:
                continue
            name = (p.info.get('name') or '').lower()
            if name == LEGACY_EXE:
                return True
            if name.startswith('python'):
                args = [str(a) for a in (p.info.get('cmdline') or [])]
                for a in args:
                    if os.path.basename(a).lower() == 'main.py' and \
                            os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(a)), 'core', 'tracker.py')):
                        return True
        except (psutil.Error, TypeError, OSError):
            pass
    return False


@dataclass
class Status:
    tracking: bool = False            # False = 1.x 執行中而暫停
    sai2_running: bool = False
    drawing: bool = False
    current_file: str | None = None
    unsaved_file: str | None = None   # SAI2 開著未存檔的新畫布（不會被記錄）
    session_draw: float = 0.0
    today_draw: float = 0.0
    budget_minutes: float = 60.0
    streak: int = 0
    rest_day: bool = False


@dataclass
class TickResult:
    status: Status
    ready: list = field(default_factory=list)       # 剛達標的任務
    events: list = field(default_factory=list)      # legacy_paused / legacy_resumed / new_day / exe_found


class CompanionService:
    def __init__(self, settings, tracker_factory=DrawTracker, quests_factory=QuestManager,
                 legacy_check=legacy_running, exe_finder=None, clock=time.monotonic):
        self.settings = settings
        self._tracker_factory = tracker_factory
        self._quests_factory = quests_factory
        self._legacy_check = legacy_check
        self._exe_finder = exe_finder
        self._clock = clock
        self.tracker = None
        self.quests: QuestManager | None = None
        self.paused = False
        self._counter = None
        self._last_legacy = -1e9
        self._last_exe = -1e9
        self._day = None

    # ── 啟停 ──
    def start(self):
        self.paused = bool(self._legacy_check())
        self._last_legacy = self._clock()
        self.quests = self._quests_factory(self.settings.quests_path)
        if not self.paused:
            self._start_tracking()

    def stop(self):
        self._stop_tracking()

    def _start_tracking(self):
        self.quests = self._quests_factory(self.settings.quests_path)    # 重新讀取（1.x 可能剛改過）
        self.quests.ensure_today()
        self._day = self.quests.data.get('current_day')
        self.tracker = self._tracker_factory(
            data_path=self.settings.data_path,
            idle_timeout=float(self.settings.get('idle_timeout', 10.0)),
            track_unsaved=bool(self.settings.get('track_unsaved', False)))
        self.tracker.start()
        self._counter = None

    def _stop_tracking(self):
        if self.tracker is not None:
            self.tracker.stop()
            self.tracker = None
        if self.quests is not None and not self.paused:
            self.quests.save(force=True)

    # ── 每秒 ──
    def tick(self, now: datetime | None = None) -> TickResult:
        t = self._clock()
        res = TickResult(Status())
        if t - self._last_legacy >= LEGACY_CHECK_SEC:
            self._last_legacy = t
            legacy = bool(self._legacy_check())
            if legacy and not self.paused:
                self._stop_tracking()
                self.paused = True
                res.events.append('legacy_paused')
            elif not legacy and self.paused:
                self.paused = False
                self._start_tracking()
                res.events.append('legacy_resumed')

        st = res.status
        st.tracking = not self.paused
        if self.quests is not None:
            st.budget_minutes = float(self.quests.settings.get('budget_minutes', 60))
            st.streak = self.quests.streak(now)
            st.rest_day = self.quests.is_rest(self.quests.day_key(now))
        if self.paused or self.tracker is None:
            return res

        state = self.tracker.get_state()
        counter = self.tracker.get_draw_counter()
        last, self._counter = self._counter, counter
        delta = 0.0 if last is None or counter < last else counter - last
        st.sai2_running = bool(state.get('sai2_running'))
        st.current_file = state.get('current_file')
        raw = state.get('raw_current_file')
        st.unsaved_file = raw if raw and not st.current_file and st.sai2_running else None
        st.session_draw = float(state.get('session_draw') or 0.0)
        st.drawing = delta > 0
        st.today_draw = self.tracker.today_draw_seconds()

        res.ready = self.quests.tick(delta, now=now, current_file=st.current_file if delta > 0 else None)
        day = self.quests.data.get('current_day')
        if day != self._day:
            self._day = day
            res.events.append('new_day')
        self.quests.save(force=bool(res.ready))

        if st.sai2_running and self._exe_finder and t - self._last_exe >= EXE_REMEMBER_SEC:
            self._last_exe = t
            exe = self._exe_finder()
            if exe and exe != self.settings.get('sai2_exe'):
                self.settings.set('sai2_exe', exe)
                self.settings.save()
                res.events.append('exe_found')
        return res

    # ── 最近開啟 ──
    def recent_files(self, n: int = 4) -> list[dict]:
        """[{key, name, last_seen, draw_seconds}]，依最後使用時間排序"""
        if self.tracker is not None:
            files = self.tracker.get_state().get('files', {})
        else:
            import json
            try:
                with open(self.settings.data_path, encoding='utf-8') as f:
                    files = json.load(f).get('files', {})
            except (OSError, ValueError):
                files = {}
        rows = [{'key': k, 'name': display_name(k), 'last_seen': v.get('last_seen', ''),
                 'draw_seconds': float(v.get('draw_seconds', 0.0))}
                for k, v in files.items() if v.get('last_seen')]
        rows.sort(key=lambda r: r['last_seen'], reverse=True)
        return rows[:n]

    def week_draw(self, today: datetime | None = None) -> list[tuple[str, float]]:
        """本週（週一起）每日動筆秒數 [(日期, 秒)]；今天含尚未寫入的部分"""
        from datetime import timedelta
        today = today or datetime.now()
        hist = self.tracker.daily_history() if self.tracker is not None else {}
        monday = today - timedelta(days=today.weekday())
        out = []
        for i in range(7):
            d = (monday + timedelta(days=i)).strftime('%Y-%m-%d')
            sec = hist.get(d, 0.0)
            if d == today.strftime('%Y-%m-%d') and self.tracker is not None:
                sec = self.tracker.today_draw_seconds()
            out.append((d, sec))
        return out

    def study_task_for_path(self, skill: str) -> str | None:
        """控制中心「練這一課」：今天已有該路徑的研究任務就沿用，沒有就加入一個"""
        q = self.quests
        for t in q.today_tasks():
            if t['mode'] == 'study' and t['params'].get('path') == skill and t['status'] in ('active', 'ready'):
                return t['uid']
        tpl = next((x for x in q.data['templates'] if x['mode'] == 'study' and x.get('params', {}).get('path') == skill), None)
        if not tpl:
            return None
        task = q.add_today(tpl['id'])
        q.save(force=True)
        return task['uid'] if task else None

    # ── 任務 ──
    def today_tasks(self) -> list[dict]:
        return self.quests.today_tasks() if self.quests else []

    def go(self, uid: str) -> tuple[str, str]:
        """按下任務的「開始 / 繼續」。回傳 (動作, 訊息)：
        started（創作時長，直接在 SAI2 畫）/ open_study / open_sketch（開參考小窗）/ need_count / not_yet"""
        t = self.quests.task(uid) if self.quests else None
        if not t or self.paused:
            return 'not_yet', '1.x 正在執行，2.0 暫停記錄中' if self.paused else '找不到任務'
        mode = t['mode']
        if mode == 'draw_time':
            return 'started', f'「{t["name"]}」：在 SAI2 動筆的時間會自動累計'
        if mode == 'study':
            self.quests.start_study(uid)
            self.quests.save(force=True)
            return 'open_study', f'開始「{t["name"]}」研究計時：在 SAI2 動筆的時間會計入任務'
        if mode in ('drill', 'thumbnail'):
            return 'need_count', f'「{t["name"]}」完成了幾{"張" if mode == "thumbnail" else "個"}？'
        if mode == 'sketch':
            return 'open_sketch', f'開始「{t["name"]}」：倒數自然歸零才算一張'
        return 'not_yet', '這種任務還不支援'

    def record_sketch(self, topic: str, seconds: float, quest_uid: str | None, interval: int | None) -> list:
        """完成一張有效速寫（1.x 執行中時不記錄，避免兩邊同時寫入）"""
        if self.paused or self.quests is None:
            return []
        ready = self.quests.record_sketch(topic, seconds, quest_uid, interval)
        self.quests.save(force=bool(ready))
        return ready

    def save_checkin_snapshot(self, uid: str, img) -> str | None:
        """打卡快照存到 checkin_snapshots/<日期>/<uid>.jpg（與 1.x 相同位置）"""
        if img is None or not self.quests.settings.get('snapshot_on_checkin', True):
            return None
        from core.snapshots import save_snapshot
        try:
            path = save_snapshot(img, os.path.join(self.settings.app_dir, 'checkin_snapshots',
                                                   self.quests.data['current_day']), uid)
        except OSError:
            return None
        self.quests.set_task_snapshot(uid, path)
        self.quests.save(force=True)
        return path

    def add_count(self, uid: str, n: int) -> list:
        ready = self.quests.add_count(uid, n)
        self.quests.save(force=True)
        return ready

    def check_in(self, uid: str, note: str = '', rating: int | None = None, self_report: bool = False) -> str | None:
        err = self.quests.check_in(uid, note, self_report=self_report, rating=rating)
        if not err:
            self.quests.save(force=True)
        return err

    def reroll(self, uid: str) -> str | None:
        new = self.quests.reroll(uid)
        self.quests.save(force=True)
        return new
