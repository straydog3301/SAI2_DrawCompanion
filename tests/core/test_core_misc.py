# -*- coding: utf-8 -*-
"""core/ 不依賴 Tk、程式資料目錄、語系載入、空白 PSD 產生"""
import os
import sys
import importlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir, REPO  # noqa: E402

block_tk()
CORE = ['paths', 'sai2_win', 'i18n', 'tracker', 'timelapse', 'brush_assets', 'daily_quests', 'growth',
        'snapshots', 'study_lessons', 'study_refs', 'psd_writer', 'single_instance', 'sai2_launcher']
for m in CORE:
    importlib.import_module('core.' + m)
check(len(CORE) == len([f for f in os.listdir(os.path.join(REPO, 'core')) if f.endswith('.py') and f != '__init__.py']),
      'every core module is covered by the no-Tk import check')

from core import paths, i18n  # noqa: E402
check(os.path.normcase(paths.APP_DIR) == os.path.normcase(REPO), f'APP_DIR {paths.APP_DIR}')
check(set(i18n.get_available_languages()) >= {'zh_tw', 'en_us', 'ja_jp'}, 'locales loaded')

# 三個語系檔的鍵必須完全一致，佔位符也要一致
import json, re  # noqa: E402
locs = {l: json.load(open(os.path.join(REPO, 'locales', f'{l}.json'), encoding='utf-8')) for l in ('zh_tw', 'en_us', 'ja_jp')}
check(set(locs['zh_tw']) == set(locs['en_us']) == set(locs['ja_jp']), 'locale keys identical')
for k, zh in locs['zh_tw'].items():
    want = set(re.findall(r'\{\w+\}', zh))
    for lang in ('en_us', 'ja_jp'):
        got = set(re.findall(r'\{\w+\}', locs[lang][k]))
        check(got <= want, f'{lang}:{k} placeholders {got} not in {want}')

# 空白 PSD：尺寸、顏色、PackBits 邊界（128 / 129 / 257）
from PIL import Image  # noqa: E402
from core.psd_writer import write_blank_psd  # noqa: E402
d = tmpdir()
for w, h, c in ((2000, 1500, (255, 255, 255)), (1, 1, (10, 20, 30)), (129, 3, (0, 0, 0)), (257, 2, (1, 2, 3)), (128, 5, (9, 9, 9))):
    p = os.path.join(d, f'{w}x{h}.psd')
    write_blank_psd(p, w, h, c)
    im = Image.open(p)
    im.load()
    check(im.size == (w, h) and im.mode == 'RGB' and im.getextrema() == tuple((v, v) for v in c), f'psd {w}x{h}')
try:
    write_blank_psd(os.path.join(d, 'bad.psd'), 0, 10)
    check(False, 'invalid size must raise')
except ValueError:
    check(True)

# 畫布擷取裁切：模擬 SAI2 實際的畫布視窗（深色外框、顏色接近工作區的捲軸＋箭頭、捲軸邊線）
from PIL import Image, ImageDraw  # noqa: E402
from core.snapshots import trim_workspace  # noqa: E402
W, H = 1600, 1000
shot = Image.new('RGB', (W, H), (61, 65, 80))
dr = ImageDraw.Draw(shot)
dr.rectangle((0, 0, W - 1, H - 1), outline=(23, 23, 28), width=3)
dr.rectangle((W - 26, 0, W - 1, H - 1), fill=(58, 61, 75))                    # 直捲軸
dr.rectangle((0, H - 26, W - 1, H - 1), fill=(58, 61, 75))                    # 橫捲軸
dr.line((W - 27, 0, W - 27, H), fill=(23, 23, 28))
dr.line((0, H - 27, W, H - 27), fill=(23, 23, 28))
dr.polygon([(W - 18, H - 40), (W - 8, H - 40), (W - 13, H - 34)], fill=(200, 200, 210))   # 捲軸箭頭
dr.rectangle((W - 24, 200, W - 4, 600), fill=(90, 95, 112))                   # 捲軸滑塊
dr.rectangle((500, 300, 1099, 749), fill=(255, 255, 255))                     # 600x450 畫布
dr.ellipse((600, 400, 800, 600), fill=(160, 90, 70))
cut = trim_workspace(shot)
check(cut.size == (600, 450), f'trim ignores frame + scrollbars: {cut.size}')
check(trim_workspace(Image.new('RGB', (300, 200), (61, 65, 80))).size == (300, 200), 'empty workspace kept')
done()
