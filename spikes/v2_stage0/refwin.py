# -*- coding: utf-8 -*-
"""
驗證 2、6：參考小窗
- 無邊框、置頂、可拖曳移動、右下角拉動縮放；平常只有圖＋一行進度，滑鼠停留才浮出工具列
- 穿透模式：半透明且滑鼠點擊穿透到下方程式（只能用快捷鍵切回）
- 比對：按住快捷鍵時疊上 SAI2 畫布擷取（左右對半），放開回到參考圖
"""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizeGrip, QWidget

import winutil

INFO_H = 30


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    img = img.convert('RGBA')
    q = QImage(img.tobytes('raw', 'RGBA'), img.width, img.height, img.width * 4, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(q)


class RefWindow(QWidget):
    def __init__(self, ref: QPixmap, capture=None, width: int = 240):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.ref = ref
        self.capture = capture            # () -> PIL.Image | None
        self.compare_img: QPixmap | None = None
        self.click_through = False
        self.info = '2/4 大色塊 · 7:12'
        self._drag = None
        self.resize(width, int(width * ref.height() / ref.width()) + INFO_H)

        self.toolbar = QWidget(self)
        self.toolbar.setStyleSheet('QWidget{background:rgba(18,18,24,210);border-radius:8px}'
                                   'QPushButton{color:#eee;background:transparent;border:none;padding:4px 6px}'
                                   'QPushButton:hover{background:#3b2f5c;border-radius:6px}')
        lay = QHBoxLayout(self.toolbar)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)
        for text in ('翻轉', '灰階', '明度', '格線', '比對', '穿透'):
            b = QPushButton(text, self.toolbar)
            if text == '穿透':
                b.clicked.connect(lambda: self.set_click_through(True))
            lay.addWidget(b)
        self.toolbar.hide()
        self.grip = QSizeGrip(self)
        self.grip.resize(14, 14)

    # 版面
    def resizeEvent(self, _e):
        self.toolbar.setGeometry(6, 6, self.width() - 12, 30)
        self.grip.move(self.width() - 14, self.height() - 14)

    def image_rect(self) -> QRect:
        return QRect(0, 0, self.width(), self.height() - INFO_H)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#15151b'))
        r = self.image_rect()
        p.drawPixmap(r, self.ref)
        if self.compare_img is not None:
            half = QRect(r.width() // 2, 0, r.width() - r.width() // 2, r.height())
            src = self.compare_img.rect()
            p.drawPixmap(half, self.compare_img, QRect(src.width() // 2, 0, src.width() - src.width() // 2, src.height()))
            p.fillRect(QRect(r.width() // 2 - 1, 0, 2, r.height()), QColor('white'))
        p.setPen(QColor('#f2f1f6'))
        text = '參考｜我的畫布（放開回到參考圖）' if self.compare_img is not None else self.info
        p.drawText(QRect(10, r.height(), self.width() - 20, INFO_H), Qt.AlignVCenter | Qt.AlignLeft, text)

    # 停留時浮出工具列
    def enterEvent(self, _e):
        self.toolbar.show()

    def leaveEvent(self, _e):
        self.toolbar.hide()

    # 拖曳移動
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._drag = None

    # 穿透
    def set_click_through(self, on: bool, opacity: float = 0.5):
        self.click_through = on
        self.toolbar.hide()
        winutil.set_click_through(winutil.hwnd_of(self), on)
        self.setWindowOpacity(opacity if on else 1.0)

    def toggle_click_through(self):
        self.set_click_through(not self.click_through)

    # 比對（按住快捷鍵期間）
    def begin_compare(self, vk: int, poll_ms: int = 30) -> bool:
        img = self.capture() if self.capture else None
        if img is None:
            self.info = '找不到 SAI2 畫布'
            self.update()
            return False
        self.compare_img = pil_to_pixmap(img)
        self.update()
        self._vk = vk
        self._hold = QTimer(self, interval=poll_ms, timeout=self._poll_release)
        self._hold.start()
        return True

    def _poll_release(self):
        if not winutil.key_down(self._vk):
            self._hold.stop()
            self.end_compare()

    def end_compare(self):
        self.compare_img = None
        self.update()

    def heal_topmost(self):
        if self.isVisible():
            winutil.force_topmost(winutil.hwnd_of(self))

    def center_global(self) -> QPoint:
        return self.mapToGlobal(self.image_rect().center())
