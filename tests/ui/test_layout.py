# -*- coding: utf-8 -*-
"""版面：主視窗按鈕列（繁中 / 英文）不被裁切、精簡模式進出還原最小尺寸、研究視窗與筆刷工坊的最小尺寸容得下內容"""
import os
import sys
import tkinter as tk
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, headless_main, make_app, close_app, tmpdir  # noqa: E402

for lang in ('zh_tw', 'en_us'):
    M, tmp = headless_main(tmpdir(), language=lang)
    root, app = make_app(M)
    bar = next(w for w in app.main_container.winfo_children()
               if isinstance(w, tk.Frame) and sum(isinstance(c, tk.Button) for c in w.winfo_children()) >= 8)
    clipped = [c.cget('text') for c in bar.winfo_children()
               if c.winfo_x() + c.winfo_width() > bar.winfo_width() or c.winfo_width() < c.winfo_reqwidth()]
    check(not clipped, f'{lang}: clipped buttons {clipped}')
    check(root.minsize()[0] >= bar.winfo_reqwidth() - 2, f'{lang}: min width fits button bar')
    if lang == 'zh_tw':
        normal_min = root.minsize()
        app.toggle_mini_mode()
        root.update()
        check(root.winfo_height() < normal_min[1] // 4, f'mini mode is a small strip ({root.winfo_height()}px)')
        check(root.minsize()[1] < normal_min[1], 'mini mode lifts min size')
        app.toggle_mini_mode()
        root.update()
        check(root.minsize() == normal_min, 'min size restored after mini mode')
    close_app(root, app)

# 研究視窗：最小寬度 = 工具列需要的寬度（「重新擷取」不會被裁切）
import types  # noqa: E402
import study_window as SW  # noqa: E402
import brush_studio as BS  # noqa: E402
from _helpers import quest_manager  # noqa: E402
root = tk.Tk()
root.withdraw()
q = quest_manager()
q.ensure_today()
st = q.add_today('t_st_color')
fake_app = types.SimpleNamespace(quests=q, _settings={'study_topmost': False}, var_status=tk.StringVar())
SW.StudyWindow._load_reference = lambda self: None
w = SW.StudyWindow(root, fake_app, st['uid'], tmpdir())
w.compare = True
w._refresh_tool_buttons()
root.update()
bar = w.b_flip.master
check(w.minsize()[0] >= bar.winfo_reqwidth(), f'study min width {w.minsize()} vs toolbar {bar.winfo_reqwidth()}')
check(w.b_recapture.winfo_x() + w.b_recapture.winfo_width() <= bar.winfo_width(), 'recapture visible')
w.close()

# 筆刷工坊：最小尺寸 = 內容需要的尺寸
BS.SETTINGS_FILE = os.path.join(tmpdir(), 'brush.json')
BS.SAI2SettingsManager.get_settings_dir = staticmethod(lambda: None)
BS.read_clipboard_safely = lambda: None
b = BS.BrushStudioWindow(root)
root.update()
check(b.minsize() == (b.winfo_reqwidth(), b.winfo_reqheight()) or b.minsize()[0] >= b.winfo_reqwidth() - 2,
      f'brush studio min size {b.minsize()} vs content {b.winfo_reqwidth()}x{b.winfo_reqheight()}')
b.destroy()
root.destroy()
done()
