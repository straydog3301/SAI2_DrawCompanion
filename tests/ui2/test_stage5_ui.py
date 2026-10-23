# -*- coding: utf-8 -*-
"""2.0 階段五介面：「30 秒調整你的練習」卡片、使用 3 天後的提醒、第一部影片的位置提示、
對比（每個主題的文字組合 ≥ 4.5）、鍵盤操作（Tab 焦點、Ctrl+Tab 換頁、側欄上下鍵）、只有圖示的按鈕有報讀名稱、減少動態。
以暫存資料夾與假的追蹤器執行"""
import os
import sys
import time
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QLineEdit, QPushButton  # noqa: E402

from core import companion, onboarding as OB, settings2  # noqa: E402
from ui2 import app as A, theme  # noqa: E402
from ui2.quick_panel import PracticeCard  # noqa: E402
from ui2.widgets import NavButton, ToggleSwitch  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


HIST = {}


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
        return dict(HIST)

    def resolve_alias(self, n):
        return n


# ─── 對比：每個主題的文字組合 ──
bad = []
for mode in ('dark', 'light'):
    for acc in theme.ACCENTS:
        theme.apply(acc, mode)
        for fg, bg in theme.TEXT_PAIRS:
            c = fg if fg.startswith('#') else getattr(theme, fg)
            r = theme.contrast(c, getattr(theme, bg))
            if r < 4.5:
                bad.append(f'{mode}/{acc} {fg} on {bg} = {r:.2f}')
        for level in (1, 2, 3):                        # 月曆熱度格上的日期數字
            cell = theme.HEAT[level]
            col = theme.on_color(cell) if level >= 2 else theme.TEXT
            if theme.contrast(col, cell) < 4.5:
                bad.append(f'{mode}/{acc} heat {level} = {theme.contrast(col, cell):.2f}')
check(not bad, f'all text pairs pass WCAG AA {bad[:4]}')
check(abs(theme.contrast('#ffffff', '#000000') - 21) < 0.01 and theme.on_color('#ffffff') != '#ffffff', 'contrast helper')

qapp = QApplication(sys.argv[:1])
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
said = []
ctl.say = lambda text, actions=(), important=True, seconds=6.0: said.append((text, [a[0] for a in actions], actions))
ctl.start()
pump(150)

# ─── 30 秒調整你的練習 ──
ctl.toggle_panel()
pump(200)
cards = ctl.panel.findChildren(PracticeCard)
check(len(cards) == 1, 'practice card on first panel open')
card = cards[0]
check(card.minutes.value == '60' and card.focus.count() == 1 + len(ctl.service.quests.data['skills']), 'defaults')
card.minutes.set_value('20', emit=True)
card.focus.setCurrentIndex(card.focus.findData('color'))
next(b for b in card.findChildren(QPushButton) if b.text() == '套用').click()
pump(100)
q = ctl.service.quests
check(q.settings['budget_minutes'] == 20 and q.settings['weekly_focus'] == 'color', 'card applied')
check(s.was_prompted(OB.KEY_PRACTICE) and not ctl.panel.findChildren(PracticeCard), 'card gone after answering')
check(any('任務' in t for t, _a, _f in said), 'pet confirms')
ctl.panel.hide()
s.data['prompted'].pop(OB.KEY_PRACTICE)
ctl.panel.hidden_at = 0
ctl.toggle_panel()
pump(150)
next(b for b in ctl.panel.findChildren(QPushButton) if b.text() == '略過').click()
pump(50)
check(s.was_prompted(OB.KEY_PRACTICE) and q.settings['budget_minutes'] == 20, 'skip keeps settings')
ctl.panel.hide()

# ─── 使用 3 天後：建議練習時間，之後問開機啟動 ──
now = datetime.now()
s.set('first_run_at', (now - timedelta(days=4)).isoformat(timespec='seconds'))
for i in range(1, 5):
    HIST[(now - timedelta(days=i)).strftime('%Y-%m-%d')] = 70 * 60
said.clear()
ctl.autostart_enabled = lambda: False
check(ctl._usage_prompt(), 'day-3 prompt shown')
text, labels, acts = said[-1]
check('60' in text and labels[0] == '改成 60 分', f'budget 20 but draws ~70 → suggests 60 ({text})')
acts[0][1]()
check(q.settings['budget_minutes'] == 60, 'suggestion applied')
said.clear()
turned = []
ctl.set_autostart = lambda on: turned.append(on)
check(ctl._usage_prompt() and '開機' in said[-1][0], 'then asks about autostart')
said[-1][2][0][1]()
check(turned == [True], 'autostart turned on from bubble')
check(not ctl._usage_prompt(), 'nothing more to ask')

# ─── 第一部影片：告訴使用者放在哪裡 ──
said.clear()
ctl._on_export(100, 'ok')
check(s.videos_dir in said[-1][0] and '更改位置' in said[-1][1], 'first video shows folder')
ctl._on_export(100, 'ok')
check(said[-1][0] == '縮時影片完成了！', 'later videos: short message')

# ─── 鍵盤與報讀 ──
ctl.open_main('今日')
pump(300)
mw = ctl._main
mw.show()
pump(100)
buttons = [b for b in mw.findChildren(QAbstractButton) if b.isVisible()]
check(all(b.focusPolicy() == Qt.TabFocus for b in buttons), 'buttons focus by Tab only')
unnamed = [b for b in buttons if not b.text().strip() and not b.accessibleName()]
check(not unnamed, f'icon-only buttons have names {[b.toolTip() for b in unnamed][:3]}')
mw.cycle_page(1)
check(mw.current == '練習', f'Ctrl+Tab → next page ({mw.current})')
mw.cycle_page(-2)
check(mw.current == '快捷鍵', 'wraps around backwards')
nav = mw.nav['快捷鍵']
qapp.sendEvent(nav, QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier))
check(mw.current == '今日', 'arrow key in sidebar moves')
qapp.sendEvent(mw.nav['今日'], QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier))
check(mw.current == '快捷鍵', 'arrow up')

# 滑鼠點按鈕時，輸入框的內容仍會確定（editingFinished）
mw.show_page('寵物')
pump(200)
pp = mw.page_widget('寵物', 'PetPage')
ed = QLineEdit(pp)
ed.show()
fired = []
ed.editingFinished.connect(lambda: fired.append(ed.text()))
mw.activateWindow()
ed.setFocus()
pump(50)
QTest.keyClicks(ed, 'abc')
btn = next(b for b in mw.findChildren(NavButton) if b.text().strip() == '寵物')   # 點目前這頁的側欄，不會換頁
QTest.mouseClick(btn, Qt.LeftButton)
pump(50)
check(fired == ['abc'], f'typed text committed when clicking a button ({fired})')

# 減少動態
mw.show_page('外觀')
pump(200)
s.set('theme.reduce_motion', False)
tg = [t for t in mw.pages['外觀'].findChildren(ToggleSwitch)][-1]
tg.setChecked(True)
check(theme.MOTION is False and s.get('theme.reduce_motion'), 'reduce motion on')
t2 = ToggleSwitch(False)
t2.setChecked(True)
check(t2._anim.duration() == 0, 'switch animation off')
tg.setChecked(False)
check(theme.MOTION is True, 'reduce motion off')

mw.close()
ctl.quit()
A.release_widgets(qapp)
done()
