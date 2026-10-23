# -*- coding: utf-8 -*-
"""無障礙（docs/UI_2.0_PLAN.md §14）：整個程式一次套用，不必逐一修改每個按鈕

- 按鈕只在按 Tab 時取得焦點：滑鼠點過不會留下焦點框，鍵盤操作時才看得到（QSS 的 :focus 框）。
  滑鼠按下按鈕時仍會讓輸入框失去焦點，輸入到一半的內容照常觸發 editingFinished 存檔
- 只有圖示的按鈕，用提示文字當作螢幕報讀的名稱
- 主視窗：Ctrl+Tab / Ctrl+Shift+Tab（或 Ctrl+PgDown / PgUp）切換頁面；側欄按上下鍵移動
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QApplication, QLineEdit

_installed: list = []


class _Polisher(QObject):
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Polish and isinstance(obj, QAbstractButton):
            fix_button(obj)
        elif t == QEvent.MouseButtonPress and isinstance(obj, QAbstractButton):
            fw = QApplication.focusWidget()
            if isinstance(fw, (QLineEdit, QAbstractSpinBox)) and fw is not obj:
                fw.clearFocus()
        return False


def fix_button(b: QAbstractButton):
    if b.focusPolicy() & Qt.ClickFocus:
        b.setFocusPolicy(Qt.TabFocus)
    if not b.accessibleName() and not b.text().strip() and b.toolTip():
        b.setAccessibleName(b.toolTip())


def install(qapp):
    """在建立任何視窗前呼叫一次"""
    if _installed:
        return
    f = _Polisher(qapp)
    qapp.installEventFilter(f)
    _installed.append(f)


def uninstall(qapp):
    while _installed:
        qapp.removeEventFilter(_installed.pop())
