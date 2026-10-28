# -*- coding: utf-8 -*-
"""作品縮時影片的後製：合併片段（解析度相同直接串接；不同時以時間最長的解析度為準，其他等比例縮放補邊、不拉伸）、
匯出指定長度（等比例加速；比較短時不放慢）。用 ffmpeg 產生的小影片測試；沒有 ffmpeg 時略過"""
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image  # noqa: E402

from core import video_tools as V  # noqa: E402

d = tmpdir()
open(os.path.join(d, '合併_20261001_000000.mp4'), 'w').close()
open(os.path.join(d, '縮時_60秒_20261001_000000.mp4'), 'w').close()
open(os.path.join(d, 'last_frame.jpg'), 'w').close()
check(V.segments(d) == [], 'merged / exported files and previews are not segments')

if V.available():
    def clip(name, size, sec, square=True):
        """白色正方形在中間的片段（用來檢查有沒有被拉伸）"""
        w, h = size
        box = f'drawbox=x={w // 2 - 50}:y={h // 2 - 50}:w=100:h=100:color=white:t=fill' if square else 'null'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'color=c=0x181818:s={w}x{h}:r=30:d={sec}',
                        '-vf', box, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', os.path.join(d, name)], check=True)

    def frame_box(path, t):
        png = path + f'.{t}.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', path, '-frames:v', '1', '-y', png], check=True)
        im = Image.open(png).convert('L')
        bb = im.point(lambda v: 255 if v > 200 else 0).getbbox()
        return bb[2] - bb[0], bb[3] - bb[1]

    clip('20261020_100000.mp4', (640, 360), 4)
    clip('20261021_100000.mp4', (640, 360), 3)
    check([os.path.basename(p) for p in V.segments(d)] == ['20261020_100000.mp4', '20261021_100000.mp4'], 'segments in time order')
    seen = []
    r = V.merge(d, seen.append)
    info = V.probe(r['path'])
    check(r['copied'] and r['segments'] == 2 and abs(info['duration'] - 7.0) < 0.3, f'same size → joined without re-encoding {info}')
    check(seen and seen[-1] == 100, 'progress reported')

    clip('20261022_100000.mp4', (900, 380), 2)              # 中途按 Tab 隱藏面板：畫面變寬
    p = V.plan(V.segments(d))
    check(p['size'] == (640, 360) and p['resized'] == ['20261022_100000.mp4'] and not p['same'],
          'size with the most footage wins; the other is resized')
    r = V.merge(d)
    info = V.probe(r['path'])
    check((info['w'], info['h']) == (640, 360) and abs(info['duration'] - 9.0) < 0.3, f'mixed sizes merged {info}')
    bw, bh = frame_box(r['path'], 8.0)
    check(abs(bw - bh) <= 2, f'resized clip not stretched (square stays square: {bw}x{bh})')
    merged = [n for n in os.listdir(d) if n.startswith(V.MERGED_PREFIX) and n.endswith('.mp4')]
    check(len(merged) == 1 and not any(n.endswith('.part.mp4') for n in os.listdir(d)), f'one merged file kept ({merged})')

    r = V.export_length(d, 5)
    info = V.probe(r['path'])
    check(abs(info['duration'] - 5.0) < 0.3 and r['speed'] < 1 and os.path.basename(r['path']).startswith('縮時_5秒_'),
          f'exported to 5 s {info}')
    r = V.export_length(d, 60)
    info = V.probe(r['path'])
    check(r['speed'] == 1.0 and abs(info['duration'] - 9.0) < 0.3 and '縮時_9秒_' in os.path.basename(r['path']),
          'shorter than requested → not slowed down, named by its real length')

    for bad, call in (('two clips', lambda: V.merge(tmpdir())), ('no clips', lambda: V.export_length(tmpdir(), 60)),
                      ('too short', lambda: V.export_length(d, 2))):
        try:
            call()
            check(False, f'should fail: {bad}')
        except V.VideoError:
            check(True)
done()
