# -*- coding: utf-8 -*-
"""1.x 開啟又關閉後（2.0 暫停 → 繼續），在已開著的每日任務頁重新啟用每日任務要能生效：
快捷面板、今日頁看到的是同一份資料，存檔也不會被舊資料蓋回去；暫停期間頁面是唯讀的。以暫存資料夾執行"""
import json
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from core import companion, settings2  # noqa: E402
from ui2 import app as A  # noqa: E402
from ui2.widgets import ToggleSwitch  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


class FakeTracker:
    def __init__(self, *a, **k):
        self.locked_file = None
        self._persist = {'aliases': {}}

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': None, 'raw_current_file': None, 'session_draw': 0.0, 'files': {}}

    def get_draw_counter(self):
        return 0.0

    def today_draw_seconds(self):
        return 0.0

    def daily_history(self):
        return {}

    def resolve_alias(self, n):
        return n


qapp = QApplication(sys.argv[:1])
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.save()
legacy = [False]
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: legacy[0])
ctl.say = lambda *a, **k: None
ctl.start()
pump(150)


def set_legacy(on):
    legacy[0] = on
    ctl.service._last_legacy = -1e9
    ctl._tick()
    pump(80)


def page():
    return ctl._main.page_widget('每日任務', 'QuestsPage')


def enabled_toggle(p):
    return p.findChildren(ToggleSwitch)[0]


ctl.open_main('每日任務')
pump(300)
enabled_toggle(page()).setChecked(False)          # 先關閉每日任務
pump(50)
check(not ctl.service.quests.settings['enabled'], 'quests turned off')

set_legacy(True)                                  # 1.x 開啟 → 暫停：頁面變唯讀
check(ctl.service.paused and page().readonly and not enabled_toggle(page()).isEnabled(), 'read-only while 1.x runs')
check(any('1.x 正在執行' in lb.text() for lb in page().findChildren(QLabel)), 'explains why')

set_legacy(False)                                 # 1.x 關閉 → 繼續：頁面恢復可編輯
p = page()
check(not p.readonly and enabled_toggle(p).isEnabled(), 'editable again after 1.x exits')
check(p.q is ctl.service.quests, 'page uses the live quest data')
enabled_toggle(p).setChecked(True)                # 重新啟用
pump(50)
check(ctl.service.quests.settings['enabled'], 'service sees quests enabled again')
for _ in range(3):
    ctl._tick()
ctl.service.quests.mark_dirty()
ctl.service.quests.save(force=True)
check(json.load(open(s.quests_path, encoding='utf-8'))['settings']['enabled'] is True, 'saved, not overwritten')
check(ctl.service.today_tasks(), 'today has tasks')
ctl.toggle_panel()
pump(200)
check('每日任務' in [lb.text() for lb in ctl.panel.findChildren(QLabel)], 'quick panel shows quests again')
ctl.panel.hide()

# 主視窗停在別頁時：下次打開每日任務頁才重建
ctl.open_main('外觀')
pump(100)
set_legacy(True)
ctl.open_main('每日任務')
pump(200)
check(page().readonly, 'rebuilt as read-only when opened during pause')
set_legacy(False)
check(not page().readonly, 'and editable after resume')

ctl._main.close()
ctl.quit()
A.release_widgets(qapp)
done()
