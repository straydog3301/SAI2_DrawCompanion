# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk, ImageGrab, ImageDraw
import math
import io
import ctypes
import ctypes.wintypes
import os
import sys
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
ACTIVE_OFFSET = None
ACTIVE_CANVAS_SIZE = (0, 0)
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

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

# 註冊 PNG 剪貼簿格式以支援現代跨平台透明度
PNG_FORMAT_ID = user32.RegisterClipboardFormatW("PNG")

# Windows 8+ Pointer API 常數 (繪圖板筆壓偵測)
WM_POINTERUPDATE = 0x0245
WM_POINTERDOWN = 0x0246
WM_POINTERUP = 0x0247
WM_POINTERLEAVE = 0x024A
PT_PEN = 3
GWL_WNDPROC = -4

class POINTER_INFO(ctypes.Structure):
    """Pointer API 的基礎資訊結構 (Windows 8+)"""
    _fields_ = [
        ("pointerType", ctypes.wintypes.DWORD),
        ("pointerId", ctypes.c_uint32),
        ("frameId", ctypes.c_uint32),
        ("pointerFlags", ctypes.wintypes.DWORD),
        ("sourceDevice", ctypes.wintypes.HANDLE),
        ("hwndTarget", ctypes.wintypes.HWND),
        ("ptPixelLocation", ctypes.wintypes.POINT),
        ("ptHimetricLocation", ctypes.wintypes.POINT),
        ("ptPixelLocationRaw", ctypes.wintypes.POINT),
        ("ptHimetricLocationRaw", ctypes.wintypes.POINT),
        ("dwTime", ctypes.wintypes.DWORD),
        ("historyCount", ctypes.c_uint32),
        ("InputData", ctypes.c_int32),
        ("dwKeyStates", ctypes.wintypes.DWORD),
        ("PerformanceCount", ctypes.c_uint64),
        ("ButtonChangeType", ctypes.c_int),
    ]

class POINTER_PEN_INFO(ctypes.Structure):
    """Pointer API 的手寫筆資訊結構，pressure 為 0-1024 的筆壓值"""
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("penFlags", ctypes.wintypes.DWORD),
        ("penMask", ctypes.wintypes.DWORD),
        ("pressure", ctypes.c_uint32),
        ("rotation", ctypes.c_uint32),
        ("tiltX", ctypes.c_int32),
        ("tiltY", ctypes.c_int32),
    ]

class BITMAPINFOHEADER(ctypes.Structure):
    """
    Win32 BITMAPINFOHEADER 結構，用於攜帶 24-bit/32-bit 標準 BMP 像素。
    大小固定為 40 位元組。
    """
    _pack_ = 1
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD)
    ]

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
    import time
    global ACTIVE_OFFSET, ACTIVE_CANVAS_SIZE
    if ACTIVE_OFFSET and ACTIVE_CANVAS_SIZE != (0, 0):
        # 構造與大畫布大小一致的透明圖層，實現原地對齊
        final_canvas = Image.new("RGBA", ACTIVE_CANVAS_SIZE, (0, 0, 0, 0))
        final_canvas.paste(pil_img, ACTIVE_OFFSET)
        pil_img = final_canvas
        # 重設變數，避免干擾常規複製
        ACTIVE_OFFSET = None
        ACTIVE_CANVAS_SIZE = (0, 0)
        
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
    import time
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

DEFAULT_SETTINGS = {
    "brush_size": 80, "brush_strength": 0.5, "bg_mode": "checkerboard",
    "show_mesh": False, "use_pressure": True
}

def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
    except:
        pass
    return dict(DEFAULT_SETTINGS)

def save_settings(size, strength, bg_mode="checkerboard", show_mesh=False, use_pressure=True):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({
                "brush_size": size, "brush_strength": strength, "bg_mode": bg_mode,
                "show_mesh": show_mesh, "use_pressure": use_pressure
            }, f)
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
        self.geometry("1180x900")
        self.configure(bg="#1c1c22")
        
        # 讓編輯視窗永遠置頂，方便直接在畫布上工作
        self.attributes("-topmost", True)
        self.focus_force()
        
        # 載入歷史筆刷設定
        settings = load_settings()
        self.brush_size = settings.get("brush_size", 80)
        self.brush_strength = settings.get("brush_strength", 0.5)
        self.mode = "push"
        self.bg_mode = settings.get("bg_mode", "checkerboard")
        self.show_mesh = settings.get("show_mesh", False)
        self.use_pressure = settings.get("use_pressure", True)

        # 筆壓狀態 (由 Windows Pointer API 更新，僅在偵測到手寫筆時生效)
        self.current_pressure = 1.0
        self.pen_available = False
        self._orig_wndproc = None
        
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

        # 最後已知的游標畫布座標 (供調整筆刷大小時立即重繪筆刷圈)
        self._cursor_x = None
        self._cursor_y = None

        self.create_widgets()
        self.setup_images(image)
        
        # 鍵盤快捷鍵與空白鍵平移綁定
        self.bind("<bracketleft>", lambda e: self.adjust_brush_size(-5))
        self.bind("<bracketright>", lambda e: self.adjust_brush_size(5))
        # 泛用按鍵後備：輸入法 (IME) 開啟時可能不會產生 bracketleft/right keysym，
        # 改由 event.char 判斷 (同一 widget 上較特定的綁定會優先觸發，不會重複執行)
        self.bind("<Key>", self.on_any_key)
        self.bind("<Return>", lambda e: self.save_and_close())
        self.bind("<Escape>", lambda e: self.destroy())
        
        # 復原與重做快捷鍵綁定
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-Z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())
        self.bind("<Control-Y>", lambda e: self.redo())

        # 網格顯示切換快捷鍵
        self.bind("<m>", lambda e: self.toggle_mesh_hotkey())
        self.bind("<M>", lambda e: self.toggle_mesh_hotkey())

        # 全域空白鍵監聽 (用於拖曳畫布)
        self.bind("<KeyPress-space>", self.on_space_press)
        self.bind("<KeyRelease-space>", self.on_space_release)
        
        # 視窗關閉時釋放狀態
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.parent.editor_active = True

        # 嘗試啟用繪圖板筆壓偵測 (Windows 8+ Pointer API，失敗則靜默退回滑鼠模式)
        self._init_pen_pressure()

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
            ("👇 推拉", "push"),
            ("🔍 膨脹", "bloat"),
            ("🌀 收縮", "pinch"),
            ("↻ 順時旋轉", "twirl_cw"),
            ("↺ 逆時旋轉", "twirl_ccw"),
            ("〰️ 平滑", "smooth"),
            ("🔄 重建", "reconstruct"),
            ("❄️ 凍結", "freeze"),
            ("🔥 解凍", "thaw"),
        ]
        mode_grid = tk.Frame(sidebar, bg="#2a2a35")
        mode_grid.pack(fill=tk.X)
        mode_grid.columnconfigure(0, weight=1)
        mode_grid.columnconfigure(1, weight=1)
        for i, (text, val) in enumerate(modes):
            rbtn = tk.Radiobutton(
                mode_grid, text=text, variable=self.mode_var, value=val, command=self.change_mode,
                bg="#2a2a35", fg="#d0d0d5", selectcolor="#3a3a4a", activebackground="#2a2a35",
                activeforeground="white", font=("Microsoft JhengHei", 9), anchor=tk.W
            )
            rbtn.grid(row=i // 2, column=i % 2, sticky="ew", pady=2)

        # 凍結遮罩清除按鈕
        self.btn_clear_mask = tk.Button(
            sidebar, text="🧹 清除凍結遮罩", command=self.clear_freeze_mask,
            bg="#4a4a5a", fg="white", activebackground="#5a5a6a", bd=0, pady=4,
            font=("Microsoft JhengHei", 9)
        )
        self.btn_clear_mask.pack(fill=tk.X, pady=(6, 0))

        # 分隔線
        divider1 = tk.Frame(sidebar, bg="#3d3d4d", height=1)
        divider1.pack(fill=tk.X, pady=8)
        
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
        divider2.pack(fill=tk.X, pady=8)
        
        # 背景模式區
        lbl_bg_sec = tk.Label(
            sidebar, text="背景模式", bg="#2a2a35", fg="#a0a0b0", font=("Microsoft JhengHei", 9, "bold")
        )
        lbl_bg_sec.pack(anchor=tk.W, pady=(0, 5))
        
        self.bg_var = tk.StringVar(value=self.bg_mode)
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
        divider_bg.pack(fill=tk.X, pady=8)

        # 顯示選項區 (網格 / 筆壓)
        lbl_view_sec = tk.Label(
            sidebar, text="顯示與輸入", bg="#2a2a35", fg="#a0a0b0", font=("Microsoft JhengHei", 9, "bold")
        )
        lbl_view_sec.pack(anchor=tk.W, pady=(0, 3))

        self.mesh_var = tk.BooleanVar(value=self.show_mesh)
        chk_mesh = tk.Checkbutton(
            sidebar, text="🕸️ 顯示液化網格 (M)", variable=self.mesh_var, command=self.toggle_mesh,
            bg="#2a2a35", fg="#d0d0d5", selectcolor="#3a3a4a", activebackground="#2a2a35",
            activeforeground="white", font=("Microsoft JhengHei", 9), anchor=tk.W
        )
        chk_mesh.pack(fill=tk.X, pady=2)

        self.pressure_var = tk.BooleanVar(value=self.use_pressure)
        chk_pressure = tk.Checkbutton(
            sidebar, text="🖊️ 筆壓調整強度", variable=self.pressure_var, command=self.toggle_pressure,
            bg="#2a2a35", fg="#d0d0d5", selectcolor="#3a3a4a", activebackground="#2a2a35",
            activeforeground="white", font=("Microsoft JhengHei", 9), anchor=tk.W
        )
        chk_pressure.pack(fill=tk.X, pady=2)

        # 分隔線
        divider_view = tk.Frame(sidebar, bg="#3d3d4d", height=1)
        divider_view.pack(fill=tk.X, pady=8)

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

    def _snapshot_state(self):
        """建立完整編輯狀態快照 (變形網格 + 凍結遮罩)"""
        return (
            [row[:] for row in self.grid_x],
            [row[:] for row in self.grid_y],
            self.freeze_mask.copy()
        )

    def _restore_state(self, state):
        self.grid_x = state[0]
        self.grid_y = state[1]
        self.freeze_mask = state[2]
        self._freeze_px = self.freeze_mask.load()
        self._mesh_dirty = True

    def undo(self):
        if not self.undo_stack:
            return

        self.redo_stack.append(self._snapshot_state())
        self._restore_state(self.undo_stack.pop())

        self.render_warp()
        self.update_history_buttons()
        # 重設拖曳狀態防止坐標跳躍
        self.last_mx = None
        self.last_my = None

    def redo(self):
        if not self.redo_stack:
            return

        self.undo_stack.append(self._snapshot_state())
        self._restore_state(self.redo_stack.pop())

        self.render_warp()
        self.update_history_buttons()
        # 重設拖曳狀態防止坐標跳躍
        self.last_mx = None
        self.last_my = None

    def update_status_label(self):
        pct = int(self.zoom_level * 100)
        pen_txt = "🖊️ 已偵測手寫筆" if self.pen_available else "🖱️ 滑鼠模式"
        self.lbl_status.configure(
            text=f"縮放: {pct}% | {pen_txt} | 滾輪 (縮放) | 右鍵 或 空白鍵+左鍵 (平移) | [ / ] (筆刷) | M (網格)"
        )

    def change_mode(self):
        self.mode = self.mode_var.get()
        # 切換到凍結/解凍模式時重新渲染，讓遮罩覆蓋層立即顯示
        if self.mode in ("freeze", "thaw"):
            self.render_warp()

    def toggle_mesh(self):
        self.show_mesh = self.mesh_var.get()
        self.draw_mesh()

    def toggle_mesh_hotkey(self):
        self.mesh_var.set(not self.mesh_var.get())
        self.toggle_mesh()

    def toggle_pressure(self):
        self.use_pressure = self.pressure_var.get()

    def clear_freeze_mask(self):
        if not self.freeze_mask.getbbox():
            return
        self.undo_stack.append(self._snapshot_state())
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.update_history_buttons()

        self.freeze_mask = Image.new("L", self.freeze_mask.size, 0)
        self._freeze_px = self.freeze_mask.load()
        self.render_warp()

    def change_bg_mode(self):
        self.bg_mode = self.bg_var.get()
        self.render_warp()
        
    def on_resize(self, event):
        if not hasattr(self, "edit_img") or self.edit_img is None:
            return
        self.render_warp()
        
    def update_brush_size(self, val):
        self.brush_size = int(val)
        self._redraw_brush_at_cursor()

    def adjust_brush_size(self, delta):
        new_size = max(10, min(300, self.brush_size + delta))
        self.brush_size = new_size
        self.size_scale.set(new_size)
        self._redraw_brush_at_cursor()

    def _redraw_brush_at_cursor(self):
        """筆刷大小變更時立即重繪筆刷圈，提供即時視覺回饋"""
        if self._cursor_x is not None and not self.space_held:
            self.draw_brush_circle(self._cursor_x, self._cursor_y)

    def on_any_key(self, event):
        """泛用按鍵處理：以 event.char 判斷 [ ]，避免輸入法吃掉 keysym"""
        if event.char == '[':
            self.adjust_brush_size(-5)
        elif event.char == ']':
            self.adjust_brush_size(5)

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
        self._img_w, self._img_h = ew, eh
        self.cols = math.ceil(ew / self.cell_size)
        self.rows = math.ceil(eh / self.cell_size)

        # 初始化變形網格控制點
        self.grid_x = [[min(c * self.cell_size, ew) for c in range(self.cols + 1)] for r in range(self.rows + 1)]
        self.grid_y = [[min(r * self.cell_size, eh) for c in range(self.cols + 1)] for r in range(self.rows + 1)]

        # 初始化凍結遮罩 (灰階圖，255 = 完全凍結不受變形影響)
        self.freeze_mask = Image.new("L", (ew, eh), 0)
        self._freeze_px = self.freeze_mask.load()
        self._mesh_dirty = True

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
        # 1. 於編輯解析度下進行液化變形 (僅在網格有異動時重新計算，平移/縮放/遮罩繪製時直接沿用快取)
        if self._mesh_dirty or self.warped_img is None:
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

            self.warped_img = self.edit_img.transform((ew, eh), Image.MESH, mesh_data, Image.Resampling.BICUBIC)
            self._mesh_dirty = False

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

            # 6. 疊加凍結遮罩覆蓋層 (半透明紅色標示受保護區域)
            if self.freeze_mask.getbbox():
                alpha = self.freeze_mask.point(lambda v: 110 if v else 0)
                if self.zoom_level != 1.0:
                    alpha = alpha.resize((disp_w, disp_h), Image.Resampling.NEAREST)
                overlay = Image.new("RGBA", alpha.size, (255, 64, 96, 255))
                overlay.putalpha(alpha)
                bg_img.paste(overlay, (self.offset_x, self.offset_y), overlay)

        self.tk_img = ImageTk.PhotoImage(bg_img)

        self.canvas.delete("image")
        self.canvas.create_image(0, 0, image=self.tk_img, anchor=tk.NW, tags="image")
        self.canvas.tag_lower("image")
        self.draw_mesh()

    def draw_mesh(self):
        """繪製液化網格覆蓋層，以一階反向近似顯示變形後的網格 (隨筆刷方向移動，較符合直覺)"""
        self.canvas.delete("mesh")
        if not self.show_mesh or self.edit_img is None:
            return

        # 大圖時對網格線抽樣，避免 Canvas 物件過多造成卡頓
        step_r = max(1, round(self.rows / 40))
        step_c = max(1, round(self.cols / 40))
        zl = self.zoom_level

        def screen_pt(r, c):
            # 網格點的輸出位置 = 原始格點 + (原始格點 - 來源取樣點)，即位移的反向近似
            lx = min(c * self.cell_size, self._img_w)
            ly = min(r * self.cell_size, self._img_h)
            dx = 2 * lx - self.grid_x[r][c]
            dy = 2 * ly - self.grid_y[r][c]
            return dx * zl + self.offset_x, dy * zl + self.offset_y

        rows_iter = list(range(0, self.rows + 1, step_r))
        if rows_iter[-1] != self.rows:
            rows_iter.append(self.rows)
        cols_iter = list(range(0, self.cols + 1, step_c))
        if cols_iter[-1] != self.cols:
            cols_iter.append(self.cols)

        for r in rows_iter:
            pts = []
            for c in range(self.cols + 1):
                pts.extend(screen_pt(r, c))
            self.canvas.create_line(*pts, fill="#3ad6a8", width=1, stipple="gray50", tags="mesh")
        for c in cols_iter:
            pts = []
            for r in range(self.rows + 1):
                pts.extend(screen_pt(r, c))
            self.canvas.create_line(*pts, fill="#3ad6a8", width=1, stipple="gray50", tags="mesh")

        self.canvas.tag_raise("brush")

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
            self.undo_stack.append(self._snapshot_state())
            if len(self.undo_stack) > self.max_history:
                self.undo_stack.pop(0)
            self.redo_stack.clear()
            self.update_history_buttons()

            ix, iy = self.to_img_coords(event.x, event.y)
            self.last_mx = ix
            self.last_my = iy

            # 凍結/解凍模式：按下時立即塗抹一筆
            if self.mode in ("freeze", "thaw"):
                self._paint_freeze(ix, iy, ix, iy)
                self.render_warp()
                self.draw_brush_circle(event.x, event.y)

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

        # 凍結/解凍模式：在遮罩上塗抹，不進行變形
        if self.mode in ("freeze", "thaw"):
            self._paint_freeze(self.last_mx, self.last_my, ix, iy)
            self.last_mx = ix
            self.last_my = iy
            self.render_warp()
            self.draw_brush_circle(event.x, event.y)
            return

        # 筆壓係數 (僅在偵測到手寫筆且啟用筆壓時生效)
        press = self.current_pressure if (self.use_pressure and self.pen_available) else 1.0

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
                    # 使用 Cosine 漸層平滑衰減，並乘上筆壓與凍結遮罩保護係數
                    w = 0.5 * (math.cos(math.pi * dist / self.brush_size) + 1.0)
                    eff = w * self.brush_strength * press * (1.0 - self._freeze_at(c, r))

                    if self.mode == "push":
                        self.grid_x[r][c] -= dx * eff
                        self.grid_y[r][c] -= dy * eff
                    elif self.mode == "bloat":
                        if dist > 0:
                            factor = eff * 4.0
                            self.grid_x[r][c] -= ((vx - self.last_mx) / dist) * factor
                            self.grid_y[r][c] -= ((vy - self.last_my) / dist) * factor
                    elif self.mode == "pinch":
                        if dist > 0:
                            factor = eff * 4.0
                            self.grid_x[r][c] += ((vx - self.last_mx) / dist) * factor
                            self.grid_y[r][c] += ((vy - self.last_my) / dist) * factor
                    elif self.mode == "reconstruct":
                        orig_x = c * self.cell_size
                        orig_y = r * self.cell_size
                        self.grid_x[r][c] += (orig_x - vx) * eff
                        self.grid_y[r][c] += (orig_y - vy) * eff
                    elif self.mode in ("twirl_cw", "twirl_ccw"):
                        if dist > 0:
                            # 將來源取樣點繞筆刷中心旋轉；來源反向旋轉等同內容正向旋轉
                            ang = eff * 0.12 * (-1.0 if self.mode == "twirl_cw" else 1.0)
                            rel_x = vx - self.last_mx
                            rel_y = vy - self.last_my
                            cos_a = math.cos(ang)
                            sin_a = math.sin(ang)
                            self.grid_x[r][c] = self.last_mx + rel_x * cos_a - rel_y * sin_a
                            self.grid_y[r][c] = self.last_my + rel_x * sin_a + rel_y * cos_a
                    elif self.mode == "smooth":
                        # 將格點往四鄰居的平均位置靠攏，使變形過渡更平滑
                        avg_x = (self.grid_x[r-1][c] + self.grid_x[r+1][c] +
                                 self.grid_x[r][c-1] + self.grid_x[r][c+1]) / 4.0
                        avg_y = (self.grid_y[r-1][c] + self.grid_y[r+1][c] +
                                 self.grid_y[r][c-1] + self.grid_y[r][c+1]) / 4.0
                        self.grid_x[r][c] += (avg_x - vx) * eff
                        self.grid_y[r][c] += (avg_y - vy) * eff

                # 邊界約束
                self.grid_x[r][c] = max(0, min(ew, self.grid_x[r][c]))
                self.grid_y[r][c] = max(0, min(eh, self.grid_y[r][c]))

        self.last_mx = ix
        self.last_my = iy

        self._mesh_dirty = True
        self.render_warp()
        self.draw_brush_circle(event.x, event.y)

    def _freeze_at(self, c, r):
        """取得網格點 (r, c) 對應位置的凍結程度 (0.0 = 不受保護, 1.0 = 完全凍結)"""
        x = min(c * self.cell_size, self._img_w - 1)
        y = min(r * self.cell_size, self._img_h - 1)
        return self._freeze_px[x, y] / 255.0

    def _paint_freeze(self, x0, y0, x1, y1):
        """在凍結遮罩上沿線段塗抹 (freeze 模式塗上、thaw 模式擦除)"""
        val = 255 if self.mode == "freeze" else 0
        r = self.brush_size
        draw = ImageDraw.Draw(self.freeze_mask)
        if (x0, y0) != (x1, y1):
            draw.line([x0, y0, x1, y1], fill=val, width=int(r * 2))
        for (px, py) in ((x0, y0), (x1, y1)):
            draw.ellipse([px - r, py - r, px + r, py + r], fill=val)
        self._freeze_px = self.freeze_mask.load()
        
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
        self._cursor_x = event.x
        self._cursor_y = event.y
        if not self.space_held:
            self.draw_brush_circle(event.x, event.y)
        else:
            self.canvas.delete("brush")

    def on_leave(self, event):
        self._cursor_x = None
        self._cursor_y = None
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

    def _init_pen_pressure(self):
        """
        透過子類化 (subclass) 畫布視窗攔截 WM_POINTER 訊息以讀取繪圖板筆壓。
        Windows 8+ 的手寫筆輸入預設會先以 Pointer 訊息送達，未處理時系統才合成滑鼠訊息，
        因此攔截後轉交原本的視窗程序即可同時取得筆壓並保留 Tkinter 的滑鼠事件。
        失敗時 (如 Windows 7) 靜默退回滑鼠模式 (筆壓固定 1.0)。
        """
        try:
            self.update_idletasks()
            hwnd = self.canvas.winfo_id()

            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(
                LRESULT, ctypes.wintypes.HWND, ctypes.c_uint,
                ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
            )

            user32.GetPointerType.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
            user32.GetPointerType.restype = ctypes.wintypes.BOOL
            user32.GetPointerPenInfo.argtypes = [ctypes.c_uint32, ctypes.POINTER(POINTER_PEN_INFO)]
            user32.GetPointerPenInfo.restype = ctypes.wintypes.BOOL
            user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p, ctypes.wintypes.HWND, ctypes.c_uint,
                ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
            ]
            user32.CallWindowProcW.restype = LRESULT

            def _wnd_proc(hwnd_, msg, wparam, lparam):
                if msg in (WM_POINTERDOWN, WM_POINTERUPDATE):
                    try:
                        pointer_id = wparam & 0xFFFF
                        ptype = ctypes.c_uint32(0)
                        if user32.GetPointerType(pointer_id, ctypes.byref(ptype)) and ptype.value == PT_PEN:
                            pen_info = POINTER_PEN_INFO()
                            if user32.GetPointerPenInfo(pointer_id, ctypes.byref(pen_info)):
                                if not self.pen_available:
                                    self.pen_available = True
                                    self.after(0, self.update_status_label)
                                if pen_info.pressure > 0:
                                    self.current_pressure = max(0.05, min(1.0, pen_info.pressure / 1024.0))
                    except Exception:
                        pass
                elif msg in (WM_POINTERUP, WM_POINTERLEAVE):
                    self.current_pressure = 1.0
                return user32.CallWindowProcW(self._orig_wndproc, hwnd_, msg, wparam, lparam)

            # 保留 callback 參考避免被 GC 回收
            self._pen_proc_ref = WNDPROC(_wnd_proc)

            try:
                set_wndproc = user32.SetWindowLongPtrW
            except AttributeError:
                set_wndproc = user32.SetWindowLongW  # 32 位元系統
            set_wndproc.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            set_wndproc.restype = ctypes.c_void_p
            self._set_wndproc = set_wndproc
            self._pen_hwnd = hwnd

            self._orig_wndproc = set_wndproc(
                hwnd, GWL_WNDPROC, ctypes.cast(self._pen_proc_ref, ctypes.c_void_p)
            )
        except Exception:
            self._orig_wndproc = None
            self.pen_available = False

    def _release_pen_pressure(self):
        """視窗銷毀前還原原本的視窗程序"""
        if getattr(self, "_orig_wndproc", None):
            try:
                self._set_wndproc(self._pen_hwnd, GWL_WNDPROC, self._orig_wndproc)
            except Exception:
                pass
            self._orig_wndproc = None

    def save_and_close(self):
        # 儲存目前的筆刷大小與強度設定
        save_settings(self.brush_size, self.brush_strength, self.bg_mode, self.show_mesh, self.use_pressure)

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
        save_settings(self.brush_size, self.brush_strength, self.bg_mode, self.show_mesh, self.use_pressure)
        self._release_pen_pressure()
        self.parent.editor_active = False
        super().destroy()


def log_debug(msg):
    import time
    try:
        # 將除錯紀錄寫到執行檔 (或腳本) 所在目錄，避免依賴特定使用者的路徑
        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base_dir, "companion_debug.log"), "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except:
        pass

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
        log_debug("trigger_workflow triggered!")
        
        # 1. 等待使用者放開 Ctrl 與 Alt 鍵，避開實體鍵盤衝突
        log_debug("Waiting for physical Ctrl and Alt keys to be released...")
        start_wait = time.time()
        while True:
            ctrl_down = user32.GetAsyncKeyState(0x11) & 0x8000
            alt_down = user32.GetAsyncKeyState(0x12) & 0x8000
            if not ctrl_down and not alt_down:
                break
            if time.time() - start_wait > 2.0: # 最多等待 2 秒防卡死
                log_debug("Timeout waiting for key release!")
                break
            time.sleep(0.05)
            
        log_debug("Keys released. Starting simulations...")
        
        global ACTIVE_OFFSET, ACTIVE_CANVAS_SIZE
        ACTIVE_OFFSET = None
        ACTIVE_CANVAS_SIZE = (0, 0)

        # 2. 先釋放 Alt 與 Ctrl 鍵以避免干擾後續按鍵模擬
        user32.keybd_event(0x11, 0, 2, 0)  # VK_CONTROL
        user32.keybd_event(0x12, 0, 2, 0)  # VK_MENU (ALT)
        time.sleep(0.05)
        
        # 活化 SAI2 視窗
        hwnd_sai2 = find_sai2_hwnd()
        if hwnd_sai2:
            log_debug(f"Found SAI2 HWND={hwnd_sai2}. SetForegroundWindow...")
            user32.SetForegroundWindow(hwnd_sai2)
            time.sleep(0.15)

        # 3. 自動模擬 Ctrl + C 複製選區
        log_debug("Step 1: Copy selection...")
        clear_clipboard()
        press_keys([0x11, 0x43]) # Ctrl + C
        time.sleep(0.25)
        sel_img = read_image_from_clipboard()
        if sel_img is None:
            # 沒有選區 → 自動遞補為「整層液化」模式 (角標錨定，保證原地貼回)
            log_debug("No selection; falling back to whole-layer liquify mode (anchored)")
            layer_img, warn = acquire_whole_layer_anchored()
            if layer_img is None:
                log_debug(f"Whole-layer acquire failed: {warn}")
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                messagebox.showwarning("提示", warn or "無法取得圖層影像！")
                return
            if warn:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                messagebox.showwarning("警告", warn)
            log_debug(f"Whole layer acquired (anchored): {layer_img.width}x{layer_img.height}")
            try:
                LiquifyEditor(self, layer_img, on_save_callback=self.on_save_success)
            except Exception as e:
                log_debug(f"Failed to launch editor: {e}")
                messagebox.showerror("錯誤", f"開啟液化工具失敗: {e}")
            return
        log_debug(f"Selection acquired: {sel_img.width}x{sel_img.height}")
            
        # 4. 模擬 Ctrl + A 全選整個畫布
        log_debug("Step 2: Select All...")
        clear_clipboard()
        press_keys([0x11, 0x41]) # Ctrl + A
        time.sleep(0.25)
        
        # 5. 模擬 Ctrl + Shift + C 複製合併
        log_debug("Step 3: Copy Merged...")
        press_keys([0x11, 0x10, 0x43]) # Ctrl + Shift + C
        time.sleep(0.4)
        canvas_img = read_canvas_from_clipboard()
        if canvas_img is None:
            log_debug("Failed to read merged canvas image from clipboard!")
        else:
            log_debug(f"Canvas acquired: {canvas_img.width}x{canvas_img.height}")
        
        # 6. 模擬 Ctrl + Z 復原以還原原本選區
        log_debug("Step 4: Restore selection via Ctrl+Z...")
        press_keys([0x11, 0x5A]) # Ctrl + Z
        time.sleep(0.2)
        
        # 7. 比對計算偏移量並保存
        if canvas_img and sel_img:
            log_debug("Step 5: Matching selection inside canvas...")
            offset = find_match(canvas_img, sel_img)
            if offset:
                ACTIVE_OFFSET = offset
                ACTIVE_CANVAS_SIZE = canvas_img.size
                log_debug(f"Match success! Offset: {offset}")
            else:
                log_debug("Match failed!")
                
        # 8. 啟動編輯器
        log_debug("Launching LiquifyEditor...")
        try:
            LiquifyEditor(self, sel_img, on_save_callback=self.on_save_success)
        except Exception as e:
            log_debug(f"Failed to launch editor: {e}")
            messagebox.showerror("錯誤", f"開啟液化工具失敗: {e}")

    def trigger_liquify(self):
        """
        手動從剪貼簿啟動 (fallback)
        """
        global ACTIVE_OFFSET, ACTIVE_CANVAS_SIZE
        ACTIVE_OFFSET = None
        ACTIVE_CANVAS_SIZE = (0, 0)
        try:
            img = read_image_from_clipboard()
            if img is None:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                messagebox.showwarning("提示", "剪貼簿中沒有圖像數據！")
                return
            LiquifyEditor(self, img, on_save_callback=self.on_save_success)
        except Exception as e:
            messagebox.showerror("錯誤", f"開啟液化工具失敗: {e}")

    def on_save_success(self):
        """
        存檔成功後貼回 SAI2
        """
        log_debug("LiquifyEditor save success callback triggered!")
        time.sleep(0.2)
        
        # 確保回到 SAI2
        hwnd_sai2 = find_sai2_hwnd()
        if hwnd_sai2:
            log_debug(f"Activating SAI2 HWND={hwnd_sai2} for paste...")
            user32.SetForegroundWindow(hwnd_sai2)
            time.sleep(0.2)
            
        # 模擬 Ctrl + V
        log_debug("Simulating Ctrl+V paste...")
        press_keys([0x11, 0x56])
        winsound.MessageBeep(winsound.MB_OK)
        log_debug("Workflow completed!")

    def on_exit(self):
        self.root.destroy()

def find_sai2_hwnd():
    hwnd_out = [0]
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _cb(hwnd, lparam):
        buf_size = 512
        buf = ctypes.create_unicode_buffer(buf_size)
        user32.GetWindowTextW(hwnd, buf, buf_size)
        title = buf.value.lower()
        if "painttool sai" in title:
            hwnd_out[0] = hwnd
            return False
        return True
    cb_func = WNDENUMPROC(_cb)
    user32.EnumWindows(cb_func, 0)
    return hwnd_out[0]

def clear_clipboard():
    import time
    opened = False
    for _ in range(10):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.02)
    if opened:
        user32.EmptyClipboard()
        user32.CloseClipboard()

def press_keys(keys):
    import time
    for k in keys:
        user32.keybd_event(k, 0, 0, 0)
        time.sleep(0.02)
    time.sleep(0.05)
    for k in reversed(keys):
        user32.keybd_event(k, 0, 2, 0)
        time.sleep(0.02)
    time.sleep(0.15)

# 角標錨定用的特徵色 (極不可能出現在畫作左上角的顏色)
MARKER_COLOR = (137, 42, 250, 255)

def _copy_active_layer():
    """Ctrl+A 全選後 Ctrl+C 複製目前圖層 (注意: SAI2 會自動裁掉透明邊界)"""
    clear_clipboard()
    press_keys([0x11, 0x41])  # Ctrl + A
    time.sleep(0.25)
    press_keys([0x11, 0x43])  # Ctrl + C
    time.sleep(0.35)
    return read_image_from_clipboard()

def _same_image(a, b):
    return (a is not None and b is not None and
            a.size == b.size and a.tobytes() == b.tobytes())

def acquire_whole_layer_anchored():
    """
    取得「錨定於畫布 (0,0)」的目前圖層影像 (整層液化模式用)。

    SAI2 複製時會自動裁掉透明邊界，導致左/上有透明區域的圖層貼回時錯位。
    解法 (角標錨定法)：先在畫布左上角 (0,0) 貼上一顆 1x1 特徵色標記並向下
    合併到目前圖層，讓內容邊界框強制從 (0,0) 開始，左/上的透明邊距因此保留；
    複製完成後以 Ctrl+Z 還原圖層 (含驗證與自我修復)，並在軟體端清除標記像素。

    回傳 (影像, 警告訊息或 None)；失敗時回傳 (None, 錯誤訊息)。
    """
    # 1. 取得基準影像 (之後用來驗證圖層已還原)
    base_img = _copy_active_layer()
    if base_img is None:
        return None, "無法複製圖層（目前圖層可能為空）"
    log_debug(f"acquire_whole_layer: base image {base_img.width}x{base_img.height}")

    # 2. 在 (0,0) 貼上 1x1 標記並向下合併到目前圖層
    global ACTIVE_OFFSET, ACTIVE_CANVAS_SIZE
    ACTIVE_OFFSET = None
    ACTIVE_CANVAS_SIZE = (0, 0)
    marker = Image.new("RGBA", (1, 1), MARKER_COLOR)
    if not copy_image_to_clipboard(marker):
        return None, "無法寫入剪貼簿"
    time.sleep(0.15)
    press_keys([0x11, 0x56])  # Ctrl + V 貼上標記 (SAI2 貼在畫布左上角)
    time.sleep(0.35)
    press_keys([0x11, 0x45])  # Ctrl + E 向下合併到目前圖層
    time.sleep(0.35)

    # 3. 複製錨定後的圖層 (邊界框現在從 (0,0) 開始)
    anchored = _copy_active_layer()
    if anchored is not None:
        log_debug(f"acquire_whole_layer: anchored image {anchored.width}x{anchored.height}")

    # 4. 還原使用者圖層：撤銷合併與貼上，驗證失敗時自我修復 (最多多按 4 次)
    press_keys([0x11, 0x5A])  # Ctrl + Z (撤銷合併)
    time.sleep(0.25)
    press_keys([0x11, 0x5A])  # Ctrl + Z (撤銷貼上)
    time.sleep(0.25)
    restored = False
    for _ in range(4):
        chk = _copy_active_layer()
        if _same_image(chk, base_img):
            restored = True
            break
        log_debug("acquire_whole_layer: layer not restored yet, pressing extra Ctrl+Z")
        press_keys([0x11, 0x5A])
        time.sleep(0.25)
    press_keys([0x11, 0x44])  # Ctrl + D 取消全選
    time.sleep(0.1)

    restore_warn = None
    if not restored:
        restore_warn = "圖層自動還原驗證失敗！請立即檢查 SAI2 的復原 (Ctrl+Z) 狀態，確認左上角沒有殘留標記像素。"
        log_debug("acquire_whole_layer: RESTORE VERIFICATION FAILED")

    if anchored is None:
        return None, restore_warn or "標記後複製圖層失敗"
    if anchored.size == (1, 1):
        msg = "無法合併標記（目前圖層可能是圖層資料夾或特殊圖層），請改用一般點陣圖層。"
        if restore_warn:
            msg += "\n" + restore_warn
        return None, msg

    # 5. 清除 (0,0) 的標記像素
    anchored = anchored.convert("RGBA")
    if anchored.getpixel((0, 0)) == MARKER_COLOR:
        if anchored.size == base_img.size:
            # 圖層內容原本就頂到左上角 → 用基準影像還原使用者原本的像素
            anchored.putpixel((0, 0), base_img.convert("RGBA").getpixel((0, 0)))
        else:
            anchored.putpixel((0, 0), (0, 0, 0, 0))
        log_debug("acquire_whole_layer: marker pixel cleared at (0,0)")
    else:
        log_debug(f"acquire_whole_layer: (0,0) is {anchored.getpixel((0, 0))}, marker not found "
                  "(paste position assumption may not hold)")

    return anchored, restore_warn

def read_canvas_from_clipboard():
    import time
    opened = False
    for _ in range(10):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.05)
    if not opened:
        return None
    img = None
    try:
        if user32.IsClipboardFormatAvailable(8): # CF_DIB
            h_dib = user32.GetClipboardData(8)
            if h_dib:
                size = kernel32.GlobalSize(h_dib)
                p_dib = kernel32.GlobalLock(h_dib)
                if p_dib:
                    try:
                        class BITMAPINFOHEADER(ctypes.Structure):
                            _pack_ = 1
                            _fields_ = [
                                ('biSize', ctypes.wintypes.DWORD),
                                ('biWidth', ctypes.wintypes.LONG),
                                ('biHeight', ctypes.wintypes.LONG),
                                ('biPlanes', ctypes.wintypes.WORD),
                                ('biBitCount', ctypes.wintypes.WORD),
                                ('biCompression', ctypes.wintypes.DWORD),
                                ('biSizeImage', ctypes.wintypes.DWORD),
                                ('biXPelsPerMeter', ctypes.wintypes.LONG),
                                ('biYPelsPerMeter', ctypes.wintypes.LONG),
                                ('biClrUsed', ctypes.wintypes.DWORD),
                                ('biClrImportant', ctypes.wintypes.DWORD)
                            ]
                        header = BITMAPINFOHEADER.from_address(p_dib)
                        width = header.biWidth
                        height = header.biHeight
                        is_top_down = height < 0
                        height = abs(height)
                        pixel_bytes = ctypes.string_at(p_dib + 40, size - 40)
                        row_size = width * 3
                        padded_row_size = (row_size + 3) & ~3
                        img = Image.frombytes("RGB", (width, height), pixel_bytes, "raw", "BGR", padded_row_size, 1 if is_top_down else -1)
                    finally:
                        kernel32.GlobalUnlock(h_dib)
    finally:
        user32.CloseClipboard()
    return img

def find_match(canvas_img, selection_img):
    """
    在整張畫布中尋找選區圖像的位置 (用於原地貼回對齊)。
    以分散在選區各處的網格取樣點做特徵比對——相比只取左上角叢集像素，
    分散取樣涵蓋整個選區的特徵，大幅降低在相似區域誤判的機率。
    """
    cw, ch = canvas_img.size
    sw, sh = selection_img.size
    if sw > cw or sh > ch:
        return None
    canvas_rgba = canvas_img.convert("RGBA")
    sel_rgba = selection_img.convert("RGBA")

    sel_data = sel_rgba.load()
    key_pixels = []
    grid_n = 8
    for gy in range(grid_n):
        for gx in range(grid_n):
            x = min(sw - 1, int((gx + 0.5) * sw / grid_n))
            y = min(sh - 1, int((gy + 0.5) * sh / grid_n))
            r, g, b, a = sel_data[x, y]
            if a > 200:
                key_pixels.append((x, y, (r, g, b)))

    # 控制取樣數量以維持掃描速度
    if len(key_pixels) > 24:
        key_pixels = key_pixels[::len(key_pixels) // 24 + 1] + key_pixels[-1:]

    # 選區過小或幾乎全透明時，退回原本的循序掃描取樣
    if len(key_pixels) < 4:
        key_pixels = []
        for x in range(sw):
            for y in range(sh):
                r, g, b, a = sel_data[x, y]
                if a > 200:
                    key_pixels.append((x, y, (r, g, b)))
                    if len(key_pixels) >= 15:
                        break
            if len(key_pixels) >= 15:
                break
    if not key_pixels:
        return None

    canvas_data = canvas_rgba.load()
    tolerance = 15
    for cx in range(cw - sw + 1):
        for cy in range(ch - sh + 1):
            match = True
            for sx, sy, (sr, sg, sb) in key_pixels:
                cr, cg, cb, ca = canvas_data[cx + sx, cy + sy]
                if abs(cr - sr) > tolerance or abs(cg - sg) > tolerance or abs(cb - sb) > tolerance:
                    match = False
                    break
            if match:
                return cx, cy
    return None

if __name__ == "__main__":
    # 高 DPI 支援
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
        
    root = tk.Tk()
    app = HotkeyManager(root)
    root.mainloop()
