# -*- coding: utf-8 -*-
"""對話泡泡外觀（九宮格）、寵物提醒改成規則的設定遷移、泡泡圖跟著設定匯出 / 匯入"""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir  # noqa: E402

block_tk()
from PIL import Image  # noqa: E402
from core import backup, bubble_skin as B, pet_state, rules as R, settings2  # noqa: E402

# ─── 文字範圍與四邊 ──
check(B.margins([30, 20, 40, 10], 100, 50) == (30, 20, 30, 20), 'margins from text rect')
check(B.clamp_rect([90, 45, 40, 30], 100, 50) == [60, 20, 40, 30], 'rect pushed back inside')
check(B.clamp_rect([50, 30, -20, -10], 100, 50) == [30, 20, 20, 10], 'negative size from dragging up-left')
check(B.clamp_rect([10, 10, 1, 0], 100, 50)[2:] == [B.MIN_TEXT, B.MIN_TEXT], 'minimum size')
check(B.clamp_rect(None, 100, 50) == B.default_text_rect(100, 50), 'no rect → default')

# ─── 九宮格對應 ──
sl = B.slices(100, 50, (30, 20, 30, 20), 300, 120)
check(len(sl) == 9, '9 patches')
check(sl[0] == ((0, 0, 30, 20), (0, 0, 30, 20)), 'top-left corner not scaled')
check(sl[8] == ((70, 30, 30, 20), (270, 100, 30, 20)), 'bottom-right corner pinned to the edge')
check(sl[1][1] == (30, 0, 240, 20) and sl[3][1] == (0, 20, 30, 80), 'edges stretch one way only')
check(sl[4][1] == (30, 20, 240, 80), 'centre stretches both ways')
covered = sum(d[2] * d[3] for _s, d in sl)
check(covered == 300 * 120, 'patches cover the whole bubble')
sl = B.slices(100, 50, (30, 20, 30, 20), 300, 120, scale=2)
check(sl[0][1] == (0, 0, 60, 40) and sl[8][1] == (240, 80, 60, 40), 'scale enlarges corners')
sl = B.slices(100, 50, (30, 20, 10, 20), 20, 30)
check(sum(d[2] * d[3] for _s, d in sl) == 20 * 30 and sl[0][1][2] == 15, 'too small → corners shrink by ratio')
check(len(B.slices(100, 50, (0, 0, 0, 0), 200, 80)) == 1, 'no margins → one stretched patch')

check(B.normalize({'scale': 99, 'color': 'red', 'x': 1}) == {**B.DEFAULT, 'scale': B.SCALES[1]}, 'normalize clamps')

# ─── 匯入圖片 ──
app = tmpdir()
src = tmpdir()
png = os.path.join(src, 'frame.png')
Image.new('RGBA', (3000, 1500), (255, 255, 255, 200)).save(png)
name, w, h = B.import_image(app, png)
check(max(w, h) == B.MAX_SIDE and os.path.isfile(os.path.join(app, B.BUBBLES_DIR, name)), 'large image shrunk and copied')
check(B.image_path(app, {'image': name}) and B.image_path(app, {'image': 'nope.png'}) is None, 'image path lookup')
txt = os.path.join(src, 'a.txt')
open(txt, 'w').write('x')
try:
    B.import_image(app, txt)
    check(False, 'non-image rejected')
except ValueError:
    check(True, 'non-image rejected')
name2 = B.import_image(app, png)[0]
B.remove_unused(app, keep=name2)
check(os.listdir(os.path.join(app, B.BUBBLES_DIR)) == [name2], 'unused bubble images removed')

# ─── 設定：新安裝有預設的休息規則；舊設定的提醒轉成規則 ──
d = tmpdir()
s = settings2.Settings2(d)
check('rest_minutes' not in s.get('pet') and 'night_sleep' not in s.get('pet'), 'reminder settings removed')
check([r['trigger'] for r in s.get('rules')] == [{'type': 'draw_minutes', 'value': 50}], 'default rest rule')
check(R.validate(s.get('rules')[0]) is None, 'default rule valid')
check(s.get('pet.bubble_skin') == B.DEFAULT, 'default bubble skin')

d = tmpdir()
json.dump({'version': 3, 'pet': {'rest_minutes': 70, 'night_sleep': True},
           'rules': [{'id': 'x', 'enabled': True, 'trigger': {'type': 'checkin', 'value': ''},
                      'actions': [{'type': 'pet', 'value': 'cheer'}]}]},
          open(os.path.join(d, settings2.SETTINGS_FILE), 'w', encoding='utf-8'))
s = settings2.Settings2(d)
types = [r['trigger']['type'] for r in s.get('rules')]
check(types == ['draw_minutes', 'after_time', 'checkin'], f'old reminders became rules {types}')
check(s.get('rules')[0]['trigger']['value'] == 70 and '70 分鐘' in s.get('rules')[0]['actions'][0]['value'],
      'rest minutes kept')
check('rest_minutes' not in s.get('pet') and s.get('version') == settings2.SETTINGS_VERSION, 'migrated once')
saved = json.load(open(s.path, encoding='utf-8'))
check('night_sleep' not in saved['pet'], 'old keys dropped from file')

d = tmpdir()
json.dump({'version': 3, 'pet': {'rest_minutes': 0}, 'rules': []},
          open(os.path.join(d, settings2.SETTINGS_FILE), 'w', encoding='utf-8'))
check(settings2.Settings2(d).get('rules') == [], 'reminder off → no rule added')

d = tmpdir()
json.dump({'version': 3, 'pet': {}, 'rules': [{'id': 'y', 'trigger': {'type': 'draw_minutes', 'value': 30},
                                                'actions': [{'type': 'bubble', 'value': 'hi'}]}]},
          open(os.path.join(d, settings2.SETTINGS_FILE), 'w', encoding='utf-8'))
check(len(settings2.Settings2(d).get('rules')) == 1, 'existing rest-like rule not duplicated')

# 規則觸發的休息、睡覺動畫停留久一點
clk = [0.0]
brain = pet_state.PetBrain(rest_minutes=0, clock=lambda: clk[0])
brain.trigger('rest')
clk[0] = 20
check(brain.update(pet_state.PetInputs(True, False, False, False))[0] == 'rest', 'rule rest lasts')
brain.trigger('sleep')
clk[0] = 60
check(brain.update(pet_state.PetInputs(True, False, False, False))[0] == 'sleep', 'rule sleep lasts')

# ─── 匯出 / 匯入時泡泡圖一起帶走 ──
a = settings2.Settings2(tmpdir())
name = B.import_image(a.app_dir, png)[0]
a.set('pet.bubble_skin', {'image': name, 'text': [100, 100, 500, 300], 'color': '#334455', 'scale': 0.5})
a.save()
bundle = os.path.join(src, 'b.zip')
backup.export_bundle(a, bundle)
b = settings2.Settings2(tmpdir())
backup.import_bundle(b, bundle)
skin = b.get('pet.bubble_skin')
check(skin['image'] and skin['image'] != '' and B.image_path(b.app_dir, skin), 'bubble image imported')
check(skin['text'] == [100, 100, 500, 300] and skin['color'] == '#334455', 'skin settings imported')
os.remove(B.image_path(a.app_dir, a.get('pet.bubble_skin')))
backup.export_bundle(a, bundle)
c = settings2.Settings2(tmpdir())
backup.import_bundle(c, bundle)
check(c.get('pet.bubble_skin.image') == '', 'missing image → built-in bubble')
done()
