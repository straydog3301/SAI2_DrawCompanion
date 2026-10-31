# -*- coding: utf-8 -*-
"""「工具」頁的隱藏浮動檢視：選了這個錄製範圍才顯示「SAI2「新增浮動檢視」的快捷鍵」；沒設定、和 2.0 自己的快捷鍵相同時提醒；
錄影器的問題訊息會由寵物說出來。以暫存資料夾執行，不開啟 SAI2"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from core import companion, settings2  # noqa: E402
from ui2 import app as A  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


class FakeTracker:
    def __init__(self, *a, **k):
        self.locked_file = None

    def start(self): pass
    def stop(self): pass

    def get_state(self):
        return {'sai2_running': False, 'current_file': None, 'raw_current_file': None, 'session_draw': 0.0,
                'files': {}, 'raw_title': ''}

    def get_draw_counter(self): return 0.0
    def today_draw_seconds(self): return 0.0
    def daily_history(self): return {}
    def resolve_alias(self, n): return n


qapp = QApplication(sys.argv[:1])
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True, 'practice_card': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.set('hotkeys.sketch_next', 'Ctrl+Alt+N')
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
said = []
ctl.say = lambda text, actions=(), important=True, seconds=6.0: said.append((text, [a[0] for a in actions]))
ctl.start()
pump(150)
ctl.open_main('工具')
pump(300)
tp = ctl._main.page_widget('工具', 'ToolsPage')
combo = next(cb for cb in tp.findChildren(QComboBox) if cb.findData('canvas_float') >= 0)
check(not tp.float_row.isVisible(), 'hidden for paper-only recording')
combo.setCurrentIndex(combo.findData('canvas_float'))
pump(50)
check(tp.float_row.isVisible() and s.get('timelapse.target') == 'canvas_float', 'shown for the floating-view mode')
check('還沒設定' in tp.float_row.note.text(), 'not set yet → explained')
tp.float_key.setKeySequence(QKeySequence('Ctrl+Alt+N'))
tp._float_key_changed()
check(s.get('timelapse.float_hotkey') == 'Ctrl+Alt+N' and '速寫：下一張' in tp.float_row.note.text(),
      "same as 2.0's sketch hotkey → warned")
check(ctl.service.recorder.float_keys is None, 'clashing key not sent')
tp.float_key.setKeySequence(QKeySequence('Ctrl+Shift+N'))
tp._float_key_changed()
check(tp.float_row.note.text() == '' and ctl.service.recorder.float_keys == [0x11, 0x10, 0x4E], 'valid key used')
s.set('hotkeys.sketch_next', 'Ctrl+Shift+N')
ctl.apply_hotkeys()
check(ctl.service.recorder.float_keys is None, "changing 2.0's hotkeys rechecks the clash")

# 錄影器的問題由寵物說；正常狀態不打擾
ctl.service._on_rec_status('📹 已建立隱藏浮動檢視，鎖定錄製中')
ctl.service._on_rec_status('⚠️ 無法建立浮動檢視：請確認 SAI2「新增浮動檢視」的快捷鍵和設定的相同。這次改用只錄畫紙')
n = len(said)
ctl._tick()
new = said[n:]
check(len(new) == 1 and new[0][0].startswith('無法建立浮動檢視') and new[0][1] == ['錄影設定'], f'only problems shown ({new})')

ctl._main.close()
ctl.quit()
A.release_widgets(qapp)
done()
