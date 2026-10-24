# -*- coding: utf-8 -*-
"""
canvas_crop.py - 從 SAI2 畫布視窗的擷取畫面找出「畫紙」的範圍（不含 UI）

SAI2 的畫布視窗（暗色系、白色系都一樣）：
  ┌ 外框：四邊對稱、每層顏色一致的細線（目前是 3 px）
  │ 工作區：畫紙以外的單色區域（暗色系 24 灰、白色系 176 灰、舊版是偏藍的灰）
  │ 畫紙：可能縮小在中間、放大到超出視窗、或旋轉
  └ 右側與下方的捲軸：以「和外框最內層同色」的一條線和畫面分隔
捲軸是畫在視窗裡的，不是子視窗，所以只能從畫面判斷。

paper_box(img) 回傳畫紙在圖中的範圍；畫紙填滿整個畫面（放大）時回傳畫面範圍（去掉外框與捲軸）。
旋轉的畫紙回傳外接矩形。筆刷游標、選取框等細線不會被當成畫紙。
"""

from __future__ import annotations

from PIL import Image, ImageChops, ImageFilter

MAX_FRAME = 12          # 外框最多幾層
SCROLL_ZONE = 96        # 捲軸只會在離外框這麼近的範圍內（px，4K 150% 約 25 px）
TOL = 6                 # 顏色容許差
DIFF = 18               # 與工作區相差多少算「不是工作區」
WHITE = 235             # 三個色版都高於這個值：是白紙，不會是工作區


def _close(a, b, tol=TOL) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= tol


def _uniform(px, coords) -> tuple | None:
    """這些點最多的顏色（九成以上一致時），否則 None。角落的幾個點和外框交疊，不影響判斷"""
    ps = [px[c] for c in coords]
    if not ps:
        return None
    counts: dict = {}
    for p in ps:
        counts[p] = counts.get(p, 0) + 1
    top = max(counts, key=counts.get)
    return top if sum(1 for p in ps if _close(p, top)) >= 0.9 * len(ps) else None


def view_box(rgb: Image.Image) -> tuple[int, int, int, int]:
    """畫布視窗中「畫面」的範圍：去掉四邊的外框，以及右側、下方的捲軸"""
    return _view_box(rgb)[0]


def _view_box(rgb: Image.Image) -> tuple[tuple[int, int, int, int], bool]:
    """(畫面範圍, 是否找到外框)"""
    w, h = rgb.size
    px = rgb.load()
    ys = range(0, h, max(1, h // 64))
    xs = range(0, w, max(1, w // 64))

    def col(x):
        return _uniform(px, ((x, y) for y in ys))

    def row(y):
        return _uniform(px, ((x, y) for x in xs))

    # 外框：從邊緣往內，四邊同一層都是同一個顏色
    frame = 0
    line = None
    for k in range(min(MAX_FRAME, w // 4, h // 4)):
        cs = [col(k), col(w - 1 - k), row(k), row(h - 1 - k)]
        if any(c is None for c in cs) or not all(_close(c, cs[0]) for c in cs):
            break
        inner = col(k + 1)
        if inner is not None and _close(inner, cs[0]):
            break               # 外框每一層都和內側不同色；整片同色的是工作區，不是外框
        frame, line = k + 1, cs[0]
    right, bottom = w - frame, h - frame
    if line is not None:
        # 捲軸：右側與下方各有一條分隔線（一整條同色、和外側不同色），兩邊捲軸一樣粗。
        # 分隔線的顏色不一定和外框相同（SAI2 在前景時，使用中的畫面外框會變成主題色）
        def edges(get, start, end):
            out = []
            for i in range(max(frame + 1, start), end):
                c, prev = get(i), get(i - 1)
                if c is not None and not (prev is not None and _close(prev, c)):
                    out.append(i)
            return out
        xs_ = edges(col, w - frame - SCROLL_ZONE, w - frame - 1)
        ys_ = edges(row, h - frame - SCROLL_ZONE, h - frame - 1)
        pairs = [(x, y) for x in xs_ for y in ys_ if abs((w - frame - x) - (h - frame - y)) <= 1]
        if pairs:
            right, bottom = min(pairs)
        else:
            # 只有一邊找得到時，退回「與外框最內層同色」的線
            same = [x for x in xs_ if _close(col(x), line)]
            right = same[0] if same else right
            same = [y for y in ys_ if _close(row(y), line)]
            bottom = same[0] if same else bottom
    if right - frame < 8 or bottom - frame < 8:
        return (0, 0, w, h), False
    return (frame, frame, right, bottom), frame > 0


def _strip_lines(mask: Image.Image, zone: int = 64) -> tuple[int, int, int, int]:
    """沒有對稱外框時（較舊的版面、捲軸蓋住外框）：去掉邊緣附近貫穿整個畫面的細線（外框、捲軸邊線）。
    只認 1～3 px 的細線，畫紙的邊緣（後面還連著整片）不會被當成線"""
    w, h = mask.size
    px = mask.load()
    zone = min(zone, w // 4, h // 4)

    def full_col(x):
        if not 0 <= x < w:
            return False
        ys = range(0, h, 4)
        return sum(1 for y in ys if px[x, y]) >= 0.9 * len(ys)

    def full_row(y):
        if not 0 <= y < h:
            return False
        xs = range(0, w, 4)
        return sum(1 for x in xs if px[x, y]) >= 0.9 * len(xs)

    def cut(full, rng, inward):
        found = None
        for i in rng:
            if full(i) and not full(i + inward) and not all(full(i - inward * k) for k in range(1, 4)):
                found = i
        return found
    left = cut(full_col, range(zone), 1)
    right = cut(full_col, range(w - 1, w - 1 - zone, -1), -1)
    top = cut(full_row, range(zone), 1)
    bottom = cut(full_row, range(h - 1, h - 1 - zone, -1), -1)
    return (0 if left is None else left + 1, 0 if top is None else top + 1,
            w if right is None else right, h if bottom is None else bottom)


def workspace_color(view: Image.Image) -> tuple | None:
    """畫面四邊出現最多的顏色，且至少兩邊有一定比例是它，才當成工作區。
    畫紙填滿畫面時邊緣都是畫紙（多半是白色），不會被當成工作區"""
    w, h = view.size
    px = view.load()
    m = 2 if w > 8 and h > 8 else 0
    n = 48
    sides = [
        [px[min(w - 1, m + i * (w - 2 * m) // n), m] for i in range(n)],
        [px[min(w - 1, m + i * (w - 2 * m) // n), h - 1 - m] for i in range(n)],
        [px[m, min(h - 1, m + i * (h - 2 * m) // n)] for i in range(n)],
        [px[w - 1 - m, min(h - 1, m + i * (h - 2 * m) // n)] for i in range(n)],
    ]
    counts: dict = {}
    for side in sides:
        for p in side:
            counts[p] = counts.get(p, 0) + 1
    bg = max(counts, key=counts.get)
    if min(bg) >= WHITE:
        return None
    sides_with_bg = sum(1 for side in sides if sum(_close(p, bg) for p in side) >= 0.3 * len(side))
    return bg if sides_with_bg >= 2 else None


def paper_box(img: Image.Image) -> tuple[int, int, int, int]:
    """畫紙在 img 中的範圍 (left, top, right, bottom)"""
    rgb = img.convert('RGB')
    (l, t, r, b), framed = _view_box(rgb)
    view = rgb.crop((l, t, r, b))
    bg = workspace_color(view)
    if bg is None:
        return l, t, r, b
    if not framed:
        full = ImageChops.difference(view, Image.new('RGB', view.size, bg)).convert('L').point(
            lambda v: 255 if v > DIFF else 0)
        il, it, ir, ib = _strip_lines(full)
        if (il, it, ir, ib) != (0, 0, view.size[0], view.size[1]) and ir - il > 8 and ib - it > 8:
            l, t, r, b = l + il, t + it, l + ir, t + ib
            view = rgb.crop((l, t, r, b))
    vw, vh = view.size
    # 先縮小找大概的範圍（快、細線會被侵蝕掉），再回原尺寸修邊
    f = max(1, max(vw, vh) // 800)
    small = view.reduce(f) if f > 1 else view
    mask = ImageChops.difference(small, Image.new('RGB', small.size, bg)).convert('L').point(
        lambda v: 255 if v > DIFF else 0)
    coarse = mask.filter(ImageFilter.MinFilter(3)).getbbox()
    if not coarse:
        return l, t, r, b
    pad = 2 * f + 2
    cx0, cy0 = max(0, coarse[0] * f - pad), max(0, coarse[1] * f - pad)
    cx1, cy1 = min(vw, coarse[2] * f + pad), min(vh, coarse[3] * f + pad)
    region = view.crop((cx0, cy0, cx1, cy1))
    # 修邊時同樣去掉細線：畫紙邊緣上的筆刷游標圓圈不會把一條工作區算進來（錄影時畫面才不會忽大忽小）
    fine = ImageChops.difference(region, Image.new('RGB', region.size, bg)).convert('L').point(
        lambda v: 255 if v > DIFF else 0).filter(ImageFilter.MinFilter(3)).getbbox()
    if not fine:
        return l, t, r, b
    x0, y0 = cx0 + max(0, fine[0] - 1), cy0 + max(0, fine[1] - 1)
    x1, y1 = cx0 + min(region.size[0], fine[2] + 1), cy0 + min(region.size[1], fine[3] + 1)
    if (x1 - x0) * (y1 - y0) < 0.002 * vw * vh:
        return l, t, r, b       # 太小：多半只是游標之類的雜訊
    return l + x0, t + y0, l + x1, t + y1


def crop_paper(img: Image.Image) -> Image.Image:
    return img.convert('RGB').crop(paper_box(img))
