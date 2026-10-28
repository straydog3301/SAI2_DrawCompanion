# -*- coding: utf-8 -*-
"""未存檔的畫布：照常記錄在暫時名稱底下；存檔的那一刻（2026-10 實機觀察：存檔視窗 → 標題直接換成新檔名、文件視窗不變）
併到正式作品；切分頁、開啟檔案、取消存檔不會誤判；另存新檔時錄影接著錄；暫時紀錄不出現在作品清單。
以假的 SAI2 視窗資訊測試，不開啟 SAI2"""
import json
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from core import companion, settings2, timelapse as TL, tracker as T, unsaved as U  # noqa: E402

A = U.temp_key('新增畫布1', '1028-1750')
B = U.temp_key('新增畫布2', '1028-1750')
check(A == '未存檔 _ 1028-1750 _ 新增畫布1' and U.is_temp(A) and U.temp_name(A) == '新增畫布1', 'temp key')
check(not T.is_saved_filename(A) and not U.is_temp('暫存 _ a.sai2'), 'temp key is never a saved work')
check(TL.file_key_to_subdir(A) == U.VIDEO_FOLDER, 'never-saved videos go to one folder')

# ─── 存檔的判斷 ──
def run(steps, docs_seq=None):
    """steps：[(key, dialog), …]；docs_seq：每一步的文件視窗數量（None = 取不到）"""
    w = U.SaveWatcher()
    out = []
    for i, (key, dialog) in enumerate(steps):
        n = None if docs_seq is None else docs_seq[i]
        e = w.observe(key, dialog, lambda n=n: n)
        if e:
            out.append(e)
    return out


SAVED = '暫存 _ 新增畫布1.sai2'
check(run([(A, False), (A, True), (A, True), (SAVED, False)], [2, 2, 2, 2]) == [('adopt', A, SAVED)],
      'save: dialog, then the title becomes a new file')
check(run([(A, False), (SAVED, False)], [2, 2]) == [], 'no dialog → tab switch, not a save')
check(run([(A, False), (A, True), ('其他 _ x.sai2', False)], [2, 2, 3]) == [], 'open dialog adds a document → not a save')
check(run([(SAVED, False), (A, False), (A, True), (A, False), (SAVED, False)], [2, 2, 2, 2, 2]) == [],
      'cancelled save, then switching to a file already open → nothing')
check(run([(A, False), (A, True), (B, False)], [2, 2, 3]) == [], 'new canvas from an unsaved one → nothing')
check(run([(A, False), (A, True), (SAVED, False)]) == [('ask', A, SAVED)], 'cannot count documents → ask the user')
check(run([(SAVED, False), (SAVED, True), ('暫存 _ 新增畫布1_t.sai2', False)], [2, 2, 2])
      == [('saveas', SAVED, '暫存 _ 新增畫布1_t.sai2')], 'save as')
check(run([(A, False), (None, False), (A, True), (SAVED, False)], [2, 2, 2, 2]) == [('adopt', A, SAVED)],
      'a moment without a title does not break it')

# ─── 追蹤器：未存檔照常記錄，存檔時併到正式作品 ──
d = tmpdir()
dp = os.path.join(d, 'sai2_draw_time.json')
APP = 'PaintTool SAI Ver.2 (64bit) Alpha.2026.10.19'
title = [f'{APP} - 新增畫布1 (*)']
dialog = [False]
docs = [3]
T._scan_sai2 = lambda: (T.extract_filename(title[0]), True, title[0], True)
T._sai2_dialog_owner = lambda fg: 1234 if dialog[0] else None
T._sai2_doc_windows = lambda main: docs[0]
tr = T.DrawTracker(data_path=dp, idle_timeout=10, track_unsaved=True)


def step(seconds=1.2):
    tr._last_win_scan = 0
    time.sleep(seconds)


t_start = time.monotonic()
tr.start()
step()
st = tr.get_state()
temp = st['current_file']
check(U.is_temp(temp) and U.temp_name(temp) == '新增畫布1', f'unsaved canvas tracked under a temp key ({temp})')
check(tr.key_for_name('新增畫布1') == temp, 'recorder can match the unsaved title')
dialog[0] = True
step()
dialog[0] = False
title[0] = f'{APP} - 暫存 / 新增畫布1.sai2'
step()
st = tr.get_state()
saved = '暫存 _ 新增畫布1.sai2'
check(st['current_file'] == saved and temp not in st['files'] and st['files'][saved]['open_seconds'] > 1.5,
      'saved: the time moved to the saved work')
check(tr.pop_save_events() == [('adopt', temp, saved)] and tr.pop_save_events() == [], 'save event reported once')
step()
tr.save()
opened = json.load(open(dp, encoding='utf-8'))['files'][saved]['open_seconds']
elapsed = time.monotonic() - t_start
check(abs(opened - elapsed) < 1.5, f'no time lost or counted twice across the save ({opened:.1f}s vs {elapsed:.1f}s)')
tr.stop()

# 換檔時，上次自動存檔之後畫的時間也要算進今日總計（舊問題：換檔後從今日總計漏掉）
dp2 = os.path.join(tmpdir(), 'sai2_draw_time.json')
title[0] = f'{APP} - 暫存 / a.sai2'
T._mouse_pressed = lambda: True                       # 一直在下筆
tr2 = T.DrawTracker(data_path=dp2, idle_timeout=10, track_unsaved=True)
tr2.start()
step2 = lambda sec=1.3: (setattr(tr2, '_last_win_scan', 0), time.sleep(sec))  # noqa: E731
step2(2.0)
title[0] = f'{APP} - 新增畫布3 (*)'
step2()
title[0] = f'{APP} - 暫存 / a.sai2'
step2()
tr2.save()                                            # 寫入目前這段，紀錄與今日總計都是最新的
saved2 = json.load(open(dp2, encoding='utf-8'))
files2 = saved2['files']
temp3 = next(k for k in files2 if U.is_temp(k))
check(files2[temp3]['draw_seconds'] > 0.8 and 2.8 < files2['暫存 _ a.sai2']['draw_seconds'] < 4.0,
      f'plain tab switch from an unsaved canvas keeps the times separate ({ {k: round(v["draw_seconds"], 1) for k, v in files2.items()} })')
drawn = sum(v['draw_seconds'] for v in files2.values())
today = sum(saved2['daily_history'].values())
tr2.stop()
check(drawn > 2.0 and abs(today - drawn) < 0.6, f'switching files keeps the daily total complete ({today:.1f}s vs {drawn:.1f}s)')

off = T.DrawTracker(data_path=os.path.join(tmpdir(), 'x.json'), idle_timeout=10, track_unsaved=False)
check(off.key_for_name('新增畫布1') is None, 'tracking unsaved canvases can still be turned off (1.x)')

# ─── 服務：錄影改名、縮圖搬過去；暫時紀錄不出現在作品清單 ──
class FakeRecorder:
    def __init__(self, output_dir, fps):
        self.output_dir, self.fps, self.enabled, self.active_file = output_dir, fps, False, None
        self.frame_count, self.multiplier, self.total_recorded_duration, self.export_threads = 0, 5, 0.0, []
        self.renamed = []

    def start(self): pass
    def stop(self): pass
    def switch_file(self, f): self.active_file = f if self.enabled else None
    def rename_file(self, old, new): self.renamed.append((old, new))


class FakeTracker:
    def __init__(self, *a, **k):
        self.locked_file = None
        self.events = []
        self.aliases = []
        self.files = {'暫存 _ a.sai2': {'last_seen': '2026-10-28T10:00:00', 'draw_seconds': 5.0},
                      A: {'last_seen': '2026-10-28T11:00:00', 'draw_seconds': 9.0}}

    def start(self): pass
    def stop(self): pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': A, 'raw_current_file': '新增畫布1', 'files': dict(self.files)}

    def get_draw_counter(self): return 0.0
    def today_draw_seconds(self): return 0.0
    def daily_history(self): return {}
    def resolve_alias(self, n): return n
    def pop_save_events(self): out, self.events = self.events, []; return out
    def add_alias(self, a, b): self.aliases.append((a, b))


s = settings2.Settings2(tmpdir())
svc = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False, recorder_factory=FakeRecorder)
svc.start()
res = svc.tick()
check(res.status.current_file == A and res.status.unsaved_file == '新增畫布1', 'status: drawing on an unsaved canvas')
check(list(svc.all_files()) == ['暫存 _ a.sai2'] and [r['key'] for r in svc.recent_files()] == ['暫存 _ a.sai2'],
      'temp records hidden from works and recent')
from core import work_thumbs  # noqa: E402
thumb = work_thumbs.path_for(s.app_dir, A)
os.makedirs(os.path.dirname(thumb), exist_ok=True)
open(thumb, 'wb').write(b'x')
svc.tracker.events = [('adopt', A, SAVED), ('saveas', SAVED, '暫存 _ b.sai2'), ('ask', B, '暫存 _ c.sai2')]
res = svc.tick()
check(svc.recorder.renamed == [(A, SAVED), (SAVED, '暫存 _ b.sai2')], 'recording follows save and save-as')
check(os.path.isfile(work_thumbs.path_for(s.app_dir, SAVED)) and not os.path.isfile(thumb), 'thumbnail moved')
check([e[0] for e in res.saves] == ['adopt', 'saveas', 'ask'], 'events passed to the UI (ask = question)')
svc.adopt_unsaved(B, '暫存 _ c.sai2')
check(svc.tracker.aliases == [(B, '暫存 _ c.sai2')] and svc.recorder.renamed[-1] == (B, '暫存 _ c.sai2'), 'user confirmed')
svc.stop()

# ─── 錄影器：改名後接著錄；沒有這段錄影時不動 ──
rec = TL.TimelapseRecorder(output_dir=tmpdir(), fps=30)
rec.per_file = True
rec.enabled = True
rec.switch_file(A)
tdir = rec.temp_dir
rec.rename_file(A, SAVED)
check(rec.active_file == SAVED and rec.temp_dir == tdir and rec._current_subdir == TL.file_key_to_subdir(SAVED),
      'active recording renamed, same frames folder')
meta = json.load(open(os.path.join(tdir, TL.SESSION_META), encoding='utf-8'))
check(meta['file'] == SAVED, 'session info updated (crash recovery uses the saved name)')
rec.switch_file(B)
rec.rename_file(SAVED, '暫存 _ b.sai2')
check('暫存 _ b.sai2' in rec._sessions and SAVED not in rec._sessions, 'kept recording renamed too')
rec.rename_file('沒有 _ x.sai2', '暫存 _ y.sai2')
check(rec.pending_files() == [B, '暫存 _ b.sai2'], 'unknown name ignored')
done()
