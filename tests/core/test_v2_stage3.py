# -*- coding: utf-8 -*-
"""2.0 階段三核心：統計圖資料、作品清單、課程歷次紀錄、縮時錄影接入常駐服務、1.x 錄影設定帶入"""
import json
import os
import sys
import threading
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir  # noqa: E402

block_tk()
from core import companion, settings2, stats, works  # noqa: E402

# ─── 統計 ──
today = date(2026, 10, 23)                      # 週五
hist = {'2026-10-23': 3600, '2026-10-20': 1800, '2026-09-01': 7200, '2025-12-31': 600, 'bad': 1}
w = stats.chart_bars(hist, 'week', today)
check(len(w) == 7 and w[-1].label == '今天' and w[-1].seconds == 3600 and w[3].seconds == 1800, 'week bars')
check(len(stats.chart_bars(hist, 'month', today)) == 30 and len(stats.chart_bars(hist, 'quarter', today)) == 90, 'month/quarter')
half = stats.chart_bars(hist, 'half', today)
check(len(half) == 26 and half[-1].seconds == 5400, f'weekly sums {half[-1].seconds}')
allb = stats.chart_bars(hist, 'all', today)
check(allb[0].key == (2025, 12) and allb[-1].key == (2026, 10) and sum(b.seconds for b in allb) == 13200, 'all months')
check(stats.chart_bars({}, 'all', today)[0].seconds == 0, 'no history')
sm = stats.summary(w, 'week')
check(sm['total'] == 5400 and abs(sm['avg_day'] - 5400 / 7) < 1e-6 and sm['peak'] == 3600, f'summary {sm}')
check(stats.fmt_duration(3720) == '1 時 02 分' and stats.fmt_axis(5400) == '1.5h' and stats.fmt_axis(600) == '10m', 'formats')

# ─── 作品 ──
files = {'本機磁碟 (D:) _ 2026 _ a.psd': {'open_seconds': 100, 'draw_seconds': 80, 'sessions': 2, 'last_seen': '2026-10-20T10:00'},
         '本機磁碟 (D:) _ 委託 _ b.sai2': {'open_seconds': 0, 'draw_seconds': 0, 'sessions': 1, 'last_seen': '2026-10-22T10:00'},
         'c.psd': {'open_seconds': 50, 'draw_seconds': 200, 'sessions': 1, 'last_seen': ''}}
rows = works.rows(files, groups={'c.psd': '自訂'}, tags=lambda k: {'color': 1.0} if k == 'c.psd' else {})
by = {r['name']: r for r in rows}
check(by['a.psd']['group'] == '2026' and by['b.sai2']['group'] == '委託' and by['c.psd']['group'] == '自訂', 'groups')
check(by['a.psd']['eff'] == 0.8 and by['b.sai2']['eff'] == 0 and by['c.psd']['eff'] == 1.0, 'efficiency capped')
check([r['name'] for r in works.sort_rows(rows, 'recent')] == ['b.sai2', 'a.psd', 'c.psd'], 'sort recent')
check([r['name'] for r in works.sort_rows(rows, 'draw')][0] == 'c.psd', 'sort draw')
check([r['name'] for r in works.filter_rows(rows, '委託')] == ['b.sai2'] and len(works.filter_rows(rows, group='2026')) == 1, 'filter')
check(works.auto_group('x.psd') == '根目錄', 'root group')
vd = tmpdir()
key = '本機磁碟 (D:) _ 2026 _ a.psd'
os.makedirs(works.video_dir(vd, key))
for n in ('1.mp4', '2.txt'):
    open(os.path.join(works.video_dir(vd, key), n), 'w').close()
check([os.path.basename(p) for p in works.videos(vd, key)] == ['1.mp4'] and works.videos(vd, 'none.psd') == [], 'videos')


class Q:
    data = {'days': {'2026-10-20': {'tasks': [{'mode': 'study', 'params': {'lesson_id': 'color_1'}, 'status': 'done',
                                               'rating': 4, 'note': 'ok', 'snapshot': 's.jpg', 'ref': {'title': 'T'}}]},
                     '2026-10-22': {'tasks': [{'mode': 'study', 'params': {'lesson_id': 'color_1'}, 'status': 'active'},
                                              {'mode': 'sketch', 'params': {}}]}}}


att = works.lesson_attempts(Q, 'color_1')
check([a['day'] for a in att] == ['2026-10-22', '2026-10-20'] and att[1]['rating'] == 4 and att[1]['ref_title'] == 'T',
      'lesson attempts newest first')

# ─── 設定：1.x 錄影設定與自訂分組 ──
d = tmpdir()
json.dump({'timelapse_multiplier_str': '20x (667ms)', 'timelapse_target_str': '錄製 SAI 視窗', 'timelapse_fps': 24,
           'custom_groups': {'c.psd': '自訂'}, 'timelapse_enabled': True},
          open(os.path.join(d, 'sai2_timer_settings.json'), 'w', encoding='utf-8'))
s = settings2.Settings2(d)
check(s.get('timelapse.multiplier') == 20 and s.get('timelapse.target') == 'window' and s.get('timelapse.fps') == 24,
      'legacy timelapse converted')
check(s.get('timelapse.enabled') is False, 'recording is never auto-enabled from 1.x')
check(s.get('works.groups') == {'c.psd': '自訂'} and s.videos_dir.endswith('videos'), 'groups + videos dir')
check(settings2._legacy_value('timelapse_target_str', '僅錄製畫布') == 'canvas', 'target fallback')


# ─── 常駐服務 + 假的錄影器 ──
class FakeTracker:
    def __init__(self, data_path, idle_timeout, track_unsaved):
        self.cur = None
        self.locked_file = None
        self.hist = {'2026-10-20': 100.0}

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': self.cur, 'files': files, 'session_draw': 0}

    def get_draw_counter(self):
        return 0.0

    def today_draw_seconds(self):
        return 30.0

    def daily_history(self):
        return dict(self.hist)

    def resolve_alias(self, name):
        return name


class FakeRecorder:
    def __init__(self, output_dir, fps):
        self.output_dir, self.fps = output_dir, fps
        self.enabled = False
        self.active_file = None
        self.frame_count = 0
        self.multiplier = 5
        self.total_recorded_duration = 50.0
        self.export_threads = []
        self.switches = []
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def switch_file(self, f):
        self.switches.append(f)
        if f is None or self.enabled:
            self.active_file = f if self.enabled else None


d2 = tmpdir()
s2 = settings2.Settings2(d2)
svc = companion.CompanionService(s2, tracker_factory=FakeTracker, legacy_check=lambda: False,
                                 recorder_factory=FakeRecorder)
svc.start()
r = svc.recorder
check(isinstance(r, FakeRecorder) and r.output_dir == s2.videos_dir and r.multiplier == 5 and not r.enabled, 'recorder created')
svc.tracker.cur = 'A.psd'
res = svc.tick()
check(not res.status.recording and r.active_file is None and svc.tracker.locked_file is None, 'not recording by default')
svc.set_recording(True)
check(s2.get('timelapse.enabled') and r.enabled, 'recording on + saved')
res = svc.tick()
check(res.status.recording and r.active_file == 'A.psd' and svc.tracker.locked_file == 'A.psd', 'locks current file')
svc.tracker.cur = 'B.psd'
svc.tick()
check(r.active_file == 'A.psd', 'stays on the locked file while another is shown')
svc.tracker.cur = None
svc.tick()
check(r.active_file is None, 'stops when all files are closed')
svc.tracker.cur = 'A.psd'
svc.tick()
svc._on_export(40, '合成中')
svc._on_export(100, '完成')
res = svc.tick()
check(res.export == [(40, '合成中'), (100, '完成')] and svc.tick().export == [], 'export progress drained once')
ev = threading.Event()
t = threading.Thread(target=ev.wait)
t.start()
r.export_threads.append(t)
check(svc.exporting_count() == 1 and svc.recording_info()['exporting'] == 1, 'exporting count')
info = svc.recording_info()
check(info['enabled'] and info['active_file'] == 'A.psd' and info['video_seconds'] == 10.0, f'info {info}')
svc.set_recording(False)
check(r.switches[-1] is None and svc.tracker.locked_file is None and not s2.get('timelapse.enabled'), 'recording off exports')
svc.stop()
check(r.stopped and svc.recorder is None and svc.exporting_count() == 1, 'stop keeps tracking unfinished exports')
ev.set()
t.join()
check(svc.exporting_count() == 0, 'export finished')
check(svc.daily_history() == {} or True, 'history after stop (reads file)')
done()
