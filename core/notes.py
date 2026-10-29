# -*- coding: utf-8 -*-
"""
notes.py - 浮動筆記（不含 UI）

每則筆記是程式資料夾 notes/ 裡的一個 Markdown 檔（也可以用其他編輯器打開）；貼上的圖片存在 notes/images/。
頁籤的順序與上次打開的筆記記在 notes/_order.json。

blocks(text)：把 Markdown 切成閱讀模式顯示的區塊
  ('heading', 層級, 文字)   標題（也是目錄）
  ('code', 語言, 內容)      ``` 或 ~~~ 包起來的區塊（顯示「複製」）——放常用參數、色碼、提示詞
  ('image', 說明, 路徑)     單獨一行的 ![說明](路徑)，可以點開放大、複製回剪貼簿
  ('text', Markdown)        其他文字（段落、清單、引用、表格；空行不會切開，到下一個標題／區塊／圖片為止）
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

EXT = '.md'
ORDER = '_order.json'
IMAGES = 'images'
NAME_MAX = 40
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_IMAGE_LINE = re.compile(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$')
_HEADING = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')

WELCOME = """# 我的筆記

按右上角「編輯」寫筆記，寫完按「完成」（或 Ctrl+S）存檔。

## 常用參數
```
筆刷大小 12 / 濃度 80%
```

在編輯模式按 Ctrl+V 可以貼上剪貼簿的圖片。
"""


class NoteStore:
    def __init__(self, app_dir: str):
        self.dir = os.path.join(app_dir, 'notes')

    # ── 筆記清單 ──
    def _read_order(self) -> dict:
        try:
            with open(os.path.join(self.dir, ORDER), encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_order(self, order: list[str], current: str | None = None):
        os.makedirs(self.dir, exist_ok=True)
        data = self._read_order()
        data['order'] = order
        if current is not None:
            data['current'] = current
        with open(os.path.join(self.dir, ORDER), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def names(self) -> list[str]:
        """頁籤順序（照記下的順序，新出現的檔案排在後面）；沒有任何筆記時建立一則範例"""
        try:
            files = sorted(n[:-len(EXT)] for n in os.listdir(self.dir) if n.lower().endswith(EXT))
        except OSError:
            files = []
        if not files:
            self.create('筆記', WELCOME)
            return ['筆記']
        order = [n for n in self._read_order().get('order', []) if n in files]
        return order + [n for n in files if n not in order]

    def current(self) -> str | None:
        names = self.names()
        cur = self._read_order().get('current')
        return cur if cur in names else (names[0] if names else None)

    def set_current(self, name: str):
        self._write_order(self.names(), name)

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name + EXT)

    @staticmethod
    def clean_name(name: str) -> str:
        name = _BAD.sub('', (name or '').strip()).strip('. ')[:NAME_MAX]
        return name

    def unique_name(self, base: str) -> str:
        base = self.clean_name(base) or '筆記'
        existing = {n.lower() for n in self._existing()}
        name, i = base, 2
        while name.lower() in existing:
            name = f'{base} {i}'
            i += 1
        return name

    def _existing(self) -> list[str]:
        try:
            return [n[:-len(EXT)] for n in os.listdir(self.dir) if n.lower().endswith(EXT)]
        except OSError:
            return []

    def create(self, name: str = '新筆記', text: str = '') -> str:
        os.makedirs(self.dir, exist_ok=True)
        name = self.unique_name(name)
        with open(self.path(name), 'w', encoding='utf-8') as f:
            f.write(text or f'# {name}\n\n')
        order = [n for n in self._read_order().get('order', []) if n in self._existing()]
        self._write_order(order + [name], name)
        return name

    def read(self, name: str) -> str:
        try:
            with open(self.path(name), encoding='utf-8') as f:
                return f.read()
        except OSError:
            return ''

    def write(self, name: str, text: str):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path(name) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, self.path(name))

    def rename(self, old: str, new: str) -> str:
        new = self.clean_name(new)
        if not new or new == old:
            return old
        if new.lower() != old.lower() and new.lower() in {n.lower() for n in self._existing()}:
            new = self.unique_name(new)
        os.replace(self.path(old), self.path(new))
        order = [new if n == old else n for n in self.names()]
        cur = self._read_order().get('current')
        self._write_order(order, new if cur == old else cur)
        self._set_collapsed_map(old, None, rename_to=new)
        return new

    def delete(self, name: str):
        try:
            os.remove(self.path(name))
        except OSError:
            pass
        order = [n for n in self.names() if n != name]
        self._write_order(order, order[0] if order else None)
        self._set_collapsed_map(name, None)

    # ── 收合的標題（以標題文字記住，改內容不會錯位）──
    def collapsed(self, name: str) -> set[str]:
        m = self._read_order().get('collapsed', {})
        return set(m.get(name, [])) if isinstance(m, dict) else set()

    def set_collapsed(self, name: str, titles):
        self._set_collapsed_map(name, sorted(titles))

    def _set_collapsed_map(self, name: str, titles, rename_to: str | None = None):
        data = self._read_order()
        m = data.get('collapsed', {})
        if not isinstance(m, dict):
            m = {}
        if rename_to is not None:
            if name in m:
                m[rename_to] = m.pop(name)
        elif titles:
            m[name] = list(titles)
        else:
            m.pop(name, None)
        data['collapsed'] = m
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, ORDER), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def move(self, name: str, index: int):
        order = [n for n in self.names() if n != name]
        order.insert(max(0, min(len(order), index)), name)
        self._write_order(order)

    # ── 圖片 ──
    def save_image(self, img, now: datetime | None = None) -> str:
        """貼上的圖片存到 notes/images/，回傳 Markdown 裡用的相對路徑"""
        folder = os.path.join(self.dir, IMAGES)
        os.makedirs(folder, exist_ok=True)
        stem = (now or datetime.now()).strftime('%Y%m%d_%H%M%S')
        name, i = f'{stem}.png', 2
        while os.path.exists(os.path.join(folder, name)):
            name = f'{stem}_{i}.png'
            i += 1
        img.save(os.path.join(folder, name), format='PNG')
        return f'{IMAGES}/{name}'

    def image_path(self, ref: str) -> str:
        """Markdown 裡的圖片路徑 → 實際檔案（相對於 notes/；也接受絕對路徑）"""
        ref = ref.strip().strip('<>')
        return ref if os.path.isabs(ref) else os.path.normpath(os.path.join(self.dir, ref))


# ─── Markdown → 區塊 ──
def blocks(text: str) -> list[tuple]:
    out: list[tuple] = []
    para: list[str] = []

    def flush():
        while para and not para[0].strip():
            para.pop(0)
        while para and not para[-1].strip():
            para.pop()
        if para:
            out.append(('text', '\n'.join(para)))
        para.clear()
    lines = (text or '').replace('\r\n', '\n').split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        fence = re.match(r'^\s*(```|~~~)\s*(\S*)', line)
        if fence:
            flush()
            mark, lang, body = fence.group(1), fence.group(2), []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(mark):
                body.append(lines[i])
                i += 1
            while body and not body[-1].strip():          # 沒有收尾的區塊（寫到檔案最後）不帶結尾空行
                body.pop()
            out.append(('code', lang, '\n'.join(body)))
            i += 1
            continue
        h = _HEADING.match(line)
        if h:
            flush()
            out.append(('heading', len(h.group(1)), h.group(2)))
        elif _IMAGE_LINE.match(line.strip()):
            flush()
            m = _IMAGE_LINE.match(line.strip())
            out.append(('image', m.group(1), m.group(2)))
        else:
            para.append(line)
        i += 1
    flush()
    return out


def headings(text: str) -> list[tuple[int, int, str]]:
    """目錄：[(區塊索引, 層級, 標題)]"""
    return [(i, b[1], b[2]) for i, b in enumerate(blocks(text)) if b[0] == 'heading']


def hard_breaks(markdown: str) -> str:
    """閱讀模式照編輯時的換行顯示：Markdown 的單一換行會被接成同一行，這裡每行行尾加上強制換行"""
    lines = markdown.split('\n')
    out = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ''
        if line.strip() and nxt.strip() and not line.endswith('  '):
            line += '  '
        out.append(line)
    return '\n'.join(out)


def plain(markdown: str) -> str:
    """複製段落時去掉 Markdown 記號（**粗體**、`程式碼`、[連結](網址)、清單符號）"""
    s = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', markdown)
    s = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', s)
    s = re.sub(r'(\*\*|__)(.+?)\1', r'\2', s)
    s = re.sub(r'(?<![\*\w])[\*_](?!\s)(.+?)(?<!\s)[\*_](?![\*\w])', r'\1', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)
    s = re.sub(r'^\s{0,3}>\s?', '', s, flags=re.M)
    return s
