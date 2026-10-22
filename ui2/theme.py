# -*- coding: utf-8 -*-
"""設計系統：色票與樣式表（深色）。數值與 docs/UI_2.0_PLAN.md §13 一致；元件在 ui2/widgets.py"""

BG = '#0e0e12'
SIDEBAR = '#121218'
SURFACE = '#16161c'
CARD = '#17171e'
SURFACE2 = '#1d1c24'
SURFACE3 = '#24232c'
BORDER = '#26252f'
DIVIDER = '#22212a'
TEXT = '#f2f1f6'
MUTED = '#a3a1b3'
SUBTLE = '#77758a'
ACCENT = '#8b5cf6'
ACCENT_BTN = '#7c3aed'          # 白字在上面需要 4.5:1 對比，按鈕底色用較深的紫
ACCENT_TEXT = '#c4b5fd'
ACCENT_SOFT = '#231d36'
SUCCESS = '#86efac'
WARNING = '#fbbf6a'
DANGER = '#fca5a5'
FONT = '"Microsoft JhengHei UI", "Microsoft JhengHei", "Segoe UI", sans-serif'

QSS = f"""
* {{ font-family: {FONT}; font-size: 13px; color: {TEXT}; }}
QWidget#window, QWidget#page, QStackedWidget {{ background: {BG}; }}
QScrollArea > QWidget > QWidget#page {{ background: {BG}; }}
QWidget#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {DIVIDER}; }}

/* 文字層級 */
QLabel[role="title"] {{ font-size: 26px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 15px; font-weight: 700; }}
QLabel[role="section"] {{ color: {MUTED}; font-size: 12px; font-weight: 700; letter-spacing: 1px; padding-left: 2px; }}
QLabel[role="body"] {{ font-size: 14px; }}
QLabel[role="muted"] {{ color: {MUTED}; font-size: 13px; }}
QLabel[role="caption"] {{ color: {MUTED}; font-size: 12px; }}
QLabel[role="stat"] {{ font-size: 24px; font-weight: 700; }}
QLabel[role="warn"] {{ color: {WARNING}; font-size: 12px; }}
QLabel[role="ok"] {{ color: {SUCCESS}; font-size: 12px; }}
QLabel[role="accent"] {{ color: {ACCENT_TEXT}; }}
QLabel[muted="true"] {{ color: {MUTED}; font-size: 12px; }}
QLabel[h1="true"] {{ font-size: 20px; font-weight: 700; }}
QLabel[h2="true"] {{ font-size: 15px; font-weight: 700; }}
QLabel[section="true"] {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}
QLabel[warn="true"] {{ color: {WARNING}; font-size: 12px; }}
QLabel[ok="true"] {{ color: {SUCCESS}; font-size: 12px; }}
QLabel[chip="neutral"] {{ background: {SURFACE3}; color: {MUTED}; border-radius: 10px; padding: 2px 10px; font-size: 11px; }}
QLabel[chip="accent"] {{ background: {ACCENT_SOFT}; color: {ACCENT_TEXT}; border-radius: 10px; padding: 2px 10px; font-size: 11px; }}
QLabel[chip="ok"] {{ background: #16291e; color: {SUCCESS}; border-radius: 10px; padding: 2px 10px; font-size: 11px; }}
QLabel[chip="warn"] {{ background: #2c2215; color: {WARNING}; border-radius: 10px; padding: 2px 10px; font-size: 11px; }}

/* 卡片與分隔 */
QFrame[card="true"] {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame[divider="true"] {{ background: {DIVIDER}; border: none; margin: 0 18px; }}
QWidget[settingRow="true"] {{ background: transparent; }}

/* 按鈕 */
QPushButton {{ background: {SURFACE3}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px; min-height: 20px; }}
QPushButton:hover {{ background: #2e2d38; }}
QPushButton:disabled {{ color: #6b6979; background: {SURFACE2}; }}
QPushButton[kind="primary"], QPushButton[primary="true"] {{ background: {ACCENT_BTN}; border: none; color: white; font-weight: 600; }}
QPushButton[kind="primary"]:hover, QPushButton[primary="true"]:hover {{ background: #6d28d9; }}
QPushButton[kind="ghost"], QPushButton[flat="true"] {{ background: transparent; border: none; color: #d6d4e2; }}
QPushButton[kind="ghost"]:hover, QPushButton[flat="true"]:hover {{ background: {SURFACE3}; }}
QPushButton[kind="link"] {{ background: transparent; border: none; color: {ACCENT_TEXT}; padding: 4px 6px; }}
QPushButton[kind="link"]:hover {{ color: #ddd6fe; }}
QPushButton[slot="true"], QToolButton[slot="true"] {{ background: {SURFACE2}; border: none; border-radius: 12px;
    padding: 6px 2px; font-size: 11px; }}
QPushButton[slot="true"]:hover, QToolButton[slot="true"]:hover {{ background: #2a2933; }}
QPushButton[slot="true"]:disabled, QToolButton[slot="true"]:disabled {{ color: #6b6979; }}
QPushButton[nav="true"] {{ background: transparent; border: none; border-radius: 10px; padding: 0 14px; min-height: 40px;
    text-align: left; color: #c9c7d6; font-size: 14px; }}
QPushButton[nav="true"]:hover {{ background: #1c1b24; }}
QPushButton[nav="true"]:checked {{ background: {ACCENT_SOFT}; color: #ede9fe; font-weight: 600; }}
QPushButton[nav="true"]:disabled {{ color: {SUBTLE}; }}
QWidget[segmented="true"] {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 10px; }}
QPushButton[seg="true"] {{ background: transparent; border: none; border-radius: 8px; padding: 6px 14px; color: {MUTED}; }}
QPushButton[seg="true"]:checked {{ background: {SURFACE3}; color: {TEXT}; font-weight: 600; }}

/* 輸入 */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {{
    background: #1b1a22; border: 1px solid #33323e; border-radius: 10px; padding: 7px 10px; min-height: 20px; }}
QSpinBox, QDoubleSpinBox {{ padding: 5px 10px; min-height: 24px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 22px; border: none; background: transparent; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #2a2933; border-radius: 6px; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE2}; border: 1px solid {BORDER}; selection-background-color: #3b2f5c; padding: 4px; }}
QCheckBox {{ spacing: 8px; }}
QSlider::groove:horizontal {{ height: 4px; background: #3a3946; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; border-radius: 8px; background: white; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QListWidget#nav {{ background: {SURFACE}; border: none; padding: 8px; outline: 0; }}
QListWidget#nav::item {{ height: 40px; padding-left: 12px; border-radius: 8px; color: #c9c7d6; }}
QListWidget#nav::item:selected {{ background: #2a2440; color: #ede9fe; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3a3946; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}
QMenu {{ background: {SURFACE2}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: #3b2f5c; }}
QMenu::item:disabled {{ color: #6b6979; }}
"""
