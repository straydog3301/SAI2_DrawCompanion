# -*- coding: utf-8 -*-
"""core/ 不依賴 Tk、程式資料目錄、語系載入、空白 PSD 產生"""
import os
import sys
import importlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir, REPO  # noqa: E402

block_tk()
CORE = ['paths', 'sai2_win', 'i18n', 'tracker', 'timelapse', 'brush_assets', 'daily_quests', 'growth',
        'snapshots', 'study_lessons', 'study_refs', 'psd_writer']
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
done()
