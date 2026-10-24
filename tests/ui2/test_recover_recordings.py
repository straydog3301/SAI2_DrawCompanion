# -*- coding: utf-8 -*-
"""沒有合成的縮時錄影：啟動時寵物詢問要不要合成、「工具」頁列出並可合成或捨棄（捨棄要按兩次）。
以暫存資料夾執行，錄影器不開啟錄影"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from core import companion, settings2, timelapse as TL  # noqa: E402
from ui2 import app as A  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


class FakeTracker:
    def __init__(self, *a, **k):
        self.locked_file = None
        self._persist = {'aliases': {}}

    def start(self): pass
    def stop(self): pass

    def get_state(self):
        return {'sai2_running': False, 'current_file': None, 'raw_current_file': None, 'session_draw': 0.0,
                'files': {}, 'raw_title': ''}

    def get_draw_counter(self): return 0.0
    def today_draw_seconds(self): return 0.0
    def daily_history(self): return {}
    def resolve_alias(self, n): return n


def leftover(videos, name, frames):
    d = os.path.join(videos, 'temp', name)
    os.makedirs(d)
    for i in range(frames):
        Image.new('RGB', (320, 180), (200, 200, 200)).save(os.path.join(d, f'frame_{i:06d}.jpg'))
    t = time.time() - 600
    for f in os.listdir(d):
        os.utime(os.path.join(d, f), (t, t))
    os.utime(d, (t, t))
    return d


qapp = QApplication(sys.argv[:1])
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True, 'practice_card': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.save()
a = leftover(s.videos_dir, '桌面_貓咪_20261024_090000', 4)
b = leftover(s.videos_dir, '桌面_練習_20261024_091000', 3)

ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
said = []
ctl.say = lambda text, *a, **k: said.append((text, k.get('actions') or (a[0] if a else ())))
ctl.start()
pump(150)

has_ffmpeg = TL.find_ffmpeg()
check(len(ctl.service.unexported_recordings()) == 2, 'leftovers found at startup')
asked = ctl._recover_prompt()
if has_ffmpeg:
    check(asked and '貓咪' in said[-1][0] and '2 段' in said[-1][0], f'pet asks to merge ({said[-1][0]})')
    check([x[0] for x in said[-1][1]] == ['合成', '之後再說'], 'merge / later buttons')
else:
    check(not asked, 'no prompt without ffmpeg')

ctl.open_main('工具')
pump(300)
mw = ctl._main
tp = mw.page_widget('工具', 'ToolsPage')
pump(50)
check(tp.recover_card.isVisible(), 'unexported recordings listed on the Tools page')
rows = [lb.text() for lb in tp.recover_card.findChildren(QLabel)]
check(any('貓咪' in t and '4 張' in t for t in rows) and any('練習' in t for t in rows), f'rows show name and frames ({rows})')


def btn(name, text):
    """某一列（以作品名稱找）的按鈕"""
    pump(30)
    for lb in tp.recover_card.findChildren(QLabel):
        if name in lb.text() and lb.isVisible():
            row = lb.parentWidget()
            hit = [x for x in row.findChildren(QPushButton) if x.text() == text]
            return hit[0] if hit else None
    return None


# 捨棄要確認
btn('練習', '捨棄').click()
check(os.path.isdir(b) and btn('練習', '確定捨棄') and btn('貓咪', '捨棄'), 'first click only asks to confirm')
btn('練習', '確定捨棄').click()
check(not os.path.isdir(b) and os.path.isdir(a), 'second click discards only that one')
check(btn('練習', '合成') is None and btn('貓咪', '合成') is not None, 'list refreshed')

if has_ffmpeg:
    btn('貓咪', '合成').click()
    check(any('開始合成 1 段' in t for t, _ in said), 'pet confirms merging')
    for r in [ctl.service.recorder] + ctl.service._old_recorders:
        for th in list(r.export_threads):
            th.join(timeout=60)
    vdir = os.path.join(s.videos_dir, '桌面_貓咪')
    check(os.path.isdir(vdir) and any(x.endswith('.mp4') for x in os.listdir(vdir)), 'video merged into the work folder')
    pump(50)
    tp._refresh_recover()
    check(not tp.recover_card.isVisible(), 'card hidden when nothing is left')

mw.close()
ctl.quit()
A.release_widgets(qapp)
done()
