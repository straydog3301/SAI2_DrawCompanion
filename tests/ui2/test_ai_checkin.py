# -*- coding: utf-8 -*-
"""課程打卡的 AI 評鑑（參考小窗）：等待 → 顯示分數與簡評、預選 AI 的分數、可以改分數（標示手動修改）、
AI 失敗時改用自評、等待中可以改用自評（晚到的結果不使用）、未開啟時照常自評；設定頁「AI 評鑑」。
AI 呼叫以假的函式代替，不連網"""
import os
import sys
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit  # noqa: E402

from core import ai_review as AR, companion, settings2  # noqa: E402
from ui2 import app as A, ref_window as RW, theme  # noqa: E402


def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.005)


def wait(cond, ms=4000):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


class FakeTracker:
    def __init__(self, *a, **k):
        pass

    def start(self): pass
    def stop(self): pass

    def get_state(self):
        return {'sai2_running': True, 'current_file': 'a.psd', 'raw_current_file': 'a.psd', 'session_draw': 0.0, 'files': {}}

    def get_draw_counter(self): return 0.0
    def today_draw_seconds(self): return 600.0
    def daily_history(self): return {}


REF = Image.new('RGB', (512, 625), (180, 150, 120))
RW.study_refs.fetch_reference = lambda lesson, settings, exclude=None, rng=None: (
    REF.copy(), {'id': f'fake:{len(exclude or ())}', 'title': '測試', 'artist': 'T', 'source': 'Fake', 'url': '', 'license': ''})
CANVAS = Image.new('RGB', (400, 300), (90, 120, 200))
RW.RefWindow._capture = lambda self: CANVAS.copy()

# 假的 AI：記錄收到的內容，依 behaviour 回傳結果、丟錯誤或延遲
calls = []
behaviour = {'mode': 'ok', 'score': 4}
gate = threading.Event()


def fake_review(cfg, lesson, work_img, ref_img=None, note='', pass_rating=3, opener=None):
    calls.append({'lesson': lesson['id'], 'work': work_img.size if work_img else None,
                  'ref': ref_img.size if ref_img else None, 'note': note, 'key': cfg.get('api_key')})
    if behaviour['mode'] == 'slow':
        gate.wait(5)
    if behaviour['mode'] == 'error':
        raise AR.ReviewError('超過使用額度（免費額度每天有上限），請稍後再試')
    sc = behaviour['score']
    return {'score': sc, 'summary': '明暗分組清楚', 'strengths': ['亮暗面積接近'], 'improve': ['中間調太多'],
            'provider': 'gemini', 'model': 'fake', 'passed': sc >= pass_rating}


AR.review = fake_review

qapp = QApplication(sys.argv[:1])
qapp.setStyleSheet(theme.QSS)
d = tmpdir()
s = settings2.Settings2(d)
s.set('prompted', {'welcome': True, 'legacy_watcher': True})
s.set('hotkeys', {k: '' for k in s.get('hotkeys')})
s.set('study.canvas_dir', os.path.join(d, 'canvas'))
s.set('ai_review', {'enabled': True, 'provider': 'gemini', 'api_key': 'test-key', 'model': 'fake', 'base_url': ''})
s.save()
ctl = A.CompanionApp(qapp, s)
ctl.service = companion.CompanionService(s, tracker_factory=FakeTracker, legacy_check=lambda: False)
said = []
ctl.say = lambda text, actions=(), important=True, seconds=6.0: said.append(text)
ctl.open_path = lambda p: None
ctl.focus_sai2 = lambda: True
ctl.start()
pump(200)
q = ctl.service.quests


def start_study(skill, index=0):
    q.path_state(skill)['index'] = index
    tid = next(t['id'] for t in q.data['templates'] if t.get('mode') == 'study' and t.get('params', {}).get('path') == skill)
    task = q.add_today(tid)
    w = ctl.open_ref('study', task['uid'])
    wait(lambda: w.base is not None)
    task['progress'], task['status'] = task['target'], 'ready'
    w.mode.checkin()
    pump(50)
    return task, w


def texts(w):
    pump(30)
    return ' '.join(lb.text() for lb in w.sheet.findChildren(QLabel) if lb.isVisible())


# ─── 1. AI 評分 → 預選分數 → 打卡推進 ──
task, w = start_study('value')
check(w.sheet.isVisible() and w.sheet.ai_mode and w.sheet.ok.text() == '完成打卡並請 AI 評分' and w.sheet.ok.isEnabled(),
      'AI mode: one button checks in and asks the AI')
check(not w.sheet.rating_box.isVisible(), 'self-rating hidden until the AI answers')
w.sheet.note.setText('暗部有點難')
w.sheet.ok.click()
check(wait(lambda: w.sheet.ai_result is not None), 'AI result arrives')
c = calls[-1]
check(c['lesson'] == 'value_1' and c['work'] == (400, 300) and c['ref'] == (512, 625) and c['note'] == '暗部有點難',
      f'lesson, canvas snapshot, cached reference and note sent ({c})')
pump(50)
check('AI 評分　4 分' in texts(w) and '明暗分組清楚' in texts(w) and '中間調太多' in texts(w), 'score and review shown')
check(w.sheet.rating == 4 and w.sheet.rating_box.isVisible() and w.sheet.ok.text() == '完成打卡', 'AI score preselected')
check(task['status'] == 'ready', 'not checked in until confirmed')
w.sheet.ok.click()
pump(100)
check(task['status'] == 'done' and task['rating'] == 4 and task['ai_review']['summary'] == '明暗分組清楚'
      and not task['ai_review']['overridden'] and task['advanced_to'] == 'value_2', 'checked in with the AI score, next lesson')

# ─── 2. 不同意：改分數 → 標示手動修改、不推進 ──
behaviour['score'] = 4
task, w = start_study('color')
w.sheet.ok.click()
wait(lambda: w.sheet.ai_result is not None)
w.sheet._pick(2)
check('手動修改' in w.sheet.hint.text(), 'changing the score is explained')
w.sheet.ok.click()
pump(100)
check(task['rating'] == 2 and task['ai_review']['overridden'] and task['ai_review']['score'] == 4 and not task['advanced_to'],
      'user score wins, record marked as changed')

# ─── 3. AI 失敗 → 改用自評 ──
behaviour['mode'] = 'error'
task, w = start_study('value', index=1)
w.sheet.ok.click()
check(wait(lambda: w.sheet.rating_box.isVisible()), 'falls back to self-rating')
check('額度' in texts(w) and '改用自評' in texts(w) and not w.sheet.ai_mode and not w.sheet.ok.isEnabled(),
      'error explained, must pick a score')
w.sheet._pick(3)
w.sheet.ok.click()
pump(100)
check(task['status'] == 'done' and task['rating'] == 3 and 'ai_review' not in task, 'self-rated check-in, no AI record')

# ─── 4. 等待中改用自評：晚到的結果不使用 ──
behaviour['mode'] = 'slow'
gate.clear()
task, w = start_study('value', index=2)
w.sheet.ok.click()
pump(50)
check(any('AI 評鑑中' in lb.text() for lb in w.sheet.findChildren(QLabel)) and w.sheet.back.text() == '改用自評',
      'waiting state with a way out')
w.sheet.back.click()
check(w.sheet.rating_box.isVisible() and not w.sheet.ai_mode, 'switched to self-rating')
gate.set()
pump(300)
check(w.sheet.ai_result is None and w.sheet.rating is None, 'late AI result ignored')
w.sheet._pick(5)
w.sheet.ok.click()
pump(100)
check(task['rating'] == 5 and 'ai_review' not in task, 'self-rated')

# ─── 5. 關閉 AI 評鑑：照常自評 ──
behaviour['mode'] = 'ok'
s.set('ai_review.enabled', False)
n = len(calls)
task, w = start_study('color', index=1)
check(not w.sheet.ai_mode and w.sheet.rating_box.isVisible() and not w.sheet.ok.isEnabled(), 'AI off → self-rating as before')
w.sheet._pick(3)
w.sheet.ok.click()
pump(100)
check(task['status'] == 'done' and len(calls) == n, 'no AI call')

# ─── 設定頁 ──
ctl.open_main('AI 評鑑')
pump(300)
page = ctl._main.pages['AI 評鑑']
eds = [e for e in page.findChildren(QLineEdit) if e.isVisible()]
check(any(e.echoMode() == QLineEdit.PasswordEchoOnEdit and e.text() == 'test-key' for e in eds), 'key field hidden')
combo = next(cb for cb in page.findChildren(QComboBox) if cb.findData('openai') >= 0)
base = next(e for e in page.findChildren(QLineEdit) if 'localhost:11434' in e.placeholderText())
check(not base.isVisible(), 'service URL hidden for Gemini')
combo.setCurrentIndex(combo.findData('openai'))
pump(50)
check(base.isVisible() and s.get('ai_review.provider') == 'openai', 'OpenAI-compatible shows the URL field')
check(any('隱私' in lb.text() or '傳送給你選擇的 AI 服務' in lb.text() for lb in page.findChildren(QLabel)), 'privacy note')

ctl._main.close()
ctl.quit()
A.release_widgets(qapp)
done()
