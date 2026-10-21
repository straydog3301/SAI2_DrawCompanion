# -*- coding: utf-8 -*-
"""
study_refs.py - 臨摹研究的參考圖來源（不含 UI，於背景執行緒呼叫）

依課程 refs 設定的順序嘗試：
  met   大都會博物館 Open Access：v1.1/search（舊版 v1/search 已於 2026-10-01 停用）→ v1/objects/{id}
  artic 芝加哥藝術博物館：artworks/search（篩公有領域）→ IIIF 圖片
  photo Unsplash / Pexels（沿用速寫的 API 金鑰；沒有金鑰時略過）
都失敗時退回本機圖庫。兩個美術館的搜尋都是寬鬆比對，結果一律以畫家名稱過濾。
"""

from __future__ import annotations

import io
import os
import json
import random
import unicodedata
import urllib.parse
import urllib.request
import urllib.error

from PIL import Image, ImageOps

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
AIC_UA = 'SAI2-DrawCompanion (study reference)'   # 芝加哥藝術博物館要求的識別標頭
MAX_SIDE = 2048
IMG_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')

MET_SEARCH = 'https://collectionapi.metmuseum.org/public/collection/v1.1/search'
MET_OBJECT = 'https://collectionapi.metmuseum.org/public/collection/v1/objects/{}'
AIC_SEARCH = 'https://api.artic.edu/api/v1/artworks/search'
AIC_IMAGE = 'https://www.artic.edu/iiif/2/{}/full/843,/0/default.jpg'


class RefError(Exception):
    """找不到可用的參考圖"""


def _norm(s: str) -> str:
    """小寫並去除重音符號（Sorolla y Bastida、Joaquín → joaquin）"""
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(ch for ch in s if not unicodedata.combining(ch)).lower()


def _get(url: str, headers: dict | None = None, timeout: int = 15) -> bytes:
    hdrs = {'User-Agent': UA}
    hdrs.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=timeout) as r:
        return r.read()


def _get_json(url: str, headers: dict | None = None) -> dict | list:
    return json.loads(_get(url, headers).decode('utf-8'))


def _load_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    img = ImageOps.exif_transpose(img).convert('RGB')
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return img


# ─── 各來源 ───────────────────────────────────────────────────────────────
# 作品類型過濾：課程需要「油畫」才能練色彩，需要「素描」才能練線條
_MET_KIND_WORDS = {
    'painting': ('painting', 'oil', 'tempera'),
    'drawing': ('drawing', 'chalk', 'graphite', 'charcoal', 'pen and', 'crayon'),
    'print': ('print', 'etching', 'woodcut', 'engraving', 'lithograph'),
}
_AIC_KIND_TYPES = {'painting': 'Painting', 'drawing': 'Drawing and Watercolor', 'print': 'Print'}


def _met_kind_ok(o: dict, kind: str | None) -> bool:
    if not kind:
        return True
    text = _norm(' '.join(str(o.get(k, '')) for k in ('classification', 'objectName', 'medium')))
    return any(w in text for w in _MET_KIND_WORDS.get(kind, ()))


def _from_met(query: str, artist: str, exclude: set, rng: random.Random,
              kind: str | None = None) -> tuple[Image.Image, dict] | None:
    limit = 60
    # artistOrCulture=true 只比對作者欄位；搜尋端的 isPublicDomain 篩選不可靠，逐件再檢查
    params = {'hasImages': 'true', 'isPublicDomain': 'true', 'artistOrCulture': 'true',
              'q': query, 'limit': limit, 'offset': 0}
    if kind == 'painting':
        params['medium'] = 'Paintings'
    first = _get_json(MET_SEARCH + '?' + urllib.parse.urlencode(params))
    ids = list(first.get('objectIDs') or [])
    total = int(first.get('total') or 0)
    if total > limit:
        # 再隨機取一頁，讓重複練習同一課時拿到不同作品
        params['offset'] = rng.randrange(limit, min(total, 600), limit) if total > limit * 2 else limit
        ids += list(_get_json(MET_SEARCH + '?' + urllib.parse.urlencode(params)).get('objectIDs') or [])
    rng.shuffle(ids)
    tries = 0
    for oid in ids:
        ref_id = f'met:{oid}'
        if ref_id in exclude:
            continue
        tries += 1
        if tries > 20:
            break
        try:
            o = _get_json(MET_OBJECT.format(oid))
        except Exception:
            continue
        url = o.get('primaryImageSmall') or o.get('primaryImage')
        if (not o.get('isPublicDomain') or not url or not _met_kind_ok(o, kind)
                or _norm(artist) not in _norm(o.get('artistDisplayName', ''))):
            continue
        try:
            img = _load_image(_get(url, timeout=25))
        except Exception:
            continue
        return img, {
            'id': ref_id, 'title': o.get('title', ''), 'artist': o.get('artistDisplayName', ''),
            'date': o.get('objectDate', ''), 'source': '大都會博物館 The Met',
            'url': o.get('objectURL', ''), 'license': '公有領域（Open Access / CC0）',
        }
    return None


def _from_artic(query: str, artist: str, exclude: set, rng: random.Random,
                kind: str | None = None) -> tuple[Image.Image, dict] | None:
    params = {'q': query, 'query[term][is_public_domain]': 'true', 'limit': 60,
              'fields': 'id,title,artist_title,artist_display,date_display,image_id,'
                        'is_public_domain,artwork_type_title'}
    data = _get_json(AIC_SEARCH + '?' + urllib.parse.urlencode(params), {'AIC-User-Agent': AIC_UA})
    # 以 artist_title（主要作者）比對：artist_display 會包含「after 某某」的仿作版畫
    want_type = _AIC_KIND_TYPES.get(kind or '')
    items = [d for d in data.get('data') or []
             if d.get('image_id') and d.get('is_public_domain')
             and _norm(artist) in _norm(d.get('artist_title') or '')
             and (not want_type or d.get('artwork_type_title') == want_type)
             and f"artic:{d.get('id')}" not in exclude]
    rng.shuffle(items)
    for d in items[:5]:
        try:
            img = _load_image(_get(AIC_IMAGE.format(d['image_id']), {'AIC-User-Agent': AIC_UA}, timeout=25))
        except Exception:
            continue
        return img, {
            'id': f"artic:{d['id']}", 'title': d.get('title', ''),
            'artist': d.get('artist_title') or (d.get('artist_display') or '').split('\n')[0],
            'date': d.get('date_display', ''), 'source': '芝加哥藝術博物館 Art Institute of Chicago',
            'url': f"https://www.artic.edu/artworks/{d['id']}", 'license': '公有領域（CC0）',
        }
    return None


def _from_photo(query: str, settings: dict, exclude: set, rng: random.Random) -> tuple[Image.Image, dict] | None:
    unsplash = (settings.get('sketch_unsplash_key') or '').strip()
    pexels = (settings.get('sketch_pexels_key') or '').strip()
    if unsplash:
        data = _get_json('https://api.unsplash.com/photos/random?' + urllib.parse.urlencode(
            {'query': query, 'count': 10, 'content_filter': 'high'}),
            {'Authorization': f'Client-ID {unsplash}', 'Accept-Version': 'v1'})
        for d in (data if isinstance(data, list) else [data]):
            ref_id = f"unsplash:{d.get('id')}"
            url = (d.get('urls') or {}).get('regular')
            if not url or ref_id in exclude:
                continue
            return _load_image(_get(url, timeout=25)), {
                'id': ref_id, 'title': d.get('alt_description') or query,
                'artist': (d.get('user') or {}).get('name', ''), 'date': '',
                'source': 'Unsplash', 'url': (d.get('links') or {}).get('html', ''),
                'license': 'Unsplash License',
            }
    if pexels:
        data = _get_json('https://api.pexels.com/v1/search?' + urllib.parse.urlencode(
            {'query': query, 'per_page': 30, 'page': rng.randint(1, 3)}), {'Authorization': pexels})
        photos = [p for p in data.get('photos') or [] if f"pexels:{p.get('id')}" not in exclude]
        rng.shuffle(photos)
        for p in photos[:3]:
            url = (p.get('src') or {}).get('large')
            if not url:
                continue
            return _load_image(_get(url, timeout=25)), {
                'id': f"pexels:{p['id']}", 'title': p.get('alt') or query,
                'artist': p.get('photographer', ''), 'date': '', 'source': 'Pexels',
                'url': p.get('url', ''), 'license': 'Pexels License',
            }
    return None


def _from_local(settings: dict, exclude: set, rng: random.Random) -> tuple[Image.Image, dict] | None:
    root = settings.get('sketch_local_dir') or ''
    if not root or not os.path.isdir(root):
        return None
    files = []
    for d, _dirs, names in os.walk(root):
        files += [os.path.join(d, n) for n in names if n.lower().endswith(IMG_EXTS)]
        if len(files) > 5000:
            break
    files = [f for f in files if f'local:{f}' not in exclude] or files
    if not files:
        return None
    path = rng.choice(files)
    with open(path, 'rb') as f:
        img = _load_image(f.read())
    return img, {'id': f'local:{path}', 'title': os.path.basename(path), 'artist': '', 'date': '',
                 'source': '本機圖庫', 'url': path, 'license': ''}


def load_local_file(path: str) -> tuple[Image.Image, dict]:
    """使用者自選圖檔"""
    with open(path, 'rb') as f:
        img = _load_image(f.read())
    return img, {'id': f'local:{path}', 'title': os.path.basename(path), 'artist': '', 'date': '',
                 'source': '自選圖檔', 'url': path, 'license': ''}


def fetch_reference(lesson: dict, settings: dict, exclude: set | None = None,
                    rng: random.Random | None = None) -> tuple[Image.Image, dict]:
    """依課程設定取得一張參考圖，回傳 (影像, 出處資訊)。全部失敗時拋出 RefError（附各來源失敗原因）。"""
    rng = rng or random.Random()
    exclude = exclude or set()
    errors = []
    for ref in lesson.get('refs', []):
        kind = ref[0]
        try:
            if kind == 'met':
                got = _from_met(ref[1], ref[2], exclude, rng, ref[3] if len(ref) > 3 else None)
            elif kind == 'artic':
                got = _from_artic(ref[1], ref[2], exclude, rng, ref[3] if len(ref) > 3 else None)
            elif kind == 'photo':
                got = _from_photo(ref[1], settings, exclude, rng)
            else:
                got = None
        except Exception as e:
            errors.append(f'{kind}: {e}')
            continue
        if got:
            img, meta = got
            meta['why'] = lesson.get('look_for', '')
            return img, meta
    try:
        got = _from_local(settings, exclude, rng)
    except Exception as e:
        got = None
        errors.append(f'local: {e}')
    if got:
        img, meta = got
        meta['why'] = lesson.get('look_for', '')
        return img, meta
    detail = '；'.join(errors[:3])
    raise RefError('找不到可用的參考圖（可按「📁 自選圖檔」）' + (f'：{detail}' if detail else ''))


def save_cache(img: Image.Image, cache_dir: str, name: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f'{name}.jpg')
    img.save(path, format='JPEG', quality=90)
    return path


def prune_cache(cache_dir: str, keep: set[str], max_files: int = 60):
    """只保留目前任務用到的圖與最近的 max_files 張"""
    try:
        files = sorted((os.path.join(cache_dir, n) for n in os.listdir(cache_dir)),
                       key=os.path.getmtime, reverse=True)
    except OSError:
        return
    keep_norm = {os.path.normcase(os.path.abspath(k)) for k in keep}
    for i, f in enumerate(files):
        if i >= max_files and os.path.normcase(os.path.abspath(f)) not in keep_norm:
            try:
                os.remove(f)
            except OSError:
                pass
