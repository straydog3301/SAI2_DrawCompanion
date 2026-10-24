# -*- coding: utf-8 -*-
"""
onboarding.py - 「不需要先設定，用到時才提醒」（docs/UI_2.0_PLAN.md §16，不含 UI）

- 第一次打開快捷面板：「30 秒調整你的練習」卡片（每日練習時間＋想加強的技能，可略過）
- 使用 3 天後：依實際動筆時間建議調整每日練習時間；詢問一次要不要開機啟動
- 第一次錄好縮時影片：告訴使用者影片放在哪裡、可以改

每個提醒只出現一次，記在 settings2 的 prompted。
"""

from __future__ import annotations

from datetime import datetime, timedelta

PRACTICE_MINUTES = (20, 40, 60, 90)
ASK_AFTER_DAYS = 3
TUNE_LOW = 0.5            # 平均動筆不到目標的一半 → 建議調低
TUNE_HIGH = 1.6           # 平均超過目標 1.6 倍 → 建議調高
TUNE_WINDOW = 7           # 看最近幾天（只算有開程式的天）

KEY_PRACTICE = 'practice_card'
KEY_TUNE = 'practice_tune'
KEY_AUTOSTART = 'autostart_ask'
KEY_FIRST_VIDEO = 'first_video'


def days_used(first_run_at: str, now: datetime | None = None) -> int:
    """從第一次啟動到現在過了幾天（日期差）；沒有紀錄回傳 0"""
    try:
        first = datetime.fromisoformat(first_run_at)
    except (TypeError, ValueError):
        return 0
    return max(0, ((now or datetime.now()).date() - first.date()).days)


def show_practice_card(settings, quests) -> bool:
    return (not settings.was_prompted(KEY_PRACTICE) and quests is not None
            and quests.settings.get('enabled', True))


def focus_choices(quests) -> list[tuple[str, str]]:
    """[(技能 id, 名稱)]；第一個是「平均練」"""
    out = [('', '平均練')]
    if quests is not None:
        out += [(s['id'], s['name']) for s in quests.data.get('skills', [])]
    return out


def apply_practice(quests, minutes: int, focus: str, now: datetime | None = None) -> bool:
    """套用卡片的選擇；今天還沒開始練習時依新設定重排課表。回傳是否重排"""
    quests.settings['budget_minutes'] = int(minutes)
    quests.settings['weekly_focus'] = focus or ''
    quests.mark_dirty()
    changed = quests.regenerate_today(now)
    quests.save(force=True)
    return changed


def _nearest(v: float) -> int:
    return min(PRACTICE_MINUTES, key=lambda m: abs(m - v))


def suggest_budget(history: dict, budget: float, now: datetime | None = None,
                   first_run_at: str = '') -> int | None:
    """依最近的實際動筆秒數（{'YYYY-MM-DD': 秒}）建議新的每日練習分鐘數；不需要調整回傳 None。
    只看啟用之後、今天以前的日子（今天還沒畫完）"""
    today = (now or datetime.now()).date()
    try:
        start = datetime.fromisoformat(first_run_at).date()
    except (TypeError, ValueError):
        start = today - timedelta(days=TUNE_WINDOW)
    start = max(start, today - timedelta(days=TUNE_WINDOW))
    days = []
    d = start
    while d < today:
        days.append(float(history.get(d.strftime('%Y-%m-%d'), 0.0)) / 60)
        d += timedelta(days=1)
    if len(days) < ASK_AFTER_DAYS:
        return None
    avg = sum(days) / len(days)
    budget = float(budget or 60)
    if avg < budget * TUNE_LOW or avg > budget * TUNE_HIGH:
        new = _nearest(avg)
        if new < PRACTICE_MINUTES[0]:
            new = PRACTICE_MINUTES[0]
        return new if new != int(budget) else None
    return None


def due_after_days(settings, key: str, now: datetime | None = None) -> bool:
    """使用滿 ASK_AFTER_DAYS 天、且還沒問過"""
    return not settings.was_prompted(key) and days_used(settings.get('first_run_at', ''), now) >= ASK_AFTER_DAYS
