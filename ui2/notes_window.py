# -*- coding: utf-8 -*-
"""
notes_window.py - 浮動筆記視窗

頁籤是一則則筆記（core/notes.py）；閱讀模式把 Markdown 顯示成區塊：標題、段落、程式碼區塊（有「複製」）、圖片
（點一下放大，可以複製回剪貼簿）；按「編輯」改原文，「完成」或 Ctrl+S 存檔回到閱讀模式。可以切換置頂；
在編輯模式按 Ctrl+V 貼上剪貼簿的圖片。
"""

from __future__ import annotations

import io
import os
import subprocess

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut, QTextCursor, QTextOption
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTabBar, QTextBrowser,
                               QVBoxLayout, QWidget)

from core import notes as N
from ui2 import theme, winutil
from ui2.icons import icon
from ui2.widgets import button, label

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')


def _qimage_to_pil(qimg: QImage) -> Image.Image:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    qimg.save(buf, 'PNG')
    return Image.open(io.BytesIO(bytes(buf.data()))).copy()


class NoteEditor(QPlainTextEdit):
    """編輯模式：貼上剪貼簿的圖片時存成檔案，插入 Markdown 圖片連結"""

    def __init__(self, store: N.NoteStore, on_save):
        super().__init__()
        self.store = store
        self.setTabChangesFocus(False)
        self.setPlaceholderText('用 Markdown 寫筆記：# 標題、- 清單、``` 程式碼區塊（閱讀時可以一鍵複製）。Ctrl+V 可以貼上圖片')
        QShortcut(QKeySequence.Save, self, activated=on_save)

    def canInsertFromMimeData(self, md):
        return md.hasImage() or self._image_files(md) or super().canInsertFromMimeData(md)

    @staticmethod
    def _image_files(md) -> list[str]:
        return [u.toLocalFile() for u in (md.urls() if md.hasUrls() else [])
                if u.toLocalFile().lower().endswith(IMAGE_EXTS) and os.path.isfile(u.toLocalFile())]

    def insertFromMimeData(self, md):
        imgs = []
        for path in self._image_files(md):
            try:
                with Image.open(path) as im:
                    imgs.append(im.copy())
            except OSError:
                pass
        if not imgs and md.hasImage():
            q = md.imageData()
            if q is not None and not q.isNull():
                imgs.append(_qimage_to_pil(q))
        if not imgs:
            return super().insertFromMimeData(md)
        cur = self.textCursor()
        lead = '' if cur.atBlockStart() else '\n'
        refs = [self.store.save_image(im) for im in imgs]
        cur.insertText(lead + '\n'.join(f'![]({r})' for r in refs) + '\n')


class ImagePreview(QDialog):
    """點筆記裡的圖片：放大看，可以複製回剪貼簿"""

    def __init__(self, parent, path: str):
        super().__init__(parent)
        self.setWindowTitle(os.path.basename(path))
        self.path = path
        self.pm = QPixmap(path)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        screen = (parent.screen() if parent else QGuiApplication.primaryScreen()).availableGeometry()
        shown = self.pm.scaled(int(screen.width() * 0.8), int(screen.height() * 0.75), Qt.KeepAspectRatio,
                               Qt.SmoothTransformation) if (self.pm.width() > screen.width() * 0.8
                                                            or self.pm.height() > screen.height() * 0.75) else self.pm
        pic = QLabel()
        pic.setPixmap(shown)
        pic.setAlignment(Qt.AlignCenter)
        lay.addWidget(pic, 1)
        row = QHBoxLayout()
        row.addWidget(label(f'{self.pm.width()}×{self.pm.height()}', 'caption'))
        row.addStretch(1)
        self.copy_btn = button('複製到剪貼簿', 'primary')
        self.copy_btn.clicked.connect(self.copy)
        folder = button('開啟資料夾', 'ghost', ic='works')
        folder.clicked.connect(lambda: subprocess.Popen(['explorer', '/select,', os.path.normpath(self.path)]))
        close = button('關閉', 'secondary')
        close.clicked.connect(self.accept)
        for b in (self.copy_btn, folder, close):
            row.addWidget(b)
        lay.addLayout(row)

    def copy(self):
        set_clipboard(image=self.pm.toImage())
        self.copy_btn.setText('已複製')


def set_clipboard(text: str | None = None, image=None, tries: int = 20) -> bool:
    """寫入剪貼簿並讀回確認。Windows 剪貼簿剛被別的程式（例如剪貼簿歷程）佔用時會寫不進去，
    就每 50ms 再試一次（最多約 1 秒），不卡住畫面。回傳這一次是否已寫入"""
    cb = QGuiApplication.clipboard()
    if image is not None:
        cb.setImage(image)
        ok = not cb.image().isNull()
    else:
        cb.setText(text)
        ok = cb.text() == text
    if not ok and tries > 1:
        QTimer.singleShot(50, lambda: set_clipboard(text, image, tries - 1))
    return ok


class NoteText(QTextBrowser):
    """閱讀模式的一段文字：寬度跟著視窗，太長的英文、網址、路徑、程式碼也會在任何位置換行
    （QLabel 只能在空白處換行，會把卡片撐出視窗外），高度隨內容長高，不出現自己的捲軸"""

    def __init__(self, text: str, code: bool = False):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setOpenExternalLinks(True)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(40)
        self.document().setDocumentMargin(0)
        self.document().setIndentWidth(theme.size(14))   # 清單縮排（預設 40px 太寬）
        self.viewport().setCursor(Qt.IBeamCursor)
        css = 'QTextBrowser{background:transparent;border:none;padding:0;}'
        if code:
            css += theme.scale_css('QTextBrowser{font-family:Consolas,"Microsoft JhengHei UI",monospace;font-size:13px;}')
        self.setStyleSheet(css)
        if code:
            self.setPlainText(text)
        else:
            self.setMarkdown(text)
            self._space_paragraphs(text)
        self._fit()

    def _space_paragraphs(self, markdown: str):
        """空行分開的段落之間留出間距；單一換行只換行不加間距。
        Qt 把每個強制換行都變成獨立的段落，所以依原文每一行後面是否接空行來決定（對不上時——例如表格——就不調整）"""
        lines = markdown.split('\n')
        ends = [i + 1 < len(lines) and not lines[i + 1].strip() for i, ln in enumerate(lines) if ln.strip()]
        doc = self.document()
        if doc.blockCount() != len(ends):
            return
        gap = theme.size(10)
        block = doc.begin()
        for para_end in ends:
            fmt = block.blockFormat()
            fmt.setTopMargin(0)
            fmt.setBottomMargin(gap if para_end else 0)
            QTextCursor(block).setBlockFormat(fmt)
            block = block.next()

    def text(self) -> str:
        return self.toPlainText()

    def _fit(self):
        self.document().setTextWidth(max(1, self.viewport().width()))
        h = int(self.document().size().height() + 0.99) + 2
        if self.height() != h:
            self.setFixedHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def wheelEvent(self, e):
        e.ignore()                                   # 讓外層的閱讀區捲動


class _ClickLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class _Heading(QLabel):
    """可以點一下收合／展開的標題：收合時藏起底下的內容，直到下一個同層或更上層的標題"""
    clicked = Signal()

    def __init__(self, title: str, level: int, collapsed: bool = False):
        super().__init__()
        self.title, self.level, self.collapsed = title, level, collapsed
        self.setWordWrap(True)
        self.setCursor(Qt.PointingHandCursor)
        size = {1: 20, 2: 17, 3: 15}.get(level, 14)
        self.setStyleSheet(theme.scale_css(f'font-size:{size}px;font-weight:700;margin-top:4px;'))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._update()

    def _update(self):
        self.setText(('▸ ' if self.collapsed else '▾ ') + self.title)
        self.setToolTip('點一下展開' if self.collapsed else '點一下收合')

    def set_collapsed(self, on: bool):
        self.collapsed = on
        self._update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class NotesWindow(QWidget):
    closed = Signal()

    def __init__(self, ctl):
        super().__init__(None, Qt.Window)
        self.ctl = ctl
        self.store = N.NoteStore(ctl.settings.app_dir)
        self.setWindowTitle('DrawCompanion 筆記')
        self.setWindowIcon(ctl.qapp.windowIcon())
        self.setStyleSheet(theme.QSS + f'NotesWindow{{background:{theme.BG};}}')
        self.current: str | None = None
        self.editing = False
        self.heading_widgets: list[QWidget] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.tabs = QTabBar()
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._tab_menu)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabMoved.connect(lambda _a, _b: self._save_order())
        top.addWidget(self.tabs, 1)
        add = button('', 'ghost', tip='新增一則筆記')
        add.setText('＋')
        add.clicked.connect(self.new_note)
        top.addWidget(add)
        lay.addLayout(top)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.toc_btn = button('目錄', 'ghost', tip='跳到這則筆記的標題')
        self.toc_btn.clicked.connect(self._show_toc)
        self.pin_btn = button('置頂', 'ghost', tip='永遠顯示在其他視窗上面')
        self.pin_btn.setCheckable(True)
        self.pin_btn.toggled.connect(self.set_pinned)
        self.mode_btn = button('編輯', 'primary')
        self.mode_btn.clicked.connect(self.toggle_edit)
        self.status = label('', 'caption')
        bar.addWidget(self.toc_btn)
        bar.addWidget(self.status, 1)
        bar.addWidget(self.pin_btn)
        bar.addWidget(self.mode_btn)
        lay.addLayout(bar)

        self.stack = QStackedWidget()
        self.reader = QScrollArea()
        self.reader.setWidgetResizable(True)
        self.reader.setFrameShape(QFrame.NoFrame)
        self.reader.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor = NoteEditor(self.store, self.finish_edit)
        self.stack.addWidget(self.reader)
        self.stack.addWidget(self.editor)
        lay.addWidget(self.stack, 1)
        self._status_timer = QTimer(self, singleShot=True, timeout=lambda: self.status.setText(''))

        self._load_tabs()
        self._restore()

    # ── 頁籤 ──
    def _load_tabs(self, select: str | None = None):
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for name in self.store.names():
            self.tabs.addTab(name)
        self.tabs.blockSignals(False)
        names = [self.tabs.tabText(i) for i in range(self.tabs.count())]
        target = select or self.store.current()
        idx = names.index(target) if target in names else 0
        self.tabs.setCurrentIndex(idx)
        self._open(names[idx] if names else None)

    def _save_order(self):
        names = [self.tabs.tabText(i) for i in range(self.tabs.count())]
        for i, n in enumerate(names):
            self.store.move(n, i)

    def _tab_changed(self, idx):
        if idx < 0:
            return
        if self.editing:
            self._save_edit()
            self._set_editing(False)
        self._open(self.tabs.tabText(idx))

    def _open(self, name: str | None):
        self.current = name
        if name:
            self.store.set_current(name)
        self.render()

    def new_note(self):
        if self.editing:
            self._save_edit()
        name = self.store.create('新筆記')
        self._load_tabs(select=name)
        self.toggle_edit()

    def _tab_menu(self, pos):
        idx = self.tabs.tabAt(pos)
        if idx < 0:
            return
        name = self.tabs.tabText(idx)
        menu = QMenu(self)
        menu.addAction('重新命名…', lambda: self.rename(name))
        menu.addAction('刪除這則筆記', lambda: self.delete(name))
        menu.exec(self.tabs.mapToGlobal(pos))

    def rename(self, name: str, new: str | None = None):
        if new is None:
            new, ok = QInputDialog.getText(self, '重新命名', '筆記名稱', text=name)
            if not ok:
                return
        if self.editing and self.current == name:
            self._save_edit()
        self._load_tabs(select=self.store.rename(name, new))

    def delete(self, name: str, confirm: bool = True):
        if confirm and QMessageBox.question(self, '刪除筆記', f'要刪除「{name}」嗎？刪除後無法復原。') != QMessageBox.Yes:
            return
        self.editing = False
        self._set_editing(False)
        self.store.delete(name)
        self._load_tabs()

    # ── 閱讀模式 ──
    def render(self):
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(4, 4, 8, 12)
        lay.setSpacing(8)
        self.heading_widgets = []
        self._items = []                      # [(元件, 它所在的各層標題)]——收合時依此決定顯示與否
        text = self.store.read(self.current) if self.current else ''
        parts = N.blocks(text)
        collapsed = self.store.collapsed(self.current) if self.current else set()
        if not parts:
            lay.addWidget(label('這則筆記還是空的。按「編輯」開始寫。', 'muted'))
        stack: list = []                      # 目前所在的各層標題
        for b in parts:
            kind = b[0]
            if kind == 'heading':
                while stack and stack[-1].level >= b[1]:
                    stack.pop()
                w = _Heading(b[2], b[1], b[2] in collapsed)
                w.clicked.connect(lambda h=w: self.toggle_heading(h))
                self.heading_widgets.append(w)
            elif kind == 'code':
                w = self._card(b[2], b[2], code=True)
            elif kind == 'image':
                w = self._image(b[1], b[2])
            else:
                w = NoteText(N.hard_breaks(b[1]))
                w.setContentsMargins(4, 0, 4, 0)
            lay.addWidget(w)
            self._items.append((w, list(stack)))
            if kind == 'heading':
                stack.append(w)
        lay.addStretch(1)
        self.reader.setWidget(holder)
        self._apply_collapse()
        self.toc_btn.setEnabled(bool(self.heading_widgets))

    def _apply_collapse(self):
        for w, parents in self._items:
            w.setVisible(not any(p.collapsed for p in parents))

    def toggle_heading(self, h, collapsed: bool | None = None):
        h.set_collapsed(not h.collapsed if collapsed is None else collapsed)
        if self.current:
            self.store.set_collapsed(self.current, {w.title for w in self.heading_widgets if w.collapsed})
        self._apply_collapse()

    def _jump(self, h):
        """目錄跳到標題：被收在上層標題裡就先展開上層"""
        for w, parents in self._items:
            if w is h:
                for p in parents:
                    if p.collapsed:
                        self.toggle_heading(p, False)
        QTimer.singleShot(0, lambda: self.reader.verticalScrollBar().setValue(h.y()))

    def _card(self, shown: str, copy_text: str, code: bool = False) -> QWidget:
        card = QFrame()
        card.setObjectName('notecard')
        bg = theme.SURFACE3 if code else theme.SURFACE2
        card.setStyleSheet(f'QFrame#notecard{{background:{bg};border-radius:10px;}}')
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 8, 6, 8)
        row.setSpacing(6)
        row.addWidget(NoteText(shown, code), 1)
        cp = QPushButton()
        cp.setIcon(icon('paste', theme.MUTED, 16))
        cp.setToolTip('複製')
        cp.setFixedSize(theme.size(28), theme.size(28))
        cp.setCursor(Qt.PointingHandCursor)
        cp.setStyleSheet('QPushButton{background:transparent;border:none;border-radius:6px;padding:0;}'
                         f'QPushButton:hover{{background:{theme.HOVER};}}')
        cp.clicked.connect(lambda: self.copy_text(copy_text))
        row.addWidget(cp, 0, Qt.AlignTop)
        return card

    def _image(self, alt: str, ref: str) -> QWidget:
        path = self.store.image_path(ref)
        pm = QPixmap(path) if os.path.isfile(path) else QPixmap()
        if pm.isNull():
            return label(f'（找不到圖片：{ref}）', 'warn')
        lb = _ClickLabel()
        maxw = max(160, self.reader.viewport().width() - 24)
        lb.setPixmap(pm.scaled(min(maxw, pm.width()), theme.size(220), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lb.setCursor(Qt.PointingHandCursor)
        lb.setToolTip((alt + '\n' if alt else '') + '點一下放大，可以複製回剪貼簿')
        lb.clicked.connect(lambda p=path: self.preview(p))
        return lb

    def preview(self, path: str):
        self._preview = ImagePreview(self, path)
        self._preview.show()

    def copy_text(self, text: str):
        set_clipboard(text=text)
        self.flash('已複製')

    def flash(self, text: str):
        self.status.setText(text)
        self._status_timer.start(2000)

    def _show_toc(self):
        text = self.store.read(self.current) if self.current else ''
        menu = QMenu(self)
        for (_i, level, title), w in zip(N.headings(text), self.heading_widgets):
            menu.addAction('　' * (level - 1) + title, lambda w=w: self._jump(w))
        menu.exec(self.toc_btn.mapToGlobal(self.toc_btn.rect().bottomLeft()))

    # ── 編輯模式 ──
    def toggle_edit(self):
        if self.editing:
            self.finish_edit()
        elif self.current:
            self.editor.setPlainText(self.store.read(self.current))
            self._set_editing(True)
            self.editor.setFocus()

    def _set_editing(self, on: bool):
        self.editing = on
        self.stack.setCurrentWidget(self.editor if on else self.reader)
        self.mode_btn.setText('完成' if on else '編輯')
        self.toc_btn.setVisible(not on)

    def _save_edit(self):
        if self.current:
            self.store.write(self.current, self.editor.toPlainText())

    def finish_edit(self):
        if not self.editing:
            return
        self._save_edit()
        self._set_editing(False)
        self.render()
        self.flash('已存檔')

    # ── 置頂、位置 ──
    def set_pinned(self, on: bool):
        self.ctl.settings.set('notes.pinned', bool(on))
        self.ctl.settings.save()
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
        if visible:
            self.show()
        self.pin_btn.setText('已置頂' if on else '置頂')

    def _restore(self):
        g = self.ctl.settings.get('notes.geometry') or []
        from PySide6.QtCore import QRect
        if len(g) == 4 and any(s.availableGeometry().intersects(QRect(*g)) for s in QGuiApplication.screens()):
            self.resize(g[2], g[3])                # 位置用外框左上角：顯示前設定也不會被標題列往下推
            self.move(g[0], g[1])
        else:
            scr = QGuiApplication.primaryScreen().availableGeometry()
            w, h = theme.size(380), theme.size(520)
            self.setGeometry(scr.right() - w - 60, scr.top() + 80, w, h)
        self.pin_btn.blockSignals(True)
        on = bool(self.ctl.settings.get('notes.pinned', True))
        self.pin_btn.setChecked(on)
        self.pin_btn.blockSignals(False)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.pin_btn.setText('已置頂' if on else '置頂')

    def showEvent(self, e):
        super().showEvent(e)
        hwnd = winutil.hwnd_of(self)
        winutil.set_frame_colors(hwnd, border=theme.ACCENT, caption=theme.BG, text=theme.TEXT)

    def closeEvent(self, e):
        if self.editing:
            self._save_edit()
            self._set_editing(False)
            self.render()
        self.ctl.settings.set('notes.geometry', [self.x(), self.y(), self.width(), self.height()])
        self.ctl.settings.save()
        self.closed.emit()
        super().closeEvent(e)
