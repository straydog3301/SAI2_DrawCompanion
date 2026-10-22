# -*- coding: utf-8 -*-
"""
pet_pack.py - 桌面寵物的角色包（不含 UI）

角色包＝ APP_DIR/pets/<名稱>/ 底下的 pet.json ＋各狀態圖檔：
    {"name": "我的貓", "anchor": "bottom-center",
     "states": {"idle": {"file": "idle.apng", "loop": true},
                "drawing": {"file": "draw.png", "frames": 8, "fps": 12}}}
- 支援 PNG（靜態）、GIF、APNG、WebP，或橫排精靈圖（frames 指定格數）
- 沒設定圖檔的狀態依 FALLBACK 沿用其他狀態，最少只要一張「待命」
- 影格一律用 Pillow 解碼，載入時就縮到顯示大小
沒有 pet.json、只放了 idle.png / drawing.gif 這類以狀態命名的圖檔，也會自動辨識。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from PIL import Image, ImageSequence

STATES = ('idle', 'drawing', 'cheer', 'rest', 'remind', 'sleep', 'offline')
STATE_LABELS = {'idle': '待命', 'drawing': '一起畫', 'cheer': '歡呼', 'rest': '休息',
                'remind': '提醒', 'sleep': '睡覺', 'offline': '未連結'}
FALLBACK = {'offline': ('sleep', 'idle'), 'sleep': ('idle',), 'drawing': ('idle',), 'cheer': ('idle',),
            'rest': ('sleep', 'idle'), 'remind': ('idle',), 'idle': ()}
ONE_SHOT = ('cheer', 'remind')              # 預設只播一次的狀態
IMAGE_EXTS = ('.apng', '.png', '.gif', '.webp')
MAX_FRAMES = 120
MAX_FILE_BYTES = 5 * 1024 * 1024
MANIFEST = 'pet.json'
BUILTIN_ID = ''


@dataclass
class PetPack:
    folder: str                              # 內建角色為空字串
    name: str
    anchor: str = 'bottom-center'
    states: dict = field(default_factory=dict)   # state -> {'file', 'frames', 'fps', 'loop'}
    warnings: list = field(default_factory=list)

    @property
    def pack_id(self) -> str:
        return os.path.basename(self.folder) if self.folder else BUILTIN_ID

    @property
    def builtin(self) -> bool:
        return not self.folder

    def resolve(self, state: str) -> str:
        """實際要播放的狀態（沒設定時依 FALLBACK 沿用）"""
        if state in self.states or self.builtin:
            return state
        for alt in FALLBACK.get(state, ()):
            if alt in self.states:
                return alt
        return 'idle' if 'idle' in self.states else next(iter(self.states), state)

    def loops(self, state: str) -> bool:
        """有自己的圖檔時依 pet.json；沿用其他狀態時，歡呼 / 提醒仍只播一次"""
        spec = self.states.get(state)
        return bool(spec.get('loop', state not in ONE_SHOT)) if spec else state not in ONE_SHOT

    def frames(self, state: str, size: int) -> list[tuple[Image.Image, int]]:
        """[(size×size 的 RGBA 影格, 毫秒)]"""
        real = self.resolve(state)
        if self.builtin:
            from core import pet_builtin
            return pet_builtin.frames(real, size)
        spec = self.states[real]
        return decode(os.path.join(self.folder, spec['file']), size, spec.get('frames'), spec.get('fps'), self.anchor)


def decode(path: str, size: int, frames: int | None = None, fps: float | None = None,
           anchor: str = 'bottom-center') -> list[tuple[Image.Image, int]]:
    im = Image.open(path)
    if frames:
        w = im.width // int(frames)
        raw = [im.crop((i * w, 0, (i + 1) * w, im.height)) for i in range(int(frames))]
        durs = [int(1000 / float(fps or 12))] * len(raw)
    else:
        raw, durs = [], []
        for fr in ImageSequence.Iterator(im):
            raw.append(fr.convert('RGBA'))
            durs.append(int(fr.info.get('duration') or im.info.get('duration') or 100))
            if len(raw) >= MAX_FRAMES:
                break
    out = []
    for fr, ms in zip(raw[:MAX_FRAMES], durs):
        fr = fr.convert('RGBA')
        fr.thumbnail((size, size), Image.LANCZOS)
        canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        x = (size - fr.width) // 2
        y = size - fr.height if anchor.startswith('bottom') else (size - fr.height) // 2
        canvas.paste(fr, (x, y))
        out.append((canvas, max(16, ms)))
    return out


def builtin_pack() -> PetPack:
    return PetPack(folder='', name='墨墨（內建）', states={s: {'loop': s not in ONE_SHOT} for s in STATES})


def load_pack(folder: str) -> PetPack:
    """讀取角色包；有問題的狀態略過並記在 warnings，沒有任何可用圖檔時丟 ValueError"""
    pack = PetPack(folder=folder, name=os.path.basename(folder))
    manifest = os.path.join(folder, MANIFEST)
    specs: dict = {}
    if os.path.isfile(manifest):
        try:
            with open(manifest, encoding='utf-8') as f:
                meta = json.load(f)
        except (OSError, ValueError) as e:
            raise ValueError(f'pet.json 格式錯誤：{e}')
        pack.name = str(meta.get('name') or pack.name)
        pack.anchor = str(meta.get('anchor') or pack.anchor)
        specs = meta.get('states') or {}
    else:
        for fn in sorted(os.listdir(folder)):
            stem, ext = os.path.splitext(fn)
            if stem.lower() in STATES and ext.lower() in IMAGE_EXTS:
                specs.setdefault(stem.lower(), {'file': fn})
    for state, spec in specs.items():
        if state not in STATES:
            pack.warnings.append(f'不認得的狀態：{state}')
            continue
        if isinstance(spec, str):
            spec = {'file': spec}
        fn = spec.get('file', '')
        path = os.path.join(folder, fn)
        if not fn or not os.path.isfile(path):
            pack.warnings.append(f'{STATE_LABELS[state]}：找不到 {fn or "圖檔"}')
            continue
        if os.path.getsize(path) > MAX_FILE_BYTES:
            pack.warnings.append(f'{STATE_LABELS[state]}：{fn} 超過 5 MB，載入可能較慢')
        try:
            with Image.open(path) as im:
                n = getattr(im, 'n_frames', 1)
        except Exception as e:
            pack.warnings.append(f'{STATE_LABELS[state]}：無法讀取 {fn}（{e}）')
            continue
        if n > MAX_FRAMES:
            pack.warnings.append(f'{STATE_LABELS[state]}：{n} 格，只會播放前 {MAX_FRAMES} 格')
        pack.states[state] = {'file': fn, 'frames': spec.get('frames'), 'fps': spec.get('fps'),
                              'loop': spec.get('loop', state not in ONE_SHOT)}
    if not pack.states:
        raise ValueError('角色包裡沒有可用的狀態圖檔（至少需要一張 idle）')
    return pack


def list_packs(pets_dir: str) -> list[PetPack]:
    """內建角色＋ pets/ 底下可讀取的角色包"""
    packs = [builtin_pack()]
    if os.path.isdir(pets_dir):
        for name in sorted(os.listdir(pets_dir)):
            folder = os.path.join(pets_dir, name)
            if os.path.isdir(folder):
                try:
                    packs.append(load_pack(folder))
                except (ValueError, OSError):
                    pass
    return packs


def find_pack(pets_dir: str, pack_id: str) -> PetPack:
    if pack_id:
        folder = os.path.join(pets_dir, pack_id)
        if os.path.isdir(folder):
            try:
                return load_pack(folder)
            except (ValueError, OSError):
                pass
    return builtin_pack()
