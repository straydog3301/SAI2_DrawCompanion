# -*- coding: utf-8 -*-
"""程式資料所在目錄（設定檔、紀錄、快取都放這裡）

- 打包成 exe：exe 所在目錄；若 exe 在 dist/ 底下則取其上一層（build.bat 的預設輸出）
- 原始碼執行：專案根目錄（core/ 的上一層）
onefile 打包時 __file__ 會指向暫存的 _MEIxxxx 目錄，程式結束即被刪除，不能用來存放資料。
"""

import os
import sys

if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    APP_DIR = os.path.dirname(_exe_dir) if os.path.basename(_exe_dir).lower() == 'dist' else _exe_dir
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
