# -*- coding: utf-8 -*-
"""
companion.py - 2.0 的常駐服務：繪圖追蹤、每日任務進度、與 1.x 互斥（不含 UI）

介面每秒呼叫 tick()，取得目前狀態與這一秒發生的事件。
1.x 與 2.0 讀寫同一批資料檔（sai2_draw_time.json、daily_quests.json），同時記錄會重複計時或互相覆蓋，
所以偵測到 1.x 正在執行時 2.0 暫停記錄；1.x 結束後重新讀取資料檔再繼續。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from core.daily_quests import QuestManager
from core.file_paths import display_name
from core.tracker import DrawTracker, extract_filename

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
    recording: bool = False          # 縮時錄影開著
    rec_file: str | None = None      # 正在錄的檔案
    rec_frames: int = 0
    exporting: int = 0               # 合成中的影片數


@dataclass
class TickResult:
    status: Status
    ready: list = field(default_factory=list)       # 剛達標的任務
    events: list = field(default_factory=list)      # legacy_paused / legacy_resumed / new_day / exe_found
    export: list = field(default_factory=list)      # 影片合成進度 [(百分比, 訊息)]
    thumbs: list = field(default_factory=list)      # 剛存好縮圖的作品 key


class CompanionService:
    def __init__(self, settings, tracker_factory=DrawTracker, quests_factory=QuestManager,
                 legacy_check=legacy_running, exe_finder=None, clock=time.monotonic, recorder_factory=None,
                 thumb_capture=None):
        from core.work_thumbs import ThumbPolicy
        self.settings = settings
        self._thumb_capture = thumb_capture            # () -> PIL.Image | None；None = 擷取 SAI2 畫布
        self.thumbs = ThumbPolicy()
        self._thumb_busy = False
        self._thumb_done: list[str] = []
        self._last_tick = None
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
        self._recorder_factory = recorder_factory
        self.recorder = None
        self._old_recorders: list = []      # 停止後仍在合成影片的錄影器
        self._rec_lock = threading.Lock()
        self._rec_export: list = []
        self._rec_frames = 0

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
        # 重新讀取（1.x 可能剛改過）。沿用同一個物件：主視窗、參考小窗手上的任務物件才不會變成過期的那份，
        # 否則在那些畫面的修改（例如重新啟用每日任務）會被這裡的舊資料覆蓋
        if self.quests is not None and hasattr(self.quests, 'reload'):
            self.quests.reload()
        else:
            self.quests = self._quests_factory(self.settings.quests_path)
        self.quests.ensure_today()
        self._day = self.quests.data.get('current_day')
        self.tracker = self._tracker_factory(
            data_path=self.settings.data_path,
            idle_timeout=float(self.settings.get('idle_timeout', 10.0)),
            track_unsaved=bool(self.settings.get('track_unsaved', False)))
        self.tracker.start()
        self._counter = None
        self._start_recorder()

    def _stop_tracking(self):
        self._stop_recorder()
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

        self._sync_recorder(state, st)
        with self._rec_lock:
            res.export, self._rec_export = self._rec_export, []
            res.thumbs, self._thumb_done = self._thumb_done, []
        dt = 1.0 if self._last_tick is None else max(0.0, min(5.0, t - self._last_tick))
        self._last_tick = t
        if self.settings.get('works.thumbnails', True):
            from core import work_thumbs
            cur = st.current_file
            missing = bool(cur) and not os.path.isfile(work_thumbs.path_for(self.settings.app_dir, cur))
            key = self.thumbs.update(t, cur, st.drawing, work_thumbs.title_modified(state.get('raw_title')),
                                     dt, missing)
            if key:
                self.capture_thumb(key)

        if st.sai2_running and self._exe_finder and t - self._last_exe >= EXE_REMEMBER_SEC:
            self._last_exe = t
            exe = self._exe_finder()
            if exe and exe != self.settings.get('sai2_exe'):
                self.settings.set('sai2_exe', exe)
                self.settings.save()
                res.events.append('exe_found')
        return res

    def draw_counter(self) -> float | None:
        """累計動筆秒數（速寫「下筆才倒數」用，取兩次的差）；1.x 執行中或沒有追蹤器時 None"""
        if self.paused or self.tracker is None:
            return None
        return float(self.tracker.get_draw_counter())

    # ── 作品縮圖 ──
    def capture_thumb(self, key: str, manual: bool = False) -> bool:
        """在背景擷取 SAI2 畫布當作品縮圖；擷取前後都確認畫面上還是這個檔案。回傳是否開始擷取"""
        if self._thumb_busy or self.tracker is None or self.paused:
            return False
        if manual:
            self.thumbs.force(key, self._clock())
        self._thumb_busy = True
        capture = self._thumb_capture
        if capture is None:
            from core.snapshots import capture_sai2_canvas as capture
        tracker, app_dir = self.tracker, self.settings.app_dir

        def run():
            from core import work_thumbs
            try:
                if tracker.get_state().get('current_file') != key:
                    return
                img = capture()
                if img is None or work_thumbs.looks_blank(img) or tracker.get_state().get('current_file') != key:
                    return
                work_thumbs.save(app_dir, key, img)
                with self._rec_lock:
                    self._thumb_done.append(key)
            except Exception as e:                  # noqa: BLE001 - 擷取失敗不影響記錄
                print(f'[thumbs] capture failed: {e}')
            finally:
                self._thumb_busy = False
        threading.Thread(target=run, daemon=True, name='work-thumb').start()
        return True

    def thumb_of(self, key: str) -> str | None:
        from core import work_thumbs
        return work_thumbs.find(self.settings.app_dir, key, self.aliases_of(key))

    def delete_work(self, key: str):
        """刪除作品的計時紀錄與縮圖（不刪畫作檔案）"""
        from core import work_thumbs
        self.tracker.delete_file(key)
        work_thumbs.delete(self.settings.app_dir, key)

    def merge_work(self, key: str, target: str):
        """把 key 合併到 target（之後 key 的時間算進 target）；target 沒有縮圖時沿用 key 的"""
        from core import work_thumbs
        self.tracker.add_alias(key, target)
        work_thumbs.move(self.settings.app_dir, key, target)

    # ── 縮時錄影 ──
    def _start_recorder(self):
        if self._recorder_factory is None:
            from core.timelapse import TimelapseRecorder
            factory = TimelapseRecorder
        else:
            factory = self._recorder_factory
        cfg = self.settings.get('timelapse', {}) or {}
        r = factory(output_dir=self.settings.videos_dir, fps=int(cfg.get('fps', 30)))
        self.recorder = r
        self.apply_recorder_settings()
        r.needs_thumbnail = False

        def matcher(title):
            name = extract_filename(title or '')
            return self.tracker.resolve_alias(name) if name and self.tracker is not None else None
        r.file_matcher = matcher
        r.on_frame_captured = lambda n, _thumb, _msg: setattr(self, '_rec_frames', n)
        r.on_export_progress = self._on_export
        r.start()

    def _on_export(self, pct, msg):
        with self._rec_lock:
            self._rec_export.append((int(pct), str(msg)))

    def apply_recorder_settings(self):
        r = self.recorder
        if r is None:
            return
        cfg = self.settings.get('timelapse', {}) or {}
        r.output_dir = self.settings.videos_dir
        r.fps = int(cfg.get('fps', 30))
        r.multiplier = int(cfg.get('multiplier', 5))
        r.target_mode = cfg.get('target', 'canvas')
        r.quality_preset = cfg.get('quality', 'standard')
        r.idle_timeout = float(self.settings.get('idle_timeout', 10.0))
        r.enabled = bool(cfg.get('enabled', False))

    def _stop_recorder(self):
        if self.recorder is not None:
            self.recorder.stop()               # 停止時會把正在錄的檔案送去合成
            self._old_recorders.append(self.recorder)
            self.recorder = None

    def _sync_recorder(self, state: dict, st):
        """與 1.x 相同：開始錄某個檔案後鎖定它，直到所有檔案關閉才停止並合成"""
        r, tr = self.recorder, self.tracker
        if r is None:
            return
        cur = state.get('current_file')
        if r.enabled:
            if tr.locked_file is None and cur is not None:
                tr.locked_file = tr.resolve_alias(cur)
        else:
            tr.locked_file = None
        if r.enabled and r.active_file is not None:
            if cur is None:
                r.switch_file(None)
        else:
            r.switch_file(cur)
        st.recording = bool(r.enabled)
        st.rec_file = r.active_file
        st.rec_frames = r.frame_count if r.active_file else 0
        st.exporting = self.exporting_count()

    def set_recording(self, on: bool):
        self.settings.set('timelapse.enabled', bool(on))
        self.settings.save()
        if self.recorder is not None:
            self.recorder.enabled = bool(on)
            if not on:
                if self.tracker is not None:
                    self.tracker.locked_file = None
                self.recorder.switch_file(None)

    def exporting_count(self) -> int:
        n = 0
        for r in [self.recorder] + self._old_recorders:
            if r is not None:
                n += sum(1 for t in list(r.export_threads) if t.is_alive())
        self._old_recorders = [r for r in self._old_recorders if any(t.is_alive() for t in list(r.export_threads))]
        return n

    def recording_info(self) -> dict:
        r = self.recorder
        if r is None:
            return {'available': False, 'enabled': bool(self.settings.get('timelapse.enabled')), 'active_file': None,
                    'frames': 0, 'video_seconds': 0.0, 'exporting': self.exporting_count()}
        dur = float(getattr(r, 'total_recorded_duration', 0.0) or 0.0)
        mult = max(1, int(r.multiplier or 1))
        return {'available': True, 'enabled': bool(r.enabled), 'active_file': r.active_file,
                'frames': r.frame_count if r.active_file else 0, 'video_seconds': dur / mult,
                'exporting': self.exporting_count()}

    # ── 作品與統計（1.x 執行中時唯讀資料檔） ──
    def _persisted(self) -> dict:
        import json
        try:
            with open(self.settings.data_path, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def all_files(self) -> dict:
        if self.tracker is not None:
            return self.tracker.get_state().get('files', {})
        return self._persisted().get('files', {})

    def daily_history(self) -> dict:
        if self.tracker is not None:
            hist = self.tracker.daily_history()
            hist[datetime.now().strftime('%Y-%m-%d')] = self.tracker.today_draw_seconds()
            return hist
        return self._persisted().get('daily_history', {})

    def aliases_of(self, key: str) -> list[str]:
        if self.tracker is None:
            return []
        persist = getattr(self.tracker, '_persist', None) or {}
        return sorted(a for a, v in persist.get('aliases', {}).items() if v == key)

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
        """控制中心「練這一課」：今天已有該路徑、同一堂課的研究任務就沿用，沒有就加入一個"""
        q = self.quests
        cur = q.current_lesson(skill)
        for t in q.today_tasks():
            if (t['mode'] == 'study' and t['params'].get('path') == skill and t['status'] in ('active', 'ready')
                    and (cur is None or t['params'].get('lesson_id') == cur['id'])):
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

    def set_current_lesson(self, skill: str, lesson_id: str) -> bool:
        """課程頁「改從這課開始」：把學習路徑的目前課程移到指定的課"""
        from core import study_lessons
        ids = [l['id'] for l in study_lessons.path(skill)]
        if lesson_id not in ids or self.paused:
            return False
        self.quests.path_state(skill)['index'] = ids.index(lesson_id)
        self.quests.mark_dirty()
        self.quests.save(force=True)
        return True

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
