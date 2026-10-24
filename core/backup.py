# -*- coding: utf-8 -*-
"""
backup.py - 整套設定的匯出 / 匯入（不含 UI；docs/UI_2.0_PLAN.md §9）

匯出成一個 zip：settings.json（主題、寵物、快捷面板、規則、快捷鍵…）＋ pets/ 角色包＋ bubbles/ 對話泡泡圖。
不匯出只屬於這台電腦的設定（SAI2 位置、資料夾路徑、提醒紀錄）；API 金鑰預設不匯出，要分享給別人時比較安全。
匯入時合併設定、角色包以新名稱加入（不覆蓋現有的），本機專屬的設定維持原樣。
"""

from __future__ import annotations

import copy
import json
import os
import zipfile
from datetime import datetime

from core import bubble_skin
from core.version import APP_VERSION

FORMAT = 'drawcompanion2-settings'
LOCAL_ONLY = ('sai2_exe', 'data_path', 'autostart', 'prompted', 'first_run_at', 'version',
              'timelapse.output_dir', 'timelapse.enabled', 'study.canvas_dir', 'sources.local_dir',
              'ref', 'works.groups', 'exclude_folders')
SECRETS = ('sources.unsplash_key', 'sources.pexels_key')
MAX_BYTES = 120 * 1024 * 1024


def _pop(d: dict, dotted: str):
    parts = dotted.split('.')
    cur = d
    for p in parts[:-1]:
        cur = cur.get(p)
        if not isinstance(cur, dict):
            return
    cur.pop(parts[-1], None)


def _get(d: dict, dotted: str):
    cur = d
    for p in dotted.split('.'):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def shareable(data: dict, include_secrets: bool = False) -> dict:
    out = copy.deepcopy(data)
    for k in LOCAL_ONLY + (() if include_secrets else SECRETS):
        _pop(out, k)
    return out


def export_bundle(settings, path: str, include_secrets: bool = False, include_pets: bool = True) -> dict:
    """回傳 {'pets': 角色數}"""
    data = shareable(settings.data, include_secrets)
    pets = 0
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps({'format': FORMAT, 'version': 1, 'app_version': APP_VERSION,
                                                'exported_at': datetime.now().isoformat(timespec='seconds')},
                                               ensure_ascii=False))
        z.writestr('settings.json', json.dumps(data, ensure_ascii=False, indent=2))
        root = settings.pets_dir
        if include_pets and os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                folder = os.path.join(root, name)
                if not os.path.isdir(folder):
                    continue
                pets += 1
                for d, _dirs, files in os.walk(folder):
                    for fn in files:
                        full = os.path.join(d, fn)
                        z.write(full, 'pets/' + os.path.relpath(full, root).replace(os.sep, '/'))
        bubble = bubble_skin.image_path(settings.app_dir, settings.get('pet.bubble_skin'))
        if bubble:
            z.write(bubble, 'bubbles/' + os.path.basename(bubble))
    return {'pets': pets}


def _merge(dst: dict, src: dict):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)


def import_bundle(settings, path: str) -> dict:
    """合併設定並加入角色包，回傳 {'pets': [新 pack_id], 'keys': 是否含金鑰}；格式不對丟 ValueError"""
    from core import pet_pack
    import shutil
    import tempfile
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ValueError(f'不是有效的設定檔：{e}')
    with z:
        try:
            meta = json.loads(z.read('manifest.json').decode('utf-8'))
            data = json.loads(z.read('settings.json').decode('utf-8'))
        except (KeyError, ValueError):
            raise ValueError('不是 DrawCompanion 2.0 匯出的設定檔')
        if meta.get('format') != FORMAT or not isinstance(data, dict):
            raise ValueError('不是 DrawCompanion 2.0 匯出的設定檔')
        if sum(i.file_size for i in z.infolist()) > MAX_BYTES:
            raise ValueError('設定檔太大')
        tmp = tempfile.mkdtemp(prefix='dc2_import_')
        try:
            pet_dirs = set()
            bubbles = {}
            for info in z.infolist():
                if info.filename.startswith('bubbles/') and not info.is_dir() and info.filename.count('/') == 1:
                    bubbles[info.filename[8:]] = info
                if not info.filename.startswith('pets/') or info.is_dir():
                    continue
                target = os.path.normpath(os.path.join(tmp, info.filename))
                if not target.startswith(os.path.normpath(tmp) + os.sep):
                    raise ValueError('設定檔內有不安全的路徑')
                parts = info.filename.split('/')
                if len(parts) >= 3:
                    pet_dirs.add(parts[1])
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
            imported = {}
            for name in sorted(pet_dirs):
                try:
                    imported[name] = pet_pack.import_pack(os.path.join(tmp, 'pets', name), settings.pets_dir)
                except ValueError:
                    pass
            new_bubble = None
            want = os.path.basename(str(_get(data, 'pet.bubble_skin.image') or ''))
            if want in bubbles:
                target = os.path.join(tmp, 'bubble_src')
                with z.open(bubbles[want]) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                try:
                    new_bubble = bubble_skin.import_image(settings.app_dir, target)[0]
                except ValueError:
                    pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    clean = shareable(data, include_secrets=True)
    has_keys = any(_get(clean, k) for k in SECRETS)
    for k in SECRETS:                      # 匯入檔沒有金鑰時保留本機原本的
        if not _get(clean, k):
            _pop(clean, k)
    pack = _get(clean, 'pet.pack')
    if pack and pack in imported:
        clean['pet']['pack'] = imported[pack]
    elif pack and not os.path.isdir(os.path.join(settings.pets_dir, pack)):
        clean['pet']['pack'] = ''
    if isinstance(_get(clean, 'pet.bubble_skin'), dict):
        clean['pet']['bubble_skin']['image'] = new_bubble or ''
    _merge(settings.data, clean)
    settings.save()
    return {'pets': list(imported.values()), 'keys': has_keys}
