# -*- coding: utf-8 -*-
"""只留下畫紙：依新版 SAI2（2026-10）實測的畫布視窗版面模擬——四邊 3 px 外框、右側與下方的捲軸（以外框最內層同色的線分隔）、
暗色系／白色系的工作區、SAI2 在前景時變色的外框、畫紙縮小／放大填滿／旋轉、工作區上的筆刷游標；以及錄影時的畫紙裁切"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402

from core import canvas_crop as C  # noqa: E402

DARK = {'frame': [(88, 88, 88), (64, 64, 64), (40, 40, 40)], 'ws': (24, 24, 24), 'track': (48, 48, 48), 'thumb': (96, 96, 96)}
LIGHT = {'frame': [(177, 177, 177), (212, 212, 212), (248, 248, 248)], 'ws': (176, 176, 176), 'track': (232, 232, 232),
         'thumb': (150, 150, 150)}
# SAI2 在前景時，使用中畫面的外框變成主題色，捲軸分隔線仍是灰色
ACTIVE = dict(DARK, frame=[(120, 96, 64), (88, 74, 54), (55, 51, 45)], line=(40, 40, 40))
W, H, SB = 1600, 1000, 22


def sai2_view(theme, paper=None, rotate=0, fill=False, cursor=None):
    """畫布視窗：外框、捲軸、工作區與畫紙。paper=(x0, y0, x1, y1)；fill=True 時畫紙填滿畫面"""
    im = Image.new('RGB', (W, H), theme['ws'])
    d = ImageDraw.Draw(im)
    vr, vb = W - 3 - SB - 1, H - 3 - SB - 1          # 畫面右、下界（捲軸分隔線的位置）
    if fill:
        d.rectangle((3, 3, vr - 1, vb - 1), fill=(255, 255, 255))
        d.line((200, 300, 900, 700), fill=(60, 60, 60), width=6)
    elif paper:
        art = Image.new('RGBA', (paper[2] - paper[0], paper[3] - paper[1]), (255, 255, 255, 255))
        ImageDraw.Draw(art).ellipse((40, 40, art.width - 40, art.height - 40), outline=(50, 50, 50), width=5)
        if rotate:
            art = art.rotate(rotate, expand=True)
        cx, cy = (paper[0] + paper[2]) // 2, (paper[1] + paper[3]) // 2
        im.paste(art, (cx - art.width // 2, cy - art.height // 2), art)
    if cursor:
        d.ellipse(cursor, outline=(200, 200, 200), width=1)   # 筆刷游標（細圓圈）
    # 捲軸：分隔線（外框最內層顏色）＋軌道＋滑塊
    line = theme.get('line', theme['frame'][2])
    d.rectangle((vr, 0, W - 1, H - 1), fill=theme['thumb'])
    d.rectangle((0, vb, W - 1, H - 1), fill=theme['track'])
    d.rectangle((300, vb + 2, 1100, H - 4), fill=theme['thumb'])
    d.line((vr, 0, vr, vb), fill=line)
    d.line((0, vb, vr, vb), fill=line)
    for k, c in enumerate(theme['frame']):                   # 外框最後畫，四邊都在
        d.rectangle((k, k, W - 1 - k, H - 1 - k), outline=c)
    return im


for name, theme in (('dark', DARK), ('light', LIGHT), ('active', ACTIVE)):
    view = C.view_box(sai2_view(theme, (500, 250, 1012, 762)))
    check(view == (3, 3, W - 3 - SB - 1, H - 3 - SB - 1), f'{name}: view excludes frame and scrollbars {view}')
    box = C.paper_box(sai2_view(theme, (500, 250, 1012, 762)))
    check(box == (500, 250, 1012, 762), f'{name}: exact paper {box}')
    box = C.paper_box(sai2_view(theme, (500, 250, 1012, 762), cursor=(1200, 500, 1260, 560)))
    check(box == (500, 250, 1012, 762), f'{name}: brush cursor in the workspace ignored {box}')
    box = C.paper_box(sai2_view(theme, (500, 250, 1012, 762), cursor=(940, 200, 1100, 360)))
    check(box == (500, 250, 1012, 762), f'{name}: big brush cursor over the paper corner ignored {box}')
    box = C.paper_box(sai2_view(theme, fill=True))
    check(box == view, f'{name}: zoomed in (paper fills) → whole view without scrollbars {box}')
    box = C.paper_box(sai2_view(theme, (600, 300, 1000, 700), rotate=30))
    bw, bh = box[2] - box[0], box[3] - box[1]
    check(540 <= bw <= 560 and 540 <= bh <= 560, f'{name}: rotated paper → bounding box {bw}x{bh}')
    box = C.paper_box(sai2_view(theme, (-200, 200, 900, 700)))
    check(box[0] == 3 and box[1:] == (200, 900, 700), f'{name}: paper scrolled past the left edge {box}')

# 畫紙是深色、和工作區相近的顏色以外的情況：整片同色、白紙 → 不裁
check(C.paper_box(Image.new('RGB', (300, 200), (128, 128, 128))) == (0, 0, 300, 200), 'uniform image kept')
check(C.paper_box(Image.new('RGB', (300, 200), (255, 255, 255))) == (0, 0, 300, 200), 'white is never the workspace')
check(C.crop_paper(sai2_view(DARK, (500, 250, 1012, 762))).size == (512, 512), 'crop_paper')

# ─── 錄影：畫布模式只錄畫紙，畫紙範圍隔一段時間才重新偵測 ──
from core import timelapse as TL  # noqa: E402
rec = TL.TimelapseRecorder(output_dir=os.path.join(os.environ.get('TEMP', '.'), 'unused'), fps=30)
calls = []
orig = C.paper_box
C.paper_box = lambda img: (calls.append(1), orig(img))[1]
a = rec._paper_crop(sai2_view(DARK, (500, 250, 1012, 762)))
b = rec._paper_crop(sai2_view(DARK, (500, 250, 1012, 762)))
check(a.size == b.size == (512, 512) and len(calls) == 1, 'paper box cached between frames')
rec._paper['at'] -= 1.0
c = rec._paper_crop(sai2_view(DARK, (300, 200, 1100, 800)))
check(c.size == (800, 600) and len(calls) == 2, 'refreshed after a while (zoom / scroll followed)')
small = sai2_view(DARK, (500, 250, 1012, 762)).resize((W // 2, H // 2))
rec._paper_crop(small)
check(len(calls) == 3, 'refreshed when the canvas window size changes')
C.paper_box = orig
done()
