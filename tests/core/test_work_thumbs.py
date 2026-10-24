# -*- coding: utf-8 -*-
"""作品縮圖：擷取時機（存檔、停筆、長時間作畫、還沒有縮圖）、存檔與找檔、刪除／合併紀錄時一併處理、
背景擷取時確認畫面上還是同一個檔案；刪除紀錄後畫面馬上看得到（不用刪兩次）"""
import json
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir  # noqa: E402

block_tk()
from PIL import Image, ImageDraw  # noqa: E402
from core import companion, settings2, work_thumbs as W  # noqa: E402
from core.tracker import DrawTracker  # noqa: E402

# ─── 修改記號 ──
check(W.title_modified('PaintTool SAI Ver.2 (64bit) - a.psd (*)') is True, '(*) means modified')
check(W.title_modified('* a.sai2 - PaintTool SAI Ver.2') is True, 'leading * means modified')
check(W.title_modified('PaintTool SAI Ver.2 (64bit) - a.psd') is False and W.title_modified('') is None, 'clean / none')


# ─── 擷取時機 ──
def run(policy, seconds, file, drawing, modified=False, missing=False, start=0.0):
    out = []
    for i in range(seconds):
        k = policy.update(start + i, file, drawing, modified, 1.0, missing)
        if k:
            out.append((start + i, k))
    return out


p = W.ThumbPolicy()
check(run(p, 10, 'a.psd', False, missing=True) == [(W.FIRST_SEC, 'a.psd')], 'missing thumb: first shot after a few seconds')
p = W.ThumbPolicy()
run(p, 70, 'a.psd', True, modified=True)                   # 畫了 70 秒（期間有修改記號）
check(p.update(100, 'a.psd', False, False) == 'a.psd', 'saving after drawing → shot')
check(p.update(101, 'a.psd', False, True) is None and p.update(102, 'a.psd', False, False) is None,
      'saving again right away (nothing drawn) → no shot')
p = W.ThumbPolicy()
shots = run(p, 61, 'b.psd', True) + run(p, 25, 'b.psd', False, start=61)
check([k for _t, k in shots] == ['b.psd'] and shots[0][0] >= 61 + W.PAUSE_SEC - 1, f'pause after drawing → one shot {shots}')
p = W.ThumbPolicy()
shots = run(p, 30, 'c.psd', True) + run(p, 40, 'c.psd', False, start=30)
check(shots == [], 'short scribble then pause → no shot')
p = W.ThumbPolicy()
shots = run(p, int(W.PERIODIC_SEC) * 2 + 5, 'd.psd', True)
check(len(shots) == 2, f'long continuous drawing → periodic shots ({len(shots)})')
p = W.ThumbPolicy()
run(p, 70, 'e.psd', True)
check(p.update(70, 'f.psd', False, False) is None and p.update(71, None, False, None) is None, 'file switch resets, no file → none')
p = W.ThumbPolicy()
p.force('g.psd', 0)
check(run(p, 10, 'g.psd', False, missing=True) == [], 'manual capture counts toward the minimum gap')

# ─── 存檔、找檔、合併、刪除 ──
app = tmpdir()
img = Image.new('RGB', (1600, 1000), (240, 240, 240))
ImageDraw.Draw(img).ellipse((300, 200, 1200, 900), fill=(120, 80, 200))
key = '本機磁碟 (D:) _ art _ 立繪.psd'
path = W.save(app, key, img)
check(os.path.isfile(path) and max(Image.open(path).size) == W.MAX_SIDE, 'saved as small jpeg')
check(os.path.basename(path).endswith('.jpg') and ' _ ' not in os.path.basename(path), 'hashed file name')
check(W.find(app, 'old.psd', [key]) == path and W.find(app, 'none.psd') is None, 'find via alias')
W.move(app, key, 'new.psd')
check(W.find(app, 'new.psd') and not W.find(app, key), 'merge moves thumb to target')
W.delete(app, 'new.psd')
check(W.find(app, 'new.psd') is None, 'delete')
check(W.looks_blank(Image.new('RGB', (300, 200), 'white')) and not W.looks_blank(img), 'blank capture detection')

# ─── 刪除紀錄後馬上從清單消失（真的追蹤器，不啟動執行緒） ──
d = tmpdir()
dp = os.path.join(d, 'sai2_draw_time.json')
rec = {'open_seconds': 10, 'draw_seconds': 5, 'sessions': 1, 'last_seen': '2026-10-20T10:00:00'}
json.dump({'files': {'a.psd': dict(rec), 'b.psd': dict(rec), 'c.psd': dict(rec)}, 'aliases': {}}, open(dp, 'w'))
t = DrawTracker(data_path=dp, idle_timeout=10, track_unsaved=False)
with t._lock:
    t._update_state(time.monotonic(), force=True)
t.delete_file('a.psd')
check(sorted(t.get_state()['files']) == ['b.psd', 'c.psd'], 'deleted record gone from snapshot immediately')
t.add_alias('b.psd', 'c.psd')
check(sorted(t.get_state()['files']) == ['c.psd'], 'merged record gone immediately')


# ─── 服務：背景擷取 ──
class FakeTracker:
    def __init__(self, *a, **k):
        self.file = 'x.psd'
        self.deleted = []
        self.aliases = {}
        self._persist = {'aliases': self.aliases}

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': self.file, 'raw_current_file': None, 'session_draw': 0.0,
                'files': {}, 'raw_title': f'PaintTool SAI Ver.2 (64bit) - {self.file}'}

    def get_draw_counter(self):
        return 0.0

    def today_draw_seconds(self):
        return 0.0

    def daily_history(self):
        return {}

    def resolve_alias(self, n):
        return n

    def delete_file(self, k):
        self.deleted.append(k)

    def add_alias(self, a, b):
        self.aliases[a] = b


s = settings2.Settings2(tmpdir())
calls = []


def fake_capture():
    calls.append(1)
    return img


clk = [0.0]
svc = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False,
                                 clock=lambda: clk[0], thumb_capture=fake_capture)
svc.start()


def wait_idle():
    end = time.time() + 3
    while svc._thumb_busy and time.time() < end:
        time.sleep(0.01)


for i in range(8):                                 # 還沒有縮圖：開啟幾秒後自動擷取
    clk[0] += 1
    svc.tick()
wait_idle()
check(calls and os.path.isfile(W.path_for(s.app_dir, 'x.psd')), 'service captured a missing thumbnail')
clk[0] += 1
check('x.psd' in svc.tick().thumbs, 'tick reports the new thumbnail')
check(svc.thumb_of('x.psd') == W.path_for(s.app_dir, 'x.psd'), 'thumb_of')


def switching_capture():
    svc.tracker.file = 'y.psd'                     # 擷取的同時換了檔案
    return img


svc._thumb_capture = switching_capture
check(svc.capture_thumb('x.psd', manual=True), 'manual capture started')
wait_idle()
check(not os.path.isfile(W.path_for(s.app_dir, 'y.psd')), 'file changed during capture → not saved under either name')
svc.tracker.file = 'x.psd'
svc._thumb_capture = lambda: Image.new('RGB', (100, 100), 'white')
before = os.path.getmtime(W.path_for(s.app_dir, 'x.psd'))
svc.capture_thumb('x.psd', manual=True)
wait_idle()
check(os.path.getmtime(W.path_for(s.app_dir, 'x.psd')) == before, 'blank capture does not overwrite')
s.set('works.thumbnails', False)
n = len(calls)
svc.tracker.file = 'z.psd'
for i in range(10):
    clk[0] += 1
    svc.tick()
wait_idle()
check(len(calls) == n, 'turned off → no automatic capture')
svc.merge_work('x.psd', 'w.psd')
check(svc.tracker.aliases == {'x.psd': 'w.psd'} and os.path.isfile(W.path_for(s.app_dir, 'w.psd')), 'merge_work moves thumb')
svc.delete_work('w.psd')
check(svc.tracker.deleted == ['w.psd'] and not os.path.isfile(W.path_for(s.app_dir, 'w.psd')), 'delete_work removes thumb')
svc.stop()
done()
