# -*- coding: utf-8 -*-
"""線條圖示（Lucide 風格的 24×24 路徑），依顏色即時繪成 QIcon"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    'sketch': 'M13 2 3 14h9l-1 8 10-12h-9z',
    'study': 'M3 5h18v14H3zM3 15l5-5 5 5 3-3 5 5',
    'snapshot': 'M4 7h3l2-3h6l2 3h3v13H4zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
    'record': 'M23 7l-7 5 7 5zM1 5h15v14H1z',
    'works': 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
    'open_sai2': 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z',
    'settings': 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1',
    'home': 'M3 10l9-7 9 7v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
    'hide': 'M17.9 17.9A10 10 0 0 1 12 20c-7 0-10-8-10-8a18 18 0 0 1 4.1-5.1M9.9 4.2A9 9 0 0 1 12 4c7 0 10 8 10 8a18 18 0 0 1-2.2 3.2M1 1l22 22',
    'play': 'M7 4l12 8-12 8z',
    'check': 'M5 12l5 5 9-10',
    'more': 'M5 12h.01M12 12h.01M19 12h.01',
    'flame': 'M12 3c1 4 6 6 6 11a6 6 0 0 1-12 0c0-3 2-4.5 2-7 1.5 1 2.5 2.5 3 4 .5-3 1-5 1-8z',
    'file': 'M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6',
    'close': 'M6 6l12 12M18 6 6 18',
    'flip': 'M12 3v18M8 7 3 12l5 5M16 7l5 5-5 5',
    'gray': 'M12 21a9 9 0 1 0 0-18v18z',
    'value': 'M4 20h4v-6H4zM10 20h4V9h-4zM16 20h4V4h-4z',
    'grid': 'M3 3h18v18H3zM9 3v18M15 3v18M3 9h18M3 15h18',
    'compare': 'M3 4h8v16H3zM13 4h8v16h-8z',
    'through': 'M4 4l7 17 2-7 7-2z',
    'opacity': 'M12 2.7l5.7 5.7a8 8 0 1 1-11.4 0z',
    'minimize': 'M5 12h14',
    'prev': 'M15 18l-6-6 6-6',
    'up': 'M18 15l-6-6-6 6',
    'down': 'M6 9l6 6 6-6',
    'next': 'M9 18l6-6-6-6',
    'pause': 'M7 5h3v14H7zM14 5h3v14h-3z',
    'canvas': 'M4 4h16v16H4zM12 8v8M8 12h8',
    'link': 'M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1',
    'image': 'M3 5h18v14H3zM3 15l5-5 5 5 3-3 5 5',
    'refresh': 'M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5',
}


def icon(name: str, color: str | None = None, size: int = 20, width: float = 1.8) -> QIcon:
    from ui2 import theme
    return _icon(name, color or theme.ICON, size, width)


@lru_cache(maxsize=256)
def _icon(name: str, color: str, size: int, width: float) -> QIcon:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"><path d="{PATHS[name]}"/></svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        r.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    return ic
