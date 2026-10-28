# -*- coding: utf-8 -*-
"""新版 SAI2（2026-10）的標題路徑：「本機 _ …」、使用者資料夾的完整路徑、桌面上的檔案只有檔名——換成舊版的寫法
（同一個檔案只有一筆紀錄，只差大小寫的沿用既有紀錄）；由各種寫法找回實際檔案（顯示名稱「下載」→ Downloads）；
啟動時把新寫法留下的紀錄併入舊的那筆。以暫存資料夾與假的顯示名稱測試，不依賴這台電腦的資料夾"""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from core import companion, file_paths as F, settings2, tracker as T  # noqa: E402

root = tmpdir()
home = os.path.join(root, 'Users', 'artist')
desk = os.path.join(home, 'Desktop')
for p in (os.path.join(home, 'Downloads', 'ref'), os.path.join(home, 'Documents'), os.path.join(desk, '暫存')):
    os.makedirs(p, exist_ok=True)
for p in (os.path.join(home, 'Downloads', 'ref', 'b.png'), os.path.join(desk, '暫存', 'd.sai2'), os.path.join(desk, 'c.png'),
          os.path.join(home, 'Documents', 'e.psd')):
    open(p, 'w').close()
DISPLAY = {os.path.join(home, 'Downloads'): '下載', os.path.join(home, 'Documents'): '文件', desk: '桌面'}
NAMES = {'home': home, 'users_root': os.path.dirname(home), 'desktop_dir': desk, 'user': 'artist',
         'user_label': 'Artist', 'users': {'users', '使用者'}, 'desktop': '桌面'}
F._NAMES = dict(NAMES)          # 讓 tracker、companion 也用假的資料夾


def disp(p):
    return DISPLAY.get(p)


# ─── 標準寫法 ──
C = lambda k, **kw: F.canonical_key(k, NAMES, **kw)  # noqa: E731
check(C('本機 _ SSD磁碟區 (E:) _ CR _ a.png') == 'SSD磁碟區 (E:) _ CR _ a.png', 'This PC prefix dropped')
check(C('本機 _ Windows (C:) _ 使用者 _ artist _ 下載 _ b.png') == 'Artist _ 下載 _ b.png', 'user folder → old form')
check(C('This PC _ Windows (C:) _ Users _ ARTIST _ 下載 _ b.png') == 'Artist _ 下載 _ b.png', 'English names, any case')
check(C('本機 _ Windows (C:) _ 使用者 _ 別人 _ 下載 _ b.png') == 'Windows (C:) _ 使用者 _ 別人 _ 下載 _ b.png',
      "another user's folder keeps the path")
check(C('本機 _ Windows (C:) _ 使用者 _ artist _ 桌面 _ 暫存 _ d.sai2') == '暫存 _ d.sai2', 'desktop folder → relative')
check(C('本機 _ Windows (C:) _ 使用者 _ artist _ 桌面 _ c.png') == '桌面 _ c.png', 'desktop file → 桌面 _ file')
check(C('c.png') == '桌面 _ c.png' and C('c.png', bare_is_desktop=False) == 'c.png', 'bare name = desktop (new titles only)')
check(C('新增畫布5') == '新增畫布5', 'unsaved canvas untouched')
for k in ('SSD磁碟區 (E:) _ CR _ a.png', 'Artist _ 下載 _ b.png', '桌面 _ c.png', '暫存 _ d.sai2', 'CR反饋 _ x.png'):
    check(C(k) == k, f'old form unchanged: {k}')

# ─── 標題 → key ──
title = 'PaintTool SAI Ver.2 (64bit) Alpha.2026.10.19 - {} (*)'
check(T.extract_filename(title.format('本機 / Windows (C:) / 使用者 / artist / 下載 / ref / b.png')) == 'Artist _ 下載 _ ref _ b.png',
      'title parsed to the old form')
check(T.extract_filename(title.format('Idle.png')) == '桌面 _ Idle.png', 'desktop file title')
check(T.extract_filename('artwork.sai2 - PaintTool SAI Ver.2 (64bit)') == 'artwork.sai2', 'very old title style untouched')

# ─── key → 實際檔案 ──
R = lambda k: F.resolve_file_key(k, search_roots=[], names=NAMES, display=disp)  # noqa: E731
check(R('Artist _ 下載 _ ref _ b.png') == os.path.join(home, 'Downloads', 'ref', 'b.png'), 'localized folder name → real folder')
check(R('本機 _ Windows (C:) _ 使用者 _ artist _ 下載 _ ref _ b.png') == os.path.join(home, 'Downloads', 'ref', 'b.png'),
      'new form resolves too')
check(R('Artist _ 文件 _ e.psd') == os.path.join(home, 'Documents', 'e.psd'), 'documents')
check(R('桌面 _ c.png') == os.path.join(desk, 'c.png') and R('c.png') == os.path.join(desk, 'c.png'), 'desktop file')
check(R('暫存 _ d.sai2') == os.path.join(desk, '暫存', 'd.sai2'), 'desktop folder')
check(R('Artist _ 下載 _ gone.png') is None, 'missing file → None')

# ─── 只差大小寫的沿用既有紀錄；啟動時把新寫法的紀錄併入 ──
d = tmpdir()
dp = os.path.join(d, 'sai2_draw_time.json')
rec = lambda s: {'open_seconds': s, 'draw_seconds': s, 'sessions': 1, 'last_seen': '2026-10-20T10:00:00'}  # noqa: E731
json.dump({'files': {'Artist _ 下載 _ ref _ b.png': rec(100), '暫存 _ d.sai2': rec(50),
                     '本機 _ Windows (C:) _ 使用者 _ artist _ 下載 _ ref _ b.png': rec(10),
                     '本機 _ Windows (C:) _ 使用者 _ artist _ 桌面 _ 暫存 _ d.sai2': rec(5),
                     'c.png': rec(7), '本機 _ SSD磁碟區 (E:) _ x.png': rec(3)}, 'aliases': {}},
          open(dp, 'w', encoding='utf-8'), ensure_ascii=False)
tr = T.DrawTracker(data_path=dp, idle_timeout=10, track_unsaved=False)
check(tr._existing_key('artist _ 下載 _ ref _ b.png') == 'Artist _ 下載 _ ref _ b.png', 'case-insensitive match to the record')
check(tr._existing_key('Artist _ 下載 _ new.png') == 'Artist _ 下載 _ new.png', 'new file keeps its name')
s = settings2.Settings2(d)
s.set('data_path', dp)


class NoScan(T.DrawTracker):
    def start(self):          # 不偵測真正的 SAI2（測試時畫面上開著的檔案不能混進來）
        pass


svc = companion.CompanionService(s, legacy_check=lambda: False, tracker_factory=NoScan)
svc.start()
svc.stop()
files = json.load(open(dp, encoding='utf-8'))['files']
check(files['Artist _ 下載 _ ref _ b.png']['draw_seconds'] == 110 and files['暫存 _ d.sai2']['draw_seconds'] == 55,
      'new-form records merged into the old ones')
check(files['桌面 _ c.png']['draw_seconds'] == 7 and files['SSD磁碟區 (E:) _ x.png']['draw_seconds'] == 3, 'renamed to the old form')
check(not any(k.startswith('本機') for k in files) and 'c.png' not in files and len(files) == 4, f'one record per file ({sorted(files)})')
check(sum(v['draw_seconds'] for v in files.values()) == 175, 'no drawing time lost')
done()
