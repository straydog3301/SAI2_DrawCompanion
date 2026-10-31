# -*- coding: utf-8 -*-
"""2.0 階段三介面：成長（月曆、單日明細、統計圖、主修）、課程（切換路徑、改從某課開始、練這一課）、
作品（搜尋、標籤、分組、合併、刪除、匯出）、工具（縮時錄影開關與設定）、錄影快捷按鈕、結束時等待影片合成。
以暫存資料夾與假的追蹤器、錄影器執行。"""
import os
import sys
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from core import companion, settings2  # noqa: E402
from ui2 import app as A, pages_more as PM, theme  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


FILES = {'本機磁碟 (D:) _ art _ 立繪.psd': {'open_seconds': 3600, 'draw_seconds': 2400, 'sessions': 3, 'last_seen': '2026-10-22T20:00:00'},
         '本機磁碟 (D:) _ art _ 立繪_v2.psd': {'open_seconds': 600, 'draw_seconds': 300, 'sessions': 1, 'last_seen': '2026-10-23T09:00:00'},
         '本機磁碟 (D:) _ 委託 _ 頭像.sai2': {'open_seconds': 900, 'draw_seconds': 800, 'sessions': 2, 'last_seen': '2026-10-21T09:00:00'}}


class FakeTracker:
    def __init__(self, data_path, idle_timeout, track_unsaved):
        self.files = {k: dict(v) for k, v in FILES.items()}
        self.locked_file = None
        self._persist = {'aliases': {}}
        self.cur = None

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': self.cur, 'raw_current_file': None, 'session_draw': 0, 'files': self.files}

    def get_draw_counter(self):
        return 0.0

    def today_draw_seconds(self):
        return 1200.0

    def daily_history(self):
        return {'2026-10-20': 3600.0, '2026-10-21': 1800.0}

    def resolve_alias(self, n):
        return self._persist['aliases'].get(n, n)

    def add_alias(self, alias, target):
        self._persist['aliases'][alias] = target
        rec = self.files.pop(alias)
        self.files[target]['draw_seconds'] += rec['draw_seconds']

    def delete_file(self, k):
        self.files.pop(k, None)

    def export_csv(self, path):
        open(path, 'w', encoding='utf-8').write('file\n')


class FakeRecorder:
    def __init__(self, output_dir, fps):
        self.output_dir, self.fps = output_dir, fps
        self.enabled = False
        self.active_file = None
        self.frame_count = 0
        self.multiplier = 5
        self.total_recorded_duration = 0.0
        self.export_threads = []

    def start(self):
        pass

    def stop(self):
        pass

    def switch_file(self, f):
        self.active_file = f if (f and self.enabled) else None


qapp = QApplication(sys.argv[:1])
qapp.setStyleSheet(theme.QSS)
d = tmpdir()
s = settings2.Settings2(d)
s.set('prompted', {'welcome': True, 'legacy_watcher': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False,
                                         recorder_factory=FakeRecorder)
said = []
ctl.say = lambda text, actions=(), important=True, seconds=6.0: said.append(text)
ctl.start()
pump(200)
q = ctl.service.quests

# ─── 成長 ──
t = q.today_tasks()[0]
t['status'], t['rating'], t['note'] = 'done', 4, '很順'
ctl.open_main('成長')
pump(300)
mw = ctl._main
gp = mw.page_widget('成長', 'GrowthPage')
labels = ' '.join(lb.text() for lb in gp.findChildren(QLabel))
check(gp is not None and '連續天數' in labels and '練習月曆' in labels and '動筆時間統計' in labels, 'growth page')
check('很順' in labels and '已打卡' in labels, 'today detail shown by default')
gp._shift(-1)
check(gp.month_label.text().endswith('月'), 'month navigation')
gp._set_period('week')
check(len(gp.chart.bars) == 7 and '合計' in gp.summary.text(), 'weekly chart + summary')
gp._set_period('all')
check(gp.chart.bars, 'all-time chart')
sid = q.data['skills'][0]['id']
gp._toggle_focus(sid)
check(q.settings['weekly_focus'] == sid, 'weekly focus set from skill card')

# ─── 課程 ──
ctl.open_main('課程')
pump(200)
cp = mw.page_widget('課程', 'CoursesPage')
check(cp is not None and len(cp.path_btns) == 7, f'7 learning paths ({len(cp.path_btns) if cp else 0})')
cp._select('color')
texts = ' '.join(lb.text() for lb in cp.findChildren(QLabel))
check('目前課程' in texts and '本次專注' in texts, 'lesson cards')
from core import study_lessons  # noqa: E402
third = study_lessons.path('color')[2]['id']
cp._jump(third)
check(q.current_lesson('color')['id'] == third, 'jump to a lesson')
cp._practice()
pump(200)
check(ctl.ref_win is not None and ctl.ref_win.mode.lesson['id'] == third, 'practice current lesson opens mini window')
ctl.ref_win.close()

# ─── 作品 ──
ctl.open_main('作品')
pump(300)
wp = mw.page_widget('作品', 'WorksPage')
check(wp is not None and len(wp.rows) == 3 and wp.selected == '本機磁碟 (D:) _ art _ 立繪_v2.psd', 'works list, newest selected')
wp.search.setText('委託')
pump(50)
rows_shown = [b for b in wp.findChildren(PM.QFrame) if b.objectName() == 'wrow']
check(len(rows_shown) == 1, f'search filter ({len(rows_shown)})')
wp.search.setText('')
key = '本機磁碟 (D:) _ art _ 立繪.psd'
wp._show(key)
btn = next(b for b in wp._tag_btns if b.property('sid') == 'color')
btn.setChecked(True)
check('color' in q.file_tags(key), 'skill tag saved')
wp._set_group(key, '主線作品')
check(s.get('works.groups')[key] == '主線作品' and any(r['group'] == '主線作品' for r in wp.rows), 'custom group')
wp._merge('本機磁碟 (D:) _ art _ 立繪_v2.psd', key)
check(len(wp.rows) == 2 and ctl.service.aliases_of(key) == ['本機磁碟 (D:) _ art _ 立繪_v2.psd'], 'merge into another work')
wp._delete('本機磁碟 (D:) _ 委託 _ 頭像.sai2')
check(len(wp.rows) == 1, 'delete record')
os.makedirs(os.path.join(s.videos_dir, 'art_立繪'), exist_ok=True)
open(os.path.join(s.videos_dir, 'art_立繪', 'take1.mp4'), 'w').close()
wp._show(key)
check(any('take1.mp4' in b.text() for b in wp.findChildren(QPushButton)), 'videos listed for the work')

# ─── 工具：縮時錄影 ──
ctl.open_main('工具')
pump(200)
tp = mw.tools_page
tp.toggle.setChecked(True)
check(s.get('timelapse.enabled') and ctl.service.recorder.enabled, 'recording on from tools page')
ctl.service.tracker.cur = key
ctl._tick()
tp.refresh()
labels = ' '.join(lb.text() for lb in tp.findChildren(QLabel))
check(ctl.service.recorder.active_file == key and '錄影中' in labels, 'records current work')
cb = tp.findChildren(PM.QComboBox)[0]
cb.setCurrentIndex(cb.findData(20))
check(s.get('timelapse.multiplier') == 20 and ctl.service.recorder.multiplier == 20, 'multiplier applied live')
ctl.run_slot('record')
check(not s.get('timelapse.enabled') and ctl.service.recorder.active_file is None, 'record slot toggles off')
ctl._on_export(100, '完成：x.mp4')
check(any('影片完成' in x for x in said) and ctl.export_state[0] is None, 'export done bubble')

# ─── 工具：SAI2 內建濾鏡擴充 (Mod) 與個別濾鏡開關 ──
from core import sai2_filters as SF  # noqa: E402
fake_sai2_dir = os.path.join(d, 'fake_sai2')
os.makedirs(fake_sai2_dir, exist_ok=True)
fake_sai2_exe = os.path.join(fake_sai2_dir, 'sai2.exe')
open(fake_sai2_exe, 'wb').close()
s.set('sai2_exe', fake_sai2_exe)

tp.flt_toggle.setChecked(True)
st_mod = SF.get_mod_status(fake_sai2_exe)
check(bool(s.get('filters_mod.enabled')) and st_mod['dll_installed'] and st_mod['enabled'],
      'filters mod enabled and mscms.dll deployed from tools page')
check(not os.path.exists(os.path.join(fake_sai2_dir, 'dwmapi.dll')), 'no dwmapi.dll deployed')
check('fx_stroke' in tp.flt_toggles, 'stroke layer effect toggle on tools page')
tp.flt_toggles['fx_stroke'].setChecked(False)
st_mod = SF.get_mod_status(fake_sai2_exe)
check(not bool(s.get('filters_mod.fx_stroke')) and not st_mod['fx_stroke'] and st_mod['binarize'],
      'fx_stroke toggle synced to sai2_filters_mod.ini')
tp.flt_toggles['fx_stroke'].setChecked(True)

tp.flt_toggles['posterize'].setChecked(False)
st_mod = SF.get_mod_status(fake_sai2_exe)
check(not bool(s.get('filters_mod.posterize')) and st_mod['binarize'] and not st_mod['posterize'],
      'posterize toggle synced to sai2_filters_mod.ini')
tp.flt_toggles['pixelate'].setChecked(False)
st_mod = SF.get_mod_status(fake_sai2_exe)
check(not bool(s.get('filters_mod.pixelate')) and not st_mod['pixelate'] and st_mod['sharpen'],
      'pixelate toggle synced; sharpen stays on (data-driven filters)')

tp.flt_toggle.setChecked(False)
st_mod = SF.get_mod_status(fake_sai2_exe)
check(not s.get('filters_mod.enabled') and not st_mod['enabled'] and not st_mod['dll_installed'],
      'filters mod disabled and mscms.dll removed from tools page')
mw.close()

# ─── 結束時等影片合成 ──
ev = threading.Event()
th = threading.Thread(target=ev.wait)
th.start()
ctl.service.recorder.export_threads.append(th)
quit_called = []
ctl.qapp.quit = lambda: quit_called.append(1)
ctl.quit()
check(not quit_called and not ctl.pet.isVisible(), 'quit waits while a video is exporting')
ev.set()
th.join()
pump(1300)
check(quit_called, 'quits after export finishes')
A.release_widgets(qapp)
done()
