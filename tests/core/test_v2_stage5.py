# -*- coding: utf-8 -*-
"""2.0 階段五核心：用到時才提醒（練習卡片、3 天後建議練習時間與開機啟動）、今天課表重排、
內建資料以 id 對應翻譯表（使用者改過的名稱不翻）"""
import os
import sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir  # noqa: E402

block_tk()
from core import (data_text as DT, daily_quests as DQ, diagnostics, growth, onboarding as OB, pet_builtin,  # noqa: E402
                  settings2, study_lessons, works)
from core.version import APP_VERSION  # noqa: E402

now = datetime(2026, 10, 23, 14, 0)

# ─── 使用天數與到期 ──
check(OB.days_used('2026-10-20T09:00:00', now) == 3 and OB.days_used('', now) == 0, 'days used')
s = settings2.Settings2(tmpdir())
s.set('first_run_at', '2026-10-22T09:00:00')
check(not OB.due_after_days(s, OB.KEY_TUNE, now), 'not due on day 1')
s.set('first_run_at', '2026-10-19T09:00:00')
check(OB.due_after_days(s, OB.KEY_TUNE, now), 'due after 3 days')
s.mark_prompted(OB.KEY_TUNE)
check(not OB.due_after_days(s, OB.KEY_TUNE, now), 'asked only once')

# ─── 建議每日練習時間 ──
hist = {'2026-10-20': 20 * 60, '2026-10-21': 15 * 60, '2026-10-22': 25 * 60, '2026-10-23': 0}
check(OB.suggest_budget(hist, 60, now, '2026-10-20T08:00:00') == 20, 'draws much less → suggest 20')
hist = {'2026-10-20': 130 * 60, '2026-10-21': 100 * 60, '2026-10-22': 110 * 60}
check(OB.suggest_budget(hist, 60, now, '2026-10-20T08:00:00') == 90, 'draws much more → suggest 90')
hist = {'2026-10-20': 50 * 60, '2026-10-21': 70 * 60, '2026-10-22': 55 * 60}
check(OB.suggest_budget(hist, 60, now, '2026-10-20T08:00:00') is None, 'close to target → nothing')
check(OB.suggest_budget(hist, 60, now, '2026-10-22T08:00:00') is None, 'too few days → nothing')
hist = {'2026-10-20': 0, '2026-10-21': 0, '2026-10-22': 0}
check(OB.suggest_budget(hist, 40, now, '2026-10-20T08:00:00') == 20, 'never draws → lowest choice')
check(OB.suggest_budget(hist, 20, now, '2026-10-20T08:00:00') is None, 'already lowest → nothing')

# ─── 練習卡片 + 今天課表重排 ──
qpath = os.path.join(tmpdir(), 'daily_quests.json')
q = DQ.QuestManager(qpath)
q.ensure_today(now)
check(OB.show_practice_card(s, q), 'card shown first time')
choices = OB.focus_choices(q)
check(choices[0] == ('', '平均練') and ('color', '色彩') in choices, 'focus choices')
regen = OB.apply_practice(q, 20, 'color', now)
check(regen and q.settings['budget_minutes'] == 20 and q.settings['weekly_focus'] == 'color', 'card applied, schedule redone')
check(q.today_tasks(), 'today still has a schedule')
reloaded = DQ.QuestManager(qpath)
check(reloaded.settings['budget_minutes'] == 20, 'saved')
t0 = q.today_tasks()[0]
t0['progress'] = 5
check(not q.regenerate_today(now), 'started today → keep schedule')
t0['progress'] = 0
q.settings['enabled'] = False
check(not q.regenerate_today(now), 'disabled → nothing')
q.settings['enabled'] = True
s.mark_prompted(OB.KEY_PRACTICE)
check(not OB.show_practice_card(s, q), 'card not shown again')

# ─── 內建資料翻譯 ──
check(DT.language() == 'zh_tw' and DT.skill_name({'id': 'color', 'name': '色彩'}) == '色彩', 'default zh: unchanged')
DT.load_table('en_us', {
    'skill': {'color': {'name': 'Color'}},
    'template': {'t_sk_pose': {'name': 'Gesture sketch'}},
    'mode': {'sketch': {'name': 'Timed sketch'}},
    'lesson': {'value_1': {'name': 'Three values', 'goal': 'Simplify into three values',
                           'phases': [{'name': 'Squint'}, {'name': 'Split', 'tip': 'Find the terminator'}, {}, {}],
                           'checks': ['only one item']}},
})
DT.set_language('en_us')
check(DT.skill_name({'id': 'color', 'name': '色彩'}) == 'Color', 'builtin skill translated')
check(DT.skill_name({'id': 'color', 'name': '配色'}) == '配色', 'renamed builtin keeps user text')
check(DT.skill_name({'id': 'u_bg', 'name': '背景'}) == '背景', 'user skill keeps user text')
check(DT.skill_name({'id': 'value', 'name': '明暗光影'}) == '明暗光影', 'missing translation → original')
check(DT.task_name({'template_id': 't_sk_pose', 'name': '姿勢速寫'}) == 'Gesture sketch', 'task name via template id')
check(DT.mode_name('sketch') == 'Timed sketch' and DT.mode_name('study') == '臨摹研究', 'mode names')
les = study_lessons.lesson('value_1')
check(les['name'] == 'Three values' and les['goal'] == 'Simplify into three values', 'lesson translated')
check(les['phases'][0]['name'] == 'Squint' and les['phases'][0]['tip'] == study_lessons.LESSON_BY_ID['value_1']['phases'][0]['tip'],
      'phase partly translated, rest original')
check(les['checks'] == study_lessons.LESSON_BY_ID['value_1']['checks'], 'list with wrong length ignored')
check(study_lessons.LESSON_BY_ID['value_1']['name'] == '三階明度', 'source data untouched')
check(study_lessons.path('value')[0]['name'] == 'Three values', 'path uses translations')
check(q.skill_label({'color': 1.0}) == 'Color', 'skill label translated')
cards = {c['id']: c['name'] for c in growth.skill_cards(q)}
check(cards['color'] == 'Color', 'growth cards translated')
miss = DT.coverage('en_us')
check('color' not in miss['skill'] and 'value' in miss['skill'] and 'value_1' not in miss['lesson'], 'coverage report')
DT.set_language('zh_tw')
check(study_lessons.lesson('value_1')['name'] == '三階明度', 'back to zh')

# ─── 程式圖示（墨墨）與半透明繪製 ──
ic = pet_builtin.icon(16)
check(ic.size == (16, 16) and ic.getpixel((0, 15))[3] == 0 and ic.getpixel((8, 10))[3] == 255, 'icon 16px: square, transparent corner')
check(pet_builtin.icon(256).getchannel('A').getbbox()[3] >= 250, 'icon fills the square (no shadow, no padding)')
ico = os.path.join(tmpdir(), 'a.ico')
pet_builtin.save_ico(ico)
from PIL import Image  # noqa: E402
check(sorted(Image.open(ico).ico.sizes()) == [(s_, s_) for s_ in pet_builtin.ICON_SIZES], 'multi-size ico')
f = pet_builtin.frame('idle', 0, 120)
check(f.getpixel((39, 46))[3] == 255 and f.getpixel((40, 78))[3] == 255, 'highlight and cheeks blend instead of punching holes')
# ─── 作品自動分組：使用者資料夾不以使用者名稱分組 ──
check(works.auto_group('本機磁碟 (D:) _ art _ x.psd') == 'art', 'drive: first folder')
check(works.auto_group('Artist _ Desktop _ 委託 _ x.psd') == '委託', 'user folder: skip name and Desktop')
check(works.auto_group('Artist _ Desktop _ x.psd') == '桌面', 'file right on desktop')
check(works.auto_group('Artist _ AppData _ Local _ Temp _ x.psd') == '暫存與程式資料', 'temp files')
check(works.auto_group('x.psd') == '根目錄', 'no folder')

# ─── 錯誤記錄與診斷資訊 ──
clean = tmpdir()
diagnostics.install(clean)
check(not diagnostics.has_log(clean), 'empty log file is not a log')
diagnostics.uninstall()
check(not os.path.exists(diagnostics.log_path(clean)), 'no empty log left after a clean exit')
import json  # noqa: E402
import threading  # noqa: E402
import zipfile  # noqa: E402
app = tmpdir()
old_stderr = sys.stderr
hooks_before = (sys.excepthook, threading.excepthook)
diagnostics.install(app)
sys.stderr = None                                  # 模擬打包後沒有主控台
try:
    raise ValueError('boom')
except ValueError:
    sys.excepthook(*sys.exc_info())
t = threading.Thread(target=lambda: 1 / 0, name='worker')
t.start()
t.join()
sys.stderr = old_stderr
diagnostics.uninstall()
log = open(diagnostics.log_path(app), encoding='utf-8').read()
check('Unhandled ValueError' in log and 'boom' in log and APP_VERSION in log, 'main-thread error logged')
check('ZeroDivisionError in thread worker' in log, 'thread error logged')
check((sys.excepthook, threading.excepthook) == hooks_before, 'hooks restored')
big = diagnostics.log_path(app)
open(big, 'a', encoding='utf-8').write('x' * (diagnostics.MAX_BYTES + 10))
diagnostics.write(app, 'after trim')
check(os.path.getsize(big) < diagnostics.MAX_BYTES and 'after trim' in open(big, encoding='utf-8').read(), 'log trimmed')
s2 = settings2.Settings2(app)
s2.set('sources.unsplash_key', 'SECRET123')
s2.set('sai2_exe', r'D:\Tools\sai2.exe')
z = diagnostics.export_bundle(s2, os.path.join(tmpdir(), 'diag.zip'), {'paused_for_1x': False})
with zipfile.ZipFile(z) as zf:
    names = set(zf.namelist())
    info = json.loads(zf.read('info.json'))
    body = zf.read('settings.json').decode('utf-8')
check(names == {'info.json', 'settings.json', diagnostics.LOG_NAME} and info['app_version'] == APP_VERSION, 'bundle contents')
check('SECRET123' not in body and 'sai2.exe' not in body, 'no keys or local paths in diagnostics')
done()
