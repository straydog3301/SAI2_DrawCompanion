# -*- coding: utf-8 -*-
"""
階段 0 技術驗證：可手動操作的整合版本

    python spikes/v2_stage0/app.py              # 啟動（第二次執行會把參數交給第一份後結束）
    python spikes/v2_stage0/app.py --open X.psd # 已有一份在執行時：交給它；--sai2 才真的在 SAI2 開檔

快捷鍵：Ctrl+Alt+T 小窗穿透切換、按住 Ctrl+Alt+C 比對 SAI2 畫布、Ctrl+Alt+R 顯示/隱藏小窗、Ctrl+Alt+Q 結束
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from PySide6.QtCore import QObject, QTimer, Signal                    # noqa: E402
from PySide6.QtGui import QAction, QIcon, QPixmap                     # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket              # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon    # noqa: E402

from core.single_instance import SingleInstance, channel_name         # noqa: E402
import winutil                                                         # noqa: E402
from pet import PetWindow, load_frames, make_demo_assets              # noqa: E402
from refwin import RefWindow, pil_to_pixmap                            # noqa: E402

HK_CLICK_THROUGH, HK_COMPARE, HK_TOGGLE_REF, HK_QUIT = 1, 2, 3, 4
VK = {'T': 0x54, 'C': 0x43, 'R': 0x52, 'Q': 0x51}


def demo_reference():
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (520, 390), (125, 138, 163))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 520, 200), fill=(167, 163, 180))
    d.ellipse((346, 76, 414, 144), fill=(233, 176, 122))
    d.rectangle((0, 188, 520, 210), fill=(92, 102, 128))
    return img


def send_to_first(name: str, payload: dict, timeout_ms: int = 2000) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(json.dumps(payload).encode('utf-8'))
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class Inbox(QObject):
    """第一份程式接收第二份交過來的參數"""
    received = Signal(dict)

    def __init__(self, name: str):
        super().__init__()
        QLocalServer.removeServer(name)       # 上次異常結束留下的通道
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--open')
    ap.add_argument('--sai2', action='store_true', help='收到 --open 時真的在 SAI2 開檔')
    ap.add_argument('--instance-name', default='SAI2DrawCompanion_spike')
    ap.add_argument('--state-dir', default=os.path.join(tempfile.gettempdir(), 'sai2dc_spike'))
    ap.add_argument('--log')
    ap.add_argument('--ready-file')
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    inst = SingleInstance(args.instance_name)
    chan = channel_name(args.instance_name)
    if not inst.acquire():
        ok = send_to_first(chan, {'open': args.open, 'argv': sys.argv[1:]})
        return 0 if ok else 1

    def log(msg):
        print(msg, flush=True)
        if args.log:
            with open(args.log, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')

    inbox = Inbox(chan)
    os.makedirs(args.state_dir, exist_ok=True)
    assets = make_demo_assets(os.path.join(args.state_dir, 'assets'))
    pet = PetWindow(load_frames(assets['apng'], 128), state_file=os.path.join(args.state_dir, 'pet_pos.json'))

    from core.snapshots import capture_sai2_canvas
    ref = RefWindow(pil_to_pixmap(demo_reference()), capture=capture_sai2_canvas)
    g = app.primaryScreen().availableGeometry()
    ref.move(g.right() - ref.width() - 40, g.top() + 40)

    panel = QMenu()
    panel.addAction('每日任務：姿勢速寫 9/15（驗證用）')
    panel.addAction('最近開啟：立繪_0616.psd（驗證用）')
    panel.addSeparator()
    panel.addAction('顯示/隱藏參考小窗', lambda: ref.setVisible(not ref.isVisible()))
    panel.addAction('結束', app.quit)
    pet.clicked.connect(lambda: panel.popup(pet.mapToGlobal(pet.rect().topLeft())))
    pet.dragged.connect(lambda p: log(f'pet moved to {p.x()},{p.y()}'))

    opener_lock = threading.Lock()

    def on_received(msg):
        log(f'received {json.dumps(msg, ensure_ascii=False)}')
        path = msg.get('open')
        if path and args.sai2 and opener_lock.acquire(blocking=False):
            def _run():
                from core.sai2_launcher import Sai2Opener
                try:
                    res = Sai2Opener(exe_path=os.path.join(os.path.dirname(REPO), 'sai2.exe')).open(path)
                    log(f'sai2 open: {res}')
                finally:
                    opener_lock.release()
            threading.Thread(target=_run, daemon=True).start()
    inbox.received.connect(on_received)

    hub = winutil.HotkeyHub(app)
    mods = winutil.MOD_CONTROL | winutil.MOD_ALT
    for hid, key in ((HK_CLICK_THROUGH, 'T'), (HK_COMPARE, 'C'), (HK_TOGGLE_REF, 'R'), (HK_QUIT, 'Q')):
        if not hub.register(hid, mods, VK[key]):
            log(f'hotkey Ctrl+Alt+{key} 已被其他程式佔用')

    def on_hotkey(hid):
        log(f'hotkey {hid}')
        if hid == HK_CLICK_THROUGH:
            ref.toggle_click_through()
        elif hid == HK_COMPARE:
            ref.begin_compare(VK['C'])
        elif hid == HK_TOGGLE_REF:
            ref.setVisible(not ref.isVisible())
        elif hid == HK_QUIT:
            app.quit()
    hub.triggered.connect(on_hotkey)

    fg = winutil.ForegroundWatcher()
    fg.changed.connect(lambda h, t: log(f'foreground {t!r}') if 'painttool sai' in t.lower() else None)
    heal = QTimer(interval=2000, timeout=ref.heal_topmost)
    heal.start()

    tray = QSystemTrayIcon(QIcon(QPixmap(assets['sprite']).copy(0, 0, 512, 512)))
    menu = QMenu()
    quit_act = QAction('結束', menu, triggered=app.quit)
    menu.addAction(quit_act)
    tray.setContextMenu(menu)
    tray.setToolTip('DrawCompanion 2.0 驗證版')
    tray.show()

    pet.start()
    ref.show()
    log(f'ready inbox={inbox.ok}')
    if args.ready_file:
        with open(args.ready_file, 'w') as f:
            f.write('ready')
    if args.open:
        on_received({'open': args.open, 'argv': sys.argv[1:]})
    code = app.exec()
    hub.unregister_all()
    fg.close()
    inst.release()
    return code


if __name__ == '__main__':
    sys.exit(main())
