# -*- coding: utf-8 -*-
"""（需連網）美術館開放典藏：每堂使用美術館參考圖的課程，至少要有一個來源能取得畫家相符的公有領域作品。
API 若改版（例如大都會博物館 2026-10-01 停用 v1/search）這個測試會失敗。"""
import os
import sys
import random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done  # noqa: E402

from core import study_refs as R  # noqa: E402
from core.study_lessons import LESSONS  # noqa: E402

rng = random.Random(1)
cache = {}


def works(ref) -> bool:
    key = tuple(ref)
    if key not in cache:
        fn = R._from_met if ref[0] == 'met' else R._from_artic
        try:
            got = fn(ref[1], ref[2], set(), rng, ref[3] if len(ref) > 3 else None)
        except Exception as e:
            print(f'  {ref[0]} {ref[1]}: {e}')
            got = None
        if got:
            print(f"  {ref[0]:5s} {ref[1]:22s} → {got[1]['artist'][:30]} | {got[1]['title'][:40]}")
        cache[key] = bool(got) and R._norm(ref[2]) in R._norm(got[1]['artist'])
    return cache[key]


for les in LESSONS:
    museum = [r for r in les['refs'] if r[0] in ('met', 'artic')]
    if museum:
        check(any(works(r) for r in museum), f"{les['id']}: no museum source works")
done()
