# -*- coding: utf-8 -*-
"""
brush_studio.py - SAI2 筆刷、紋理與材質製作工坊 (Brush & Texture Studio) 的介面
提供便利的畫布選區/剪貼簿一鍵製作 SAI2 筆刷工具、無縫紋理 (brushtex) 與紙張材質 (papertex)。
包含 3x3 平鋪即時預覽、動態自適應試畫畫布與參數數值持久記憶。
SAI2 設定檔讀寫、影像轉換與待寫入佇列在 core/brush_assets.py。
"""

from __future__ import annotations

import os
import time
import json
import math
import random
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageOps, ImageGrab

from core.i18n import _tr
from core.paths import APP_DIR as _APP_DIR
from core.brush_assets import (SAI2SettingsManager, BrushImageProcessor, PendingBrushQueue,
                               validate_asset_name, sai2_write_session)
from ui_kit import px, fit_window
from liquify_helper import read_image_from_clipboard


def is_text_input_widget(widget) -> bool:
    """事件來源是否為可輸入文字的元件（Entry / 可編輯 Combobox / Text / Spinbox）。
    綁在整個視窗上的單鍵快捷鍵（空白、方向鍵、Ctrl+V）遇到這類元件時應讓出，避免打字時誤觸。"""
    if not isinstance(widget, (tk.Entry, ttk.Entry, tk.Text, tk.Spinbox, ttk.Spinbox)):
        return False
    try:
        return str(widget.cget('state')) not in ('readonly', 'disabled')
    except Exception:
        return True

# ─── 色彩 / 樣式常數 ─────────────────────────────────────────────────────────
BG     = '#111111'
CARD   = '#1e1e1e'
CARD2  = '#282828'
CARD3  = '#333333'
ACCENT = '#7c3aed'
ACCH   = '#6d28d9'
TEXT   = '#f0f0f0'
TEXTD  = '#888888'
GREEN  = '#22c55e'
YELLOW = '#f59e0b'
RED    = '#ef4444'
BORDER = '#3a3a3a'

FT_TITLE = ('Microsoft JhengHei', 13, 'bold')
FT_HEAD  = ('Microsoft JhengHei', 11, 'bold')
FT_NORM  = ('Microsoft JhengHei', 9)
FT_BOLD  = ('Microsoft JhengHei', 9, 'bold')
FT_SMALL = ('Microsoft JhengHei', 8)


# ─── 參數持久化記憶管理 ────────────────────────────────────────────────────────


SETTINGS_FILE = os.path.join(_APP_DIR, 'brush_studio_settings.json')

class BrushStudioSettings:
    """負責儲存與還原筆刷工坊的各項調動數值，記憶使用者最後設定"""

    DEFAULT_SETTINGS = {
        'main_mode': 'scatter',
        'preview_view': 'single',
        'target_group': '',
        'size': 60,
        'spacing': 35,
        'scattering': 30,
        'angle_ctl': 0,
        'angle': 0,
        'angle_jitter': 20,
        'size_jitter': 30,
        'pen_pressure': True,
        'convert_mode': 'alpha',
        'autocrop': True,
        'seamless_mode': 'crossfade',
        'blend_margin': 25,
        'tex_res': 256,
        'contrast': 1.0,
        'brightness': 0.0,
        'invert': False,
        'create_texture_brush': True,
        'pad_bg_mode': 'dark',
    }

    @classmethod
    def load(cls) -> dict:
        d = dict(cls.DEFAULT_SETTINGS)
        if os.path.isfile(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    d.update(saved)
            except Exception as e:
                print(f"[BrushStudioSettings] Load warning: {e}")
        return d

    @classmethod
    def save(cls, settings: dict):
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[BrushStudioSettings] Save warning: {e}")


# ─── 強健多格式剪貼簿讀取 ──────────────────────────────────────────────────────

def read_clipboard_safely() -> Image.Image | None:
    """
    多重備援剪貼簿圖像讀取：
    1. 優先透過 Win32 讀取 CF_DIBV5 (32-bit RGBA，SAI2 複製時攜帶的透明度)
    2. 嘗試 PNG 剪貼簿格式
    3. 嘗試 ImageGrab.grabclipboard() 讀取常規點陣圖或截圖
    4. 支援檔案清單：若使用者在檔案總管按 Ctrl+C 複製圖檔，自動解析開啟該圖片
    """
    # 1. 嘗試 Win32 原生透明通道
    try:
        img = read_image_from_clipboard()
        if img is not None and isinstance(img, Image.Image):
            return img
    except Exception as e:
        print(f"[BrushStudio] Win32 clipboard failed: {e}")

    # 2. 嘗試 PIL ImageGrab
    try:
        grabbed = ImageGrab.grabclipboard()
        if isinstance(grabbed, Image.Image):
            return grabbed
        elif isinstance(grabbed, list):
            for item in grabbed:
                if isinstance(item, str) and os.path.isfile(item):
                    ext = os.path.splitext(item)[1].lower()
                    if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.gif', '.tif'):
                        try:
                            f_img = Image.open(item)
                            f_img.load()
                            return ImageOps.exif_transpose(f_img)
                        except Exception:
                            pass
    except Exception as e:
        print(f"[BrushStudio] ImageGrab failed: {e}")

    return None


# ─── 動態自適應試畫畫布 (Auto-resizing Scratchpad) ────────────────────────────

class ScratchpadCanvas(tk.Canvas):
    """
    供使用者用滑鼠/繪圖筆即時試畫塗抹筆刷與紋理效果的測試畫布。
    支援視窗縮放動態自適應，徹底解決框線內右側與下方無法繪製之問題。
    """

    def __init__(self, parent, width=320, height=280, **kwargs):
        super().__init__(parent, width=width, height=height, bg='#222222',
                         highlightthickness=1, highlightbackground=BORDER, **kwargs)
        self.w = max(10, width)
        self.h = max(10, height)

        self.brush_stamp_img: Image.Image | None = None
        self._stamp_cache: dict[int, Image.Image] = {}   # 尺寸 → 已縮放的印章，避免每個印章點都從 512px 重新縮放
        self.texture_img: Image.Image | None = None
        self.brush_type = 'scatter'
        self.brush_size = 50
        self.spacing = 25
        self.scattering = 0
        self.angle_ctl = 0
        self.angle = 0
        self.angle_jitter = 0
        self.size_jitter = 0
        self.ink_color = (240, 240, 240)
        self.bg_color = (34, 34, 34)

        self._buf_img = Image.new('RGB', (self.w, self.h), self.bg_color)
        self._buf_photo = None
        self._last_pt = None
        self._dist_accum = 0.0

        self.bind('<ButtonPress-1>', self._on_down)
        self.bind('<B1-Motion>', self._on_drag)
        self.bind('<ButtonRelease-1>', self._on_up)
        # 動態監聽畫布大小改變
        self.bind('<Configure>', self._on_canvas_resize)
        self._refresh_canvas()

    def _on_canvas_resize(self, event):
        """當畫布容器被使用者拉大或縮小時，自動將緩衝區影像等比拓展"""
        new_w = max(10, event.width)
        new_h = max(10, event.height)
        if new_w == self.w and new_h == self.h:
            return

        new_buf = Image.new('RGB', (new_w, new_h), self.bg_color)
        # 將原有內容無損貼到新尺寸的左上角
        new_buf.paste(self._buf_img, (0, 0))
        self._buf_img = new_buf
        self.w = new_w
        self.h = new_h
        self._refresh_canvas()

    def set_brush_params(self, stamp: Image.Image | None, brush_type: str,
                         size: int, spacing: int, scattering: int,
                         angle_ctl: int, angle: int, angle_jitter: int, size_jitter: int,
                         texture: Image.Image | None = None):
        if stamp is not self.brush_stamp_img:
            self._stamp_cache.clear()
        self.brush_stamp_img = stamp
        self.texture_img = texture
        self.brush_type = brush_type
        self.brush_size = max(4, size)
        self.spacing = max(1, spacing)
        self.scattering = scattering
        self.angle_ctl = angle_ctl
        self.angle = angle
        self.angle_jitter = angle_jitter
        self.size_jitter = size_jitter

    def clear(self):
        self._buf_img = Image.new('RGB', (self.w, self.h), self.bg_color)
        self._refresh_canvas()

    def set_bg_mode(self, mode: str):
        self.current_bg_mode = mode
        if mode == 'dark':
            self.bg_color = (30, 30, 30)
            self.ink_color = (240, 240, 240)
        elif mode == 'light':
            self.bg_color = (245, 245, 245)
            self.ink_color = (30, 30, 30)
        elif mode == 'accent':
            self.bg_color = (24, 24, 27)
            self.ink_color = (192, 132, 252)
        self.clear()

    def _on_down(self, event):
        self._last_pt = (event.x, event.y)
        self._dist_accum = 0.0
        self._draw_stamp(event.x, event.y, 0.0)
        self._refresh_canvas()

    def _on_drag(self, event):
        if not self._last_pt:
            self._last_pt = (event.x, event.y)
            return

        x0, y0 = self._last_pt
        x1, y1 = event.x, event.y
        dx = x1 - x0
        dy = y1 - y0
        seg_len = math.hypot(dx, dy)
        if seg_len < 1:
            return

        step_dist = max(2.0, (self.brush_size * (self.spacing / 100.0)))
        angle_rad = math.atan2(dy, dx)
        stroke_angle_deg = math.degrees(angle_rad)

        dist = self._dist_accum
        while dist < seg_len:
            t = dist / seg_len
            px = x0 + dx * t
            py = y0 + dy * t
            self._draw_stamp(px, py, stroke_angle_deg)
            dist += step_dist

        self._dist_accum = dist - seg_len
        self._last_pt = (x1, y1)
        self._refresh_canvas()

    def _on_up(self, event):
        self._last_pt = None
        self._dist_accum = 0.0

    def _draw_stamp(self, x: float, y: float, stroke_angle: float):
        if self.brush_type in ('brushtex', 'papertex'):
            draw = ImageDraw.Draw(self._buf_img)
            r = self.brush_size / 2.0
            draw.ellipse([x - r, y - r, x + r, y + r], fill=self.ink_color)
            return

        if not self.brush_stamp_img:
            draw = ImageDraw.Draw(self._buf_img)
            r = self.brush_size / 2.0
            draw.ellipse([x - r, y - r, x + r, y + r], fill=self.ink_color)
            return

        cur_sz = self.brush_size
        if self.size_jitter > 0:
            scale_mod = 1.0 + (random.random() * 2 - 1) * (self.size_jitter / 100.0) * 0.7
            cur_sz = max(4, int(cur_sz * max(0.1, scale_mod)))

        cx, cy = x, y
        if self.scattering > 0:
            offset_max = self.brush_size * (self.scattering / 100.0) * 1.5
            cx += (random.random() * 2 - 1) * offset_max
            cy += (random.random() * 2 - 1) * offset_max

        cur_ang = self.angle
        if self.angle_ctl == 2:
            cur_ang += stroke_angle
        elif self.angle_ctl == 1:
            cur_ang += (time.time() * 100) % 360

        if self.angle_jitter > 0:
            cur_ang += (random.random() * 2 - 1) * 180 * (self.angle_jitter / 100.0)

        stamp = self.brush_stamp_img
        if stamp.size != (cur_sz, cur_sz):
            cached = self._stamp_cache.get(cur_sz)
            if cached is None:
                if len(self._stamp_cache) >= 64:
                    self._stamp_cache.clear()
                cached = stamp.resize((cur_sz, cur_sz), Image.Resampling.BILINEAR)
                self._stamp_cache[cur_sz] = cached
            stamp = cached

        if abs(cur_ang % 360) > 0.5:
            stamp = stamp.rotate(-cur_ang, resample=Image.Resampling.BILINEAR, expand=True)

        sw, sh = stamp.size
        left = int(cx - sw / 2.0)
        top = int(cy - sh / 2.0)

        tinted = Image.new('RGB', (sw, sh), self.ink_color)
        self._buf_img.paste(tinted, (left, top), mask=stamp)

    def _refresh_canvas(self):
        photo = self._buf_photo
        if photo is not None and (photo.width(), photo.height()) == self._buf_img.size:
            # 尺寸未變：直接更新既有 Tk 影像，避免每個拖曳事件都重建 PhotoImage 與 canvas 物件
            photo.paste(self._buf_img)
            return
        self._buf_photo = ImageTk.PhotoImage(self._buf_img)
        self.delete('all')
        self.create_image(0, 0, image=self._buf_photo, anchor='nw')


# ─── 筆刷與紋理工作台主視窗 (Brush & Texture Studio) ───────────────────────────

class BrushStudioWindow(tk.Toplevel):
    """SAI2 筆刷、紋理與材質製作工坊主視窗"""

    def __init__(self, parent, on_brush_created_callback=None):
        super().__init__(parent)
        self.parent = parent
        self.on_brush_created_callback = on_brush_created_callback

        self.title(_tr('ui.brush_studio.title', "🖌️ SAI2 筆刷與紋理製作工坊 (Brush & Texture Studio)"))
        self.configure(bg=BG)

        # 不設 transient：transient 視窗會跟著主視窗最小化而隱藏，主視窗縮小時用快捷鍵叫出會看不到
        self.focus_force()

        # 讀取使用者上次設定
        self._saved_cfg = BrushStudioSettings.load()

        # 內部狀態
        self._raw_image: Image.Image | None = None       # 原始全解析度來源（最終寫入時使用）
        self._preview_src: Image.Image | None = None     # 縮小後的 RGBA 工作副本（即時預覽用）
        self._update_job = None                          # 延遲重算的 after() 排程
        self._processed_stamp: Image.Image | None = None
        self._processed_texture: Image.Image | None = None
        self._settings_dir = SAI2SettingsManager.get_settings_dir()
        self._tool_groups = SAI2SettingsManager.get_tool_groups(self._settings_dir)
        self._asset_groups = SAI2SettingsManager.get_asset_groups(
            self._saved_cfg.get('main_mode', 'scatter'), self._settings_dir
        )

        # 核心分類模式
        self.var_main_mode = tk.StringVar(value=self._saved_cfg.get('main_mode', 'scatter'))

        # 預覽檢視模式
        self.var_preview_view = tk.StringVar(value=self._saved_cfg.get('preview_view', 'single'))

        # UI 綁定變數
        self.var_brush_name = tk.StringVar(value=f"自製筆刷_{random.randint(10, 99)}")
        self.var_convert_mode = tk.StringVar(value=self._saved_cfg.get('convert_mode', 'alpha'))
        self.var_autocrop = tk.BooleanVar(value=self._saved_cfg.get('autocrop', True))
        self.var_target_group = tk.StringVar()
        saved_grp = self._saved_cfg.get('target_group', '')
        if saved_grp and any(g['name'] == saved_grp for g in self._tool_groups):
            self.var_target_group.set(saved_grp)
        elif self._tool_groups:
            pref = next((g['name'] for g in self._tool_groups if '效果' in g['name'] or '基本' in g['name']), self._tool_groups[0]['name'])
            self.var_target_group.set(pref)

        self.var_asset_group = tk.StringVar(value=self._saved_cfg.get('asset_group', '(未分類)'))

        # 筆刷專用參數 (從上次設定還原)
        self.var_size = tk.IntVar(value=self._saved_cfg.get('size', 60))
        self.var_spacing = tk.IntVar(value=self._saved_cfg.get('spacing', 35))
        self.var_scattering = tk.IntVar(value=self._saved_cfg.get('scattering', 30))
        self.var_angle_ctl = tk.IntVar(value=self._saved_cfg.get('angle_ctl', 0))
        self.var_angle = tk.IntVar(value=self._saved_cfg.get('angle', 0))
        self.var_angle_jitter = tk.IntVar(value=self._saved_cfg.get('angle_jitter', 20))
        self.var_size_jitter = tk.IntVar(value=self._saved_cfg.get('size_jitter', 30))
        self.var_pen_pressure = tk.BooleanVar(value=self._saved_cfg.get('pen_pressure', True))

        # 紋理/材質專用參數 (從上次設定還原)
        self.var_seamless_mode = tk.StringVar(value=self._saved_cfg.get('seamless_mode', 'crossfade'))
        self.var_blend_margin = tk.IntVar(value=self._saved_cfg.get('blend_margin', 25))
        self.var_tex_res = tk.IntVar(value=self._saved_cfg.get('tex_res', 256))
        self.var_contrast = tk.DoubleVar(value=self._saved_cfg.get('contrast', 1.0))
        self.var_brightness = tk.DoubleVar(value=self._saved_cfg.get('brightness', 0.0))
        self.var_invert = tk.BooleanVar(value=self._saved_cfg.get('invert', False))
        self.var_create_texture_brush = tk.BooleanVar(value=self._saved_cfg.get('create_texture_brush', True))

        self._build_ui()

        # 綁定全域貼上快捷鍵 Ctrl+V
        self.bind('<Control-v>', self._on_ctrl_v)
        self.bind('<Control-V>', self._on_ctrl_v)

        # 視窗關閉時自動儲存所有參數設定
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # 還原畫布底色
        pad_bg = self._saved_cfg.get('pad_bg_mode', 'dark')
        self.pad.set_bg_mode(pad_bg)

        self._load_from_clipboard_silent()
        self._on_mode_switched()
        self._update_sai2_status()
        # 依縮放倍率與內容決定大小（原本固定 980x680，在 150% 縮放下內容需要約 1229x800）
        fit_window(self, 980, 680)

    def _on_window_close(self):
        """關閉視窗前持久化所有參數"""
        self._save_current_settings()
        self.destroy()

    def destroy(self):
        # 取消所有排程：視窗銷毀後仍觸發會對已不存在的元件操作而拋出 TclError
        for attr in ('_update_job', '_status_job'):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, attr, None)
        super().destroy()

    def _save_current_settings(self):
        """將當前視窗的所有選項保存到設定檔"""
        cfg = {
            'main_mode': self.var_main_mode.get(),
            'preview_view': self.var_preview_view.get(),
            'target_group': self.var_target_group.get(),
            'asset_group': self.var_asset_group.get(),
            'size': self.var_size.get(),
            'spacing': self.var_spacing.get(),
            'scattering': self.var_scattering.get(),
            'angle_ctl': self.var_angle_ctl.get(),
            'angle': self.var_angle.get(),
            'angle_jitter': self.var_angle_jitter.get(),
            'size_jitter': self.var_size_jitter.get(),
            'pen_pressure': self.var_pen_pressure.get(),
            'convert_mode': self.var_convert_mode.get(),
            'autocrop': self.var_autocrop.get(),
            'seamless_mode': self.var_seamless_mode.get(),
            'blend_margin': self.var_blend_margin.get(),
            'tex_res': self.var_tex_res.get(),
            'contrast': self.var_contrast.get(),
            'brightness': self.var_brightness.get(),
            'invert': self.var_invert.get(),
            'create_texture_brush': self.var_create_texture_brush.get(),
            'pad_bg_mode': getattr(self.pad, 'current_bg_mode', 'dark'),
        }
        BrushStudioSettings.save(cfg)

    def _build_ui(self):
        # ── 頂部標題與主分類切換列 ───────────────────────────────────────────
        hdr = tk.Frame(self, bg=CARD, padx=16, pady=8)
        hdr.pack(fill='x')

        left_hdr = tk.Frame(hdr, bg=CARD)
        left_hdr.pack(side='left')
        tk.Label(left_hdr, text=_tr('ui.brush_studio.hdr_title', "🖌️ SAI2 筆刷與紋理工坊"),
                 font=FT_TITLE, fg=TEXT, bg=CARD).pack(anchor='w')
        tk.Label(left_hdr, text="支援剪貼簿快捷鍵 Ctrl+V 貼上圖像 | 自動無縫紋理平鋪 | 自動記憶數值",
                 font=FT_SMALL, fg=TEXTD, bg=CARD).pack(anchor='w')

        self.lbl_sai_status = tk.Label(hdr, text="偵測中...", font=FT_NORM, bg=CARD)
        self.lbl_sai_status.pack(side='right', padx=(10, 0))

        # 類別切換標籤列
        cat_bar = tk.Frame(self, bg=CARD2, padx=14, pady=5)
        cat_bar.pack(fill='x')

        modes = [
            ("✨ 散布筆刷 (Scatter)", "scatter"),
            ("🖌️ 印章/形狀 (Shape)", "brush"),
            ("🧶 筆刷紋理 (BrushTex)", "brushtex"),
            ("📜 紙張材質 (PaperTex)", "papertex"),
        ]
        self._mode_radios = []
        for text, val in modes:
            r = tk.Radiobutton(cat_bar, text=text, variable=self.var_main_mode, value=val,
                               font=FT_HEAD, fg=TEXT, bg=CARD2, selectcolor=ACCENT,
                               activebackground=CARD2, activeforeground='white',
                               indicatoron=0, padx=14, pady=4, cursor='hand2',
                               command=self._on_mode_switched)
            r.pack(side='left', padx=3)
            self._mode_radios.append(r)

        # ── 主內容區域 ───────────────────────────────────────────────────────
        content = tk.Frame(self, bg=BG, padx=12, pady=10)
        content.pack(fill='both', expand=True)
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=4)
        content.columnconfigure(2, weight=4)
        content.rowconfigure(0, weight=1)

        # ── 欄位 1：圖案來源與預覽 ─────────────────────────────────────────────
        col1 = tk.Frame(content, bg=CARD, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
        col1.grid(row=0, column=0, sticky='nsew', padx=(0, 6))

        tk.Label(col1, text="1. 圖案來源與預覽", font=FT_HEAD, fg=TEXT, bg=CARD).pack(anchor='w', pady=(0, 6))

        # 縮圖預覽框
        self.canvas_preview = tk.Canvas(col1, width=px(self, 190), height=px(self, 190), bg='#1a1a1a',
                                        highlightthickness=1, highlightbackground=BORDER)
        self.canvas_preview.pack(pady=2)

        # 預覽檢視切換按鈕
        self.prev_toggle_box = tk.Frame(col1, bg=CARD)
        self.prev_toggle_box.pack(fill='x', pady=3)
        tk.Radiobutton(self.prev_toggle_box, text="單圖檢視", variable=self.var_preview_view, value="single",
                       font=FT_SMALL, fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=self._render_preview).pack(side='left', padx=2)
        tk.Radiobutton(self.prev_toggle_box, text="3×3 平鋪預覽", variable=self.var_preview_view, value="tiled",
                       font=FT_SMALL, fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=self._render_preview).pack(side='left', padx=4)

        # 來源按鈕 (支援點擊與提示 Ctrl+V)
        btn_box = tk.Frame(col1, bg=CARD)
        btn_box.pack(fill='x', pady=4)
        self._create_btn(btn_box, "📋 剪貼簿貼上 (Ctrl+V)", self._on_click_clip).pack(side='left', fill='x', expand=True, padx=(0, 3))
        self._create_btn(btn_box, "📁 開啟圖片", self._on_click_file).pack(side='right', fill='x', expand=True, padx=(3, 0))

        # 去背與形狀模式 (通用於筆刷與紋理)
        self.frame_src_common = tk.Frame(col1, bg=CARD)
        self.frame_src_common.pack(fill='x', pady=(6, 0))

        tk.Label(self.frame_src_common, text="色彩與去背模式：", font=FT_BOLD, fg=TEXT, bg=CARD).pack(anchor='w', pady=(2, 2))
        brush_modes = [
            ("透明背景 (Alpha形狀/保留線條)", "alpha"),
            ("白底黑線 (亮度轉透明/反轉)", "white_bg"),
            ("黑底白線 (發光/原亮)", "black_bg"),
            ("實心剪影 (填滿不透明)", "silhouette"),
        ]
        for text, val in brush_modes:
            tk.Radiobutton(self.frame_src_common, text=text, variable=self.var_convert_mode, value=val,
                           font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                           command=self._on_param_changed).pack(anchor='w', pady=1)

        self.chk_autocrop = tk.Checkbutton(
            self.frame_src_common, text="自動裁切多餘邊界 (Autocrop)",
            variable=self.var_autocrop, font=FT_NORM,
            fg=TEXT, bg=CARD, selectcolor=CARD2,
            command=self._on_param_changed
        )
        self.chk_autocrop.pack(anchor='w', pady=(4, 0))

        # 紋理專用無縫選項框架
        self.frame_src_texture = tk.Frame(col1, bg=CARD)
        tk.Label(self.frame_src_texture, text="無縫接縫平鋪處理 (Seamless)：", font=FT_BOLD, fg=TEXT, bg=CARD).pack(anchor='w', pady=(2, 2))
        tex_modes = [
            ("無縫平滑融合 (Cross-fade 推薦)", "crossfade"),
            ("2×2 鏡像對稱平鋪 (Mirror)", "mirror"),
            ("保持原樣 (不進行接縫處理)", "none"),
        ]
        for text, val in tex_modes:
            tk.Radiobutton(self.frame_src_texture, text=text, variable=self.var_seamless_mode, value=val,
                           font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                           command=self._on_param_changed).pack(anchor='w', pady=1)

        # ── 欄位 2：參數配置 ──────────────────────────────────────────────────
        col2 = tk.Frame(content, bg=CARD, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
        col2.grid(row=0, column=1, sticky='nsew', padx=3)

        tk.Label(col2, text="2. 名稱與參數設定", font=FT_HEAD, fg=TEXT, bg=CARD).pack(anchor='w', pady=(0, 6))

        # 名稱輸入
        self.lbl_name_prompt = tk.Label(col2, text="筆刷名稱：", font=FT_NORM, fg=TEXT, bg=CARD)
        self.lbl_name_prompt.pack(anchor='w')
        ent_name = tk.Entry(col2, textvariable=self.var_brush_name, font=FT_NORM,
                            bg=CARD2, fg=TEXT, insertbackground=TEXT, relief='flat',
                            highlightthickness=1, highlightbackground=BORDER)
        ent_name.pack(fill='x', pady=(2, 6), ipady=3)

        # 目標分頁與素材分類
        self.frame_group_sel = tk.Frame(col2, bg=CARD)
        self.frame_group_sel.pack(fill='x', pady=(0, 4))
        tk.Label(self.frame_group_sel, text="加入 SAI2 工具分頁 (群組)：", font=FT_NORM, fg=TEXT, bg=CARD).pack(anchor='w')
        grp_names = [g['name'] for g in self._tool_groups] or ["基本", "二值", "效果"]
        self.cbo_group = ttk.Combobox(self.frame_group_sel, textvariable=self.var_target_group, values=grp_names, font=FT_NORM)
        self.cbo_group.pack(fill='x', pady=(2, 0))

        self.frame_asset_grp_sel = tk.Frame(col2, bg=CARD)
        self.frame_asset_grp_sel.pack(fill='x', pady=(0, 6))
        tk.Label(self.frame_asset_grp_sel, text="存入素材庫分類：", font=FT_NORM, fg=TEXT, bg=CARD).pack(anchor='w')
        asset_grp_names = [g['name'] for g in self._asset_groups] or ["(未分類)"]
        self.cbo_asset_group = ttk.Combobox(self.frame_asset_grp_sel, textvariable=self.var_asset_group, values=asset_grp_names, font=FT_NORM)
        self.cbo_asset_group.pack(fill='x', pady=(2, 0))

        # 筆刷參數容器
        self.box_brush_params = tk.Frame(col2, bg=CARD)
        self.box_brush_params.pack(fill='both', expand=True)

        # 以下參數只影響試畫區的筆觸模擬，不改變素材圖像本身 → 不需重算圖像
        brush_cb = self._on_brush_param_changed
        self._add_slider(self.box_brush_params, "間距 (Spacing %):", self.var_spacing, 1, 300, brush_cb)
        self._add_slider(self.box_brush_params, "散布幅度 (Scattering %):", self.var_scattering, 0, 200, brush_cb)
        self._add_slider(self.box_brush_params, "尺寸大小 (Size px):", self.var_size, 10, 500, brush_cb)
        self._add_slider(self.box_brush_params, "尺寸抖動 (Size Jitter %):", self.var_size_jitter, 0, 100, brush_cb)
        self._add_slider(self.box_brush_params, "角度抖動 (Angle Jitter %):", self.var_angle_jitter, 0, 100, brush_cb)

        ang_box = tk.Frame(self.box_brush_params, bg=CARD)
        ang_box.pack(fill='x', pady=3)
        tk.Label(ang_box, text="角度控制：", font=FT_NORM, fg=TEXT, bg=CARD).pack(side='left')
        tk.Radiobutton(ang_box, text="無", variable=self.var_angle_ctl, value=0,
                       font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=brush_cb).pack(side='left')
        tk.Radiobutton(ang_box, text="隨筆向", variable=self.var_angle_ctl, value=2,
                       font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=brush_cb).pack(side='left', padx=4)
        tk.Radiobutton(ang_box, text="自動", variable=self.var_angle_ctl, value=1,
                       font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=brush_cb).pack(side='left')

        tk.Checkbutton(self.box_brush_params, text="啟用繪圖板筆壓 (感應大小與濃度)",
                       variable=self.var_pen_pressure, font=FT_NORM,
                       fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=brush_cb).pack(anchor='w', pady=(3, 0))

        # 紋理與材質專用參數容器
        self.box_texture_params = tk.Frame(col2, bg=CARD)

        self._add_slider(self.box_texture_params, "融合過渡比例 (%):", self.var_blend_margin, 10, 50)

        res_frame = tk.Frame(self.box_texture_params, bg=CARD)
        res_frame.pack(fill='x', pady=3)
        tk.Label(res_frame, text="材質輸出尺寸：", font=FT_NORM, fg=TEXT, bg=CARD).pack(side='left')
        for r_val, r_text in [(256, "256×256"), (512, "512×512"), (1024, "1024×1024")]:
            tk.Radiobutton(res_frame, text=r_text, variable=self.var_tex_res, value=r_val,
                           font=FT_NORM, fg=TEXT, bg=CARD, selectcolor=CARD2,
                           command=self._on_param_changed).pack(side='left', padx=2)

        f_cnt = tk.Frame(self.box_texture_params, bg=CARD)
        f_cnt.pack(fill='x', pady=2)
        self.lbl_contrast = tk.Label(f_cnt, text=f"對比度增強: {self.var_contrast.get():.2f}x", font=FT_NORM, fg=TEXT, bg=CARD)
        self.lbl_contrast.pack(side='top', anchor='w')
        def _on_cnt_slide(val):
            self.lbl_contrast.config(text=f"對比度增強: {float(val):.2f}x")
            self._on_param_changed()
        ttk.Scale(f_cnt, from_=0.3, to=3.0, variable=self.var_contrast, command=_on_cnt_slide).pack(side='top', fill='x')

        f_brt = tk.Frame(self.box_texture_params, bg=CARD)
        f_brt.pack(fill='x', pady=2)
        self.lbl_bright = tk.Label(f_brt, text=f"亮度偏移: {int(self.var_brightness.get()*100)}%", font=FT_NORM, fg=TEXT, bg=CARD)
        self.lbl_bright.pack(side='top', anchor='w')
        def _on_brt_slide(val):
            self.lbl_bright.config(text=f"亮度偏移: {int(float(val)*100)}%")
            self._on_param_changed()
        ttk.Scale(f_brt, from_=-0.5, to=0.5, variable=self.var_brightness, command=_on_brt_slide).pack(side='top', fill='x')

        tk.Checkbutton(self.box_texture_params, text="反轉黑白明暗 (Invert Lightness)",
                       variable=self.var_invert, font=FT_NORM,
                       fg=TEXT, bg=CARD, selectcolor=CARD2,
                       command=self._on_param_changed).pack(anchor='w', pady=(3, 0))

        self.chk_create_tex_brush = tk.Checkbutton(
            self.box_texture_params, text="✨ 同時在 SAI2 工具面板建立「質感筆刷」",
            variable=self.var_create_texture_brush, font=FT_NORM,
            fg=YELLOW, bg=CARD, selectcolor=CARD2, activebackground=CARD, activeforeground=YELLOW
        )
        self.chk_create_tex_brush.pack(anchor='w', pady=(4, 0))

        # ── 欄位 3：試畫區與操作按鈕 ─────────────────────────────────────────
        col3 = tk.Frame(content, bg=CARD, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
        col3.grid(row=0, column=2, sticky='nsew', padx=(6, 0))

        pad_hdr = tk.Frame(col3, bg=CARD)
        pad_hdr.pack(fill='x', pady=(0, 4))
        self.lbl_pad_title = tk.Label(pad_hdr, text="3. 即時手感試畫區", font=FT_HEAD, fg=TEXT, bg=CARD)
        self.lbl_pad_title.pack(side='left')

        self._create_btn(pad_hdr, "🧹 清除", self._on_clear_pad, pad=(6, 1)).pack(side='right')

        bg_btn_box = tk.Frame(col3, bg=CARD)
        bg_btn_box.pack(fill='x', pady=(0, 4))
        tk.Label(bg_btn_box, text="底色：", font=FT_SMALL, fg=TEXTD, bg=CARD).pack(side='left')
        self._create_btn(bg_btn_box, "深黑", lambda: self.pad.set_bg_mode('dark'), pad=(4, 1)).pack(side='left', padx=2)
        self._create_btn(bg_btn_box, "純白", lambda: self.pad.set_bg_mode('light'), pad=(4, 1)).pack(side='left', padx=2)
        self._create_btn(bg_btn_box, "羅蘭", lambda: self.pad.set_bg_mode('accent'), pad=(4, 1)).pack(side='left', padx=2)

        # 動態自適應畫布
        self.pad = ScratchpadCanvas(col3, width=px(self, 280), height=px(self, 260))
        self.pad.pack(fill='both', expand=True, pady=4)

        self.lbl_pad_tip = tk.Label(col3, text="※ 在上方試畫區拖曳即可即時模擬筆觸軌跡 (支援視窗自由縮放)",
                                    font=FT_SMALL, fg=TEXTD, bg=CARD)
        self.lbl_pad_tip.pack(anchor='w', pady=(2, 6))

        # 底部執行動作按鈕
        act_box = tk.Frame(col3, bg=CARD)
        act_box.pack(fill='x', side='bottom')

        self.btn_deploy = tk.Button(
            act_box, text="🚀 一鍵建立並加入 SAI2",
            font=FT_HEAD, bg=ACCENT, fg='white', activebackground=ACCH,
            activeforeground='white', relief='flat', cursor='hand2',
            command=self._on_click_deploy, pady=7
        )
        self.btn_deploy.pack(fill='x', pady=(0, 4))

        self.btn_mat_only = tk.Button(
            act_box, text="💾 僅儲存素材到素材庫",
            font=FT_NORM, bg=CARD2, fg=TEXT, activebackground=CARD3,
            activeforeground=TEXT, relief='flat', cursor='hand2',
            command=self._on_click_save_material_only, pady=4
        )
        self.btn_mat_only.pack(fill='x')

    def _create_btn(self, parent, text, cmd, pad=(8, 3)):
        b = tk.Button(parent, text=text, font=FT_NORM, bg=CARD2, fg=TEXT,
                      activebackground=ACCENT, activeforeground='white',
                      relief='flat', cursor='hand2', padx=pad[0], pady=pad[1], command=cmd)
        b.bind('<Enter>', lambda e: b.config(bg=CARD3))
        b.bind('<Leave>', lambda e: b.config(bg=CARD2))
        return b

    def _add_slider(self, parent, label_text, var, min_v, max_v, on_change=None):
        on_change = on_change or self._on_param_changed
        f = tk.Frame(parent, bg=CARD)
        f.pack(fill='x', pady=2)
        lbl = tk.Label(f, text=f"{label_text} {var.get()}", font=FT_NORM, fg=TEXT, bg=CARD)
        lbl.pack(side='top', anchor='w')

        def _on_slide(val):
            lbl.config(text=f"{label_text} {int(float(val))}")
            on_change()

        s = ttk.Scale(f, from_=min_v, to=max_v, variable=var, command=_on_slide)
        s.pack(side='top', fill='x')

    def _on_mode_switched(self):
        m = self.var_main_mode.get()
        is_texture_mode = m in ('brushtex', 'papertex')

        # 動態更新該模式對應的素材分類清單
        self._asset_groups = SAI2SettingsManager.get_asset_groups(m, self._settings_dir)
        asset_names = [g['name'] for g in self._asset_groups] or ["(未分類)"]
        self.cbo_asset_group.config(values=asset_names)
        if self.var_asset_group.get() not in asset_names:
            self.var_asset_group.set("(未分類)")

        if is_texture_mode:
            self.chk_autocrop.pack_forget()
            self.frame_src_texture.pack(fill='x', pady=(6, 0))
            self.var_preview_view.set("tiled")
        else:
            self.frame_src_texture.pack_forget()
            self.chk_autocrop.pack(anchor='w', pady=(4, 0))
            self.var_preview_view.set("single")

        if is_texture_mode:
            self.box_brush_params.pack_forget()
            self.box_texture_params.pack(fill='both', expand=True)
            if m == 'brushtex':
                self.lbl_name_prompt.config(text="紋理名稱 (BrushTex)：")
                self.chk_create_tex_brush.pack(anchor='w', pady=(4, 0))
                self.frame_group_sel.pack(fill='x', pady=(0, 4), before=self.frame_asset_grp_sel)
                self.btn_deploy.config(text="🚀 儲存紋理並建立質感筆刷")
                self.btn_mat_only.config(text="💾 僅將紋理存入 brushtex 目錄")
            else:  # papertex
                self.lbl_name_prompt.config(text="材質名稱 (PaperTex)：")
                self.chk_create_tex_brush.pack_forget()
                self.frame_group_sel.pack_forget()
                self.btn_deploy.config(text="🚀 儲存至 SAI2 紙張材質庫")
                self.btn_mat_only.config(text="💾 僅將材質存入 papertex 目錄")
        else:
            self.box_texture_params.pack_forget()
            self.box_brush_params.pack(fill='both', expand=True)
            self.frame_group_sel.pack(fill='x', pady=(0, 4), before=self.frame_asset_grp_sel)
            self.lbl_name_prompt.config(text="筆刷名稱：")
            self.btn_deploy.config(text="🚀 一鍵建立並加入 SAI2")
            self.btn_mat_only.config(text="💾 僅儲存素材到素材庫")

        self._update_processed_output()

    def _update_sai2_status(self):
        is_running = SAI2SettingsManager.is_sai2_running()
        if is_running:
            self.lbl_sai_status.config(
                text="🟡 SAI2 運行中 (提供安全防覆蓋寫入)",
                fg=YELLOW
            )
        else:
            self.lbl_sai_status.config(
                text="🟢 SAI2 未運行 (可直接寫入並立即生效)",
                fg=GREEN
            )
        self._status_job = self.after(2000, self._update_sai2_status)

    # 預覽時的來源長邊上限；最終寫入仍以全解析度原圖重新處理，品質不受影響
    PREVIEW_MAX_SIDE = 1024
    # 參數變動後的重算延遲：拖曳滑桿時每秒會觸發數十次，合併成停手後的一次重算
    UPDATE_DELAY_MS = 120

    def _set_source_image(self, img: Image.Image):
        self._raw_image = img
        work = img.convert('RGBA')   # convert 一律回傳新影像，下方 thumbnail 不會改到原圖
        work.thumbnail((self.PREVIEW_MAX_SIDE, self.PREVIEW_MAX_SIDE), Image.Resampling.LANCZOS)
        self._preview_src = work

    def _load_from_clipboard_silent(self):
        try:
            img = read_clipboard_safely()
            if img:
                self._set_source_image(img)
        except Exception:
            pass

    def _on_ctrl_v(self, event):
        # 在名稱 / 分類輸入框內 Ctrl+V 是貼上文字，交給輸入框自己處理，不去讀剪貼簿圖像
        if is_text_input_widget(event.widget):
            return
        self._on_click_clip()

    def _on_click_clip(self):
        img = read_clipboard_safely()
        if not img:
            messagebox.showwarning(
                "筆刷工坊",
                "剪貼簿中未偵測到有效圖像！\n\n"
                "• 若在 SAI2 中：請先選取圖樣並按下 Ctrl+C 複製\n"
                "• 若在檔案總管中：選取圖片檔案按下 Ctrl+C 即可貼上\n"
                "• 亦可直接在工作台視窗中按下 Ctrl+V 貼上",
                parent=self
            )
            return
        self._set_source_image(img)
        self.lbl_pad_tip.config(text=f"✅ 已成功從剪貼簿讀取圖像 ({img.size[0]}×{img.size[1]})！", fg=GREEN)
        self._update_processed_output()

    def _on_click_file(self):
        fpath = filedialog.askopenfilename(
            title="選擇圖片素材",
            filetypes=[("圖片檔案", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"), ("所有檔案", "*.*")],
            parent=self
        )
        if not fpath or not os.path.isfile(fpath):
            return
        try:
            img = Image.open(fpath)
            img.load()
            self._set_source_image(ImageOps.exif_transpose(img))
            base_name = os.path.splitext(os.path.basename(fpath))[0]
            self.var_brush_name.set(base_name)
            self._update_processed_output()
        except Exception as e:
            messagebox.showerror("載入失敗", f"無法開啟圖片檔案：{e}", parent=self)

    def _on_clear_pad(self):
        self.pad.clear()

    def _on_param_changed(self, *args):
        """會改變輸出圖像的參數：延遲合併後再重算"""
        if self._update_job is not None:
            self.after_cancel(self._update_job)
        self._update_job = self.after(self.UPDATE_DELAY_MS, self._update_processed_output)

    def _on_brush_param_changed(self, *args):
        """只影響試畫筆觸的參數：直接更新試畫區，不重算圖像"""
        self._sync_pad_params()

    def _flush_processed_output(self):
        """若還有尚未執行的延遲重算，立即執行（寫入前確保圖像對應目前參數）"""
        if self._update_job is not None:
            self._update_processed_output()

    @staticmethod
    def _default_source(is_texture_mode: bool) -> Image.Image:
        if is_texture_mode:
            base_im = Image.new('L', (256, 256), 180)
            d = ImageDraw.Draw(base_im)
            for _ in range(300):
                x, y = random.randint(0, 255), random.randint(0, 255)
                d.point((x, y), fill=random.randint(60, 220))
            return base_im
        default_im = Image.new('L', (512, 512), 0)
        d = ImageDraw.Draw(default_im)
        pts = []
        cx, cy, r_out, r_in = 256, 256, 200, 90
        for i in range(10):
            ang = i * math.pi / 5 - math.pi / 2
            r = r_out if i % 2 == 0 else r_in
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        d.polygon(pts, fill=255)
        return default_im

    def _process_image(self, src: Image.Image) -> Image.Image:
        """依目前模式與參數處理來源影像（預覽與最終寫入共用）"""
        mode = self.var_convert_mode.get()
        if self.var_main_mode.get() in ('brushtex', 'papertex'):
            return BrushImageProcessor.process_texture(
                src, seamless_mode=self.var_seamless_mode.get(),
                blend_ratio=self.var_blend_margin.get() / 100.0,
                contrast=self.var_contrast.get(), brightness=self.var_brightness.get(),
                invert=self.var_invert.get(), target_size=self.var_tex_res.get(),
                convert_mode=mode
            )
        return BrushImageProcessor.process(
            src, mode=mode, autocrop=self.var_autocrop.get(), target_size=512
        )

    def _final_output_image(self) -> Image.Image | None:
        """寫入用的圖像：有使用者來源時以全解析度原圖重新處理，否則沿用預覽結果"""
        self._flush_processed_output()
        is_texture = self.var_main_mode.get() in ('brushtex', 'papertex')
        preview = self._processed_texture if is_texture else self._processed_stamp
        if self._raw_image is None or preview is None:
            return preview
        return self._process_image(self._raw_image)

    def _update_processed_output(self):
        if self._update_job is not None:
            try:
                self.after_cancel(self._update_job)
            except Exception:
                pass
            self._update_job = None

        is_texture_mode = self.var_main_mode.get() in ('brushtex', 'papertex')
        src = self._preview_src if self._preview_src is not None else self._default_source(is_texture_mode)
        out = self._process_image(src)
        if is_texture_mode:
            self._processed_texture = out
        else:
            self._processed_stamp = out

        self._render_preview()
        self._sync_pad_params()

    def _sync_pad_params(self):
        self.pad.set_brush_params(
            stamp=self._processed_stamp,
            brush_type=self.var_main_mode.get(),
            size=self.var_size.get(),
            spacing=self.var_spacing.get(),
            scattering=self.var_scattering.get(),
            angle_ctl=self.var_angle_ctl.get(),
            angle=self.var_angle.get(),
            angle_jitter=self.var_angle_jitter.get(),
            size_jitter=self.var_size_jitter.get(),
            texture=self._processed_texture
        )

    def _render_preview(self):
        m = self.var_main_mode.get()
        is_texture_mode = m in ('brushtex', 'papertex')
        img_to_show = self._processed_texture if is_texture_mode else self._processed_stamp
        if not img_to_show:
            return

        cw = self.canvas_preview.winfo_width()
        ch = self.canvas_preview.winfo_height()
        if cw <= 1 or ch <= 1:
            cw = ch = px(self, 190)

        pw, ph = cw - 4, ch - 4
        is_tiled = (self.var_preview_view.get() == "tiled")

        if is_tiled or is_texture_mode:
            tile_w, tile_h = max(10, pw // 3), max(10, ph // 3)
            sub = img_to_show.resize((tile_w, tile_h), Image.Resampling.BILINEAR)
            tiled_img = Image.new('L', (pw, ph))
            for ty in range(3):
                for tx in range(3):
                    tiled_img.paste(sub, (tx * tile_w, ty * tile_h))
            prev_img = tiled_img.convert('RGBA')
        else:
            prev_img = Image.new('RGBA', (pw, ph), (25, 25, 25, 255))
            draw = ImageDraw.Draw(prev_img)
            grid_s = 10
            for y in range(0, ph, grid_s):
                for x in range(0, pw, grid_s):
                    if ((x // grid_s) + (y // grid_s)) % 2 == 0:
                        draw.rectangle([x, y, x + grid_s, y + grid_s], fill=(40, 40, 40, 255))

            thumb = img_to_show.resize((pw, ph), Image.Resampling.LANCZOS)
            fg_white = Image.new('RGBA', (pw, ph), (255, 255, 255, 255))
            prev_img.paste(fg_white, (0, 0), mask=thumb)

        self._preview_photo = ImageTk.PhotoImage(prev_img)
        self.canvas_preview.delete('all')
        self.canvas_preview.create_image(2, 2, image=self._preview_photo, anchor='nw')

    # 新群組（清單中沒有的名稱）一律回傳 ID 0，實際 ID 由 SAI2SettingsManager 在寫入當下
    # 依磁碟內容配發；不在這裡算 max+1，否則清單過期或連續排入佇列時會算出重複的 ID。
    def _get_target_group_info(self) -> tuple[int, str]:
        chosen_name = self.var_target_group.get().strip()
        for g in self._tool_groups:
            if g['name'] == chosen_name:
                return g['id'], chosen_name
        return 0, chosen_name

    def _get_asset_group_info(self) -> tuple[int, str]:
        chosen_name = self.var_asset_group.get().strip()
        if not chosen_name or chosen_name == '(未分類)':
            return 0, ''
        for g in self._asset_groups:
            if g['name'] == chosen_name:
                return g['id'], g['name']
        return 0, chosen_name

    def _reload_groups(self):
        """寫入後重新讀取分頁與分類清單，讓剛建立的群組出現在選單中"""
        self._tool_groups = SAI2SettingsManager.get_tool_groups(self._settings_dir)
        self.cbo_group.config(values=[g['name'] for g in self._tool_groups] or ["基本", "二值", "效果"])
        self._asset_groups = SAI2SettingsManager.get_asset_groups(self.var_main_mode.get(), self._settings_dir)
        self.cbo_asset_group.config(values=[g['name'] for g in self._asset_groups] or ["(未分類)"])

    def _gather_params(self) -> dict:
        ag_id, ag_name = self._get_asset_group_info()
        return {
            'size': self.var_size.get(),
            'spacing': self.var_spacing.get(),
            'scattering': self.var_scattering.get(),
            'angle_control': self.var_angle_ctl.get(),
            'angle': self.var_angle.get(),
            'angle_jitter': self.var_angle_jitter.get(),
            'size_jitter': self.var_size_jitter.get(),
            'pen_pressure': self.var_pen_pressure.get(),
            'asset_group_id': ag_id,
            'asset_group_name': ag_name,
        }

    # ── 寫入流程 ──────────────────────────────────────────────────────────

    def _validated_name(self) -> str | None:
        """讀取並驗證名稱（兩個寫入按鈕共用）；不合法時顯示錯誤並回傳 None"""
        name = self.var_brush_name.get().strip()
        err = validate_asset_name(name)
        if err:
            messagebox.showerror("名稱不合法", err, parent=self)
            return None
        return name

    def _asset_exists(self, name: str, mode: str) -> bool:
        if not self._settings_dir:
            return False
        if mode == 'scatter':
            folder = os.path.join(self._settings_dir, 'scatter')
        elif mode in ('brushtex', 'papertex'):
            folder = os.path.join(self._settings_dir, mode)
        else:
            folder = os.path.join(self._settings_dir, 'brushfom', 'brshape')
        return os.path.isfile(os.path.join(folder, f"{name}.bmp"))

    def _ask_write_strategy(self, what: str) -> str | None:
        """
        決定寫入方式：
          'direct' — SAI2 未運行，直接寫入
          'queue'  — SAI2 運行中，排入佇列，待 SAI2 關閉後才寫入（不碰任何 SAI2 設定檔）
          'force'  — SAI2 運行中，使用者選擇立刻強制寫入
          None     — 使用者取消
        """
        if not SAI2SettingsManager.is_sai2_running():
            return 'direct'
        choice = messagebox.askyesnocancel(
            "SAI2 正在運行中",
            f"PaintTool SAI2 正在運行中。\n\n"
            f"SAI2 關閉時會以記憶體中的內容覆寫自己的設定檔，若現在寫入{what}，"
            f"素材清單或工具面板的變更可能會被覆蓋而消失。\n\n"
            f"• 【是 (Yes)】：排入背景佇列，待您關閉 SAI2 後自動安全寫入 (推薦)\n"
            f"• 【否 (No)】：立刻強制寫入 (之後需重新啟動 SAI2)\n"
            f"• 【取消 (Cancel)】：不寫入任何檔案",
            parent=self,
        )
        if choice is True:
            return 'queue'
        if choice is False:
            return 'force'
        return None

    def _finish_success(self, name: str, close: bool):
        if not close:
            return  # 「僅儲存素材」維持原行為：不關閉視窗，方便連續製作
        if self.on_brush_created_callback:
            self.on_brush_created_callback(name)
        self.destroy()

    def _write_asset_now(self, name: str, mode: str, image: Image.Image,
                         params: dict) -> tuple[str, int]:
        """立即寫入素材 / 紋理並註冊，回傳 (BMP 路徑, 實際歸屬的素材分類 ID)"""
        if mode in ('brushtex', 'papertex'):
            return SAI2SettingsManager.write_texture(
                name, image, mode, self._settings_dir,
                asset_group_id=params.get('asset_group_id', 0),
                asset_group_name=params.get('asset_group_name', ''))
        bmp_p, _, gid = SAI2SettingsManager.write_material(
            name, image, mode, params, self._settings_dir)
        return bmp_p, gid

    def _run_write(self, create_tool_requested: bool):
        self._save_current_settings()
        name = self._validated_name()
        if name is None:
            return

        m = self.var_main_mode.get()
        try:
            image = self._final_output_image()
        except Exception as e:
            messagebox.showerror("錯誤", f"處理圖像時發生錯誤：{e}", parent=self)
            return
        if image is None:
            messagebox.showerror("錯誤", "尚未產生可儲存的圖像。", parent=self)
            return

        # 紙張材質沒有對應工具；筆刷紋理依勾選決定是否建立質感筆刷
        create_tool = create_tool_requested and m != 'papertex'
        if m == 'brushtex':
            create_tool = create_tool and self.var_create_texture_brush.get()
        tool_type = 'texture_brush' if m == 'brushtex' else m

        if self._asset_exists(name, m) and not messagebox.askyesno(
                "名稱已存在",
                f"素材「{name}」已存在，繼續將會覆蓋原檔案（原檔會先備份）。\n\n確定要覆蓋嗎？",
                icon='warning', parent=self):
            return

        params = self._gather_params()
        grp_id, grp_name = self._get_target_group_info()
        what = "素材與工具" if create_tool else "素材"

        strategy = self._ask_write_strategy(what)
        if strategy is None:
            return

        try:
            if strategy == 'queue':
                PendingBrushQueue.add_deploy_task(
                    name, m, image, params, grp_id, create_tool, tool_type, grp_name)
                messagebox.showinfo(
                    "已排入自動儲存佇列",
                    f"已將 [{name}] 的{what}加入佇列！\n"
                    f"SAI2 運行期間不會修改其任何設定檔；DrawCompanion 會在您關閉 SAI2 後自動寫入。\n"
                    f"下次開啟 SAI2 即可看見。",
                    parent=self)
                self._finish_success(name, close=create_tool_requested)
                return

            with sai2_write_session():
                bmp_p, asset_gid = self._write_asset_now(name, m, image, params)
                tid = None
                if create_tool:
                    # 工具的 fomgid / texgid 必須指向素材實際被放入的分類
                    tool_params = dict(params, asset_group_id=asset_gid)
                    tid = SAI2SettingsManager.write_tool(
                        name, tool_type, name, grp_id, tool_params, self._settings_dir,
                        target_group_name=grp_name)
        except Exception as e:
            messagebox.showerror("寫入失敗", f"發生錯誤：{e}", parent=self)
            return
        finally:
            # 無論成功或部分失敗，磁碟上的群組都可能已變動；「僅儲存素材」不關視窗，需重新整理選單
            try:
                self._reload_groups()
            except Exception:
                pass

        restart_hint = "\n\n⚠️ SAI2 目前仍在運行，請重新啟動 SAI2 後才會看見變更。" if strategy == 'force' else ""
        if m == 'papertex':
            messagebox.showinfo(
                "紙張材質建立成功 🎉",
                f"畫布/紙張材質 [{name}] 已成功加入 SAI2！\n\n"
                f"• 存放位置：{bmp_p}\n\n"
                f"於 PaintTool SAI2 的圖層效果「紙張材質」下拉選單中即可選用。{restart_hint}",
                parent=self)
        elif tid is None:
            type_desc = {"brushtex": "筆刷紋理 (brushtex)", "scatter": "散布筆刷素材",
                         "brush": "筆刷形狀素材"}.get(m, "素材")
            messagebox.showinfo(
                "儲存成功",
                f"{type_desc} [{name}] 已成功儲存並註冊至 SAI2 素材清單！\n\n"
                f"路徑：\n{bmp_p}{restart_hint}",
                parent=self)
        else:
            messagebox.showinfo(
                "建立成功 🎉",
                f"工具 [{name}] 已成功建立！\n\n"
                f"• 工具編號：{tid}\n"
                f"• 目標分頁：{self.var_target_group.get()}\n"
                f"• 工具類型：{tool_type}\n\n"
                f"啟動 PaintTool SAI2 即可在工具面板中看見此工具。{restart_hint}",
                parent=self)
        self._finish_success(name, close=create_tool_requested)

    def _on_click_save_material_only(self):
        self._run_write(create_tool_requested=False)

    def _on_click_deploy(self):
        self._run_write(create_tool_requested=True)
