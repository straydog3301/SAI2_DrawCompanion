# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk, ImageGrab
import math
import io
import ctypes
import ctypes.wintypes
import os
import threading
import queue
import time
import winsound
import json

# Win32 剪貼簿與鍵盤/視窗相關常數
CF_DIB = 8
CF_DIBV5 = 17       # Windows 系統中的 DIBV5 格式 ID
CF_HDROP = 15       # Windows 系統中的 HDROP 檔案格式 ID
GMEM_MOVEABLE = 0x0002
WM_HOTKEY = 0x0312

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 64 位元 Windows 安全類型聲明 (防止指標位址被截斷)
kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL

kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p

kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL

kernel32.GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalFree.restype = ctypes.wintypes.HGLOBAL

kernel32.GlobalSize.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t

user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
user32.OpenClipboard.restype = ctypes.wintypes.BOOL

user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = ctypes.wintypes.BOOL

user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = ctypes.wintypes.BOOL

user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
user32.SetClipboardData.restype = ctypes.wintypes.HANDLE

user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
user32.GetClipboardData.restype = ctypes.wintypes.HANDLE

user32.RegisterClipboardFormatW.argtypes = [ctypes.wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = ctypes.wintypes.UINT

user32.IsClipboardFormatAvailable.argtypes = [ctypes.wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = ctypes.wintypes.BOOL

# 註冊 PNG 剪貼簿格式以支援現代跨平台透明度
PNG_FORMAT_ID = user32.RegisterClipboardFormatW("PNG")

class BITMAPV5HEADER(ctypes.Structure):
    """
    Win32 BITMAPV5HEADER 結構，用於攜帶 32-bit 透明度 (Alpha) 的未經壓縮像素。
    大小固定為 124 位元組。
    """
    _fields_ = [
        ("bV5Size", ctypes.wintypes.DWORD),
        ("bV5Width", ctypes.wintypes.LONG),
        ("bV5Height", ctypes.wintypes.LONG),
        ("bV5Planes", ctypes.wintypes.WORD),
        ("bV5BitCount", ctypes.wintypes.WORD),
        ("bV5Compression", ctypes.wintypes.DWORD),
        ("bV5SizeImage", ctypes.wintypes.DWORD),
        ("bV5XPelsPerMeter", ctypes.wintypes.LONG),
        ("bV5YPelsPerMeter", ctypes.wintypes.LONG),
        ("bV5ClrUsed", ctypes.wintypes.DWORD),
        ("bV5ClrImportant", ctypes.wintypes.DWORD),
        ("bV5RedMask", ctypes.wintypes.DWORD),
        ("bV5GreenMask", ctypes.wintypes.DWORD),
        ("bV5BlueMask", ctypes.wintypes.DWORD),
        ("bV5AlphaMask", ctypes.wintypes.DWORD),
        ("bV5CSType", ctypes.wintypes.DWORD),
        ("bV5Endpoints", ctypes.wintypes.BYTE * 36),
        ("bV5GammaRed", ctypes.wintypes.DWORD),
        ("bV5GammaGreen", ctypes.wintypes.DWORD),
        ("bV5GammaBlue", ctypes.wintypes.DWORD),
        ("bV5Intent", ctypes.wintypes.DWORD),
        ("bV5ProfileData", ctypes.wintypes.DWORD),
        ("bV5ProfileSize", ctypes.wintypes.DWORD),
        ("bV5Reserved", ctypes.wintypes.DWORD),
    ]

def make_dibv5_data(pil_img):
    """
    將 PIL Image 轉換為帶有 BITMAPV5HEADER 的 32-bit RGBA 記憶體區塊。
    """
    width, height = pil_img.size
    # 轉換為 Windows 的 BGRA 原生像素結構位元組
    pixel_data = pil_img.tobytes("raw", "BGRA")
    
    header = BITMAPV5HEADER()
    header.bV5Size = 124
    header.bV5Width = width
    header.bV5Height = -height  # 使用負數表示 Top-Down (自上而下) 的點陣圖，與 PIL 的 tobytes 順序一致
    header.bV5Planes = 1
    header.bV5BitCount = 32     # 32 位元 (8-B, 8-G, 8-R, 8-A)
    header.bV5Compression = 3   # BI_BITFIELDS
    header.bV5SizeImage = len(pixel_data)
    header.bV5XPelsPerMeter = 2835  # 72 DPI
    header.bV5YPelsPerMeter = 2835
    header.bV5ClrUsed = 0
    header.bV5ClrImportant = 0
    # 定義 RGBA 的位元遮罩
    header.bV5RedMask = 0x00ff0000
    header.bV5GreenMask = 0x0000ff00
    header.bV5BlueMask = 0x000000ff
    header.bV5AlphaMask = 0xff000000
    header.bV5CSType = 0x73524742  # sRGB (LCS_sRGB)
    
    return bytes(header) + pixel_data

def copy_image_to_clipboard(pil_img):
    """
    將 PIL Image 同時寫入多種剪貼簿格式以獲得最佳相容性：
    1. CF_DIBV5 (ID 17, 32-bit RGBA, 含透明度) -> SAI2 等專業軟體會優先載入此格式以獲取透明度。
    2. PNG (32-bit RGBA, 含透明度) -> 瀏覽器、Discord 等支援跨平台 PNG 的應用。
    3. CF_DIB (ID 8, 24-bit RGB, 墊白底作為相容備用) -> 不支援透明度的老舊程式。
    """
    has_alpha = pil_img.mode == "RGBA" or "A" in pil_img.getbands()
    
    # 1. 準備 PNG 數據
    png_data = None
    if has_alpha:
        output_png = io.BytesIO()
        pil_img.save(output_png, "PNG")
        png_data = output_png.getvalue()
        output_png.close()

    # 2. 準備 BMP (CF_DIB) 數據 (24-bit RGB, 墊白底)
    output_bmp = io.BytesIO()
    if has_alpha:
        bg_white = Image.new("RGB", pil_img.size, (255, 255, 255))
        bg_white.paste(pil_img, mask=pil_img.split()[3])
        bg_white.save(output_bmp, "BMP")
    else:
        pil_img.convert("RGB").save(output_bmp, "BMP")
    bmp_data = output_bmp.getvalue()[14:]  # 丟棄前 14 個位元組的檔案標頭
    output_bmp.close()

    # 3. 準備 DIBV5 (32-bit RGBA) 數據
    dibv5_data = None
    if has_alpha:
        dibv5_data = make_dibv5_data(pil_img)

    # 4. 重試開啟剪貼簿
    opened = False
    for _ in range(10):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.05)
    if not opened:
        return False

    try:
        user32.EmptyClipboard()

        # 寫入 CF_DIB
        h_bmp_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(bmp_data))
        if h_bmp_global:
            p_bmp = kernel32.GlobalLock(h_bmp_global)
            if p_bmp:
                ctypes.memmove(p_bmp, bmp_data, len(bmp_data))
                kernel32.GlobalUnlock(h_bmp_global)
                user32.SetClipboardData(CF_DIB, h_bmp_global)
            else:
                kernel32.GlobalFree(h_bmp_global)

        # 寫入 CF_DIBV5 (若影像有透明度，則寫入透明 32 位元資訊)
        if dibv5_data:
            h_v5_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dibv5_data))
            if h_v5_global:
                p_v5 = kernel32.GlobalLock(h_v5_global)
                if p_v5:
                    ctypes.memmove(p_v5, dibv5_data, len(dibv5_data))
                    kernel32.GlobalUnlock(h_v5_global)
                    user32.SetClipboardData(CF_DIBV5, h_v5_global)
                else:
                    kernel32.GlobalFree(h_v5_global)

        # 寫入 PNG
        if png_data and PNG_FORMAT_ID:
            h_png_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(png_data))
            if h_png_global:
                p_png = kernel32.GlobalLock(h_png_global)
                if p_png:
                    ctypes.memmove(p_png, png_data, len(png_data))
                    kernel32.GlobalUnlock(h_png_global)
                    user32.SetClipboardData(PNG_FORMAT_ID, h_png_global)
                else:
                    kernel32.GlobalFree(h_png_global)

        return True
    except Exception:
        return False
    finally:
        user32.CloseClipboard()

def read_image_from_clipboard():
    """
    從 Windows 剪貼簿讀取圖像，優先讀取 CF_DIBV5 (32-bit RGBA) 與 PNG 格式以保留透明度通道。
    """
    opened = False
    for _ in range(10):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.05)
    if not opened:
        return None

    try:
        # 1. 優先檢查 CF_DIBV5 (格式 17) - 這是 Windows 原生且 SAI2 複製透明選區時使用的格式
        if user32.IsClipboardFormatAvailable(CF_DIBV5):
            h_data = user32.GetClipboardData(CF_DIBV5)
            if h_data:
                p_data = kernel32.GlobalLock(h_data)
                if p_data:
                    try:
                        size = kernel32.GlobalSize(h_data)
                        if size >= 124:  # 確保大於等於 BITMAPV5HEADER
                            header = BITMAPV5HEADER.from_address(p_data)
                            width = header.bV5Width
                            height = header.bV5Height
                            is_top_down = height < 0
                            height = abs(height)
                            
                            # 像素資料在 header (124 位元組) 之後
                            pixel_bytes = ctypes.string_at(p_data + 124, size - 124)
                            img = Image.frombytes("RGBA", (width, height), pixel_bytes, "raw", "BGRA")
                            if not is_top_down:
                                img = img.transpose(Image.FLIP_TOP_BOTTOM)
                            return img
                    finally:
                        kernel32.GlobalUnlock(h_data)

        # 2. 次優先檢查 PNG 格式
        if PNG_FORMAT_ID and user32.IsClipboardFormatAvailable(PNG_FORMAT_ID):
            h_data = user32.GetClipboardData(PNG_FORMAT_ID)
            if h_data:
                p_data = kernel32.GlobalLock(h_data)
                if p_data:
                    size = kernel32.GlobalSize(h_data)
                    buffer = ctypes.create_string_buffer(size)
                    ctypes.memmove(buffer, p_data, size)
                    kernel32.GlobalUnlock(h_data)
                    
                    png_bytes = buffer.raw[:size]
                    img = Image.open(io.BytesIO(png_bytes))
                    img.load()
                    return img
    except Exception as e:
        print(f"Clipboard Read Failed: {e}")
    finally:
        user32.CloseClipboard()

    # 若無透明格式，退回使用標準 PIL ImageGrab
    return ImageGrab.grabclipboard()

SETTINGS_FILE = "liquify_settings.json"

def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {"brush_size": 80, "brush_strength": 0.5}

def save_settings(size, strength):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"brush_size": size, "brush_strength": strength}, f)
    except:
        pass
class LiquifyEditor(tk.Toplevel):
    """
    液化編輯器視窗 (Toplevel)，由主程式在觸發快捷鍵時建立
    """
    def __init__(self, parent, image, on_save_callback):
        super().__init__(parent.root)
        self.parent = parent
        self.orig_img = image
        self.on_save_callback = on_save_callback
        
        self.title("液化變形中... [Enter] 套用並貼回 | [Esc] 取消")
        self.geometry("1150x850")
        self.configure(bg="#1c1c22")
        
        # 讓編輯視窗永遠置頂，方便直接在畫布上工作
        self.attributes("-topmost", True)
        self.focus_force()
        
        # 載入歷史筆刷設定
        settings = load_settings()
        self.brush_size = settings.get("brush_size", 80)
        self.brush_strength = settings.get("brush_strength", 0.5)
        self.mode = "push"
        self.bg_mode = "checkerboard"
        
        # 歷史紀錄佇列 (Undo/Redo)
        self.undo_stack = []
        self.redo_stack = []
        self.max_history = 50
        
        # 變形與縮放平移參數
        self.cell_size = 8
        self.scale = 1.0          # 原始大圖適應螢幕的縮放比例
        self.zoom_level = 1.0     # 使用者手動縮放比例 (Ctrl+滾輪)
        self.offset_x = 0         # 平移 X 偏移
        self.offset_y = 0         # 平移 Y 偏移
        self.space_held = False   # 是否按著空白鍵
        
        # 平移拖曳用暫存變數
        self.pan_start_x = 0
        self.pan_start_y = 0
        self.pan_init_offset_x = 0
        self.pan_init_offset_y = 0
        
        self.edit_img = None
        self.warped_img = None
        self.tk_img = None
        
        self.grid_x = []
        self.grid_y = []
        
        self.last_mx = None
        self.last_my = None
        
        self.create_widgets()
        self.setup_images(image)
        
        # 鍵盤快捷鍵與空白鍵平移綁定
        self.bind("<bracketleft>", lambda e: self.adjust_brush_size(-5))
        self.bind("<bracketright>", lambda e: self.adjust_brush_size(5))
        self.bind("<Return>", lambda e: self.save_and_close())
        self.bind("<Escape>", lambda e: self.destroy())
        
        # 復原與重做快捷鍵綁定
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-Z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())
        self.bind("<Control-Y>", lambda e: self.redo())
        
        # 全域空白鍵監聽 (用於拖曳畫布)
        self.bind("<KeyPress-space>", self.on_space_press)
        self.bind("<KeyRelease-space>", self.on_space_release)
        
        # 視窗關閉時釋放狀態
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.parent.editor_active = True

    def create_widgets(self):
        # 左側邊欄
        sidebar = tk.Frame(self, bg="#2a2a35", width=220, padx=15, pady=15)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        
        # 標題
        lbl_title = tk.Label(
            sidebar, text="🎨 液化編輯面板", 
            bg="#2a2a35", fg="#ffffff", font=("Microsoft JhengHei", 12, "bold")
        )
        lbl_title.pack(anchor=tk.W, pady=(0, 15))
        
        # 1. 工具模式區
        lbl_tool_sec = tk.Label(
            sidebar, text="工具模式", bg="#2a2a35", fg="#a0a0b0", font=("Microsoft JhengHei", 9, "bold")
        )
        lbl_tool_sec.pack(anchor=tk.W, pady=(5, 5))
        
        self.mode_var = tk.StringVar(value="push")
        modes = [
            ("👇 推拉 (Push)", "push"), 
            ("🔍 膨脹 (Bloat)", "bloat"), 
            ("🌀 收縮 (Pinch)", "pinch"), 
            ("🔄 重建 (Reconstruct)", "reconstruct")
        ]
        for text, val in modes:
            rbtn = tk.Radiobutton(
                sidebar, text=text, variable=self.mode_var, value=val, command=self.change_mode,
                bg="#2a2a35", fg="#d0d0d5", selectcolor="#3a3a4a", activebackground="#2a2a35",
                activeforeground="white", font=("Microsoft JhengHei", 9), anchor=tk.W
            )
            rbtn.pack(fill=tk.X, pady=3)
            
        # 分隔線
        divider1 = tk.Frame(sidebar, bg="#3d3d4d", height=1)
        divider1.pack(fill=tk.X, pady=12)
        
        # 2. 筆刷設定區
        lbl_brush_sec = tk.Label(
            sidebar, text="筆刷設定", bg="#2a2a35", fg="#a0a0b0", font=("Microsoft JhengHei", 9, "bold")
        )
        lbl_brush_sec.pack(anchor=tk.W, pady=(0, 5))
        
        # 筆刷大小
        lbl_size = tk.Label(sidebar, text="大小 [ / ]:", bg="#2a2a35", fg="white", font=("Microsoft JhengHei", 9))
        lbl_size.pack(anchor=tk.W, pady=(5, 2))
        self.size_scale = tk.Scale(
            sidebar, from_=10, to=300, orient=tk.HORIZONTAL, command=self.update_brush_size,
            bg="#2a2a35", fg="white", highlightthickness=0, activebackground="#00ffcc"
        )
        self.size_scale.set(self.brush_size)
        self.size_scale.pack(fill=tk.X, pady=(0, 8))
        
        # 強度
        lbl_strength = tk.Label(sidebar, text="強度:", bg="#2a2a35", fg="white", font=("Microsoft JhengHei", 9))
        lbl_strength.pack(anchor=tk.W, pady=(5, 2))
        self.strength_scale = tk.Scale(
            sidebar, from_=1, to=10, orient=tk.HORIZONTAL, command=self.update_strength,
            bg="#2a2a35", fg="white", highlightthickness=0, activebackground="#00ffcc"
        )
        self.strength_scale.set(int(self.brush_strength * 10))
        self.strength_scale.pack(fill=tk.X, pady=(0, 10))
        
        # 分隔線
        divider2 = tk.Frame(sidebar, bg="#3d3d4d", height=1)
        divider2.pack(fill=tk.X, pady=12)
        
        # 背景模式區
        lbl_bg_sec = tk.Label(
            sidebar, text="背景模式", bg="#2a2a35", fg="#a0a0b0", font=("Microsoft JhengHei", 9, "bold")
        )
        lbl_bg_sec.pack(anchor=tk.W, pady=(0, 5))
        
        self.bg_var = tk.StringVar(value="checkerboard")
        bg_modes = [
            ("🏁 棋盤方格", "checkerboard"),
            ("⚪ 純白背景", "white"),
            ("⚫ 純灰背景", "grey")
        ]
        for text, val in bg_modes:
            rbtn = tk.Radiobutton(
                sidebar, text=text, variable=self.bg_var, value=val, command=self.change_bg_mode,
                bg="#2a2a35", fg="#d0d0d5", selectcolor="#3a3a4a", activebackground="#2a2a35",
                activeforeground="white", font=("Microsoft JhengHei", 9), anchor=tk.W
            )
            rbtn.pack(fill=tk.X, pady=3)
            
        # 分隔線
        divider_bg = tk.Frame(sidebar, bg="#3d3d4d", height=1)
        divider_bg.pack(fill=tk.X, pady=12)
        
        # 3. 歷史紀錄區 (復原/重做)
        lbl_hist_sec = tk.Label(
            sidebar, text="歷史紀錄", bg="#2a2a35", fg="#a0a0b0", font=("Microsoft JhengHei", 9, "bold")
        )
        lbl_hist_sec.pack(anchor=tk.W, pady=(0, 5))
        
        hist_frame = tk.Frame(sidebar, bg="#2a2a35")
        hist_frame.pack(fill=tk.X, pady=2)
        
        self.btn_undo = tk.Button(
            hist_frame, text="↩️ 復原 (Ctrl+Z)", command=self.undo,
            bg="#4a4a5a", fg="white", activebackground="#5a5a6a", bd=0, padx=5, pady=6,
            font=("Microsoft JhengHei", 9)
        )
        self.btn_undo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        
        self.btn_redo = tk.Button(
            hist_frame, text="↪️ 重做 (Ctrl+Y)", command=self.redo,
            bg="#4a4a5a", fg="white", activebackground="#5a5a6a", bd=0, padx=5, pady=6,
            font=("Microsoft JhengHei", 9)
        )
        self.btn_redo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        
        # 初始化歷史紀錄按鈕的啟用狀態
        self.update_history_buttons()
        
        # 4. 操作按鈕區 (最底部)
        btn_cancel = tk.Button(
            sidebar, text="❌ 取消退出 (Esc)", command=self.destroy,
            bg="#4a4a5a", fg="white", activebackground="#5a5a6a", bd=0, pady=8,
            font=("Microsoft JhengHei", 9, "bold")
        )
        btn_cancel.pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        
        btn_save = tk.Button(
            sidebar, text="💾 套用並貼回 (Enter)", command=self.save_and_close,
            bg="#008c5e", fg="white", activebackground="#00aa70", bd=0, pady=10,
            font=("Microsoft JhengHei", 10, "bold")
        )
        btn_save.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 10))
        
        # 底部狀態列 (橫跨右側區域底部)
        self.status_bar = tk.Frame(self, bg="#2a2a35", height=30)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.lbl_status = tk.Label(
            self.status_bar, text="", bg="#2a2a35", fg="#d0d0d5", font=("Microsoft JhengHei", 9)
        )
        self.lbl_status.pack(side=tk.LEFT, padx=15, pady=5)
        self.update_status_label()
        
        # 畫布容器
        self.canvas_frame = tk.Frame(self, bg="#1c1c22")
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        self.canvas = tk.Canvas(self.canvas_frame, bg="#1c1c22", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # 滑鼠與縮放平移事件綁定
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_hover)
        self.canvas.bind("<Leave>", self.on_leave)
        
        # 縮放 (滾輪) 與平移 (右鍵拖曳)
        self.canvas.bind("<MouseWheel>", self.on_zoom)
        self.canvas.bind("<ButtonPress-3>", self.on_pan_press)
        self.canvas.bind("<B3-Motion>", self.on_pan_drag)
        self.canvas.bind("<ButtonRelease-3>", self.on_pan_release)
        self.canvas.bind("<Configure>", self.on_resize)

    def update_history_buttons(self):
        if hasattr(self, "btn_undo") and hasattr(self, "btn_redo"):
            if self.undo_stack:
                self.btn_undo.configure(state=tk.NORMAL, bg="#4a4a5a", fg="white")
            else:
                self.btn_undo.configure(state=tk.DISABLED, bg="#20202a", fg="#666677")
                
            if self.redo_stack:
                self.btn_redo.configure(state=tk.NORMAL, bg="#4a4a5a", fg="white")
            else:
                self.btn_redo.configure(state=tk.DISABLED, bg="#20202a", fg="#666677")

    def undo(self):
        if not self.undo_stack:
            return
            
        curr_state = (
            [row[:] for row in self.grid_x],
            [row[:] for row in self.grid_y]
        )
        self.redo_stack.append(curr_state)
        
        prev_state = self.undo_stack.pop()
        self.grid_x = prev_state[0]
        self.grid_y = prev_state[1]
        
        self.render_warp()
        self.update_history_buttons()
        # 重設拖曳狀態防止坐標跳躍
        self.last_mx = None
        self.last_my = None

    def redo(self):
        if not self.redo_stack:
            return
            
        curr_state = (
            [row[:] for row in self.grid_x],
            [row[:] for row in self.grid_y]
        )
        self.undo_stack.append(curr_state)
        
        next_state = self.redo_stack.pop()
        self.grid_x = next_state[0]
        self.grid_y = next_state[1]
        
        self.render_warp()
        self.update_history_buttons()
        # 重設拖曳狀態防止坐標跳躍
        self.last_mx = None
        self.last_my = None

    def update_status_label(self):
        pct = int(self.zoom_level * 100)
        self.lbl_status.configure(
            text=f"縮放: {pct}% | 快捷鍵: 滾輪 (縮放) | 右鍵 或 空白鍵+左鍵 (平移畫布) | [ / ] (調整筆刷)"
        )

    def change_mode(self):
        self.mode = self.mode_var.get()
        
    def change_bg_mode(self):
        self.bg_mode = self.bg_var.get()
        self.render_warp()
        
    def on_resize(self, event):
        if not hasattr(self, "edit_img") or self.edit_img is None:
            return
        self.render_warp()
        
    def update_brush_size(self, val):
        self.brush_size = int(val)
        
    def adjust_brush_size(self, delta):
        new_size = max(10, min(300, self.brush_size + delta))
        self.brush_size = new_size
        self.size_scale.set(new_size)
        
    def update_strength(self, val):
        self.brush_strength = float(val) / 10.0

    def setup_images(self, img):
        self.orig_img = img.convert("RGBA")
        ow, oh = self.orig_img.size
        
        # 為了保證拖曳時能有 60fps 順暢感，若大圖則等比例縮小進行互動編輯
        max_w, max_h = 1000, 750
        if ow > max_w or oh > max_h:
            self.scale = min(max_w / ow, max_h / oh)
            ew = int(ow * self.scale)
            eh = int(oh * self.scale)
            self.edit_img = self.orig_img.resize((ew, eh), Image.Resampling.BILINEAR)
        else:
            self.scale = 1.0
            self.edit_img = self.orig_img.copy()
            
        ew, eh = self.edit_img.size
        self.cols = math.ceil(ew / self.cell_size)
        self.rows = math.ceil(eh / self.cell_size)
        
        # 初始化變形網格控制點
        self.grid_x = [[min(c * self.cell_size, ew) for c in range(self.cols + 1)] for r in range(self.rows + 1)]
        self.grid_y = [[min(r * self.cell_size, eh) for c in range(self.cols + 1)] for r in range(self.rows + 1)]
        
        # 讓圖片在 Canvas 中置中
        self.canvas.update()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        self.offset_x = max(0, (cw - ew) // 2)
        self.offset_y = max(0, (ch - eh) // 2)
        
        self.render_warp()

    def render_warp(self):
        if self.edit_img is None:
            return
            
        ew, eh = self.edit_img.size
        mesh_data = []
        for r in range(self.rows):
            for c in range(self.cols):
                x0 = c * self.cell_size
                y0 = r * self.cell_size
                x1 = min((c + 1) * self.cell_size, ew)
                y1 = min((r + 1) * self.cell_size, eh)
                box = (x0, y0, x1, y1)
                
                # 來源 Quad 頂點座標
                quad = (
                    self.grid_x[r][c], self.grid_y[r][c],
                    self.grid_x[r+1][c], self.grid_y[r+1][c],
                    self.grid_x[r+1][c+1], self.grid_y[r+1][c+1],
                    self.grid_x[r][c+1], self.grid_y[r][c+1]
                )
                mesh_data.append((box, quad))
                
        # 1. 於編輯解析度下進行液化變形
        self.warped_img = self.edit_img.transform((ew, eh), Image.MESH, mesh_data, Image.Resampling.BICUBIC)
        
        # 2. 取得目前畫布大小
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            cw, ch = 1150, 850
            
        # 3. 建立背景圖層
        if self.bg_mode == "checkerboard":
            cols = math.ceil(cw / 16)
            rows = math.ceil(ch / 16)
            small = Image.new("RGBA", (cols, rows))
            pixels = []
            c1 = (255, 255, 255, 255)
            c2 = (223, 223, 223, 255)
            for r in range(rows):
                for c in range(cols):
                    pixels.append(c1 if (c + r) % 2 == 0 else c2)
            small.putdata(pixels)
            bg_img = small.resize((cols * 16, rows * 16), Image.Resampling.NEAREST).crop((0, 0, cw, ch))
        elif self.bg_mode == "white":
            bg_img = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))
        else: # grey
            bg_img = Image.new("RGBA", (cw, ch), (128, 128, 128, 255))
            
        # 4. 根據 zoom_level 進行縮放 warped_img
        disp_w = int(ew * self.zoom_level)
        disp_h = int(eh * self.zoom_level)
        
        if disp_w > 0 and disp_h > 0:
            if self.zoom_level != 1.0:
                warped_resized = self.warped_img.resize((disp_w, disp_h), Image.Resampling.BILINEAR)
            else:
                warped_resized = self.warped_img
                
            # 5. 疊加影像到背景上
            bg_img.paste(warped_resized, (self.offset_x, self.offset_y), warped_resized)
            
        self.tk_img = ImageTk.PhotoImage(bg_img)
        
        self.canvas.delete("image")
        self.canvas.create_image(0, 0, image=self.tk_img, anchor=tk.NW, tags="image")
        self.canvas.tag_lower("image")

    def to_img_coords(self, mx, my):
        # 考量平移偏移量與縮放倍率，轉換為原始 edit_img 的內部像素座標
        ix = (mx - self.offset_x) / self.zoom_level
        iy = (my - self.offset_y) / self.zoom_level
        return ix, iy
        
    def on_press(self, event):
        if self.space_held:
            self.on_pan_press(event)
        else:
            # 儲存當前狀態以供復原
            prev_state = (
                [row[:] for row in self.grid_x],
                [row[:] for row in self.grid_y]
            )
            self.undo_stack.append(prev_state)
            if len(self.undo_stack) > self.max_history:
                self.undo_stack.pop(0)
            self.redo_stack.clear()
            self.update_history_buttons()
            
            ix, iy = self.to_img_coords(event.x, event.y)
            self.last_mx = ix
            self.last_my = iy
        
    def on_drag(self, event):
        if self.edit_img is None:
            return
            
        if self.space_held:
            self.on_pan_drag(event)
            return
            
        if self.last_mx is None:
            return
            
        ix, iy = self.to_img_coords(event.x, event.y)
        dx = ix - self.last_mx
        dy = iy - self.last_my
        
        if dx == 0 and dy == 0:
            return
        ew, eh = self.edit_img.size
        # 限制計算範圍於筆刷 Bounding Box 內（大幅提升密網格下的效能）
        margin = 3
        c_min = max(1, int((self.last_mx - self.brush_size) / self.cell_size) - margin)
        c_max = min(self.cols, int((self.last_mx + self.brush_size) / self.cell_size) + margin + 1)
        r_min = max(1, int((self.last_my - self.brush_size) / self.cell_size) - margin)
        r_max = min(self.rows, int((self.last_my + self.brush_size) / self.cell_size) + margin + 1)

        # 對範圍內的網格點進行變形計算
        for r in range(r_min, r_max):
            for c in range(c_min, c_max):
                vx = self.grid_x[r][c]
                vy = self.grid_y[r][c]
                
                dist = math.hypot(vx - self.last_mx, vy - self.last_my)
                if dist < self.brush_size:
                    # 使用 Cosine 漸層平滑衰減
                    w = 0.5 * (math.cos(math.pi * dist / self.brush_size) + 1.0)
                    
                    if self.mode == "push":
                        self.grid_x[r][c] -= dx * w * self.brush_strength
                        self.grid_y[r][c] -= dy * w * self.brush_strength
                    elif self.mode == "bloat":
                        if dist > 0:
                            factor = w * self.brush_strength * 4.0
                            self.grid_x[r][c] -= ((vx - self.last_mx) / dist) * factor
                            self.grid_y[r][c] -= ((vy - self.last_my) / dist) * factor
                    elif self.mode == "pinch":
                        if dist > 0:
                            factor = w * self.brush_strength * 4.0
                            self.grid_x[r][c] += ((vx - self.last_mx) / dist) * factor
                            self.grid_y[r][c] += ((vy - self.last_my) / dist) * factor
                    elif self.mode == "reconstruct":
                        orig_x = c * self.cell_size
                        orig_y = r * self.cell_size
                        self.grid_x[r][c] += (orig_x - vx) * w * self.brush_strength
                        self.grid_y[r][c] += (orig_y - vy) * w * self.brush_strength
                        
                # 邊界約束
                self.grid_x[r][c] = max(0, min(ew, self.grid_x[r][c]))
                self.grid_y[r][c] = max(0, min(eh, self.grid_y[r][c]))
                
        self.last_mx = ix
        self.last_my = iy
        
        self.render_warp()
        self.draw_brush_circle(event.x, event.y)
        
    def on_release(self, event):
        if self.space_held:
            self.on_pan_release(event)
        else:
            self.last_mx = None
            self.last_my = None
        
    def draw_brush_circle(self, mx, my):
        self.canvas.delete("brush")
        # 筆刷圓圈大小隨手動縮放比例同步放大/縮小
        screen_brush_size = self.brush_size * self.zoom_level
        self.canvas.create_oval(
            mx - screen_brush_size, my - screen_brush_size,
            mx + screen_brush_size, my + screen_brush_size,
            outline="#00ffcc", width=1.5, tags="brush"
        )
        
    def on_hover(self, event):
        if not self.space_held:
            self.draw_brush_circle(event.x, event.y)
        else:
            self.canvas.delete("brush")
        
    def on_leave(self, event):
        self.canvas.delete("brush")

    # 畫布縮放 (滾輪) 與平移 (右鍵 / 空白鍵 + 左鍵) 邏輯
    def on_zoom(self, event):
        mx, my = event.x, event.y
        ix, iy = self.to_img_coords(mx, my)
        
        if event.delta > 0:
            self.zoom_level = min(8.0, self.zoom_level * 1.15)
        else:
            self.zoom_level = max(0.15, self.zoom_level / 1.15)
            
        # 調整平移偏移量，以確保滑鼠指針下的像素點在縮放後保持不動 (以滑鼠為中心縮放)
        self.offset_x = int(mx - ix * self.zoom_level)
        self.offset_y = int(my - iy * self.zoom_level)
        
        self.render_warp()
        self.draw_brush_circle(mx, my)
        self.update_status_label()

    def on_pan_press(self, event):
        self.pan_start_x = event.x
        self.pan_start_y = event.y
        self.pan_init_offset_x = self.offset_x
        self.pan_init_offset_y = self.offset_y
        
    def on_pan_drag(self, event):
        dx = event.x - self.pan_start_x
        dy = event.y - self.pan_start_y
        self.offset_x = self.pan_init_offset_x + dx
        self.offset_y = self.pan_init_offset_y + dy
        self.render_warp()
        
    def on_pan_release(self, event):
        pass

    def on_space_press(self, event):
        if not self.space_held:
            self.space_held = True
            self.canvas.configure(cursor="hand2")
            self.canvas.delete("brush")
            
    def on_space_release(self, event):
        if self.space_held:
            self.space_held = False
            self.canvas.configure(cursor="")

    def save_and_close(self):
        # 儲存目前的筆刷大小與強度設定
        save_settings(self.brush_size, self.brush_strength)
        
        ow, oh = self.orig_img.size
        orig_mesh_data = []
        orig_cell_w = self.cell_size / self.scale
        orig_cell_h = self.cell_size / self.scale
        
        for r in range(self.rows):
            for c in range(self.cols):
                x0 = c * orig_cell_w
                y0 = r * orig_cell_h
                x1 = min((c + 1) * orig_cell_w, ow)
                y1 = min((r + 1) * orig_cell_h, oh)
                box = (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))
                
                quad = (
                    self.grid_x[r][c] / self.scale, self.grid_y[r][c] / self.scale,
                    self.grid_x[r+1][c] / self.scale, self.grid_y[r+1][c] / self.scale,
                    self.grid_x[r+1][c+1] / self.scale, self.grid_y[r+1][c+1] / self.scale,
                    self.grid_x[r][c+1] / self.scale, self.grid_y[r][c+1] / self.scale
                )
                orig_mesh_data.append((box, quad))
                
        try:
            final_img = self.orig_img.transform((ow, oh), Image.MESH, orig_mesh_data, Image.Resampling.BICUBIC)
            if copy_image_to_clipboard(final_img):
                # 呼叫回呼函數，執行後續貼上動作
                self.on_save_callback()
                self.destroy()
            else:
                messagebox.showerror("錯誤", "複製到剪貼簿失敗。")
        except Exception as e:
            messagebox.showerror("錯誤", f"液化高解析度渲染失敗: {e}")

    def on_close(self):
        self.destroy()
        
    def destroy(self):
        save_settings(self.brush_size, self.brush_strength)
        self.parent.editor_active = False
        super().destroy()


class HotkeyManager:
    """
    全域快捷鍵與主程式管理
    """
    def __init__(self, root):
        self.root = root
        self.root.title("SAI2 液化助手 - 背景運行中")
        self.root.geometry("450x220")
        self.root.configure(bg="#1a1a24")
        self.root.resizable(False, False)
        
        self.editor_active = False
        self.hotkey_queue = queue.Queue()
        
        self.setup_ui()
        self.start_hotkey_listener()
        
        # 定期檢查佇列是否收到快捷鍵事件
        self.root.after(100, self.poll_hotkey_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

    def setup_ui(self):
        # 標題標籤
        lbl_title = tk.Label(
            self.root, text="🎨 SAI2 液化繪圖助手", 
            bg="#1a1a24", fg="#ffffff", font=("Microsoft JhengHei", 14, "bold")
        )
        lbl_title.pack(pady=(20, 5))
        
        # 說明文字
        lbl_desc = tk.Label(
            self.root, 
            text="全域啟動快捷鍵: Ctrl + Alt + L\n\n(在 SAI2 中有選取區域時，按下快捷鍵即可啟動液化)\n(編輯完成按 Enter 自動貼回，Esc 取消)", 
            bg="#1a1a24", fg="#a0a0b0", font=("Microsoft JhengHei", 10), justify=tk.CENTER
        )
        lbl_desc.pack(pady=10)
        
        # 控制按鈕
        btn_frame = tk.Frame(self.root, bg="#1a1a24")
        btn_frame.pack(fill=tk.X, pady=10)
        
        btn_manual = tk.Button(
            btn_frame, text="📋 手動從剪貼簿啟動", command=self.trigger_liquify,
            bg="#3e3e52", fg="white", activebackground="#505065", bd=0, padx=12, pady=6,
            font=("Microsoft JhengHei", 9, "bold")
        )
        btn_manual.pack(side=tk.LEFT, padx=(70, 10))
        
        btn_exit = tk.Button(
            btn_frame, text="🛑 退出程式", command=self.on_exit,
            bg="#b32424", fg="white", activebackground="#cf3232", bd=0, padx=15, pady=6,
            font=("Microsoft JhengHei", 9, "bold")
        )
        btn_exit.pack(side=tk.LEFT, padx=10)

    def start_hotkey_listener(self):
        """
        啟動背景線程來監聽 Windows 全域快捷鍵
        """
        self.listener_thread = threading.Thread(target=self.hotkey_thread_proc, daemon=True)
        self.listener_thread.start()

    def hotkey_thread_proc(self):
        # 註冊 Ctrl + Alt + L 全域快捷鍵
        # ID = 101, MOD_ALT (0x0001) | MOD_CONTROL (0x0002) = 3, VK_L = 0x4C
        if not user32.RegisterHotKey(None, 101, 3, 0x4C):
            self.root.after(0, lambda: messagebox.showerror("錯誤", "無法註冊 Ctrl+Alt+L 全域快捷鍵！可能是其他程式佔用了。"))
            return
            
        try:
            msg = ctypes.wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    if msg.wParam == 101:
                        self.hotkey_queue.put(True)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, 101)

    def poll_hotkey_queue(self):
        try:
            while True:
                self.hotkey_queue.get_nowait()
                if not self.editor_active:
                    self.trigger_workflow()
        except queue.Empty:
            pass
        self.root.after(50, self.poll_hotkey_queue)

    def trigger_workflow(self):
        """
        快捷鍵觸發時的自動化流程
        """
        # 1. 先釋放 Alt 與 Ctrl 鍵以避免干擾後續按鍵模擬
        user32.keybd_event(0x11, 0, 2, 0)  # VK_CONTROL
        user32.keybd_event(0x12, 0, 2, 0)  # VK_MENU (ALT)
        time.sleep(0.05)
        
        # 2. 自動模擬 Ctrl + C 複製 SAI2 畫布/選區
        user32.keybd_event(0x11, 0, 0, 0)  # 按下 Ctrl
        user32.keybd_event(0x43, 0, 0, 0)  # 按下 C
        user32.keybd_event(0x43, 0, 2, 0)  # 釋放 C
        user32.keybd_event(0x11, 0, 2, 0)  # 釋放 Ctrl
        
        # 3. 等待剪貼簿完成更新
        time.sleep(0.2)
        
        # 4. 啟動液化編輯器
        self.trigger_liquify()

    def trigger_liquify(self):
        try:
            img = read_image_from_clipboard()
            if img is None:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                # 提示使用者目前剪貼簿沒有圖片
                messagebox.showwarning("提示", "剪貼簿中沒有圖像數據！\n請先在 SAI2 中選擇並複製 (Ctrl+C)。")
                return
                
            if isinstance(img, list):
                if len(img) > 0 and os.path.exists(img[0]):
                    img = Image.open(img[0])
                else:
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    return
            
            # 建立液化編輯視窗
            LiquifyEditor(self, img, on_save_callback=self.on_save_success)
        except Exception as e:
            messagebox.showerror("錯誤", f"開啟液化工具失敗: {e}")

    def on_save_success(self):
        """
        Paste back to SAI2 after save success
        """
        # Wait a bit for clipboard update
        time.sleep(0.15)
        
        # Simulate Ctrl + V
        user32.keybd_event(0x11, 0, 0, 0)  # Press Ctrl
        user32.keybd_event(0x56, 0, 0, 0)  # Press V
        user32.keybd_event(0x56, 0, 2, 0)  # Release V
        user32.keybd_event(0x11, 0, 2, 0)  # Release Ctrl
        
        # Play beep sound
        winsound.MessageBeep(winsound.MB_OK)

    def on_exit(self):
        self.root.destroy()

if __name__ == "__main__":
    # 高 DPI 支援
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
        
    root = tk.Tk()
    app = HotkeyManager(root)
    root.mainloop()
