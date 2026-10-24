# -*- coding: utf-8 -*-
"""
階段 0 自動驗證（會短暫開出寵物與小窗，並模擬 Ctrl+Alt+Shift+F9/F10 按鍵；不移動滑鼠、不開 SAI2）

    python spikes/v2_stage0/selftest.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [HERE, REPO]

import psutil                                                          # noqa: E402
from PIL import Image                                                  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt                 # noqa: E402
from PySide6.QtGui import QMouseEvent                                  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget                   # noqa: E402

import winutil                                                         # noqa: E402
from pet import PetWindow, load_frames, make_demo_assets, measure_fps  # noqa: E402
from refwin import RefWindow, pil_to_pixmap                            # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def record(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


def pump(app, ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def mouse(w, kind, local, button=Qt.LeftButton):
    types = {'press': QEvent.MouseButtonPress, 'move': QEvent.MouseMove, 'release': QEvent.MouseButtonRelease}
    lp = QPointF(local)
    gp = QPointF(w.mapToGlobal(local))
    btns = Qt.NoButton if kind == 'release' else button
    QApplication.sendEvent(w, QMouseEvent(types[kind], lp, gp, button if kind != 'move' else Qt.NoButton, btns, Qt.NoModifier))


def phys(w, p):
    """Qt 邏輯座標 → Win32 實體像素（高 DPI 縮放下兩者不同）"""
    r = w.devicePixelRatioF()
    return int(p.x() * r), int(p.y() * r)


def key(vk, up=False):
    winutil.user32.keybd_event(vk, 0, 0x2 if up else 0, 0)


def main():
    app = QApplication(sys.argv[:1])
    tmp = tempfile.mkdtemp(prefix='sai2dc_spike_')
    assets = make_demo_assets(os.path.join(tmp, 'assets'))
    proc = psutil.Process()

    # ── 1. 影格格式 ──
    for kind in ('apng', 'gif', 'webp', 'sprite'):
        t0 = time.perf_counter()
        fr = load_frames(assets[kind], 128, frames=24 if kind == 'sprite' else None, fps=24)
        ms = (time.perf_counter() - t0) * 1000
        img = fr[0][0].toImage()
        alphas = {img.pixelColor(x, y).alpha() for x in range(128) for y in range(100, 128)}
        soft = any(0 < a < 255 for a in alphas)
        if kind == 'gif':
            raw = Image.open(assets['gif']).convert('RGBA').getchannel('A')
            soft = sum(raw.histogram()[1:255]) > 0     # GIF 原圖只有全透明 / 不透明
        record(f'decode {kind}', len(fr) == 24 and fr[0][0].width() == 128,
               f'{len(fr)} frames {fr[0][1]}ms/frame load {ms:.0f}ms soft-alpha={soft}')

    # ── 2. 寵物視窗：透明區域點擊穿透、拖曳 / 點擊判斷、位置記憶 ──
    state = os.path.join(tmp, 'pos.json')
    pet = PetWindow(load_frames(assets['apng'], 128), state_file=state)
    pet.move(400, 300)
    pet.start()
    pump(app, 400)
    h = winutil.hwnd_of(pet)
    record('pet layered/topmost style', winutil.ex_style(h) & winutil.WS_EX_TOPMOST,
           f'exstyle=0x{winutil.ex_style(h):x}')
    corner = phys(pet, pet.mapToGlobal(QPoint(3, 3)))
    body = phys(pet, pet.mapToGlobal(QPoint(64, 80)))
    record('pet transparent pixel passes clicks', winutil.root_at(*corner) != h)
    record('pet opaque pixel receives clicks', winutil.root_at(*body) == h, f'dpr={pet.devicePixelRatioF()}')

    clicks, drags = [], []
    pet.clicked.connect(lambda: clicks.append(1))
    pet.dragged.connect(lambda p: drags.append(p))
    mouse(pet, 'press', QPoint(60, 80))
    mouse(pet, 'move', QPoint(62, 81))
    mouse(pet, 'release', QPoint(62, 81))
    record('pet small move = click', clicks == [1] and not drags and pet.pos() == QPoint(400, 300))
    mouse(pet, 'press', QPoint(60, 80))
    mouse(pet, 'move', QPoint(90, 120))
    mouse(pet, 'release', QPoint(90, 120))
    pump(app, 50)
    record('pet drag moves + saves', drags and pet.pos() == QPoint(430, 340) and os.path.isfile(state),
           f'pos={pet.pos().x()},{pet.pos().y()}')
    pet2 = PetWindow(load_frames(assets['gif'], 64), state_file=state)
    record('pet position restored', pet2.pos() == QPoint(430, 340))
    pet2.move(-6000, -6000)
    record('pet pulled back on screen', pet2.clamp_to_screens() and pet2.screen() is not None
           and any(s.availableGeometry().contains(pet2.frameGeometry().center()) for s in app.screens()))
    pet2.deleteLater()

    # ── 3. 置頂自我修復 ──
    rival = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    rival.setGeometry(380, 280, 200, 200)
    rival.show()
    pump(app, 200)
    rh = winutil.hwnd_of(rival)
    covered = winutil.is_above(rh, h)
    pet.heal_topmost()
    pump(app, 100)
    record('topmost self-heal', covered and winutil.is_above(h, rh), f'covered before={covered}')
    rival.close()

    # ── 4. 動畫效能 ──
    cpu0 = proc.cpu_times()
    fps = measure_fps(pet, 3.0, app)
    record('anim 24fps APNG', fps >= 20, f'{fps:.1f} fps')
    pet.set_frames(load_frames(assets['sprite'], 256, frames=24, fps=60))
    fps60 = measure_fps(pet, 3.0, app)
    cpu1 = proc.cpu_times()
    cpu = (cpu1.user + cpu1.system - cpu0.user - cpu0.system) / 6.0 * 100
    record('anim 60fps 256px sprite', fps60 >= 50, f'{fps60:.1f} fps, cpu≈{cpu:.0f}% of one core (6s total)')
    mem = proc.memory_info().rss / 1e6
    record('memory', mem < 400, f'rss={mem:.0f}MB')

    # ── 5. 參考小窗：穿透切換 ──
    ref_img = Image.new('RGB', (520, 390), (125, 138, 163))
    fake_canvas = Image.new('RGB', (520, 390), (200, 120, 90))
    ref = RefWindow(pil_to_pixmap(ref_img), capture=lambda: fake_canvas)
    ref.move(800, 300)
    ref.show()
    pump(app, 300)
    rh = winutil.hwnd_of(ref)
    c = phys(ref, ref.center_global())
    before = winutil.root_at(*c) == rh
    ref.set_click_through(True)
    pump(app, 150)
    through = winutil.root_at(*c) != rh
    ref.set_click_through(False)
    pump(app, 150)
    back = winutil.root_at(*c) == rh
    record('ref click-through on/off', before and through and back,
           f'before={before} through={through} restored={back}')

    # ── 6. 全域快捷鍵＋按住比對 ──
    hub = winutil.HotkeyHub(app)
    got = []
    hub.triggered.connect(got.append)
    mods = winutil.MOD_CONTROL | winutil.MOD_ALT | winutil.MOD_SHIFT
    VK_F9, VK_F10, VK_CTRL, VK_ALT, VK_SHIFT = 0x78, 0x79, 0x11, 0x12, 0x10
    reg = hub.register(9, mods, VK_F9) and hub.register(10, mods, VK_F10)
    hub.triggered.connect(lambda hid: ref.begin_compare(VK_F10) if hid == 10 else None)
    held = []
    try:
        for vk in (VK_CTRL, VK_ALT, VK_SHIFT, VK_F9):
            key(vk)
        key(VK_F9, up=True)
        pump(app, 300)
        key(VK_F10)
        pump(app, 400)
        held.append(ref.compare_img is not None)
    finally:
        for vk in (VK_F10, VK_SHIFT, VK_ALT, VK_CTRL):
            key(vk, up=True)
    pump(app, 300)
    record('global hotkey', reg and 9 in got, f'registered={reg} got={got}')
    record('hold-to-compare', held == [True] and ref.compare_img is None, f'while held={held} after release={ref.compare_img is None}')
    hub.unregister_all()

    # ── 7. 前景視窗監聽 ──
    fg = winutil.ForegroundWatcher()
    seen = []
    fg.changed.connect(lambda hwnd, title: seen.append(title))
    probe = QWidget()
    probe.setWindowTitle('fg-probe')
    probe.setGeometry(100, 100, 200, 100)
    probe.show()
    probe.raise_()
    probe.activateWindow()
    pump(app, 500)
    record('foreground hook', 'fg-probe' in seen, f'events={seen[:3]}')
    probe.close()
    fg.close()
    pet.close()
    ref.close()
    pump(app, 100)

    # ── 8. 單一實例：第二份把參數交給第一份後結束 ──
    name = 'SAI2DC_selftest_' + uuid.uuid4().hex[:8]
    log = os.path.join(tmp, 'first.log')
    ready = os.path.join(tmp, 'ready')
    py = sys.executable
    first = subprocess.Popen([py, '-X', 'utf8', os.path.join(HERE, 'app.py'), '--instance-name', name,
                              '--state-dir', os.path.join(tmp, 'first'), '--log', log, '--ready-file', ready])
    try:
        for _ in range(200):
            if os.path.exists(ready):
                break
            time.sleep(0.05)
        t0 = time.perf_counter()
        second = subprocess.run([py, '-X', 'utf8', os.path.join(HERE, 'app.py'), '--instance-name', name,
                                 '--open', r'C:\art\handoff_test.psd'], timeout=30)
        dt = time.perf_counter() - t0
        time.sleep(0.5)
        text = open(log, encoding='utf-8').read() if os.path.exists(log) else ''
        record('single instance handoff', second.returncode == 0 and 'handoff_test.psd' in text and first.poll() is None,
               f'second exited {second.returncode} in {dt:.1f}s; first alive={first.poll() is None}')
    finally:
        first.terminate()
        first.wait(10)

    failed = [r for r in RESULTS if not r[1]]
    print(f'\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
