# -*- coding: utf-8 -*-
"""對話泡泡外觀設定（選圖、圈選文字範圍、顏色、大小、還原）、寵物頁不再有提醒設定、
規則頁加動作時維持捲動位置。以暫存資料夾與假的追蹤器執行"""
import os
import sys
import time
import warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QColorDialog, QFileDialog, QLabel, QPushButton  # noqa: E402

from core import bubble_skin as B, companion, settings2  # noqa: E402
from ui2 import app as A, bubble_editor as BE  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


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
        return {}

    def resolve_alias(self, n):
        return n


qapp = QApplication(sys.argv[:1])
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
ctl.start()
pump(150)

# ─── 寵物頁：提醒設定移走，改為泡泡外觀 ──
ctl.open_main('寵物')
pump(300)
mw = ctl._main
pp = mw.page_widget('寵物', 'PetPage')
texts = ' '.join(lb.text() for lb in pp.findChildren(QLabel))
check('連續動筆提醒休息' not in texts and '顯示睡覺' not in texts, 'reminder rows removed')
check('對話泡泡外觀' in texts and '規則' in texts, 'bubble card shown, points to rules')
check(not pp.bubble_range.isEnabled() and pp.bubble_preview.pix is None, 'built-in bubble by default')

src = tmpdir()
png = os.path.join(src, 'frame.png')
Image.new('RGBA', (200, 120), (250, 230, 200, 255)).save(png)
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (png, ''))
seen = {}


def fake_exec(dlg):
    seen['dlg'] = dlg
    c = dlg.canvas
    k = c.k
    for kind, x, y in ((QMouseEvent.MouseButtonPress, 40, 30), (QMouseEvent.MouseMove, 160, 90),
                       (QMouseEvent.MouseButtonRelease, 160, 90)):
        pos = QPointF(x * k, y * k)
        btns = Qt.LeftButton if kind != QMouseEvent.MouseButtonRelease else Qt.NoButton
        ev = QMouseEvent(kind, pos, c.mapToGlobal(pos.toPoint()), Qt.LeftButton, btns, Qt.NoModifier)
        {QMouseEvent.MouseButtonPress: c.mousePressEvent, QMouseEvent.MouseMove: c.mouseMoveEvent,
         QMouseEvent.MouseButtonRelease: c.mouseReleaseEvent}[kind](ev)
    seen['preview'] = dlg.long.margins()
    return 1


BE.TextRangeDialog.exec = fake_exec
pp._bubble_pick()
pump(50)
skin = s.get('pet.bubble_skin')
check(skin['image'] and B.image_path(s.app_dir, skin), 'image copied into settings folder')
check(skin['text'] == [40, 30, 120, 60], f'drawn text range saved {skin["text"]}')
check(seen.get('preview') == (40, 30, 40, 30), 'dialog preview follows the drag')
check(ctl.bubble.body.pix is not None and pp.bubble_range.isEnabled(), 'pet bubble uses the skin')

# 拖曳邊線調整
c = BE.RangeCanvas(seen['dlg'].canvas.pix, [40, 30, 120, 60])
k = c.k


def drag(x0, y0, x1, y1):
    for kind, x, y in ((QMouseEvent.MouseButtonPress, x0, y0), (QMouseEvent.MouseMove, x1, y1),
                       (QMouseEvent.MouseButtonRelease, x1, y1)):
        pos = QPointF(x * k, y * k)
        ev = QMouseEvent(kind, pos, QPointF(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        {QMouseEvent.MouseButtonPress: c.mousePressEvent, QMouseEvent.MouseMove: c.mouseMoveEvent,
         QMouseEvent.MouseButtonRelease: c.mouseReleaseEvent}[kind](ev)


drag(160, 60, 180, 60)
check(c.rect_px == [40, 30, 140, 60], f'drag right edge {c.rect_px}')
drag(100, 60, 110, 70)
check(c.rect_px == [50, 40, 140, 60], f'drag inside moves {c.rect_px}')
drag(100, 60, 300, 60)
check(c.rect_px == [60, 40, 140, 60], 'cannot move outside the image')

ctl.bubble.show_message('畫得好！')
pump(50)
l, t, r, b = ctl.bubble.body.margins()
check(ctl.bubble.width() >= l + r and ctl.bubble.height() >= t + b, 'bubble at least as big as the corners')
ctl.bubble.hide()

QColorDialog.getColor = staticmethod(lambda *a, **k: QColor('#ff0000'))
pp._bubble_pick_color()
check(s.get('pet.bubble_skin.color') == '#ff0000' and 'ff0000' in ctl.bubble.label.styleSheet(), 'text colour')
pp.bubble_scale.setValue(50)
check(s.get('pet.bubble_skin.scale') == 0.5 and ctl.bubble.body.skin['scale'] == 0.5, 'scale applied')
old = s.get('pet.bubble_skin.image')
pp._bubble_pick()
check(not os.path.exists(os.path.join(s.app_dir, B.BUBBLES_DIR, old)), 'old image cleaned up after replacing')
pp._bubble_restore()
check(s.get('pet.bubble_skin') == B.DEFAULT and ctl.bubble.body.pix is None, 'restore built-in bubble')
check(not os.listdir(os.path.join(s.app_dir, B.BUBBLES_DIR)), 'images removed on restore')

# ─── 規則頁：加動作時不捲動 ──
from core import rules as R  # noqa: E402
s.set('rules', [R.new_rule(e['trigger'], e['actions']) for e in R.EXAMPLES] * 1
      + [R.new_rule(e['trigger'], e['actions']) for e in R.EXAMPLES])
s.save()
mw.resize(1000, 600)
mw.show()
mw.show_page('規則')
pump(200)
rp = mw.page_widget('規則', 'RulesPage')
rp._build()
pump(100)
bar = rp._scroll_bar()
check(bar is not None and bar.maximum() > 300, f'rules page scrolls ({bar.maximum() if bar else None})')
bar.setValue(bar.maximum() - 100)
pump(50)
before = bar.value()
btns = [x for x in rp.findChildren(QPushButton) if x.text() == '＋ 再加一個動作' and x.isVisible()]
mw.activateWindow()
with warnings.catch_warnings():
    warnings.simplefilter('ignore', DeprecationWarning)
    qapp.setActiveWindow(mw)
btns[-1].setFocus()                  # 實際點擊時按鈕有焦點；按鈕被移除後焦點跳到別處會讓捲動區自動捲過去
pump(50)
btns[-1].click()
pump(150)
check(abs(bar.value() - before) <= 2, f'scroll kept after adding an action ({before} → {bar.value()})')
rm = [x for x in rp.findChildren(QPushButton) if x.toolTip() == '移除這個動作' and x.isVisible()]
before = bar.value()
rm[0].click()
pump(150)
check(abs(bar.value() - before) <= 2 or bar.value() == bar.maximum(), 'scroll kept after removing an action')

mw.close()
ctl.quit()
A.release_widgets(qapp)
done()
