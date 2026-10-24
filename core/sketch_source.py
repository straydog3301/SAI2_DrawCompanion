# -*- coding: utf-8 -*-
"""
sketch_source.py - 速寫練習的圖源、歷史與倒數規則（不含 UI；自 1.x main.py 的速寫視窗移入）

- 圖源：本機資料夾（可選子資料夾分類）、Unsplash、Pexels
- 網路圖源一次 API 請求取回一批網址放進網址池，抽完才再請求（圖片本體走 CDN，不計 API 額度）
- 倒數「自然歸零」才算一張有效速寫；提早換下一張不算（避免灌數量）
- 不限時模式：停留滿 UNLIMITED_SKETCH_MIN_SECONDS 再換下一張才算一張
"""

from __future__ import annotations

import io
import json
import os
import random
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageOps

from core.daily_quests import UNLIMITED_SKETCH_MIN_SECONDS

# (機器碼, 顯示名稱, 搜尋關鍵字)
CATEGORIES = [
    ('portrait', '人像 / 臉部', 'portrait'),
    ('pose', '姿勢 / 全身', 'model pose'),
    ('hands', '手部', 'hands'),
    ('feet', '足部', 'feet'),
    ('landscape', '風景', 'landscape'),
    ('animal', '動物', 'animals'),
    ('still', '靜物', 'still life'),
    ('architecture', '建築 / 場景', 'architecture'),
    ('custom', '自訂關鍵字', ''),
]
INTERVALS = [('30 秒', 30), ('60 秒', 60), ('90 秒', 90), ('2 分', 120), ('5 分', 300), ('10 分', 600), ('不限時', 0)]
SOURCES = [('local', '本機資料夾'), ('unsplash', 'Unsplash'), ('pexels', 'Pexels')]
IMG_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')
HISTORY_MAX = 15
HISTORY_MAX_SIDE = 1600
RETRY_SEC = 20
RATE_LIMIT_RETRY_SEC = 300
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/120.0.0.0 Safari/537.36')          # Pexels 前端會對 python-urllib 預設 UA 回 403


class SketchError(RuntimeError):
    def __init__(self, msg: str, retry_after: int = 0, need_setup: str = ''):
        super().__init__(msg)
        self.retry_after = retry_after
        self.need_setup = need_setup             # 'local_dir' / 'unsplash_key' / 'pexels_key'


def query_for(category: str, custom: str = '') -> str:
    if category == 'custom':
        return custom.strip() or 'portrait'
    return next((q for k, _l, q in CATEGORIES if k == category), 'portrait')


def category_label(category: str) -> str:
    return next((l for k, l, _q in CATEGORIES if k == category), category)


def local_subdirs(root: str) -> list[str]:
    if not root or not os.path.isdir(root):
        return []
    try:
        return sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
    except OSError:
        return []


def resolve_quest_topic(topic: str, opts: dict) -> dict:
    """每日任務的速寫題目 → 實際圖源設定。
    網路題目沒有任何 API 金鑰時，改用本機圖庫中名稱相符的子資料夾（找不到就用整個圖庫）。
    回傳 {'source', 'local_category', 'category', 'custom_query', 'note'}"""
    if topic.startswith('local:'):
        return {'source': 'local', 'local_category': topic[6:], 'category': 'pose', 'custom_query': '', 'note': ''}
    if topic.startswith('kw:'):
        cat, query = 'custom', topic[3:]
    else:
        cat, query = topic, ''
    cur = opts.get('source', 'local')
    has = {m: bool((opts.get(f'{m}_key') or '').strip()) for m in ('unsplash', 'pexels')}
    src = cur if cur != 'local' and has.get(cur) else next((m for m in ('unsplash', 'pexels') if has[m]), None)
    if src:
        return {'source': src, 'local_category': '', 'category': cat, 'custom_query': query, 'note': ''}
    label = category_label(cat) if cat != 'custom' else query
    names = {n.strip().lower() for n in label.split('/')} | {cat.lower(), query.lower()}
    sub = next((s for s in local_subdirs(opts.get('local_dir', '')) if s.lower() in names), '')
    return {'source': 'local', 'local_category': sub, 'category': cat, 'custom_query': query,
            'note': '' if sub else '沒有圖庫 API 金鑰，改用本機圖庫的全部圖片'}


def topic_key(opts: dict) -> str:
    """目前設定對應的題目 key（與每日任務範本的 topic 格式一致）"""
    if opts.get('source', 'local') == 'local':
        return 'local:' + (opts.get('local_category') or '')
    cat = opts.get('category', 'pose')
    return 'kw:' + (opts.get('custom_query') or '').strip() if cat == 'custom' else cat


def _get_json(url: str, headers: dict, opener=urllib.request.urlopen):
    hdrs = dict(headers)
    hdrs.setdefault('User-Agent', UA)
    try:
        with opener(urllib.request.Request(url, headers=hdrs), timeout=15) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise SketchError(f'HTTP {e.code}：請確認 API 金鑰正確（Unsplash 要用 Access Key）', 0, 'key')
        if e.code == 429:
            raise SketchError('已達圖庫每小時的請求上限，稍後會自動重試', RATE_LIMIT_RETRY_SEC)
        raise SketchError(f'HTTP {e.code} {e.reason}', RETRY_SEC if e.code >= 500 else 0)


class SketchSource:
    """依目前的圖源設定取得下一張圖（在背景執行緒呼叫 next_image）"""

    def __init__(self, rng: random.Random | None = None, opener=None):
        self.rng = rng or random.Random()
        self._opener = opener or urllib.request.urlopen
        self._queue: list[str] = []
        self._queue_root = None
        self._pool: dict[tuple, list[str]] = {}
        self._totals: dict[tuple, int] = {}
        self._seen: set[str] = set()

    def next_image(self, opts: dict) -> tuple[Image.Image, str]:
        """回傳 (圖片, 說明)；失敗丟 SketchError"""
        src = opts.get('source', 'local')
        if src == 'local':
            return self._local(opts)
        key = (opts.get(f'{src}_key') or '').strip()
        if not key:
            raise SketchError(f'尚未設定 {src.capitalize()} API 金鑰', 0, f'{src}_key')
        query = query_for(opts.get('category', 'pose'), opts.get('custom_query', ''))
        return self._web(src, key, query), f'{src.capitalize()} · {query}'

    def _local(self, opts: dict):
        root = opts.get('local_dir') or ''
        if not root or not os.path.isdir(root):
            raise SketchError('尚未設定本機參考圖資料夾', 0, 'local_dir')
        sub = opts.get('local_category') or ''
        scan = os.path.join(root, sub) if sub and os.path.isdir(os.path.join(root, sub)) else root
        if not self._queue or self._queue_root != scan:
            files = []
            for d, _dirs, names in os.walk(scan):
                files += [os.path.join(d, n) for n in names if n.lower().endswith(IMG_EXTS)]
            self.rng.shuffle(files)
            self._queue, self._queue_root = files, scan
        if not self._queue:
            raise SketchError('這個資料夾裡找不到圖片', 0, 'local_dir')
        path = self._queue.pop()
        img = Image.open(path)
        img.load()
        img = ImageOps.exif_transpose(img)
        tag = f'[{sub}] ' if sub else ''
        return img, f'{tag}{os.path.basename(path)}（剩 {len(self._queue)} 張）'

    def _web(self, src: str, key: str, query: str) -> Image.Image:
        pool_key = (src, query)
        pool = self._pool.setdefault(pool_key, [])
        if not pool:
            if src == 'unsplash':
                params = urllib.parse.urlencode({'query': query, 'orientation': 'portrait',
                                                 'content_filter': 'high', 'count': 30})
                data = _get_json(f'https://api.unsplash.com/photos/random?{params}',
                                 {'Authorization': f'Client-ID {key}', 'Accept-Version': 'v1'}, self._opener)
                data = data if isinstance(data, list) else [data]
                urls = [d['urls']['regular'] for d in data if (d.get('urls') or {}).get('regular')]
            else:
                per_page = 80
                total = self._totals.get(pool_key)
                page = self.rng.randint(1, min(50, -(-total // per_page))) if total and total > per_page else 1
                data = _get_json('https://api.pexels.com/v1/search?' + urllib.parse.urlencode(
                    {'query': query, 'per_page': per_page, 'page': page}), {'Authorization': key}, self._opener)
                self._totals[pool_key] = int(data.get('total_results', 0) or 0)
                urls = [p['src']['large'] for p in (data.get('photos') or []) if (p.get('src') or {}).get('large')]
            if not urls:
                raise SketchError('這個關鍵字沒有搜尋結果，換個關鍵字試試（建議用英文）')
            fresh = [u for u in urls if u not in self._seen]
            pool.extend(fresh or urls)
            self.rng.shuffle(pool)
        url = pool.pop()
        if len(self._seen) > 3000:
            self._seen.clear()
        self._seen.add(url)
        try:
            with self._opener(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=20) as r:
                raw = r.read()
        except (urllib.error.URLError, OSError) as e:
            raise SketchError(f'下載圖片失敗：{e}', RETRY_SEC)
        img = Image.open(io.BytesIO(raw))
        img.load()
        return ImageOps.exif_transpose(img)


class SketchSession:
    """一輪速寫：歷史（上一張 / 下一張）、倒數、何時算完成一張。時間由呼叫端以 tick(秒) 推進"""

    def __init__(self, interval: int):
        self.interval = int(interval)
        self.history: list[Image.Image] = []
        self.idx = -1
        self.remaining = 0.0
        self.shown = 0.0              # 目前這張已顯示秒數（不含暫停）
        self.paused = False
        self.completed = 0
        self.waiting = False          # 這張已倒數完、等下一張載入；期間不再計張

    @property
    def current(self) -> Image.Image | None:
        return self.history[self.idx] if 0 <= self.idx < len(self.history) else None

    def push(self, img: Image.Image) -> Image.Image:
        """加入新圖（先縮小再保存，避免相機原圖佔用大量記憶體），回傳實際保存的圖"""
        img = img.copy()
        img.thumbnail((HISTORY_MAX_SIDE, HISTORY_MAX_SIDE), Image.LANCZOS)
        if self.idx < len(self.history) - 1:
            self.history = self.history[:self.idx + 1]
        self.history.append(img)
        if len(self.history) > HISTORY_MAX:
            self.history = self.history[-HISTORY_MAX:]
        self.idx = len(self.history) - 1
        self.restart()
        return img

    def restart(self):
        self.remaining = float(self.interval)
        self.shown = 0.0
        self.waiting = False

    def can_forward(self) -> bool:
        return self.idx < len(self.history) - 1

    def forward(self) -> float:
        """手動換下一張（已載入的下一張或準備抓新圖）。回傳這次要計入的秒數（0 = 不算一張）"""
        counted = 0.0
        if self.interval == 0 and self.shown >= UNLIMITED_SKETCH_MIN_SECONDS:
            counted = self.shown
        if self.can_forward():
            self.idx += 1
            self.restart()
        return counted

    def back(self) -> bool:
        if self.idx > 0:
            self.idx -= 1
            self.restart()
            return True
        return False

    def tick(self, dt: float) -> bool:
        """推進時間；倒數自然歸零時回傳 True（算完成一張，呼叫端應計入並換下一張）"""
        if self.paused or self.current is None or self.waiting:
            return False
        self.shown += dt
        if self.interval <= 0:
            return False
        self.remaining -= dt
        if self.remaining <= 0:
            self.remaining = 0
            self.completed += 1
            self.waiting = True
            return True
        return False
