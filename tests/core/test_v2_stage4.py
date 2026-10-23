# -*- coding: utf-8 -*-
"""2.0 階段四核心：角色工作室（建立 / 指定狀態圖 / 精靈圖格數 / 清除 / 匯入 zip 與資料夾 / 刪除）、
快捷按鈕自訂動作、「如果…就…」規則、設定匯出與匯入"""
import json
import os
import sys
import zipfile
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir  # noqa: E402

block_tk()
from PIL import Image  # noqa: E402
from core import backup, pet_pack as P, rules as R, settings2, slots  # noqa: E402

src = tmpdir()
idle = os.path.join(src, 'my_idle.png')
Image.new('RGBA', (64, 64), (255, 0, 0, 255)).save(idle)
sheet = os.path.join(src, 'walk.png')
Image.new('RGBA', (64 * 4, 64), (0, 255, 0, 255)).save(sheet)
gif = os.path.join(src, 'yay.gif')
Image.new('RGB', (32, 32), 'blue').save(gif)
bad = os.path.join(src, 'note.txt')
open(bad, 'w').write('x')

# ─── 角色工作室 ──
pets = os.path.join(tmpdir(), 'pets')
pid = P.create_pack(pets, '我的/貓', idle)
folder = os.path.join(pets, pid)
pk = P.load_pack(folder)
check(pid == '我的_貓' and pk.name == '我的/貓' and set(pk.states) == {'idle'}, f'create {pid} {pk.states}')
check(P.create_pack(pets, '我的/貓', idle) == '我的_貓_2', 'unique folder names')
P.set_state(folder, 'drawing', sheet)
P.set_state(folder, 'drawing', frames=4, fps=8)
pk = P.load_pack(folder)
check(pk.states['drawing']['frames'] == 4 and len(pk.frames('drawing', 32)) == 4 and pk.frames('drawing', 32)[0][1] == 125,
      'sprite sheet frames + fps')
P.set_state(folder, 'cheer', gif)
P.set_state(folder, 'cheer', gif)
check(os.path.isfile(os.path.join(folder, 'cheer.gif')) and P.load_pack(folder).states['cheer']['file'] == 'cheer.gif', 'state file copied')
P.set_state(folder, 'idle', gif)
check(not os.path.exists(os.path.join(folder, 'idle.png')) and P.load_pack(folder).states['idle']['file'] == 'idle.gif',
      'replacing removes the old file')
for fn, args in ((P.set_state, (folder, 'idle', bad)), (P.set_state, (folder, 'dance', idle)), (P.clear_state, (folder, 'idle'))):
    try:
        fn(*args)
        check(False, f'{fn.__name__}{args[1:]} should fail')
    except ValueError:
        check(True)
P.clear_state(folder, 'cheer')
check('cheer' not in P.load_pack(folder).states and not os.path.exists(os.path.join(folder, 'cheer.gif')), 'clear state')
P.rename_pack(folder, '黑貓')
check(P.load_pack(folder).name == '黑貓', 'rename')

# 匯入：zip 多包一層資料夾、資料夾、壞掉的 zip、路徑穿越
zpath = os.path.join(src, 'share.zip')
with zipfile.ZipFile(zpath, 'w') as z:
    z.write(idle, 'Neko/idle.png')
    z.write(gif, 'Neko/sleep.gif')
iid = P.import_pack(zpath, pets)
check(iid == 'share' and set(P.load_pack(os.path.join(pets, iid)).states) == {'idle', 'sleep'}, f'import zip {iid}')
check(P.import_pack(folder, pets) == '黑貓', 'import folder uses pet.json name')
evil = os.path.join(src, 'evil.zip')
with zipfile.ZipFile(evil, 'w') as z:
    z.writestr('../../escape.png', b'x')
for bad_src in (evil, bad):
    try:
        P.import_pack(bad_src, pets)
        check(False, f'{bad_src} should fail')
    except ValueError:
        check(True)
empty_zip = os.path.join(src, 'empty.zip')
with zipfile.ZipFile(empty_zip, 'w') as z:
    z.writestr('readme.txt', 'hi')
before = sorted(os.listdir(pets))
try:
    P.import_pack(empty_zip, pets)
    check(False)
except ValueError:
    check(sorted(os.listdir(pets)) == before, 'failed import leaves nothing')
P.delete_pack(pets, '我的_貓_2')
check(not os.path.exists(os.path.join(pets, '我的_貓_2')), 'delete pack')
for args in ((pets, ''), (pets, '..')):
    try:
        P.delete_pack(*args)
        check(False)
    except ValueError:
        check(True)

# ─── 快捷按鈕 ──
check(slots.describe('sketch')[0] == '速寫' and slots.describe(None)[0] == '', 'describe builtin')
url = {'type': 'url', 'label': 'Pinterest', 'target': 'https://pinterest.com'}
check(slots.describe(url)[1] == 'link' and slots.validate(url) is None, 'url slot')
check(slots.validate({'type': 'url', 'target': 'ftp://x'}) and slots.validate({'type': 'path', 'target': 'Z:\\none'}), 'invalid slots')
opened = []
check(slots.run_custom(url, browser=opened.append) is None and opened == ['https://pinterest.com'], 'run url')
check(slots.run_custom({'type': 'path', 'target': src}, startfile=opened.append) is None and opened[-1] == src, 'run path')
ran = []
check(slots.run_custom({'type': 'program', 'target': idle, 'args': '--a "b c"'}, popen=lambda a, cwd=None: ran.append(a)) is None
      and ran[0][1:] == ['--a', 'b c'], f'run program {ran}')
check(slots.normalize_slots(['sketch']) == ['sketch'] + [None] * 5 and slots.normalize_blocks(['x', 'quests']) == ['quests'],
      'normalize')


# ─── 規則 ──
class Clock:
    t = 0.0

    def __call__(self):
        return self.t


clk = Clock()
eng = R.RuleEngine(clk)
rs = [R.new_rule({'type': 'draw_minutes', 'value': 2}, {'type': 'bubble', 'value': '休息'}),
      R.new_rule({'type': 'open_file', 'value': '*練習*'}, {'type': 'open_study', 'value': ''}),
      R.new_rule({'type': 'after_time', 'value': '23:00'}, {'type': 'bubble', 'value': '晚了'}),
      R.new_rule({'type': 'sai2_start', 'value': ''}, {'type': 'record_on', 'value': ''}),
      R.new_rule({'type': 'checkin', 'value': ''}, {'type': 'snapshot', 'value': ''}),
      R.new_rule({'type': 'draw_minutes', 'value': 1}, {'type': 'bubble', 'value': 'x'}, enabled=False),
      R.new_rule({'type': 'draw_minutes', 'value': 0}, {'type': 'bubble', 'value': 'bad'})]
noon = datetime(2026, 10, 23, 12, 0)


def run(**ctx):
    base = {'now': noon, 'sai2_running': True, 'drawing': False, 'current_file': None, 'events': set()}
    base.update(ctx)
    return [a['type'] for a in eng.evaluate(rs, base)]


check(run(sai2_running=False) == [] and run() == ['record_on'], 'sai2 start fires on transition only')
check(run() == [], 'not again while running')
fired = []
for _ in range(130):
    clk.t += 1
    fired += run(drawing=True)
check(fired.count('bubble') == 1, f'draw streak fires once {fired}')
clk.t += R.BREAK_RESET_SEC + 1
run()
for _ in range(121):
    clk.t += 1
    fired += run(drawing=True)
check(fired.count('bubble') == 2, 'fires again after a long break')
check(run(current_file='本機磁碟 (D:) _ 色彩練習_1.psd') == ['open_study'] and run(current_file='本機磁碟 (D:) _ 色彩練習_1.psd') == [],
      'open file once per change')
check(run(current_file='a.psd') == [], 'non-matching file')
late = datetime(2026, 10, 23, 23, 30)
check(run(now=late, drawing=True) == ['bubble'] and run(now=late, drawing=True) == [], 'late night once a day')
check(run(events={'checkin'}) == ['snapshot'], 'checkin event')
check(R.validate(rs[6]) and 'bad' not in str(run(drawing=True)), 'invalid rule skipped')
check('連續動筆超過 2 分鐘' in R.describe(rs[0]), R.describe(rs[0]))
check(all(R.validate(R.new_rule(e['trigger'], e['actions'])) is None for e in R.EXAMPLES), 'examples are valid')
multi = R.new_rule({'type': 'checkin', 'value': ''}, [{'type': 'bubble', 'value': '好棒'}, {'type': 'pet', 'value': 'cheer'}])
check([a['type'] for a in R.RuleEngine().evaluate([multi], {'events': {'checkin'}})] == ['bubble', 'pet'], 'several actions run in order')
check('寵物說一句話：好棒、寵物做動作：歡呼' in R.describe(multi), R.describe(multi))
legacy = {'id': 'old', 'enabled': True, 'trigger': {'type': 'checkin', 'value': ''}, 'action': {'type': 'snapshot', 'value': ''}}
check(R.actions_of(legacy) == [{'type': 'snapshot', 'value': ''}] and R.validate(legacy) is None
      and 'action' not in R.normalize(legacy), 'old single-action rules still work')
check(R.validate({'id': 'e', 'trigger': {'type': 'checkin', 'value': ''}, 'actions': []}) == '至少要有一個動作'
      and '動作 2' in R.validate(R.new_rule({'type': 'checkin', 'value': ''}, [{'type': 'snapshot'}, {'type': 'pet', 'value': 'x'}])),
      'action validation')

# ─── 設定匯出 / 匯入 ──
a = tmpdir()
sa = settings2.Settings2(a)
sa.set('sai2_exe', r'C:\SAI2\sai2.exe')
sa.set('sources.pexels_key', 'SECRET')
sa.set('theme.accent', 'teal')
sa.set('rules', [rs[0]])
sa.set('pet.pack', 'cat')
sa.save()
os.makedirs(os.path.join(sa.pets_dir, 'cat'))
Image.new('RGBA', (32, 32)).save(os.path.join(sa.pets_dir, 'cat', 'idle.png'))
bundle = os.path.join(src, 'bundle.zip')
info = backup.export_bundle(sa, bundle)
names = zipfile.ZipFile(bundle).namelist()
data = json.loads(zipfile.ZipFile(bundle).read('settings.json'))
check(info['pets'] == 1 and 'pets/cat/idle.png' in names, 'pets exported')
check('sai2_exe' not in data and 'pexels_key' not in data['sources'] and data['theme']['accent'] == 'teal', 'local-only + secrets removed')
backup.export_bundle(sa, bundle + '2.zip', include_secrets=True)
check(json.loads(zipfile.ZipFile(bundle + '2.zip').read('settings.json'))['sources']['pexels_key'] == 'SECRET', 'secrets on request')

b = tmpdir()
sb = settings2.Settings2(b)
sb.set('sai2_exe', r'D:\mine.exe')
sb.set('sources.pexels_key', 'MINE')
os.makedirs(os.path.join(sb.pets_dir, 'cat'))
Image.new('RGBA', (32, 32)).save(os.path.join(sb.pets_dir, 'cat', 'idle.png'))
res = backup.import_bundle(sb, bundle)
check(res['pets'] == ['cat_2'] and sb.get('pet.pack') == 'cat_2', f'imported pack renamed and selected {res}')
check(sb.get('sai2_exe') == r'D:\mine.exe' and sb.get('sources.pexels_key') == 'MINE', 'local settings + own keys kept')
check(sb.get('theme.accent') == 'teal' and sb.get('rules')[0]['id'] == rs[0]['id'], 'shared settings merged')
check(settings2.Settings2(b).get('theme.accent') == 'teal', 'saved')
for bad_bundle in (zpath, bad):
    try:
        backup.import_bundle(sb, bad_bundle)
        check(False)
    except ValueError:
        check(True)
done()
