# -*- coding: utf-8 -*-
"""縮時錄影合成：固定輸出尺寸（畫布大小中途改變時等比例縮放補邊、不拉伸）、整理影格（缺號、寫壞的最後一張）、
找出沒有合成的錄影（當機、斷電、沒有 ffmpeg）並復原合成。只用暫存資料夾；需要 ffmpeg 的部分在沒有 ffmpeg 時略過"""
import json
import os
import subprocess
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402

from core import timelapse as TL  # noqa: E402

# ─── 輸出尺寸 ──
check(TL.pick_output_size({'3232x1909': 454, '3832x2012': 68}) == (3232, 1908), 'most frequent size, even')
check(TL.pick_output_size({(640, 360): 5, (900, 380): 5}) == (900, 380), 'tie → larger area')
check(TL.pick_output_size({}) is None and TL.pick_output_size({'bad': 3, '1x1': 9}) is None, 'no usable size')
f = TL.fit_filter((640, 360))
check('force_original_aspect_ratio=decrease' in f and 'pad=640:360' in f, 'scale keeps aspect, then pads')


def make_frames(d, sizes, ext='jpg', start=0, step=1):
    os.makedirs(d, exist_ok=True)
    n = start
    for (w, h) in sizes:
        im = Image.new('RGB', (w, h), (24, 24, 24))
        ImageDraw.Draw(im).rectangle((w // 2 - 60, h // 2 - 60, w // 2 + 60, h // 2 + 60), fill='white')
        im.save(os.path.join(d, f'frame_{n:06d}.{ext}'), quality=95)
        n += step


def age(path, seconds):
    t = time.time() - seconds
    for root, _dirs, files in os.walk(path):
        for name in files:
            os.utime(os.path.join(root, name), (t, t))
        os.utime(root, (t, t))


# ─── 整理影格 ──
d = os.path.join(tmpdir(), 'frames')
make_frames(d, [(320, 180)] * 5, step=2)                     # 0, 2, 4, 6, 8：缺號
open(os.path.join(d, 'frame_000010.jpg'), 'wb').write(open(os.path.join(d, 'frame_000008.jpg'), 'rb').read()[:300])
n, ext = TL.normalize_frames(d, check_tail=3)
names = sorted(os.listdir(d))
check(n == 5 and ext == 'jpg', f'truncated last frame removed ({n})')
check(names == [f'frame_{i:06d}.jpg' for i in range(5)], f'renumbered without gaps ({names})')
check(TL.frame_sizes(TL.frame_files(d)) == {'320x180': 5}, 'sizes read from headers')

# ─── 找出沒有合成的錄影 ──
out = tmpdir()
temp = os.path.join(out, 'temp')
old = os.path.join(temp, '暫存_測試作品_20261024_193240')
make_frames(old, [(320, 180)] * 3)
json.dump({'file': '暫存 _ 測試作品.sai2', 'subdir': '暫存_測試作品', 'duration': 30.0, 'multiplier': 5, 'fps': 30,
           'sizes': {'320x180': 3}}, open(os.path.join(old, TL.SESSION_META), 'w', encoding='utf-8'), ensure_ascii=False)
no_meta = os.path.join(temp, '舊版_作品_20261020_101010')
make_frames(no_meta, [(320, 180)] * 2)
recent = os.path.join(temp, '正在錄_20261024_200000')
make_frames(recent, [(320, 180)] * 2)
empty = os.path.join(temp, '空的_20261024_100000')
os.makedirs(empty)
busy = os.path.join(temp, '忙碌_20261024_100000')
make_frames(busy, [(320, 180)])
for p in (old, no_meta, empty, busy):
    age(p, 600)
found = TL.find_unexported(out, exclude=[busy])
by = {os.path.basename(x['dir']): x for x in found}
check(set(by) == {os.path.basename(old), os.path.basename(no_meta)}, f'old leftovers found ({sorted(by)})')
check(by[os.path.basename(old)]['name'] == '測試作品.sai2' and by[os.path.basename(old)]['frames'] == 3, 'name from session info')
check(by[os.path.basename(no_meta)]['subdir'] == '舊版_作品', 'subdir from folder name when no session info (1.x)')
check(not os.path.isdir(empty), 'empty leftover removed')
check(os.path.isdir(recent) and os.path.isdir(busy), 'recent and busy folders untouched')
check(TL.find_unexported(os.path.join(out, 'nope')) == [], 'missing folder → nothing')

# ─── 錄影資訊快照：切換檔案後重設的時間與倍速不影響前一段的合成 ──
rec = TL.TimelapseRecorder(output_dir=tmpdir(), fps=30)
rec.multiplier = 10
rec.enabled = True
rec.switch_file('A _ 一號.sai2')
check(os.path.isfile(os.path.join(rec.temp_dir, TL.SESSION_META)), 'session info written when recording starts')
jobs = []
rec._trigger_export = lambda name, tdir, count, job=None: jobs.append((name, job or rec._session_info()))
rec.total_recorded_duration = 42.0
rec._frame_sizes = {'640x360': 3}
rec.frame_count = 3
info = rec._session_info()
check(info['duration'] == 42.0 and info['multiplier'] == 10 and info['sizes'] == {'640x360': 3}, 'snapshot fields')
rec.switch_file(None)
check(jobs and jobs[0][0] == 'A _ 一號.sai2', 'export triggered on file close')

# ─── 每個作品各自錄（2.0）：跟著最上層的檔案，切回來接著錄，關閉時各自合成 ──
pf = TL.TimelapseRecorder(output_dir=tmpdir(), fps=30)
pf.per_file = True
pf.enabled = True
pf.switch_file('桌面 _ 作品A.sai2')
dir_a = pf.temp_dir
make_frames(dir_a, [(320, 180)] * 4)
pf.frame_count, pf.total_recorded_duration, pf._pressed_seconds = 4, 8.0, 6.0
pf._frame_sizes = {'320x180': 4}
pf.switch_file('下載 _ 參考.png')                       # 切去看參考圖
dir_ref = pf.temp_dir
check(dir_ref != dir_a and os.path.isdir(dir_a) and pf.frame_count == 0, 'switching keeps the first recording')
check(pf.pending_files() == ['下載 _ 參考.png', '桌面 _ 作品A.sai2'], 'both pending')
make_frames(dir_ref, [(320, 180)] * 2)
pf.frame_count, pf._pressed_seconds = 2, 0.5           # 只是看，幾乎沒下筆
pf.switch_file(None)                                    # 暫時沒有檔案（例如開檔中）：不合成
pf.switch_file('桌面 _ 作品A.sai2')
check(pf.temp_dir == dir_a and pf.frame_count == 4 and pf.total_recorded_duration == 8.0 and pf._pressed_seconds == 6.0,
      'back to A continues the same recording')
check(os.path.normcase(os.path.abspath(dir_ref)) in {os.path.normcase(os.path.abspath(d)) for d in pf.busy_dirs()},
      'kept recordings are not treated as crash leftovers')
age(dir_ref, 600)
check(all(x['dir'] != dir_ref for x in pf.find_unexported()), 'kept recording not offered for recovery')
merged = []
pf._trigger_export = lambda name, d, n, job=None: merged.append((name, d, n, job))
check(pf.export_all() == 1, 'one video merged')
check(merged[0][0] == '桌面 _ 作品A.sai2' and merged[0][2] == 4 and merged[0][3]['duration'] == 8.0, 'A merged with its own info')
check(not os.path.isdir(dir_ref), 'reference only looked at (no drawing) → discarded')
check(pf.pending_files() == [] and pf.active_file is None, 'nothing pending after merging')
pf.enabled = False
pf.switch_file('桌面 _ 作品A.sai2')
check(pf.active_file is None, 'nothing recorded while recording is off')

# ─── 隱藏浮動檢視：SAI2「新增檢視」的快捷鍵要使用者設定；沒設定時不送按鍵 ──
from core import companion, hotkeys, settings2  # noqa: E402
check(hotkeys.key_sequence('Ctrl+Shift+F8') == [0x11, 0x10, 0x77], 'key sequence: modifiers then key')
check(hotkeys.clash('ctrl+alt+n', {'sketch_next': 'Ctrl+Alt+N'}) == '速寫：下一張', "same as 2.0's own hotkey")
check(hotkeys.clash('Ctrl+Shift+N', {'sketch_next': 'Ctrl+Alt+N'}) is None, 'no clash')
fr = TL.TimelapseRecorder(output_dir=tmpdir(), fps=30)
fr.float_keys = None
pressed, msgs = [], []
orig_press = TL._press_keys
TL._press_keys = lambda vks: pressed.append(vks)
fr.on_status_msg = msgs.append
fr.sai_pid = os.getpid()
check(fr._ensure_float_window(12345, 'A _ a.sai2') is None and not pressed, 'no shortcut set → no keys sent to SAI2')
check(fr._float_given_up and msgs and '新增檢視' in msgs[0], 'falls back to paper-only and says why')
TL._press_keys = orig_press
s2 = settings2.Settings2(tmpdir())
svc = companion.CompanionService(s2, legacy_check=lambda: False, recorder_factory=TL.TimelapseRecorder)
svc.recorder = TL.TimelapseRecorder(output_dir=s2.videos_dir, fps=30)
svc.apply_recorder_settings()
check(svc.recorder.float_keys is None, 'default: not set (new SAI2 has no default shortcut)')
s2.set('timelapse.float_hotkey', 'Ctrl+Shift+N')
svc.apply_recorder_settings()
check(svc.recorder.float_keys == [0x11, 0x10, 0x4E], 'uses the shortcut the user set')
s2.set('timelapse.float_hotkey', 'Ctrl+Alt+N')
svc.apply_recorder_settings()
check(svc.recorder.float_keys is None, "same as 2.0's sketch hotkey → not used (2.0 would intercept it)")
svc._on_rec_status('⚠️ 問題')
svc._on_rec_status('⚠️ 問題')
check(svc._rec_msgs == ['⚠️ 問題'], 'recorder messages queued once')

# ─── 實際合成（需要 ffmpeg） ──
if TL.find_ffmpeg():
    def probe(path):
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', path],
                           capture_output=True, text=True)
        return tuple(int(v) for v in r.stdout.strip().split(','))

    def white_box(path, n):
        png = path + f'.{n}.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path, '-vf', f'select=eq(n\\,{n})', '-frames:v', '1', png],
                       capture_output=True)
        im = Image.open(png).convert('L')
        bb = im.point(lambda v: 255 if v > 200 else 0).getbbox()
        return bb[2] - bb[0], bb[3] - bb[1]

    out2 = tmpdir()
    r2 = TL.TimelapseRecorder(output_dir=out2, fps=30)
    msgs = []
    r2.on_export_progress = lambda p, m: msgs.append((p, m))
    tdir = os.path.join(out2, 'temp', '畫布_20261024_120000')
    make_frames(tdir, [(640, 360)] * 30 + [(900, 380)] * 20)    # 中途按 Tab 隱藏面板：畫布區域變寬
    job = {'file': '畫布 _ 作品.sai2', 'subdir': '畫布_作品', 'duration': 10.0, 'multiplier': 5, 'fps': 30,
           'sizes': {'640x360': 30, '900x380': 20}}
    r2._export_worker('畫布 _ 作品.sai2', tdir, 50, job)
    vids = [os.path.join(out2, '畫布_作品', x) for x in os.listdir(os.path.join(out2, '畫布_作品')) if x.endswith('.mp4')]
    check(len(vids) == 1 and probe(vids[0]) == (640, 360), 'fixed output size = most frequent frame size')
    w1, h1 = white_box(vids[0], 5)
    w2, h2 = white_box(vids[0], 40)
    check(abs(w1 - h1) <= 2 and abs(w2 - h2) <= 2, f'square stays square after size change ({w1}x{h1}, {w2}x{h2})')
    check(not os.path.isdir(tdir), 'temp frames removed after success')

    # 當機後復原：沒有寫完的最後一張、缺號都能處理，合成到原本作品的資料夾
    out3 = tmpdir()
    r3 = TL.TimelapseRecorder(output_dir=out3, fps=30)
    crash = os.path.join(out3, 'temp', '桌面_當機作品_20261024_090000')
    make_frames(crash, [(320, 180)] * 20)
    os.remove(os.path.join(crash, 'frame_000007.jpg'))
    open(os.path.join(crash, 'frame_000020.jpg'), 'wb').write(b'\xff\xd8\xff\xe0broken')
    json.dump({'file': '桌面 _ 當機作品.sai2', 'subdir': '桌面_當機作品', 'duration': 8.0, 'multiplier': 5, 'fps': 30,
               'sizes': {'320x180': 19}}, open(os.path.join(crash, TL.SESSION_META), 'w', encoding='utf-8'))
    age(crash, 600)
    items = r3.find_unexported()
    check(len(items) == 1 and r3.recover(items[0]), 'recovery started')
    check(not r3.recover(items[0]), 'same folder not recovered twice')
    check(r3.find_unexported(min_age=0) == [], 'folder being recovered is not listed again')
    for th in list(r3.export_threads):
        th.join(timeout=60)
    vdir = os.path.join(out3, '桌面_當機作品')
    check(os.path.isdir(vdir) and any(x.endswith('.mp4') for x in os.listdir(vdir)), 'recovered video in the work folder')
    check(os.path.isfile(os.path.join(vdir, 'last_frame.jpg')), 'last frame preview saved')
    check(not os.path.isdir(crash), 'temp removed after recovery')

    # 捨棄
    r4 = TL.TimelapseRecorder(output_dir=tmpdir(), fps=30)
    junk = os.path.join(r4.output_dir, 'temp', '不要了_20261024_080000')
    make_frames(junk, [(320, 180)] * 2)
    age(junk, 600)
    item = r4.find_unexported()[0]
    check(r4.discard(item) and not os.path.isdir(junk), 'discard removes the frames')
    check(not r4.discard({'dir': os.path.join(r4.output_dir, 'elsewhere')}), 'only folders under temp can be discarded')

# ─── 沒有 ffmpeg：保留影格，之後可以合成 ──
orig = TL.find_ffmpeg
TL.find_ffmpeg = lambda: False
r5 = TL.TimelapseRecorder(output_dir=tmpdir(), fps=30)
status = []
r5.on_status_msg = status.append
keep = os.path.join(r5.output_dir, 'temp', '沒有ffmpeg_20261024_070000')
make_frames(keep, [(320, 180)] * 3)
r5._export_worker('沒有ffmpeg.sai2', keep, 3, {'recovered': True})
TL.find_ffmpeg = orig
check(os.path.isdir(keep) and len(TL.frame_files(keep)) == 3, 'frames kept when ffmpeg is missing')
check(status and 'ffmpeg' in status[0], 'user told why')
done()
