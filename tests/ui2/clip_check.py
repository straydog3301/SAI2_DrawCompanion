# -*- coding: utf-8 -*-
"""找出被截斷的文字（文字大小、多語系用）：元件的寬度比放下文字所需的寬度窄，或換行的文字高度不夠。
給 test_text_scale.py 與手動檢查共用"""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QScrollArea, QWidget

SLACK = 2


def _visible_in_viewport(w: QWidget) -> bool:
    """在捲動區裡被捲到看不到的地方也算（只看有沒有被擠壓，不看位置）"""
    return w.isVisible() and w.width() > 0 and w.height() > 0


def clipped(root: QWidget) -> list[str]:
    out = []
    for w in root.findChildren(QWidget):
        if not _visible_in_viewport(w) or isinstance(w, QScrollArea):
            continue
        name = type(w).__name__
        if isinstance(w, QLabel):
            text = w.text()
            if not text or w.pixmap() is not None and not w.pixmap().isNull():
                continue
            if w.wordWrap():
                need = w.heightForWidth(w.width())
                if need > w.height() + SLACK:
                    out.append(f'{name}「{text[:24]}」高度 {w.height()} < {need}')
            elif w.sizeHint().width() > w.width() + SLACK:
                out.append(f'{name}「{text[:24]}」寬度 {w.width()} < {w.sizeHint().width()}')
        elif isinstance(w, QAbstractButton):
            text = w.text()
            if '…' in text:                                         # 已經刻意縮短（例如作品縮圖下的名稱）
                continue
            if text and w.sizeHint().width() > w.width() + SLACK:
                out.append(f'{name}「{text[:24]}」寬度 {w.width()} < {w.sizeHint().width()}')
            elif text and w.sizeHint().height() > w.height() + SLACK:
                out.append(f'{name}「{text[:24]}」高度 {w.height()} < {w.sizeHint().height()}')
        elif isinstance(w, QComboBox):
            fm = w.fontMetrics()
            need = fm.horizontalAdvance(w.currentText()) + 40          # 左右內距＋下拉箭頭
            if w.currentText() and need > w.width() + SLACK:
                out.append(f'{name}「{w.currentText()[:24]}」寬度 {w.width()} < {need}')
        elif isinstance(w, QLineEdit) and w.text():
            pass
    return out
