# -*- coding: utf-8 -*-
"""2.0 階段四介面：面板再點寵物就關閉、寵物下方計時與錄影膠囊、角色工作室、快捷面板編輯與自訂按鈕、
規則、主題切換（主色 / 淺色）、每日任務範本與技能、設定匯出匯入。以暫存資料夾與假的追蹤器、錄影器執行。"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QLineEdit, QPushButton, QToolButton  # noqa: E402

from core import backup, companion, settings2  # noqa: E402
from ui2 import app as A, quests_page as QP, settings_pages as SP, theme  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


class FakeTracker:
    def __init__(self, data_path, idle_timeout, track_unsaved):
        self.counter = 0.0
        self.locked_file = None
        self._persist = {'aliases': {}}

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': '本機磁碟 (D:) _ 色彩練習.psd', 'raw_current_file': None,
                'session_draw': 754.0, 'files': {}}

    def get_draw_counter(self):
        return self.counter

    def today_draw_seconds(self):
        return 1800.0

    def daily_history(self):
        return {}

    def resolve_alias(self, n):
        return n


class FakeRecorder:
    def __init__(self, output_dir, fps):
        self.enabled = False
        self.active_file = None
        self.frame_count = 0
        self.multiplier = 5
        self.total_recorded_duration = 0.0
        self.export_threads = []

    def start(self):
        pass

    def stop(self):
        pass

    def switch_file(self, f):
        self.active_file = f if (f and self.enabled) else None


qapp = QApplication(sys.argv[:1])
d = tmpdir()
s = settings2.Settings2(d)
s.set('prompted', {'welcome': True, 'legacy_watcher': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False,
                                         recorder_factory=FakeRecorder)
said = []
ctl.say = lambda text, actions=(), important=True, seconds=6.0: said.append(text)
ctl.start()
pump(200)

# ─── 1. 面板開著時再點寵物 = 關閉 ──
ctl._pet_clicked()
pump(100)
check(ctl.panel.isVisible(), 'pet click opens panel')
ctl.panel.hide()                 # 點寵物時，彈出面板因為點到外面先自己收起
ctl._pet_clicked()
pump(50)
check(not ctl.panel.isVisible(), 'the same click does not reopen it')
ctl.panel.hidden_at -= 1
ctl._pet_clicked()
check(ctl.panel.isVisible(), 'a later click opens again')
ctl.panel.hide()

# ─── 2. 寵物下方的計時與錄影膠囊 ──
ctl._tick()
cap = ctl.capsule
check(cap.isVisible() and cap.text == '12:34', f'capsule shows session time ({cap.text})')
cap.toggle_record.emit()
ctl._tick()
check(s.get('timelapse.enabled') and cap.recording and cap.rec_active, 'record toggle from capsule')
cap.toggle_record.emit()
check(not s.get('timelapse.enabled'), 'toggle off')
s.set('pet.show_timer', False)
ctl._tick()
check(not cap.isVisible(), 'can be turned off in settings')
s.set('pet.show_timer', True)
ctl.service.paused = True
ctl._tick()
check(cap.text == '暫停（1.x）' and cap.paused, 'shows paused when 1.x runs')
ctl.service.paused = False

# ─── 角色工作室 ──
src = tmpdir()
img = os.path.join(src, 'idle.png')
Image.new('RGBA', (64, 64), (0, 200, 0, 255)).save(img)
ctl.open_main('寵物')
pump(300)
mw = ctl._main
pp = mw.page_widget('寵物', 'PetPage')
labels = ' '.join(lb.text() for lb in pp.findChildren(QLabel))
check('角色工作室' in labels and '不能修改' in labels, 'studio shown, builtin read-only')
pp.new_idle = img
pp.new_name.setText('小綠')
pp._create_pack()
check(s.get('pet.pack') == '小綠' and ctl._pack.name == '小綠', 'create pack switches to it')
check(len([b for b in pp.findChildren(QPushButton) if b.text() in ('指定圖檔', '換圖')]) == 7, 'one row per state')
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (img, ''))
pack = pp._current_pack()
pp._pick_state(pack, 'drawing')
check('drawing' in ctl._pack.states, 'assign a state image')

# ─── 快捷面板編輯 + 自訂按鈕 ──
mw.show_page('快捷面板')
pump(200)
panel_page = mw.page_widget('快捷面板', 'PanelPage')
panel_page._move('slots', -3)
check(s.get('panel.blocks')[0] == 'slots', f"block order {s.get('panel.blocks')}")
panel_page._toggle_block('recent', False)
check('recent' not in s.get('panel.blocks'), 'block turned off')
panel_page._kind_changed(5, 'custom:url')
panel_page._set_slot(5, {'type': 'url', 'label': '靈感', 'target': 'https://example.com'}, rebuild=True)
opened = []
import webbrowser  # noqa: E402
webbrowser.open = opened.append
ctl.toggle_panel()
pump(200)
tb = next(b for b in ctl.panel.findChildren(QToolButton) if b.text() == '靈感')
tb.click()
check(opened == ['https://example.com'], 'custom url slot runs')
labels = [lb.text() for lb in ctl.panel.findChildren(QLabel)]
check('最近開啟' not in labels, 'hidden block not shown')
ctl.panel.hide()

# ─── 規則 ──
mw.show_page('規則')
pump(150)
rp = mw.page_widget('規則', 'RulesPage')
rp._add_examples()
check(len(s.get('rules')) == 4, 'examples added')
rp._add_examples()
check(len(s.get('rules')) == 4, 'examples not duplicated')
first = s.get('rules')[0]
check(len(first['actions']) == 2, 'example rule speaks and acts')
n_acts = len(first['actions'])
next(b for b in rp.findChildren(QPushButton) if b.text() == '＋ 再加一個動作').click()
pump(50)
check(len(s.get('rules')[0]['actions']) == n_acts + 1, 'add another action to the same rule')
said.clear()
ctl.rules.evaluate(s.get('rules'), {'sai2_running': True, 'current_file': None})
ctl._tick()                       # 目前的檔案名稱含「練習」→ 開啟今天的研究（沒有研究任務時寵物會提示）
check(any('研究' in x for x in said) or ctl.ref_win is not None, f'open-file rule ran {said[-2:]}')
if ctl.ref_win is not None:
    ctl.ref_win.close()

# ─── 主題 ──
mw.show_page('外觀')
pump(100)
ctl.set_theme(accent='teal', mode='light')
pump(200)
check(theme.IS_LIGHT and theme.ACCENT == '#14b8a6' and ctl._main is not mw and ctl._main.current == '外觀',
      'theme applied + main window rebuilt')
check(theme.BG in qapp.styleSheet(), 'app stylesheet updated')
custom = s.get('pet.pack')
s.set('pet.pack', '')
ctl.apply_pet_settings(reload_frames=True)
check(ctl._pack.builtin and ctl._pack.tint == theme.PET_BODY, 'built-in pet follows the accent')
s.set('pet.pack', custom)
ctl.apply_pet_settings(reload_frames=True)
ctl.set_theme(accent='purple', mode='dark')
mw = ctl._main

# ─── 每日任務：範本與技能 ──
mw.show_page('每日任務')
pump(200)
qp = mw.page_widget('每日任務', 'QuestsPage')
q = ctl.service.quests
n_before = len(q.data['templates'])
qp._edit('new')
card = qp.editor_box.itemAt(0).widget()
card.findChildren(QLineEdit)[0].setText('手指速寫 20 張')
next(b for b in card.findChildren(QPushButton) if b.property('sid') == 'figure').setChecked(True)
next(b for b in card.findChildren(QPushButton) if b.text() == '儲存').click()
pump(50)
new = [t for t in q.data['templates'] if t['name'] == '手指速寫 20 張']
check(len(q.data['templates']) == n_before + 1 and new and new[0]['skills'] == {'figure': 1.0}, 'template added')
qp._add_skill('背景', '🏞')
sid = next(x['id'] for x in q.data['skills'] if x['name'] == '背景')
check(sid.startswith('u_'), 'custom skill added')
qp._delete_skill(sid)
check(all(x['name'] != '背景' for x in q.data['skills']), 'custom skill deleted')
qp._delete(new[0]['id'])
check(len(q.data['templates']) == n_before, 'custom template deleted')
qp._delete(q.data['templates'][0]['id'])
check(len(q.data['templates']) == n_before and said, 'builtin template cannot be deleted')

# ─── 設定匯出 / 匯入 ──
bundle = os.path.join(src, 'b.zip')
backup.export_bundle(s, bundle)
s.set('theme.accent', 'orange')
s.save()
backup.import_bundle(s, bundle)
ctl.reload_settings()
check(theme.ACCENT_KEY == 'purple' and s.get('pet.pack', '').startswith('小綠'), 'import restores and applies')
mw = ctl._main
mw.close()
ctl.quit()
A.release_widgets(qapp)
done()
