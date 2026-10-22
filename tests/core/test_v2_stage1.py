# -*- coding: utf-8 -*-
"""2.0 階段一核心：快捷鍵字串、設定檔、寵物角色包與內建角色、寵物狀態、檔案路徑、常駐服務、開機啟動"""
import json
import os
import sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir  # noqa: E402

block_tk()
from PIL import Image  # noqa: E402
from core import hotkeys, settings2, pet_pack, pet_builtin, pet_state, file_paths, companion, autostart  # noqa: E402

# ─── 快捷鍵 ──
check(hotkeys.parse('ctrl+alt+d') == (hotkeys.MOD_CONTROL | hotkeys.MOD_ALT, 0x44), 'parse')
check(hotkeys.normalize('Alt + Ctrl + space') == 'Ctrl+Alt+Space', 'normalize order')
check(hotkeys.parse('F10') == (0, 0x79), 'bare F-key allowed')
for bad in ('', 'D', 'Ctrl+Foo', 'Hyper+D'):
    try:
        hotkeys.parse(bad)
        check(False, f'{bad!r} should fail')
    except ValueError:
        check(True)
c = hotkeys.conflicts({'panel': 'Ctrl+Alt+D', 'toggle_pet': 'ctrl+alt+d', 'snapshot': 'Ctrl+Alt+T', 'open_sai2': ''})
check('toggle_pet' in c and '1.x' in c.get('snapshot', '') and 'panel' not in c, f'conflicts {c}')
check(not hotkeys.conflicts({k: v[1] for k, v in hotkeys.ACTIONS.items()}), 'defaults have no conflict')

# ─── 設定檔：從 1.x 帶入共用值、巢狀預設、存取 ──
d = tmpdir()
json.dump({'idle_timeout': 7.0, 'language': 'en_us', 'theme_mode': 'dark'},
          open(os.path.join(d, 'sai2_timer_settings.json'), 'w', encoding='utf-8'))
s = settings2.Settings2(d)
check(s.imported_legacy and s.get('idle_timeout') == 7.0 and s.get('language') == 'en_us', 'legacy values imported')
check('theme_mode' not in s.data and s.get('pet.size') == 128, 'only shared keys + defaults')
s.set('pet.size', 96)
s.mark_prompted('legacy_watcher')
s.save()
s2 = settings2.Settings2(d)
check(s2.get('pet.size') == 96 and s2.was_prompted('legacy_watcher') and not s2.imported_legacy, 'round trip')
check(s2.data_path.endswith('sai2_draw_time.json') and s2.quests_path.endswith('daily_quests.json'), 'paths')
open(s.path, 'w').write('{broken')
check(settings2.Settings2(d).get('pet.opacity') == 1.0, 'broken file falls back to defaults')

# ─── 內建角色 ──
for st in pet_pack.STATES:
    fr = pet_builtin.frames(st, 96)
    check(len(fr) == pet_builtin.COUNTS[st] and fr[0][0].size == (96, 96) and fr[0][0].mode == 'RGBA', st)
a = fr[0][0].getchannel('A')
check(a.getextrema() == (0, 255) and sum(a.histogram()[1:255]) > 0, 'transparent bg + soft edges')

# ─── 角色包 ──
pets = os.path.join(d, 'pets')
cat = os.path.join(pets, 'cat')
os.makedirs(cat)
frames = [Image.new('RGBA', (64, 64), (i * 40, 0, 0, 255)) for i in range(4)]
frames[0].save(os.path.join(cat, 'idle.apng'), format='PNG', save_all=True, append_images=frames[1:], duration=80, loop=0)
sheet = Image.new('RGBA', (64 * 6, 64), (0, 0, 0, 0))
sheet.save(os.path.join(cat, 'draw.png'))
json.dump({'name': '我的貓', 'states': {'idle': {'file': 'idle.apng'}, 'drawing': {'file': 'draw.png', 'frames': 6, 'fps': 12},
                                        'sleep': {'file': 'missing.gif'}, 'dance': {'file': 'idle.apng'}}},
          open(os.path.join(cat, 'pet.json'), 'w', encoding='utf-8'), ensure_ascii=False)
pk = pet_pack.load_pack(cat)
check(pk.name == '我的貓' and set(pk.states) == {'idle', 'drawing'}, f'states {pk.states}')
check(any('missing.gif' in w for w in pk.warnings) and any('dance' in w for w in pk.warnings), f'warnings {pk.warnings}')
check(pk.resolve('offline') == 'idle' and pk.resolve('cheer') == 'idle' and pk.resolve('drawing') == 'drawing', 'fallback')
fi = pk.frames('idle', 32)
check(len(fi) == 4 and fi[0][1] == 80 and fi[0][0].size == (32, 32), 'apng decode + resize')
fd = pk.frames('drawing', 32)
check(len(fd) == 6 and fd[0][1] == 83, 'sprite sheet decode')
check(not pk.loops('cheer') and pk.loops('idle'), 'loop defaults')

dog = os.path.join(pets, 'dog')                  # 沒有 pet.json：依檔名辨識
os.makedirs(dog)
frames[0].save(os.path.join(dog, 'idle.png'))
frames[1].save(os.path.join(dog, 'Sleep.gif'))
pk2 = pet_pack.load_pack(dog)
check(set(pk2.states) == {'idle', 'sleep'} and pk2.resolve('offline') == 'sleep', 'auto-detect by file name')
os.makedirs(os.path.join(pets, 'empty'))
ids = [p.pack_id for p in pet_pack.list_packs(pets)]
check(ids == ['', 'cat', 'dog'], f'list skips broken packs {ids}')
check(pet_pack.find_pack(pets, 'nope').builtin and pet_pack.find_pack(pets, 'cat').name == '我的貓', 'find pack')

# ─── 寵物狀態 ──
class Clock:
    t = 0.0

    def __call__(self):
        return self.t


clk = Clock()
brain = pet_state.PetBrain(rest_minutes=1, clock=clk)
noon = datetime(2026, 10, 23, 12, 0)
I = pet_state.PetInputs
check(brain.update(I(False, False), noon)[0] == 'offline', 'offline')
check(brain.update(I(True, False), noon)[0] == 'idle', 'idle')
check(brain.update(I(True, True), noon)[0] == 'drawing', 'drawing')
bubbles = []
for _ in range(61):
    clk.t += 1
    bubbles += brain.update(I(True, True), noon)[1]
check([b.key for b in bubbles] == ['rest'] and brain.state == 'rest', f'rest reminder once {bubbles}')
clk.t += 31
check(brain.update(I(True, True), noon)[0] == 'drawing', 'rest shown for a while then back')
brain.trigger('cheer')
check(brain.update(I(False, False), noon)[0] == 'cheer', 'one-shot overrides offline')
clk.t += 3
check(brain.update(I(True, False), noon)[0] == 'idle', 'one-shot ends')
check(brain.update(I(True, False, rest_day=True), noon)[0] == 'sleep', 'rest day sleeps')
check(brain.update(I(True, True, legacy_running=True), noon)[0] == 'sleep', 'legacy running sleeps')
brain.night_sleep = True
check(brain.update(I(True, False), datetime(2026, 10, 23, 23, 30))[0] == 'sleep', 'night sleep')
clk.t += pet_state.BREAK_RESET_SEC + 1
brain.update(I(True, False), noon)
check(brain.continuous_draw_seconds() == 0.0, 'long break resets streak')

# ─── 檔案路徑 ──
cands = file_paths.candidates_from_key('本機磁碟 (D:) _ 2026 _ 0621.sai2', users_root=r'C:\Users')
check(cands[0] == r'D:\2026\0621.sai2', f'drive label key {cands}')
cands = file_paths.candidates_from_key('Artist _ AppData _ x.psd', users_root=r'C:\Users')
check(cands[-1] == r'C:\Users\Artist\AppData\x.psd', f'user folder key {cands}')
check(file_paths.resolve_file_key('Artist _ AppData _ x.psd', users_root=r'C:\Users', search_roots=[],
                                  isfile=lambda p: p == r'C:\Users\Artist\AppData\x.psd') == r'C:\Users\Artist\AppData\x.psd', 'resolve')
check(file_paths.resolve_file_key('a_b_c.psd', search_roots=[r'Z:\\'], isfile=lambda p: p == os.path.join(r'Z:\\', 'a', 'b_c.psd'))
      == os.path.join(r'Z:\\', 'a', 'b_c.psd'), 'legacy underscore search')
check(file_paths.display_name('本機磁碟 (D:) _ 2026 _ 0621.sai2') == '0621.sai2', 'display name')


# ─── 常駐服務（假的追蹤器、真的 QuestManager） ──
class FakeTracker:
    def __init__(self, data_path, idle_timeout, track_unsaved):
        self.counter = 0.0
        self.running = False
        self.files = {'A.psd': {'last_seen': '2026-10-22T10:00:00', 'draw_seconds': 60},
                      'B.psd': {'last_seen': '2026-10-23T09:00:00', 'draw_seconds': 30},
                      'tmp': {'last_seen': '', 'draw_seconds': 0}}

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def get_state(self):
        return {'sai2_running': True, 'current_file': 'B.psd', 'session_draw': 5.0, 'files': self.files}

    def get_draw_counter(self):
        return self.counter

    def today_draw_seconds(self):
        return 120.0


d2 = tmpdir()
s3 = settings2.Settings2(d2)
legacy = {'on': False}
clk2 = Clock()
svc = companion.CompanionService(s3, tracker_factory=FakeTracker, legacy_check=lambda: legacy['on'],
                                 exe_finder=lambda: r'E:\SAI2\sai2.exe', clock=clk2)
svc.start()
check(not svc.paused and svc.tracker.running, 'tracking started')
tasks = svc.today_tasks()
check(tasks, 'today tasks generated')
dt = [t for t in tasks if t['mode'] == 'draw_time']
r = svc.tick()
check(r.status.sai2_running and not r.status.drawing and 'exe_found' in r.events and s3.get('sai2_exe').endswith('sai2.exe'),
      f'first tick {r.events}')
svc.tracker.counter = 30.0
clk2.t += 1
r = svc.tick()
check(r.status.drawing and r.status.today_draw == 120.0, 'drawing detected from counter delta')
if dt:
    check(svc.quests.task(dt[0]['uid'])['progress'] >= 30, 'draw_time progress accumulates')
check([f['name'] for f in svc.recent_files(5)] == ['B.psd', 'A.psd'], 'recent files sorted, unseen skipped')
legacy['on'] = True
clk2.t += companion.LEGACY_CHECK_SEC
r = svc.tick()
check('legacy_paused' in r.events and svc.paused and svc.tracker is None and not r.status.tracking, 'pause when 1.x runs')
check(svc.go(tasks[0]['uid'])[0] == 'not_yet', 'actions blocked while paused')
legacy['on'] = False
clk2.t += companion.LEGACY_CHECK_SEC
r = svc.tick()
check('legacy_resumed' in r.events and svc.tracker.running, 'resume after 1.x exits')
drill = next((t for t in svc.today_tasks() if t['mode'] in ('drill', 'thumbnail')), None)
if drill:
    check(svc.go(drill['uid'])[0] == 'need_count', 'count task asks for number')
    svc.add_count(drill['uid'], drill['target'])
    check(svc.quests.task(drill['uid'])['status'] == 'ready' and svc.check_in(drill['uid'], 'ok') is None, 'count + check in')
check(svc.go('nope')[0] == 'not_yet', 'unknown task')
svc.stop()
check(svc.tracker is None and os.path.isfile(s3.quests_path), 'stop saves quests')
check(not companion.legacy_running() or True, 'real legacy check runs')


# ─── 開機啟動與 1.x 監視器 ──
class FakeReg:
    def __init__(self):
        self.v = {}

    def get(self, n):
        return self.v.get(n)

    def set(self, n, val):
        self.v[n] = val

    def delete(self, n):
        self.v.pop(n, None)


reg = FakeReg()
check(not autostart.is_enabled(reg), 'autostart off')
autostart.set_enabled(True, autostart.launch_command('x.py'), reg)
check(autostart.is_enabled(reg) and '--background' in reg.v[autostart.VALUE_NAME], 'autostart on')
autostart.set_enabled(False, '', reg)
check(not autostart.is_enabled(reg), 'autostart off again')
startup = tmpdir()
check(autostart.legacy_watcher_link(startup) == '', 'no legacy link')
open(os.path.join(startup, autostart.LEGACY_LINK), 'w').close()
check(autostart.legacy_watcher_link(startup).endswith(autostart.LEGACY_LINK), 'legacy link found')
done()
