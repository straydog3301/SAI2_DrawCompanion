# -*- coding: utf-8 -*-
"""作品頁：清單與詳細資料各自捲動（點舊作品時清單不跳、詳細資料看得到）、選取多個作品一次刪除、
不記錄的資料夾（輸入資料夾名稱、從作品詳細資料排除並可一併刪除舊紀錄）。以暫存資料夾與假的追蹤器執行"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton  # noqa: E402

from core import companion, settings2  # noqa: E402
from ui2 import app as A  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


FILES = {}
for i in range(40):
    FILES[f'本機磁碟 (D:) _ art _ 作品{i:02d}.psd'] = i
for i in range(5):
    FILES[f'Artist _ 下載 _ 參考{i}.png'] = 50 + i


class FakeTracker:
    def __init__(self, *a, **k):
        self.locked_file = None
        self._persist = {'aliases': {}}
        self.files = {k: {'open_seconds': 600.0, 'draw_seconds': 300.0 + v, 'sessions': 1,
                          'last_seen': f'2026-10-{(v % 28) + 1:02d}T10:00:00'} for k, v in FILES.items()}
        self.batches = []

    def start(self): pass
    def stop(self): pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': None, 'raw_current_file': None, 'session_draw': 0.0,
                'files': {k: dict(v) for k, v in self.files.items()}, 'raw_title': ''}

    def get_draw_counter(self): return 0.0
    def today_draw_seconds(self): return 0.0
    def daily_history(self): return {}
    def resolve_alias(self, n): return n

    def delete_file(self, k):
        self.files.pop(k, None)

    def delete_files(self, keys):
        self.batches.append(list(keys))
        for k in keys:
            self.files.pop(k, None)


qapp = QApplication(sys.argv[:1])
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True, 'practice_card': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.set('works.thumbnails', False)
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
said = []
ctl.say = lambda text, *a, **k: said.append(text)
ctl.start()
pump(150)
ctl.open_main('作品')
pump(400)
mw = ctl._main
mw.resize(1200, 760)
pump(300)
wp = mw.page_widget('作品', 'WorksPage')
tr = ctl.service.tracker


def btn(text, parent=None):
    pump(30)
    return next(b for b in (parent or wp).findChildren(QPushButton) if b.text() == text and b.isVisible())


# ─── 各自捲動 ──
outer = mw.pages['作品'].parentWidget()
while outer is not None and not hasattr(outer, 'verticalScrollBar'):
    outer = outer.parentWidget()
check(outer.verticalScrollBar().maximum() == 0, f'page itself does not scroll ({outer.verticalScrollBar().maximum()})')
lbar = wp.list_scroll.verticalScrollBar()
check(lbar.maximum() > 500, f'long list scrolls inside its own area ({lbar.maximum()})')
lbar.setValue(lbar.maximum())
pump(50)
old_key = list(wp._row_widgets)[-1]
wp._row_widgets[old_key].clicked.emit()
pump(100)
check(lbar.value() == lbar.maximum(), 'clicking an old work keeps the list where it was')
detail_name = wp.detail.findChildren(QLabel)[0].text()
check(wp.selected == old_key and detail_name == old_key.split(' _ ')[-1], f'detail shows the clicked work ({detail_name})')
check(wp.detail_scroll.isVisible() and wp.detail.isVisible(), 'detail visible without scrolling the page')

# ─── 選取多個並刪除 ──
btn('選取').click()
pump(100)
boxes = [cb for cb in wp.findChildren(QCheckBox) if cb.isVisible()]
check(len(boxes) == len(wp._row_widgets) > 0, 'checkboxes shown in select mode')
keys = list(wp._row_widgets)[:3]
for k in keys:
    wp._row_widgets[k].clicked.emit()                 # 選取模式下點整列 = 勾選
pump(50)
check(wp.picked == set(keys), 'clicking rows picks them')
check(any('已選 3 個作品' in lb.text() for lb in wp.sel_bar.findChildren(QLabel)), 'selection count shown')
btn('刪除選取的紀錄').click()
check(all(k in tr.files for k in keys), 'nothing deleted before confirming')
btn('確定刪除 3 筆').click()
pump(100)
check(not any(k in tr.files for k in keys) and tr.batches[-1] == sorted(keys), 'batch deleted in one call')
check(not any(k in wp._row_widgets for k in keys) and not wp.picked, 'list updated, selection cleared')
wp.search.setText('參考')
pump(50)
btn('全選目前清單').click()
check(wp.picked == {k for k in tr.files if '參考' in k} and len(wp.picked) > 0, 'select all respects the current filter')
btn('清除選取').click()
check(not wp.picked, 'clear selection')
wp.search.setText('')
btn('完成選取').click()
pump(50)
check(not wp.sel_bar.isVisible() and not [cb for cb in wp.findChildren(QCheckBox) if cb.isVisible()], 'leave select mode')

# ─── 不記錄的資料夾：輸入名稱 ──
btn('不記錄的資料夾').click()
pump(50)
check(wp.excl_card.isVisible(), 'exclusion panel opens')
wp.excl_edit.setText('下載')
btn('加入').click()
check(s.get('exclude_folders') == [{'kind': 'folder', 'value': '下載'}], 'folder rule saved')
check(ctl.service.is_excluded('Artist _ 下載 _ new.png'), 'applies to tracking immediately')
n_dl = len([k for k in tr.files if '下載' in k])
check(any(f'有 {n_dl} 筆舊紀錄' in lb.text() for lb in wp.excl_card.findChildren(QLabel)), 'shows old records in that folder')
rm = next(b for b in wp.excl_card.findChildren(QPushButton) if b.toolTip() == '恢復記錄這個資料夾')
rm.click()
pump(50)
check(s.get('exclude_folders') == [], 'rule removed')

# ─── 從作品詳細資料排除這個資料夾，並刪除舊紀錄 ──
ref = next(k for k in tr.files if '下載' in k)
wp._show(ref)
pump(50)
btn('不再記錄這個資料夾').click()
pump(50)
btn(f'停止記錄並刪除 {n_dl} 筆').click()
pump(100)
check(s.get('exclude_folders') == [{'kind': 'prefix', 'value': 'Artist _ 下載'}], 'prefix rule from the work')
check(not any('下載' in k for k in tr.files) and '下載' not in (wp.selected or ''), 'old records in that folder deleted')
check(any('不再記錄' in x for x in said), 'pet confirms')

mw.close()
ctl.quit()
A.release_widgets(qapp)
done()
