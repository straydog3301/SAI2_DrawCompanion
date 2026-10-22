# -*- coding: utf-8 -*-
"""作品檔案技能標籤、範本與技能管理的驗證規則（不得依賴 Tk）"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk  # noqa: E402,F401
import random
import tempfile
from datetime import datetime
block_tk()
from core.daily_quests import QuestManager
from core import growth as G



NOW = datetime(2026, 10, 22, 12)
m = QuestManager(os.path.join(tempfile.mkdtemp(), 'q.json'), rng=random.Random(1))
m.ensure_today(NOW)

# ── 作品檔案技能標籤 ──
m.set_file_tags('立繪.psd', ['color', 'rendering', 'nope'])
check(m.file_tags('立繪.psd') == {'color': 0.5, 'rendering': 0.5}, f"tags {m.file_tags('立繪.psd')}")
for _ in range(3):
    m.tick(10, NOW, current_file='立繪.psd')
m.tick(10, NOW, current_file='未標記.psd')
day = m.day_key(NOW)
entries = [e for e in m.data['practice_log'][day] if e['source'] == 'file']
check(len(entries) == 1 and entries[0]['seconds'] == 30, f'file log merged {entries}')
sec = m.skill_seconds()
check(abs(sec['color'] - 15) < 1e-9 and abs(sec['rendering'] - 15) < 1e-9, f'weighted {sec}')
st = m.add_today('t_st_value'); m.start_study(st['uid'])
m.tick(10, NOW, current_file='立繪.psd')
check(entries[0]['seconds'] == 30, 'no file log while studying (counted by study)')
m.stop_study()
card = next(c for c in G.skill_cards(m, NOW) if c['id'] == 'color')
check(abs(card['total_seconds'] - 15) < 1e-9, 'file time in skill card')
m.set_file_tags('立繪.psd', [])
check('立繪.psd' not in m.data['file_tags'], 'clear tags')

# ── 範本管理 ──
base = {'mode': 'sketch', 'name': '龍的速寫', 'skills': {'form': 1.0},
        'params': {'topic': 'kw:dragon', 'count': 10, 'interval': 60}, 'weight': 1.0}
tid, err = m.add_template(base)
check(err is None and tid.startswith('u_') and m.template(tid)['params']['topic'] == 'kw:dragon', f'add {err}')
bad_cases = [
    (dict(base, name=''), '請輸入名稱'),
    (dict(base, mode='xx'), '請選擇練習方式'),
    (dict(base, skills={'ghost': 1.0}), '技能設定不正確'),
    (dict(base, params={'topic': 'pose', 'count': 0, 'interval': 60}), '張數需介於 1～200'),
    (dict(base, params={'topic': 'pose', 'count': 5, 'interval': 45}), '每張秒數不正確'),
    (dict(base, weight=9), '權重需介於 0.1～5'),
    ({'mode': 'study', 'name': 'x', 'params': {'path': 'nope'}}, '學習路徑不存在'),
    ({'mode': 'study', 'name': 'x', 'params': {'minutes': 2}}, '分鐘數需介於 5～240'),
    ({'mode': 'drill', 'name': 'x', 'params': {'count': 10, 'est_minutes': 0}}, '預估分鐘需介於 1～240'),
    ({'mode': 'draw_time', 'name': 'x', 'params': {'minutes': 900}}, '分鐘數需介於 5～600'),
]
for tpl, want in bad_cases:
    check(m.add_template(tpl)[1] == want, f'{want} -> {m.add_template(tpl)[1]}')
check(m.update_template(tid, dict(base, name='龍與恐龍', params={'topic': 'kw:dinosaur', 'count': 6,
                                                               'interval': 90, 'junk': 1})) is None, 'update')
check(m.template(tid)['name'] == '龍與恐龍' and 'junk' not in m.template(tid)['params'], 'params cleaned')
m.set_template_enabled(tid, False)
check(tid not in {t['id'] for t in m.addable_templates()}, 'disabled not addable')
m.set_template_enabled(tid, True)
check(any(t['id'] == tid for t in m.addable_templates()), 'enabled addable')
check(m.delete_template('t_sk_pose') == '內建範本無法刪除，可以改為停用', 'builtin delete refused')
check(m.update_template('t_dt_30', {'mode': 'draw_time', 'name': '創作 45 分鐘', 'params': {'minutes': 45}}) is None
      and m.template('t_dt_30')['params']['minutes'] == 45, 'builtin editable')
check(m.delete_template(tid) is None and m.template(tid) is None, 'custom delete')
sid, err = m.add_template({'mode': 'study', 'name': '自由臨摹', 'skills': {'color': 1.0}, 'params': {'minutes': 25}})
check(err is None and m._effective(m.template(sid))['params'].get('lesson_id') is None, 'custom study without path')

# ── 技能管理 ──
k, err = m.add_skill('場景設計', '🏙')
check(err is None and m.skill(k)['name'] == '場景設計', 'add skill')
check(m.add_skill('場景設計')[1] == '已有同名技能', 'dup skill')
check(m.add_skill('')[1] == '請輸入技能名稱', 'empty skill')
t2, _ = m.add_template({'mode': 'draw_time', 'name': '場景創作', 'skills': {k: 1.0}, 'params': {'minutes': 60}})
check(m.delete_skill(k).startswith('仍有任務範本使用此技能'), 'skill in use')
m.delete_template(t2)
m.set_file_tags('場景.psd', [k, 'color']); m.settings['weekly_focus'] = k
check(m.delete_skill(k) is None and m.skill(k) is None, 'delete custom skill')
check(m.file_tags('場景.psd') == {'color': 1.0} and m.settings['weekly_focus'] == '', 'cleanup tags/focus')
check(m.delete_skill('color') == '內建技能無法刪除', 'builtin skill refused')
check(any(c['id'] == 'color' for c in G.skill_cards(m, NOW)), 'cards still fine')
done()
