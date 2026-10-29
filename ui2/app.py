# -*- coding: utf-8 -*-
"""
SAI2 DrawCompanion 2.0 主程式（階段一：常駐骨架）

    python drawcompanion2.py                 # 啟動；已有一份在執行時把參數交給它後結束
    python drawcompanion2.py --background    # 開機啟動用
    python drawcompanion2.py --open X.psd    # 在 SAI2 開啟檔案（交給已在執行的那一份）
    python drawcompanion2.py --data-dir D    # 用其他資料夾（開發、測試用，不碰真正的紀錄）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from core import autostart, bubble_skin, hotkeys, onboarding, pet_pack, study_lessons
from core.companion import CompanionService
from core.paths import APP_DIR
from core.pet_state import PetBrain, PetInputs
from core.sai2_launcher import Sai2Opener, Win32Backend
from core.settings2 import Settings2
from core.version import APP_VERSION
from core.single_instance import SingleInstance, channel_name
from ui2 import theme, winutil
from ui2.bubble import Bubble
from ui2.pet_window import PetWindow, to_pixmap
from ui2.quick_panel import PANEL_W, QuickPanel

INSTANCE_NAME = 'SAI2DrawCompanion2'
ENTRY_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'drawcompanion2.py')
HIDE_MINUTES = 30


class Inbox(QObject):
    """第一份程式接收第二份交過來的參數"""
    received = Signal(dict)

    def __init__(self, name: str):
        super().__init__()
        QLocalServer.removeServer(name)
        self.server = QLocalServer(self)
        self.ok = self.server.listen(name)
        self.server.newConnection.connect(self._accept)

    def _accept(self):
        sock = self.server.nextPendingConnection()
        buf = bytearray()

        def _read():
            buf.extend(bytes(sock.readAll()))

        def _done():
            _read()
            try:
                self.received.emit(json.loads(buf.decode('utf-8')))
            except ValueError:
                pass
            sock.deleteLater()
        sock.readyRead.connect(_read)
        sock.disconnected.connect(_done)


def send_to_first(name: str, payload: dict, timeout_ms: int = 3000) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(json.dumps(payload).encode('utf-8'))
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class CompanionApp(QObject):
    open_done = Signal(object, str)          # (OpenResult, 檔名)
    work_done = Signal(object)               # 背景工作完成後要在主執行緒執行的 callable

    def __init__(self, qapp: QApplication, settings: Settings2, background: bool = False):
        super().__init__()
        self.qapp = qapp
        self.settings = settings
        theme.apply(settings.get('theme.accent', 'purple'), settings.get('theme.mode', 'dark'),
                    settings.get('theme.text_scale', 1.0))
        theme.MOTION = not settings.get('theme.reduce_motion', False)
        qapp.setStyleSheet(theme.QSS)
        from ui2 import a11y
        a11y.install(qapp)
        self.service = CompanionService(settings, exe_finder=self._find_exe)
        self.brain = PetBrain(rest_minutes=0)        # 休息提醒、夜間睡覺改用規則（core/rules.py）
        self.backend = Win32Backend()
        self.opener = Sai2Opener(self.backend, exe_path=settings.get('sai2_exe', ''))
        self.last_status = None
        self._pack = None
        self._frames: dict[str, list] = {}
        self._pet_state = None
        self._reminded_unsaved: set[str] = set()
        from core.rules import RuleEngine
        self.rules = RuleEngine()
        self._rule_events: set[str] = set()
        self._main = None
        self.export_state = (None, '')       # 影片合成：(百分比, 訊息)
        self._quitting = False
        self.ref_win = None
        self.open_done.connect(self._on_open_done)
        self.work_done.connect(lambda fn: fn())

        self.pet = PetWindow(os.path.join(settings.app_dir, 'drawcompanion2_pet_pos.json'))
        self.bubble = Bubble()
        self.bubble.anchor = self.pet
        self.apply_bubble_skin()
        self.panel = QuickPanel(self)
        self.pet.clicked.connect(self._pet_clicked)
        from ui2.status_capsule import StatusCapsule
        self.capsule = StatusCapsule()
        self.capsule.anchor = self.pet
        self.capsule.open_panel.connect(self.toggle_panel)
        self.capsule.toggle_record.connect(lambda: self.run_slot('record'))
        self.pet.menu_requested.connect(self._pet_menu)
        self.pet.moved.connect(self._pet_moved)

        self.hub = winutil.HotkeyHub(qapp)
        self.hub.triggered.connect(self._on_hotkey)
        self._hk_ids: dict[int, str] = {}

        self._tray = QSystemTrayIcon(self._tray_icon())
        qapp.setWindowIcon(self._tray.icon())
        menu = QMenu()
        menu.addAction('快捷面板', self.toggle_panel)
        menu.addAction('控制中心', lambda: self.open_control_center())
        menu.addAction('顯示寵物', self.show_pet)
        menu.addAction('設定', lambda: self.open_settings())
        menu.addSeparator()
        menu.addAction(QAction('結束', menu, triggered=self.quit))
        self._tray_menu = menu
        self._tray.setContextMenu(menu)
        self._tray.setToolTip(f'DrawCompanion {APP_VERSION}')
        self._tray.activated.connect(lambda r: self.show_pet() if r == QSystemTrayIcon.Trigger else None)

        self._tick_timer = QTimer(self, interval=1000, timeout=self._tick)
        self._heal_timer = QTimer(self, interval=2000, timeout=self._heal)
        self._unhide_timer = QTimer(self, singleShot=True, timeout=self.show_pet)

    # ── 啟動 ──
    def start(self):
        if not self.settings.get('first_run_at'):
            self.settings.set('first_run_at', datetime.now().isoformat(timespec='seconds'))
            self.settings.save()
        self.service.start()
        self.apply_pet_settings(reload_frames=True)
        self._tick()
        self.pet.restore_position()
        self.pet.show()
        self._tray.show()
        failed = self.apply_hotkeys()
        self._tick_timer.start()
        self._heal_timer.start()
        threading.Thread(target=self._warm_frames, daemon=True).start()
        QTimer.singleShot(800, lambda: self._startup_prompts(failed))

    def _startup_prompts(self, failed_hotkeys: dict):
        if not self.settings.was_prompted('welcome'):
            self.settings.mark_prompted('welcome')
            self.settings.save()
            self.say('嗨！點我打開快捷面板，按住可以把我拖到任何地方。右鍵還有更多選項。', seconds=10)
            return
        link = autostart.legacy_watcher_link()
        if link and not self.settings.was_prompted('legacy_watcher'):
            def remove():
                done = autostart.remove_legacy_watcher(link)
                self.say('已移除 1.x 的自動啟動監視器。' if done else '沒有找到要移除的監視器。')
            self.settings.mark_prompted('legacy_watcher')
            self.settings.save()
            self.say('偵測到 1.x 的自動啟動監視器：開 SAI2 時它會另外啟動 1.x，兩版會同時記錄。要移除嗎？',
                     actions=[('移除', remove), ('保留', lambda: None)])
            return
        if self._recover_prompt():
            return
        if self.service.paused:
            self.say('1.x 正在執行，2.0 先暫停記錄，避免重複計時。關閉 1.x 後會自動繼續。')
        elif self._usage_prompt():
            pass
        elif failed_hotkeys:
            self.say('有快捷鍵被其他程式佔用：' + '、'.join(hotkeys.ACTIONS[a][0] for a in failed_hotkeys)
                     + '。可以到設定修改。', actions=[('設定', lambda: self.open_settings('快捷鍵'))])

    def _recover_prompt(self) -> bool:
        """上次有沒合成的縮時錄影（當機、斷電）時，問要不要合成。沒有 ffmpeg 時不問，到「工具」頁處理"""
        from core.timelapse import find_ffmpeg
        pending = self.service.unexported_recordings()
        if not pending or not find_ffmpeg():
            return False
        names = '、'.join(dict.fromkeys(p['name'] for p in pending[:3]))
        more = f'等 {len(pending)} 段' if len(pending) > 1 else ''
        self.say(f'上次有沒合成的縮時錄影（{names}{more}），可能是程式意外關閉。要現在合成影片嗎？',
                 actions=[('合成', self.recover_recordings),
                          ('之後再說', lambda: self.say('之後可以在「工具」頁合成或捨棄。', important=False))],
                 seconds=20)
        return True

    def recover_recordings(self, items=None):
        n = self.service.recover_recordings(items)
        if n:
            self.say(f'開始合成 {n} 段錄影，完成後會通知你。', important=False)
        else:
            self.say('沒有可以合成的錄影。', important=False)
        return n

    def _usage_prompt(self, now: datetime | None = None) -> bool:
        """使用滿 3 天後各問一次（§16）：依實際動筆時間建議每日練習時間、要不要開機啟動。一次只問一件"""
        s, q = self.settings, self.service.quests
        if q is not None and q.settings.get('enabled', True) and onboarding.due_after_days(s, onboarding.KEY_TUNE, now):
            s.mark_prompted(onboarding.KEY_TUNE)
            s.save()
            budget = float(q.settings.get('budget_minutes', 60))
            new = onboarding.suggest_budget(self.service.daily_history(), budget, now, s.get('first_run_at', ''))
            if new:
                more = new > budget
                self.say(f'這幾天平均每天畫得比 {int(budget)} 分鐘{"多" if more else "少"}，'
                         f'要把每日練習時間改成 {new} 分鐘嗎？',
                         actions=[(f'改成 {new} 分', lambda: self._set_budget(new)), ('維持', lambda: None)])
                return True
        if onboarding.due_after_days(s, onboarding.KEY_AUTOSTART, now) and not self.autostart_enabled():
            s.mark_prompted(onboarding.KEY_AUTOSTART)
            s.save()
            self.say('要讓我開機就自動出現嗎？這樣不用每次手動打開，也不會漏記畫圖時間。',
                     actions=[('開機啟動', lambda: (self.set_autostart(True), self.say('好，之後開機就會出現。', important=False))),
                              ('不用', lambda: None)])
            return True
        return False

    def _set_budget(self, minutes: int):
        q = self.service.quests
        q.settings['budget_minutes'] = int(minutes)
        q.mark_dirty()
        q.save(force=True)
        self.say(f'每日練習時間改成 {minutes} 分鐘，明天起的任務會照這個排。', important=False)

    # ── 每秒 ──
    def _tick(self):
        res = self.service.tick()
        st = res.status
        self.last_status = st
        state, bubbles = self.brain.update(PetInputs(st.sai2_running, st.drawing, st.rest_day, self.service.paused))
        for b in bubbles:
            self.say(b.text, important=b.important)
        if 'legacy_paused' in res.events:
            self.say('偵測到 1.x 開啟，2.0 暫停記錄，避免重複計時。')
        if 'legacy_resumed' in res.events:
            self.say('1.x 已關閉，2.0 繼續記錄。', important=False)
        if self._main is not None and ({'legacy_paused', 'legacy_resumed'} & set(res.events)):
            self._main.on_tracking_changed()
        if 'exe_found' in res.events:
            self.opener.exe_path = self.settings.get('sai2_exe', '')
        if st.unsaved_file and st.drawing and st.unsaved_file not in self._reminded_unsaved:
            self._reminded_unsaved.add(st.unsaved_file)
            self.brain.trigger('remind')
            self.say(f'「{st.unsaved_file}」還沒存檔：動筆時間和錄影照常記錄，存檔時會接到作品上。',
                     actions=[('現在存檔', lambda: self.send_sai2_keys([0x11, 0x53]))], important=False)
        for kind, old, new in res.saves:
            from core.unsaved import temp_name
            from core.file_paths import display_name
            if kind == 'adopt':
                self.say(f'「{temp_name(old)}」存成了「{display_name(new)}」，剛才的動筆時間和錄影都接上了。', important=False)
            elif kind == 'ask':
                self.say(f'剛才的「{temp_name(old)}」是存成了「{display_name(new)}」嗎？',
                         actions=[('是', lambda o=old, n=new: (self.service.adopt_unsaved(o, n),
                                                               self.say('好，已經接上了。', important=False))),
                                  ('不是', lambda: None)], seconds=20)
        if res.ready:
            self.on_ready(res.ready)
            self._rule_events.add('quest_ready')
        self._run_rules(st)
        for pct, msg in res.export:
            self._on_export(pct, msg)
        for msg in res.messages:                    # 錄影器的問題（例如無法建立浮動檢視）；正常的狀態不打擾
            if msg.startswith(('⚠', '❌')):
                self.say(msg.lstrip('⚠️❌ ').strip(), actions=[('錄影設定', lambda: self.open_main('工具'))])
        if res.thumbs and self._main is not None and self._main.current == '作品':
            page = self._main.page_widget('作品', 'WorksPage')
            if page is not None:
                page.thumbs_updated(res.thumbs)
        if 'new_day' in res.events and not self.service.paused:
            self._usage_prompt()
        if res.events and self.panel.isVisible():
            self.panel.refresh()
        self._set_pet_state(state)
        self._apply_opacity()
        self._update_capsule(st)

    def _heal(self):
        if QApplication.activePopupWidget() is not None:
            return          # 選單、下拉清單開著時不重新置頂，否則會把它們壓到寵物或小窗下面
        self.pet.heal_topmost()
        if self.ref_win is not None:
            self.ref_win.heal_topmost()
        if self.bubble.isVisible():
            winutil.force_topmost(winutil.hwnd_of(self.bubble))
        if self.capsule.isVisible():
            winutil.force_topmost(winutil.hwnd_of(self.capsule))

    # ── 寵物 ──
    def _dpr(self) -> float:
        return (self.pet.screen() or self.qapp.primaryScreen()).devicePixelRatio()

    def _phys_size(self) -> int:
        return int(round(int(self.settings.get('pet.size', 128)) * self._dpr()))

    def _load_frames(self, state: str):
        key = state
        if key not in self._frames:
            dpr = self._dpr()
            out = []
            for img, ms in self._pack.frames(state, self._phys_size()):
                pm = to_pixmap(img)
                pm.setDevicePixelRatio(dpr)
                out.append((pm, ms))
            self._frames[key] = out
        return self._frames[key]

    def _warm_frames(self):
        """背景先解碼其他狀態的影格（Pillow 可在背景執行緒；轉成 QPixmap 仍在主執行緒）"""
        pack, size = self._pack, self._phys_size()
        for st in pet_pack.STATES:
            try:
                pack.frames(st, size)
            except Exception:
                pass

    def _set_pet_state(self, state: str, force: bool = False):
        if state == self._pet_state and not force:
            return
        self._pet_state = state
        try:
            frames = self._load_frames(state)
        except Exception as e:
            self.say(f'角色「{self._pack.name}」的「{pet_pack.STATE_LABELS.get(state, state)}」載入失敗：{e}')
            self._pack = pet_pack.builtin_pack()
            self._frames.clear()
            frames = self._load_frames(state)
        self.pet.set_animation(frames, self._pack.loops(state))

    def _apply_opacity(self):
        base = float(self.settings.get('pet.opacity', 1.0))
        if self._pet_state == 'drawing' and self.settings.get('pet.fade_when_drawing', True):
            base = min(base, float(self.settings.get('pet.drawing_opacity', 0.55)))
        if abs(self.pet.windowOpacity() - base) > 0.01:
            self.pet.setWindowOpacity(base)

    def apply_pet_settings(self, reload_frames: bool = False):
        self.pet.snap_edges = bool(self.settings.get('pet.snap_edges', False))
        if reload_frames or self._pack is None:
            self._pack = pet_pack.find_pack(self.settings.pets_dir, self.settings.get('pet.pack', ''), self.pet_tint())
            self._frames.clear()
            if self._pet_state:
                self._set_pet_state(self._pet_state, force=True)
        self._apply_opacity()

    def pet_tint(self) -> str | None:
        return theme.PET_BODY if self.settings.get('pet.tint_builtin', True) else None

    def _pet_menu(self, pos):
        m = QMenu()
        m.setStyleSheet(theme.QSS)
        m.addAction('快捷面板', self.toggle_panel)
        m.addAction('控制中心', lambda: self.open_control_center())
        m.addAction('設定', lambda: self.open_settings())
        m.addAction(f'隱藏 {HIDE_MINUTES} 分', self.hide_for_a_while)
        m.addSeparator()
        m.addAction('結束 DrawCompanion', self.quit)
        m.exec(pos)

    def show_pet(self):
        self._unhide_timer.stop()
        self.pet.show()
        self.pet.heal_topmost()

    def hide_for_a_while(self):
        self.panel.hide()
        self.bubble.hide()
        self.capsule.hide()
        self.pet.hide()
        self._unhide_timer.start(HIDE_MINUTES * 60 * 1000)
        self._tray.showMessage('DrawCompanion', f'寵物先躲起來 {HIDE_MINUTES} 分鐘，點系統匣圖示可以叫回來。',
                               QSystemTrayIcon.Information, 4000)

    def _tray_icon(self) -> QIcon:
        """系統匣、視窗與工作列的圖示：墨墨（內建角色跟隨主題色時一起換色；exe 圖示固定預設色）"""
        from core import pet_builtin
        body = pet_builtin.parse_color(self.pet_tint())
        ic = QIcon()
        for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
            ic.addPixmap(to_pixmap(pet_builtin.icon(size, body)))
        return ic

    def apply_app_icon(self):
        ic = self._tray_icon()
        self.qapp.setWindowIcon(ic)
        if getattr(self, '_tray', None) is not None:
            self._tray.setIcon(ic)

    # ── 面板與泡泡 ──
    def _pet_moved(self):
        if self.bubble.isVisible():
            self.bubble.reposition()
        if self.capsule.isVisible():
            self.capsule.reposition()

    def _pet_clicked(self):
        # 面板開著時點寵物：面板會因為「點到外面」先自己收起，這時不要再打開，達成「再點一次就關閉」
        if not self.panel.isVisible() and time.monotonic() - self.panel.hidden_at < 0.35:
            return
        self.toggle_panel()

    def _update_capsule(self, st):
        show = (bool(self.settings.get('pet.show_timer', True)) and self.pet.isVisible()
                and (st.sai2_running or not st.tracking))
        if show:
            self.capsule.set_status(st)
            if not self.capsule.isVisible():
                self.capsule.reposition()
                self.capsule.show()
        elif self.capsule.isVisible():
            self.capsule.hide()

    def toggle_panel(self):
        if self.panel.isVisible():
            self.panel.hide()
        else:
            if not self.pet.isVisible():
                self.show_pet()
            self.bubble.hide()
            self.panel.popup()

    def say(self, text: str, actions=(), important: bool = True, seconds: float = 6.0):
        level = self.settings.get('pet.bubbles', 'important')
        if level == 'off' and not actions:
            return
        if level == 'important' and not important and not actions:
            return
        if not self.pet.isVisible():
            self._tray.showMessage('DrawCompanion', text, QSystemTrayIcon.Information, 5000)
            return
        self.bubble.show_message(text, actions, seconds)

    def on_ready(self, tasks: list):
        for t in tasks:
            self.brain.trigger('cheer')
            self.say(f'「{t["name"]}」達標了，可以打卡！', actions=[('打卡', lambda u=t['uid']: self._checkin_from_bubble(u))])

    def _checkin_from_bubble(self, uid: str):
        w = self.ref_win
        if w is not None and getattr(w.mode, 'uid', None) == uid:
            t = self.service.quests.task(uid)
            if w.capsule.isVisible():
                w.restore_from_capsule()
            w.open_checkin(t, getattr(w.mode, 'lesson', None), self_report=t['status'] != 'ready')
            return
        self.panel.popup()
        if self.panel.quest_list is not None:
            self.panel.quest_list._open_inline(uid, 'checkin')

    # ── 規則 ──
    def _run_rules(self, st):
        events, self._rule_events = self._rule_events, set()
        if self.service.paused:
            return
        ctx = {'now': datetime.now(), 'sai2_running': st.sai2_running, 'drawing': st.drawing,
               'current_file': st.current_file, 'events': events}
        for act in self.rules.evaluate(self.settings.get('rules', []) or [], ctx):
            self.run_rule_action(act)

    def run_rule_action(self, act: dict):
        t, v = act.get('type'), act.get('value')
        if t == 'bubble':
            self.say(str(v))
        elif t == 'pet':
            self.brain.trigger(v)
        elif t == 'open_sketch':
            if self.ref_win is None:
                self.open_ref('sketch', None)
        elif t == 'open_study':
            if self.ref_win is None:
                self.run_slot('study')
        elif t in ('record_on', 'record_off'):
            if bool(self.settings.get('timelapse.enabled')) != (t == 'record_on'):
                self.set_recording(t == 'record_on')
        elif t == 'snapshot':
            self.run_slot('snapshot')
        elif t == 'open_url':
            self.run_slot({'type': 'url', 'label': '', 'target': str(v)})
        elif t == 'open_path':
            self.run_slot({'type': 'path', 'label': '', 'target': str(v)})

    def on_checked_in(self, uid: str):
        self._rule_events.add('checkin')
        t = self.service.quests.task(uid)
        self.brain.trigger('cheer')
        msg = f'已打卡「{t["name"]}」，連續 {self.service.quests.streak()} 天！'
        nxt = study_lessons.lesson(t.get('advanced_to') or '') if t else None
        if nxt:
            msg += f'\n下一課：{nxt.get("name", "")}'
        self.say(msg)

    # ── SAI2 ──
    def _find_exe(self) -> str:
        procs = self.backend.find_processes()
        return procs[0][1] if procs and procs[0][1] else ''

    def send_sai2_keys(self, vks: list[int]) -> bool:
        """切到 SAI2 後送出快捷鍵（新增畫布 Ctrl+N、存檔 Ctrl+S）；SAI2 沒開時回傳 False"""
        if not self.focus_sai2():
            return False

        def press():
            from core.timelapse import _press_keys
            _press_keys(vks)
        QTimer.singleShot(250, press)                       # 等 SAI2 真的到前景
        return True

    def focus_sai2(self) -> bool:
        procs = self.backend.find_processes(self.opener._extra_names())
        if not procs:
            return False
        hwnd = self.backend.main_window(procs[0][0])
        if hwnd:
            self.backend.focus(hwnd)
        return bool(hwnd)

    def open_path(self, path: str):
        name = os.path.basename(path)
        self.say(f'正在 SAI2 開啟「{name}」…', important=False, seconds=3)
        self.opener.exe_path = self.settings.get('sai2_exe', '') or self.opener.exe_path

        def run():
            res = self.opener.open(path)
            self.open_done.emit(res, path)
        threading.Thread(target=run, daemon=True).start()

    def open_recent(self, key: str):
        from core.file_paths import resolve_file_key, display_name

        def run():
            path = resolve_file_key(key)
            if path:
                self.work_done.emit(lambda: self.open_path(path))
            else:
                self.work_done.emit(lambda: self.say(f'找不到「{display_name(key)}」的檔案位置，可能已經移動或改名。'))
        threading.Thread(target=run, daemon=True).start()

    def _on_open_done(self, res, path):
        name = os.path.basename(path)
        if res.ok:
            if res.exe_path and res.exe_path != self.settings.get('sai2_exe'):
                self.settings.set('sai2_exe', res.exe_path)
                self.settings.save()
            return
        if res.status == 'busy':
            self.say('上一個檔案還在開啟中，請稍等。')
        elif res.status == 'need_exe':
            self.say('還不知道 SAI2 裝在哪裡。指定一次之後就會記住。',
                     actions=[('指定 SAI2', lambda: self._ask_exe_then(path))])
        elif res.status == 'not_found':
            self.say(f'找不到檔案「{name}」。')
        elif res.status == 'launch_timeout':
            self.say('SAI2 啟動逾時，請確認 SAI2 能正常開啟。')
        else:
            self.say(f'沒有確認到「{name}」已開啟，可以改用 Windows 的檔案關聯開啟。',
                     actions=[('用檔案關聯開啟', lambda: os.startfile(path))])

    def _ask_exe_then(self, path: str | None):
        exe, _ = QFileDialog.getOpenFileName(None, '選擇 SAI2 執行檔', '', 'sai2.exe (*.exe)')
        if exe:
            self.settings.set('sai2_exe', os.path.normpath(exe))
            self.settings.save()
            self.opener.exe_path = self.settings.get('sai2_exe')
            if path:
                self.open_path(path)
            else:
                self.run_slot('open_sai2')

    # ── 參考小窗 ──
    def open_ref(self, kind: str, uid: str | None):
        """開啟參考小窗（同時只有一個；換任務時關掉舊的）"""
        from ui2.ref_window import ReferenceMode, RefWindow, SketchMode, StudyMode
        w = self.ref_win
        if w is not None:
            if w.kind == kind and (kind == 'reference' or (getattr(w.mode, 'uid', None) == uid and uid is not None)):
                if w.capsule.isVisible():
                    w.restore_from_capsule()
                w.show()
                return w
            w.close()
        w = RefWindow(self, kind)
        mode = {'study': StudyMode, 'reference': ReferenceMode}.get(kind, SketchMode)(w, uid)
        w.set_mode(mode)
        w.closed.connect(self._ref_closed)
        self.ref_win = w
        w.show()
        mode.start()
        if kind == 'study':
            self.focus_sai2()
        return w

    def _ref_closed(self, w):
        if self.ref_win is w:
            self.ref_win = None
        if self.panel.isVisible():
            self.panel.refresh()

    def _study_task_today(self):
        q = self.service.quests
        if q is None:
            return None
        if q.active_study:
            return q.active_study
        t = next((t for t in q.today_tasks() if t['mode'] == 'study' and t['status'] in ('active', 'ready')), None)
        return t['uid'] if t else None

    # ── 縮時錄影 ──
    def set_recording(self, on: bool):
        if self.service.paused:
            self.say('1.x 正在執行，2.0 暫停中，無法開始錄影。')
            return
        self.service.set_recording(on)
        if on:
            from core.timelapse import find_ffmpeg
            msg = '縮時錄影開始：在 SAI2 畫哪個作品就錄哪個，每個作品各自一部；關閉 SAI2 時自動合成影片。'
            if not find_ffmpeg():
                msg += '\n（找不到 ffmpeg，影片無法合成，請先安裝）'
            self.say(msg, important=False)
        else:
            self.say('縮時錄影已停止，正在合成影片。' if self.service.exporting_count() else '縮時錄影已停止。',
                     important=False)
        if self.panel.isVisible():
            self.panel.refresh()

    def _on_export(self, pct: int, msg: str):
        self.export_state = (pct, msg)
        videos = self.settings.videos_dir
        if pct >= 100:
            self.export_state = (None, msg)
            self.brain.trigger('cheer')
            if not self.settings.was_prompted(onboarding.KEY_FIRST_VIDEO):
                self.settings.mark_prompted(onboarding.KEY_FIRST_VIDEO)
                self.settings.save()
                self.say(f'第一部縮時影片完成了！影片放在：\n{videos}\n想放別的地方可以在「工具」頁更改。',
                         actions=[('開啟資料夾', lambda: os.startfile(videos)), ('更改位置', lambda: self.open_main('工具'))],
                         seconds=20)
            else:
                self.say('縮時影片完成了！', actions=[('開啟資料夾', lambda: os.startfile(videos))])
        elif pct == 0 and ('失敗' in msg or '錯誤' in msg or 'fail' in msg.lower() or 'error' in msg.lower()):
            self.export_state = (None, msg)
            self.say(f'影片合成失敗：{msg}')

    def run_slot(self, key):
        if isinstance(key, dict):
            from core import slots
            err = slots.run_custom(key)
            if err:
                self.say(f'無法執行「{slots.describe(key)[0]}」：{err}', actions=[('設定', lambda: self.open_settings('快捷面板'))])
            return
        if key == 'main':
            self.open_main('今日')
            return
        if key == 'growth':
            self.open_main('成長')
            return
        if key == 'record':
            self.set_recording(not bool(self.settings.get('timelapse.enabled')))
            return
        if key == 'sketch':
            self.open_ref('sketch', None)
            return
        if key == 'study':
            uid = self._study_task_today()
            if uid:
                action, msg = self.service.go(uid)
                if action == 'open_study':
                    self.open_ref('study', uid)
                else:
                    self.say(msg)
            else:
                self.say('今天沒有研究任務。可以到控制中心的「練習」選一堂課。',
                         actions=[('打開練習頁', lambda: self.open_control_center('練習'))])
            return
        if key == 'open_sai2':
            if self.focus_sai2():
                return
            exe = self.settings.get('sai2_exe', '')
            if exe and os.path.isfile(exe):
                self.backend.spawn([exe])
                self.say('正在開啟 SAI2…', important=False, seconds=3)
            else:
                self.say('還不知道 SAI2 裝在哪裡。', actions=[('指定 SAI2', lambda: self._ask_exe_then(None))])
        elif key == 'reference':
            self.open_ref('reference', None)
        elif key == 'new_canvas':
            if not self.send_sai2_keys([0x11, 0x4E]):        # Ctrl+N：SAI2 的新增畫布（你的預設尺寸清單）
                self.say('SAI2 還沒開啟。', actions=[('開啟 SAI2', lambda: self.run_slot('open_sai2'))])
        elif key == 'snapshot':
            self._snapshot()
        elif key == 'works':
            self._open_works_folder()

    def _snapshot(self):
        folder = os.path.join(self.settings.app_dir, 'snapshots')

        def run():
            from core.snapshots import capture_sai2_canvas, save_snapshot
            img = capture_sai2_canvas()
            if img is None:
                self.work_done.emit(lambda: self.say('找不到 SAI2 畫布，請先在 SAI2 開啟畫布。'))
                return
            path = save_snapshot(img, folder, datetime.now().strftime('snapshot_%Y%m%d_%H%M%S'), max_side=4096)
            self.work_done.emit(lambda: self.say('已存下畫布快照。', actions=[('開啟資料夾', lambda: os.startfile(folder))]))
            return path
        threading.Thread(target=run, daemon=True).start()

    def _open_works_folder(self):
        rows = self.service.recent_files(1)
        if not rows:
            os.startfile(self.settings.app_dir)
            return
        from core.file_paths import resolve_file_key

        def run():
            path = resolve_file_key(rows[0]['key'])
            target = os.path.dirname(path) if path else self.settings.app_dir
            self.work_done.emit(lambda: os.startfile(target))
        threading.Thread(target=run, daemon=True).start()

    # ── 設定、快捷鍵、開機啟動 ──
    def open_main(self, page: str = '今日'):
        """主視窗：控制中心與設定在同一個視窗"""
        from ui2.main_window import MainWindow
        if self._main is None:
            self._main = MainWindow(self)
        self._main.show_page(page)

    def set_theme(self, accent: str | None = None, mode: str | None = None, scale: float | None = None):
        if accent:
            self.settings.set('theme.accent', accent)
        if mode:
            self.settings.set('theme.mode', mode)
        if scale:
            self.settings.set('theme.text_scale', float(scale))
        self.settings.save()
        theme.apply(self.settings.get('theme.accent', 'purple'), self.settings.get('theme.mode', 'dark'),
                    self.settings.get('theme.text_scale', 1.0))
        if scale:                                  # 文字大小：快捷面板的寬度、泡泡的字也跟著變
            self.panel.card.setFixedWidth(theme.size(PANEL_W))
            self.apply_bubble_skin()
        self.qapp.setStyleSheet(theme.QSS)
        self.apply_pet_settings(reload_frames=True)          # 內建角色跟著換色
        self.apply_app_icon()
        if self.ref_win is not None:
            self.ref_win.setStyleSheet(theme.QSS + 'QWidget{background:transparent;}')
        if self._main is not None:            # 主視窗重新建立，讓所有元件用新的色票
            page = self._main.current or '外觀'
            geo = self._main.geometry()
            self._main.close()
            self._main.deleteLater()
            self._main = None
            self.open_main(page)
            self._main.setGeometry(geo)
        if self.panel.isVisible():
            self.panel.refresh()

    def reload_settings(self):
        """匯入設定後重新套用：主題、寵物、快捷鍵、錄影設定"""
        self.apply_pet_settings(reload_frames=True)
        self.apply_bubble_skin()
        self.apply_hotkeys()
        self.service.apply_recorder_settings()
        self.opener.exe_path = self.settings.get('sai2_exe', '') or self.opener.exe_path
        self.set_theme()

    def apply_bubble_skin(self):
        skin = self.settings.get('pet.bubble_skin')
        self.bubble.set_skin(skin, bubble_skin.image_path(self.settings.app_dir, skin))

    def open_control_center(self, page: str = '今日'):
        self.open_main(page)

    def open_settings(self, page: str = '一般'):
        self.open_main(page)

    def apply_hotkeys(self) -> dict:
        """依設定重新註冊；回傳 {動作: 失敗原因}"""
        self.hub.unregister_all()
        self._hk_ids.clear()
        failed = {}
        for i, (action, text) in enumerate(sorted(self.settings.get('hotkeys', {}).items()), start=1):
            if not text or action not in hotkeys.ACTIONS:
                continue
            try:
                mods, vk = hotkeys.parse(text)
            except ValueError as e:
                failed[action] = str(e)
                continue
            if self.hub.register(i, mods, vk):
                self._hk_ids[i] = action
            else:
                failed[action] = '已被其他程式佔用'
        self.service.apply_recorder_settings()      # SAI2「新增檢視」的快捷鍵不能和 2.0 的相同
        return failed

    def _on_hotkey(self, hid: int):
        action = self._hk_ids.get(hid)
        if action == 'panel':
            self.toggle_panel()
        elif action == 'toggle_pet':
            if self.pet.isVisible():
                self.panel.hide()
                self.bubble.hide()
                self.capsule.hide()
                self.pet.hide()
            else:
                self.show_pet()
        elif action in ('open_sai2', 'snapshot'):
            self.run_slot(action)
        elif action == 'record_toggle':
            self.run_slot('record')
        elif action == 'ref_toggle':
            if self.ref_win is not None:
                self.ref_win.toggle_visible()
            else:
                self.say('目前沒有開啟參考小窗。', important=False)
        elif self.ref_win is None:
            return
        elif action == 'click_through':
            self.ref_win.toggle_click_through()
        elif action == 'compare':
            try:
                _mods, vk = hotkeys.parse(self.settings.get('hotkeys.compare', ''))
                self.ref_win.begin_hold_compare(vk)
            except ValueError:
                pass
        elif action == 'sketch_next' and self.ref_win.kind == 'sketch':
            self.ref_win.mode.next()
        elif action == 'sketch_pause':
            self.ref_win.mode.toggle_pause()

    def autostart_enabled(self) -> bool:
        return autostart.is_enabled()

    def set_autostart(self, on: bool):
        autostart.set_enabled(on, autostart.launch_command(ENTRY_SCRIPT))
        self.settings.set('autostart', on)
        self.settings.save()

    # ── 其他份程式交過來的參數 ──
    def on_message(self, msg: dict):
        if msg.get('open'):
            self.open_path(msg['open'])
        elif not msg.get('background'):
            self.show_pet()
            self.toggle_panel() if not self.panel.isVisible() else None

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        self._tick_timer.stop()
        if self.ref_win is not None:
            self.ref_win.close()
        self.service.stop()                  # 停止錄影時會把正在錄的檔案送去合成
        self.settings.save()
        self.hub.close()
        if self.service.exporting_count():
            # 影片還在合成：先收起畫面，合成完再結束（直接結束會留下半成品）
            for w in (self.panel, self.bubble, self.capsule, self.pet, self._main):
                if w is not None:
                    w.hide()
            self._tray.showMessage('DrawCompanion', '縮時影片合成中，完成後會自動結束。', QSystemTrayIcon.Information, 5000)
            self._wait_export = QTimer(self, interval=1000, timeout=self._finish_quit)
            self._wait_export.start()
            return
        self._finish_quit()

    def _finish_quit(self):
        if self.service.exporting_count():
            return
        if getattr(self, '_wait_export', None) is not None:
            self._wait_export.stop()
        self._tray.hide()
        self.qapp.quit()


def release_widgets(qapp: QApplication):
    """結束前先釋放所有視窗：讓 Python 在程式結束時才回收的話，可能晚於 QApplication 被銷毀而卡住不退出"""
    for w in qapp.topLevelWidgets():
        w.deleteLater()
    qapp.sendPostedEvents(None, 0)
    qapp.processEvents()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='drawcompanion2')
    ap.add_argument('--background', action='store_true')
    ap.add_argument('--open')
    ap.add_argument('--data-dir')
    ap.add_argument('--instance-name', default=INSTANCE_NAME)
    args, _rest = ap.parse_known_args(argv)

    qapp = QApplication(sys.argv[:1])
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationName('DrawCompanion 2.0')
    qapp.setStyleSheet(theme.QSS)
    inst = SingleInstance(args.instance_name)
    chan = channel_name(args.instance_name)
    if not inst.acquire():
        payload = {'open': os.path.abspath(args.open) if args.open else None, 'background': args.background}
        return 0 if send_to_first(chan, payload) else 1

    app_dir = os.path.abspath(args.data_dir) if args.data_dir else APP_DIR
    os.makedirs(app_dir, exist_ok=True)
    from core import diagnostics
    diagnostics.install(app_dir)                  # 打包後沒有主控台：未處理的錯誤寫進記錄檔
    settings = Settings2(app_dir)
    inbox = Inbox(chan)
    ctl = CompanionApp(qapp, settings, background=args.background)
    inbox.received.connect(ctl.on_message)
    ctl.start()
    if args.open:
        ctl.open_path(os.path.abspath(args.open))
    code = qapp.exec()
    release_widgets(qapp)
    inst.release()
    diagnostics.uninstall()
    return code
