"""
main.py - SAI2 繪圖時間記錄器 主程式 / UI
"""

from __future__ import annotations

import os
import sys
import subprocess
import json
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk

from tracker import DrawTracker, fmt_seconds
from timelapse import TimelapseRecorder, find_ffmpeg, file_key_to_subdir
from i18n import _tr, set_language, get_current_language, get_available_languages

# ─── 啟動參數 ─────────────────────────────────────────────────────────────
# --auto-close：由 watcher.pyw 傳入，SAI2 關閉時自動儲存並關閉計時器
AUTO_CLOSE = '--auto-close' in sys.argv


# ─── DPI 感知 ─────────────────────────────────────────────────────────────
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# ─── 全域例外攔截 ─────────────────────────────────────────────────────────
def _excepthook(et, ev, etb):
    try:
        messagebox.showerror(_tr('err.unexpected'),
                             ''.join(traceback.format_exception(et, ev, etb))[:900])
    except Exception:
        pass
sys.excepthook = _excepthook

# ─── 螢幕解析度自適應 ─────────────────────────────────────────────────────
def _get_scaled_size(screen_width: int, base_width: int = 540, base_height: int = 820) -> tuple[int, int]:
    """
    根據螢幕寬度計算合適的視窗大小。
    在 2560x1440 上使用 540x820，在 3840x2160 上適當放大。
    """
    # 基準解析度 (2560x1440)
    base_screen_width = 2560
    
    # 計算縮放比例，但限制在合理範圍內
    scale_factor = screen_width / base_screen_width
    
    # 針對不同解析度進行調整
    if screen_width >= 3840:  # 4K
        width = int(base_width * 1.2)  # 放大20%
        height = int(base_height * 1.15)  # 放大15%
    elif screen_width >= 1920:  # Full HD
        width = int(base_width * 1.1)  # 放大10%
        height = int(base_height * 1.05)  # 放大5%
    else:  # 較低解析度
        width = base_width
        height = base_height
    
    # 確保視窗不會超出螢幕範圍
    max_width = int(screen_width * 0.7)
    max_height = int(screen_width * 0.8)  # 基於寬度計算最大高度
    
    width = min(width, max_width)
    height = min(height, max_height)
    
    return width, height

def _get_scaled_dialog_size(screen_width: int, base_width: int) -> int:
    """
    計算對話框的適當大小。
    """
    if screen_width >= 3840:  # 4K
        return int(base_width * 1.3)
    elif screen_width >= 1920:  # Full HD
        return int(base_width * 1.15)
    else:
        return base_width

# ─── 色彩 / 字型 ──────────────────────────────────────────────────────────
BG     = '#111111'
CARD   = '#1e1e1e'
CARD2  = '#282828'
ACCENT = '#7c3aed'
ACCH   = '#6d28d9'
TEXT   = '#f0f0f0'
TEXTD  = '#717171'
GREEN  = '#22c55e'
YELLOW = '#f59e0b'
RED    = '#ef4444'
BORDER = '#2f2f2f'

FT     = ('Microsoft JhengHei', 12, 'bold')
FH     = ('Microsoft JhengHei', 10, 'bold')
FB     = ('Microsoft JhengHei', 9)
FS     = ('Microsoft JhengHei', 8)
FM     = ('Microsoft JhengHei', 10)
FBIG   = ('Microsoft JhengHei', 20, 'bold')
FEFF   = ('Microsoft JhengHei', 24, 'bold')

# 取得程式運行所在的實際目錄（相容 PyInstaller 打包）
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    # 如果執行檔位於 dist 目錄中，則將套件目錄指回其父目錄
    if os.path.basename(_exe_dir).lower() == 'dist':
        _APP_DIR = os.path.dirname(_exe_dir)
    else:
        _APP_DIR = _exe_dir
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

# 預設資料路徑：套件目錄底下的 sai2_draw_time.json
_DEFAULT_DATA = os.path.join(_APP_DIR, 'sai2_draw_time.json')

# 設定檔路徑
_SETTINGS_PATH = os.path.join(_APP_DIR, 'sai2_timer_settings.json')


def _eff_color(pct: int) -> str:
    if pct >= 60:
        return GREEN
    if pct >= 30:
        return YELLOW
    return RED


THEME_PRESETS = {
    '羅蘭紫': '#7c3aed',
    '天空藍': '#2563eb',
    '海洋青': '#0891b2',
    '極光綠': '#0d9488',
    '森林綠': '#16a34a',
    '萊姆黃': '#84cc16',
    '向日葵': '#eab308',
    '琥珀金': '#f59e0b',
    '活力橙': '#ea580c',
    '火焰紅': '#dc2626',
    '霓虹粉': '#db2777',
    '石板灰': '#475569',
}


def _get_hover_color(hex_str: str) -> str:
    try:
        hex_str = hex_str.lstrip('#')
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
        r = max(0, int(r * 0.85))
        g = max(0, int(g * 0.85))
        b = max(0, int(b * 0.85))
        return f'#{r:02x}{g:02x}{b:02x}'
    except Exception:
        return '#6d28d9'


def _load_theme_colors(settings: dict):
    global BG, CARD, CARD2, TEXT, TEXTD, BORDER, ACCENT, ACCH
    
    # 模式
    mode = settings.get('theme_mode', '深色模式')
    if mode == '亮色模式':
        BG     = '#f3f4f6'
        CARD   = '#ffffff'
        CARD2  = '#f9fafb'
        TEXT   = '#111827'
        TEXTD  = '#6b7280'
        BORDER = '#e5e7eb'
    else:
        BG     = '#111111'
        CARD   = '#1e1e1e'
        CARD2  = '#282828'
        TEXT   = '#f0f0f0'
        TEXTD  = '#717171'
        BORDER = '#2f2f2f'
        
    # 主色調
    preset = settings.get('theme_accent_preset', '羅蘭紫')
    if preset == '自訂':
        custom_color = settings.get('theme_accent_custom', '#7c3aed')
        ACCENT = custom_color
        ACCH   = _get_hover_color(custom_color)
    else:
        accent_color = THEME_PRESETS.get(preset, '#7c3aed')
        ACCENT = accent_color
        ACCH   = _get_hover_color(accent_color)


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        d = {}
        
    # Map old values for backward compatibility
    mode_map = {'深色模式': 'dark', '亮色模式': 'light'}
    if d.get('theme_mode') in mode_map:
        d['theme_mode'] = mode_map[d['theme_mode']]

    target_map = {
        '僅錄製畫布': 'canvas',
        '錄製 SAI 視窗': 'window',
        '整個螢幕': 'screen'
    }
    if d.get('timelapse_target_str') in target_map:
        d['timelapse_target_str'] = target_map[d['timelapse_target_str']]

    defaults = {
        'idle_timeout': 10.0,
        'always_on_top': False,
        'timelapse_enabled': False,
        'timelapse_multiplier_str': '5x (167ms)',
        'timelapse_target_str': 'canvas',
        'timelapse_fps': 30,
        'timelapse_quality': 'standard',
        'language': 'zh_tw',
        'theme_mode': 'dark',
        'theme_accent_preset': '羅蘭紫',
        'theme_accent_custom': '#7c3aed',
        'hotkey_record_key': 'F10',
        'hotkey_record_ctrl': False,
        'hotkey_record_alt': False,
        'hotkey_record_shift': False
    }
    for k, v in defaults.items():
        if k not in d:
            d[k] = v
    return d


def _save_settings(d: dict):
    try:
        with open(_SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─── ttk 樣式 ─────────────────────────────────────────────────────────────
def _setup_styles():
    s = ttk.Style()
    s.theme_use('clam')
    s.configure('TCombobox', fieldbackground=CARD2, background=CARD2,
                 foreground=TEXT, selectbackground=ACCENT,
                 selectforeground='white', borderwidth=0,
                 arrowcolor=TEXT, insertcolor=TEXT)
    s.map('TCombobox',
          fieldbackground=[('readonly', CARD2), ('disabled', CARD)],
          foreground=[('disabled', TEXTD)],
          arrowcolor=[('disabled', TEXTD)])
    # Treeview
    s.configure('Treeview', background=CARD2, foreground=TEXT,
                 fieldbackground=CARD2, rowheight=24, borderwidth=0,
                 font=FS, indent=14)
    s.configure('Treeview.Heading', background=CARD, foreground=TEXTD,
                 font=FS, borderwidth=0, relief='flat')
    s.map('Treeview',
          background=[('selected', ACCENT)],
          foreground=[('selected', 'white')])
    s.map('Treeview.Heading', background=[('active', CARD2)])
    # 設定樹狀列管理小三角展開符號的色彩
    s.configure('Treeview', indent=14)
    try:
        s.element_create('custom.Treeitem.indicator', 'from', 'default')
    except Exception:
        pass
    s.layout('Treeview.Item',
             [('Treeitem.padding',
               {'sticky': 'nswe',
                'children': [('custom.Treeitem.indicator', {'side': 'left', 'sticky': ''}),
                              ('Treeitem.image', {'side': 'left', 'sticky': ''}),
                              ('Treeitem.focus',
                               {'side': 'left', 'sticky': '',
                                'children': [('Treeitem.text', {'side': 'left', 'sticky': ''})]})]
                })])
    s.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor=CARD2, bordercolor=BORDER, borderwidth=0)
    
    # ── Scrollbar 樣式 ──
    s.configure('TScrollbar', gripcount=0, background=CARD2, troughcolor=BG, bordercolor=BORDER,
                arrowcolor=TEXTD, lightcolor=CARD2, darkcolor=CARD2, borderwidth=0)
    s.map('TScrollbar',
          background=[('active', ACCENT), ('disabled', CARD)],
          arrowcolor=[('active', 'white')])


def _setup_combobox_colors(root: tk.Tk):
    """設定 Combobox 下拉清單（popup）的顏色，並即時更新已存在的下拉選單 Listbox。"""
    root.option_add('*TCombobox*Listbox.background', CARD2)
    root.option_add('*TCombobox*Listbox.foreground', TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground', ACCENT)
    root.option_add('*TCombobox*Listbox.selectForeground', 'white')
    root.option_add('*TCombobox*Listbox.borderWidth', '0')
    root.option_add('*TCombobox*Listbox.relief', 'flat')

    # 即時更新所有已建立的 Listbox (包含已生成的下拉選單)
    def _update_listboxes(w):
        if isinstance(w, tk.Listbox):
            try:
                w.configure(bg=CARD2, fg=TEXT, selectbackground=ACCENT, selectforeground='white',
                            borderwidth=0, relief='flat')
            except Exception:
                pass
        try:
            for child in w.winfo_children():
                _update_listboxes(child)
        except Exception:
            pass

    try:
        _update_listboxes(root)
    except Exception:
        pass


def _apply_titlebar_theme(root: tk.Tk | tk.Toplevel):
    """透過 Windows DWM API 套用標題列深色/亮色模式及主題色，並強制更新視窗外框。"""
    try:
        import ctypes
        import ctypes.wintypes
        # 等待視窗實際出現後才能取得 HWND
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        if hwnd == 0:
            hwnd = root.winfo_id()

        is_dark = (BG == '#111111')  # 深色模式旗標
        dark_val = ctypes.c_int(1 if is_dark else 0)

        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20（Win10 1903+），舊版用 19
        for attr_id in (20, 19):
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr_id,
                    ctypes.byref(dark_val), ctypes.sizeof(dark_val)
                )
            except Exception:
                pass

        # DWMWA_CAPTION_COLOR = 35（Windows 11 only）
        # 用 ACCENT 色作為標題列背景色
        h = ACCENT.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        # Windows COLORREF = 0x00BBGGRR（小端序 RGB）
        color_ref = ctypes.c_int(r | (g << 8) | (b << 16))
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 35,
                ctypes.byref(color_ref), ctypes.sizeof(color_ref)
            )
        except Exception:
            pass

        # DWMWA_TEXT_COLOR = 36（Windows 11 only）
        # 根據 ACCENT 亮度自動選擇標題文字顏色 (深色背景用白字，亮色背景用 TEXT 色碼)
        is_accent_dark = _is_dark_color(ACCENT)
        text_hex = 'ffffff' if is_accent_dark else TEXT.lstrip('#')
        tr, tg, tb = int(text_hex[0:2], 16), int(text_hex[2:4], 16), int(text_hex[4:6], 16)
        text_color_ref = ctypes.c_int(tr | (tg << 8) | (tb << 16))
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 36,
                ctypes.byref(text_color_ref), ctypes.sizeof(text_color_ref)
            )
        except Exception:
            pass

        # 強制 Window Frame 重繪以立即使主題色生效 (SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        try:
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
        except Exception:
            pass
    except Exception:
        pass


# ─── 按鈕 Helper ──────────────────────────────────────────────────────────
def _is_dark_color(hex_str: str) -> bool:
    """判斷十六進位色碼是否為深色（亮度 < 0.5），用於決定按鈕文字顏色。"""
    try:
        h = hex_str.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance < 0.5
    except Exception:
        return True


def _btn(parent, text, bg, hbg, cmd, font=FB, width=None, **kw) -> tk.Button:
    kw.setdefault('padx', 8)
    kw.setdefault('pady', 5)
    # 根據背景亮度自動選擇文字顏色，避免亮色模式下白字不可見（使用 '#111827' 確保高對比）
    fg_color = 'white' if _is_dark_color(bg) else '#111827'
    hfg_color = 'white' if _is_dark_color(hbg) else '#111827'
    b = tk.Button(parent, text=text, font=font,
                  bg=bg, fg=fg_color,
                  activebackground=hbg, activeforeground=hfg_color,
                  relief='flat', cursor='hand2', command=cmd, **kw)
    if width:
        b.config(width=width)
    b.bind('<Enter>', lambda _: b['state'] != 'disabled' and b.config(bg=hbg, fg=hfg_color))
    b.bind('<Leave>', lambda _: b['state'] != 'disabled' and b.config(bg=bg, fg=fg_color))
    b._bg, b._hbg = bg, hbg
    return b


def _card(parent, **kw) -> tk.Frame:
    kw.setdefault('padx', 12)
    kw.setdefault('pady', 10)
    return tk.Frame(parent, bg=CARD, highlightthickness=1,
                    highlightbackground=BORDER, **kw)


# ─── 主應用程式 ───────────────────────────────────────────────────────────
VERSION = '1.2.0'


class App:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{_tr('ui.title')} v{VERSION}")

        # 設定與配色
        self._settings = _load_settings()
        set_language(self._settings.get('language', 'zh_tw'))
        _load_theme_colors(self._settings)

        self.root.configure(bg=BG)
        
        # 取得螢幕解析度並計算合適的視窗大小
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width, window_height = _get_scaled_size(screen_width)
        
        # 設定視窗大小並允許調整寬度
        self.root.geometry(f'{window_width}x{window_height}')
        self.root.resizable(True, True)  # 允許調整寬度和高度
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        
        # 儲存基礎大小供精簡模式使用
        self._base_width = window_width
        self._base_height = window_height

        _setup_styles()

        data_path = self._settings.get('data_path', _DEFAULT_DATA)
        idle_to   = float(self._settings.get('idle_timeout', 10.0))

        self.tracker = DrawTracker(data_path=data_path, idle_timeout=idle_to)

        self._blink    = False
        self._on_top   = tk.BooleanVar(value=self._settings.get('always_on_top', False))
        self._selected_file: str | None = None
        self._selected_group: str | None = None

        # 自訂分組設定：{file_key: 自訂分組名稱}
        self._custom_groups: dict[str, str] = self._settings.get('custom_groups', {})
        # 自訂群組圖示設定：{group_name: 自訂emoji}
        self._group_emojis: dict[str, str] = self._settings.get('group_emojis', {})
        # 分組展開狀態：{group_name: bool}，預設全展開
        self._group_open: dict[str, bool] = {}

        # Hover 縮圖預覽狀態
        self._hover_item: str | None = None
        self._thumb_popup: tk.Toplevel | None = None
        self._thumb_img_ref = None   # 避免 PhotoImage 被 GC

        # 隨 SAI2 關閉模式
        self._auto_close       = AUTO_CLOSE
        self._sai2_was_alive   = False    # 上一次輪詢時 SAI2 是否在線
        self._closing          = False    # 是否已進入關閉流程

        self._is_mini = False

        # 縮時錄影初始化
        tl_out = self._settings.get('timelapse_output_dir', os.path.join(_APP_DIR, 'videos'))
        tl_fps = int(self._settings.get('timelapse_fps', 30))
        self.timelapse_recorder = TimelapseRecorder(output_dir=tl_out, fps=tl_fps)
        self.timelapse_recorder.enabled = self._settings.get('timelapse_enabled', False)
        
        mult_str = self._settings.get('timelapse_multiplier_str', '5x (167ms)')
        self.timelapse_recorder.multiplier = self._parse_multiplier(mult_str)
        
        target_str = self._settings.get('timelapse_target_str', 'canvas')
        self.timelapse_recorder.target_mode = self._parse_target(target_str)
        self.timelapse_recorder.quality_preset = self._settings.get('timelapse_quality', 'standard')
        
        self.timelapse_recorder.idle_timeout = idle_to
        self.timelapse_recorder.on_frame_captured = self._cb_tl_frame
        self.timelapse_recorder.on_status_msg = self._cb_tl_status
        self.timelapse_recorder.on_export_progress = self._cb_export_progress

        self._build_ui()
        self._apply_topmost()
        self._setup_system_hotkey()

        # Combobox 下拉清單主題 & 標題列主題
        _setup_combobox_colors(self.root)
        self.root.after(200, lambda: _apply_titlebar_theme(self.root))

        self.tracker.start()
        self.timelapse_recorder.start()
        self._poll()

    # ════════════════════════════════════════════════════════════════════════
    # UI 建構
    # ════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        # ── 建立主容器 ──────────────────────────────────────────────────
        self.main_container = tk.Frame(self.root, bg=BG)
        self.main_container.pack(fill='both', expand=True)

        # ── 標題列 ──────────────────────────────────────────────────────
        hdr = tk.Frame(self.main_container, bg=ACCENT, pady=13)
        hdr.pack(fill='x')

        # 根據 ACCENT 亮度決定標頭元件文字與按鈕顏色，避免在亮色主題下看不清
        is_accent_dark = _is_dark_color(ACCENT)
        hdr_title_fg = 'white' if is_accent_dark else '#111827'
        hdr_sub_fg   = '#c4b5fd' if is_accent_dark else '#374151'

        left_hdr = tk.Frame(hdr, bg=ACCENT)
        left_hdr.pack(side='left', padx=14)
        tk.Label(left_hdr, text=f"{_tr('ui.hdr.title')} v{VERSION}", font=FT,
                 fg=hdr_title_fg, bg=ACCENT).pack(anchor='w')
        tk.Label(left_hdr, text=_tr('ui.hdr.subtitle'), font=FS,
                 fg=hdr_sub_fg, bg=ACCENT).pack(anchor='w')

        # 永遠置頂按鈕
        right_hdr = tk.Frame(hdr, bg=ACCENT)
        right_hdr.pack(side='right', padx=14)
        self._top_btn = tk.Checkbutton(
            right_hdr, text=_tr('ui.hdr.topmost'), variable=self._on_top,
            font=FS, fg=hdr_title_fg, bg=ACCENT,
            activebackground=ACCENT, activeforeground=hdr_title_fg,
            selectcolor=CARD if is_accent_dark else 'white', cursor='hand2',
            command=self._apply_topmost)
        self._top_btn.pack(side='left', padx=(0, 6))
        # 精簡模式切換按鈕
        self._mini_btn = _btn(right_hdr, _tr('ui.hdr.mini'), ACCENT, ACCH, self.toggle_mini_mode, font=FS)
        self._mini_btn.pack(side='left')

        # ── 頁籤選單 ──────────────────────────────────────────────────────
        self.tab_frame = tk.Frame(self.main_container, bg=BG, bd=0)
        self.tab_frame.pack(fill='x', pady=(6, 2))
        
        # 🕒 繪圖計時 頁籤
        self.tab_tracker_btn = tk.Frame(self.tab_frame, bg=BG, cursor='hand2')
        self.tab_tracker_btn.pack(side='left', expand=True, fill='x')
        self.tab_tracker_lbl = tk.Label(self.tab_tracker_btn, text=_tr('ui.tab.tracker'), font=FT, fg=TEXT, bg=BG)
        self.tab_tracker_lbl.pack(pady=(6, 4))
        self.tab_tracker_indicator = tk.Frame(self.tab_tracker_btn, height=3, bg=ACCENT)
        self.tab_tracker_indicator.pack(fill='x', side='bottom')
        
        # 📊 統計圖表 頁籤
        self.tab_stats_btn = tk.Frame(self.tab_frame, bg=BG, cursor='hand2')
        self.tab_stats_btn.pack(side='left', expand=True, fill='x')
        self.tab_stats_lbl = tk.Label(self.tab_stats_btn, text=_tr('ui.tab.stats'), font=FT, fg=TEXTD, bg=BG)
        self.tab_stats_lbl.pack(pady=(6, 4))
        self.tab_stats_indicator = tk.Frame(self.tab_stats_btn, height=3, bg=BG)
        self.tab_stats_indicator.pack(fill='x', side='bottom')
        
        self.tab_tracker_btn.bind('<Button-1>', lambda _: self._switch_tab('tracker'))
        self.tab_tracker_lbl.bind('<Button-1>', lambda _: self._switch_tab('tracker'))
        self.tab_stats_btn.bind('<Button-1>', lambda _: self._switch_tab('stats'))
        self.tab_stats_lbl.bind('<Button-1>', lambda _: self._switch_tab('stats'))
        
        def _on_tab_enter(lbl, indicator):
            if indicator['bg'] != ACCENT:
                lbl.config(fg=TEXT)
        def _on_tab_leave(lbl, indicator):
            if indicator['bg'] != ACCENT:
                lbl.config(fg=TEXTD)
                
        self.tab_tracker_btn.bind('<Enter>', lambda _: _on_tab_enter(self.tab_tracker_lbl, self.tab_tracker_indicator))
        self.tab_tracker_btn.bind('<Leave>', lambda _: _on_tab_leave(self.tab_tracker_lbl, self.tab_tracker_indicator))
        self.tab_stats_btn.bind('<Enter>', lambda _: _on_tab_enter(self.tab_stats_lbl, self.tab_stats_indicator))
        self.tab_stats_btn.bind('<Leave>', lambda _: _on_tab_leave(self.tab_stats_lbl, self.tab_stats_indicator))
        
        # ── 內容展示區 ──────────────────────────────────────────────────
        self.content_frame = tk.Frame(self.main_container, bg=BG)
        self.content_frame.pack(fill='both', expand=True)
        
        # 1. 計時器主視圖
        self.tracker_view = tk.Frame(self.content_frame, bg=BG)
        self.tracker_view.pack(fill='both', expand=True)
        
        # 2. 統計圖表視圖
        self.stats_view = tk.Frame(self.content_frame, bg=BG)
        self._build_stats_view()
        
        body = tk.Frame(self.tracker_view, bg=BG)
        body.pack(fill='both', expand=True, padx=14, pady=10)

        # ── 卡片 1：SAI2 狀態 + 目前檔案 ────────────────────────────────
        c1 = _card(body)
        c1.pack(fill='x', pady=(0, 8))

        # 狀態列
        row_status = tk.Frame(c1, bg=CARD)
        row_status.pack(fill='x')
        tk.Label(row_status, text=_tr('ui.tracker.sai_status'), font=FH, fg=TEXT, bg=CARD
                 ).pack(side='left')
        self.dot = tk.Label(row_status, text='●', font=FB, fg=TEXTD, bg=CARD)
        self.dot.pack(side='right')

        # 目前檔案
        self.var_cur_file = tk.StringVar(value=_tr('ui.tracker.not_detected'))
        self.lbl_cur_file = tk.Label(c1, textvariable=self.var_cur_file,
                                      font=FB, fg=TEXT, bg=CARD,
                                      wraplength=490, justify='left')
        self.lbl_cur_file.pack(fill='x', pady=(4, 0))

        # 動筆指示燈
        self.var_draw_ind = tk.StringVar(value='')
        tk.Label(c1, textvariable=self.var_draw_ind,
                 font=FS, fg=GREEN, bg=CARD).pack(anchor='w', pady=(2, 0))

        # ── 卡片 2：目前工作階段統計 ─────────────────────────────────────
        c2 = _card(body)
        c2.pack(fill='x', pady=(0, 8))
        tk.Label(c2, text=_tr('ui.tracker.current_session'), font=FH, fg=TEXT, bg=CARD
                 ).pack(anchor='w', pady=(0, 6))

        metrics = tk.Frame(c2, bg=CARD)
        metrics.pack(fill='x')

        # 開啟時間
        b_open = tk.Frame(metrics, bg=CARD2, padx=14, pady=10)
        b_open.pack(side='left', expand=True, fill='both', padx=(0, 4))
        tk.Label(b_open, text=_tr('ui.tracker.open_time'), font=FS, fg=TEXTD, bg=CARD2).pack()
        self.var_open = tk.StringVar(value='--:--')
        tk.Label(b_open, textvariable=self.var_open, font=FBIG,
                 fg=TEXT, bg=CARD2).pack()

        # 動筆時間
        b_draw = tk.Frame(metrics, bg=CARD2, padx=14, pady=10)
        b_draw.pack(side='left', expand=True, fill='both', padx=(0, 4))
        tk.Label(b_draw, text=_tr('ui.tracker.draw_time'), font=FS, fg=TEXTD, bg=CARD2).pack()
        self.var_draw = tk.StringVar(value='--:--')
        tk.Label(b_draw, textvariable=self.var_draw, font=FBIG,
                 fg=ACCENT, bg=CARD2).pack()

        # 效率
        b_eff = tk.Frame(metrics, bg=CARD2, padx=14, pady=10)
        b_eff.pack(side='left', expand=True, fill='both')
        tk.Label(b_eff, text=_tr('ui.tracker.efficiency'), font=FS, fg=TEXTD, bg=CARD2).pack()
        self.var_eff = tk.StringVar(value='--%')
        self.lbl_eff = tk.Label(b_eff, textvariable=self.var_eff, font=FEFF,
                                 fg=TEXTD, bg=CARD2)
        self.lbl_eff.pack()

        # 說明文字
        tk.Label(c2, text=_tr('ui.tracker.desc', timeout=f'{self.tracker.idle_timeout:.0f}'),
                 font=FS, fg=TEXTD, bg=CARD, justify='left').pack(anchor='w', pady=(6,0))

        # ── 卡片 3：縮時錄影 (Timelapse) ───────────────────────────────────
        c3_tl = _card(body)
        c3_tl.pack(fill='x', pady=(0, 8))

        tk.Label(c3_tl, text=_tr('ui.tracker.timelapse_title'), font=FH, fg=TEXT, bg=CARD
                 ).pack(anchor='w', pady=(0, 6))

        # Row 1: 控制項
        row_tl_ctrl = tk.Frame(c3_tl, bg=CARD)
        row_tl_ctrl.pack(fill='x', pady=(2, 6))

        self.var_tl_enabled = tk.BooleanVar(value=self._settings.get('timelapse_enabled', False))
        self.chk_tl = tk.Checkbutton(
            row_tl_ctrl, text=_tr('ui.tracker.enable_timelapse'), variable=self.var_tl_enabled,
            font=FB, fg=TEXT, bg=CARD, selectcolor=CARD2, activebackground=CARD,
            activeforeground=TEXT, cursor='hand2', command=self._on_tl_toggle
        )
        self.chk_tl.pack(side='left', padx=(0, 10))

        tk.Label(row_tl_ctrl, text=_tr('ui.tracker.multiplier'), font=FB, fg=TEXTD, bg=CARD).pack(side='left', padx=(0, 4))
        self.var_tl_mult = tk.StringVar(value=self._settings.get('timelapse_multiplier_str', '5x (167ms)'))
        self.combo_tl_mult = ttk.Combobox(
            row_tl_ctrl, textvariable=self.var_tl_mult, state='readonly', width=11, font=FS,
            values=['1x (33ms)', '2x (67ms)', '5x (167ms)', '10x (333ms)', '20x (667ms)', '50x (1.7s)', '100x (3.3s)']
        )
        self.combo_tl_mult.pack(side='left', padx=(0, 10))
        self.combo_tl_mult.bind('<<ComboboxSelected>>', self._on_tl_mult_change)

        tk.Label(row_tl_ctrl, text=_tr('ui.tracker.target_range'), font=FB, fg=TEXTD, bg=CARD).pack(side='left', padx=(0, 4))
        self.target_display_map = {
            'canvas': _tr('timelapse.target.canvas'),
            'window': _tr('timelapse.target.window'),
            'screen': _tr('timelapse.target.screen')
        }
        self.target_display_rev = {v: k for k, v in self.target_display_map.items()}
        stored_target = self._settings.get('timelapse_target_str', 'canvas')
        initial_target_display = self.target_display_map.get(stored_target, _tr('timelapse.target.canvas'))
        self.var_tl_target = tk.StringVar(value=initial_target_display)
        self.combo_tl_target = ttk.Combobox(
            row_tl_ctrl, textvariable=self.var_tl_target, state='readonly', width=12, font=FS,
            values=list(self.target_display_map.values())
        )
        self.combo_tl_target.pack(side='left')
        self.combo_tl_target.bind('<<ComboboxSelected>>', self._on_tl_target_change)

        # Row 1 right: 影片資料夾快捷鈕
        self.btn_open_videos = _btn(
            row_tl_ctrl, _tr('ui.tracker.open_video_folder'), CARD2, ACCH,
            self._open_videos_root_dir, font=FS
        )
        self.btn_open_videos.pack(side='right')

        # Row 2: 預覽與資訊
        row_tl_disp = tk.Frame(c3_tl, bg=CARD)
        row_tl_disp.pack(fill='x', pady=(4, 0))

        info_col = tk.Frame(row_tl_disp, bg=CARD)
        info_col.pack(side='left', fill='both', expand=True)

        row_f = tk.Frame(info_col, bg=CARD)
        row_f.pack(anchor='w', pady=2)
        tk.Label(row_f, text=_tr('ui.tracker.frames_captured'), font=FB, fg=TEXTD, bg=CARD).pack(side='left')
        self.var_tl_frames = tk.StringVar(value=_tr('msg.frames_count', count=0))
        tk.Label(row_f, textvariable=self.var_tl_frames, font=FB, fg=ACCENT, bg=CARD).pack(side='left', padx=4)

        row_v = tk.Frame(info_col, bg=CARD)
        row_v.pack(anchor='w', pady=2)
        tk.Label(row_v, text=_tr('ui.tracker.estimated_video_len'), font=FB, fg=TEXTD, bg=CARD).pack(side='left')
        self.var_tl_vidlen = tk.StringVar(value='00:00 (@ 30fps)')
        tk.Label(row_v, textvariable=self.var_tl_vidlen, font=FB, fg=GREEN, bg=CARD).pack(side='left', padx=4)

        self.var_tl_status = tk.StringVar(value=_tr('ui.tracker.status_waiting'))
        if not find_ffmpeg():
            self.var_tl_status.set(_tr('ui.tracker.ffmpeg_missing'))
        self.lbl_tl_status = tk.Label(info_col, textvariable=self.var_tl_status, font=FS, fg=YELLOW, bg=CARD, justify='left')
        self.lbl_tl_status.pack(anchor='w', pady=(6, 0))

        self.canvas_tl = tk.Canvas(
            row_tl_disp, width=160, height=90, bg='#0a0a0a', highlightthickness=1, highlightbackground=BORDER
        )
        self.canvas_tl.pack(side='right', padx=(6, 0))
        self.canvas_tl.create_text(80, 45, text=_tr('ui.tracker.no_live_preview'), fill=TEXTD, font=FS, tags='ph')

        # 🎬 影片匯出進度條
        self.pb_export = ttk.Progressbar(c3_tl, orient='horizontal', mode='determinate', style='Horizontal.TProgressbar')

        # ── 卡片 4：所有圖檔記錄 ─────────────────────────────────────────
        c4 = _card(body)
        c4.pack(fill='both', expand=True, pady=(0, 8))

        hrow = tk.Frame(c4, bg=CARD)
        hrow.pack(fill='x', pady=(0, 6))
        tk.Label(hrow, text=_tr('ui.tracker.records_title'), font=FH, fg=TEXT, bg=CARD
                 ).pack(side='left')
        self.var_file_count = tk.StringVar(value=_tr('ui.tracker.file_count', count=0))
        tk.Label(hrow, textvariable=self.var_file_count,
                 font=FS, fg=TEXTD, bg=CARD).pack(side='right')

        # Treeview
        tree_frame = tk.Frame(c4, bg=CARD)
        tree_frame.pack(fill='both', expand=True)

        cols = ('file', 'open', 'draw', 'eff', 'sessions', 'last')
        self.tree = ttk.Treeview(tree_frame, columns=cols, show='tree headings',
                                  selectmode='browse')

        heads = [
            ('file',     _tr('ui.tracker.col_file'),   200, 'w'),
            ('open',     _tr('ui.tracker.col_open'),    80, 'center'),
            ('draw',     _tr('ui.tracker.col_draw'),    80, 'center'),
            ('eff',      _tr('ui.tracker.col_eff'),     55, 'center'),
            ('sessions', _tr('ui.tracker.col_sessions'), 45, 'center'),
            ('last',     _tr('ui.tracker.col_last'),   100, 'center'),
        ]
        for col, head, w, anchor in heads:
            self.tree.heading(col, text=head,
                              command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=w, minwidth=40, anchor=anchor)
        # tree 樹狀欄僅保留展開符號寬度，群組名稱收入 file 欄
        self.tree.column('#0', width=18, minwidth=18, stretch=False)

        sb = ttk.Scrollbar(tree_frame, orient='vertical',
                             command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.bind('<Button-3>', self._on_tree_right_click)
        self.tree.bind('<Motion>', self._on_tree_hover)
        self.tree.bind('<Leave>', self._hide_thumb_popup)
        self.tree.bind('<Double-1>', self._on_tree_double_click)
        # 正確追蹤群組展開/摺疊狀態
        self.tree.bind('<<TreeviewOpen>>', self._on_group_open)
        self.tree.bind('<<TreeviewClose>>', self._on_group_close)

        # 排序狀態
        self._sort_col = 'last'
        self._sort_rev = True

        # ── 控制列 ───────────────────────────────────────────────────────
        ctrl = tk.Frame(self.main_container, bg=BG, padx=14, pady=6)
        ctrl.pack(fill='x')

        _btn(ctrl, _tr('ui.tracker.btn_export_csv'), CARD2, ACCENT,
             self._export_csv, font=FS).pack(side='left', padx=(0, 4))
        _btn(ctrl, _tr('ui.tracker.btn_delete'), CARD2, '#b91c1c',
             self._delete_selected, font=FS).pack(side='left', padx=(0, 4))
        _btn(ctrl, _tr('ui.tracker.btn_reset'), CARD2, '#b91c1c',
             self._reset_all, font=FS).pack(side='left', padx=(0, 4))
        _btn(ctrl, _tr('ui.tracker.btn_settings'), CARD2, ACCH,
             self._open_settings, font=FS).pack(side='right')
        _btn(ctrl, _tr('ui.tracker.btn_save'), CARD2, ACCH,
             self._manual_save, font=FS).pack(side='right', padx=(0, 4))

        # ── 狀態列 ───────────────────────────────────────────────────────
        self.var_status = tk.StringVar(value=_tr('ui.tracker.status_tracking'))
        tk.Label(self.main_container, textvariable=self.var_status,
                 font=FS, fg=TEXTD, bg=CARD,
                 anchor='w', padx=10, pady=4).pack(fill='x', side='bottom')

        # ── 建立精簡模式容器 ──────────────────────────────────────────────
        self.mini_frame = tk.Frame(self.root, bg=CARD, highlightthickness=1, highlightbackground=ACCENT)
        self.var_mini_text = tk.StringVar(value=_tr('ui.mini.text', open_time='00:00', draw_time='00:00'))
        
        # 數據標籤
        self.lbl_mini = tk.Label(self.mini_frame, textvariable=self.var_mini_text,
                                 font=FH, fg=TEXT, bg=CARD, cursor='fleur', padx=6, pady=5)
        self.lbl_mini.pack(side='left', fill='both', expand=True)

        # 錄製控制按鈕 (極簡模式)
        self.btn_mini_record = tk.Button(
            self.mini_frame, text=_tr('ui.mini.record_waiting'), font=FS, bg=CARD2, fg=TEXT,
            activebackground=ACCENT, activeforeground='white',
            relief='flat', cursor='hand2', command=self._toggle_record_from_mini,
            padx=8, pady=2
        )
        self.btn_mini_record.pack(side='left', padx=3)
        self.btn_mini_record.bind('<Enter>', lambda _: self.btn_mini_record.config(bg=ACCENT))
        self.btn_mini_record.bind('<Leave>', lambda _: self.btn_mini_record.config(bg=CARD2))

        # 還原主視窗按鈕 (極簡模式)
        self.btn_mini_restore = tk.Button(
            self.mini_frame, text=_tr('ui.mini.restore'), font=FS, bg=CARD2, fg=TEXT,
            activebackground=ACCENT, activeforeground='white',
            relief='flat', cursor='hand2', command=self.toggle_mini_mode,
            padx=6, pady=2
        )
        self.btn_mini_restore.pack(side='left', padx=(3, 6))
        self.btn_mini_restore.bind('<Enter>', lambda _: self.btn_mini_restore.config(bg=ACCENT))
        self.btn_mini_restore.bind('<Leave>', lambda _: self.btn_mini_restore.config(bg=CARD2))

        # 拖曳與雙擊綁定
        self._make_draggable(self.lbl_mini)
        self._make_draggable(self.mini_frame)
        self.lbl_mini.bind("<Double-Button-1>", lambda _: self.toggle_mini_mode())
        
        # 鍵盤快速鍵切換（軟體內有效）
        self.root.bind("<Control-Alt-t>", lambda _: self.toggle_mini_mode())
        self.root.bind("<Control-Alt-T>", lambda _: self.toggle_mini_mode())

    # ════════════════════════════════════════════════════════════════════════
    # 輪詢更新
    # ════════════════════════════════════════════════════════════════════════

    def _poll(self):
        if self._closing or getattr(self, '_closing_temp', False):
            return

        # ── 自動鎖定邏輯 ──
        if self.timelapse_recorder.enabled:
            if self.tracker.locked_file is None:
                cur_tracked = self.tracker._cur_file
                if cur_tracked is not None:
                    # 優先解析別名後再鎖定
                    if hasattr(self.tracker, '_persist') and 'aliases' in self.tracker._persist:
                        if cur_tracked in self.tracker._persist['aliases']:
                            cur_tracked = self.tracker._persist['aliases'][cur_tracked]
                    self.tracker.locked_file = cur_tracked
        else:
            self.tracker.locked_file = None

        state = self.tracker.get_state()
        
        # 同步縮時錄影檔案狀態
        cur_file = state.get('current_file')
        self.timelapse_recorder.switch_file(cur_file)

        self._update_ui(state)

        # ── SAI2 進程監控（--auto-close 模式）────────────────────────────
        if self._auto_close:
            alive = state.get('sai2_running', False)
            if self._sai2_was_alive and not alive:
                # SAI2 剛剛關閉 → 進入自動關閉流程
                self._closing = True
                self.tracker.stop()
                self._start_close_countdown()
                return
            self._sai2_was_alive = alive

        self.root.after(1000, self._poll)

    def _update_ui(self, state: dict):
        sai2    = state['sai2_active']
        cur     = state['current_file']
        open_s  = state['session_open']
        draw_s  = state['session_draw']
        files   = state['files']

        # ── 狀態點 ───────────────────────────────────────────────────────
        self.dot.config(fg=GREEN if sai2 else RED)

        # ── 目前檔案 ───────────────────────────────────────────────
        raw = state.get('raw_title', '')
        raw_file = state.get('raw_current_file')
        if cur:
            display_cur = self._get_display_name(cur)
            lock_suffix = f" [{_tr('ui.tracker.lock_status_label', '🔒已鎖定')}]" if self.tracker.locked_file else ""
            if raw_file and raw_file != cur:
                display_raw = self._get_display_name(raw_file)
                self.var_cur_file.set(f'🖼  {display_cur}{lock_suffix} (別名: {display_raw})')
            else:
                self.var_cur_file.set(f'🖼  {display_cur}{lock_suffix}')
        elif raw:  # 已偵測到但檔名解析失敗——顯示原始標題供除錯
            self.var_cur_file.set(_tr('msg.sai_detected_no_name', title=raw[:60]))
        elif sai2:
            self.var_cur_file.set(_tr('msg.sai_detected_no_file'))
        else:
            self.var_cur_file.set(_tr('msg.sai_not_detected'))

        # ── 動筆指示燈 ───────────────────────────────────────────────────
        if cur and sai2:
            self._blink = not self._blink
            # 判斷是否正在動筆（draw 時間正在增加）
            if draw_s > 0 and open_s > 0:
                drawing_now = (open_s - draw_s) < (self.tracker.idle_timeout + 1)
            else:
                drawing_now = False

            if drawing_now:
                self.var_draw_ind.set('✏️ 動筆中' if self._blink else '   動筆中')
            else:
                self.var_draw_ind.set('')
        else:
            self.var_draw_ind.set('')

        # ── 工作階段時間 ─────────────────────────────────────────────────
        if cur:
            self.var_open.set(fmt_seconds(open_s))
            self.var_draw.set(fmt_seconds(draw_s))
            pct = int(draw_s / open_s * 100) if open_s > 0 else 0
            pct = min(pct, 100)
            self.var_eff.set(f'{pct}%')
            self.lbl_eff.config(fg=_eff_color(pct))
        else:
            self.var_open.set('--:--')
            self.var_draw.set('--:--')
            self.var_eff.set('--%')
            self.lbl_eff.config(fg=TEXTD)

        # ── 更新 Treeview ────────────────────────────────────────────────
        self._refresh_tree(files)

        # ── 狀態列 ───────────────────────────────────────────────────────
        n = len(files)
        self.var_file_count.set(_tr('ui.tracker.file_count', count=n))
        
        # 縮時錄影精簡模式狀態指示
        tl_ind = ""
        if self.timelapse_recorder.enabled:
            if self.timelapse_recorder.is_actively_recording:
                tl_ind = " | 📹 錄影中"
            else:
                tl_ind = " | ⏸️ 錄影暫停"

        if cur:
            status_text = _tr('msg.tracking_file', file=cur)
            if not sai2:
                status_text += _tr('msg.paused_suffix')
            save_loc = '桌面' if 'desktop' in self.tracker.data_path.lower() else '套件目錄'
            self.var_status.set(_tr('msg.status_saved', status=status_text, path=save_loc))
            # 取得該圖檔的總累計時間紀錄
            rec = files.get(cur, {})
            tot_open = rec.get('open_seconds', 0.0)
            tot_draw = rec.get('draw_seconds', 0.0)
            tot_pct = int(tot_draw / tot_open * 100) if tot_open > 0 else 0
            tot_pct = min(tot_pct, 100)
            self.var_mini_text.set(f"⏱️ {fmt_seconds(tot_open)} | ✏️ {fmt_seconds(tot_draw)} ({tot_pct}%)")
        else:
            self.var_status.set('等待 PaintTool SAI 開啟中…')
            self.var_mini_text.set(_tr('msg.no_working_file'))
            
        self._update_mini_buttons()

    def _get_auto_group(self, fname: str) -> str:
        """依路徑第一層資料夾自動分組。"""
        if ' _ ' in fname:
            parts = fname.split(' _ ')
            import re
            # 跳過磁碟機標籤段（含括號磁碟代號）
            if parts and re.search(r'\([A-Za-z]:\)', parts[0]):
                parts = parts[1:]
            if parts:
                return parts[0]   # 第一層資料夾名稱
        return '根目錄'

    def _get_group(self, fname: str) -> str:
        """回傳此圖檔的分組名稱（自訂 > 自動）。"""
        return self._custom_groups.get(fname) or self._get_auto_group(fname)

    def _get_display_name(self, fname: str) -> str:
        """回傳圖檔在列表中顯示的簡短檔名（僅保留最後一個 ' _ ' 後段）。"""
        if ' _ ' in fname:
            return fname.split(' _ ')[-1]
        return fname

    def _refresh_tree(self, files: dict):
        """重建圖檔列表，按分組顯示可摺疊的樹狀結構。"""
        sel_file = self._selected_file

        # ── 先讀取目前展開狀態，避免重建後遮失使用者設定 ────────────
        for child in self.tree.get_children():
            if child.startswith('__grp__'):
                grp_name = child[7:]
                self._group_open[grp_name] = bool(self.tree.item(child, 'open'))

        # ── 依分組收集檔案 ──────────────────────────────────────────────
        groups: dict[str, list[tuple]] = {}
        for fname, rec in files.items():
            grp = self._get_group(fname)
            groups.setdefault(grp, []).append((fname, rec))

        # ── 依群組名稱排序，群組內再依 _sort_col 排序 ───────────────────
        def sort_key(item):
            fname, rec = item
            if self._sort_col == 'file':     return fname.lower()
            if self._sort_col == 'open':     return rec.get('open_seconds', 0)
            if self._sort_col == 'draw':     return rec.get('draw_seconds', 0)
            if self._sort_col == 'eff':
                op = rec.get('open_seconds', 0)
                return rec.get('draw_seconds', 0) / op if op > 0 else 0
            if self._sort_col == 'sessions': return rec.get('sessions', 0)
            if self._sort_col == 'last':     return rec.get('last_seen', '')
            return 0

        def group_sort_key(gname):
            if self._sort_col == 'file':
                return gname.lower()
            g_items = groups[gname]
            if not g_items:
                return "" if self._sort_col == 'last' else 0
            vals = [sort_key(x) for x in g_items]
            return max(vals) if self._sort_rev else min(vals)

        # 清空並重建
        self.tree.delete(*self.tree.get_children())
        restore_iid = None

        sorted_groups = sorted(groups.keys(), key=group_sort_key, reverse=self._sort_rev)
        for grp_name in sorted_groups:
            items = sorted(groups[grp_name], key=sort_key, reverse=self._sort_rev)
            grp_iid = f'__grp__{grp_name}'

            # 群組加總統計
            total_open = sum(r.get('open_seconds', 0) for _, r in items)
            total_draw = sum(r.get('draw_seconds', 0) for _, r in items)
            total_sess = sum(r.get('sessions', 0) for _, r in items)
            grp_eff    = int(total_draw / total_open * 100) if total_open > 0 else 0
            grp_eff    = min(grp_eff, 100)

            is_open = self._group_open.get(grp_name, True)  # 預設展開
            emoji = self._group_emojis.get(grp_name, '📁')

            # 插入群組列（parent 列）—群組名稱放入 file 欄顯示
            self.tree.insert(
                '', 'end', iid=grp_iid,
                text='',   # 空白，展開符號就在 #0
                values=(
                    _tr('msg.group_info', emoji=emoji, name=grp_name, count=len(items)),
                    fmt_seconds(total_open),
                    fmt_seconds(total_draw),
                    f'{grp_eff}%',
                    total_sess,
                    ''
                ),
                open=is_open,
                tags=('group',)
            )

            # 插入群組內的檔案列
            for fname, rec in items:
                op  = rec.get('open_seconds', 0)
                dr  = rec.get('draw_seconds', 0)
                eff = int(dr / op * 100) if op > 0 else 0
                eff = min(eff, 100)
                ls  = rec.get('last_seen', '')[:10]
                self.tree.insert(
                    grp_iid, 'end', iid=fname,
                    values=(
                        self._get_display_name(fname), fmt_seconds(op), fmt_seconds(dr),
                        f'{eff}%', rec.get('sessions', 0), ls
                    )
                )
                if fname == sel_file:
                    restore_iid = fname

        # 群組列樣式
        self.tree.tag_configure('group', background=CARD, foreground=ACCENT, font=FH)

        # 恢復選取
        if restore_iid:
            try:
                self.tree.see(restore_iid)
                self.tree.selection_set(restore_iid)
            except Exception:
                pass

    def _sort_by(self, col: str):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = col != 'file'  # 數字欄預設由大到小，名稱由小到大
        self._refresh_tree(self.tracker.get_state().get('files', {}))

    def _on_tree_select(self, _=None):
        sel = self.tree.selection()
        if sel:
            iid = sel[0]
            # 群組列本身不算選取檔案
            if iid.startswith('__grp__'):
                self._selected_file = None
            else:
                self._selected_file = iid
        else:
            self._selected_file = None

    def _on_group_open(self, event):
        """TreeviewOpen 事件：群組被展開"""
        iid = self.tree.focus()
        if iid.startswith('__grp__'):
            self._group_open[iid[7:]] = True

    def _on_group_close(self, event):
        """TreeviewClose 事件：群組被摺疊"""
        iid = self.tree.focus()
        if iid.startswith('__grp__'):
            self._group_open[iid[7:]] = False

    def _on_tree_double_click(self, event):
        """雙擊檔案列時，嘗試用 SAI2 開啟該檔案。"""
        item = self.tree.identify_row(event.y)
        if not item or item.startswith('__grp__'):
            return  # 群組列預設提供占開/摺疊行為

        fname = item
        # 若啟用錄影，雙擊打開檔案時，自動將鎖定圖檔切換為此圖檔（支援別名自動解析）
        if self.timelapse_recorder.enabled:
            resolved_fname = fname
            if hasattr(self.tracker, '_persist') and 'aliases' in self.tracker._persist:
                if fname in self.tracker._persist['aliases']:
                    resolved_fname = self.tracker._persist['aliases'][fname]
            self.tracker.locked_file = resolved_fname

        self.var_status.set(_tr('msg.finding_path', file=fname))
        self.root.update_idletasks()

        def _do_open():
            path = self._find_file_path(fname)
            if not path or not os.path.isfile(path):
                self.root.after(0, lambda: self.var_status.set(
                    f'⚠️ 找不到檔案路徑：{fname}'
                ))
                return
            try:
                # 優先找尋正在執行的 SAI2 執行檔路徑
                sai2_exe = None
                
                # 1. 優先從當前已開啟的 SAI 視窗取得執行路徑（精準且極速）
                try:
                    from timelapse import scan_sai_windows
                    main_win, _ = scan_sai_windows(os.getpid())
                    if main_win:
                        import win32process
                        import psutil
                        _, pid = win32process.GetWindowThreadProcessId(main_win[0])
                        proc = psutil.Process(pid)
                        exe_path = proc.exe()
                        if exe_path and os.path.isfile(exe_path):
                            sai2_exe = exe_path
                except Exception:
                    pass
                
                # 2. 備用方案：如果未開啟，遍歷行程尋找符合名稱的軟體
                if not sai2_exe:
                    try:
                        import psutil
                        for proc in psutil.process_iter(['name', 'exe']):
                            n = (proc.info.get('name') or '').lower()
                            # 排除本計時器、監視器及 python 進程，精確尋找繪圖軟體
                            if n in ('sai.exe', 'sai2.exe', 'sai2c.exe', 'sai2_backup.exe') or (
                                ('painttool' in n or 'sai' in n)
                                and not any(x in n for x in ('drawcompanion', 'drawtimer', 'watcher', 'python', 'cmd', 'powershell', 'explorer', 'lsaiso'))
                                and n.endswith('.exe')
                            ):
                                exe_path = proc.info.get('exe')
                                if exe_path and os.path.isfile(exe_path):
                                    sai2_exe = exe_path
                                    break
                    except Exception:
                        pass

                # 備援一：尋找同層或上層目錄下的 PaintTool SAI 執行檔
                if not sai2_exe:
                    for folder in (_APP_DIR, os.path.dirname(_APP_DIR)):
                        for candidate in ('sai2.exe', 'sai.exe', 'sai2_backup.exe'):
                            p = os.path.join(folder, candidate)
                            if os.path.isfile(p):
                                sai2_exe = p
                                break
                        if sai2_exe:
                            break

                if sai2_exe and os.path.isfile(sai2_exe):
                    subprocess.Popen([sai2_exe, path])
                    self.root.after(0, lambda: self.var_status.set(
                        f'✅ 已要求 SAI2 開啟：{os.path.basename(path)}'
                    ))
                else:
                    # 備案二：用 Windows 檔案關聯開啟
                    os.startfile(path)
                    self.root.after(0, lambda: self.var_status.set(
                        f'✅ 已開啟：{os.path.basename(path)}'
                    ))
            except Exception as e:
                self.root.after(0, lambda: self.var_status.set(_tr('msg.open_failed', err=e)))

        import threading
        threading.Thread(target=_do_open, daemon=True).start()

    def _on_tree_right_click(self, event):
        """在 Treeview 上顯示右鍵快捷選單"""
        item = self.tree.identify_row(event.y)
        
        # 根據點選項目類型來設定選取與選中狀態
        if item:
            self.tree.selection_set(item)
            if item.startswith('__grp__'):
                self._selected_file = None
                self._selected_group = item[7:]
            else:
                self._selected_file = item
                self._selected_group = None
        else:
            self.tree.selection_clear()
            self._selected_file = None
            self._selected_group = None

        menu = tk.Menu(self.root, tearoff=0, bg=CARD2, fg=TEXT,
                       activebackground=ACCENT, activeforeground='white',
                       font=FB, bd=0, relief='flat')

        if self._selected_file:
            fname = self._selected_file
            menu.add_command(
                label=_tr('menu.open_dir'),
                command=lambda: self._open_file_directory(fname)
            )
            menu.add_command(
                label=_tr('menu.open_video_dir'),
                command=lambda: self._open_video_dir(fname)
            )
            menu.add_separator()
            menu.add_command(
                label=_tr('menu.copy_name'),
                command=lambda: self._copy_filename(fname)
            )
            menu.add_command(
                label=_tr('menu.change_group'),
                command=lambda: self._change_group_dialog(fname)
            )
            if fname in self._custom_groups:
                menu.add_command(
                    label=_tr('menu.revert_auto_group'),
                    command=lambda: self._revert_to_auto_group(fname)
                )
            menu.add_separator()
            menu.add_command(
                label=_tr('menu.manage_aliases', '🔗  別名管理 (關聯另存...)'),
                command=lambda: self._manage_aliases_dialog(fname)
            )
            menu.add_command(
                label=_tr('menu.set_as_alias', '🏷️  將此檔設為其他檔的別名...'),
                command=lambda: self._set_as_alias_dialog(fname)
            )
            menu.add_separator()
            menu.add_command(
                label=_tr('menu.delete_record'),
                command=self._delete_selected
            )
        elif self._selected_group:
            grp_name = self._selected_group
            menu.add_command(
                label=_tr('menu.rename_group'),
                command=lambda: self._rename_group_dialog(grp_name)
            )
            menu.add_command(
                label=_tr('menu.customize_emoji'),
                command=lambda: self._change_group_emoji_dialog(grp_name)
            )
        else:
            menu.add_command(label=_tr('menu.no_selection'), state='disabled')

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _revert_to_auto_group(self, fname: str):
        """移除自訂分組，還原為自動分組路徑。"""
        if fname in self._custom_groups:
            self._custom_groups.pop(fname, None)
            self._settings['custom_groups'] = self._custom_groups
            _save_settings(self._settings)
            
            # 立刻刷新列表
            state = self.tracker.get_state()
            self._refresh_tree(state.get('files', {}))
            self.var_status.set(_tr('dialog.group.reverted', file=fname))

    def _copy_filename(self, fname: str):
        """複製檔名至剪貼簿"""
        self.root.clipboard_clear()
        self.root.clipboard_append(fname)
        self.var_status.set(_tr('msg.copied', file=fname))

    def _rename_group_dialog(self, old_grp_name: str):
        """彈出小對話框讓使用者修改群組名稱，並批次更新所有屬於該群組的檔案。"""
        dlg = tk.Toplevel(self.root)
        dlg.title(_tr('dialog.group.rename_title'))
        dlg.configure(bg=CARD)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.root)

        tk.Label(dlg, text=_tr('dialog.group.rename_prompt'), font=FB, fg=TEXT, bg=CARD
                 ).pack(padx=14, pady=(12, 6), anchor='w')

        var = tk.StringVar(value=old_grp_name)
        ent = tk.Entry(dlg, textvariable=var, font=FB, bg=CARD2, fg=TEXT,
                       insertbackground=TEXT, relief='flat', width=28)
        ent.pack(padx=14, pady=(0, 10))
        ent.focus_set()
        ent.select_range(0, 'end')

        def _confirm():
            new_grp = var.get().strip()
            if not new_grp:
                return
            if new_grp == old_grp_name:
                dlg.destroy()
                return

            state = self.tracker.get_state()
            files = state.get('files', {})
            
            # 批次更新所有原屬於 old_grp_name 的檔案為 new_grp
            updated_count = 0
            for fname in files.keys():
                if self._get_group(fname) == old_grp_name:
                    self._custom_groups[fname] = new_grp
                    updated_count += 1
            
            if updated_count > 0:
                self._settings['custom_groups'] = self._custom_groups
                
                # 同步更新自訂 Emoji 的 Key
                if old_grp_name in self._group_emojis:
                    emoji = self._group_emojis.pop(old_grp_name)
                    self._group_emojis[new_grp] = emoji
                    self._settings['group_emojis'] = self._group_emojis
                
                _save_settings(self._settings)

            dlg.destroy()
            self._refresh_tree(files)
            self.var_status.set(_tr('dialog.group.rename_success', old=old_grp_name, new=new_grp))

        btn_row = tk.Frame(dlg, bg=CARD)
        btn_row.pack(padx=14, pady=(0, 12))
        _btn(btn_row, _tr('dialog.confirm'), ACCENT, ACCH, _confirm, font=FB).pack(side='left', padx=(0, 6))
        _btn(btn_row, _tr('dialog.cancel'), CARD2, '#b91c1c', dlg.destroy, font=FB).pack(side='left')

    def _change_group_emoji_dialog(self, grp_name: str):
        """彈出小對話框讓使用者輸入該分組的自訂 Emoji，並自動彈出系統 Emoji 面板。"""
        current_emoji = self._group_emojis.get(grp_name, '📁')
        
        dlg = tk.Toplevel(self.root)
        dlg.title(_tr('dialog.group.emoji_title'))
        dlg.configure(bg=CARD)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.root)

        tk.Label(dlg, text=_tr('dialog.group.emoji_prompt'), font=FB, fg=TEXT, bg=CARD
                 ).pack(padx=14, pady=(12, 6), anchor='w')

        var = tk.StringVar(value=current_emoji)
        ent = tk.Entry(dlg, textvariable=var, font=FB, bg=CARD2, fg=TEXT,
                       insertbackground=TEXT, relief='flat', width=28)
        ent.pack(padx=14, pady=(0, 10))
        ent.focus_set()
        ent.select_range(0, 'end')

        def _trigger_emoji_panel():
            try:
                import ctypes
                # Simulate Win + .
                ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # Win Press
                ctypes.windll.user32.keybd_event(0xBE, 0, 0, 0)  # . Press
                ctypes.windll.user32.keybd_event(0xBE, 0, 2, 0)  # . Release
                ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)  # Win Release
            except Exception:
                pass

        # 延遲待對話框繪製且聚焦後，自動呼叫 Windows Emoji 面板
        dlg.after(150, _trigger_emoji_panel)

        def _confirm():
            new_emoji = var.get().strip()
            if new_emoji and new_emoji != '📁':
                self._group_emojis[grp_name] = new_emoji
            else:
                self._group_emojis.pop(grp_name, None)
            
            self._settings['group_emojis'] = self._group_emojis
            _save_settings(self._settings)
            dlg.destroy()
            
            state = self.tracker.get_state()
            self._refresh_tree(state.get('files', {}))
            self.var_status.set(_tr('dialog.group.emoji_success', group=grp_name, emoji=new_emoji or '📁'))

        btn_row = tk.Frame(dlg, bg=CARD)
        btn_row.pack(padx=14, pady=(0, 12))
        _btn(btn_row, _tr('dialog.confirm'), ACCENT, ACCH, _confirm, font=FB).pack(side='left', padx=(0, 6))
        _btn(btn_row, _tr('dialog.cancel'), CARD2, '#b91c1c', dlg.destroy, font=FB).pack(side='left')

    def _change_group_dialog(self, fname: str):
        """彈出小對話框讓使用者輸入自訂分組名稱。"""
        current = self._custom_groups.get(fname, '')
        auto    = self._get_auto_group(fname)

        dlg = tk.Toplevel(self.root)
        dlg.title(_tr('dialog.group.title'))
        dlg.configure(bg=CARD)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.root)

        tk.Label(dlg, text=_tr('dialog.group.file', file=fname), font=FS, fg=TEXTD, bg=CARD,
                 wraplength=320, justify='left').pack(padx=14, pady=(12, 4), anchor='w')
        tk.Label(dlg, text=_tr('dialog.group.auto', auto=auto), font=FS, fg=TEXTD, bg=CARD).pack(padx=14, anchor='w')
        tk.Label(dlg, text=_tr('dialog.group.prompt'), font=FB, fg=TEXT, bg=CARD
                 ).pack(padx=14, pady=(8, 2), anchor='w')

        # 收集現有所有檔案的分組名稱，作為下拉選單預設選項
        state = self.tracker.get_state()
        files = state.get('files', {})
        existing_groups = sorted(list(set(self._get_group(fn) for fn in files.keys())))

        var = tk.StringVar(value=current)
        ent = ttk.Combobox(dlg, textvariable=var, values=existing_groups, font=FB, width=26)
        ent.pack(padx=14, pady=(0, 10))
        ent.focus_set()
        ent.select_range(0, 'end')

        def _confirm():
            new_grp = var.get().strip()
            if new_grp:
                self._custom_groups[fname] = new_grp
            else:
                self._custom_groups.pop(fname, None)
            self._settings['custom_groups'] = self._custom_groups
            _save_settings(self._settings)
            dlg.destroy()
            # 立刻刷新列表
            state = self.tracker.get_state()
            self._refresh_tree(state.get('files', {}))
            self.var_status.set(_tr('dialog.group.updated', file=fname, group=new_grp or auto))

        btn_row = tk.Frame(dlg, bg=CARD)
        btn_row.pack(padx=14, pady=(0, 12))
        _btn(btn_row, _tr('dialog.confirm'), ACCENT, ACCH, _confirm, font=FB).pack(side='left', padx=(0, 6))
        _btn(btn_row, _tr('dialog.cancel'), CARD2, '#b91c1c', dlg.destroy, font=FB).pack(side='left')

        ent.bind('<Return>', lambda _: _confirm())
        ent.bind('<Escape>', lambda _: dlg.destroy())

    def _set_as_alias_dialog(self, fname: str):
        """彈出對話框讓使用者將此圖檔設定為其他圖檔的別名（關聯/合併）。"""
        dlg = tk.Toplevel(self.root)
        dlg.title(_tr('dialog.alias.set_title', "設定別名關聯"))
        dlg.configure(bg=CARD)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.root)

        tk.Label(
            dlg, 
            text=_tr('dialog.alias.set_prompt', f"將圖檔「{self._get_display_name(fname)}」設定為別名，其計時紀錄將合併至所選的主圖檔中：", file=self._get_display_name(fname)), 
            font=FS, fg=TEXT, bg=CARD, wraplength=320, justify='left'
        ).pack(padx=14, pady=(12, 8), anchor='w')

        # 獲取其他所有主圖檔（排除自身）
        state = self.tracker.get_state()
        files = state.get('files', {})
        target_files = sorted([fn for fn in files.keys() if fn != fname])

        if not target_files:
            tk.Label(dlg, text="無其他可用的主圖檔。", font=FB, fg=RED, bg=CARD).pack(padx=14, pady=10)
            _btn(dlg, _tr('dialog.close', "關閉"), CARD2, ACCH, dlg.destroy, font=FB).pack(pady=(0, 12))
            return

        var = tk.StringVar()
        ent = ttk.Combobox(dlg, textvariable=var, values=target_files, font=FB, width=32, state='readonly')
        ent.pack(padx=14, pady=(0, 12))
        ent.focus_set()
        if target_files:
            ent.current(0)

        def _confirm():
            target = var.get().strip()
            if not target:
                return
            
            # 確認提示
            if messagebox.askyesno(
                "確認關聯", 
                f"確定要將「{self._get_display_name(fname)}」設定為「{self._get_display_name(target)}」的別名嗎？\n此檔目前的計時數據將被合併至該主圖檔中，且此檔將不再獨立顯示於列表中。", 
                parent=dlg
            ):
                # 呼叫 tracker 新增別名
                self.tracker.add_alias(fname, target)
                
                # 清除該別名在 custom_groups 中的設定
                if fname in self._custom_groups:
                    self._custom_groups.pop(fname, None)
                    self._settings['custom_groups'] = self._custom_groups
                    _save_settings(self._settings)
                
                dlg.destroy()
                
                # 刷新列表和統計
                state = self.tracker.get_state()
                self._refresh_tree(state.get('files', {}))
                self._refresh_stats_chart()
                self.var_status.set(f"已將「{self._get_display_name(fname)}」設為「{self._get_display_name(target)}」的別名")

        btn_row = tk.Frame(dlg, bg=CARD)
        btn_row.pack(padx=14, pady=(0, 12))
        _btn(btn_row, _tr('dialog.confirm'), ACCENT, ACCH, _confirm, font=FB).pack(side='left', padx=(0, 6))
        _btn(btn_row, _tr('dialog.cancel'), CARD2, '#b91c1c', dlg.destroy, font=FB).pack(side='left')

        ent.bind('<Return>', lambda _: _confirm())
        ent.bind('<Escape>', lambda _: dlg.destroy())

    def _manage_aliases_dialog(self, fname: str):
        """彈出對話框管理此圖檔的別名。"""
        dlg = tk.Toplevel(self.root)
        dlg.title(_tr('dialog.alias.manage_title', "管理別名"))
        dlg.configure(bg=CARD)
        dlg.geometry("400x380")
        dlg.grab_set()
        dlg.transient(self.root)
        
        # 標題
        tk.Label(
            dlg, 
            text=f"主圖檔：{self._get_display_name(fname)}", 
            font=FH, fg=ACCENT, bg=CARD, justify='left'
        ).pack(padx=14, pady=(12, 4), anchor='w')

        # 說明
        tk.Label(
            dlg, 
            text="設定別名可讓「另存新檔」或「匯出」的檔案共用同一個計時紀錄。", 
            font=FS, fg=TEXTD, bg=CARD, justify='left'
        ).pack(padx=14, pady=(0, 8), anchor='w')

        # 別名列表區域 (Scrollable Frame)
        list_frame = tk.LabelFrame(dlg, text="目前的別名清單", font=FH, fg=TEXT, bg=CARD, bd=1, relief='solid', padx=10, pady=8)
        list_frame.pack(fill='both', expand=True, padx=14, pady=4)

        # 滾動容器
        canvas = tk.Canvas(list_frame, bg=CARD, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=CARD)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _refresh_aliases():
            # 清空舊列表
            for child in scrollable_frame.winfo_children():
                child.destroy()
            
            # 獲取目前的別名
            aliases = []
            if 'aliases' in self.tracker._persist:
                aliases = sorted([k for k, v in self.tracker._persist['aliases'].items() if v == fname])
            
            if not aliases:
                tk.Label(scrollable_frame, text="（無別名設定）", font=FB, fg=TEXTD, bg=CARD).pack(anchor='w', pady=4)
                return
                
            for alias in aliases:
                row = tk.Frame(scrollable_frame, bg=CARD)
                row.pack(fill='x', expand=True, pady=2)
                
                # 顯示名稱及提示
                lbl = tk.Label(row, text=self._get_display_name(alias), font=FB, fg=TEXT, bg=CARD, wraplength=220, justify='left')
                lbl.pack(side='left', anchor='w')
                
                # 顯示 tooltip，滑鼠移上去可以看完整路徑
                lbl.bind("<Enter>", lambda _, a=alias: self.var_status.set(f"別名完整路徑: {a}"))
                lbl.bind("<Leave>", lambda _: self.var_status.set(""))
                
                # 刪除按鈕
                def _remove(a_name=alias):
                    if messagebox.askyesno("解除關聯", f"確定要解除別名「{self._get_display_name(a_name)}」的關聯嗎？\n解除後此檔的時間將不會扣除，但未來的時間將重新獨立計時。", parent=dlg):
                        self.tracker.remove_alias(a_name)
                        _refresh_aliases()
                        # 立刻刷新主列表
                        state = self.tracker.get_state()
                        self._refresh_tree(state.get('files', {}))
                        self.var_status.set(f"已解除別名「{self._get_display_name(a_name)}」的關聯")

                _btn(row, "解除", CARD2, '#b91c1c', _remove, font=FS, pady=1).pack(side='right', padx=4)

        _refresh_aliases()

        # 新增別名區域
        add_frame = tk.Frame(dlg, bg=CARD, pady=8)
        add_frame.pack(fill='x', padx=14)

        tk.Label(add_frame, text="手動新增別名（請輸入完整檔名，含副檔名）：", font=FS, fg=TEXTD, bg=CARD).pack(anchor='w', pady=(0, 2))
        
        row_input = tk.Frame(add_frame, bg=CARD)
        row_input.pack(fill='x')
        
        var_new_alias = tk.StringVar()
        ent_new = tk.Entry(row_input, textvariable=var_new_alias, font=FB, bg=CARD2, fg=TEXT, insertbackground=TEXT, relief='flat')
        ent_new.pack(side='left', fill='x', expand=True, padx=(0, 6))

        def _add_alias_action():
            val = var_new_alias.get().strip()
            if not val:
                return
            # 驗證檔名必須有副檔名
            from tracker import is_saved_filename
            if not is_saved_filename(val):
                messagebox.showerror("格式錯誤", "別名必須是合法的檔案名稱（需包含副檔名，如 .sai2, .png 等）。", parent=dlg)
                return
                
            # 檢查是否已是別名
            if val in self.tracker._persist.get('aliases', {}):
                current_target = self.tracker._persist['aliases'][val]
                messagebox.showerror("重複設定", f"此檔已被設定為「{self._get_display_name(current_target)}」的別名。", parent=dlg)
                return
                
            # 檢查是否已是主圖檔
            if val in self.tracker._persist.get('files', {}):
                # 警告合併
                if not messagebox.askyesno("合併確認", f"「{val}」已經有計時紀錄。將其新增為別名會合併其歷史數據，且此後它將不再獨立顯示於列表中。確定要合併嗎？", parent=dlg):
                    return
            
            self.tracker.add_alias(val, fname)
            var_new_alias.set("")
            _refresh_aliases()
            # 刷新主列表
            state = self.tracker.get_state()
            self._refresh_tree(state.get('files', {}))
            self.var_status.set(f"已成功為「{self._get_display_name(fname)}」新增別名「{val}」")

        _btn(row_input, "新增", ACCENT, ACCH, _add_alias_action, font=FB).pack(side='right')

        # 關閉按鈕
        _btn(dlg, _tr('dialog.close', "關閉"), CARD2, ACCH, dlg.destroy, font=FB).pack(pady=(10, 12))

    def _open_video_dir(self, fname: str):
        """開啟該圖檔對應的錄影子目錄；若尚無錄影記錄則顯示提示。"""
        subdir = file_key_to_subdir(fname)
        tl_out = self._settings.get('timelapse_output_dir',
                                    os.path.join(_APP_DIR, 'videos'))
        video_dir = os.path.join(tl_out, subdir)
        if os.path.isdir(video_dir):
            try:
                import subprocess
                subprocess.Popen(['explorer', os.path.normpath(video_dir)])
                self.var_status.set(_tr('msg.opened_video_dir', dir=video_dir))
            except Exception as e:
                self.var_status.set(_tr('msg.open_dir_failed', err=e))
        else:
            self.var_status.set(_tr('msg.no_video_record', subdir=subdir))

    def _open_videos_root_dir(self):
        """開啟影片根目錄。"""
        tl_out = self._settings.get('timelapse_output_dir',
                                    os.path.join(_APP_DIR, 'videos'))
        os.makedirs(tl_out, exist_ok=True)
        try:
            import subprocess
            subprocess.Popen(['explorer', os.path.normpath(tl_out)])
        except Exception:
            os.startfile(tl_out)

    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.csv',
            filetypes=[(_tr('filetype.csv'), '*.csv')],
            title=_tr('dialog.export.title'),
            initialfile='sai2_draw_time.csv'
        )
        if path:
            try:
                self.tracker.export_csv(path)
                self.var_status.set(f'✅ 已成功匯出 CSV 至：{path}')
            except Exception as e:
                messagebox.showerror('匯出失敗', f'無法寫入 CSV 檔案：{e}', parent=self.root)

    def _delete_selected(self):
        fname = self._selected_file
        if not fname:
            messagebox.showinfo('提示', '請先從列表中選取要刪除的圖檔記錄', parent=self.root)
            return
        if messagebox.askyesno('確認刪除', f'確定要刪除「{fname}」的計時與錄影記錄嗎？\n此動作無法還原。', parent=self.root):
            self.tracker.delete_file(fname)
            try:
                subdir = file_key_to_subdir(fname)
                tl_out = self._settings.get('timelapse_output_dir', os.path.join(_APP_DIR, 'videos'))
                video_dir = os.path.normpath(os.path.join(tl_out, subdir))
                import shutil
                if os.path.isdir(video_dir):
                    shutil.rmtree(video_dir, ignore_errors=True)
            except Exception:
                pass
                
            self._selected_file = None
            state = self.tracker.get_state()
            self._refresh_tree(state.get('files', {}))
            self._refresh_stats_chart()
            self.var_status.set(_tr('msg.deleted_record', file=fname))

    def _reset_all(self):
        if messagebox.askyesno('確認清空', '確定要清空所有圖檔計時與錄影記錄嗎？\n此動作將清除全部歷史資料且無法還原！', parent=self.root):
            self.tracker.reset_all()
            try:
                tl_out = self._settings.get('timelapse_output_dir', os.path.join(_APP_DIR, 'videos'))
                if os.path.isdir(tl_out):
                    for item in os.listdir(tl_out):
                        p = os.path.join(tl_out, item)
                        if os.path.isdir(p) and item != 'temp':
                            import shutil
                            shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
                
            self._selected_file = None
            state = self.tracker.get_state()
            self._refresh_tree(state.get('files', {}))
            self._refresh_stats_chart()
            self.var_status.set(_tr('msg.reset_success'))

    def _manual_save(self):
        try:
            self.tracker.save()
            self.var_status.set(_tr('msg.manual_saved'))
        except Exception as e:
            messagebox.showerror('存檔失敗', f'無法寫入資料庫：{e}', parent=self.root)

    # ── Hover 縮圖預覽 ──────────────────────────────────────────────────────

    def _on_tree_hover(self, event):
        """滑鼠在 Treeview 上移動時，若移入不同的檔案列則更新縮圖浮動視窗。"""
        item = self.tree.identify_row(event.y)
        # 只對檔案列（非群組列）顯示預覽
        if not item or item.startswith('__grp__'):
            self._hide_thumb_popup()
            return

        if item == self._hover_item:
            # 同一列：只移動浮動視窗位置
            if self._thumb_popup:
                x = event.x_root + 16
                y = event.y_root + 8
                self._thumb_popup.geometry(f'+{x}+{y}')
            return

        self._hover_item = item
        self._destroy_popup()

        # 背景載入縮圖
        import threading
        threading.Thread(
            target=self._load_thumb_async,
            args=(item, event.x_root, event.y_root),
            daemon=True
        ).start()

    def _destroy_popup(self):
        """僅銷毀浮動視窗，不清除 _hover_item 狀態。"""
        if self._thumb_popup:
            try:
                self._thumb_popup.destroy()
            except Exception:
                pass
            self._thumb_popup = None

    def _hide_thumb_popup(self, _=None):
        """完全隱藏縮圖並清除 hover 狀態。"""
        self._destroy_popup()
        self._hover_item = None

    def _load_thumb_async(self, fname: str, mx: int, my: int):
        """在背景執行緒中找到 last_frame.jpg 並通知主執行緒顯示。"""
        try:
            subdir = file_key_to_subdir(fname)
            tl_out = self._settings.get('timelapse_output_dir',
                                        os.path.join(_APP_DIR, 'videos'))
            thumb_path = os.path.join(tl_out, subdir, 'last_frame.jpg')
            if not os.path.isfile(thumb_path):
                return
            img = Image.open(thumb_path)
            img.thumbnail((220, 124), Image.BILINEAR)
            self.root.after(0, lambda: self._show_thumb_popup(img, fname, mx, my))
        except Exception:
            pass

    def _show_thumb_popup(self, img: 'Image.Image', fname: str, mx: int, my: int):
        """在主執行緒中建立/更新縮圖浮動視窗。"""
        # 確認 hover 仍停留在同一列
        if self._hover_item != fname:
            return
        self._destroy_popup()

        try:
            popup = tk.Toplevel(self.root)
            popup.overrideredirect(True)    # 無邊框
            popup.attributes('-topmost', True)
            popup.configure(bg=CARD, highlightthickness=1,
                            highlightbackground=ACCENT)
            popup.geometry(f'+{mx + 16}+{my + 8}')

            photo = ImageTk.PhotoImage(img)
            tk.Label(popup, image=photo, bg=CARD).pack()

            self._thumb_popup   = popup
            self._thumb_img_ref = photo   # 防止 GC
        except Exception:
            pass

    def _find_file_path(self, key: str) -> str | None:
        """
        從儲存的 key 反推出真實的檔案路徑。

        實際儲存格式範例：
          「本機磁碟 (D:) _ 2026 _ 0621.sai2」
          → 分隔符為 ' _ '（兩側帶空格）
          → 第一段為磁碟機標籤，含括號磁碟代號 (D:)
          → 其餘段依序為路徑層級
          → 組合結果：D:\2026\0621.sai2
        """
        import re

        # ── 方法一：依照 ' _ '（帶空格）拆分，直接解析磁碟機標籤 ────────
        if ' _ ' in key:
            parts = key.split(' _ ')
            if parts:
                # 從第一段萃取磁碟機代號，支援：
                #   本機磁碟 (D:)、Local Disk (C:)、(D:) 等各種語言標籤
                drive_match = re.search(r'\(([A-Za-z]:)\)', parts[0])
                if drive_match:
                    drive_letter = drive_match.group(1).upper()
                    # 將後續各段組成完整路徑
                    rel_parts = parts[1:]
                    if rel_parts:
                        full_path = drive_letter + '\\' + '\\'.join(rel_parts)
                        if os.path.isfile(full_path):
                            return full_path
                        # 即使檔案不存在（可能已被移動），也回傳推算的目錄讓使用者確認
                        # 只要目錄存在，就視為有效提示
                        parent = os.path.dirname(full_path)
                        if os.path.isdir(parent):
                            return full_path  # 目錄存在但檔案可能已更名

        # ── 方法二（備援）：舊格式 — 以 '_' 拆分並窮舉組合搜尋 ──────────
        import itertools, string

        search_roots: list[str] = [f"{d}:\\" for d in string.ascii_uppercase
                                   if os.path.exists(f"{d}:\\")]
        home = os.path.expanduser('~')
        for subdir in ('Documents', 'Desktop', 'Pictures', 'Downloads',
                       '圖片', '桌面', '文件'):
            p = os.path.join(home, subdir)
            if os.path.isdir(p):
                search_roots.append(p)

        parts2 = key.split('_')
        n = min(len(parts2) - 1, 12)

        for combo in itertools.product([False, True], repeat=n):
            components: list[str] = []
            cur = parts2[0]
            for i, is_sep in enumerate(combo):
                if is_sep:
                    components.append(cur)
                    cur = parts2[i + 1]
                else:
                    cur = cur + '_' + parts2[i + 1]
            components.append(cur)
            rel = os.path.join(*components) if components else key

            for root in search_roots:
                full = os.path.join(root, rel)
                if os.path.isfile(full):
                    return full

        return None


    def _open_file_directory(self, fname: str):
        """嘗試找出對應的真實檔案路徑，並在檔案總管中開啟其目錄。"""
        import threading

        self.var_status.set(_tr('msg.find_position', file=fname))
        self.root.update_idletasks()

        def _search():
            found = self._find_file_path(fname)
            self.root.after(0, lambda: _on_result(found))

        def _on_result(found: str | None):
            if found:
                # 用 explorer /select 選中並定位該檔案
                try:
                    import subprocess
                    subprocess.Popen(['explorer', '/select,', os.path.normpath(found)])
                    self.var_status.set(_tr('msg.opened_dir', dir=os.path.dirname(found)))
                except Exception as e:
                    self.var_status.set(_tr('msg.open_dir_failed', err=e))
            else:
                # 找不到時讓使用者手動定位
                self.var_status.set(_tr('msg.file_not_found_manual', file=fname))
                path = filedialog.askopenfilename(
                    title=f'找不到「{fname}」— 請手動選取該檔案',
                    filetypes=[('SAI2 & 圖片檔', '*.sai2 *.sai *.psd *.psb *.png *.jpg *.tga *.bmp'),
                               ('所有檔案', '*.*')]
                )
                if path:
                    try:
                        import subprocess
                        subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
                        self.var_status.set(_tr('msg.opened_dir', dir=os.path.dirname(path)))
                    except Exception:
                        os.startfile(os.path.dirname(os.path.abspath(path)))

        threading.Thread(target=_search, daemon=True).start()

    def _open_settings(self):
        SettingsDialog(self.root, self._settings, self._apply_settings)

    def _apply_settings(self, new_settings: dict):
        self._settings = new_settings
        _save_settings(new_settings)

        # 更新語言
        lang_code = new_settings.get('language', 'zh_tw')
        set_language(lang_code)

        # 更新配色
        _load_theme_colors(new_settings)

        # 更新追蹤器設定
        idle_to = float(new_settings.get('idle_timeout', 10.0))
        self.tracker.idle_timeout = idle_to
        self.timelapse_recorder.idle_timeout = idle_to

        # 更新資料路徑（需重啟追蹤器）
        new_path = new_settings.get('data_path', _DEFAULT_DATA)
        if new_path != self.tracker.data_path:
            self.tracker.stop()
            self.tracker = DrawTracker(data_path=new_path, idle_timeout=idle_to)
            self.tracker.start()

        # 更新縮時錄影設定
        self.timelapse_recorder.output_dir = new_settings.get('timelapse_output_dir', os.path.join(_APP_DIR, 'videos'))
        self.timelapse_recorder.fps = int(new_settings.get('timelapse_fps', 30))
        self.timelapse_recorder.quality_preset = new_settings.get('timelapse_quality', 'standard')

        # 重新設定全域快捷鍵
        self._setup_system_hotkey()

        # 重新建立 UI 畫面以套用配色
        self._recreate_ui()

        self.var_status.set(_tr('dialog.settings.updated'))

    def _apply_topmost(self):
        # 精簡模式下強制開啟置頂，常規模式則遵循按鈕狀態
        on_top = True if getattr(self, '_is_mini', False) else self._on_top.get()
        self.root.wm_attributes('-topmost', on_top)
        self._settings['always_on_top'] = self._on_top.get()
        _save_settings(self._settings)

    # ════════════════════════════════════════════════════════════════════════
    # 精簡模式 / 拖曳與熱鍵功能
    # ════════════════════════════════════════════════════════════════════════

    def _make_draggable(self, widget):
        widget.bind("<Button-1>", self._on_drag_start)
        widget.bind("<B1-Motion>", self._on_drag_motion)

    def _on_drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag_motion(self, event):
        x = self.root.winfo_x() + (event.x - self._drag_x)
        y = self.root.winfo_y() + (event.y - self._drag_y)
        self.root.geometry(f"+{x}+{y}")

    def toggle_mini_mode(self):
        self._is_mini = not getattr(self, '_is_mini', False)
        if self._is_mini:
            # 儲存常規模式的視窗大小與位置
            self._normal_geometry = self.root.geometry()
            
            # 隱藏常規 UI
            self.main_container.pack_forget()
            
            # 顯示精簡 UI
            self.mini_frame.pack(fill='both', expand=True)
            
            # 隱藏標題列邊框
            self.root.overrideredirect(True)
            
            # 調整為精簡模式尺寸，根據螢幕解析度動態計算
            parts = self._normal_geometry.split('+')
            x = parts[1] if len(parts) > 1 else "100"
            y = parts[2] if len(parts) > 2 else "100"
            
            # 根據螢幕寬度計算精簡模式寬度
            screen_width = self.root.winfo_screenwidth()
            if screen_width >= 3840:  # 4K
                mini_width = 400
            elif screen_width >= 2560:  # 2K
                mini_width = 350
            else:  # 較低解析度
                mini_width = 300
            
            self.root.geometry(f"{mini_width}x36+{x}+{y}")
            
            # 關閉縮圖生成，節省 CPU
            self.timelapse_recorder.needs_thumbnail = False
        else:
            # 隱藏精簡 UI
            self.mini_frame.pack_forget()
            
            # 顯示常規 UI
            self.main_container.pack(fill='both', expand=True)
            
            # 恢復標題列邊框
            self.root.overrideredirect(False)
            
            # 恢復常規尺寸
            self.root.geometry(self._normal_geometry)
            
            # 開啟縮圖生成
            self.timelapse_recorder.needs_thumbnail = True
            
        # 重新套用置頂設定
        self._apply_topmost()

    def _setup_system_hotkey(self):
        """設定系統層級（全域）快速鍵"""
        import threading
        
        self._stop_hotkey_thread()
        
        self._hotkey_running = True
        self._hotkey_thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self._hotkey_thread.start()

    def _stop_hotkey_thread(self):
        self._hotkey_running = False
        if hasattr(self, '_hotkey_thread_id') and self._hotkey_thread_id:
            import ctypes
            # 發送 WM_QUIT (0x0012) 訊息到熱鍵執行緒來喚醒 GetMessageW
            ctypes.windll.user32.PostThreadMessageW(self._hotkey_thread_id, 0x0012, 0, 0)
            self._hotkey_thread_id = None

    def _parse_key_to_vk(self, key_str: str) -> int:
        key_str = key_str.upper()
        if len(key_str) >= 2 and key_str.startswith('F'):
            try:
                num = int(key_str[1:])
                if 1 <= num <= 12:
                    return 0x6F + num
            except ValueError:
                pass
        if len(key_str) == 1 and 'A' <= key_str <= 'Z':
            return ord(key_str)
        if len(key_str) == 1 and '0' <= key_str <= '9':
            return ord(key_str)
        if key_str == 'SPACE':
            return 0x20
        return 0

    def _hotkey_loop(self):
        import ctypes
        from ctypes import wintypes
        
        MINI_HOTKEY_ID = 1234
        RECORD_HOTKEY_ID = 5678
        
        # 註冊 Ctrl+Alt+T (精簡模式)
        ctypes.windll.user32.RegisterHotKey(None, MINI_HOTKEY_ID, 0x0003, 0x54)
        
        # 解析並註冊錄影熱鍵
        rec_key = self._settings.get('hotkey_record_key', 'F10')
        rec_ctrl = self._settings.get('hotkey_record_ctrl', False)
        rec_alt = self._settings.get('hotkey_record_alt', False)
        rec_shift = self._settings.get('hotkey_record_shift', False)
        
        vk = self._parse_key_to_vk(rec_key)
        mods = 0
        if rec_alt:   mods |= 0x0001
        if rec_ctrl:  mods |= 0x0002
        if rec_shift: mods |= 0x0004
        
        rec_registered = False
        if vk > 0:
            res = ctypes.windll.user32.RegisterHotKey(None, RECORD_HOTKEY_ID, mods, vk)
            if res:
                rec_registered = True
            else:
                self.root.after(0, lambda: self.var_status.set(f"⚠️ 全域快捷鍵 {rec_key} 註冊失敗，可能已被佔用"))
        
        self._hotkey_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        
        try:
            msg = wintypes.MSG()
            while self._hotkey_running and ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    if msg.wParam == MINI_HOTKEY_ID:
                        self.root.after(0, self.toggle_mini_mode)
                    elif msg.wParam == RECORD_HOTKEY_ID:
                        self.root.after(0, self._toggle_record_from_hotkey)
                elif msg.message == 0x0012: # WM_QUIT
                    break
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            pass
        finally:
            ctypes.windll.user32.UnregisterHotKey(None, MINI_HOTKEY_ID)
            if rec_registered:
                ctypes.windll.user32.UnregisterHotKey(None, RECORD_HOTKEY_ID)

    def _toggle_record_from_hotkey(self):
        enabled = not self.timelapse_recorder.enabled
        self.var_tl_enabled.set(enabled)
        self._on_tl_toggle()
        status_msg = "🔴 已開始縮時錄影 (熱鍵)" if enabled else "⏸️ 已暫停縮時錄影 (熱鍵)"
        self.var_status.set(status_msg)

    # ── 關閉 ───────────────────────────────────────────────────────────────

    def _start_close_countdown(self):
        """SAI2 關閉後顯示倒數通知視窗，10 秒後自動關閉計時器。"""
        top = tk.Toplevel(self.root)
        top.title(_tr('dialog.sai_closed.title'))
        top.configure(bg=CARD)
        top.resizable(False, False)
        top.attributes('-topmost', True)
        
        # 根據螢幕解析度動態計算對話框大小
        sw = top.winfo_screenwidth()
        if sw >= 3840:  # 4K
            dialog_width = 430  # 360 * 1.2
            dialog_height = 190  # 160 * 1.2
        elif sw >= 2560:  # 2K
            dialog_width = 390  # 360 * 1.083
            dialog_height = 175  # 160 * 1.094
        else:
            dialog_width = 360
            dialog_height = 160
        
        top.geometry(f'{dialog_width}x{dialog_height}')
        top.update_idletasks()
        sh = top.winfo_screenheight()
        x  = (sw - dialog_width) // 2
        y  = (sh - dialog_height) // 2
        top.geometry(f'{dialog_width}x{dialog_height}+{x}+{y}')
        _apply_titlebar_theme(top)


        tk.Label(top, text=_tr('dialog.sai_closed.header'), font=FH,
                 fg=GREEN, bg=CARD).pack(pady=(18, 4))
        tk.Label(top, text=_tr('dialog.sai_closed.saved'), font=FB,
                 fg=TEXT, bg=CARD).pack()

        var_cd = tk.StringVar(value='10 秒後自動關閉…')
        lbl_cd = tk.Label(top, textvariable=var_cd, font=FS,
                          fg=TEXTD, bg=CARD)
        lbl_cd.pack(pady=(8, 4))

        _btn(top, _tr('dialog.sai_closed.close_btn'), ACCENT, ACCH,
             lambda: self._do_close(top), font=FB, pady=6, width=14).pack(pady=4)

        def _countdown(n=10):
            if n <= 0 or self.root is None:
                self._do_close(top)
                return
            var_cd.set(_tr('dialog.sai_closed.auto_close_n', sec=n))
            top.after(1000, lambda: _countdown(n - 1))

        _countdown()

    def _on_tl_toggle(self):
        enabled = self.var_tl_enabled.get()
        self.timelapse_recorder.enabled = enabled
        self._settings['timelapse_enabled'] = enabled
        _save_settings(self._settings)
        
        # 即時切換狀態
        self.timelapse_recorder.switch_file(self.tracker._cur_file)
        self._update_mini_buttons()

    def _on_tl_mult_change(self, _=None):
        mult_str = self.var_tl_mult.get()
        self.timelapse_recorder.multiplier = self._parse_multiplier(mult_str)
        self._settings['timelapse_multiplier_str'] = mult_str
        _save_settings(self._settings)

    def _on_tl_target_change(self, _=None):
        target_str = self.var_tl_target.get()
        self.timelapse_recorder.target_mode = self._parse_target(target_str)
        self._settings['timelapse_target_str'] = target_str
        _save_settings(self._settings)

    def _do_close(self, top=None):
        """儲存並關閉主視窗。"""
        try:
            if top and top.winfo_exists():
                top.destroy()
        except Exception:
            pass
        self._on_close()

    def _on_close(self):
        self._closing = True
        self.tracker.stop()
        self.timelapse_recorder.stop()
        
        # 檢查是否有縮時背景編碼程序在執行
        active_threads = [t for t in self.timelapse_recorder.export_threads if t.is_alive()]
        
        if active_threads:
            self._show_wait_export_dialog(active_threads)
        else:
            self.root.destroy()

    def _cb_export_progress(self, pct, msg):
        self.root.after(0, lambda: self._update_export_progress(pct, msg))

    def _update_export_progress(self, pct, msg):
        # 1. 顯示並更新主介面進度條
        try:
            if not self.pb_export.winfo_manager():
                self.pb_export.pack(fill='x', pady=(6, 0))
            self.pb_export['value'] = pct
        except Exception:
            pass
        self.var_status.set(msg)
        
        # 2. 如果關閉視窗的進度條對話框存在，也同步更新
        if hasattr(self, '_export_dialog_pb') and self._export_dialog_pb.winfo_exists():
            try:
                self._export_dialog_pb['value'] = pct
                if hasattr(self, '_export_dialog_status'):
                    self._export_dialog_status.set(msg)
            except Exception:
                pass
                
        # 3. 匯出完成 (100%) 或失敗時，延遲 3 秒隱藏進度條
        if pct >= 100 or '❌' in msg or '✅' in msg:
            self.root.after(3000, self._hide_export_progress)

    def _hide_export_progress(self):
        try:
            self.pb_export.pack_forget()
        except Exception:
            pass

    def _toggle_record_from_mini(self):
        enabled = not self.var_tl_enabled.get()
        self.var_tl_enabled.set(enabled)
        self._on_tl_toggle()

    def _update_mini_buttons(self):
        try:
            if not hasattr(self, 'btn_mini_record') or not self.btn_mini_record.winfo_exists():
                return
            enabled = self.timelapse_recorder.enabled
            is_active = self.timelapse_recorder.is_actively_recording
            if enabled:
                if is_active:
                    self.btn_mini_record.config(text='🔴 錄製中', fg=RED)
                else:
                    self.btn_mini_record.config(text=_tr('ui.mini.record_waiting'), fg=YELLOW)
            else:
                self.btn_mini_record.config(text='⏸️ 錄影關', fg=TEXTD)
        except Exception:
            pass

    def _show_wait_export_dialog(self, threads):
        top = tk.Toplevel(self.root)
        top.title('正在匯出縮時影片')
        top.configure(bg=CARD)
        top.resizable(False, False)
        top.grab_set()
        top.attributes('-topmost', True)
        top.geometry('360x180')
        top.update_idletasks()
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        x  = (sw - 360) // 2
        y  = (sh - 180) // 2
        top.geometry(f'360x180+{x}+{y}')
        _apply_titlebar_theme(top)


        tk.Label(top, text='🎬 正在背景合成縮時影片，請勿關閉...', font=FH, fg=ACCENT, bg=CARD).pack(pady=(16, 6))
        
        self._export_dialog_status = tk.StringVar(value='準備匯出中...')
        tk.Label(top, textvariable=self._export_dialog_status, font=FB, fg=TEXT, bg=CARD, wraplength=320).pack(pady=2)
        
        self._export_dialog_pb = ttk.Progressbar(top, orient='horizontal', mode='determinate', length=300, style='Horizontal.TProgressbar')
        self._export_dialog_pb.pack(pady=10)
        
        def _check():
            still_alive = [t for t in threads if t.is_alive()]
            if not still_alive:
                if hasattr(self, '_export_dialog_pb'):
                    delattr(self, '_export_dialog_pb')
                if hasattr(self, '_export_dialog_status'):
                    delattr(self, '_export_dialog_status')
                top.destroy()
                self.root.destroy()
                return
            top.after(500, _check)
            
        _check()

    def _parse_multiplier(self, mult_str: str) -> int:
        import re
        m = re.match(r'^(\d+)x', mult_str)
        if m:
            return int(m.group(1))
        return 5

    def _parse_target(self, target_str: str) -> str:
        if target_str == 'canvas' or '畫布' in target_str:
            return 'canvas'
        elif target_str == 'window' or '視窗' in target_str or 'window' in target_str.lower():
            return 'window'
        return 'screen'

    def _cb_tl_status(self, msg: str):
        self.root.after(0, lambda: self.var_tl_status.set(msg))

    def _cb_tl_frame(self, frame_count: int, thumb: Image.Image | None, msg: str):
        def _update():
            self.var_tl_frames.set(_tr('msg.frames_count', count=frame_count))
            dur = self.timelapse_recorder.total_recorded_duration
            mult = self.timelapse_recorder.multiplier
            fps = self.timelapse_recorder.fps
            if mult > 0:
                est_sec = dur / mult
                self.var_tl_vidlen.set(f'{fmt_seconds(est_sec)} (@ {fps}fps)')
            else:
                self.var_tl_vidlen.set(f'--:-- (@ {fps}fps)')
            
            if msg:
                self.var_tl_status.set(_tr('msg.recording_with_msg', msg=msg))
            else:
                self.var_tl_status.set(_tr('msg.recording_dots'))
                
            if thumb:
                try:
                    photo = ImageTk.PhotoImage(thumb)
                    self.canvas_tl.delete('all')
                    self.canvas_tl.create_image(80, 45, image=photo)
                    self._canvas_tl_img_ref = photo
                except Exception:
                    pass
        self.root.after(0, _update)

    def _switch_tab(self, tab: str):
        if tab == 'tracker':
            self.tab_tracker_lbl.config(fg=TEXT)
            self.tab_tracker_indicator.config(bg=ACCENT)
            self.tab_stats_lbl.config(fg=TEXTD)
            self.tab_stats_indicator.config(bg=BG)
            
            self.stats_view.pack_forget()
            self.tracker_view.pack(fill='both', expand=True)
        else:
            self.tab_tracker_lbl.config(fg=TEXTD)
            self.tab_tracker_indicator.config(bg=BG)
            self.tab_stats_lbl.config(fg=TEXT)
            self.tab_stats_indicator.config(bg=ACCENT)
            
            self.tracker_view.pack_forget()
            self.stats_view.pack(fill='both', expand=True)
            self._refresh_stats_chart()

    def _build_stats_view(self):
        self.subtab_frame = tk.Frame(self.stats_view, bg=BG)
        self.subtab_frame.pack(fill='x', padx=14, pady=(10, 6))
        
        self._active_stats_tab = '週'
        self.stats_tabs = {}
        tab_names = ['週', '月', '三月', '六月', '年', '至今']
        
        for name in tab_names:
            btn = _btn(self.subtab_frame, name, CARD2, ACCENT, lambda n=name: self._select_stats_tab(n), font=FS)
            btn.pack(side='left', padx=(0, 4), expand=True, fill='x')
            self.stats_tabs[name] = btn
            
        self._update_stats_tab_ui()
        
        self.chart_card = _card(self.stats_view)
        self.chart_card.pack(fill='both', expand=True, padx=14, pady=6)
        
        self.chart_canvas = tk.Canvas(self.chart_card, bg=CARD, highlightthickness=0)
        self.chart_canvas.pack(fill='both', expand=True, padx=4, pady=4)
        
        self.chart_canvas.bind('<Configure>', lambda _: self._refresh_stats_chart())
        self.chart_canvas.bind('<Motion>', self._on_chart_mouse_move)
        self.chart_canvas.bind('<Leave>', self._on_chart_mouse_leave)
        
        self.summary_card = _card(self.stats_view)
        self.summary_card.pack(fill='x', padx=14, pady=(6, 14))
        
        self.lbl_sum_total = tk.Label(self.summary_card, text='總繪圖時間：--', font=FB, fg=TEXT, bg=CARD)
        self.lbl_sum_total.pack(anchor='w', pady=2)
        
        self.lbl_sum_avg = tk.Label(self.summary_card, text='每日平均：--', font=FB, fg=TEXTD, bg=CARD)
        self.lbl_sum_avg.pack(anchor='w', pady=2)
        
        self.lbl_sum_peak = tk.Label(self.summary_card, text='單日最高：--', font=FB, fg=TEXTD, bg=CARD)
        self.lbl_sum_peak.pack(anchor='w', pady=2)

    def _select_stats_tab(self, name: str):
        self._active_stats_tab = name
        self._update_stats_tab_ui()
        self._refresh_stats_chart()

    def _update_stats_tab_ui(self):
        for name, btn in self.stats_tabs.items():
            if name == self._active_stats_tab:
                btn.config(bg=ACCENT, fg='white', activebackground=ACCH, activeforeground='white')
            else:
                inactive_fg = 'white' if _is_dark_color(CARD2) else TEXT
                btn.config(bg=CARD2, fg=inactive_fg, activebackground=ACCENT, activeforeground='white')

    def _get_chart_data(self):
        from datetime import datetime, timedelta
        raw_history = self.tracker._persist.get('daily_history', {})
        history = {}
        for k, v in raw_history.items():
            try:
                dt = datetime.strptime(k, '%Y-%m-%d').date()
                history[dt] = float(v)
            except Exception:
                pass
                
        today = datetime.now().date()
        tab = self._active_stats_tab
        bars = []
        
        if tab == '週':
            for i in range(6, -1, -1):
                d = today - timedelta(days=i)
                val = history.get(d, 0.0)
                lbl = d.strftime('%m/%d')
                tt = _tr('ui.stats.tooltip_day', date=d.strftime('%Y-%m-%d'), duration=fmt_seconds(val))
                bars.append((lbl, tt, val, d))
        elif tab == '月':
            for i in range(29, -1, -1):
                d = today - timedelta(days=i)
                val = history.get(d, 0.0)
                lbl = d.strftime('%m/%d') if i % 5 == 0 or i == 0 else ''
                tt = _tr('ui.stats.tooltip_day', date=d.strftime('%Y-%m-%d'), duration=fmt_seconds(val))
                bars.append((lbl, tt, val, d))
        elif tab == '三月':
            for i in range(89, -1, -1):
                d = today - timedelta(days=i)
                val = history.get(d, 0.0)
                lbl = d.strftime('%m/%d') if i % 15 == 0 or i == 0 else ''
                tt = _tr('ui.stats.tooltip_day', date=d.strftime('%Y-%m-%d'), duration=fmt_seconds(val))
                bars.append((lbl, tt, val, d))
        elif tab == '六月':
            for i in range(25, -1, -1):
                end_d = today - timedelta(days=i * 7)
                start_d = end_d - timedelta(days=6)
                val = 0.0
                curr = start_d
                while curr <= end_d:
                    val += history.get(curr, 0.0)
                    curr += timedelta(days=1)
                lbl = start_d.strftime('%m/%d') if i % 4 == 0 or i == 0 else ''
                tt = _tr('ui.stats.tooltip_week', start=start_d.strftime('%m/%d'), end=end_d.strftime('%m/%d'), duration=fmt_seconds(val))
                bars.append((lbl, tt, val, (start_d, end_d)))
        elif tab == '年':
            for i in range(51, -1, -1):
                end_d = today - timedelta(days=i * 7)
                start_d = end_d - timedelta(days=6)
                val = 0.0
                curr = start_d
                while curr <= end_d:
                    val += history.get(curr, 0.0)
                    curr += timedelta(days=1)
                lbl = start_d.strftime('%m/%d') if i % 8 == 0 or i == 0 else ''
                tt = _tr('ui.stats.tooltip_week', start=start_d.strftime('%Y/%m/%d'), end=end_d.strftime('%m/%d'), duration=fmt_seconds(val))
                bars.append((lbl, tt, val, (start_d, end_d)))
        elif tab == '至今':
            if not history:
                for i in range(5, -1, -1):
                    d = today - timedelta(days=i * 30)
                    lbl = d.strftime('%Y/%m')
                    tt = _tr('ui.stats.tooltip_month_empty', lbl=lbl)
                    bars.append((lbl, tt, 0.0, lbl))
            else:
                min_date = min(history.keys())
                curr_y, curr_m = min_date.year, min_date.month
                end_y, end_m = today.year, today.month
                months = []
                y, m = curr_y, curr_m
                while (y < end_y) or (y == end_y and m <= end_m):
                    months.append((y, m))
                    m += 1
                    if m > 12:
                        m = 1
                        y += 1
                for ym in months:
                    y, m = ym
                    val = 0.0
                    for d, secs in history.items():
                        if d.year == y and d.month == m:
                            val += secs
                    lbl = f"{y}/{m:02d}"
                    tt = _tr('ui.stats.tooltip_month', year=y, month=m, duration=fmt_seconds(val))
                    bars.append((lbl, tt, val, ym))
        return bars

    def _refresh_stats_chart(self):
        canvas = self.chart_canvas
        canvas.delete('all')
        self._chart_bar_rects = []
        self._hover_chart_key = None
        
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        
        if width <= 1 or height <= 1:
            return
            
        bars = self._get_chart_data()
        self._update_summary_card(bars)
        
        if not bars:
            canvas.create_text(width / 2, height / 2, text='目前尚無任何繪圖記錄資料', fill=TEXTD, font=FH)
            return
            
        left_margin = 45
        right_margin = 15
        top_margin = 25
        bottom_margin = 30
        
        plot_w = width - left_margin - right_margin
        plot_h = height - top_margin - bottom_margin
        
        max_val = max(b[2] for b in bars)
        y_max = max(max_val, 3600.0)
        
        grid_count = 4
        for i in range(grid_count + 1):
            val = y_max * (i / grid_count)
            y = top_margin + plot_h * (1.0 - i / grid_count)
            if i > 0:
                canvas.create_line(left_margin, y, width - right_margin, y, fill=BORDER, dash=(2, 2))
            lbl = self._fmt_y_label(val)
            canvas.create_text(left_margin - 8, y, text=lbl, font=FS, fill=TEXTD, anchor='e')
            
        canvas.create_line(left_margin, top_margin, left_margin, height - bottom_margin, fill=BORDER)
        canvas.create_line(left_margin, height - bottom_margin, width - right_margin, height - bottom_margin, fill=BORDER)
        
        n = len(bars)
        bar_w = plot_w / n
        gap = 1 if bar_w < 5 else (2 if bar_w < 10 else 4)
        
        for i, bar_data in enumerate(bars):
            lbl, tt, val, key = bar_data
            x1 = left_margin + i * bar_w + gap
            x2 = left_margin + (i + 1) * bar_w - gap
            y_val = top_margin + plot_h * (1.0 - val / y_max)
            y_bottom = height - bottom_margin
            
            if val > 0:
                item_id = canvas.create_rectangle(x1, y_val, x2, y_bottom, fill=ACCENT, outline='', width=0)
            else:
                item_id = canvas.create_rectangle(x1, y_bottom - 1, x2, y_bottom, fill=BORDER, outline='', width=0)
                
            self._chart_bar_rects.append((x1, y_val, x2, y_bottom, bar_data, item_id))
            if lbl:
                canvas.create_text((x1 + x2) / 2, height - bottom_margin + 10, text=lbl, font=FS, fill=TEXTD, anchor='n')

    def _fmt_y_label(self, secs: float) -> str:
        h = secs / 3600.0
        if h >= 1.0:
            if h == int(h):
                return f"{int(h)}h"
            return f"{h:.1f}h"
        m = secs / 60.0
        if m >= 1.0:
            return f"{int(m)}m"
        return f"{int(secs)}s"

    def _update_summary_card(self, bars):
        if not bars:
            self.lbl_sum_total.config(text='總繪圖時間：00:00')
            self.lbl_sum_avg.config(text='每日平均：00:00')
            self.lbl_sum_peak.config(text='單日最高：--')
            return
            
        tab = self._active_stats_tab
        total_secs = sum(b[2] for b in bars)
        
        if tab in ('週', '月', '三月'):
            avg_secs = total_secs / len(bars)
        elif tab in ('六月', '年'):
            avg_secs = total_secs / (len(bars) * 7)
        else:
            raw_history = self.tracker._persist.get('daily_history', {})
            if raw_history:
                try:
                    from datetime import datetime
                    dates = [datetime.strptime(d, '%Y-%m-%d').date() for d in raw_history.keys()]
                    day_span = (max(dates) - min(dates)).days + 1
                    day_span = max(1, day_span)
                except Exception:
                    day_span = len(bars) * 30
                avg_secs = total_secs / day_span
            else:
                avg_secs = 0.0
                
        from datetime import datetime, timedelta
        raw_history = self.tracker._persist.get('daily_history', {})
        today = datetime.now().date()
        filtered_daily = {}
        
        for k, v in raw_history.items():
            try:
                d = datetime.strptime(k, '%Y-%m-%d').date()
                val = float(v)
                in_range = False
                if tab == '週':
                    in_range = (today - d).days < 7
                elif tab == '月':
                    in_range = (today - d).days < 30
                elif tab == '三月':
                    in_range = (today - d).days < 90
                elif tab == '六月':
                    in_range = (today - d).days < 182
                elif tab == '年':
                    in_range = (today - d).days < 365
                elif tab == '至今':
                    in_range = True
                if in_range:
                    filtered_daily[d] = val
            except Exception:
                pass
                
        if filtered_daily:
            peak_date = max(filtered_daily, key=filtered_daily.get)
            peak_secs = filtered_daily[peak_date]
            peak_str = f"{fmt_seconds(peak_secs)} ({peak_date.strftime('%m/%d')})"
        else:
            peak_str = '--'
            
        self.lbl_sum_total.config(text=f'總繪圖時間：{fmt_seconds(total_secs)}')
        self.lbl_sum_avg.config(text=f'每日平均：{fmt_seconds(avg_secs)}')
        self.lbl_sum_peak.config(text=f'單日最高：{peak_str}')

    def _on_chart_mouse_move(self, event):
        x, y = event.x, event.y
        found_bar = None
        for x1, y1, x2, y2, bar_data, item_id in getattr(self, '_chart_bar_rects', []):
            if x1 <= x <= x2:
                found_bar = (x1, y1, x2, y2, bar_data)
                break
                
        if found_bar:
            x1, y1, x2, y2, bar_data = found_bar
            lbl, tt, val, key = bar_data
            if getattr(self, '_hover_chart_key', None) != key:
                self._hover_chart_key = key
                self._draw_chart_tooltip(x, y, tt)
                self._highlight_bar(key)
        else:
            self._on_chart_mouse_leave()

    def _on_chart_mouse_leave(self, event=None):
        self._hover_chart_key = None
        self.chart_canvas.delete('tooltip')
        canvas = self.chart_canvas
        for x1, y1, x2, y2, bar_data, item_id in getattr(self, '_chart_bar_rects', []):
            canvas.itemconfig(item_id, fill=ACCENT)

    def _highlight_bar(self, key):
        canvas = self.chart_canvas
        for x1, y1, x2, y2, bar_data, item_id in getattr(self, '_chart_bar_rects', []):
            _, _, _, bar_key = bar_data
            if bar_key == key:
                canvas.itemconfig(item_id, fill=ACCH)
            else:
                canvas.itemconfig(item_id, fill=ACCENT)

    def _draw_chart_tooltip(self, x, y, text):
        canvas = self.chart_canvas
        canvas.delete('tooltip')
        
        t_id = canvas.create_text(0, 0, text=text, font=FS, fill=TEXT, justify='left', anchor='nw')
        bbox = canvas.bbox(t_id)
        canvas.delete(t_id)
        
        if not bbox:
            return
            
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        
        tx = x + 10
        ty = y - th - 15
        cw = canvas.winfo_width()
        
        if tx + tw + 10 > cw:
            tx = x - tw - 10
        if ty < 5:
            ty = y + 15
            
        pad = 6
        canvas.create_rectangle(tx - pad, ty - pad, tx + tw + pad, ty + th + pad, fill=CARD2, outline=ACCENT, width=1, tags='tooltip')
        canvas.create_text(tx, ty, text=text, font=FS, fill=TEXT, justify='left', anchor='nw', tags='tooltip')

    def _recreate_ui(self):
        # ── 暫停 _poll，整個重建流程都保持 _closing_temp=True ──
        self._closing_temp = True
        
        _setup_styles()
        
        # 銷毀現有容器（先處理 mini_frame 再處理 main_container）
        for attr in ('mini_frame', 'main_container'):
            try:
                w = getattr(self, attr, None)
                if w:
                    w.destroy()
            except Exception:
                pass
            
        self.root.configure(bg=BG)
        
        # 重建 UI（_closing_temp 仍為 True，確保沒有殘存的 _poll 干擾）
        self._build_ui()
        
        # 重建完成後套用 Combobox 顏色（需在建立 Combobox 之後呼叫才能覆蓋）
        _setup_combobox_colors(self.root)
        
        is_mini = getattr(self, '_is_mini', False)
        if is_mini:
            self.main_container.pack_forget()
            self.mini_frame.pack(fill='both', expand=True)
            self.root.overrideredirect(True)
        else:
            self.mini_frame.pack_forget()
            self.main_container.pack(fill='both', expand=True)
            self.root.overrideredirect(False)
            
        self._apply_topmost()
        _apply_titlebar_theme(self.root)
        
        # 恢復資料顯示
        state = self.tracker.get_state()
        self._refresh_tree(state.get('files', {}))
        self._refresh_stats_chart()
        
        # ── 一切就緒，解除暫停並重啟 _poll 循環 ──
        self._closing_temp = False
        self.root.after(200, self._poll)




# ─── 設定對話框 ───────────────────────────────────────────────────────────
class SettingsDialog(tk.Toplevel):

    def __init__(self, parent, settings: dict, callback):
        super().__init__(parent)
        self.title(_tr('dialog.settings.title'))
        self.configure(bg=CARD)
        self.resizable(False, False)
        self.grab_set()
        self._callback = callback
        self._settings = dict(settings)
        
        # 根據螢幕解析度動態計算設定對話框大小
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        
        # 計算適合當前解析度的對話框大小
        if sw >= 3840:  # 4K
            dialog_width = 780  # 650 * 1.2
            dialog_height = 600  # 500 * 1.2
        elif sw >= 2560:  # 2K
            dialog_width = 700  # 650 * 1.075
            dialog_height = 540  # 500 * 1.08
        else:  # 較低解析度
            dialog_width = 650
            dialog_height = 500
        
        self.geometry(f'{dialog_width}x{dialog_height}')
        self.update_idletasks()
        
        x = (sw - dialog_width) // 2
        y = (sh - dialog_height) // 2
        self.geometry(f'{dialog_width}x{dialog_height}+{x}+{y}')
        _apply_titlebar_theme(self)


        # ── 底部按鈕欄 ──
        btn_row = tk.Frame(self, bg=CARD)
        btn_row.pack(side='bottom', fill='x', pady=(10, 14))
        
        # 根據對話框寬度動態計算按鈕間距
        dialog_width = self.winfo_width() or 650
        if dialog_width >= 780:  # 4K
            button_padx = 280
        elif dialog_width >= 700:  # 2K
            button_padx = 240
        else:  # 原始大小
            button_padx = 200
        
        _btn(btn_row, _tr('dialog.settings.btn_apply'), ACCENT, ACCH, self._apply, font=FB, width=12).pack(side='left', padx=(button_padx, 10))
        _btn(btn_row, _tr('dialog.settings.btn_cancel'), CARD2, BORDER, self.destroy, font=FB, width=12).pack(side='left', padx=10)

        # ── 主佈局左右兩欄 ──
        left_col = tk.Frame(self, bg=CARD)
        left_col.pack(side='left', fill='both', expand=True, padx=(14, 7), pady=10)
        
        right_col = tk.Frame(self, bg=CARD)
        right_col.pack(side='right', fill='both', expand=True, padx=(7, 14), pady=10)
        
        # ── 1. 一般設定 (左欄) ──
        f_general = tk.LabelFrame(left_col, text=_tr('dialog.settings.grp_general'), font=FH, fg=ACCENT, bg=CARD, bd=1, relief='solid', padx=10, pady=8)
        f_general.pack(fill='x', pady=(0, 10))
        
        tk.Label(f_general, text=_tr('dialog.settings.idle_timeout'), font=FB, fg=TEXT, bg=CARD).grid(row=0, column=0, sticky='w', pady=4)
        self.var_idle = tk.StringVar(value=str(self._settings.get('idle_timeout', 10.0)))
        self.ent_idle = tk.Entry(f_general, textvariable=self.var_idle, font=FB, bg=CARD2, fg=TEXT, insertbackground=TEXT, relief='flat', width=8)
        self.ent_idle.grid(row=0, column=1, sticky='w', pady=4)
        
        tk.Label(f_general, text=_tr('dialog.settings.data_path'), font=FB, fg=TEXT, bg=CARD).grid(row=1, column=0, columnspan=2, sticky='w', pady=(6, 2))
        path_row = tk.Frame(f_general, bg=CARD)
        path_row.grid(row=2, column=0, columnspan=2, sticky='we')
        self.var_path = tk.StringVar(value=self._settings.get('data_path', _DEFAULT_DATA))
        self.ent_path = tk.Entry(path_row, textvariable=self.var_path, font=FS, bg=CARD2, fg=TEXT, insertbackground=TEXT, relief='flat', width=20)
        self.ent_path.pack(side='left', fill='x', expand=True, padx=(0, 6))
        _btn(path_row, _tr('dialog.settings.btn_browse'), CARD2, ACCH, self._choose_path, font=FS, pady=2).pack(side='right')

        # ── 語系選擇 (左欄 - 一般設定內第 3 行) ──
        tk.Label(f_general, text=_tr('dialog.settings.language'), font=FB, fg=TEXT, bg=CARD).grid(row=3, column=0, sticky='w', pady=6)
        self.langs_dict = get_available_languages()
        lang_codes = list(self.langs_dict.keys())
        lang_names = [self.langs_dict[c] for c in lang_codes]
        
        current_lang_code = self._settings.get('language', 'zh_tw')
        current_lang_name = self.langs_dict.get(current_lang_code, '繁體中文')
        
        self.var_lang_name = tk.StringVar(value=current_lang_name)
        self.combo_lang = ttk.Combobox(f_general, textvariable=self.var_lang_name, state='readonly', width=12, font=FS, values=lang_names)
        self.combo_lang.grid(row=3, column=1, sticky='w', pady=6)
        
        # ── 3. 縮時錄影 (左欄) ──
        f_tl = tk.LabelFrame(left_col, text=_tr('dialog.settings.grp_timelapse'), font=FH, fg=ACCENT, bg=CARD, bd=1, relief='solid', padx=10, pady=8)
        f_tl.pack(fill='x')
        
        tk.Label(f_tl, text=_tr('dialog.settings.video_dir'), font=FB, fg=TEXT, bg=CARD).grid(row=0, column=0, columnspan=2, sticky='w', pady=2)
        tl_row = tk.Frame(f_tl, bg=CARD)
        tl_row.grid(row=1, column=0, columnspan=2, sticky='we')
        self.var_tl_out = tk.StringVar(value=self._settings.get('timelapse_output_dir', os.path.join(_APP_DIR, 'videos')))
        self.ent_tl_out = tk.Entry(tl_row, textvariable=self.var_tl_out, font=FS, bg=CARD2, fg=TEXT, insertbackground=TEXT, relief='flat', width=20)
        self.ent_tl_out.pack(side='left', fill='x', expand=True, padx=(0, 6))
        _btn(tl_row, _tr('dialog.settings.btn_browse'), CARD2, ACCH, self._choose_tl_out, font=FS, pady=2).pack(side='right')
        
        tk.Label(f_tl, text=_tr('dialog.settings.video_fps'), font=FB, fg=TEXT, bg=CARD).grid(row=2, column=0, sticky='w', pady=6)
        self.var_tl_fps = tk.StringVar(value=str(self._settings.get('timelapse_fps', 30)))
        self.combo_tl_fps = ttk.Combobox(f_tl, textvariable=self.var_tl_fps, state='readonly', width=10, font=FS, values=['12', '16', '24', '30', '60'])
        self.combo_tl_fps.grid(row=2, column=1, sticky='w', pady=6)

        # ── 影片畫質設定 (左欄 - 縮時錄影設定內第 3 行) ──
        tk.Label(f_tl, text=_tr('dialog.settings.video_quality'), font=FB, fg=TEXT, bg=CARD).grid(row=3, column=0, sticky='w', pady=6)
        self.quality_map = {
            _tr('dialog.settings.video_quality.compact'): 'compact',
            _tr('dialog.settings.video_quality.standard'): 'standard',
            _tr('dialog.settings.video_quality.high'): 'high',
            _tr('dialog.settings.video_quality.lossless'): 'lossless'
        }
        self.quality_rev_map = {v: k for k, v in self.quality_map.items()}
        current_q_code = self._settings.get('timelapse_quality', 'standard')
        current_q_name = self.quality_rev_map.get(current_q_code, _tr('dialog.settings.video_quality.standard'))
        
        self.var_q_name = tk.StringVar(value=current_q_name)
        self.combo_quality = ttk.Combobox(f_tl, textvariable=self.var_q_name, state='readonly', width=18, font=FS, values=list(self.quality_map.keys()))
        self.combo_quality.grid(row=3, column=1, sticky='w', pady=6)
        
        # ── 2. 主題配色 (右欄) ──
        f_theme = tk.LabelFrame(right_col, text=_tr('dialog.settings.grp_theme'), font=FH, fg=ACCENT, bg=CARD, bd=1, relief='solid', padx=10, pady=8)
        f_theme.pack(fill='x', pady=(0, 10))
        
        tk.Label(f_theme, text=_tr('dialog.settings.theme_mode'), font=FB, fg=TEXT, bg=CARD).grid(row=0, column=0, sticky='w', pady=4)
        
        # Localized theme mode mappings
        self.theme_mode_map = {
            'dark': _tr('theme.mode.dark'),
            'light': _tr('theme.mode.light')
        }
        self.theme_mode_rev = {v: k for k, v in self.theme_mode_map.items()}
        stored_mode = self._settings.get('theme_mode', 'dark')
        initial_mode_display = self.theme_mode_map.get(stored_mode, _tr('theme.mode.dark'))
        
        self.var_mode = tk.StringVar(value=initial_mode_display)
        self.combo_mode = ttk.Combobox(f_theme, textvariable=self.var_mode, state='readonly', width=12, font=FS, values=list(self.theme_mode_map.values()))
        self.combo_mode.grid(row=0, column=1, sticky='w', pady=4)
        
        tk.Label(f_theme, text=_tr('dialog.settings.theme_color'), font=FB, fg=TEXT, bg=CARD).grid(row=1, column=0, sticky='w', pady=4)
        preset_frame = tk.Frame(f_theme, bg=CARD)
        preset_frame.grid(row=1, column=1, sticky='w', pady=4)
        
        # Localized theme presets name mapping
        self.preset_display_map = {
            '羅蘭紫': _tr('theme.preset.purple'),
            '天空藍': _tr('theme.preset.blue'),
            '海洋青': _tr('theme.preset.cyan'),
            '極光綠': _tr('theme.preset.teal'),
            '森林綠': _tr('theme.preset.green'),
            '萊姆黃': _tr('theme.preset.lime'),
            '向日葵': _tr('theme.preset.yellow'),
            '琥珀金': _tr('theme.preset.amber'),
            '活力橙': _tr('theme.preset.orange'),
            '火焰紅': _tr('theme.preset.red'),
            '霓虹粉': _tr('theme.preset.pink'),
            '石板灰': _tr('theme.preset.gray'),
            '自訂': _tr('theme.preset.custom')
        }
        self.preset_display_rev = {v: k for k, v in self.preset_display_map.items()}
        
        stored_preset = self._settings.get('theme_accent_preset', '羅蘭紫')
        initial_preset_display = self.preset_display_map.get(stored_preset, _tr('theme.preset.purple'))
        
        self.var_preset = tk.StringVar(value=initial_preset_display)
        presets = list(self.preset_display_map.values())
        self.combo_preset = ttk.Combobox(preset_frame, textvariable=self.var_preset, state='readonly', width=12, font=FS, values=presets)
        self.combo_preset.pack(side='left', padx=(0, 6))
        self.combo_preset.bind('<<ComboboxSelected>>', self._on_preset_change)
        
        # 配色預覽小色塊
        self.preset_preview = tk.Frame(preset_frame, width=16, height=16, highlightthickness=1, highlightbackground=BORDER)
        self.preset_preview.pack(side='left')
        self.preset_preview.pack_propagate(False)
        
        tk.Label(f_theme, text=_tr('dialog.settings.custom_hex'), font=FB, fg=TEXT, bg=CARD).grid(row=2, column=0, sticky='w', pady=4)
        custom_frame = tk.Frame(f_theme, bg=CARD)
        custom_frame.grid(row=2, column=1, sticky='w', pady=4)
        self.var_custom_color = tk.StringVar(value=self._settings.get('theme_accent_custom', '#7c3aed'))
        self.ent_custom_color = tk.Entry(custom_frame, textvariable=self.var_custom_color, font=FB, bg=CARD2, fg=TEXT, insertbackground=TEXT, relief='flat', width=10)
        self.ent_custom_color.pack(side='left', padx=(0, 6))
        self.ent_custom_color.bind('<KeyRelease>', self._on_custom_color_keyup)
        
        # 自訂配色預覽小色塊
        self.custom_preview = tk.Frame(custom_frame, width=16, height=16, highlightthickness=1, highlightbackground=BORDER)
        self.custom_preview.pack(side='left')
        self.custom_preview.pack_propagate(False)
        
        # ── 4. 全域快速鍵 (右欄) ──
        f_hotkey = tk.LabelFrame(right_col, text=_tr('dialog.settings.grp_hotkey'), font=FH, fg=ACCENT, bg=CARD, bd=1, relief='solid', padx=10, pady=8)
        f_hotkey.pack(fill='x')
        
        mods_frame = tk.Frame(f_hotkey, bg=CARD)
        mods_frame.grid(row=0, column=0, columnspan=2, sticky='w', pady=2)
        
        self.var_ctrl = tk.BooleanVar(value=self._settings.get('hotkey_record_ctrl', False))
        self.chk_ctrl = tk.Checkbutton(mods_frame, text='Ctrl', variable=self.var_ctrl, font=FB, fg=TEXT, bg=CARD, selectcolor=CARD2, activebackground=CARD, activeforeground=TEXT, cursor='hand2')
        self.chk_ctrl.pack(side='left', padx=(0, 8))
        
        self.var_alt = tk.BooleanVar(value=self._settings.get('hotkey_record_alt', False))
        self.chk_alt = tk.Checkbutton(mods_frame, text='Alt', variable=self.var_alt, font=FB, fg=TEXT, bg=CARD, selectcolor=CARD2, activebackground=CARD, activeforeground=TEXT, cursor='hand2')
        self.chk_alt.pack(side='left', padx=(0, 8))
        
        self.var_shift = tk.BooleanVar(value=self._settings.get('hotkey_record_shift', False))
        self.chk_shift = tk.Checkbutton(mods_frame, text='Shift', variable=self.var_shift, font=FB, fg=TEXT, bg=CARD, selectcolor=CARD2, activebackground=CARD, activeforeground=TEXT, cursor='hand2')
        self.chk_shift.pack(side='left', padx=(0, 8))
        
        tk.Label(f_hotkey, text=_tr('dialog.settings.hotkey_key'), font=FB, fg=TEXT, bg=CARD).grid(row=1, column=0, sticky='w', pady=4)
        self.var_key = tk.StringVar(value=self._settings.get('hotkey_record_key', 'F10'))
        keys = [f'F{i}' for i in range(1, 13)] + [chr(i) for i in range(ord('A'), ord('Z') + 1)] + ['SPACE']
        self.combo_key = ttk.Combobox(f_hotkey, textvariable=self.var_key, state='readonly', width=10, font=FS, values=keys)
        self.combo_key.grid(row=1, column=1, sticky='w', pady=4)
        
        self._on_preset_change()
        self.wait_window()

    def _choose_path(self):
        p = filedialog.asksaveasfilename(
            defaultextension='.json',
            filetypes=[(_tr('filetype.all') if get_current_language() != 'zh_tw' else 'JSON 檔案', '*.json')],
            title=_tr('dialog.settings.data_path'))
        if p:
            self.var_path.set(p)

    def _choose_tl_out(self):
        p = filedialog.askdirectory(title=_tr('dialog.settings.video_dir'))
        if p:
            self.var_tl_out.set(os.path.normpath(p))

    def _on_preset_change(self, _=None):
        preset_display = self.var_preset.get()
        preset = self.preset_display_rev.get(preset_display, '羅蘭紫')
        if preset == '自訂':
            self.ent_custom_color.config(state='normal', bg=CARD2, fg=TEXT)
            self._update_custom_preview()
            self.preset_preview.config(bg=CARD)
        else:
            self.ent_custom_color.config(state='disabled', bg=CARD, fg=TEXTD)
            color = THEME_PRESETS.get(preset, '#7c3aed')
            self.preset_preview.config(bg=color)
            self.custom_preview.config(bg=CARD)

    def _on_custom_color_keyup(self, _=None):
        self._update_custom_preview()

    def _update_custom_preview(self):
        color = self.var_custom_color.get().strip()
        import re
        if re.match(r'^#[0-9a-fA-F]{6}$', color):
            self.custom_preview.config(bg=color)
        else:
            self.custom_preview.config(bg=CARD)

    def _apply(self):
        try:
            idle = float(self.var_idle.get())
            assert 0 <= idle <= 300
        except Exception:
            messagebox.showerror(_tr('msg.manual_save_failed'), _tr('dialog.settings.err_idle'), parent=self)
            return
            
        out_dir = self.var_tl_out.get().strip()
        if out_dir:
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception:
                messagebox.showerror(_tr('msg.manual_save_failed'), _tr('dialog.settings.err_video_dir'), parent=self)
                return
                
        preset_display = self.var_preset.get()
        preset = self.preset_display_rev.get(preset_display, '羅蘭紫')
        if preset == '自訂':
            custom_color = self.var_custom_color.get().strip()
            import re
            if not re.match(r'^#[0-9a-fA-F]{6}$', custom_color):
                messagebox.showerror(_tr('msg.manual_save_failed'), _tr('dialog.settings.err_custom_color'), parent=self)
                return
                
        self._settings['idle_timeout'] = idle
        self._settings['data_path']    = self.var_path.get()
        self._settings['timelapse_output_dir'] = out_dir
        self._settings['timelapse_fps'] = int(self.var_tl_fps.get())
        
        # Map theme mode display name back to machine key
        mode_display = self.var_mode.get()
        self._settings['theme_mode'] = self.theme_mode_rev.get(mode_display, 'dark')
        
        # Save accent preset machine key
        self._settings['theme_accent_preset'] = preset
        self._settings['theme_accent_custom'] = self.var_custom_color.get().strip()
        
        self._settings['hotkey_record_ctrl'] = self.var_ctrl.get()
        self._settings['hotkey_record_alt'] = self.var_alt.get()
        self._settings['hotkey_record_shift'] = self.var_shift.get()
        self._settings['hotkey_record_key'] = self.var_key.get()
        
        # Save Language code
        selected_lang_name = self.var_lang_name.get()
        lang_code = 'zh_tw'
        for code, name in self.langs_dict.items():
            if name == selected_lang_name:
                lang_code = code
                break
        self._settings['language'] = lang_code
        
        # Save video quality code
        selected_q_name = self.var_q_name.get()
        q_code = self.quality_map.get(selected_q_name, 'standard')
        self._settings['timelapse_quality'] = q_code
        
        callback = self._callback
        settings = self._settings
        self.destroy()
        callback(settings)



def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
