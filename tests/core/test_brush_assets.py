# -*- coding: utf-8 -*-
"""筆刷工坊核心（core/brush_assets.py）：影像轉換、群組 ID 解析、待寫入佇列重試與封存、寫入作業備份"""
import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir  # noqa: E402

block_tk()
from PIL import Image, ImageDraw  # noqa: E402
import core.brush_assets as ba  # noqa: E402

M = ba.SAI2SettingsManager

# ── 影像轉換 ──
src = Image.new('RGBA', (300, 200), (0, 0, 0, 0))
ImageDraw.Draw(src).ellipse([50, 40, 250, 160], fill=(20, 20, 20, 255))
for mode in ('alpha', 'white_bg', 'black_bg', 'silhouette'):
    out = ba.BrushImageProcessor.process(src, mode=mode, target_size=256)
    check(out.mode == 'L' and out.size == (256, 256), f'process {mode}')
stamp = ba.BrushImageProcessor.process(src, mode='alpha', target_size=256)
check(stamp.getextrema()[1] == 255 and stamp.getpixel((0, 0)) == 0, 'alpha: shape bright, border transparent')
check(ba.BrushImageProcessor.process(Image.new('RGBA', (40, 40), (0, 0, 0, 0))).size == (512, 512), 'empty alpha')
for sm in ('crossfade', 'mirror', 'none'):
    tex = ba.BrushImageProcessor.process_texture(src, seamless_mode=sm, target_size=128)
    check(tex.mode == 'L' and tex.size == (128, 128), f'texture {sm}')
tex = ba.BrushImageProcessor.process_texture(Image.new('RGB', (200, 200), 'gray'), seamless_mode='crossfade', target_size=128)
check(tex.getextrema()[0] == tex.getextrema()[1], 'crossfade keeps uniform texture uniform')

# ── 模擬 SAI2 settings：群組依名稱解析 ──
root = tmpdir()
ba.BACKUP_ROOT = os.path.join(root, 'backup')
sd = os.path.join(root, 'settings')
scat = os.path.join(sd, 'scatter'); os.makedirs(scat)
open(os.path.join(scat, '_0.saiaset'), 'w', newline='\n', encoding='utf-8').write('.\n0=3\n.\nscat,old\n.\n--EOF--\n')
open(os.path.join(scat, '_3.saiagrp'), 'w', newline='\n', encoding='utf-8').write('name=U:既有\n.\nscat,a\n.\n--EOF--\n')
cust = os.path.join(sd, 'custool', 'nrm'); os.makedirs(cust)
open(os.path.join(cust, '_0.saitset'), 'w', newline='\n', encoding='utf-8').write('.\n0=1\n1=2\n.\n--EOF--\n')
for gid, gname in ((1, '基本'), (2, '效果')):
    open(os.path.join(cust, f'_{gid}.saitgrp'), 'w', newline='\n', encoding='utf-8').write(
        f'name=U:{gname}\n.\n0=10\n.\n--EOF--\n')
img = Image.new('L', (64, 64), 255)
gids = [M.write_material(f'b{i}', img, 'scatter', {'asset_group_id': gid, 'asset_group_name': name}, sd)[2]
        for i, (gid, name) in enumerate([(0, 'X'), (0, 'Y'), (0, 'X'), (3, '既有'), (0, '')])]
check(gids == [4, 5, 4, 3, 0], f'group ids by name {gids}')
check(M._read_group_name(os.path.join(scat, '_5.saiagrp')) == 'Y', 'new group named')
t1 = M.write_tool('t1', 'scatter', 'b0', 0, {'asset_group_id': 4}, sd, target_group_name='我的分頁')
M.write_tool('t2', 'scatter', 'b1', 2, {'asset_group_id': 5}, sd, target_group_name='效果')
groups = [(g['id'], g['name']) for g in M.get_tool_groups(sd)]
check(groups == [(1, '基本'), (2, '效果'), (3, '我的分頁')], f'tool groups {groups}')
check('fomgid=I:4\n' in open(os.path.join(cust, f'{t1}.saitdat'), encoding='utf-8').read(), 'fomgid follows asset group')
check(ba.validate_asset_name('a/b') and ba.validate_asset_name('CON') and ba.validate_asset_name('ok') is None, 'names')

# ── 佇列：成功、無法重試立即封存、可重試到上限才封存 ──
Q = ba.PendingBrushQueue
ba.PENDING_QUEUE_FILE = os.path.join(root, 'q.json')
ba.PENDING_ASSET_DIR = os.path.join(root, 'pa')
ba.FAILED_QUEUE_FILE = os.path.join(root, 'failed.json')
M.is_sai2_running = staticmethod(lambda: False)
M.get_settings_dir = staticmethod(lambda: sd)
Q.add_deploy_task('q1', 'scatter', img, {'asset_group_id': 0, 'asset_group_name': 'Z'}, 0, True, 'scatter', 'Q分頁')
Q.add_deploy_task('missing', 'scatter', img, {}, 1, False, 'scatter')
os.remove(Q.load_tasks()[1]['asset']['image'])
ok, fails = Q.process_all_if_closed()
check(ok == ['q1'] and len(fails) == 1 and fails[0]['gave_up'], f'queue {ok} {fails}')
Q.add_deploy_task('retry', 'scatter', img, {}, 1, False, 'scatter')
M.get_settings_dir = staticmethod(lambda: None)
for i in range(Q.MAX_ATTEMPTS):
    ok, fails = Q.process_all_if_closed()
    check(fails[0]['attempts'] == i + 1 and fails[0]['gave_up'] == (i + 1 == Q.MAX_ATTEMPTS), f'attempt {i}')
check(not Q.has_tasks(), 'queue empty after give up')
archived = [t['tool_name'] for t in json.load(open(ba.FAILED_QUEUE_FILE, encoding='utf-8'))]
check(archived == ['missing', 'retry'], f'archived {archived}')

# ── 寫入作業備份：每次作業各一份、巢狀共用、依時間排序清理 ──
ba.BACKUP_ROOT = os.path.join(root, 'bk2')
f = os.path.join(root, 'settings', 'x.txt')
open(f, 'wb').write(b'v0')
for i in range(4):
    with ba.sai2_write_session():
        ba._write_sai2_file(f, f'v{i + 1}'.encode())
        ba._write_sai2_file(f, f'v{i + 1}b'.encode())
names = sorted(os.listdir(ba.BACKUP_ROOT))
check([open(os.path.join(ba.BACKUP_ROOT, n, 'x.txt')).read() for n in names] == ['v0', 'v1b', 'v2b', 'v3b'],
      'one backup per session, chronological')
with ba.sai2_write_session():
    with ba.sai2_write_session():
        ba._write_sai2_file(f, b'nested')
check(len(os.listdir(ba.BACKUP_ROOT)) == 5, 'nested session shares folder')
os.makedirs(os.path.join(ba.BACKUP_ROOT, 'my_notes'))
ba._prune_backups(2)
left = sorted(os.listdir(ba.BACKUP_ROOT))
check('my_notes' in left and len(left) == 3, f'prune keeps newest + foreign {left}')
done()
