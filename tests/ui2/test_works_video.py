# -*- coding: utf-8 -*-
"""作品頁的縮時影片：合併片段、匯出指定長度（背景執行，完成時寵物通知並更新清單）。
以暫存資料夾、假的追蹤器與 ffmpeg 產生的小影片執行；沒有 ffmpeg 時只檢查提示"""
import os
import subprocess
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PySide6.QtWidgets import QApplication, QPushButton, QSpinBox  # noqa: E402

from core import companion, settings2, video_tools as V, works  # noqa: E402
from ui2 import app as A  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


def wait(cond, ms=60000):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


KEY = '本機磁碟 (D:) _ art _ 貓咪.sai2'


class FakeTracker:
    def __init__(self, *a, **k):
        self.locked_file = None
        self._persist = {'aliases': {}}

    def start(self): pass
    def stop(self): pass

    def get_state(self):
        return {'sai2_running': False, 'current_file': None, 'raw_current_file': None, 'session_draw': 0.0,
                'files': {KEY: {'open_seconds': 600.0, 'draw_seconds': 300.0, 'sessions': 2,
                                'last_seen': '2026-10-27T10:00:00'}}, 'raw_title': ''}

    def get_draw_counter(self): return 0.0
    def today_draw_seconds(self): return 0.0
    def daily_history(self): return {}
    def resolve_alias(self, n): return n


qapp = QApplication(sys.argv[:1])
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True, 'practice_card': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.set('works.thumbnails', False)
s.save()
folder = works.video_dir(s.videos_dir, KEY)
os.makedirs(folder, exist_ok=True)
if V.available():
    for name, size, sec in (('20261026_100000.mp4', (640, 360), 4), ('20261027_100000.mp4', (800, 360), 3)):
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'color=c=gray:s={size[0]}x{size[1]}:r=30:d={sec}',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', os.path.join(folder, name)], check=True)
else:
    open(os.path.join(folder, '20261026_100000.mp4'), 'w').close()

ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
said = []
ctl.say = lambda text, actions=(), important=True, seconds=6.0: said.append((text, [a[0] for a in actions]))
ctl.start()
pump(150)
ctl.open_main('作品')
pump(300)
wp = ctl._main.page_widget('作品', 'WorksPage')
wp._show(KEY)
pump(100)


def btn(prefix):
    pump(30)
    return next((b for b in wp.detail.findChildren(QPushButton) if b.text().startswith(prefix) and b.isVisible()), None)


if V.available():
    merge = btn('合併 2 段影片')
    check(merge is not None and merge.isEnabled(), 'merge button for two clips')
    merge.click()
    check(wait(lambda: any(n.startswith(V.MERGED_PREFIX) for n in os.listdir(folder)) and any('合併成一部' in t for t, _ in said)),
          'merged in the background, pet tells')
    text, actions = next((t, a) for t, a in said if '合併成一部' in t)
    check('（7 秒）' in text and '1 段解析度不同' in text and actions == ['播放', '影片資料夾'], f'resize noted, play button ({text})')
    pump(200)
    spin = next(sp for sp in wp.detail.findChildren(QSpinBox) if sp.suffix() == ' 秒' and sp.isVisible())   # 合併後清單重建過
    spin.setValue(5)
    btn('匯出縮時').click()
    check(wait(lambda: any(n.startswith(V.EXPORT_PREFIX) for n in os.listdir(folder)) and any('已匯出 5 秒' in t for t, _ in said)),
          'exported to the chosen length')
    check(s.get('works.export_seconds') == 5, 'length remembered')
    pump(200)
    check(btn('合併 2 段影片') is not None, 'list refreshed after exporting (merged / exported files are not counted as clips)')
else:
    check(btn('合併') is None, 'no ffmpeg → no buttons')

ctl._main.close()
ctl.quit()
A.release_widgets(qapp)
done()
