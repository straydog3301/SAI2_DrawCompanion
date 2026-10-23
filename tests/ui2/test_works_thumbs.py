# -*- coding: utf-8 -*-
"""作品頁：列表顯示縮圖、右側大圖預覽、正開著的檔案可以手動擷取、背景存好縮圖後自動更新、
刪除只要「刪除 → 確定刪除」一次就從列表消失。以暫存資料夾與假的追蹤器執行"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from core import companion, settings2, work_thumbs as W  # noqa: E402
from ui2 import app as A  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


REC = {'open_seconds': 600.0, 'draw_seconds': 300.0, 'sessions': 2, 'last_seen': '2026-10-22T10:00:00'}


class FakeTracker:
    """和真的追蹤器一樣：刪除後快照要更新才看得到（真的追蹤器現在會馬上更新）"""
    def __init__(self, *a, **k):
        self.files = {'本機磁碟 (D:) _ art _ 立繪.psd': dict(REC), '本機磁碟 (D:) _ art _ 草稿.psd': dict(REC),
                      'Artist _ Desktop _ 委託 _ 頭像.psd': dict(REC)}
        self.current = '本機磁碟 (D:) _ art _ 立繪.psd'
        self.locked_file = None
        self._persist = {'aliases': {}}

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': self.current, 'raw_current_file': None, 'session_draw': 0.0,
                'files': {k: dict(v) for k, v in self.files.items()}, 'raw_title': ''}

    def get_draw_counter(self):
        return 0.0

    def today_draw_seconds(self):
        return 0.0

    def daily_history(self):
        return {}

    def resolve_alias(self, n):
        return n

    def delete_file(self, k):
        self.files.pop(k, None)

    def add_alias(self, a, b):
        self._persist['aliases'][a] = b
        self.files.pop(a, None)


qapp = QApplication(sys.argv[:1])
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True, 'practice_card': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.set('works.thumbnails', False)                   # 這裡手動控制擷取
s.save()
img = Image.new('RGB', (1200, 900), (250, 245, 235))
ImageDraw.Draw(img).ellipse((200, 150, 1000, 800), fill=(110, 90, 210))
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False,
                                         thumb_capture=lambda: img)
ctl.say = lambda *a, **k: None
ctl.start()
pump(150)
W.save(s.app_dir, '本機磁碟 (D:) _ art _ 草稿.psd', img)

ctl.open_main('作品')
pump(300)
mw = ctl._main
wp = mw.page_widget('作品', 'WorksPage')
tiles = wp._tiles
check(len(tiles) == 3, 'every row has a thumbnail tile')
draft = tiles['本機磁碟 (D:) _ art _ 草稿.psd'].pixmap()
check(draft is not None and draft.width() >= 64, 'row with thumbnail shows the picture')
check(tiles['本機磁碟 (D:) _ art _ 立繪.psd'].pixmap().width() < 30, 'row without thumbnail shows the file icon')
groups = {r['group'] for r in wp.rows}
check('委託' in groups and 'Artist' not in groups, f'user-folder works not grouped by user name {groups}')

wp._show('本機磁碟 (D:) _ art _ 草稿.psd')
pump(50)
texts = ' '.join(lb.text() for lb in wp.detail.findChildren(QLabel))
check('縮圖更新於' in texts, 'detail shows preview')
check(not [b for b in wp.detail.findChildren(QPushButton) if b.text() == '擷取目前畫布'], 'no capture button for a closed file')

wp._show('本機磁碟 (D:) _ art _ 立繪.psd')
ctl._tick()
wp._show('本機磁碟 (D:) _ art _ 立繪.psd')
pump(50)
texts = ' '.join(lb.text() for lb in wp.detail.findChildren(QLabel))
cap = [b for b in wp.detail.findChildren(QPushButton) if b.text() == '擷取目前畫布']
check('還沒有縮圖' in texts and cap, 'open file without thumbnail: hint + capture button')
cap[0].click()
end = time.time() + 3
while ctl.service._thumb_busy and time.time() < end:
    time.sleep(0.01)
ctl._tick()                                       # 背景存好後，下一次 tick 通知作品頁
pump(100)
wp = mw.page_widget('作品', 'WorksPage')
check(wp._tiles['本機磁碟 (D:) _ art _ 立繪.psd'].pixmap().width() >= 64, 'tile updated after capture')
check('縮圖更新於' in ' '.join(lb.text() for lb in wp.detail.findChildren(QLabel)), 'preview updated after capture')

# ─── 刪除：刪除 → 確定刪除，一次就消失 ──
key = '本機磁碟 (D:) _ art _ 草稿.psd'
wp._show(key)
pump(50)
next(b for b in wp.detail.findChildren(QPushButton) if b.text() == '刪除這筆紀錄').click()
next(b for b in wp.detail.findChildren(QPushButton) if b.text() == '確定刪除').click()
pump(100)
check(key not in [r['key'] for r in wp.rows] and key not in wp._tiles, 'gone from the list after one delete')
check(W.find(s.app_dir, key) is None, 'its thumbnail is removed too')

mw.close()
ctl.quit()
A.release_widgets(qapp)
done()
