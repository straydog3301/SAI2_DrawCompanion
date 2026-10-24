# -*- coding: utf-8 -*-
"""
exclusions.py - 不記錄的資料夾（不含 UI）

追蹤紀錄的 key 是 SAI2 標題裡的路徑把「/」換成「 _ 」，例如：
  「本機磁碟 (D:) _ art _ 立繪.psd」、「使用者名稱 _ 下載 _ 參考.png」
SAI2 標題顯示的是本機化的資料夾名稱（「下載」「桌面」），所以規則也以 key 的分段比對，不用實際路徑。

規則（settings2 的 exclude_folders）：
  {'kind': 'folder', 'value': '下載'}               路徑中任何一層資料夾叫這個名字（不分大小寫）
  {'kind': 'prefix', 'value': '本機磁碟 (D:) _ 素材'}  這個資料夾與底下所有子資料夾
"""

from __future__ import annotations

SEP = ' _ '
KINDS = ('folder', 'prefix')


def folder_of(key: str) -> str | None:
    """作品所在的資料夾（key 去掉最後的檔名）；沒有資料夾時回傳 None"""
    if SEP not in key:
        return None
    return key.rsplit(SEP, 1)[0]


def folder_label(prefix: str) -> str:
    """顯示用：「本機磁碟 (D:) › 素材」"""
    return prefix.replace(SEP, ' › ')


def normalize(rules) -> list[dict]:
    out, seen = [], set()
    for r in rules or []:
        if not isinstance(r, dict) or r.get('kind') not in KINDS:
            continue
        v = str(r.get('value') or '').strip()
        if not v:
            continue
        k = (r['kind'], v.lower())
        if k not in seen:
            seen.add(k)
            out.append({'kind': r['kind'], 'value': v})
    return out


def match(key: str | None, rules) -> bool:
    if not key:
        return False
    parts = key.split(SEP)
    folders = [p.strip().lower() for p in parts[:-1]]
    low = key.lower()
    for r in normalize(rules):
        v = r['value'].lower()
        if r['kind'] == 'folder' and v in folders:
            return True
        if r['kind'] == 'prefix' and low.startswith(v + SEP.lower()):
            return True
    return False


def matching(keys, rules) -> list[str]:
    return [k for k in keys if match(k, rules)]


def describe(rule: dict) -> str:
    if rule.get('kind') == 'folder':
        return f"名稱為「{rule['value']}」的資料夾"
    return folder_label(rule.get('value', ''))


def add(rules, kind: str, value: str) -> list[dict]:
    return normalize(list(rules or []) + [{'kind': kind, 'value': value}])


def remove(rules, rule: dict) -> list[dict]:
    target = (rule.get('kind'), str(rule.get('value', '')).strip().lower())
    return [r for r in normalize(rules) if (r['kind'], r['value'].lower()) != target]
