# -*- coding: utf-8 -*-
"""
筆刷工坊 2.x 階段 0 實測工具（docs/BRUSH_STUDIO_2x.md §5）

用法（在專案根目錄）：
  python spikes/v2_brush_probe/probe.py backup          完整備份 SAI2 settings（zip）
  python spikes/v2_brush_probe/probe.py snap 名稱       記錄目前 settings 的狀態（檔案大小、時間、雜湊、文字內容）
  python spikes/v2_brush_probe/probe.py diff 舊 新       比較兩次記錄：新增、刪除、修改的檔案與文字差異
  python spikes/v2_brush_probe/probe.py write 代號       寫入測試素材（散布）與測試工具（放在新的「DC_TEST」工具分頁）
  python spikes/v2_brush_probe/probe.py status          SAI2 是否執行中、測試項目還在不在
  python spikes/v2_brush_probe/probe.py clean           移除所有 DC_TEST 測試項目（SAI2 必須關閉）
  python spikes/v2_brush_probe/probe.py restore zip檔   從完整備份還原（SAI2 必須關閉；還原前會先再備份一次）

測試項目一律以 DC_TEST 開頭，不會碰到使用者自己的素材與工具。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
from core import brush_assets as BA  # noqa: E402
from core.paths import APP_DIR  # noqa: E402

OUT = os.path.join(HERE, 'out')
BACKUPS = os.path.join(APP_DIR, 'sai2_full_backups')
PREFIX = 'DC_TEST'
TEXT_EXT = ('.ini', '.saiagrp', '.saiaset', '.saitdat', '.saitgrp', '.saitset', '.saitlnk', '.txt')
SM = BA.SAI2SettingsManager


def settings_dir() -> str:
    d = SM.get_settings_dir()
    if not d:
        sys.exit('找不到 SAI2 settings 資料夾')
    return d


def running() -> bool:
    return SM.is_sai2_running()


def cmd_backup():
    src = settings_dir()
    os.makedirs(BACKUPS, exist_ok=True)
    path = os.path.join(BACKUPS, f'settings_{time.strftime("%Y%m%d_%H%M%S")}.zip')
    n, locked = 0, []
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for d, _dirs, files in os.walk(src):
            for f in files:
                full = os.path.join(d, f)
                try:
                    z.write(full, os.path.relpath(full, src))
                    n += 1
                except PermissionError:
                    locked.append(os.path.relpath(full, src))
    if locked:
        bad = path.replace('.zip', '_INCOMPLETE.zip')
        os.replace(path, bad)
        print(f'不完整：{len(locked)} 個檔案被 SAI2 鎖住（{", ".join(locked)}）。請關閉 SAI2 後再備份一次。→ {bad}')
        return bad
    print(f'已完整備份 {n} 個檔案 → {path}（{os.path.getsize(path) // 1024} KB）；SAI2 執行中：{running()}')
    return path


def _read_text(p):
    raw = open(p, 'rb').read()
    for enc in ('utf-8', 'utf-16'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def cmd_snap(name):
    src = settings_dir()
    snap = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'sai2_running': running(), 'files': {}}
    for d, _dirs, files in os.walk(src):
        for f in files:
            full = os.path.join(d, f)
            rel = os.path.relpath(full, src).replace('\\', '/')
            st = os.stat(full)
            try:
                data = open(full, 'rb').read()
            except PermissionError:
                snap['files'][rel] = {'size': st.st_size, 'mtime': st.st_mtime, 'sha1': f'locked:{st.st_size}:{st.st_mtime}'}
                continue
            item = {'size': st.st_size, 'mtime': st.st_mtime, 'sha1': hashlib.sha1(data).hexdigest()}
            if rel.lower().endswith(TEXT_EXT) and st.st_size < 200_000:
                item['text'] = _read_text(full)
            snap['files'][rel] = item
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f'{name}.json'), 'w', encoding='utf-8') as fh:
        json.dump(snap, fh, ensure_ascii=False)
    print(f'記錄「{name}」：{len(snap["files"])} 個檔案，SAI2 執行中：{snap["sai2_running"]}')


def cmd_diff(a, b):
    A = json.load(open(os.path.join(OUT, f'{a}.json'), encoding='utf-8'))
    B = json.load(open(os.path.join(OUT, f'{b}.json'), encoding='utf-8'))
    fa, fb = A['files'], B['files']
    added = sorted(set(fb) - set(fa))
    removed = sorted(set(fa) - set(fb))
    changed = sorted(k for k in set(fa) & set(fb) if fa[k]['sha1'] != fb[k]['sha1'])
    print(f'{a}（{A["time"]}，SAI2 {"開" if A["sai2_running"] else "關"}）→ {b}（{B["time"]}，SAI2 {"開" if B["sai2_running"] else "關"}）')
    print(f'新增 {len(added)}、刪除 {len(removed)}、修改 {len(changed)}')
    for k in added:
        print('  + ', k, fb[k]['size'])
    for k in removed:
        print('  - ', k)
    for k in changed:
        print('  * ', k, fa[k]['size'], '→', fb[k]['size'])
        ta, tb = fa[k].get('text'), fb[k].get('text')
        if ta is not None and tb is not None:
            for line in list(difflib.unified_diff(ta.splitlines(), tb.splitlines(), lineterm='', n=1))[2:40]:
                print('       ', line)


def _new_group_id(custool):
    ids = set(SM._read_saitset_group_ids(custool))
    for f in os.listdir(custool):
        if f.startswith('_') and f.endswith('.saitgrp') and f[1:-8].isdigit():
            ids.add(int(f[1:-8]))
    return max(ids, default=0) + 1


def _test_group_id(custool):
    for f in os.listdir(custool):
        if f.startswith('_') and f.endswith('.saitgrp'):
            if f'name=U:{PREFIX}' in (_read_text(os.path.join(custool, f)) or ''):
                return int(f[1:-8])
    return None


def cmd_write(tag):
    from PIL import Image, ImageDraw
    src = settings_dir()
    name = f'{PREFIX}_{tag}'
    img = Image.new('L', (128, 128), 0)              # SAI2 的素材：白＝筆觸、黑＝透明（實測 A 確認）
    d = ImageDraw.Draw(img)
    d.polygon([(64, 6), (78, 50), (122, 50), (86, 78), (100, 122), (64, 96), (28, 122), (42, 78), (6, 50), (50, 50)], fill=255)
    custool = os.path.join(src, 'custool', 'nrm')
    gid = _test_group_id(custool) or _new_group_id(custool)
    with BA.sai2_write_session():
        SM.write_material(name, img, 'scatter', {'spacing': 80, 'scattering': 30, 'size_jitter': 20}, src)
        tid = SM.write_tool(name, 'scatter', name, gid, {'size': 40, 'spacing': 80}, src, target_group_name=PREFIX)
    print(f'已寫入：散布素材「{name}」、工具「{name}」（id {tid}，分頁「{PREFIX}」= _{gid}.saitgrp）；SAI2 執行中：{running()}')


def _test_items(src):
    out = []
    scat = os.path.join(src, 'scatter')
    for f in sorted(os.listdir(scat)):
        if f.startswith(PREFIX):
            out.append(('素材檔', f'scatter/{f}'))
    for f in sorted(os.listdir(scat)):
        if f.endswith(('.saiaset', '.saiagrp')) and PREFIX in (_read_text(os.path.join(scat, f)) or ''):
            out.append(('素材清單', f'scatter/{f}'))
    custool = os.path.join(src, 'custool', 'nrm')
    for f in sorted(os.listdir(custool)):
        p = os.path.join(custool, f)
        if f.endswith(('.saitdat', '.saitgrp')) and f'name=U:{PREFIX}' in (_read_text(p) or ''):
            out.append(('工具' if f.endswith('.saitdat') else '工具分頁', f'custool/nrm/{f}'))
    gid = _test_group_id(custool)
    if gid is not None and gid in SM._read_saitset_group_ids(custool):
        out.append(('分頁清單', f'custool/nrm/_0.saitset 含 {gid}'))
    return out


def cmd_status():
    src = settings_dir()
    print(f'settings：{src}\nSAI2 執行中：{running()}')
    items = _test_items(src)
    print('測試項目：' + ('沒有' if not items else ''))
    for kind, path in items:
        print(f'  {kind}：{path}')


def _rewrite(path, keep):
    text = BA._read_sai2_text(path).replace('\r\n', '\n')
    lines = [ln for ln in text.split('\n') if keep(ln)]
    BA._write_sai2_file(path, '\n'.join(lines).encode('utf-8'))


def cmd_clean():
    if running():
        sys.exit('請先關閉 SAI2 再清除（SAI2 關閉時會把記憶體裡的設定寫回）')
    src = settings_dir()
    scat = os.path.join(src, 'scatter')
    custool = os.path.join(src, 'custool', 'nrm')
    gid = _test_group_id(custool)
    tool_ids = []
    with BA.sai2_write_session():
        for f in os.listdir(scat):
            p = os.path.join(scat, f)
            if f.startswith(PREFIX):
                BA._backup_sai2_file(p)
                os.remove(p)
            elif f.endswith(('.saiaset', '.saiagrp')) and PREFIX in (_read_text(p) or ''):
                _rewrite(p, lambda ln: PREFIX not in ln)
        for f in os.listdir(custool):
            p = os.path.join(custool, f)
            if f.endswith('.saitdat') and f'name=U:{PREFIX}' in (_read_text(p) or ''):
                tool_ids.append(f[:-8])
                BA._backup_sai2_file(p)
                os.remove(p)
        if gid is not None:
            gp = os.path.join(custool, f'_{gid}.saitgrp')
            if os.path.isfile(gp):
                BA._backup_sai2_file(gp)
                os.remove(gp)
            sp = os.path.join(custool, '_0.saitset')
            if os.path.isfile(sp):
                _rewrite(sp, lambda ln: not (ln.strip().split('=')[-1] == str(gid) and ln.strip().split('=')[0].isdigit()))
    print(f'已移除測試項目（工具 {tool_ids}，分頁 {gid}）；改寫前的檔案備份在 {BA.BACKUP_ROOT}')
    cmd_status()


def cmd_restore(zip_path):
    if running():
        sys.exit('請先關閉 SAI2 再還原')
    src = settings_dir()
    print('還原前先備份目前狀態：')
    cmd_backup()
    tmp = src + '.restoring'
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = os.path.normpath(os.path.join(tmp, info.filename))
            if not target.startswith(os.path.normpath(tmp) + os.sep):
                sys.exit('備份檔內有不安全的路徑')
        z.extractall(tmp)
    old = src + '.before_restore'
    shutil.rmtree(old, ignore_errors=True)
    os.replace(src, old)
    os.replace(tmp, src)
    shutil.rmtree(old, ignore_errors=True)
    print(f'已從 {zip_path} 還原')


if __name__ == '__main__':
    args = sys.argv[1:]
    cmds = {'backup': cmd_backup, 'snap': cmd_snap, 'diff': cmd_diff, 'write': cmd_write,
            'status': cmd_status, 'clean': cmd_clean, 'restore': cmd_restore}
    if not args or args[0] not in cmds:
        sys.exit(__doc__)
    cmds[args[0]](*args[1:])
