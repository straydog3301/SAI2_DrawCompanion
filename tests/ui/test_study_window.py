# -*- coding: utf-8 -*-
"""臨摹研究視窗：參考圖（以假的來源代替連網）、分段步驟、比對畫布與框選、自評推進課程、練習畫布、未存檔提示"""
import os
import sys
import types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, headless_main, make_app, close_app, run_mainloop  # noqa: E402

M, tmp = headless_main()
from PIL import Image, ImageDraw  # noqa: E402
import study_window as SW  # noqa: E402
from core import snapshots as SN, study_refs  # noqa: E402

# 假的參考圖來源（不連網）：比例 512x625，與 Zorn 肖像相同
REF = Image.new('RGB', (512, 625), (180, 150, 120))
study_refs.fetch_reference = lambda lesson, settings, exclude=None, rng=None: (
    REF.copy(), {'id': f'fake:{len(exclude or ())}', 'title': '測試肖像', 'artist': 'Test Artist', 'date': '1900',
                 'source': 'Fake Museum', 'url': 'https://example.com/x', 'license': '公有領域', 'why': lesson['look_for']})
SW.study_refs = study_refs
M.App._focus_sai2 = lambda self: False

root, app = make_app(M)
q = app.quests
app._settings.update({'study_topmost': False, 'study_canvas_dir': os.path.join(tmp, 'SAI2 練習')})
opened = []
app.open_in_sai2 = opened.append
q.path_state('color')['index'] = 1                                  # Lv2 限色調色盤
task = q.add_today('t_st_color')
check(task['params']['lesson_id'] == 'color_2' and task['target'] == 45 * 60, 'lesson attached')

app._quest_go(task['uid'])
win = app._study_win
check(q.active_study == task['uid'] and win is not None, 'go starts study + opens window')
for _ in range(40):
    if win.ref_img is not None:
        break
    run_mainloop(root, 100)
check(win.ref_img is not None and '測試肖像' in win.var_ref.get(), 'reference loaded')
check(os.path.isfile(task['ref']['cache']) and q.seen_refs('color_2') == {'fake:0'}, 'reference cached + seen')
check(win.show_palette and not win.gray, 'lesson default tools (palette)')

# 分段步驟依實際動筆時間推進
stages = []
for secs in (0, 6 * 60, 21 * 60, 36 * 60, 46 * 60):
    task['progress'] = secs
    win._tick()
    stages.append(win.var_phase.get())
check(stages == ['1. 觀察', '2. 大色塊', '3. 形與邊緣', '4. 比對修正', '4. 比對修正'], f'phases {stages}')
check(win.var_phase_left.get().startswith('已達預定時間'), 'overtime hint')
task['progress'] = 0
win._tick()
check('剩 5 分' in win.var_phase_left.get(), f'remaining rounds up: {win.var_phase_left.get()}')

# 比對畫布：裁掉工作區、拖曳框選、單擊取消
fake = Image.new('RGB', (900, 700), (90, 90, 90))
art = Image.new('RGB', (500, 600), (235, 220, 200))
ImageDraw.Draw(art).ellipse([100, 120, 400, 520], fill=(160, 90, 70))
fake.paste(art, (200, 50))
SW.capture_sai2_canvas = lambda: SN.trim_workspace(fake)
win.geometry('1500x1000')
root.update()
win._toggle_compare()
win._render()
root.update()
check(win.capture_img.size == (500, 600) and win._layout is not None, 'capture trimmed + side by side')
check(str(win.b_recapture.cget('state')) == 'normal', 'recapture enabled in compare mode')
lay = win._layout
E = types.SimpleNamespace
win._crop_start(E(x=lay['x'] + 2, y=lay['y'] + 2))
win._crop_end(E(x=lay['x'] + lay['w'] // 2, y=lay['y'] + lay['h'] // 2))
check(win.crop is not None and win._cropped_capture().size[0] < 300, f'crop {win.crop}')
win._crop_start(E(x=lay['x'] + 5, y=lay['y'] + 5))
win._crop_end(E(x=lay['x'] + 6, y=lay['y'] + 6))
check(win.crop is None, 'click clears crop')

# 練習畫布：同比例 PSD、依課程命名、同日不覆蓋
win._create_canvas(2000)
p1 = task['canvas']
im = Image.open(p1)
check(im.size == (1638, 2000) and os.path.basename(p1).startswith('色彩_Lv2_限色調色盤'), f'canvas {im.size} {p1}')
check(opened == [p1], 'canvas opened in SAI2')
win._create_canvas(1500)
check(task['canvas'].endswith('_2.psd') and Image.open(task['canvas']).size == (1229, 1500), 'second canvas')

# 未存檔畫布提示：只在研究計時中、偵測到畫布但沒有被追蹤時出現
app.tracker.get_state = lambda: {'sai2_running': True, 'raw_current_file': '新建畫布 1', 'current_file': None}
win._tick()
check('尚未存檔' in win.var_warn.get(), 'unsaved warning')
app.tracker.get_state = lambda: {'sai2_running': True, 'raw_current_file': 'a.psd', 'current_file': 'a.psd'}
win._tick()
check(win.var_warn.get() == '', 'no warning on saved file')

# 自評打卡（以假對話框代替互動）→ 推進到下一課、視窗關閉
M.StudyCheckinDialog = lambda parent, t, lesson, pass_rating: types.SimpleNamespace(result=(4, '冷暖有抓到'))
task['status'] = 'ready'
win._tick()
win._checkin()
root.update()
check(task['status'] == 'done' and task['rating'] == 4 and task['advanced_to'] == 'color_3', 'rating advances lesson')
check(app._study_win is None and '下一課' in app.var_status.get(), 'window closed + next lesson message')
check(q.current_lesson('color')['id'] == 'color_3', 'path index advanced')
close_app(root, app)
done()
