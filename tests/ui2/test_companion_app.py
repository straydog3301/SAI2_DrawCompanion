# -*- coding: utf-8 -*-
"""2.0 介面：寵物狀態切換、快捷面板（任務、回報、打卡、最近開啟、快捷按鈕）、設定視窗、隱藏與快捷鍵
以暫存資料夾與假的追蹤器執行，不碰使用者的紀錄；不會開啟 SAI2。"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QLineEdit, QSpinBox, QToolButton  # noqa: E402

from core import companion, settings2  # noqa: E402
from ui2 import app as A, theme  # noqa: E402


def pump(qapp, ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


class FakeTracker:
    def __init__(self, data_path, idle_timeout, track_unsaved):
        self.counter, self.sai2 = 0.0, False
        self.raw = None
        self.files = {'本機磁碟 (D:) _ art _ 立繪.psd': {'last_seen': '2026-10-23T09:00:00', 'draw_seconds': 600}}

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self):
        return {'sai2_running': self.sai2, 'current_file': None if self.raw else ('本機磁碟 (D:) _ art _ 立繪.psd' if self.sai2 else None),
                'raw_current_file': self.raw, 'session_draw': 0.0, 'files': self.files}

    def get_draw_counter(self):
        return self.counter

    def today_draw_seconds(self):
        return 22 * 60.0

    def daily_history(self):
        return {}


qapp = QApplication(sys.argv[:1])
qapp.setStyleSheet(theme.QSS)
d = tmpdir()
s = settings2.Settings2(d)
s.set('hotkeys', {'panel': 'Ctrl+Alt+Shift+F11', 'toggle_pet': '', 'open_sai2': '', 'snapshot': ''})
s.save()
legacy = {'on': False}
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: legacy['on'])
said = []
orig_say = ctl.say
ctl.say = lambda text, actions=(), important=True, seconds=6.0: (said.append(text), orig_say(text, actions, important, seconds))
ctl.start()
pump(qapp, 300)
check(ctl.pet.isVisible() and ctl._pet_state == 'offline' and ctl.pet.frames, f'pet shown offline {ctl._pet_state}')
check(ctl.pet.width() == 128, f'pet logical size {ctl.pet.width()}')
pump(qapp, 900)
check(any('點我打開快捷面板' in t for t in said), 'welcome bubble on first run')

# SAI2 開啟 → 動筆
tr = ctl.service.tracker
tr.sai2 = True
ctl._tick()
check(ctl._pet_state == 'idle', f'idle when SAI2 open {ctl._pet_state}')
tr.counter += 5
ctl._tick()
check(ctl._pet_state == 'drawing' and ctl.pet.windowOpacity() < 0.9, 'drawing + faded')

# 未存檔提醒（只提醒一次）
tr.raw = '新建畫布 1'
tr.counter += 5
ctl._tick()
tr.counter += 5
ctl._tick()
check(sum('還沒存檔' in t for t in said) == 1 and ctl._pet_state == 'remind', 'unsaved reminder once')
tr.raw = None

# 快捷面板
ctl.toggle_panel()
pump(qapp, 200)
p = ctl.panel
check(p.isVisible(), 'panel opens')
texts = [b.text() for b in p.findChildren(QPushButton)]
tips = [b.toolTip() for b in p.findChildren(QPushButton)]
check(any('立繪.psd' in t for t in tips), f'recent file listed (name in tooltip) {tips}')
check(any(t in ('開始', '繼續', '打卡') for t in texts), 'quest buttons')
slots = {b.text(): b.isEnabled() for b in p.findChildren(QToolButton) if b.property('slot')}
check(slots.get('快照') and slots.get('SAI2') and slots.get('速寫') and slots.get('錄影'), f'slot availability {slots}')
check('22 / 60 分' in ' '.join(lb.text() for lb in p.findChildren(QLabel)), 'today progress header')

q = ctl.service.quests
count_task = next((t for t in q.today_tasks() if t['mode'] in ('drill', 'thumbnail')), None)
if count_task is None:                                # 讓測試穩定涵蓋回報流程
    count_task = q.add_today(next(t['id'] for t in q.data['templates'] if t['mode'] == 'drill'))
    p.refresh()
ql = p.quest_list
ql._go(count_task['uid'])
spin = p.findChildren(QSpinBox)
check(spin, 'inline count editor (no dialog)')
spin[0].setValue(count_task['target'])
ql = p.quest_list
ql._commit_count(count_task['uid'], spin[0].value())
check(q.task(count_task['uid'])['status'] == 'ready' and any('達標' in t for t in said), 'count -> ready + bubble')
ql._open_inline(count_task['uid'], 'checkin')
note = p.findChildren(QLineEdit)
check(note, 'inline check-in editor')
ql._commit_checkin(count_task['uid'], '手感不錯', False, False)
check(q.task(count_task['uid'])['status'] == 'done' and any('已打卡' in t for t in said), 'checked in')
check(ctl.brain._override and ctl.brain._override[0] == 'cheer', 'cheer animation')

dt = next((t for t in q.today_tasks() if t['mode'] == 'draw_time' and t['status'] == 'active'), None)
if dt:
    p.quest_list._go(dt['uid'])
    check(any('自動累計' in t for t in said), 'draw_time go message')
p.hide()

# 1.x 執行中 → 暫停
legacy['on'] = True
ctl.brain._override = None
ctl.service._last_legacy = -1e9
ctl._tick()
check(ctl.service.paused and ctl._pet_state == 'sleep' and any('1.x' in t for t in said), 'paused for 1.x')
ctl.toggle_panel()
pump(qapp, 100)
check(any('暫停記錄' in lb.text() for lb in p.findChildren(QLabel)), 'panel shows paused banner')
p.hide()
legacy['on'] = False
ctl.service._last_legacy = -1e9
ctl._tick()
check(not ctl.service.paused, 'resumed')

# 設定：換大小、換角色資料夾（自訂角色只有一張 idle）
ctl.open_settings('寵物')
pump(qapp, 200)
mw = ctl._main
check(mw.isVisible() and mw.current == '寵物', 'settings open inside the main window (pet page)')
from ui2.settings_pages import PetPage  # noqa: E402
w = mw.pages['寵物'].findChild(PetPage)
s.set('pet.size', 96)
ctl.apply_pet_settings(reload_frames=True)
check(ctl.pet.width() == 96, f'size applied {ctl.pet.width()}')
from PIL import Image  # noqa: E402
os.makedirs(os.path.join(s.pets_dir, 'mine'))
Image.new('RGBA', (256, 256), (255, 0, 0, 255)).save(os.path.join(s.pets_dir, 'mine', 'idle.png'))
w._reload_packs()
check(w.pack_combo.count() == 2, 'custom pack listed')
w.pack_combo.setCurrentIndex(1)
pump(qapp, 100)
check(s.get('pet.pack') == 'mine' and ctl._pack.pack_id == 'mine', 'custom pack applied')
img = ctl.pet.frames[0][0].toImage()
check(img.pixelColor(img.width() // 2, img.height() - 2).red() == 255, 'custom art drawn')
w.state_combo.setCurrentIndex(6)        # 未連結 → 沿用待命
check('沿用' in w.state_info.text(), f'fallback info {w.state_info.text()}')
mw.show_page('快捷鍵')
pump(qapp, 100)
failed = ctl.apply_hotkeys()
check(isinstance(failed, dict) and 'panel' not in failed, f'hotkeys registered {failed}')
ctl.open_control_center()
check(mw.current == '今日' and mw.nav['今日'].isChecked(), 'control center is the same window')
check(all(b.isEnabled() for b in mw.nav.values()), 'all pages available (stage 3)')
mw.close()

# 隱藏一陣子
ctl.hide_for_a_while()
check(not ctl.pet.isVisible() and ctl._unhide_timer.isActive(), 'hidden with timer')
ctl.show_pet()
check(ctl.pet.isVisible(), 'shown again')
ctl.quit()
check(os.path.isfile(s.quests_path) and os.path.isfile(s.path), 'saved on quit')
A.release_widgets(qapp)
done()
