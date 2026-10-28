# -*- coding: utf-8 -*-
"""
video_tools.py - 作品縮時影片的後製：合併片段、匯出指定長度（不含 UI；需要 ffmpeg）

每次錄影（每段工作階段）合成一部「YYYYMMDD_HHMMSS.mp4」放在作品的影片資料夾。這裡：
- segments：資料夾裡錄影產生的原始片段（依時間排序；合併、匯出產生的檔案不算）
- merge：把片段接成一部。解析度都相同時直接串接（不重新編碼、不失真）；不同時以片段時間最長的解析度為準，
  其他片段等比例縮放並補邊（不拉伸）。輸出「合併_時間.mp4」，原始片段保留；再合併一次會取代舊的合併檔
- export_length：把全部片段壓成指定長度（例如 60 秒），整段等比例加速；片段比指定長度短時不放慢
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime

SEGMENT_RE = re.compile(r'^\d{8}_\d{6}(_\d+)?\.mp4$', re.I)
MERGED_PREFIX = '合併_'
EXPORT_PREFIX = '縮時_'
OUT_FPS = 30
_NO_WINDOW = 0x08000000


class VideoError(Exception):
    """給使用者看的錯誤訊息"""


def available() -> bool:
    return shutil.which('ffmpeg') is not None


def segments(folder: str) -> list[str]:
    """錄影產生的原始片段，依時間（檔名）排序"""
    try:
        names = sorted(n for n in os.listdir(folder) if SEGMENT_RE.match(n))
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names]


# ─── 讀取影片資訊 ──
def probe(path: str) -> dict:
    """{'w', 'h', 'duration', 'codec'}；讀不到時丟 VideoError"""
    if shutil.which('ffprobe'):
        try:
            out = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                 'stream=width,height,codec_name:format=duration', '-of', 'json', path],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
                creationflags=_NO_WINDOW)
            data = json.loads(out.stdout or '{}')
            st = (data.get('streams') or [{}])[0]
            return {'w': int(st['width']), 'h': int(st['height']), 'codec': st.get('codec_name', ''),
                    'duration': float((data.get('format') or {}).get('duration') or 0.0)}
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
            pass
    # 沒有 ffprobe：從 ffmpeg -i 的訊息解析
    try:
        err = subprocess.run(['ffmpeg', '-hide_banner', '-i', path], capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=30, creationflags=_NO_WINDOW).stderr
    except (OSError, subprocess.SubprocessError) as e:
        raise VideoError(f'無法讀取影片：{e}') from None
    m_size = re.search(r'Video: (\w+).*?, (\d{2,5})x(\d{2,5})', err)
    m_dur = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', err)
    if not m_size or not m_dur:
        raise VideoError(f'無法讀取影片「{os.path.basename(path)}」')
    h, mi, se = m_dur.groups()
    return {'w': int(m_size.group(2)), 'h': int(m_size.group(3)), 'codec': m_size.group(1),
            'duration': int(h) * 3600 + int(mi) * 60 + float(se)}


def plan(paths: list[str]) -> dict:
    """合併前的檢查：各片段資訊、輸出解析度、是否需要重新編碼、總長度"""
    infos = [dict(probe(p), path=p) for p in paths]
    by_size: dict[tuple, float] = {}
    for i in infos:
        by_size[(i['w'], i['h'])] = by_size.get((i['w'], i['h']), 0.0) + i['duration']
    w, h = max(by_size, key=lambda k: (by_size[k], k[0] * k[1]))
    w, h = w - w % 2, h - h % 2
    same = len(by_size) == 1 and len({i['codec'] for i in infos}) == 1
    return {'infos': infos, 'size': (w, h), 'same': same, 'duration': sum(i['duration'] for i in infos),
            'resized': [os.path.basename(i['path']) for i in infos if (i['w'], i['h']) != (w, h)]}


# ─── ffmpeg ──
def _run(cmd: list[str], expect_seconds: float, on_progress=None):
    """執行 ffmpeg，從 -progress 回報百分比；失敗丟 VideoError。
    錯誤訊息併進同一個輸出一起讀（分開兩條管線時，沒讀的那條塞滿會讓 ffmpeg 卡住）"""
    proc = subprocess.Popen(cmd[:1] + ['-v', 'error'] + cmd[1:] + ['-progress', 'pipe:1', '-nostats'],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, encoding='utf-8', errors='replace', creationflags=_NO_WINDOW | 0x00004000)
    errors = []
    for line in proc.stdout:
        line = line.strip()
        if line.startswith('out_time_us='):
            if on_progress and expect_seconds > 0:
                try:
                    sec = int(line.split('=', 1)[1]) / 1e6
                    on_progress(max(0, min(99, int(sec / expect_seconds * 100))))
                except ValueError:
                    pass
        elif line and '=' not in line:
            errors.append(line)
    proc.wait()
    if proc.returncode != 0:
        raise VideoError(f'ffmpeg 失敗：{(errors[-1] if errors else proc.returncode)}'[:200])
    if on_progress:
        on_progress(100)


def _fit_filters(n: int, size: tuple[int, int], speed: float | None = None) -> str:
    """每段等比例縮放到 size 內補邊、統一影格率後串接；speed（< 1）時整段加速"""
    w, h = size
    parts = [f'[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,'
             f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={OUT_FPS}[v{i}]' for i in range(n)]
    chain = ''.join(f'[v{i}]' for i in range(n)) + f'concat=n={n}:v=1:a=0'
    if speed is not None:
        chain += f'[c];[c]setpts=PTS*{speed:.6f}'
    return ';'.join(parts + [chain + '[out]'])


def _encode_args(out: str) -> list[str]:
    return ['-map', '[out]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
            '-r', str(OUT_FPS), '-movflags', '+faststart', '-y', out]


def merge(folder: str, on_progress=None, now: datetime | None = None) -> dict:
    """合併資料夾裡的片段；回傳 {'path', 'segments', 'size', 'resized', 'copied', 'duration'}"""
    segs = segments(folder)
    if len(segs) < 2:
        raise VideoError('至少要有兩段影片才能合併')
    p = plan(segs)
    out = os.path.join(folder, f"{MERGED_PREFIX}{(now or datetime.now()).strftime('%Y%m%d_%H%M%S')}.mp4")
    tmp = out + '.part.mp4'
    if p['same']:
        # 解析度、編碼都相同：直接串接，不重新編碼
        fd, listfile = tempfile.mkstemp(suffix='.txt')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            for s in segs:
                f.write("file '" + s.replace('\\', '/').replace("'", "'\\''") + "'\n")
        try:
            _run(['ffmpeg', '-hide_banner', '-f', 'concat', '-safe', '0', '-i', listfile, '-c', 'copy',
                  '-movflags', '+faststart', '-y', tmp], p['duration'], on_progress)
        finally:
            os.remove(listfile)
    else:
        cmd = ['ffmpeg', '-hide_banner']
        for s in segs:
            cmd += ['-i', s]
        _run(cmd + ['-filter_complex', _fit_filters(len(segs), p['size'])] + _encode_args(tmp), p['duration'], on_progress)
    for old in os.listdir(folder):                           # 舊的合併檔（片段變多後重新合併）
        if old.startswith(MERGED_PREFIX) and old.lower().endswith('.mp4') and not old.endswith('.part.mp4'):
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
    os.replace(tmp, out)
    return {'path': out, 'segments': len(segs), 'size': p['size'], 'resized': p['resized'], 'copied': p['same'],
            'duration': p['duration']}


def export_length(folder: str, seconds: float, on_progress=None, now: datetime | None = None) -> dict:
    """全部片段接起來後壓成指定長度；回傳 {'path', 'segments', 'size', 'resized', 'duration', 'source_duration', 'speed'}"""
    segs = segments(folder)
    if not segs:
        raise VideoError('這個作品還沒有縮時影片')
    seconds = float(seconds)
    if seconds < 5:
        raise VideoError('影片長度至少 5 秒')
    p = plan(segs)
    total = p['duration']
    speed = min(1.0, seconds / total) if total > 0 else 1.0       # 比指定長度短：不放慢
    length = int(round(total * speed))                            # 檔名寫實際長度（片段比指定長度短時不是指定的秒數）
    out = os.path.join(folder, f"{EXPORT_PREFIX}{length}秒_{(now or datetime.now()).strftime('%Y%m%d_%H%M%S')}.mp4")
    tmp = out + '.part.mp4'
    cmd = ['ffmpeg', '-hide_banner']
    for s in segs:
        cmd += ['-i', s]
    _run(cmd + ['-filter_complex', _fit_filters(len(segs), p['size'], speed)] + _encode_args(tmp),
         total * speed, on_progress)
    os.replace(tmp, out)
    return {'path': out, 'segments': len(segs), 'size': p['size'], 'resized': p['resized'], 'speed': speed,
            'duration': total * speed, 'source_duration': total}
