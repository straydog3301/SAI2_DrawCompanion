# -*- coding: utf-8 -*-
"""速寫換圖（線上圖庫比較慢、會失敗、偶爾卡住）：預先抓好下一張所以換圖不用等、載入中有提示、
失敗時畫面上看得到原因、卡住時逾時解鎖可以再按下一張。以假的圖源與追蹤器執行（不連網）"""
import os
import sys
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import companion, settings2, sketch_source as SK  # noqa: E402
from ui2 import app as A  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


def wait(cond, ms=3000):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end and not cond():
        qapp.processEvents()
        time.sleep(0.005)
    return cond()


class FakeTracker:
    def __init__(self, *a, **k):
        self.locked_file = None
        self._persist = {'aliases': {}}
        self.counter = 0.0

    def start(self): pass
    def stop(self): pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': 'x.psd', 'raw_current_file': None, 'session_draw': 0.0,
                'files': {}, 'raw_title': ''}

    def get_draw_counter(self): return self.counter
    def today_draw_seconds(self): return 0.0
    def daily_history(self): return {}
    def resolve_alias(self, n): return n


class FakeSource:
    """mode：'ok' / 'slow'（delay 秒）/ 'fail' / 'hang'（等到 release）"""
    def __init__(self):
        self.mode, self.delay, self.n, self.calls = 'ok', 0.0, 0, 0
        self.release = threading.Event()
        self.active = self.max_active = 0
        self._lock = threading.Lock()

    def next_image(self, opts):
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            return self._next()
        finally:
            with self._lock:
                self.active -= 1

    def _next(self):
        if self.mode == 'fail':
            raise SK.SketchError('HTTP 503 Service Unavailable', 0)
        if self.mode == 'hang':
            self.release.wait(5)
        if self.mode == 'slow':
            time.sleep(self.delay)
        self.n += 1
        return Image.new('RGB', (300, 400), (self.n * 30 % 255, 90, 160)), f'Pexels · 第 {self.n} 張'


qapp = QApplication(sys.argv[:1])
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True, 'practice_card': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.set('sketch.auto_canvas', False)
s.set('sketch.count_mode', 'clock')
s.set('sketch.source', 'pexels')
s.set('sources.pexels_key', 'test-key')
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
said = []
ctl.say = lambda text, *a, **k: said.append(text)
ctl.start()
pump(150)
w = ctl.open_ref('sketch', None)
m = w.mode
src = FakeSource()
m.source = src
m._token += 1                                      # 換掉開窗時用真圖源發出的請求
m.loading = False
m._prefetching = False
m.load_new()

check(wait(lambda: w.base is not None), 'first image shown')
check(wait(lambda: m._prefetched is not None), 'next image pre-fetched in the background')

# ─── 倒數結束：直接換成預先抓好的那張，不用等網路 ──
first = w.base
src.mode, src.delay = 'slow', 1.5
m.session.remaining = 1
pump(1100)
check(w.base is not first and len(m.session.history) == 2 and not m.loading, 'countdown end switches instantly')

# ─── 下一張還沒抓好就按：顯示「載入下一張…」，好了就換 ──
second = w.base
m._prefetched = None
wait(lambda: not m._prefetching, 3000)
m._prefetched = None
m.next()
check(m.loading and m.info()[0] == '載入下一張…', 'slow network: shows loading')
check(wait(lambda: w.base is not second, 4000) and not m.loading, 'slow image arrives and is shown')

# ─── 預先抓取還在進行時按下一張：等那一張，不會同時抓兩張 ──
wait(lambda: not m._prefetching, 3000)
m._prefetched = None
src.mode, src.delay = 'slow', 0.8
src.max_active = 0
m._prefetch()
cur = w.base
m.next()
check(m.loading and m._await_prefetch, 'waits for the in-flight prefetch')
check(wait(lambda: w.base is not cur, 3000) and src.max_active == 1, 'shown from prefetch, never two requests at once')

# ─── 失敗：畫面上已有圖時也要看得到原因，可以再按下一張重試 ──
wait(lambda: not m._prefetching, 3000)
m._prefetched = None
src.mode = 'fail'
said.clear()
cur = w.base
m.next()
check(wait(lambda: not m.loading), 'failure clears loading')
check(w.base is cur and '下一張載入失敗' in m.info()[0] and '503' in m.info()[0], f'failure reason visible ({m.info()[0]})')
check(any('載入失敗' in x for x in said), 'pet tells what happened')
src.mode = 'ok'
m.next()
check(wait(lambda: w.base is not cur) and '失敗' not in m.info()[0], 'pressing next again retries and recovers')

# ─── 卡住：逾時解鎖，之後可以再按下一張 ──
wait(lambda: not m._prefetching, 3000)
m._prefetched = None
src.mode = 'hang'
src.release.clear()
m.LOAD_TIMEOUT_MS = 300
cur = w.base
m.next()
check(m.loading, 'stuck request is loading')
check(wait(lambda: not m.loading, 2000) and '逾時' in m.info()[0], 'timeout unlocks and explains')
src.release.set()                                  # 卡住的請求後來才回來：結果丟掉，不會突然換圖
pump(300)
check(w.base is cur, 'late result after timeout is ignored')
src.mode = 'ok'
m.LOAD_TIMEOUT_MS = 30000
m.next()
check(wait(lambda: w.base is not cur), 'next works again after a timeout')

w.close()
ctl.quit()
A.release_widgets(qapp)
done()
