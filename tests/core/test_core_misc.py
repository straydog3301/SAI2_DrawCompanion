# -*- coding: utf-8 -*-
"""core/ 不依賴 Tk、程式資料目錄、語系載入、空白 PSD 產生"""
import os
import sys
import importlib
import shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir, REPO  # noqa: E402

block_tk()
CORE = ['paths', 'sai2_win', 'i18n', 'tracker', 'timelapse', 'brush_assets', 'daily_quests', 'growth',
        'snapshots', 'study_lessons', 'study_refs', 'psd_writer', 'single_instance', 'sai2_launcher',
        'hotkeys', 'settings2', 'pet_pack', 'pet_builtin', 'pet_state', 'file_paths', 'companion', 'autostart',
        'sketch_source', 'study_tools', 'stats', 'works', 'slots', 'rules', 'backup', 'bubble_skin', 'onboarding', 'data_text', 'version', 'diagnostics', 'work_thumbs', 'exclusions', 'canvas_crop', 'ai_review', 'unsaved', 'video_tools', 'notes', 'sai2_filters']
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

# SAI2 濾鏡演算法測試：二值化、色調分離與 Alpha 保留
from core import sai2_filters as SF  # noqa: E402
grad = Image.new('RGBA', (4, 1))
grad.putdata([(10, 10, 10, 200), (127, 127, 127, 150), (128, 128, 128, 255), (250, 250, 250, 0)])
b_img = SF.apply_binarize(grad, threshold=128, transparent_white=False)
b_px = list(b_img.getdata())
check(b_px[0] == (0, 0, 0, 200) and b_px[1] == (0, 0, 0, 150), f'binarize dark: {b_px[:2]}')
check(b_px[2] == (255, 255, 255, 255) and b_px[3] == (255, 255, 255, 0), f'binarize light: {b_px[2:]}')

b_tr = SF.apply_binarize(grad, threshold=128, transparent_white=True)
b_tr_px = list(b_tr.getdata())
check(b_tr_px[0] == (0, 0, 0, 200) and b_tr_px[2] == (255, 255, 255, 0), f'binarize transparent white: {b_tr_px}')

p_img = SF.apply_posterize(grad, levels=2)
p_px = list(p_img.getdata())
check(p_px[0] == (0, 0, 0, 200) and p_px[2] == (255, 255, 255, 255) and p_px[3] == (255, 255, 255, 0),
      f'posterize levels=2: {p_px}')
p4_lut = SF.posterize_lut(4)
check(sorted(set(p4_lut)) == [0, 85, 170, 255], f'posterize 4 levels lut: {sorted(set(p4_lut))}')

# SAI2 原生濾鏡擴充模組（mscms.dll + sai2_filters_mod.ini）部署與開關測試
fake_sai2_dir = os.path.join(d, 'sai2_inst')
os.makedirs(fake_sai2_dir, exist_ok=True)
fake_sai2_exe = os.path.join(fake_sai2_dir, 'sai2.exe')
open(fake_sai2_exe, 'wb').close()
check(os.path.isfile(SF.get_mod_dll_source_path()), 'compiled native mscms.dll exists')
check(SF.is_own_mod_dll(SF.get_mod_dll_source_path()), 'bundled mscms.dll carries the ini-name marker')
# 舊版放的 dwmapi.dll（我們的）要清掉；別人的 dwmapi.dll 不能動
legacy_dll = os.path.join(fake_sai2_dir, 'dwmapi.dll')
shutil.copy2(SF.get_mod_dll_source_path(), legacy_dll)
ok, _msg = SF.sync_filters_mod(fake_sai2_exe, enabled=True, binarize=True, posterize=False)
check(ok, 'sync_filters_mod enable succeeds')
st_mod = SF.get_mod_status(fake_sai2_exe)
check(st_mod['dll_installed'] and st_mod['enabled'] and st_mod['binarize'] and not st_mod['posterize'],
      f'mod status after enable: {st_mod}')
check(os.path.isfile(os.path.join(fake_sai2_dir, 'mscms.dll')) and not os.path.exists(legacy_dll),
      'deploys mscms.dll only and removes our legacy dwmapi.dll')
check(st_mod['fx_stroke'], 'fx_stroke layer effect defaults on')
foreign = b'MZ some other mod'
open(legacy_dll, 'wb').write(foreign)
SF.sync_filters_mod(fake_sai2_exe, enabled=True)
check(open(legacy_dll, 'rb').read() == foreign, 'foreign dwmapi.dll left untouched')
os.remove(legacy_dll)
# 模組寫回的最近筆畫顏色要保留；fx_stroke 可單獨關閉
with open(os.path.join(fake_sai2_dir, 'sai2_filters_mod.ini'), 'a', encoding='ascii') as f:
    f.write('fx_stroke_color=12ab34\n')
ok, _msg = SF.sync_filters_mod(fake_sai2_exe, enabled=True, fx_stroke=False)
st_fx = SF.get_mod_status(fake_sai2_exe)
check(ok and not st_fx['fx_stroke'] and st_fx['binarize'], 'fx_stroke toggled off independently')
check(SF.read_mod_ini(fake_sai2_dir)['fx_stroke_color'] == '12ab34', 'fx_stroke_color preserved across ini rewrite')
# 新濾鏡（像素化、銳化）：未指定時預設開啟，資料驅動寫入 ini
check(st_mod['pixelate'] and st_mod['sharpen'], 'pixelate/sharpen default on in ini')
ok, _msg = SF.sync_filters_mod(fake_sai2_exe, enabled=True, filters={'sharpen': False})
st_mod_s = SF.get_mod_status(fake_sai2_exe)
check(ok and st_mod_s['pixelate'] and not st_mod_s['sharpen'], 'per-filter dict toggles sharpen off')
ini_txt = open(os.path.join(fake_sai2_dir, 'sai2_filters_mod.ini'), encoding='ascii').read()
check('sharpen=0' in ini_txt and 'pixelate=1' in ini_txt and 'debug=0' in ini_txt, f'ini content: {ini_txt!r}')
ok, _msg = SF.sync_filters_mod(fake_sai2_exe, enabled=False, binarize=True, posterize=True)
st_mod2 = SF.get_mod_status(fake_sai2_exe)
check(ok and not st_mod2['enabled'] and not st_mod2['dll_installed'], f'mod status after disable: {st_mod2}')
# mscms.dll 被別的模組占用：不覆蓋、不刪除，狀態回報衝突
other_mscms = os.path.join(fake_sai2_dir, 'mscms.dll')
open(other_mscms, 'wb').write(foreign)
ok, _msg = SF.sync_filters_mod(fake_sai2_exe, enabled=True)
st_c = SF.get_mod_status(fake_sai2_exe)
check(not ok and open(other_mscms, 'rb').read() == foreign and st_c['dll_conflict'] and not st_c['dll_installed'],
      f'foreign mscms.dll not overwritten: {_msg}')
SF.sync_filters_mod(fake_sai2_exe, enabled=False)
check(open(other_mscms, 'rb').read() == foreign, 'foreign mscms.dll not deleted on disable')
done()
