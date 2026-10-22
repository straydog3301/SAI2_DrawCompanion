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
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from core import autostart, hotkeys, pet_pack, study_lessons
from core.companion import CompanionService
from core.paths import APP_DIR
from core.pet_state import PetBrain, PetInputs
from core.sai2_launcher import Sai2Opener, Win32Backend
from core.settings2 import Settings2
from core.single_instance import SingleInstance, channel_name
from ui2 import theme, winutil
from ui2.bubble import Bubble
from ui2.pet_window import PetWindow, to_pixmap
from ui2.quick_panel import QuickPanel

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
        self.service = CompanionService(settings, exe_finder=self._find_exe)
        self.brain = PetBrain(settings.get('pet.rest_minutes', 50), settings.get('pet.night_sleep', False))
        self.backend = Win32Backend()
        self.opener = Sai2Opener(self.backend, exe_path=settings.get('sai2_exe', ''))
        self.last_status = None
        self._pack = None
        self._frames: dict[str, list] = {}
        self._pet_state = None
        self._reminded_unsaved: set[str] = set()
        self._main = None
        self.ref_win = None
        self.open_done.connect(self._on_open_done)
        self.work_done.connect(lambda fn: fn())

        self.pet = PetWindow(os.path.join(settings.app_dir, 'drawcompanion2_pet_pos.json'))
        self.bubble = Bubble()
        self.bubble.anchor = self.pet
        self.panel = QuickPanel(self)
        self.pet.clicked.connect(self.toggle_panel)
        self.pet.menu_requested.connect(self._pet_menu)
        self.pet.moved.connect(lambda: self.bubble.isVisible() and self.bubble.reposition())

        self.hub = winutil.HotkeyHub(qapp)
        self.hub.triggered.connect(self._on_hotkey)
        self._hk_ids: dict[int, str] = {}

        self._tray = QSystemTrayIcon(self._tray_icon())
        menu = QMenu()
        menu.addAction('快捷面板', self.toggle_panel)
        menu.addAction('控制中心', lambda: self.open_control_center())
        menu.addAction('顯示寵物', self.show_pet)
        menu.addAction('設定', lambda: self.open_settings())
        menu.addSeparator()
        menu.addAction(QAction('結束', menu, triggered=self.quit))
        self._tray_menu = menu
        self._tray.setContextMenu(menu)
        self._tray.setToolTip('DrawCompanion 2.0')
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
        if self.service.paused:
            self.say('1.x 正在執行，2.0 先暫停記錄，避免重複計時。關閉 1.x 後會自動繼續。')
        elif failed_hotkeys:
            self.say('有快捷鍵被其他程式佔用：' + '、'.join(hotkeys.ACTIONS[a][0] for a in failed_hotkeys)
                     + '。可以到設定修改。', actions=[('設定', lambda: self.open_settings('快捷鍵'))])

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
        if 'exe_found' in res.events:
            self.opener.exe_path = self.settings.get('sai2_exe', '')
        if st.unsaved_file and st.drawing and st.unsaved_file not in self._reminded_unsaved:
            self._reminded_unsaved.add(st.unsaved_file)
            self.brain.trigger('remind')
            self.say(f'「{st.unsaved_file}」還沒存檔，存檔後畫圖時間才會被記錄。')
        if res.ready:
            self.on_ready(res.ready)
        if res.events and self.panel.isVisible():
            self.panel.refresh()
        self._set_pet_state(state)
        self._apply_opacity()

    def _heal(self):
        if QApplication.activePopupWidget() is not None:
            return          # 選單、下拉清單開著時不重新置頂，否則會把它們壓到寵物或小窗下面
        self.pet.heal_topmost()
        if self.ref_win is not None:
            self.ref_win.heal_topmost()
        if self.bubble.isVisible():
            winutil.force_topmost(winutil.hwnd_of(self.bubble))

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
        self.brain.rest_minutes = float(self.settings.get('pet.rest_minutes', 50))
        self.brain.night_sleep = bool(self.settings.get('pet.night_sleep', False))
        self.pet.snap_edges = bool(self.settings.get('pet.snap_edges', False))
        if reload_frames or self._pack is None:
            self._pack = pet_pack.find_pack(self.settings.pets_dir, self.settings.get('pet.pack', ''))
            self._frames.clear()
            if self._pet_state:
                self._set_pet_state(self._pet_state, force=True)
        self._apply_opacity()

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
        self.pet.hide()
        self._unhide_timer.start(HIDE_MINUTES * 60 * 1000)
        self._tray.showMessage('DrawCompanion', f'寵物先躲起來 {HIDE_MINUTES} 分鐘，點系統匣圖示可以叫回來。',
                               QSystemTrayIcon.Information, 4000)

    def _tray_icon(self) -> QIcon:
        img = pet_pack.builtin_pack().frames('idle', 64)[0][0]
        return QIcon(to_pixmap(img))

    # ── 面板與泡泡 ──
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

    def on_checked_in(self, uid: str):
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
        from ui2.ref_window import RefWindow, SketchMode, StudyMode
        w = self.ref_win
        if w is not None:
            if w.kind == kind and getattr(w.mode, 'uid', None) == uid and uid is not None:
                if w.capsule.isVisible():
                    w.restore_from_capsule()
                w.show()
                return w
            w.close()
        w = RefWindow(self, kind)
        mode = StudyMode(w, uid) if kind == 'study' else SketchMode(w, uid)
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

    def run_slot(self, key: str):
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
        return failed

    def _on_hotkey(self, hid: int):
        action = self._hk_ids.get(hid)
        if action == 'panel':
            self.toggle_panel()
        elif action == 'toggle_pet':
            if self.pet.isVisible():
                self.panel.hide()
                self.bubble.hide()
                self.pet.hide()
            else:
                self.show_pet()
        elif action in ('open_sai2', 'snapshot'):
            self.run_slot(action)
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
        self._tick_timer.stop()
        if self.ref_win is not None:
            self.ref_win.close()
        self.service.stop()
        self.settings.save()
        self.hub.close()
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
    return code
