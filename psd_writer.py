# -*- coding: utf-8 -*-
"""
psd_writer.py - 產生空白 PSD 畫布（給 SAI2 開啟的練習畫布用）

選 PSD 而非 PNG：SAI2 存回 PSD 會保留圖層，存 PNG 則會合併圖層。
只寫最精簡的結構：RGB 8-bit、無圖層區段（開啟後為單一背景圖層）、
解析度資訊與 PackBits（RLE）壓縮的合併影像；純色畫布每列只需幾個位元組。
"""

from __future__ import annotations

import struct


def _packbits_constant_row(value: int, width: int) -> bytes:
    """單一顏色一整列的 PackBits 編碼：每段最多 128 個重複位元組 → (1 - n) & 0xFF, value"""
    out = bytearray()
    left = width
    while left > 0:
        n = min(128, left)
        if n == 1:
            out += bytes((0, value))           # 字面值 1 個位元組
        else:
            out += bytes(((1 - n) & 0xFF, value))
        left -= n
    return bytes(out)


def _resolution_resource(dpi: int) -> bytes:
    """Image Resource 0x03ED（ResolutionInfo）：水平 / 垂直解析度，16.16 定點數，單位 pixels/inch"""
    fixed = dpi << 16
    data = struct.pack('>IHHIHH', fixed, 1, 1, fixed, 1, 1)
    # 8BIM + id + 空的 Pascal 名稱（長度 0，補齊到偶數）+ 資料長度 + 資料
    return b'8BIM' + struct.pack('>H', 0x03ED) + b'\x00\x00' + struct.pack('>I', len(data)) + data


def write_blank_psd(path: str, width: int, height: int,
                    color: tuple[int, int, int] = (255, 255, 255), dpi: int = 350):
    if width < 1 or height < 1 or width > 30000 or height > 30000:
        raise ValueError(f'畫布尺寸不合法：{width}x{height}')
    channels = 3
    header = b'8BPS' + struct.pack('>H', 1) + b'\x00' * 6 + struct.pack(
        '>HIIHH', channels, height, width, 8, 3)          # 3 = RGB
    color_mode = struct.pack('>I', 0)
    res = _resolution_resource(dpi)
    resources = struct.pack('>I', len(res)) + res
    layers = struct.pack('>I', 0)                          # 無圖層區段：開啟後為單一背景圖層

    rows = [_packbits_constant_row(c, width) for c in color]
    counts = b''.join(struct.pack('>H', len(rows[ch])) * height for ch in range(channels))
    data = b''.join(rows[ch] * height for ch in range(channels))
    image = struct.pack('>H', 1) + counts + data           # 1 = RLE

    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(header + color_mode + resources + layers + image)
    import os
    os.replace(tmp, path)
