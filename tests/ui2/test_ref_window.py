# -*- coding: utf-8 -*-
"""2.0 參考小窗與控制中心：研究（參考圖、步驟、穿透、膠囊、比對、練習畫布、打卡推進課程）、
速寫（本機圖庫、倒數計張、換題目不計入任務、缺圖源時提醒設定）、控制中心今日 / 練習頁。
參考圖來源與 SAI2 畫布擷取都以假資料代替，不連網、不開啟 SAI2。"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from core import companion, settings2  # noqa: E402
from ui2 import app as A, ref_window as RW, theme  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


def wait(cond, ms=4000):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


class FakeTracker:
    def __init__(self, data_path, idle_timeout, track_unsaved):
        self.counter = 0.0

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': 'a.psd', 'raw_current_file': 'a.psd', 'session_draw': 0.0,
                'files': {}}

    def get_draw_counter(self):
        return self.counter

    def today_draw_seconds(self):
        return 600.0

    def daily_history(self):
        return {}


REF = Image.new('RGB', (512, 625), (180, 150, 120))
fetched = []
RW.study_refs.fetch_reference = lambda lesson, settings, exclude=None, rng=None: (
    fetched.append(lesson['id']) or REF.copy(),
    {'id': f'fake:{len(exclude or ())}', 'title': '測試肖像', 'artist': 'Test', 'date': '1900', 'source': 'Fake Museum',
     'url': 'https://example.com/x', 'license': '公有領域'})
CANVAS = Image.new('RGB', (400, 300), (90, 120, 200))
RW.RefWindow._capture = lambda self: CANVAS.copy()

qapp = QApplication(sys.argv[:1])
qapp.setStyleSheet(theme.QSS)
d = tmpdir()
lib = os.path.join(d, 'refs')
os.makedirs(os.path.join(lib, 'Hands'))
for i in range(5):
    Image.new('RGB', (300, 400), (i * 40, 80, 80)).save(os.path.join(lib, 'Hands', f'{i}.jpg'))
s = settings2.Settings2(d)
s.set('prompted', {'welcome': True, 'legacy_watcher': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.set('study.canvas_dir', os.path.join(d, 'canvas'))
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
said, opened = [], []
ctl.say = lambda text, actions=(), important=True, seconds=6.0: said.append((text, [a[0] for a in actions]))
ctl.open_path = opened.append
ctl.focus_sai2 = lambda: True
ctl.start()
pump(200)
q = ctl.service.quests

# ─── 研究 ──
q.path_state('color')['index'] = 1
task = q.add_today('t_st_color')
ctl.toggle_panel()
pump(100)
ctl.panel.quest_list._go(task['uid'])
w = ctl.ref_win
check(w is not None and w.kind == 'study' and q.active_study == task['uid'], 'go opens study mini window + timer')
check(wait(lambda: w.base is not None) and fetched == ['color_2'], 'reference fetched')
check(task['ref']['title'] == '測試肖像' and os.path.isfile(task['ref']['cache']), 'reference cached on task')
check(w.width() <= 300 and w.tools['palette'], f'small window + lesson tools ({w.width()})')
ctl._tick()
check('/' in w.info.left and '分' in w.info.right, f'info line {w.info.left} | {w.info.right}')
w.toggle_expand()
pump(50)
texts = ' '.join(lb.text() for lb in w.steps.findChildren(QLabel))
check(w.steps.isVisible() and '學習重點' in texts and '完成檢查' in texts, 'steps expand')
w.toggle_expand()
said.clear()
w.mode.info()
task['progress'] = 6 * 60
w.mode.info()
check(any('進入' in t for t, _a in said), 'phase change announced by pet')
w.set_click_through(True)
check(w.click_through and w.windowOpacity() < 0.9, 'click-through on')
w.set_click_through(False)
check(not w.click_through and w.windowOpacity() > 0.95, 'click-through off')
w.toggle_compare_sticky()
check(w.view.compare is not None and '我的畫布' in w.info.left, 'compare overlay')
w.toggle_compare_sticky()
check(w.view.compare is None, 'compare off')
w.to_capsule()
check(not w.isVisible() and w.capsule.isVisible() and w.capsule.text, 'capsule')
ctl._on_hotkey(-1)
w.restore_from_capsule()
check(w.isVisible() and not w.capsule.isVisible(), 'restored')
s.set('study.canvas_side', 1500)
w.mode.canvas_action()
check(opened and opened[-1].endswith('.psd') and Image.open(opened[-1]).size == (1229, 1500) and task['canvas'] == opened[-1],
      f'practice canvas uses preset size {opened}')
first = opened[-1]
w.mode.canvas_action()
check(opened[-1] == first and len([f for f in os.listdir(os.path.dirname(first))]) == 1, 'second press reopens same canvas')
from PySide6.QtCore import QEvent  # noqa: E402
btn = w.action_btns['canvas']
w.eventFilter(btn, QEvent(QEvent.Enter))
check('練習畫布' in w.info.hint, 'hover shows button description in info line')
w.eventFilter(btn, QEvent(QEvent.Leave))
check(w.info.hint == '', 'hint cleared')
check(w.width() >= w.bottom.sizeHint().width(), 'window wide enough for action bar')
task['progress'] = task['target']
task['status'] = 'ready'
w.mode.checkin()
pump(50)
check(w.sheet.isVisible() and w.width() >= 340, 'check-in sheet slides in (window widened)')
w.sheet._pick(4)
w.sheet.note.setText('冷暖有抓到')
w.sheet.ok.click()
pump(100)
check(task['status'] == 'done' and task['rating'] == 4 and task['advanced_to'] == 'color_3', 'rated check-in advances lesson')
check(task.get('snapshot') and os.path.isfile(task['snapshot']), 'check-in snapshot saved')
check(ctl.ref_win is None and q.active_study is None, 'window closed, study timer stopped')

# ─── 速寫：沒有圖源 → 提醒設定 ──
said.clear()
ctl.open_ref('sketch', None)
pump(300)
check(any('設定圖源' in a for _t, a in said), f'missing source asks to set up {said}')
ctl.ref_win.close()

# ─── 速寫：任務題目對應到本機子資料夾 ──
s.set('sources.local_dir', lib)
s.save()
sk = q.add_today('t_sk_hands')
action, _msg = ctl.service.go(sk['uid'])
check(action == 'open_sketch', 'sketch go action')
w = ctl.open_ref('sketch', sk['uid'])
check(w.mode.opts['local_category'] == 'Hands' and w.mode.session.interval == 90, f'quest topic resolved {w.mode.opts}')
check(wait(lambda: w.base is not None), 'sketch image loaded')
check(w.width() >= max(w.top.sizeHint().width(), w.bottom.sizeHint().width()), 'sketch bars fit (min width)')
w.mode.toggle_pause()
check(w.mode.session.paused, 'pause')
w.mode.toggle_pause()
w.mode.session.remaining = 1
w.mode.tick()
check(q.task(sk['uid'])['progress'] == 1, 'countdown reaching zero counts one')
check(wait(lambda: len(w.mode.session.history) == 2), 'next image loaded automatically')
w.mode.next()
check(q.task(sk['uid'])['progress'] == 1, 'skipping early does not count')
w.mode.settings_menu()
pump(50)
opt = w.options
check(opt.isVisible() and w.width() >= 300 and not w.top.isVisible(), 'settings open inside the window (not a popup)')
from PySide6.QtWidgets import QComboBox, QPushButton  # noqa: E402
combos = opt.findChildren(QComboBox)
iv = next(c for c in combos if c.findData(30) >= 0)
iv.setCurrentIndex(iv.findData(30))
healed = []
orig_heal, orig_popup = w.heal_topmost, A.QApplication.activePopupWidget
w.heal_topmost = lambda: healed.append(1)
A.QApplication.activePopupWidget = staticmethod(lambda: iv)
ctl._heal()
check(not healed, 'no re-topmost while a dropdown / menu is open (it would cover the dropdown)')
A.QApplication.activePopupWidget = orig_popup
ctl._heal()
check(healed, 're-topmost resumes after the dropdown closes')
w.heal_topmost = orig_heal
next(b for b in opt.findChildren(QPushButton) if b.text() == '套用').click()
pump(50)
check(not opt.isVisible() and w.mode.uid is None and s.get('sketch.interval') == 30 and w.mode.session.interval == 30,
      'apply: interval changed, detached from quest, remembered')
w.mode.session.remaining = 1
w.mode.tick()
check(q.task(sk['uid'])['progress'] == 1, 'detached practice not counted to quest')
w.mode.finish()
pump(100)
check(ctl.ref_win is None, 'finish closes')

# ─── 主視窗（控制中心＋設定） ──
ctl.open_control_center()
pump(300)
cc = ctl._main
labels = ' '.join(lb.text() for lb in cc.pages['今日'].findChildren(QLabel))
check(cc.isVisible() and '今日任務' in labels and 'SAI2' in labels and '本週動筆' in labels and '連續天數' in labels, 'today page')
check(any(type(x).__name__ == 'QuestList' for x in cc.pages['今日'].findChildren(RW.QWidget)), 'shared quest list')
cc.show_page('練習')
pump(200)
labels = ' '.join(lb.text() for lb in cc.pages['練習'].findChildren(QLabel))
check('學習路徑' in labels and '速寫' in labels and '今天的練習' in labels, 'practice page')
before = len(q.today_tasks())
cc._study_path('value')
check(ctl.ref_win is not None and ctl.ref_win.kind == 'study' and len(q.today_tasks()) == before + 1, 'study from path')
cc._study_path('value')
check(len(q.today_tasks()) == before + 1, 'reuses today study task for same path')
ctl.ref_win.close()
check(not cc.nav['課程'].isEnabled() and cc.nav['練習'].isEnabled(), 'later pages disabled')
ctl.open_settings('參考圖來源')
pump(200)
labels = ' '.join(lb.text() for lb in cc.pages['參考圖來源'].findChildren(QLabel))
check(cc.current == '參考圖來源' and '畫布尺寸' in labels and 'Pexels' in labels, 'sources settings page in the same window')
for name in ('一般', '寵物', '快捷鍵'):
    cc.show_page(name)
    pump(100)
    check(cc.pages[name].findChildren(QLabel), f'{name} page builds')
cc.close()
ctl.quit()
A.release_widgets(qapp)
done()
