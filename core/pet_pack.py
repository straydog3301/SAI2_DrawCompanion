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
    tint: str | None = None                  # 內建角色的身體顏色（跟隨主題色）

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
            return pet_builtin.frames(real, size, self.tint)
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


def builtin_pack(tint: str | None = None) -> PetPack:
    return PetPack(folder='', name='墨墨（內建）', states={s: {'loop': s not in ONE_SHOT} for s in STATES}, tint=tint)


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


def list_packs(pets_dir: str, tint: str | None = None) -> list[PetPack]:
    """內建角色＋ pets/ 底下可讀取的角色包"""
    packs = [builtin_pack(tint)]
    if os.path.isdir(pets_dir):
        for name in sorted(os.listdir(pets_dir)):
            folder = os.path.join(pets_dir, name)
            if os.path.isdir(folder):
                try:
                    packs.append(load_pack(folder))
                except (ValueError, OSError):
                    pass
    return packs


def find_pack(pets_dir: str, pack_id: str, tint: str | None = None) -> PetPack:
    if pack_id:
        folder = os.path.join(pets_dir, pack_id)
        if os.path.isdir(folder):
            try:
                return load_pack(folder)
            except (ValueError, OSError):
                pass
    return builtin_pack(tint)


# ─── 寵物工作室：建立、修改、匯入、刪除角色包 ─────────────────────────────

MAX_IMPORT_BYTES = 80 * 1024 * 1024


def safe_name(name: str) -> str:
    bad = '\\/:*?"<>|'
    out = ''.join('_' if c in bad else c for c in (name or '').strip()).strip(' .')
    return out[:40] or 'my_pet'


def _unique_dir(pets_dir: str, name: str) -> str:
    base = os.path.join(pets_dir, safe_name(name))
    path, n = base, 2
    while os.path.exists(path):
        path = f'{base}_{n}'
        n += 1
    return path


def _write_manifest(folder: str, pack: PetPack):
    data = {'name': pack.name, 'anchor': pack.anchor, 'states': {}}
    for st, spec in pack.states.items():
        item = {'file': spec['file']}
        if spec.get('frames'):
            item['frames'] = int(spec['frames'])
            item['fps'] = float(spec.get('fps') or 12)
        if 'loop' in spec and spec['loop'] != (st not in ONE_SHOT):
            item['loop'] = bool(spec['loop'])
        data['states'][st] = item
    with open(os.path.join(folder, MANIFEST), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _check_image(path: str):
    if os.path.splitext(path)[1].lower() not in IMAGE_EXTS:
        raise ValueError('只支援 PNG、APNG、GIF、WebP')
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception as e:
        raise ValueError(f'無法讀取圖檔：{e}')


def create_pack(pets_dir: str, name: str, idle_src: str) -> str:
    """建立新角色（至少要有「待命」圖），回傳 pack_id"""
    _check_image(idle_src)
    os.makedirs(pets_dir, exist_ok=True)
    folder = _unique_dir(pets_dir, name)
    os.makedirs(folder)
    ext = os.path.splitext(idle_src)[1].lower()
    import shutil
    shutil.copy2(idle_src, os.path.join(folder, f'idle{ext}'))
    _write_manifest(folder, PetPack(folder=folder, name=(name or '').strip() or os.path.basename(folder),
                                    states={'idle': {'file': f'idle{ext}'}}))
    return os.path.basename(folder)


def set_state(folder: str, state: str, src: str | None = None, frames: int | None = None,
              fps: float | None = None, loop: bool | None = None):
    """指定某狀態的圖檔（複製進角色資料夾）或調整格數 / 速度 / 循環"""
    import shutil
    if state not in STATES:
        raise ValueError(f'不認得的狀態：{state}')
    pack = load_pack(folder)
    spec = dict(pack.states.get(state) or {})
    if src:
        _check_image(src)
        ext = os.path.splitext(src)[1].lower()
        old = spec.get('file')
        fn = f'{state}{ext}'
        shutil.copy2(src, os.path.join(folder, fn))
        if old and old != fn and os.path.isfile(os.path.join(folder, old)) and \
                all(s.get('file') != old for k, s in pack.states.items() if k != state):
            os.remove(os.path.join(folder, old))
        spec = {'file': fn}
    if not spec.get('file'):
        raise ValueError('請先指定這個狀態的圖檔')
    if frames is not None:
        spec['frames'] = int(frames) if frames and frames > 1 else None
        if spec['frames']:
            spec['fps'] = float(fps or spec.get('fps') or 12)
    elif fps is not None and spec.get('frames'):
        spec['fps'] = float(fps)
    if loop is not None:
        spec['loop'] = bool(loop)
    pack.states[state] = spec
    _write_manifest(folder, pack)


def clear_state(folder: str, state: str):
    if state == 'idle':
        raise ValueError('「待命」是必要的狀態，只能換圖不能清除')
    pack = load_pack(folder)
    spec = pack.states.pop(state, None)
    if spec:
        fn = spec.get('file')
        if fn and all(s.get('file') != fn for s in pack.states.values()):
            try:
                os.remove(os.path.join(folder, fn))
            except OSError:
                pass
    _write_manifest(folder, pack)


def rename_pack(folder: str, name: str):
    pack = load_pack(folder)
    pack.name = (name or '').strip() or pack.name
    _write_manifest(folder, pack)


def _pack_root(path: str) -> str:
    """角色包的根目錄：有 pet.json 或狀態圖檔的那一層（zip 常多包一層資料夾）"""
    def looks_like(d):
        names = [n.lower() for n in os.listdir(d)]
        return MANIFEST in names or any(os.path.splitext(n)[0] in STATES and n.endswith(IMAGE_EXTS) for n in names)
    if looks_like(path):
        return path
    subs = [os.path.join(path, n) for n in os.listdir(path) if os.path.isdir(os.path.join(path, n))]
    if len(subs) == 1 and looks_like(subs[0]):
        return subs[0]
    raise ValueError('找不到角色包內容（需要 pet.json，或 idle.png 這類以狀態命名的圖檔）')


def import_pack(src: str, pets_dir: str) -> str:
    """從 zip 或資料夾匯入角色包，回傳 pack_id；內容有問題時不留下任何檔案"""
    import shutil
    import tempfile
    import zipfile
    tmp = None
    try:
        if os.path.isfile(src) and src.lower().endswith('.zip'):
            tmp = tempfile.mkdtemp(prefix='pet_import_')
            with zipfile.ZipFile(src) as z:
                total = 0
                for info in z.infolist():
                    total += info.file_size
                    if total > MAX_IMPORT_BYTES:
                        raise ValueError('角色包太大（超過 80 MB）')
                    target = os.path.normpath(os.path.join(tmp, info.filename))
                    if not target.startswith(os.path.normpath(tmp) + os.sep) and target != os.path.normpath(tmp):
                        raise ValueError('角色包內有不安全的路徑')
                z.extractall(tmp)
            root = _pack_root(tmp)
        elif os.path.isdir(src):
            root = _pack_root(src)
        else:
            raise ValueError('請選擇 zip 檔或資料夾')
        load_pack(root)
        name = os.path.splitext(os.path.basename(src.rstrip('\\/')))[0]
        try:
            with open(os.path.join(root, MANIFEST), encoding='utf-8') as f:
                name = json.load(f).get('name') or name
        except (OSError, ValueError):
            pass
        os.makedirs(pets_dir, exist_ok=True)
        dest = _unique_dir(pets_dir, name)
        shutil.copytree(root, dest, ignore=shutil.ignore_patterns('__MACOSX', '.*'))
        try:
            load_pack(dest)
        except ValueError:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        return os.path.basename(dest)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def delete_pack(pets_dir: str, pack_id: str):
    import shutil
    if not pack_id:
        raise ValueError('內建角色不能刪除')
    folder = os.path.normpath(os.path.join(pets_dir, pack_id))
    if os.path.dirname(folder) != os.path.normpath(pets_dir) or not os.path.isdir(folder):
        raise ValueError('找不到這個角色')
    shutil.rmtree(folder)
