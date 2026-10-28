# -*- coding: utf-8 -*-
"""控制中心被最小化後，再從寵物面板打開：還原成原本的視窗（原本最大化就最大化）、回到最上層、切到指定頁面"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

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
        return {'sai2_running': False, 'current_file': None, 'raw_current_file': None, 'session_draw': 0.0, 'files': {}}

    def get_draw_counter(self): return 0.0
    def today_draw_seconds(self): return 0.0
    def daily_history(self): return {}
    def resolve_alias(self, n): return n


qapp = QApplication(sys.argv[:1])
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True, 'practice_card': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
ctl.start()
pump(150)

ctl.open_control_center('今日')
pump(200)
mw = ctl._main
mw.showMinimized()
pump(300)
check(mw.isMinimized(), 'minimized')
ctl.open_control_center('成長')
pump(300)
check(not mw.isMinimized() and mw.isVisible() and not mw.isMaximized(), 'restored as a normal window')
check(mw.current == '成長', 'and shows the requested page')

mw.showMaximized()
pump(300)
mw.showMinimized()
pump(300)
ctl.open_control_center('今日')
pump(300)
check(not mw.isMinimized() and mw.isMaximized(), 'maximized before minimizing → back to maximized')

mw.close()
ctl.quit()
A.release_widgets(qapp)
done()
