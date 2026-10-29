# -*- coding: utf-8 -*-
"""
設計系統：色票與樣式表。數值與 docs/UI_2.0_PLAN.md §13 一致；元件在 ui2/widgets.py

apply(accent, mode) 依設定換主色與深 / 淺色，會更新本模組的色票常數與 QSS；
各元件在建立時讀取 theme.X，所以換主題後重新建立的畫面就會套用。
參考小窗與寵物旁的膠囊固定用深色（疊在畫布上比較不刺眼）。
"""

FONT = '"Microsoft JhengHei UI", "Microsoft JhengHei", "Segoe UI", sans-serif'

# 主色：(主色, 按鈕底色, 按鈕滑過, 淺色模式的文字主色)
ACCENTS = {
    'purple': ('紫', '#8b5cf6', '#7c3aed', '#6d28d9', '#6d28d9'),
    'blue': ('藍', '#3b82f6', '#2563eb', '#1d4ed8', '#1d4ed8'),
    'teal': ('青綠', '#14b8a6', '#0f766e', '#115e59', '#0f766e'),
    'pink': ('粉紅', '#ec4899', '#be185d', '#9d174d', '#be185d'),
    'orange': ('橘', '#f97316', '#c2410c', '#9a3412', '#c2410c'),
}
# 一般文字至少 4.5:1（WCAG AA）的組合：(文字, 底色)；tests/ui2/test_accessibility.py 逐一檢查每個主題
TEXT_PAIRS = [('TEXT', 'BG'), ('TEXT', 'CARD'), ('TEXT', 'SURFACE3'), ('TEXT', 'INPUT_BG'), ('TEXT', 'SELECT_BG'),
              ('MUTED', 'BG'), ('MUTED', 'CARD'), ('MUTED', 'SURFACE2'), ('MUTED', 'SURFACE3'), ('SUBTLE', 'CARD'),
              ('SUBTLE', 'SURFACE2'), ('ACCENT_TEXT', 'BG'), ('ACCENT_TEXT', 'CARD'), ('ACCENT_TEXT', 'ACCENT_SOFT'),
              ('#ffffff', 'ACCENT_BTN'), ('#ffffff', 'ACCENT_BTN_HOVER'), ('WARNING', 'CARD'), ('WARNING', 'WARN_SOFT'),
              ('SUCCESS', 'CARD'), ('SUCCESS', 'OK_SOFT'), ('DANGER', 'CARD'), ('NAV_TEXT', 'SIDEBAR'),
              ('NAV_SELECTED_TEXT', 'NAV_SELECTED')]
MODES = {'dark': '深色', 'light': '淺色', 'system': '跟隨 Windows'}

DARK = dict(
    BG='#0e0e12', SIDEBAR='#121218', SURFACE='#16161c', CARD='#17171e', SURFACE2='#1d1c24', SURFACE3='#24232c',
    BORDER='#26252f', DIVIDER='#22212a', TEXT='#f2f1f6', MUTED='#a3a1b3', SUBTLE='#8a889e',
    SUCCESS='#86efac', WARNING='#fbbf6a', DANGER='#fca5a5', OK_SOFT='#16291e', WARN_SOFT='#2c2215',
    INPUT_BG='#1b1a22', INPUT_BORDER='#33323e', HOVER='#2e2d38', TRACK='#2a2933', ICON='#e6e4ef',
    NAV_TEXT='#c9c7d6', STRONG_TEXT='#ede9fe', DISABLED='#6b6979', SCROLL='#3a3946', HEAT0='#1d1c24',
)
LIGHT = dict(
    BG='#f5f4f8', SIDEBAR='#eeecf3', SURFACE='#ffffff', CARD='#ffffff', SURFACE2='#f3f2f7', SURFACE3='#e9e7f0',
    BORDER='#e2e0ea', DIVIDER='#ebe9f1', TEXT='#1b1a22', MUTED='#5c5a6b', SUBTLE='#6b697c',
    SUCCESS='#15803d', WARNING='#b45309', DANGER='#b91c1c', OK_SOFT='#dcfce7', WARN_SOFT='#fef3c7',
    INPUT_BG='#ffffff', INPUT_BORDER='#d4d1de', HOVER='#e2e0ea', TRACK='#dcd9e5', ICON='#3b3946',
    NAV_TEXT='#3b3946', STRONG_TEXT='#1b1a22', DISABLED='#a4a2b2', SCROLL='#cdcad8', HEAT0='#ebe9f1',
)

IS_LIGHT = False
ACCENT_KEY = 'purple'
MOTION = True                 # False = 減少動態效果（開關不做滑動動畫）
SCALE = 1.0                   # 文字大小（設定 › 外觀）：字級與放文字的元件尺寸一起縮放
SCALES = [(0.75, '75%'), (0.9, '90%'), (1.0, '100%'), (1.1, '110%'), (1.25, '125%'), (1.5, '150%')]


def px(n: float) -> int:
    """依文字大小縮放的像素值：字級，以及要放得下文字的寬高（固定寬度的欄位、按鈕高度…）"""
    return int(round(n * SCALE))


def size(n: float) -> int:
    """放文字的固定寬高（欄位、按鈕、面板寬度）：只放大不縮小——字變小時元件維持原本大小，內距才不會不夠"""
    return int(round(n * max(1.0, SCALE)))


def scale_css(css: str) -> str:
    """把樣式裡的 font-size、min-height 依文字大小縮放（個別元件自己設定的樣式也用這個）"""
    import re
    if SCALE == 1.0:
        return css
    return re.sub(r'(font-size|min-height)(\s*:\s*)(\d+(?:\.\d+)?)px',
                  lambda m: f'{m.group(1)}{m.group(2)}{px(float(m.group(3)))}px', css)


def _blend(a: str, b: str, t: float) -> str:
    """a 往 b 混合 t（0～1）"""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(x + (y - x) * t):02x}' for x, y in zip(ca, cb))


def _luminance(c: str) -> float:
    ch = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    ch = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(a: str, b: str) -> float:
    """WCAG 對比值（1～21）；一般文字至少 4.5"""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def on_color(bg: str, dark: str = '#1b1a22') -> str:
    """放在 bg 上的文字用白色還是深色（取對比較高的）"""
    return '#ffffff' if contrast('#ffffff', bg) >= contrast(dark, bg) else dark


def system_is_light() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as k:
            return bool(winreg.QueryValueEx(k, 'AppsUseLightTheme')[0])
    except OSError:
        return False


def apply(accent: str = 'purple', mode: str = 'dark', scale: float | None = None) -> str:
    """更新色票、文字大小與 QSS，回傳 QSS"""
    g = globals()
    if scale is not None:
        g['SCALE'] = min(2.0, max(0.75, float(scale)))
    light = mode == 'light' or (mode == 'system' and system_is_light())
    pal = LIGHT if light else DARK
    g.update(pal)
    key = accent if accent in ACCENTS else 'purple'
    _name, acc, btn, btn_hover, light_text = ACCENTS[key]
    g['IS_LIGHT'], g['ACCENT_KEY'] = light, key
    g['ACCENT'], g['ACCENT_BTN'], g['ACCENT_BTN_HOVER'] = acc, btn, btn_hover
    g['ACCENT_TEXT'] = light_text if light else _blend(acc, '#ffffff', 0.45)
    g['ACCENT_SOFT'] = _blend(pal['CARD'], acc, 0.12 if light else 0.16)
    g['ACCENT_BORDER'] = _blend(pal['CARD'], acc, 0.35 if light else 0.45)
    g['SELECT_BG'] = _blend(pal['SURFACE2'], acc, 0.22 if light else 0.32)
    g['BAR'] = _blend(pal['CARD'], acc, 0.55 if light else 0.6)
    g['NAV_SELECTED'] = _blend(pal['SIDEBAR'], acc, 0.18 if light else 0.26)
    g['NAV_SELECTED_TEXT'] = _blend(light_text, '#000000', 0.2) if light else '#ffffff'   # 對比 ≥ 4.5
    g['PET_BODY'] = _blend(acc, '#2b2640', 0.18)       # 內建角色「墨墨」跟隨主色
    g['HEAT'] = [pal['HEAT0'], _blend(pal['HEAT0'], btn, 0.3), _blend(pal['HEAT0'], btn, 0.6), btn]   # 深一階：格內數字才看得清楚
    g['QSS'] = scale_css(build_qss())
    return g['QSS']


def build_qss() -> str:
    return f"""
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
QLabel[chip="ok"] {{ background: {OK_SOFT}; color: {SUCCESS}; border-radius: 10px; padding: 2px 10px; font-size: 11px; }}
QLabel[chip="warn"] {{ background: {WARN_SOFT}; color: {WARNING}; border-radius: 10px; padding: 2px 10px; font-size: 11px; }}

/* 卡片與分隔 */
QFrame[card="true"] {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame[divider="true"] {{ background: {DIVIDER}; border: none; margin: 0 18px; }}
QWidget[settingRow="true"] {{ background: transparent; }}

/* 按鈕 */
QPushButton {{ background: {SURFACE3}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px; min-height: 20px; }}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:disabled {{ color: {DISABLED}; background: {SURFACE2}; }}
QPushButton[kind="primary"], QPushButton[primary="true"] {{ background: {ACCENT_BTN}; border: none; color: white; font-weight: 600; }}
QPushButton[kind="primary"]:hover, QPushButton[primary="true"]:hover {{ background: {ACCENT_BTN_HOVER}; }}
QPushButton[kind="ghost"], QPushButton[flat="true"] {{ background: transparent; border: none; color: {NAV_TEXT}; }}
QPushButton[kind="ghost"]:hover, QPushButton[flat="true"]:hover {{ background: {SURFACE3}; }}
QPushButton[kind="link"] {{ background: transparent; border: none; color: {ACCENT_TEXT}; padding: 4px 6px; }}
QPushButton[kind="link"]:hover {{ color: {ACCENT}; }}
QPushButton[slot="true"], QToolButton[slot="true"] {{ background: {SURFACE2}; border: none; border-radius: 12px;
    padding: 6px 2px; font-size: 11px; }}
QPushButton[slot="true"]:hover, QToolButton[slot="true"]:hover {{ background: {HOVER}; }}
QPushButton[slot="true"]:disabled, QToolButton[slot="true"]:disabled {{ color: {DISABLED}; }}
QPushButton[nav="true"] {{ background: transparent; border: none; border-radius: 10px; padding: 0 14px; min-height: 40px;
    text-align: left; color: {NAV_TEXT}; font-size: 14px; }}
QPushButton[nav="true"]:hover {{ background: {SURFACE3}; }}
QPushButton[nav="true"]:checked {{ background: {NAV_SELECTED}; color: {NAV_SELECTED_TEXT}; font-weight: 600; }}
QPushButton[nav="true"]:disabled {{ color: {SUBTLE}; }}
QWidget[segmented="true"] {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 10px; }}
QPushButton[seg="true"] {{ background: transparent; border: none; border-radius: 8px; padding: 6px 14px; color: {MUTED}; }}
QPushButton[seg="true"]:checked {{ background: {SURFACE3}; color: {TEXT}; font-weight: 600; }}

/* 輸入 */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {{
    background: {INPUT_BG}; border: 1px solid {INPUT_BORDER}; border-radius: 10px; padding: 7px 10px; min-height: 20px; }}
QSpinBox, QDoubleSpinBox {{ padding: 5px 10px; min-height: 24px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 22px; border: none; background: transparent; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {TRACK}; border-radius: 6px; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE2}; border: 1px solid {BORDER}; selection-background-color: {SELECT_BG}; padding: 4px; }}
QCheckBox {{ spacing: 8px; }}
QSlider::groove:horizontal {{ height: 4px; background: {TRACK}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; border-radius: 8px; background: {'#ffffff' if not IS_LIGHT else ACCENT_BTN}; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SCROLL}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}
QMenu {{ background: {SURFACE2}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SELECT_BG}; }}
QMenu::item:disabled {{ color: {DISABLED}; }}

/* 鍵盤焦點（按鈕只在按 Tab 時取得焦點，見 ui2/a11y.py） */
QPushButton:focus, QToolButton:focus {{ border: 2px solid {ACCENT_TEXT}; }}
QSlider:focus {{ border: 1px dashed {ACCENT_TEXT}; border-radius: 4px; }}
"""


QSS = apply()
