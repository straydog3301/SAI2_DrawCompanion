# -*- mode: python ; coding: utf-8 -*-
# DrawCompanion 2.0 打包設定（build2.bat 使用）。1.x 用 build.bat / SAI2_DrawCompanion.spec，兩個 exe 並存。
#
# 瘦身：只帶 2.0 用到的 Qt 模組（Core / Gui / Widgets / Network / Svg），去掉
#   - 用不到的 Qt 外掛：TLS、網路狀態、多餘的平台（只留 qwindows）、少見圖檔格式
#   - Qt 翻譯檔、軟體 OpenGL（opengl32sw.dll，約 20MB）
#   - tkinter 與 1.x 介面（2.0 不使用）
# 注意：libssl / libcrypto 是 Python 的 ssl 模組要用的（線上圖庫走 https），不能去掉。

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# exe 圖示：由內建角色「墨墨」的繪圖程式產生（不需要另外存圖檔，角色改了圖示也會跟著變）
sys.path.insert(0, SPECPATH)
from core import pet_builtin  # noqa: E402
ICON = os.path.join(SPECPATH, 'build', 'drawcompanion2.ico')
os.makedirs(os.path.dirname(ICON), exist_ok=True)
pet_builtin.save_ico(ICON)

hidden = (collect_submodules('core') + collect_submodules('ui2')
          + ['psutil', 'win32gui', 'win32api', 'win32con', 'win32process', 'pywintypes'])

EXCLUDES = [
    'tkinter', '_tkinter', 'PIL.ImageTk', 'PIL._tkinter_finder',
    'main', 'brush_studio', 'liquify_helper', 'study_window', 'growth_view', 'quest_manager_window', 'ui_kit',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtPdf', 'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets', 'PySide6.QtMultimedia', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
    'PySide6.QtTest', 'PySide6.QtDBus', 'PySide6.Qt3DCore', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
    'numpy', 'matplotlib', 'pydoc_data', 'lib2to3',
]

# 檔名含這些字的二進位檔不帶（不分大小寫）
DROP_BINARIES = (
    'opengl32sw', 'qminimal', 'qoffscreen', 'qdirect2d',
    'qcertonlybackend', 'qopensslbackend', 'qschannelbackend', 'qnetworklistmanager',
    'qtiff', 'qwbmp', 'qicns', 'qtga', 'qpdf',
    'qt6pdf', 'qt6qml', 'qt6quick', 'qt6virtualkeyboard', 'qt6opengl',
)
DROP_DATA_DIRS = ('PySide6/translations', 'PySide6\\translations')

a = Analysis(
    ['drawcompanion2.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('locales', 'locales'),
        ('native/sai2mod/mscms.dll', 'native/sai2mod'),
        ('native/sai2mod/dwmapi.dll', 'native/sai2mod'),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,
)
a.binaries = [b for b in a.binaries if not any(k in b[0].lower() for k in DROP_BINARIES)]
a.datas = [d for d in a.datas if not d[0].startswith(DROP_DATA_DIRS)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DrawCompanion2',
    icon=ICON,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # Qt 的 DLL 用 UPX 壓縮容易出錯，也會讓防毒軟體誤判
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
