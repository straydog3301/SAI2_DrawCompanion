# -*- coding: utf-8 -*-
"""不記錄的資料夾：規則比對（資料夾名稱／某個資料夾與子資料夾）、追蹤器把排除的檔案當作沒有開檔、
批次刪除紀錄（只存一次檔）、設定匯出不帶排除清單（含本機路徑）"""
import json
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir  # noqa: E402

block_tk()
from core import backup, companion, exclusions as E, settings2, tracker as T  # noqa: E402

# ─── 規則 ──
rules = [{'kind': 'folder', 'value': '下載'}, {'kind': 'prefix', 'value': '本機磁碟 (D:) _ 素材'}]
check(E.match('Artist _ 下載 _ ref.png', rules), 'folder name anywhere in the path')
check(E.match('本機磁碟 (D:) _ 下載 _ 子 _ a.psd', rules), 'nested under a matching folder')
check(not E.match('本機磁碟 (D:) _ art _ 下載.psd', rules), 'file named like the folder is not a folder')
check(E.match('本機磁碟 (D:) _ 素材 _ a.png', rules) and E.match('本機磁碟 (D:) _ 素材 _ 貼圖 _ b.png', rules),
      'prefix: folder and its subfolders')
check(not E.match('本機磁碟 (D:) _ 素材集 _ a.png', rules), 'prefix does not match a longer folder name')
check(E.match('artist _ 下載 _ x.png', [{'kind': 'folder', 'value': '下載'}]) and
      E.match('本機磁碟 (D:) _ 素材 _ a.png', [{'kind': 'prefix', 'value': '本機磁碟 (d:) _ 素材'}]), 'case-insensitive')
check(not E.match(None, rules) and not E.match('a.psd', rules), 'no folder → never excluded')
check(E.folder_of('本機磁碟 (D:) _ art _ a.psd') == '本機磁碟 (D:) _ art' and E.folder_of('a.psd') is None, 'folder_of')
check(E.folder_label('本機磁碟 (D:) _ art') == '本機磁碟 (D:) › art', 'folder label')
r2 = E.add(rules, 'folder', ' 下載 ')
check(len(r2) == 2, 'duplicate rule ignored')
check(E.remove(r2, {'kind': 'folder', 'value': '下載'}) == [rules[1]], 'remove rule')
check(E.normalize([{'kind': 'x', 'value': 'a'}, {'kind': 'folder', 'value': ''}, 'bad']) == [], 'invalid rules dropped')
check(E.matching(['A _ 下載 _ a', 'B _ b'], rules) == ['A _ 下載 _ a'], 'matching')

# ─── 追蹤器：排除的檔案當作沒有開檔 ──
d = tmpdir()
dp = os.path.join(d, 'sai2_draw_time.json')
current = ['本機磁碟 (D:) _ 下載 _ ref.png']
T._scan_sai2 = lambda: (current[0], True, f'{current[0]} - PaintTool SAI', True)
tr = T.DrawTracker(data_path=dp, idle_timeout=10, track_unsaved=False)
tr.is_excluded = lambda name: E.match(name, rules)
tr.start()
time.sleep(1.2)
st = tr.get_state()
check(st['current_file'] is None and st['excluded_file'] == current[0], f'excluded file not tracked ({st})')
check(st['raw_current_file'] is None, 'no unsaved-canvas reminder for excluded files')
check(current[0] not in st['files'], 'no record created')
current[0] = '本機磁碟 (D:) _ art _ 立繪.psd'
tr._last_win_scan = 0
time.sleep(1.2)
st = tr.get_state()
check(st['current_file'] == current[0] and st['excluded_file'] is None, 'other folders tracked normally')
tr.stop()

# ─── 批次刪除：一次存檔 ──
rec = {'open_seconds': 10, 'draw_seconds': 5, 'sessions': 1, 'last_seen': '2026-10-20T10:00:00'}
json.dump({'files': {k: dict(rec) for k in ('a.psd', 'b.psd', 'c.psd', 'd.psd')}, 'aliases': {'old.psd': 'b.psd'}},
          open(dp, 'w', encoding='utf-8'))
tr2 = T.DrawTracker(data_path=dp, idle_timeout=10, track_unsaved=False)
saves = []
orig_save = tr2.save
tr2.save = lambda: (saves.append(1), orig_save())
tr2.delete_files(['a.psd', 'b.psd', 'zzz.psd'])
check(sorted(tr2.get_state()['files']) == ['c.psd', 'd.psd'] and len(saves) == 1, 'batch delete, saved once')
check('old.psd' not in tr2._persist['aliases'], 'aliases of deleted records removed')
check(sorted(json.load(open(dp, encoding='utf-8'))['files']) == ['c.psd', 'd.psd'], 'written to disk')

# ─── 服務：設定改了馬上生效；匯出不帶排除清單 ──
s = settings2.Settings2(tmpdir())
check(s.get('exclude_folders') == [], 'default: nothing excluded')
svc = companion.CompanionService(s, legacy_check=lambda: False)
check(not svc.is_excluded('A _ 下載 _ x.png'), 'not excluded before adding a rule')
s.set('exclude_folders', [{'kind': 'folder', 'value': '下載'}])
check(svc.is_excluded('A _ 下載 _ x.png'), 'rule applies immediately')
s.set('exclude_folders', [{'kind': 'prefix', 'value': 'Artist _ 私人'}])
check('exclude_folders' not in backup.shareable(s.data), 'exclusions (may contain local paths) are not exported')
done()
