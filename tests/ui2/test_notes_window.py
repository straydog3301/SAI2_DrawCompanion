# -*- coding: utf-8 -*-
"""浮動筆記視窗：頁籤、閱讀／編輯模式（完成或 Ctrl+S 存檔回到閱讀）、程式碼區塊與段落的複製、
在編輯模式貼上剪貼簿的圖片、點圖片放大並複製回剪貼簿、目錄、置頂、切換頁籤與關閉時自動存檔、新增／改名／刪除。
以暫存資料夾執行"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from core import companion, notes as N, settings2  # noqa: E402
from ui2 import app as A, notes_window as NW  # noqa: E402


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
s = settings2.Settings2(tmpdir())
s.set('prompted', {'welcome': True, 'legacy_watcher': True, 'practice_card': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
ctl.say = lambda *a, **k: None
ctl.start()
pump(150)
store = N.NoteStore(s.app_dir)

ctl.run_slot('notes')
pump(300)
w = ctl.notes_win
check(w is not None and w.isVisible() and w.tabs.count() == 1 and w.tabs.tabText(0) == '筆記', 'opened with the sample note')
check(not w.editing and w.mode_btn.text() == '編輯' and w.pin_btn.isChecked()
      and bool(w.windowFlags() & Qt.WindowStaysOnTopHint), 'read mode, pinned by default')


def reader_labels():
    """閱讀區顯示的文字（標題去掉 ▾/▸）"""
    pump(30)
    out = [lb.text().lstrip('▾▸ ') for lb in w.reader.widget().findChildren(QLabel)]
    return out + [t.text() for t in w.reader.widget().findChildren(NW.NoteText)]


def copy_buttons():
    return [b for b in w.reader.widget().findChildren(QPushButton) if b.toolTip() == '複製']


def copy_button_for(text):
    """區塊裡文字是 text 的那張卡片的「複製」按鈕"""
    for b in copy_buttons():
        if any(text in t.text() for t in b.parentWidget().findChildren(NW.NoteText)):
            return b
    return None


def clip_text(want):
    """讀剪貼簿；剪貼簿被佔用時程式會稍後重試寫入，這裡也等一下（最多約 1.5 秒）"""
    for _ in range(75):
        got = QGuiApplication.clipboard().text()
        if got == want:
            return got
        pump(20)
    return got


# ─── 編輯 → 完成 ──
w.toggle_edit()
check(w.editing and w.mode_btn.text() == '完成' and '# 我的筆記' in w.editor.toPlainText(), 'edit mode shows the markdown')
w.editor.setPlainText('# 色彩\n\n常用 **主色**\n\n```\n#7C3AED\n```\n\n## 筆刷\n\n```\n大小 12 / 濃度 80%\n```\n')
w.finish_edit()
check(not w.editing and store.read('筆記').startswith('# 色彩') and w.status.text() == '已存檔', 'saved, back to read mode')
labels = reader_labels()
check('色彩' in labels and '#7C3AED' in labels and '大小 12 / 濃度 80%' in labels, f'blocks shown ({labels})')
cps = copy_buttons()
check(len(cps) == 2 and copy_button_for('主色') is None, f'only ``` blocks get a copy button ({len(cps)})')
copy_button_for('#7C3AED').click()
check(clip_text('#7C3AED') == '#7C3AED' and w.status.text() == '已複製', 'copy a code block')
copy_button_for('大小 12').click()
check(clip_text('大小 12 / 濃度 80%') == '大小 12 / 濃度 80%', 'copy another block right after')

# ─── 單一換行照樣換行；空行不會把文字切成好幾塊 ──
w.toggle_edit()
w.editor.setPlainText('第一行\n第二行\n\n隔一個空行')
w.finish_edit()
texts = [t.text() for t in w.reader.widget().findChildren(NW.NoteText)]
check(texts == ['第一行\n第二行\n隔一個空行'] or texts == ['第一行\u2028第二行\n隔一個空行'], f'line breaks kept, one text section ({texts!r})')
check(not copy_buttons(), 'plain text has no copy button')
doc = w.reader.widget().findChildren(NW.NoteText)[0].document()
margins = [doc.findBlockByNumber(i).blockFormat().bottomMargin() for i in range(doc.blockCount())]
check(margins[0] == 0 and margins[1] > 0 and margins[2] == 0, f'gap only where a blank line was ({margins})')
w.toggle_edit()
w.editor.setPlainText('# 色彩\n\n常用 **主色**\n\n```\n#7C3AED\n```\n\n## 筆刷\n\n```\n大小 12 / 濃度 80%\n```\n')
w.finish_edit()

# ─── 目錄 ──
check(w.toc_btn.isEnabled() and [h[2] for h in N.headings(store.read('筆記'))] == ['色彩', '筆刷']
      and len(w.heading_widgets) == 2, 'table of contents from headings')

# ─── 太長的內容在卡片裡換行，複製按鈕不會被擠出視窗 ──
w.toggle_edit()
w.editor.setPlainText('# 長\n\nhttps://example.com/' + 'a' * 150 + '\n\n```\n' + 'C:/path/' + 'x' * 150 + '\n```\n')
w.finish_edit()
w.resize(320, 600)
pump(150)
vw = w.reader.viewport().width()
rights = [b.mapTo(w.reader.viewport(), b.rect().bottomRight()).x() for b in copy_buttons()]
rights += [t.mapTo(w.reader.viewport(), t.rect().bottomRight()).x() for t in w.reader.widget().findChildren(NW.NoteText)]
check(len(rights) == 3 and max(rights) <= vw and w.reader.widget().width() <= vw,
      f'long lines wrap inside the window ({rights} / {vw})')
texts = w.reader.widget().findChildren(NW.NoteText)
check(all(t.height() > 40 for t in texts), 'wrapped cards grow taller')

# ─── 標題收合 ──
w.toggle_edit()
w.editor.setPlainText('# A\n\n一\n\n## A1\n\n二\n\n# B\n\n三\n')
w.finish_edit()
pump(50)
hs = w.heading_widgets
check([h.text() for h in hs] == ['▾ A', '▾ A1', '▾ B'], 'headings show a collapse arrow')


def shown():
    return [t.text() for t in w.reader.widget().findChildren(NW.NoteText) if not t.isHidden()
            and not t.parentWidget().isHidden()]


hs[0].clicked.emit()
check(hs[0].text() == '▸ A' and hs[1].isHidden() and shown() == ['三'] and not hs[2].isHidden(),
      'collapsing a heading hides everything up to the next same-level heading')
check(store.collapsed('筆記') == {'A'}, 'collapsed state saved')
hs[1].clicked.emit()
hs[0].clicked.emit()
check(not hs[1].isHidden() and shown() == ['一', '三'], 'expanding keeps the sub-heading collapsed')
w.render()
pump(30)
hs = w.heading_widgets
check(hs[1].collapsed and not hs[0].collapsed and shown() == ['一', '三'], 'collapsed state remembered after re-render')
hs[0].clicked.emit()
w._jump(hs[1])
pump(50)
check(not hs[0].collapsed and not hs[1].isHidden(), 'table of contents opens the parent heading')
hs[1].clicked.emit()
w.toggle_edit()
w.editor.setPlainText('# 色彩\n\n常用 **主色**\n\n```\n#7C3AED\n```\n\n## 筆刷\n\n```\n大小 12 / 濃度 80%\n```\n')
w.finish_edit()

# ─── 編輯模式貼上圖片 ──
w.toggle_edit()
cur = w.editor.textCursor()
cur.movePosition(cur.MoveOperation.End)
w.editor.setTextCursor(cur)
qimg = QImage(120, 80, QImage.Format_RGB32)
qimg.fill(QColor('#22c55e'))
md = QMimeData()
md.setImageData(qimg)
check(w.editor.canInsertFromMimeData(md), 'editor accepts a clipboard image')
w.editor.insertFromMimeData(md)
text = w.editor.toPlainText()
check('![](images/' in text, f'image link inserted ({text[-40:]!r})')
imgs = os.listdir(os.path.join(s.app_dir, 'notes', 'images'))
check(len(imgs) == 1 and imgs[0].endswith('.png'), 'pasted image saved as a file')
w.finish_edit()
pics = [lb for lb in w.reader.widget().findChildren(NW._ClickLabel)]
check(len(pics) == 1 and not pics[0].pixmap().isNull(), 'image shown in read mode')
pics[0].clicked.emit()
pump(100)
pv = w._preview
check(pv.isVisible() and pv.pm.width() == 120, 'click → enlarged preview')
pv.copy()
for _ in range(75):
    if not QGuiApplication.clipboard().image().isNull():
        break
    pump(20)
check(QGuiApplication.clipboard().image().pixelColor(5, 5).name() == '#22c55e' and pv.copy_btn.text() == '已複製',
      'copied back to the clipboard')
pv.close()

# ─── 置頂 ──
w.pin_btn.setChecked(False)
pump(100)
check(not (w.windowFlags() & Qt.WindowStaysOnTopHint) and s.get('notes.pinned') is False and w.isVisible(), 'unpinned')
w.pin_btn.setChecked(True)
pump(100)
check(bool(w.windowFlags() & Qt.WindowStaysOnTopHint) and s.get('notes.pinned') is True, 'pinned again')

# ─── 新增、切換頁籤時自動存檔、改名、刪除 ──
w.new_note()
check(w.tabs.count() == 2 and w.editing and w.current == '新筆記', 'new note opens in edit mode')
w.editor.setPlainText('# 臨時\n\n電話 0912')
w.tabs.setCurrentIndex(0)
pump(50)
check(store.read('新筆記').startswith('# 臨時') and not w.editing and w.current == '筆記', 'switching tabs saves the edit')
w.rename('新筆記', '臨時筆記')
check([w.tabs.tabText(i) for i in range(w.tabs.count())] == ['筆記', '臨時筆記'] and w.current == '臨時筆記', 'renamed')
w.delete('臨時筆記', confirm=False)
check(w.tabs.count() == 1 and not os.path.isfile(store.path('臨時筆記')), 'deleted')

# ─── 關閉時存檔、記住位置；快捷鍵切換 ──
w.toggle_edit()
w.editor.setPlainText('# 關閉前寫的')
w.move(300, 200)
w.close()
pump(100)
check(store.read('筆記') == '# 關閉前寫的' and ctl.notes_win is None, 'closing while editing saves')
check(s.get('notes.geometry')[:2] == [w.x(), w.y()], 'position remembered')
ctl.toggle_notes()
pump(200)
w2 = ctl.notes_win
check(w2 is not None and w2.isVisible() and w2.current == '筆記' and w2.pos() == w.pos() and w2.size() == w.size(),
      'reopens at the same place')
ctl.toggle_notes()
pump(100)
check(ctl.notes_win is None, 'hotkey / button toggles it closed')
ctl.quit()
A.release_widgets(qapp)
done()
