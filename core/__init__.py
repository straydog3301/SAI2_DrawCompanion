# -*- coding: utf-8 -*-
"""
core - 不依賴 Tk 的核心邏輯（2.0 換介面框架時可直接沿用）

規則：本套件內的模組不得 import tkinter / ImageTk / 任何介面模組；
介面層（main.py、study_window.py、brush_studio.py…）只透過這裡的公開函式與類別操作資料。
"""
