# -*- coding: utf-8 -*-
"""
study_window.py - 臨摹研究視窗與自評打卡對話框

課程卡（目標 / 本次專注 / 分段步驟 / 常見錯誤 / 完成檢查）、參考圖與出處、
檢查工具（翻轉 / 灰階 / 明度分階 / 主色 / 構圖輔助線），以及擷取 SAI2 畫布並排比對。
分段步驟依任務的實際動筆時間（task['progress']，由主程式每秒累計）推進。
"""

from __future__ import annotations

import os
import math
import time
import random
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, ImageTk, ImageOps, ImageDraw, ImageChops

import study_lessons
import study_refs
from psd_writer import write_blank_psd

# ─── 樣式（與筆刷工坊一致的深色配色）───────────────────────────────────────
BG = '#111111'
CARD = '#1e1e1e'
CARD2 = '#282828'
CARD3 = '#333333'
ACCENT = '#7c3aed'
ACCH = '#6d28d9'
TEXT = '#f0f0f0'
TEXTD = '#8a8a8a'
GREEN = '#22c55e'
TEAL = '#0f766e'
TEAL_H = '#115e59'
YELLOW = '#f59e0b'
BORDER = '#3a3a3a'
GUIDE = (34, 211, 238)          # 構圖輔助線顏色
IMG_BG = '#161616'

FT_TITLE = ('Microsoft JhengHei', 12, 'bold')
FT_HEAD = ('Microsoft JhengHei', 10, 'bold')
FT_NORM = ('Microsoft JhengHei', 9)
FT_SMALL = ('Microsoft JhengHei', 8)
FT_PHASE = ('Microsoft JhengHei', 14, 'bold')

VALUE_STEPS = [0, 3, 5]                               # 0 = 原圖
CANVAS_SIDES = (1500, 2000, 3000)                     # 練習畫布長邊（px）
_BAD_NAME_CHARS = '\\/:*?"<>|'


def _safe_filename(name: str) -> str:
    name = ''.join('_' if ch in _BAD_NAME_CHARS or ord(ch) < 32 else ch for ch in name)
    return name.strip(' .')[:80] or '臨摹研究'


def _documents_dir() -> str:
    """實際的「文件」資料夾（被 OneDrive 重新導向時也能找到）"""
    try:
        from brush_studio import SAI2SettingsManager
        return SAI2SettingsManager._documents_dir()
    except Exception:
        return os.path.expanduser('~/Documents')
GUIDES = [('none', '無'), ('thirds', '三分線'), ('grid', '九宮格'), ('diagonal', '對角線')]
PALETTE_SIZE = 6


_caption_font = None


def _font():
    """畫在影像上的中文標籤需用含中文字形的字型（Pillow 預設字型沒有中文）"""
    global _caption_font
    if _caption_font is None:
        from PIL import ImageFont
        for name in ('msjh.ttc', 'msjhbd.ttc', 'mingliu.ttc', 'arial.ttf'):
            try:
                _caption_font = ImageFont.truetype(name, 13)
                break
            except Exception:
                continue
        else:
            _caption_font = ImageFont.load_default()
    return _caption_font


def posterize_value(img: Image.Image, levels: int) -> Image.Image:
    """依明度分成 levels 階（灰階輸出），用來看清大明暗分組"""
    gray = img.convert('L')
    step = 255.0 / (levels - 1)
    lut = [int(round(round(v / step) * step)) for v in range(256)]
    return gray.point(lut).convert('RGB')


def extract_palette(img: Image.Image, n: int = PALETTE_SIZE) -> list[tuple[int, int, int]]:
    """以中位切割擷取主色，依佔比由多到少排序"""
    small = img.convert('RGB').copy()
    small.thumbnail((160, 160))
    q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    counts = sorted(q.getcolors() or [], reverse=True)
    return [tuple(pal[i * 3:i * 3 + 3]) for _c, i in counts][:n]


def trim_workspace(img: Image.Image) -> Image.Image:
    """裁掉 SAI2 畫布視窗四周的單色工作區（以左上角顏色為背景）"""
    rgb = img.convert('RGB')
    bg = rgb.getpixel((2, 2))
    diff = ImageChops.difference(rgb, Image.new('RGB', rgb.size, bg)).convert('L')
    box = diff.point(lambda v: 255 if v > 18 else 0).getbbox()
    if not box:
        return rgb
    bw, bh = box[2] - box[0], box[3] - box[1]
    if bw * bh < rgb.size[0] * rgb.size[1] * 0.05:
        return rgb   # 裁切結果過小，多半是誤判，保留原圖
    return rgb.crop(box)


def capture_sai2_canvas() -> Image.Image | None:
    """擷取 SAI2 畫布視窗（沿用縮時錄影的視窗尋找與 GDI 擷取）"""
    from timelapse import find_canvas_hwnd, capture_window_gdi
    hwnd = find_canvas_hwnd(os.getpid())
    if not hwnd:
        return None
    img = capture_window_gdi(hwnd)
    return trim_workspace(img) if img is not None else None


def _btn(parent, text, cmd, bg=CARD2, hbg=CARD3, fg=TEXT, font=FT_NORM, **kw):
    kw.setdefault('padx', 8)
    kw.setdefault('pady', 3)
    b = tk.Button(parent, text=text, command=cmd, font=font, bg=bg, fg=fg,
                  activebackground=hbg, activeforeground='white', relief='flat', cursor='hand2', **kw)
    b.bind('<Enter>', lambda _e: b['state'] != 'disabled' and b.config(bg=hbg))
    b.bind('<Leave>', lambda _e: b['state'] != 'disabled' and b.config(bg=b._base_bg))
    b._base_bg = bg
    return b


def _set_btn_bg(b, bg):
    b._base_bg = bg
    b.config(bg=bg)


class StudyWindow(tk.Toplevel):
    """臨摹研究視窗。app 需提供 quests（QuestManager）與 _settings；
    topmost_fn(win, on) 用 Win32 鎖定置頂；checkin_fn(uid) 開啟打卡流程。"""

    RESIZE_DELAY_MS = 120

    def __init__(self, parent, app, uid: str, cache_dir: str,
                 topmost_fn=None, checkin_fn=None):
        super().__init__(parent)
        self.app = app
        self.uid = uid
        self.cache_dir = cache_dir
        self.topmost_fn = topmost_fn
        self.checkin_fn = checkin_fn
        task = app.quests.task(uid)
        self.lesson = study_lessons.lesson(task['params'].get('lesson_id', '')) if task else None
        self.title('🖌️ 臨摹研究')
        self.configure(bg=BG)
        self.minsize(820, 560)

        # 檢查工具狀態（依課程預設開啟）
        tools = set(self.lesson['tools']) if self.lesson else set()
        self.flip = False
        self.gray = 'gray' in tools
        self.value_levels = 3 if 'value3' in tools else 5 if 'value5' in tools else 0
        self.guide = next((g for g in ('thirds', 'grid', 'diagonal') if g in tools), 'none')
        self.show_palette = 'palette' in tools
        self.compare = False

        self.ref_img: Image.Image | None = None
        self.capture_img: Image.Image | None = None
        self.crop = app._settings.get('study_compare_crop')    # 比對畫布的框選範圍（比例）
        self._photo = None
        self._layout = None            # 最近一次比對版面：右側畫布在顯示圖中的位置與縮放
        self._drag_start = None
        self._loading = False
        self._last_phase = None
        self._destroyed = False
        self._jobs: dict[str, str] = {}

        self._build_ui()
        w, h = 1080, 720
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f'{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.img_holder.bind('<Configure>', self._on_resize)

        self._apply_topmost()
        self._load_reference()
        self._tick()

    # ── 版面 ──────────────────────────────────────────────────────────
    def _build_ui(self):
        les = self.lesson
        task = self.app.quests.task(self.uid)

        hdr = tk.Frame(self, bg=CARD, padx=14, pady=8)
        hdr.pack(fill='x')
        right = tk.Frame(hdr, bg=CARD)
        right.pack(side='right', anchor='n')
        self.var_top = tk.BooleanVar(value=bool(self.app._settings.get('study_topmost', True)))
        tk.Checkbutton(right, text='置頂', variable=self.var_top, command=self._toggle_topmost,
                       font=FT_SMALL, fg=TEXT, bg=CARD, selectcolor=CARD2, activebackground=CARD,
                       activeforeground=TEXT).pack(anchor='e')

        skill = self.app.quests.skill(les['skill']) if les else None
        title = (f"{skill['icon'] if skill else '🖌️'} {skill['name'] if skill else ''} Lv{les['level']}"
                 f"・{les['name']}") if les else (task['name'] if task else '臨摹研究')
        tk.Label(hdr, text=title, font=FT_TITLE, fg=TEXT, bg=CARD, anchor='w').pack(fill='x')
        if les:
            tk.Label(hdr, text=f"🎯 目標：{les['goal']}", font=FT_NORM, fg=TEXT, bg=CARD,
                     anchor='w', justify='left', wraplength=900).pack(fill='x', pady=(2, 0))
            tk.Label(hdr, text=f"👁 本次只專注：{les['focus']}", font=FT_HEAD, fg=YELLOW, bg=CARD,
                     anchor='w', justify='left', wraplength=900).pack(fill='x', pady=(2, 0))

        # 工具列
        bar = tk.Frame(self, bg=CARD2, padx=10, pady=5)
        bar.pack(fill='x')
        self.b_flip = _btn(bar, '↔ 翻轉', self._toggle_flip)
        self.b_gray = _btn(bar, '◐ 灰階', self._toggle_gray)
        self.b_value = _btn(bar, '', self._cycle_value)
        self.b_guide = _btn(bar, '', self._cycle_guide)
        self.b_palette = _btn(bar, '🎨 主色', self._toggle_palette)
        self.b_compare = _btn(bar, '🔍 比對畫布', self._toggle_compare)
        for b in (self.b_flip, self.b_gray, self.b_value, self.b_guide, self.b_palette, self.b_compare):
            b.pack(side='left', padx=(0, 4))
        _btn(bar, '📁 自選圖檔', self._choose_file).pack(side='right')
        _btn(bar, '🔄 換一張', self._next_reference).pack(side='right', padx=(0, 4))
        self.b_canvas = _btn(bar, '🆕 練習畫布', self._canvas_menu, bg=TEAL, hbg=TEAL_H)   # 與「已開啟」的工具色區隔
        self.b_canvas.pack(side='right', padx=(0, 10))
        self.b_recapture = _btn(bar, '📸 重新擷取', self._capture)

        # 主體：左圖右課程
        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True, padx=10, pady=8)
        side = tk.Frame(body, bg=CARD, width=300, padx=12, pady=10)
        side.pack(side='right', fill='y', padx=(8, 0))
        side.pack_propagate(False)
        left = tk.Frame(body, bg=BG)
        left.pack(side='left', fill='both', expand=True)
        # 參考資料與主色放在圖片下方（側欄高度有限，放不下時會被截斷）
        info = tk.Frame(left, bg=CARD, padx=10, pady=6)
        info.pack(side='bottom', fill='x', pady=(6, 0))
        self.palette_box = tk.Frame(info, bg=CARD)
        self.palette_box.pack(side='right', anchor='n', padx=(10, 0))
        self.var_ref = tk.StringVar(value='讀取中…')
        ref_lbl = tk.Label(info, textvariable=self.var_ref, font=FT_SMALL, fg=TEXTD, bg=CARD, anchor='w',
                           justify='left', wraplength=460)
        ref_lbl.pack(fill='x')
        # 換行寬度跟著可用寬度走（右側主色色票寬度會變動）
        ref_lbl.bind('<Configure>', lambda e: ref_lbl.config(wraplength=max(120, e.width - 4)))
        self.b_source = _btn(info, '🔗 開啟來源頁面', self._open_source, font=FT_SMALL, pady=1)
        self.b_source.pack(anchor='w', pady=(4, 0))
        self.img_holder = tk.Frame(left, bg=IMG_BG)
        self.img_holder.pack(side='top', fill='both', expand=True)
        self.img_holder.pack_propagate(False)
        self.img_label = tk.Label(self.img_holder, bg=IMG_BG, fg=TEXTD, font=FT_NORM, text='讀取參考圖中…')
        self.img_label.pack(fill='both', expand=True)
        self.img_label.bind('<ButtonPress-1>', self._crop_start)
        self.img_label.bind('<B1-Motion>', self._crop_move)
        self.img_label.bind('<ButtonRelease-1>', self._crop_end)
        self.crop_rect = None   # 拖曳框選時的暫時外框（顯示用）

        self._build_side(side)

        # 底列：進度與打卡
        foot = tk.Frame(self, bg=CARD, padx=12, pady=7)
        foot.pack(fill='x')
        self.var_progress = tk.StringVar()
        tk.Label(foot, textvariable=self.var_progress, font=FT_HEAD, fg=TEXT, bg=CARD).pack(side='left')
        self.var_status = tk.StringVar()
        tk.Label(foot, textvariable=self.var_status, font=FT_SMALL, fg=TEXTD, bg=CARD).pack(side='left', padx=12)
        # 在未存檔的新畫布上作畫時，追蹤器不會計時 → 提醒使用者建立練習畫布或先存檔
        self.var_warn = tk.StringVar()
        tk.Label(foot, textvariable=self.var_warn, font=FT_SMALL, fg=YELLOW, bg=CARD).pack(side='left')
        self.b_checkin = _btn(foot, '✔ 完成打卡', self._checkin, bg=CARD2)
        self.b_checkin.pack(side='right')
        self.b_timer = _btn(foot, '', self._toggle_timer)
        self.b_timer.pack(side='right', padx=(0, 6))
        self._refresh_tool_buttons()

    def _section(self, parent, title):
        tk.Label(parent, text=title, font=FT_HEAD, fg=TEXT, bg=CARD, anchor='w').pack(fill='x', pady=(10, 2))

    def _bullets(self, parent, items, fg=TEXTD):
        for it in items:
            # 不換行空白：中文沒有空格可斷行，一般空白會讓 Tk 在「•」後面直接換行
            tk.Label(parent, text=f'• {it}', font=FT_SMALL, fg=fg, bg=CARD, anchor='w', justify='left',
                     wraplength=270).pack(fill='x')

    def _build_side(self, side):
        les = self.lesson
        # 目前階段
        self.phase_box = tk.Frame(side, bg=CARD2, padx=10, pady=8)
        self.phase_box.pack(fill='x')
        self.var_phase = tk.StringVar(value='—')
        self.var_phase_left = tk.StringVar(value='')
        self.var_phase_tip = tk.StringVar(value='')
        self.lbl_phase = tk.Label(self.phase_box, textvariable=self.var_phase, font=FT_PHASE, fg=TEXT,
                                  bg=CARD2, anchor='w')
        self.lbl_phase.pack(fill='x')
        tk.Label(self.phase_box, textvariable=self.var_phase_left, font=FT_SMALL, fg=YELLOW, bg=CARD2,
                 anchor='w').pack(fill='x')
        tk.Label(self.phase_box, textvariable=self.var_phase_tip, font=FT_NORM, fg=TEXT, bg=CARD2,
                 anchor='w', justify='left', wraplength=260).pack(fill='x', pady=(4, 0))

        self.phase_labels = []
        if les:
            self._section(side, f"分段步驟（共 {les['minutes']} 分）")
            for ph in les['phases']:
                lbl = tk.Label(side, text=f"○ {ph['name']}　{ph['minutes']} 分", font=FT_SMALL,
                               fg=TEXTD, bg=CARD, anchor='w')
                lbl.pack(fill='x')
                self.phase_labels.append(lbl)
            self._section(side, '⚠ 常見錯誤')
            self._bullets(side, les['mistakes'])
            self._section(side, '✅ 完成檢查')
            self._bullets(side, les['checks'])

    # ── 置頂 ──────────────────────────────────────────────────────────
    def _apply_topmost(self):
        on = bool(self.var_top.get())
        try:
            self.wm_attributes('-topmost', on)
        except Exception:
            pass
        if self.topmost_fn:
            self.topmost_fn(self, on)

    def _toggle_topmost(self):
        self.app._settings['study_topmost'] = bool(self.var_top.get())
        self._apply_topmost()

    # ── 參考圖 ────────────────────────────────────────────────────────
    def _load_reference(self):
        task = self.app.quests.task(self.uid)
        ref = (task or {}).get('ref') or {}
        cache = ref.get('cache')
        if cache and os.path.isfile(cache):
            try:
                with Image.open(cache) as im:
                    self.ref_img = im.convert('RGB')
                self._show_ref_meta(ref)
                self._render()
                return
            except Exception:
                pass
        self._fetch_reference()

    def _fetch_reference(self):
        if self._loading or not self.lesson:
            if not self.lesson:
                self.img_label.config(text='這個任務沒有對應的課程，可按「📁 自選圖檔」', image='')
            return
        self._loading = True
        self.var_status.set('🌐 正在尋找參考圖…')
        exclude = self.app.quests.seen_refs(self.lesson['id'])
        settings = dict(self.app._settings)

        def worker():
            img, meta, err = None, None, None
            try:
                img, meta = study_refs.fetch_reference(self.lesson, settings, exclude, random.Random())
            except Exception as e:
                err = str(e)

            def done():
                self._loading = False
                if self._destroyed:
                    return
                if img is None:
                    self.var_status.set('')
                    self.img_label.config(text=f'⚠ {err}', image='')
                    self.var_ref.set('—')
                    return
                self._set_reference(img, meta)
            try:
                self.after(0, done)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _set_reference(self, img: Image.Image, meta: dict):
        n = len(self.app.quests.seen_refs(self.lesson['id'])) if self.lesson else 0
        try:
            meta['cache'] = study_refs.save_cache(img, self.cache_dir, f'{self.uid}_{n}')
        except Exception as e:
            print(f'[Study] cache error: {e}')
        self.app.quests.set_task_ref(self.uid, meta)
        self.app.quests.save(force=True)
        self.ref_img = img
        self.var_status.set('')
        self._show_ref_meta(meta)
        self._render()

    def _show_ref_meta(self, meta: dict):
        lines = [meta.get('title') or '（未命名）']
        who = '，'.join(x for x in (meta.get('artist'), meta.get('date')) if x)
        if who:
            lines.append(who)
        lines.append(' · '.join(x for x in (meta.get('source'), meta.get('license')) if x))
        if meta.get('why'):
            lines.append(f"💡 {meta['why']}")
        self.var_ref.set('\n'.join(lines))
        self._ref_url = meta.get('url') or ''
        self.b_source.config(state='normal' if self._ref_url.startswith('http') else 'disabled')
        if self.show_palette:
            self._render_palette()

    def _open_source(self):
        if getattr(self, '_ref_url', '').startswith('http'):
            webbrowser.open(self._ref_url)

    def _next_reference(self):
        self._fetch_reference()

    def _choose_file(self):
        path = filedialog.askopenfilename(
            title='選擇參考圖', parent=self,
            filetypes=[('圖片檔案', '*.png;*.jpg;*.jpeg;*.webp;*.bmp'), ('所有檔案', '*.*')])
        if not path:
            return
        try:
            img, meta = study_refs.load_local_file(path)
        except Exception as e:
            messagebox.showerror('讀取失敗', f'無法開啟圖片：{e}', parent=self)
            return
        meta['why'] = self.lesson.get('look_for', '') if self.lesson else ''
        self._set_reference(img, meta)

    # ── 練習畫布 ──────────────────────────────────────────────────────
    def _canvas_menu(self):
        m = tk.Menu(self, tearoff=0, bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground='white',
                    font=FT_NORM)
        task = self.app.quests.task(self.uid) or {}
        existing = task.get('canvas')
        if existing and os.path.isfile(existing):
            m.add_command(label=f'📂 開啟這次的練習畫布：{os.path.basename(existing)}',
                          command=lambda: self._open_canvas(existing))
            m.add_separator()
        ratio = '與參考圖同比例' if self.ref_img is not None else '3:4 直式（尚無參考圖）'
        for side in CANVAS_SIDES:
            m.add_command(label=f'🆕 建立新畫布：長邊 {side}px（{ratio}）',
                          command=lambda s=side: self._create_canvas(s))
        m.add_separator()
        m.add_command(label=f'📁 存放位置：{self._canvas_dir()}', state='disabled')
        m.tk_popup(self.b_canvas.winfo_rootx(), self.b_canvas.winfo_rooty() + self.b_canvas.winfo_height())

    def _canvas_dir(self) -> str:
        base = self.app._settings.get('study_canvas_dir') or os.path.join(_documents_dir(), 'SAI2 練習')
        skill = self.app.quests.skill(self.lesson['skill']) if self.lesson else None
        return os.path.join(base, _safe_filename(skill['name'])) if skill else base

    def _canvas_name(self) -> str:
        task = self.app.quests.task(self.uid) or {}
        if self.lesson:
            skill = self.app.quests.skill(self.lesson['skill'])
            stem = f"{skill['name'] if skill else ''}_Lv{self.lesson['level']}_{self.lesson['name']}"
        else:
            stem = task.get('name', '臨摹研究')
        return _safe_filename(f"{stem}_{time.strftime('%Y%m%d')}")

    def _create_canvas(self, long_side: int):
        """建立與參考圖同比例、已命名的空白 PSD，並用 SAI2 開啟（已命名的檔案才會被計時）"""
        if self.ref_img is not None:
            rw, rh = self.ref_img.size
        else:
            rw, rh = 3, 4
        scale = long_side / max(rw, rh)
        w, h = max(1, round(rw * scale)), max(1, round(rh * scale))
        folder = self._canvas_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            stem = self._canvas_name()
            path = os.path.join(folder, f'{stem}.psd')
            n = 2
            while os.path.exists(path):
                path = os.path.join(folder, f'{stem}_{n}.psd')
                n += 1
            write_blank_psd(path, w, h)
        except Exception as e:
            messagebox.showerror('建立畫布失敗', f'無法建立練習畫布：{e}', parent=self)
            return
        task = self.app.quests.task(self.uid)
        if task is not None:
            task['canvas'] = path
            self.app.quests.mark_dirty()
            self.app.quests.save(force=True)
        self.var_status.set(f'🆕 已建立 {w}×{h} 畫布：{os.path.basename(path)}')
        self._open_canvas(path)

    def _open_canvas(self, path: str):
        opener = getattr(self.app, 'open_in_sai2', None)
        if opener:
            opener(path)
        else:
            os.startfile(path)
        self.var_status.set(f'📂 已要求 SAI2 開啟：{os.path.basename(path)}（畫完記得 Ctrl+S 存回 PSD）')

    # ── 檢查工具 ──────────────────────────────────────────────────────
    def _refresh_tool_buttons(self):
        _set_btn_bg(self.b_flip, ACCENT if self.flip else CARD2)
        _set_btn_bg(self.b_gray, ACCENT if self.gray and not self.value_levels else CARD2)
        self.b_value.config(text=f"▤ 明度：{'原圖' if not self.value_levels else f'{self.value_levels} 階'}")
        _set_btn_bg(self.b_value, ACCENT if self.value_levels else CARD2)
        self.b_guide.config(text=f"＃ 輔助線：{dict(GUIDES)[self.guide]}")
        _set_btn_bg(self.b_guide, ACCENT if self.guide != 'none' else CARD2)
        _set_btn_bg(self.b_palette, ACCENT if self.show_palette else CARD2)
        _set_btn_bg(self.b_compare, ACCENT if self.compare else CARD2)
        if self.compare:
            self.b_recapture.pack(side='left', padx=(0, 4))
        else:
            self.b_recapture.pack_forget()

    def _toggle_flip(self):
        self.flip = not self.flip
        self._refresh_tool_buttons()
        self._render()

    def _toggle_gray(self):
        self.gray = not self.gray
        if self.gray:
            self.value_levels = 0
        self._refresh_tool_buttons()
        self._render()

    def _cycle_value(self):
        self.value_levels = VALUE_STEPS[(VALUE_STEPS.index(self.value_levels) + 1) % len(VALUE_STEPS)]
        self._refresh_tool_buttons()
        self._render()

    def _cycle_guide(self):
        keys = [k for k, _ in GUIDES]
        self.guide = keys[(keys.index(self.guide) + 1) % len(keys)]
        self._refresh_tool_buttons()
        self._render()

    def _toggle_palette(self):
        self.show_palette = not self.show_palette
        self._refresh_tool_buttons()
        self._render_palette()

    def _render_palette(self):
        for w in self.palette_box.winfo_children():
            w.destroy()
        if not self.show_palette or self.ref_img is None:
            return
        tk.Label(self.palette_box, text='🎨 參考圖主色（依佔比）', font=FT_HEAD, fg=TEXT, bg=CARD,
                 anchor='w').pack(fill='x')
        row = tk.Frame(self.palette_box, bg=CARD)
        row.pack(fill='x', pady=(2, 0))
        for rgb in extract_palette(self.ref_img):
            hexc = '#%02x%02x%02x' % rgb
            cell = tk.Frame(row, bg=CARD)
            cell.pack(side='left', padx=(0, 3))
            tk.Frame(cell, bg=hexc, width=38, height=26, highlightthickness=1,
                     highlightbackground=BORDER).pack()
            tk.Label(cell, text=hexc[1:], font=('Consolas', 7), fg=TEXTD, bg=CARD).pack()

    def _process(self, img: Image.Image) -> Image.Image:
        if self.flip:
            img = ImageOps.mirror(img)
        if self.value_levels:
            img = posterize_value(img, self.value_levels)
        elif self.gray:
            img = img.convert('L').convert('RGB')
        return img

    def _draw_guides(self, img: Image.Image) -> Image.Image:
        if self.guide == 'none':
            return img
        img = img.copy()
        d = ImageDraw.Draw(img)
        w, h = img.size
        if self.guide in ('thirds', 'grid'):
            n = 3
            for i in range(1, n):
                d.line([(w * i / n, 0), (w * i / n, h)], fill=GUIDE, width=1)
                d.line([(0, h * i / n), (w, h * i / n)], fill=GUIDE, width=1)
            if self.guide == 'grid':
                # 九宮格再細分一層，方便臨摹時對照局部比例
                for i in range(1, 6, 2):
                    d.line([(w * i / 6, 0), (w * i / 6, h)], fill=(GUIDE[0] // 2, GUIDE[1] // 2, GUIDE[2] // 2))
                    d.line([(0, h * i / 6), (w, h * i / 6)], fill=(GUIDE[0] // 2, GUIDE[1] // 2, GUIDE[2] // 2))
        else:
            d.line([(0, 0), (w, h)], fill=GUIDE, width=1)
            d.line([(w, 0), (0, h)], fill=GUIDE, width=1)
        return img

    # ── 比對模式 ──────────────────────────────────────────────────────
    def _toggle_compare(self):
        self.compare = not self.compare
        self._refresh_tool_buttons()
        if self.compare and self.capture_img is None:
            self._capture()
        else:
            self._render()

    def _capture(self):
        try:
            img = capture_sai2_canvas()
        except Exception as e:
            img = None
            print(f'[Study] capture error: {e}')
        if img is None:
            self.var_status.set('⚠ 找不到 SAI2 畫布視窗，請確認 SAI2 已開啟圖檔')
        else:
            self.capture_img = img
            self.var_status.set('📸 已擷取畫布（可在右側拖曳框選畫布範圍）')
        self._render()

    def _cropped_capture(self) -> Image.Image | None:
        img = self.capture_img
        if img is None or not self.crop:
            return img
        w, h = img.size
        x0, y0, x1, y1 = self.crop
        box = (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))
        if box[2] - box[0] < 10 or box[3] - box[1] < 10:
            return img
        return img.crop(box)

    def _crop_start(self, e):
        lay = self._layout
        if not (self.compare and lay and lay['x'] <= e.x <= lay['x'] + lay['w']):
            self._drag_start = None
            return
        self._drag_start = (e.x, e.y)

    def _crop_move(self, e):
        if self._drag_start:
            self.crop_rect = (*self._drag_start, e.x, e.y)
            self._render(keep_layout=True)

    def _crop_end(self, e):
        if not self._drag_start or not self._layout:
            return
        lay = self._layout
        x0, y0 = self._drag_start
        self._drag_start = None
        self.crop_rect = None
        if abs(e.x - x0) < 12 or abs(e.y - y0) < 12:
            # 單擊（沒有拖曳）= 清除框選，回到整個畫布
            self.crop = None
        else:
            # 顯示座標 → 目前（已框選）影像上的比例 → 換算回原始擷取影像的比例
            def to_frac(px, py):
                fx = min(1.0, max(0.0, (px - lay['x']) / lay['w']))
                fy = min(1.0, max(0.0, (py - lay['y']) / lay['h']))
                if self.flip:
                    fx = 1.0 - fx
                return fx, fy
            ax, ay = to_frac(x0, y0)
            bx, by = to_frac(e.x, e.y)
            base = self.crop or (0.0, 0.0, 1.0, 1.0)
            bw, bh = base[2] - base[0], base[3] - base[1]
            self.crop = (base[0] + min(ax, bx) * bw, base[1] + min(ay, by) * bh,
                         base[0] + max(ax, bx) * bw, base[1] + max(ay, by) * bh)
        self.app._settings['study_compare_crop'] = self.crop
        self._render()

    # ── 繪製 ──────────────────────────────────────────────────────────
    def _on_resize(self, _e=None):
        job = self._jobs.pop('resize', None)
        if job:
            self.after_cancel(job)
        self._jobs['resize'] = self.after(self.RESIZE_DELAY_MS, self._render)

    @staticmethod
    def _fit(img: Image.Image, w: int, h: int) -> Image.Image:
        s = min(w / img.size[0], h / img.size[1])
        return img.resize((max(1, int(img.size[0] * s)), max(1, int(img.size[1] * s))), Image.LANCZOS)

    def _render(self, keep_layout: bool = False):
        self._jobs.pop('resize', None)
        if self._destroyed or self.ref_img is None:
            return
        aw, ah = self.img_holder.winfo_width(), self.img_holder.winfo_height()
        if aw < 40 or ah < 40:
            self._jobs['resize'] = self.after(80, self._render)
            return
        cap = self._cropped_capture() if self.compare else None
        if self.compare and cap is not None:
            half = aw // 2 - 6
            top = 22                     # 上方留給「參考 / 你的畫布」標籤
            ih = ah - top
            ref = self._draw_guides(self._process(self._fit(self.ref_img, half, ih)))
            capi = self._draw_guides(self._process(self._fit(cap, half, ih)))
            canvas = Image.new('RGB', (aw, ah), IMG_BG)
            canvas.paste(ref, ((half - ref.size[0]) // 2, top + (ih - ref.size[1]) // 2))
            cx = half + 12 + (half - capi.size[0]) // 2
            cy = top + (ih - capi.size[1]) // 2
            canvas.paste(capi, (cx, cy))
            if not keep_layout or self._layout is None:
                self._layout = {'x': cx, 'y': cy, 'w': capi.size[0], 'h': capi.size[1]}
            d = ImageDraw.Draw(canvas)
            d.text((8, 6), '參考', fill=(200, 200, 200), font=_font())
            d.text((half + 20, 6), '你的畫布（拖曳可框選範圍，單擊取消）', fill=(200, 200, 200), font=_font())
            if self.crop_rect:
                x0, y0, x1, y1 = self.crop_rect
                d.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], outline=(250, 204, 21), width=2)
            img = canvas
        else:
            self._layout = None
            img = self._draw_guides(self._process(self._fit(self.ref_img, aw, ah)))
            if self.compare:
                self.var_status.set('⚠ 尚未擷取到畫布，按「📸 重新擷取」再試一次')
        self._photo = ImageTk.PhotoImage(img)
        self.img_label.config(image=self._photo, text='')

    # ── 計時與階段 ────────────────────────────────────────────────────
    def _phase_at(self, seconds: float):
        """依累計秒數回傳 (階段索引, 本階段剩餘秒數)；超過總時間時停在最後一階段"""
        phases = self.lesson['phases'] if self.lesson else []
        acc = 0
        for i, ph in enumerate(phases):
            acc += ph['minutes'] * 60
            if seconds < acc:
                return i, acc - seconds
        return (len(phases) - 1, 0) if phases else (None, 0)

    def _tick(self):
        if self._destroyed:
            return
        task = self.app.quests.task(self.uid)
        if not task:
            self.close()
            return
        prog = task['progress']
        studying = self.app.quests.active_study == self.uid
        self.var_progress.set(f"⏱ 實際動筆 {int(prog // 60)} / {task['target'] // 60} 分"
                              + ('　● 計時中' if studying else '　（計時已暫停）'))
        self.b_timer.config(text='■ 暫停計時' if studying else '▶ 繼續計時')
        self.var_warn.set(self._unsaved_warning() if studying else '')
        if task['status'] in ('ready', 'done'):
            _set_btn_bg(self.b_checkin, GREEN)
            self.b_checkin.config(text='✔ 完成打卡' if task['status'] == 'ready' else '✓ 已打卡',
                                  state='normal' if task['status'] == 'ready' else 'disabled')
        idx, left = self._phase_at(prog)
        if idx is not None:
            ph = self.lesson['phases'][idx]
            self.var_phase.set(f"{idx + 1}. {ph['name']}")
            self.var_phase_left.set('已達預定時間，可以比對修正後打卡' if left <= 0
                                    else f'此階段約剩 {math.ceil(left / 60)} 分（以實際動筆計）')
            self.var_phase_tip.set(ph['tip'])
            for i, lbl in enumerate(self.phase_labels):
                mark = '✓' if i < idx else '▶' if i == idx else '○'
                lbl.config(text=f"{mark} {self.lesson['phases'][i]['name']}　{self.lesson['phases'][i]['minutes']} 分",
                           fg=YELLOW if i == idx else (TEXT if i < idx else TEXTD))
            if self._last_phase is not None and idx != self._last_phase:
                self._announce_phase(ph)
            self._last_phase = idx
        self._jobs['tick'] = self.after(1000, self._tick)

    def _unsaved_warning(self) -> str:
        """SAI2 開著、偵測到畫布但因為未存檔而沒被追蹤時，動筆不會計入研究時間"""
        tracker = getattr(self.app, 'tracker', None)
        if tracker is None:
            return ''
        try:
            st = tracker.get_state()
        except Exception:
            return ''
        if st.get('sai2_running') and st.get('raw_current_file') and not st.get('current_file'):
            return '⚠ 目前的畫布尚未存檔，動筆不會計時 → 按「🆕 練習畫布」或先存檔'
        return ''

    def _announce_phase(self, ph):
        """換階段：響一聲並讓階段區塊閃爍，提醒換一種畫法"""
        try:
            self.bell()
        except Exception:
            pass
        flashes = [ACCENT, CARD2, ACCENT, CARD2]

        def step(i=0):
            if self._destroyed or i >= len(flashes):
                return
            for w in (self.phase_box, *self.phase_box.winfo_children()):
                w.config(bg=flashes[i])
            self.after(250, step, i + 1)
        step()
        try:
            self.app.var_status.set(f"🖌️ 進入「{ph['name']}」：{ph['tip']}")
        except Exception:
            pass

    def _toggle_timer(self):
        q = self.app.quests
        if q.active_study == self.uid:
            q.stop_study()
        else:
            q.start_study(self.uid)
        q.save(force=True)
        if hasattr(self.app, '_quest_render'):
            self.app._quest_render(force=True)

    def _checkin(self):
        task = self.app.quests.task(self.uid)
        if self.checkin_fn and task:
            # 未達預定時間時以「自行回報」打卡（主程式會先確認）
            self.checkin_fn(self.uid, self_report=task['status'] != 'ready')
        task = self.app.quests.task(self.uid)
        if task and task['status'] == 'done':
            self.close(stop_timer=False)

    def close(self, stop_timer: bool = True):
        if self._destroyed:
            return
        self._destroyed = True
        for job in self._jobs.values():
            try:
                self.after_cancel(job)
            except Exception:
                pass
        if stop_timer and self.app.quests.active_study == self.uid:
            # 關閉參考視窗 = 結束這次研究，避免之後的一般繪圖被算進研究時間
            self.app.quests.stop_study()
            self.app.quests.save(force=True)
            if hasattr(self.app, '_quest_render'):
                self.app._quest_render(force=True)
        if getattr(self.app, '_study_win', None) is self:
            self.app._study_win = None
        self.destroy()


class StudyCheckinDialog(tk.Toplevel):
    """臨摹研究的打卡對話框：依課程的完成檢查自評 1~5 分並留心得。
    result 為 (rating, note)，取消時為 None。"""

    RATINGS = [(1, '還差很多'), (2, '有些地方抓到'), (3, '大致做到'), (4, '做得不錯'), (5, '非常接近')]

    def __init__(self, parent, task: dict, lesson: dict | None, pass_rating: int = 3):
        super().__init__(parent)
        self.result = None
        self.title('打卡：自我檢查')
        self.configure(bg=CARD, padx=18, pady=14)
        self.resizable(False, False)
        self.transient(parent)

        tk.Label(self, text=f"🎉 完成「{task['name']}」！", font=FT_TITLE, fg=TEXT, bg=CARD,
                 anchor='w').pack(fill='x')
        if lesson:
            tk.Label(self, text=f"本次專注：{lesson['focus']}", font=FT_NORM, fg=YELLOW, bg=CARD,
                     anchor='w', justify='left', wraplength=420).pack(fill='x', pady=(4, 6))
            tk.Label(self, text='對照下列問題，誠實評估這次的成果：', font=FT_NORM, fg=TEXT, bg=CARD,
                     anchor='w').pack(fill='x')
            for c in lesson['checks']:
                tk.Label(self, text=f'• {c}', font=FT_NORM, fg=TEXTD, bg=CARD, anchor='w', justify='left',
                         wraplength=420).pack(fill='x')

        self.var_rating = tk.IntVar(value=pass_rating)
        row = tk.Frame(self, bg=CARD)
        row.pack(fill='x', pady=(10, 2))
        for v, label in self.RATINGS:
            tk.Radiobutton(row, text=f'{v}\n{label}', value=v, variable=self.var_rating, indicatoron=0,
                           font=FT_SMALL, fg=TEXT, bg=CARD2, selectcolor=ACCENT, activebackground=CARD3,
                           activeforeground='white', width=9, pady=4, cursor='hand2'
                           ).pack(side='left', padx=(0, 4))
        tk.Label(self, text=f'自評 {pass_rating} 分以上會進入下一課；低於 {pass_rating} 分下次換一張參考圖再練一次。',
                 font=FT_SMALL, fg=TEXTD, bg=CARD, anchor='w', wraplength=420, justify='left').pack(fill='x')

        tk.Label(self, text='心得（可留白）：', font=FT_NORM, fg=TEXT, bg=CARD, anchor='w').pack(fill='x', pady=(10, 2))
        self.var_note = tk.StringVar()
        ent = tk.Entry(self, textvariable=self.var_note, font=FT_NORM, bg=CARD2, fg=TEXT,
                       insertbackground=TEXT, relief='flat', width=52)
        ent.pack(fill='x', ipady=3)
        ent.focus_set()

        btns = tk.Frame(self, bg=CARD)
        btns.pack(fill='x', pady=(12, 0))
        _btn(btns, '取消', self.destroy).pack(side='right')
        _btn(btns, '✔ 打卡', self._ok, bg=ACCENT, hbg=ACCH).pack(side='right', padx=(0, 6))
        self.bind('<Return>', lambda _e: self._ok())
        self.bind('<Escape>', lambda _e: self.destroy())

        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        self.geometry(f'+{px + 60}+{py + 60}')
        try:
            self.wm_attributes('-topmost', True)   # 研究視窗可能置頂，對話框需在其上方
        except Exception:
            pass
        self.grab_set()
        self.wait_window()

    def _ok(self):
        self.result = (int(self.var_rating.get()), self.var_note.get().strip())
        self.destroy()
