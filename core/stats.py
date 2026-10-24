# -*- coding: utf-8 -*-
"""
stats.py - 動筆時間統計圖的資料（不含 UI；自 1.x main.py 的統計圖表移入）

資料來源是追蹤器的每日動筆秒數 {YYYY-MM-DD: 秒}。
期間：週（7 天）、月（30 天）、三月（90 天）、六月（26 週）、年（52 週）、至今（每月）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

PERIODS = [('week', '週'), ('month', '月'), ('quarter', '三個月'), ('half', '半年'), ('year', '一年'), ('all', '至今')]


@dataclass
class Bar:
    label: str            # 座標軸文字（空白 = 不顯示）
    tooltip: str
    seconds: float
    key: object


def fmt_duration(sec: float) -> str:
    m = int(sec // 60)
    if m >= 60:
        return f'{m // 60} 時 {m % 60:02d} 分'
    return f'{m} 分'


def fmt_axis(sec: float) -> str:
    h = sec / 3600
    if h >= 1:
        return f'{int(h)}h' if h == int(h) else f'{h:.1f}h'
    return f'{int(sec // 60)}m'


def _dates(history: dict[str, float]) -> dict[date, float]:
    out = {}
    for k, v in (history or {}).items():
        try:
            out[datetime.strptime(k, '%Y-%m-%d').date()] = float(v)
        except (ValueError, TypeError):
            pass
    return out


def chart_bars(history: dict[str, float], period: str, today: date | None = None) -> list[Bar]:
    h = _dates(history)
    today = today or datetime.now().date()
    bars: list[Bar] = []
    if period in ('week', 'month', 'quarter'):
        n, every = {'week': (7, 1), 'month': (30, 5), 'quarter': (90, 15)}[period]
        for i in range(n - 1, -1, -1):
            d = today - timedelta(days=i)
            v = h.get(d, 0.0)
            lbl = d.strftime('%m/%d') if (i % every == 0 or i == 0) else ''
            if period == 'week':
                lbl = '今天' if i == 0 else '一二三四五六日'[d.weekday()]
            bars.append(Bar(lbl, f'{d:%Y-%m-%d}　{fmt_duration(v)}', v, d))
    elif period in ('half', 'year'):
        n, every = {'half': (26, 4), 'year': (52, 8)}[period]
        for i in range(n - 1, -1, -1):
            end = today - timedelta(days=i * 7)
            start = end - timedelta(days=6)
            v = sum(h.get(start + timedelta(days=k), 0.0) for k in range(7))
            lbl = start.strftime('%m/%d') if (i % every == 0 or i == 0) else ''
            bars.append(Bar(lbl, f'{start:%m/%d}～{end:%m/%d}　{fmt_duration(v)}', v, (start, end)))
    else:
        first = min(h) if h else today
        y, m = first.year, first.month
        months = []
        while (y, m) <= (today.year, today.month):
            months.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        months = months[-24:] if len(months) > 24 else months
        step = max(1, len(months) // 8)
        for i, (y, m) in enumerate(months):
            v = sum(s for d, s in h.items() if d.year == y and d.month == m)
            lbl = f'{y}/{m:02d}' if (i % step == 0 or i == len(months) - 1) else ''
            bars.append(Bar(lbl, f'{y} 年 {m} 月　{fmt_duration(v)}', v, (y, m)))
    return bars


def summary(bars: list[Bar], period: str) -> dict:
    """{'total', 'avg_day', 'peak', 'peak_tip', 'active_days'}"""
    if not bars:
        return {'total': 0.0, 'avg_day': 0.0, 'peak': 0.0, 'peak_tip': '', 'unit': '天'}
    total = sum(b.seconds for b in bars)
    if period in ('week', 'month', 'quarter'):
        days = len(bars)
        unit = '天'
    elif period in ('half', 'year'):
        days = len(bars) * 7
        unit = '週'
    else:
        days = max(1, sum(30 for _ in bars))
        unit = '月'
    peak = max(bars, key=lambda b: b.seconds)
    return {'total': total, 'avg_day': total / max(1, days), 'peak': peak.seconds,
            'peak_tip': peak.tooltip if peak.seconds > 0 else '', 'unit': unit}
