# -*- coding: utf-8 -*-
"""參照視窗：不在課程中也能放自己的參考圖——貼上剪貼簿、拖曳檔案、開啟檔案；一次一張、關掉後記住；
滾輪縮放（游標下的點不動）、放大時拖曳是平移圖片、雙擊回到整張；吸色（點一下複製色碼）；清除。
以暫存資料夾執行，不開啟 SAI2"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import companion, settings2  # noqa: E402
from ui2 import app as A, ref_window as RW  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


class FakeTracker:
    def __init__(self, *a, **k):
        self.locked_file = None

    def start(self): pass
    def stop(self): pass

    def get_state(self):
        return {'sai2_running': False, 'current_file': None, 'raw_current_file': None, 'session_draw': 0.0, 'files': {}}

    def get_draw_counter(self): return 0.0
    def today_draw_seconds(self): return 0.0
    def daily_history(self): return {}
    def resolve_alias(self, n): return n


qapp = QApplication(sys.argv[:1])
d = tmpdir()
s = settings2.Settings2(d)
s.set('prompted', {'welcome': True, 'legacy_watcher': True, 'practice_card': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
said = []
ctl.say = lambda text, *a, **k: said.append(text)
ctl.start()
pump(150)
saved = os.path.join(s.app_dir, 'reference', 'current.png')

# ─── 開啟：從快捷按鈕 ──
ctl.run_slot('reference')
pump(200)
w = ctl.ref_win
check(w is not None and w.kind == 'reference' and isinstance(w.mode, RW.ReferenceMode), 'reference window opened')
check(w.base is None and '貼上' in w.view.message and set(w.action_btns) >= {'file', 'paste', 'eyedrop', 'trash'},
      'empty: tells how to add a picture')

# ─── 貼上剪貼簿的圖（左紅右藍） ──
qimg = QImage(200, 100, QImage.Format_RGB32)
qimg.fill(QColor('#ff0000'))
for x in range(100, 200):
    for y in range(100):
        qimg.setPixelColor(x, y, QColor('#0000ff'))
QGuiApplication.clipboard().setImage(qimg)
w.mode.paste()
pump(100)
check(w.base is not None and w.base.size == (200, 100) and os.path.isfile(saved), 'pasted image shown and saved')
check(w.mode.info()[0] == '貼上的圖片', 'name shown')

# ─── 關掉再打開：記住 ──
w.close()
pump(100)
ctl.run_slot('reference')
pump(200)
w = ctl.ref_win
check(w.base is not None and w.base.size == (200, 100) and w.mode.name == '貼上的圖片', 'remembered after closing')
ctl.run_slot('reference')
check(ctl.ref_win is w, 'opening again keeps the same window')

# ─── 拖曳檔案進來（一次一張：取代舊的） ──
png = os.path.join(d, '人體參考.png')
Image.new('RGB', (120, 160), (0, 200, 0)).save(png)
md = QMimeData()
md.setUrls([QUrl.fromLocalFile(png)])
w.mode.drop(md)
pump(50)
check(w.base.size == (120, 160) and w.mode.name == '人體參考.png', 'dropped file replaces the picture')
bad = os.path.join(d, 'x.png')
open(bad, 'w').write('not an image')
w.mode._load_file(bad)
check(w.base.size == (120, 160) and any('無法開啟' in t for t in said), 'broken file → message, picture kept')
md2 = QMimeData()
md2.setText('hello')
QGuiApplication.clipboard().setMimeData(md2)
w.mode.paste()
check(any('剪貼簿裡沒有圖片' in t for t in said), 'nothing to paste → message')

# ─── 縮放、平移、雙擊回到整張 ──
w.mode.use(Image.new('RGB', (400, 300), (128, 128, 128)), '灰.png')
w.resize(400, 330)
pump(100)
v = w.view
center = QPointF(v.width() / 2, v.height() / 2)


def wheel(pos, steps):
    ev = QWheelEvent(pos, v.mapToGlobal(pos), QPoint(0, 0), QPoint(0, 120 * steps), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    v.wheelEvent(ev)


corner = QPointF(v.width() * 0.25, v.height() * 0.25)
before = v.image_rect()
u = ((corner.x() - before.x()) / before.width(), (corner.y() - before.y()) / before.height())
wheel(corner, 3)
r = v.image_rect()
u2 = ((corner.x() - r.x()) / r.width(), (corner.y() - r.y()) / r.height())
check(v.zoom > 1.9 and abs(u[0] - u2[0]) < 0.02 and abs(u[1] - u2[1]) < 0.02, f'wheel zoom keeps the point under the cursor ({u} → {u2})')
check(w.mode.info()[1] == f'{int(round(v.zoom * 100))}%', 'zoom shown in the info line')
pos0 = w.pos()
press = QMouseEvent(QMouseEvent.MouseButtonPress, center, v.mapToGlobal(center), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
v.mousePressEvent(press)
moved = center + QPointF(30, 20)
v.mouseMoveEvent(QMouseEvent(QMouseEvent.MouseMove, moved, v.mapToGlobal(moved), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
v.mouseReleaseEvent(QMouseEvent(QMouseEvent.MouseButtonRelease, moved, v.mapToGlobal(moved), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
check(w.pos() == pos0 and v.image_rect().x() != r.x(), 'zoomed in: dragging pans the picture, not the window')
v.mouseDoubleClickEvent(None)
check(v.zoom == 1.0 and v.pan == QPointF(0, 0), 'double-click fits the whole picture again')
wheel(center, -3)
check(v.zoom == 1.0, 'cannot zoom out past the whole picture')

# ─── 吸色 ──
w.mode.use(Image.new('RGB', (200, 100), (255, 0, 0)).copy(), '紅藍')
img = w.base
for x in range(100, 200):
    for y in range(100):
        img.putpixel((x, y), (0, 0, 255))
w.mode.use(img, '紅藍')
pump(50)
w.mode.toggle_pick()
check(v.picking and w.action_btns['eyedrop'].isChecked(), 'pick mode on')
r = v.image_rect()
for frac, want in ((0.25, '#FF0000'), (0.75, '#0000FF')):
    p = QPointF(r.x() + r.width() * frac, r.y() + r.height() / 2)
    v.mousePressEvent(QMouseEvent(QMouseEvent.MouseButtonPress, p, v.mapToGlobal(p), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    check(QGuiApplication.clipboard().text() == want and want in w.mode.info()[0], f'picked {want}')
w.mode.toggle_pick()
check(not v.picking, 'pick mode off')

# ─── 檢查工具照常；清除 ──
w._toggle_tool('gray')
check(w.tools['gray'] and v.pm is not None, 'check tools work on the reference')
w.mode.clear()
check(w.base is None and not os.path.isfile(saved) and s.get('ref.reference_name') == '', 'cleared')
w.close()
ctl.quit()
A.release_widgets(qapp)
done()
