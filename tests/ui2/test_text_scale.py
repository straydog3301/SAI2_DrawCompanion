# -*- coding: utf-8 -*-
"""文字大小（設定 › 外觀）：字級與放文字的元件一起縮放；75%～150% 時每一頁、快捷面板都沒有被截斷的文字
（150% 的文字約寬 50%，也大致模擬之後英文、日文較長的情況）；在外觀頁切換時立刻套用。以暫存資料夾與假的追蹤器執行"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import check, done, tmpdir  # noqa: E402
from clip_check import clipped  # noqa: E402

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from core import companion, settings2, works  # noqa: E402
from ui2 import app as A, main_window as MW, quick_panel as QP, theme  # noqa: E402

KEY = '本機磁碟 (D:) _ art _ 一張很長名稱的作品測試.sai2'


class FakeTracker:
    def __init__(self, *a, **k):
        self.locked_file = None
        self._persist = {'aliases': {}}

    def start(self): pass
    def stop(self): pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': KEY, 'raw_current_file': KEY, 'session_draw': 120.0,
                'files': {KEY: {'open_seconds': 6000.0, 'draw_seconds': 3000.0, 'sessions': 3,
                                'last_seen': '2026-10-28T10:00:00'}}}

    def get_draw_counter(self): return 0.0
    def today_draw_seconds(self): return 1800.0
    def daily_history(self): return {'2026-10-27': 3600.0}
    def resolve_alias(self, n): return n


qapp = QApplication(sys.argv[:1])


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


def make(scale):
    s = settings2.Settings2(tmpdir())
    s.set('prompted', {'welcome': True, 'legacy_watcher': True, 'practice_card': True})
    s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
    s.set('theme.text_scale', scale)
    s.save()
    vdir = works.video_dir(s.videos_dir, KEY)
    os.makedirs(vdir, exist_ok=True)
    for n in ('20261026_100000.mp4', '20261027_100000.mp4'):
        open(os.path.join(vdir, n), 'w').close()
    ctl = A.CompanionApp(qapp, s)
    ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
    ctl.say = lambda *a, **k: None
    ctl.start()
    pump(150)
    return s, ctl


def close(ctl):
    if ctl._main is not None:
        ctl._main.close()
    ctl.quit()
    A.release_widgets(qapp)
    pump(50)


check(theme.px(10) == 10, 'default 100%')
for scale in (0.75, 1.5):
    s, ctl = make(scale)
    check(theme.SCALE == scale and theme.px(20) == round(20 * scale), f'{scale}: scale applied at startup')
    problems = []
    for page in [n for n, *_ in MW.NAV_MAIN] + [n for n, _ in MW.NAV_SETTINGS]:
        ctl.open_main(page)
        ctl._main.resize(1200, 800)
        pump(150)
        if page == '作品':
            ctl._main.page_widget('作品', 'WorksPage')._show(KEY)       # 詳細資料（含縮時影片的合併、匯出）
            pump(100)
        problems += [f'{page}: {p}' for p in clipped(ctl._main.pages[page])]
    ctl.toggle_panel()
    pump(250)
    problems += [f'快捷面板: {p}' for p in clipped(ctl.panel)]
    check(not problems, f'{int(scale * 100)}%: no clipped text ({problems[:6]})')
    close(ctl)

# ─── 在外觀頁切換：立刻套用 ──
s, ctl = make(1.0)
ctl.open_main('外觀')
pump(200)
combo = next(cb for cb in ctl._main.pages['外觀'].findChildren(QComboBox) if cb.findText('125%') >= 0)
combo.setCurrentIndex(combo.findText('125%'))
pump(300)
check(s.get('theme.text_scale') == 1.25 and theme.SCALE == 1.25, 'saved and applied')
check(ctl._main.current == '外觀' and 'font-size: 16px' in qapp.styleSheet(), 'main window rebuilt on the same page, bigger text')
check(ctl.panel.card.width() == theme.size(QP.PANEL_W), 'quick panel widened')
close(ctl)
theme.apply('purple', 'dark', 1.0)
done()
